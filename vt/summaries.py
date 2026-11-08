"""Cola del resumen: resume los videos de a uno, en segundo plano (vt/summarize.py).

Se pide desde la vista («Resumir»), la API o al exportar el resumen; con la preferencia
«Resumir al procesar» en automático, cada video que termina la cola entra solo.

El modelo es el de Preferencias › Resumen o, en automático, el que recomienda el equipo
(`summarize.recommend`). Corre en la GPU si cabe en ella; si en ese momento no hay memoria
libre, la toma para sí (`Resources.exclusive`) y devuelve los otros modelos al terminar.
Si no entra en la GPU, corre en la CPU con la mitad de los hilos. La primera vez se
descarga, con su avance.

Estado de cada video: «en cola», «descargando», «resumiendo» o «error», con `pct`.
"""

import threading
import time

from . import events, hardware, modelset, summarize


def reason(e: Exception) -> str:
    s = str(e)
    if "out of memory" in s.lower() or "CUDA failed" in s:
        return "No hubo memoria suficiente para el modelo de resumen: elige uno más liviano en Preferencias."
    if "Connection" in type(e).__name__ or "HTTP" in s or "resolve" in s.lower():
        return "No se pudo descargar el modelo de resumen: revisa la conexión a internet."
    return "No se pudo resumir este video."


class Summaries:
    def __init__(self, store, library, res, prefs, notify, hw=lambda: {}, limits=lambda: {},
                 device: str = "cuda", vaults=None, threads: int = 0):
        self.store, self.library, self.res, self.prefs, self.notify = store, library, res, prefs, notify
        self.hw, self.limits, self.device, self.vaults, self.threads = hw, limits, device, vaults, threads
        self.jobs: dict[str, dict] = {}  # video → {state, pct, error}
        self._order: list[str] = []
        self._cond = threading.Condition()
        self._model: summarize.Summarizer | None = None
        threading.Thread(target=self._loop, daemon=True, name="resumen").start()

    # ------------------------------------------------------------------ API
    def model_key(self) -> str:
        key = self.prefs.values.get("summary_model", "auto")
        return key if key in summarize.MODELS else summarize.recommend(self.hw(), self.limits())

    def request(self, vid: str, force: bool = False) -> bool:
        """Pone un video en la cola del resumen. force: rehacerlo aunque ya tenga."""
        tr = self.store.open(vid)
        if not tr.segments:
            return False
        if tr.data.get("summary") and not force:
            return False
        with self._cond:
            if vid in self.jobs and self.jobs[vid]["state"] != "error":
                return True
            self.jobs[vid] = {"state": "en cola", "pct": 0, "error": "", "force": force}
            self._order.append(vid)
            self._cond.notify_all()
        self._send(vid)
        return True

    def auto(self, vid: str):
        """Un video terminó de procesarse: con el resumen automático, entra a la cola."""
        if self.prefs.values.get("summary_mode") == "auto":
            try:
                self.request(vid)
            except ValueError:
                pass

    def cancel(self, vid: str):
        with self._cond:
            j = self.jobs.get(vid)
            if j and j["state"] in ("en cola", "descargando", "resumiendo"):
                j["cancel"] = True
                if vid in self._order:
                    self._order.remove(vid)
                    self.jobs.pop(vid, None)
        self._send(vid)

    def state(self, vid: str) -> dict | None:
        j = self.jobs.get(vid)
        return {k: j[k] for k in ("state", "pct", "error")} if j else None

    def error(self, vid: str) -> str:
        j = self.jobs.get(vid)
        return j["error"] if j and j["state"] == "error" else ""

    # ---------------------------------------------------------------- bucle
    def _send(self, vid: str, summary: dict | None = None):
        msg = {"type": "summary_state", "state": self.state(vid)}
        if summary is not None:
            msg = {"type": "summary", "summary": summary, "state": None}
        self.notify({"type": "bg", "video": vid, "msg": msg})

    def _loop(self):
        while True:
            with self._cond:
                while not self._order:
                    # sin nada que resumir: el modelo no se queda ocupando memoria más de un minuto
                    if not self._cond.wait(timeout=60 if self._model else None) and self._model and not self._order:
                        self._model.unload()
                        self._model = None
                vid = self._order.pop(0)
                job = self.jobs.get(vid)
            if job is None:
                continue
            try:
                self._run(vid, job)
            except Exception as e:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                job.update(state="error", error=reason(e))
                self._send(vid)
                events.emit("resumen.error", self._vault(vid), video=vid, error=job["error"])

    def _vault(self, vid):
        v = self.vaults.of(vid) if self.vaults else None
        return v.id if v else None

    def _summarizer(self) -> summarize.Summarizer:
        key = self.model_key()
        m = summarize.MODELS[key]
        gpu = (self.hw().get("gpu") or {}) if self.device == "cuda" else {}
        device = "cuda" if (gpu.get("vram_total_mb") or 0) >= m.vram_mb + summarize.MARGIN_MB else "cpu"
        if self._model is None or self._model.key != key or self._model.device != device:
            if self._model is not None:
                self._model.unload()
            self._model = summarize.Summarizer(key, device, threads=self.threads)
        return self._model

    def _download(self, s: summarize.Summarizer, vid: str, job: dict):
        """La primera vez: el modelo se baja con su avance (el tamaño de la carpeta)."""
        if s.model_dir(download=False) is not None:
            return
        job.update(state="descargando", pct=0)
        self._send(vid)
        repo, total = s.model.repo, modelset.size(s.model.repo)
        done = threading.Event()

        def watch():
            while not done.wait(1):
                job["pct"] = min(99, int(modelset._dir_size(modelset.path(repo)) * 100 / total))
                self._send(vid)
        threading.Thread(target=watch, daemon=True).start()
        try:
            s.model_dir(download=True)
        finally:
            done.set()

    def _run(self, vid: str, job: dict):
        s = self._summarizer()
        self._download(s, vid, job)
        tr = self.store.open(vid)
        v = self.library.data["videos"].get(vid) or {}
        job.update(state="resumiendo", pct=0)
        self._send(vid)
        segments = [dict(x) for x in tr.segments]

        def progress(done, total):
            job["pct"] = int(done * 100 / total)
            self._send(vid)

        def work():
            return s.summarize(segments, tr.lang or "en", v.get("title") or "", progress,
                               cancelled=lambda: job.get("cancel", False))

        if s.device == "cuda":
            def free():
                g = hardware._nvidia_smi()
                return g[0]["vram_free_mb"] if g and g[0].get("vram_free_mb") is not None else 0
            result = self.res.exclusive(s.model.vram_mb + summarize.MARGIN_MB, free, work, release=s.unload)
        else:
            result = work()
        if result is None or job.get("cancel"):
            self.jobs.pop(vid, None)
            self._send(vid)
            return
        with tr._lock:
            tr.data["summary"] = result
        tr.save()
        self.jobs.pop(vid, None)
        self.library.set_field(vid, summarized=True)  # el diálogo de exportar lo sabe sin abrir cada video
        self._send(vid, summary=result)
        events.emit("resumen.listo", self._vault(vid), video=vid, title=v.get("title") or "",
                    points=len(result["points"]), model=result["model"])
