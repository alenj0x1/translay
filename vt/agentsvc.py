"""El agente dentro de la app: elegir el motor y el modelo según el equipo, tenerlo cargado mientras
se usa y conversar sobre cada video (vt/agent.py arma lo que lee; vt/llm.py corre el modelo).

Plan según el equipo (PLANS, medido en tools/lab/agent.py):
  gpu    NVIDIA con VRAM libre: build Vulkan (liviano, rinde como CUDA) y el video entero
  igpu   gráfica integrada Intel o AMD por Vulkan: modelo mediano, video entero hasta ~10.000 tokens
  cpu    sin GPU: modelo chico según la RAM, el video por fragmentos
Si la NVIDIA está ocupada (doblando un video, sin VRAM libre), usa la integrada o la CPU.

Una pregunta a la vez. El modelo queda cargado mientras se usa (así la segunda pregunta sobre el mismo
video reutiliza lo ya leído: responde en décimas de segundo) y se cierra tras IDLE_S sin preguntas.

La conversación de cada video se guarda en transcripts/<video>.agent.json.
Mensajes a las pestañas (bg del video): agent_state {state, pct, detail} · agent_delta {id, text} ·
agent_done {id, text, stats, stopped, cont} · agent_error {id, error}.
Detener (agent_stop) deja lo escrito hasta ahí; «Continuar» (agent_continue) sigue esa misma respuesta.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from . import agent, hardware, i18n, llm
from . import diag

IDLE_S = 300
DESCRIBE_MODEL = "qwen3.5-0.8b"  # la descripción corta: el más chico basta (~0,5 GB, unos segundos)
HISTORY = 60   # mensajes que se guardan por video
# plan → (build, modelo por defecto, presupuesto de tokens del video, contexto del servidor)
# Elegidos con tools/lab/agent.py (43 preguntas en 3 videos, RTX 4060 y UHD 730, 2026-11-14):
#   qwen3.5-4b 1.00 de calidad a 63 t/s · gemma4-e2b 0.98 a 106 t/s con la mitad de memoria ·
#   en la integrada qwen3.5-0.8b 0.95 a 15 t/s (qwen3.5-2b 0.93 a 10 t/s; lfm2.5 falla las trampas).
PLANS = {
    "gpu-big": ("vulkan", "qwen3.5-4b", 24000, 32768),  # 7 GB de VRAM libre o más
    "gpu": ("vulkan", "gemma4-e2b", 24000, 32768),      # 3,5 a 7 GB
    "igpu": ("vulkan", "qwen3.5-0.8b", 6000, 8192),     # la integrada lee ~150 t/s: video más corto
    "cpu-big": ("cpu", "qwen3.5-2b", 5000, 8192),       # 12 GB de RAM o más
    "cpu": ("cpu", "qwen3.5-0.8b", 3000, 4096),         # 6 a 12 GB
    "cpu-tiny": ("cpu", "qwen3.5-0.8b", 2000, 3072),    # menos de 6 GB (~1,9 GB en uso)
}


# calidad en el laboratorio (tools/lab/agent.py, RTX 4060, 33 preguntas con su momento) y si responde con
# honestidad las preguntas trampa (los que inventan no se recomiendan)
QUALITY = {
    "lfm2.5-350m": (0.63, False), "qwen3-0.6b": (0.72, False), "qwen3.5-0.8b": (0.91, True), "gemma3-1b": (0.56, False),
    "lfm2.5-1.2b": (0.81, True), "granite4-1b": (0.79, False), "llama3.2-1b": (0.73, False), "qwen3-1.7b": (0.81, True),
    "qwen3.5-2b": (0.96, True), "smollm3-3b": (0.87, False), "granite4-micro": (0.91, True), "llama3.2-3b": (0.89, True),
    "gemma4-e2b": (0.98, True), "qwen3-4b": (0.97, True), "qwen3.5-4b": (1.00, True), "phi4-mini": (0.87, True),
    "gemma4-e4b": (0.98, True), "qwen3.5-9b": (1.00, True),
}


def reason(e: Exception) -> str:
    s = str(e).lower()
    if "connection" in s or "urlopen" in s or "resolve" in s:
        return i18n.t("No se pudo descargar el modelo del agente. Revisa la conexión a internet.")
    if "sha-256" in s:
        return i18n.t("La descarga del motor no superó la verificación y se descartó por seguridad.")
    if "memory" in s or "terminó al cargar" in s:
        return i18n.t("Memoria insuficiente para el modelo. Elige uno más ligero en Ajustes › Agente.")
    return i18n.t("El agente no pudo responder.")


class AgentService:
    def __init__(self, root: Path, vaults, prefs, notify, screen=None, hw=lambda: {}):
        self.root, self.vaults, self.prefs, self.notify, self.screen, self.hw = root, vaults, prefs, notify, screen, hw
        self.server: llm.Server | None = None
        self.key = None             # (build, device, modelo, contexto) del servidor cargado
        self.plan = None
        self.state = {"state": "listo", "pct": 0, "detail": ""}
        self.last = 0.0
        self.cancel = threading.Event()
        self.lock = threading.RLock()  # una pregunta y un resumen no usan el modelo a la vez
        self.off = False               # apagado a mano: no se carga hasta que se pida algo
        self.downloading: dict[str, int] = {}  # modelos bajando desde Ajustes: clave → %
        self._q: queue.Queue = queue.Queue()
        self._dq: queue.Queue = queue.Queue()  # descripciones cortas pendientes (de a una, en segundo plano)
        self._describing: set[str] = set()
        threading.Thread(target=self._loop, daemon=True, name="agente").start()
        threading.Thread(target=self._describe_loop, daemon=True, name="agente-descripcion").start()
        threading.Thread(target=self._idle, daemon=True, name="agente-reposo").start()
        import atexit

        atexit.register(self.unload)  # el servidor del modelo no queda corriendo al cerrar Translay

    # ------------------------------------------------------------- plan
    def choose(self, hw: dict | None = None, auto: bool = False) -> dict:
        """Qué motor, GPU y modelo usar ahora (Ajustes › Agente puede fijar el modelo o el lugar).
        auto: el que elegiría «Automático», aunque haya uno fijado."""
        hw = hw or self.hw() or hardware.detect()
        ram = ((hw.get("ram") or {}).get("limit_mb") or (hw.get("ram") or {}).get("total_mb") or 8192)
        where = self.prefs.values.get("agent_device", "auto")
        gpu = hw.get("gpu") or {}
        plan = None
        vram = gpu.get("vram_free_mb") or 0
        if where in ("auto", "gpu") and gpu and vram >= 3500:
            plan = "gpu-big" if vram >= 7000 else "gpu"
        if plan is None and where in ("auto", "igpu", "gpu"):
            exe = llm.build_dir(self.root, "vulkan") / "llama-server.exe"
            igpus = [d for d in llm.devices(exe) if d.get("integrated")] if exe.exists() else []
            if igpus or where == "igpu":
                plan = "igpu"
        if plan is None:
            plan = "cpu-big" if ram >= 12_000 else "cpu" if ram >= 6_000 else "cpu-tiny"
        build, model, budget, ctx = PLANS[plan]
        chosen = self.prefs.values.get("agent_model", "auto")
        if chosen in llm.MODELS and not auto:
            model = chosen
        usable = (hw.get("cpu") or {}).get("usable_threads") or 4
        # en la CPU, «Uso del equipo» elige los núcleos (50 % = la mitad, como antes); nunca todos
        threads = max(1, min(usable - 1, round(usable * self.usage() / 100))) if build == "cpu" else max(1, usable // 2)
        return {"plan": plan, "build": build, "model": model, "budget": budget, "ctx": ctx, "threads": threads,
                "gpu_layers": 0 if build == "cpu" else 99}

    def usage(self) -> int:
        """Ajustes › Agente › Uso del equipo (25–100 %)."""
        try:
            return max(25, min(100, int(self.prefs.values.get("agent_usage", 50))))
        except (TypeError, ValueError):
            return 50

    def _paced(self, srv: llm.Server, cancelled=lambda: False):
        """El servidor para lo que el agente hace solo: tras cada pedido descansa en proporción a lo que tardó
        (al 50 %, lo mismo que trabajó), así la GPU y la CPU quedan libres para los otros programas la otra
        parte del tiempo. Medido en tools/lab/footprint.py: lo que traba el escritorio es la lectura del
        prompt en la GPU, y ninguna perilla de llama.cpp (prioridad, tandas, hilos) la suavizó; lo que sí se
        controla es cuánto tiempo seguido trabaja."""
        svc = self

        class Paced:
            def __getattr__(self, name):
                return getattr(srv, name)

            def chat(self, *a, **kw):
                t0 = time.perf_counter()
                try:
                    return srv.chat(*a, **kw)
                finally:
                    u = svc.usage()
                    rest = min(60.0, (time.perf_counter() - t0) * (100 - u) / u)
                    end = time.perf_counter() + rest
                    while time.perf_counter() < end and not cancelled() and svc._q.empty():  # una pregunta no espera
                        time.sleep(0.1)
        return Paced()

    def catalog(self) -> dict:
        """Para elegir el modelo en Ajustes: cuál usaría «Automático» en este equipo, y de cada modelo cuánto
        pesa, qué tal le fue en el laboratorio y si entra donde va a correr (VRAM libre o RAM)."""
        hw = self.hw() or hardware.detect()
        plan = self.choose(hw, auto=True)
        ram = ((hw.get("ram") or {}).get("limit_mb") or (hw.get("ram") or {}).get("total_mb") or 8192)
        if plan["build"] == "cpu" or plan["plan"] == "igpu":
            room = ram * 0.45                                  # la RAM se comparte con todo lo demás
        else:
            room = (hw.get("gpu") or {}).get("vram_free_mb") or 0
        out = []
        for k, m in llm.MODELS.items():
            q, honest = QUALITY.get(k, (None, True))
            need = m.gb * 1024 + (1500 if plan["ctx"] >= 16384 else 600)  # pesos + lo que lee del video
            out.append({"key": k, "name": m.name, "gb": m.gb, "quality": q, "honest": honest,
                        "fits": need <= room, "slow": plan["build"] == "cpu" and m.gb > 2.2,
                        "downloaded": llm.model_file(k, download=False) is not None,
                        "downloading": self.downloading.get(k)})
        return {"recommended": plan["model"], "place": plan["plan"], "models": out}

    # ------------------------------------------------------------- estado
    def _set(self, vid: str | None, **kw):
        self.state.update(kw)
        if vid:
            self.notify({"type": "bg", "video": vid, "msg": {"type": "agent_state", **self.state}})

    def _path(self, vid: str) -> Path:
        v = self.vaults.of(vid)
        return v.store.open(vid).path.with_name(f"{vid}.agent.json")

    def history(self, vid: str) -> list[dict]:
        try:
            p = self._path(vid)
            return json.loads(p.read_text(encoding="utf-8")).get("messages", []) if p.exists() else []
        except (OSError, ValueError, AttributeError):
            return []

    def _save(self, vid: str, msgs: list[dict]):
        p = self._path(vid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"messages": msgs[-HISTORY:]}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def clear(self, vid: str):
        self._path(vid).unlink(missing_ok=True)

    def public(self, vid: str, position: float | None = None) -> dict:
        v = self.vaults.of(vid)
        info = v.library.data["videos"].get(vid) or {} if v else {}
        tr = v.store.open(vid) if v else None
        screen = self.screen.load(vid) if self.screen else None
        out = agent.suggestions(info, tr, screen, position) if tr else []
        # las del resumen (las escribió el modelo para este video): sirven aunque el agente esté apagado
        made = [{"q": q} for q in ((tr.data.get("summary") or {}).get("suggestions") or [])] if tr else []
        lead = [s for s in out if s.get("action")]
        rest = made + [s for s in out if not s.get("action")]
        plan = self.plan or {}
        return {"messages": self.history(vid), "state": self.state, "suggestions": (lead + rest)[:5],
                "power": self.power_state(), "model": llm.MODELS[plan["model"]].name if plan.get("model") in llm.MODELS else ""}

    # ------------------------------------------------------------- preguntas
    def ask(self, vid: str, question: str, position: float | None, qid: str, cont: bool = False):
        """cont: seguir la última respuesta detenida desde donde quedó (la pregunta es la de esa respuesta)."""
        self.cancel.clear()
        self._q.put((vid, question.strip()[:2000], position, qid, cont))

    def stop(self):
        self.cancel.set()

    def _loop(self):
        while True:
            vid, q, pos, qid, cont = self._q.get()
            try:
                with self.lock:
                    if q is None:
                        self._warm(vid, pos)  # «Encender»: cargar el modelo y leer el video de antemano
                    else:
                        self._answer(vid, q, pos, qid, cont)
            except Exception as e:  # noqa: BLE001
                
                diag.exception("agente.resumen")
                self.notify({"type": "bg", "video": vid, "msg": {"type": "agent_error", "id": qid, "error": reason(e)}})
                self._set(vid, state="listo", pct=0, detail="")

    def _ensure(self, vid: str, plan: dict) -> llm.Server:
        device = None
        if plan["plan"] in ("gpu-big", "gpu", "igpu"):
            exe = llm.ensure(plan["build"], self.root, lambda d, t: self._set(vid, state="descargando", pct=int(d * 100 / t),
                                                                                 detail=i18n.t("el motor del agente")))
            devs = llm.devices(exe)
            want = [d for d in devs if d["integrated"] == (plan["plan"] == "igpu")]
            device = (want or devs or [{"id": None}])[0]["id"]
        key = (plan["build"], device, plan["model"], plan["ctx"], plan["threads"])
        if self.server and self.key == key and self.server.proc and self.server.proc.poll() is None:
            return self.server
        self.unload()
        exe = llm.ensure(plan["build"], self.root, lambda d, t: self._set(vid, state="descargando", pct=int(d * 100 / t),
                                                                             detail=i18n.t("el motor del agente")))
        if llm.model_file(plan["model"], download=False) is None:
            self._fetch(plan["model"], lambda pct: self._set(vid, state="descargando", pct=pct,
                                                            detail=llm.MODELS[plan["model"]].name))
        self._set(vid, state="cargando", pct=0, detail=llm.MODELS[plan["model"]].name)
        self.off = False
        srv = llm.Server(exe, llm.model_file(plan["model"]), ctx=plan["ctx"], threads=plan["threads"],
                         gpu_layers=plan["gpu_layers"], device=device, low_priority=plan["build"] == "cpu")
        srv.start()
        self.server, self.key, self.plan = srv, key, plan
        self._power()
        return srv

    # ------------------------------------------------------------- descargas
    def _fetch(self, key: str, on_pct):
        """Baja un modelo (fijado por revisión en vt/llm.py) avisando el avance en %, cada segundo."""
        from .modelset import _byte_counter

        bar, got = _byte_counter()
        total = int(llm.MODELS[key].gb * 1e9)
        done = threading.Event()

        def watch():
            while not done.wait(1):
                on_pct(min(99, int(got() * 100 / total)))
        threading.Thread(target=watch, daemon=True).start()
        try:
            llm.model_file(key, tqdm_class=bar)
        finally:
            done.set()

    def download(self, key: str):
        """Ajustes › Agente › Modelo › «Descargar»: baja el modelo de antemano (en segundo plano), así la
        primera pregunta no espera. Avisa a todas las pestañas con agent_model_dl {key, state, pct}."""
        if key not in llm.MODELS or key in self.downloading or llm.model_file(key, download=False):
            return
        self.downloading[key] = 0

        def run():
            def pct(n):
                self.downloading[key] = n
                self.notify({"type": "agent_model_dl", "key": key, "state": "descargando", "pct": n})
            try:
                pct(0)
                self._fetch(key, pct)
                self.notify({"type": "agent_model_dl", "key": key, "state": "listo", "pct": 100})
            except Exception as e:
                self.notify({"type": "agent_model_dl", "key": key, "state": "error", "error": reason(e)})
            finally:
                self.downloading.pop(key, None)
        threading.Thread(target=run, daemon=True, name="agente-descarga").start()

    # ------------------------------------------------------------- encendido y apagado
    def power(self, on: bool, vid: str | None = None, position: float | None = None):
        """Encender (carga el modelo y lee el video de antemano: la primera pregunta sale al instante) o
        apagar (el modelo deja la memoria ya)."""
        if on:
            self.off = False
            if vid:
                self._q.put((vid, None, position, "", False))
        else:
            self.off = True
            self.cancel.set()
            with self.lock:
                self.unload()
            self._power()

    def power_state(self) -> str:
        if self.state.get("state") in ("descargando", "cargando", "pensando", "buscando", "leyendo", "escribiendo", "resumiendo"):
            return "ocupado"
        return "encendido" if self.server and self.server.proc and self.server.proc.poll() is None else "apagado"

    def _power(self):
        plan = self.plan or {}
        self.notify({"type": "agent_power", "state": self.power_state(), "model": llm.MODELS[plan["model"]].name
                     if plan.get("model") in llm.MODELS else "", "plan": plan.get("plan", "")})

    def _warm(self, vid: str, position: float | None):
        v = self.vaults.of(vid)
        if not v:
            return
        plan = self.choose()
        srv = self._ensure(vid, plan)
        info = v.library.data["videos"].get(vid) or {}
        tr = v.store.open(vid)
        screen = self.screen.load(vid) if self.screen else None
        msgs, _ = agent.messages(info, tr, screen, "Hola", [], position, plan["budget"],
                                 name=self.prefs.values.get("agent_name", ""), tone=self.prefs.values.get("agent_tone", ""))
        self._set(vid, state="pensando", detail="")
        srv.chat(msgs[:1] + [{"role": "user", "content": "Responde solo: listo"}], max_tokens=1,
                 chat_template_kwargs={"enable_thinking": False})
        self.last = time.time()
        self._set(vid, state="listo", pct=0, detail="")
        self._power()

    # ------------------------------------------------------------- resumen (vt/digest.py)
    def summarize(self, vid: str, progress=None, cancelled=lambda: False) -> dict | None:
        """El resumen completo con el modelo del agente (vt/summaries.py lo pide desde su cola)."""
        from . import digest

        v = self.vaults.of(vid)
        with self.lock:
            plan = self.choose()
            srv = self._ensure(vid, plan)
            self._set(vid, state="resumiendo", pct=0, detail="")
            info = v.library.data["videos"].get(vid) or {}
            tr = v.store.open(vid)
            screen = self.screen.load(vid) if self.screen else None
            try:
                return digest.summarize(self._paced(srv, cancelled), info, tr, screen, plan["budget"], progress, cancelled,
                                        model=llm.MODELS[plan["model"]].name)
            finally:
                self.last = time.time()
                self._set(vid, state="listo", pct=0, detail="")
                self._power()

    def _answer(self, vid: str, question: str, position: float | None, qid: str, cont: bool = False):
        v = self.vaults.of(vid)
        if not v:
            return
        prefix = ""  # «Continuar»: lo ya escrito de la respuesta detenida; el modelo sigue desde ahí
        if cont:
            hist0 = self.history(vid)
            if len(hist0) < 2 or not hist0[-1].get("stopped") or hist0[-2]["role"] != "user":
                return
            question, prefix = hist0[-2]["content"], hist0[-1].get("raw", "")
            position = hist0[-2].get("position", position)
        if not question:
            return
        info = v.library.data["videos"].get(vid) or {}
        tr = v.store.open(vid)
        screen = self.screen.load(vid) if self.screen else None
        hist = self.history(vid)
        # acciones (exportar, ir a, subtítulos, guardar, avisos): al instante, sin el modelo (vt/agentintents.py)
        from . import agentintents

        act = None if cont else agentintents.route(question, info, tr, screen, position)
        if act:
            hist.append({"role": "user", "content": question, "t": time.time(), "position": position})
            hist.append({"role": "assistant", "content": act["text"], "t": time.time(), "card": act.get("card"),
                         "action": act.get("action"), "model": "acción"})
            self._save(vid, hist)
            self.notify({"type": "bg", "video": vid, "msg": {"type": "agent_done", "id": qid, "text": act["text"],
                                                             "card": act.get("card"), "action": act.get("action")}})
            self._set(vid, state="listo", pct=0, detail="")
            return
        plan = self.choose()
        srv = self._ensure(vid, plan)
        self._set(vid, state="pensando", pct=0, detail="")
        name = self.prefs.values.get("agent_name", "") or agent.DEFAULT_NAME
        # las detenidas no van al modelo (ni su pregunta): una respuesta a medias lo confunde, y algunas
        # plantillas (Gemma) exigen que usuario y agente se alternen
        keep = [h for i, h in enumerate(hist) if not h.get("stopped")
                and not (h["role"] == "user" and i + 1 < len(hist) and hist[i + 1].get("stopped"))]
        msgs, mode = agent.messages(info, tr, screen, question, [{"role": h["role"], "content": h["content"]} for h in keep],
                                    position, plan["budget"], name=name, tone=self.prefs.values.get("agent_tone", ""))
        # lo que está haciendo, paso a paso (la vista los muestra mientras espera)
        if mode == "fragmentos":
            self._set(vid, state="buscando", detail="")
        self._set(vid, state="leyendo", detail=i18n.t("{n} mil palabras", n=agent.tokens_estimate(msgs[0]['content']) // 1000 or 1)
                  if agent.tokens_estimate(msgs[0]["content"]) >= 1000 else "")
        if cont:
            hist.pop()  # la detenida: la reemplaza la completa (lo de antes + lo nuevo)
            if prefix.strip():  # llama-server sigue el último mensaje del agente (vacío: responde de cero)
                msgs = msgs + [{"role": "assistant", "content": prefix}]
        else:
            hist.append({"role": "user", "content": question, "t": time.time(), "position": position})
        first = [True]

        def delta(piece: str):
            if first[0]:
                first[0] = False
                self._set(vid, state="escribiendo", detail="")
            self.notify({"type": "bg", "video": vid, "msg": {"type": "agent_delta", "id": qid, "text": piece}})
        if self.cancel.is_set():  # lo detuvo mientras cargaba el modelo: no empieza
            r = {"text": "", "stopped": True, "total_s": 0}
        else:
            r = srv.chat(msgs, max_tokens=900, temperature=0.3, on_text=delta, stop_flag=self.cancel.is_set,
                         chat_template_kwargs={"enable_thinking": False})
        # citas propias: cada frase con el momento del video que más se le parece (los modelos chicos casi
        # nunca escriben las horas; medido en tools/lab/agent.py: de 0–3 % a 66–93 % de citas correctas)
        raw = prefix + r["text"]
        text = agent.cite(agent.clean(raw), tr, screen) if raw.strip() else ""
        stopped = bool(r.get("stopped"))
        # detenida: queda lo escrito hasta ahí, y el texto tal cual salió (raw) para poder continuarla
        hist.append({"role": "assistant", "content": text, "t": time.time(), "model": plan["model"], "mode": mode,
                     "s": round(r.get("total_s") or 0, 1), **({"stopped": True, "raw": raw} if stopped else {})})
        self._save(vid, hist)
        self.last = time.time()
        stats = {k: r.get(k) for k in ("ttft_s", "total_s", "prompt_n", "cached_n", "gen_tps")}
        self.notify({"type": "bg", "video": vid, "msg": {"type": "agent_done", "id": qid, "text": text, "stopped": stopped, "cont": cont,
                                                         "stats": dict(stats, model=llm.MODELS[plan["model"]].name,
                                                                       plan=plan["plan"], mode=mode)}})
        self._set(vid, state="listo", pct=0, detail="")
        self._power()

    # ------------------------------------------------------------- descripción corta
    def describe(self, vid: str):
        """La descripción bajo el título del video: al terminar de procesarlo y al abrir uno que no la tiene.
        Con el resumen hecho, son sus primeras frases; si no, la escribe el modelo más chico (o el que ya esté
        cargado) leyendo la traducción. Llega a las pestañas como video_description {video, text}."""
        if vid and vid not in self._describing:
            self._describing.add(vid)
            self._dq.put(vid)

    def _describe_loop(self):
        while True:
            vid = self._dq.get()
            try:
                self._describe(vid)
            except Exception:  # noqa: BLE001 (sin descripción no pasa nada: se intenta al volver a abrirlo)
                diag.exception("agente.descripcion")
            finally:
                self._describing.discard(vid)

    def _describe(self, vid: str):
        v = self.vaults.of(vid)
        info = (v.library.data["videos"].get(vid) or {}) if v else {}
        if not v or info.get("description"):
            return
        tr = v.store.open(vid)
        if not tr or not any((s.get("translation") or s.get("text")) for s in tr.segments):
            return
        overview = ((tr.data.get("summary") or {}).get("overview") or "").strip()
        if overview:
            text = agent.first_sentences(overview)
        else:
            with self.lock:  # no al mismo tiempo que una respuesta
                srv, temp = self._small_server()
                try:
                    r = srv.chat(agent.describe_messages(info, tr), max_tokens=160, temperature=0.3,
                                 chat_template_kwargs={"enable_thinking": False})
                finally:
                    if temp:  # lo cargó solo para esto: deja la memoria enseguida
                        temp.stop()
            text = agent.clean_description(r["text"])
        if len(text) < 20:
            return
        v.library.set_field(vid, description=text)
        self.notify({"type": "video_description", "video": vid, "text": text})

    def _small_server(self) -> tuple[llm.Server, llm.Server | None]:
        """El cargado si hay uno (no vale la pena cambiarlo); si no, el modelo más chico, solo para esto."""
        if self.server and self.server.proc and self.server.proc.poll() is None:
            return self.server, None
        plan = self.choose()
        exe = llm.ensure(plan["build"], self.root, lambda d, t: None)
        device = None
        if plan["plan"] in ("gpu-big", "gpu", "igpu"):
            devs = llm.devices(exe)
            want = [d for d in devs if d["integrated"] == (plan["plan"] == "igpu")]
            device = (want or devs or [{"id": None}])[0]["id"]
        srv = llm.Server(exe, llm.model_file(DESCRIBE_MODEL), ctx=8192, threads=plan["threads"],
                         gpu_layers=plan["gpu_layers"], device=device)
        srv.start()
        return srv, srv

    # ------------------------------------------------------------- reposo
    def unload(self):
        if self.server:
            self.server.stop()
        self.server, self.key = None, None

    def _idle(self):
        while True:
            time.sleep(15)
            if self.server and self.last and time.time() - self.last > IDLE_S and self._q.empty():
                with self.lock:
                    self.unload()  # en reposo: sin preguntas, el modelo deja la memoria (VRAM o RAM)
                self._power()

    def in_use(self) -> set[str]:
        """Los que Almacenamiento no debe borrar: el cargado, el que usó la última vez (aunque esté apagado o
        en reposo) y el fijado en Ajustes; si no, «liberar los que no se usan» lo borraría y la próxima
        pregunta lo volvería a bajar."""
        keys = {self.key[2]} if self.key else set()
        if self.plan:
            keys.add(self.plan["model"])
        fixed = self.prefs.values.get("agent_model", "auto")
        if fixed in llm.MODELS:
            keys.add(fixed)
        return {llm.MODELS[k].repo for k in keys if k in llm.MODELS}
