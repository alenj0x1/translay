"""Cola de procesamiento: el único lugar donde se procesan los videos guardados.

Procesa videos completos desde el disco (YouTube: data/youtube/<id>.m4a;
archivos: data/library/<id>.*) con el mismo pipeline de siempre
(reconocimiento → traducción → personas → voz) y guarda todo en la
transcripción del video. Lo ya procesado se salta.

Foco: el video que alguien está viendo va primero, empieza desde su punto de
reproducción y, si salta a una parte sin procesar, el procesamiento salta con
él. Al dejar de verlo sigue en la cola como cualquier otro (igual que una
descarga del navegador). Pausar la cola detiene los trabajos de fondo; el video
que se está viendo se sigue procesando.

Reconocimiento y voz comparten la GPU: el reconocimiento no se adelanta más de
unas pocas frases a la voz. Estado en data/queue.json.

Descargas: los videos de una playlist entran a la cola sin descargar. Un hilo
aparte los baja en orden (sin GPU), a lo sumo MAX_DOWNLOADED_AHEAD por delante
de lo procesado para no llenar el disco; la cola procesa solo lo descargado.
"""

import json
import random
import threading
import time
from functools import partial
from pathlib import Path

import numpy as np

from . import events
from .streaming import Segment, StreamingTranscriber

SR = 16000
CHUNK_S = 3.0
MAX_PENDING_DUBS = 3
MAX_AHEAD_OF_VOICE_S = 30  # el reconocimiento no se aleja más de esto de la última frase con voz
MAX_DOWNLOADED_AHEAD = 3   # videos descargados que esperan su turno (no llenar el disco)
# YouTube marca las ráfagas de descargas de una misma sesión: se espacian, y si pide
# verificar que no eres un bot, las descargas se pausan un rato en vez de reintentar
DOWNLOAD_GAP_S = (1, 3)       # pausa al azar entre descargas (modo normal: ~5 s por video)
CAREFUL_GAP_S = (8, 15)       # modo cuidadoso: tras una verificación de YouTube, hasta renovar cookies
BLOCK_PAUSE_S = 20 * 60       # pausa tras la verificación de YouTube
RETRY_AFTER_S = 10 * 60       # un video que falla espera antes de reintentar…
MAX_ATTEMPTS = 3              # …y tras 3 intentos queda en error


def decode_audio(path: Path) -> np.ndarray:
    import av

    out = []
    with av.open(str(path)) as c:
        res = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) / 32768.0 if out else np.zeros(0, np.float32)


class Processor:
    def __init__(self, root: Path, store, library, asr, translator, dubber, res, gpu, tts_exec, notify,
                 youtube=None, session=lambda: "ninguna", vaults=None, order=lambda: "orden"):
        self.root = root
        self.vaults = vaults  # bibliotecas (vt/vaults.py): cada video se ubica en la suya
        self.order = order    # orden de descarga: "orden" (el de la cola) o "aleatorio"
        self.youtube, self.session = youtube, session
        self.path = root / "queue.json"
        self.store, self.library, self.asr = store, library, asr
        self.translator, self.dubber, self.res = translator, dubber, res
        self.gpu, self.tts_exec, self.notify = gpu, tts_exec, notify
        self.data = {"jobs": [], "paused": False}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            for j in self.data["jobs"]:
                if j["state"] == "procesando":
                    j["state"] = "en cola"  # se cortó al cerrar el servidor: se retoma
        self.current: str | None = None
        self.blocked_until = 0.0  # YouTube pidió verificación: sin descargas hasta entonces
        self.careful = False      # y desde entonces, descargas más espaciadas
        self.focus = {"vid": None, "t": 0.0}
        self._audio = (None, None)  # último audio decodificado (para saltos sin redecodificar)
        self._cond = threading.Condition()
        self._last_note = 0.0
        threading.Thread(target=self._loop, daemon=True).start()
        if youtube:
            threading.Thread(target=self._download_loop, daemon=True).start()

    # ------------------------------------------------------------------ API
    def _job(self, vid):
        return next((j for j in self.data["jobs"] if j["id"] == vid), None)

    def add(self, vid: str, front: bool = False):
        self.add_many([vid], front)

    def add_many(self, vids: list[str], front: bool = False, download_only: bool = False, audio_only: bool = False):
        """download_only: solo se descarga (sin GPU); queda "descargado" hasta que se pida procesarlo."""
        with self._cond:
            for vid in vids:
                job = self._job(vid)
                if job is None:
                    job = {"id": vid, "state": "en cola", "added": time.time(), "error": ""}
                    if download_only:
                        job["download_only"] = True
                    if audio_only:
                        job["audio_only"] = True  # se descarga solo el audio original
                    self.data["jobs"].append(job)
                elif download_only:
                    pass  # ya estaba: se deja como está (con «front», solo pasa adelante para bajarse ya)
                elif job["state"] in ("listo", "error", "descargado"):
                    job.update(state="en cola", error="")
                    job.pop("download_only", None)  # ahora sí se procesa
                elif job.get("download_only"):
                    job.pop("download_only", None)
                if front:  # prioridad: primero en la cola y deja atrás al trabajo de fondo en curso
                    self.data["jobs"].remove(job)
                    self.data["jobs"].insert(0, job)
                    job["prio"] = True
            self._save()
            self._cond.notify_all()
        self._broadcast()

    def remove_many(self, vids):
        vids = set(vids)
        with self._cond:
            self.data["jobs"] = [j for j in self.data["jobs"] if j["id"] not in vids]
            self._save()
            self._cond.notify_all()
        self._broadcast()

    def remove(self, vid: str):
        with self._cond:
            self.data["jobs"] = [j for j in self.data["jobs"] if j["id"] != vid]
            if self.focus["vid"] == vid:
                self.focus = {"vid": None, "t": 0.0}
            self._save()
            self._cond.notify_all()
        self._broadcast()

    def fetch_videos(self, vids) -> int:
        """«Bajar video»: de lo que se descargó solo con el audio, se baja el video completo
        (sin volver a traducir: la transcripción y las voces ya están)."""
        n = 0
        with self._cond:
            for vid in vids:
                v = self.library.data["videos"].get(vid) or {}
                if v.get("source") != "youtube" or not v.get("audio_only"):
                    continue
                job = self._job(vid)
                if job is None:
                    done = self.progress(vid)["dub"] >= 0.99
                    job = {"id": vid, "state": "listo" if done else "descargado", "added": time.time(), "error": ""}
                    self.data["jobs"].append(job)
                elif job["state"] == "error":
                    job.update(state="descargado", error="")
                job["fetch_video"] = True
                job.pop("retry_at", None)
                job.pop("attempts", None)
                n += 1
            self._save()
            self._cond.notify_all()
        self._broadcast()
        return n

    def clear_done(self):
        with self._cond:
            self.data["jobs"] = [j for j in self.data["jobs"]
                                 if j["state"] not in ("listo", "error", "descargado") or j.get("fetch_video")]
            self._save()
        self._broadcast()

    def set_paused(self, paused: bool):
        with self._cond:
            self.data["paused"] = paused
            self._save()
            self._cond.notify_all()
        events.emit("cola.pausa", paused=paused)
        self._broadcast()

    def _vid_event(self, name: str, vid: str, **extra):
        v = self._vault(vid)
        info = self.library.data["videos"].get(vid) or {}
        events.emit(name, v.id if v else None, video=vid, title=info.get("title", ""), **extra)

    def watch(self, vid: str, t: float):
        """Alguien empezó a ver `vid` en el segundo `t`: pasa primero."""
        if self.progress(vid)["dub"] >= 0.995:
            return  # ya está todo listo: no hace falta tocar la cola
        with self._cond:
            self.focus = {"vid": vid, "t": float(t)}
        self.add(vid, front=True)
        # los modelos empiezan a cargar ya (la voz tarda ~15 s desde el reposo profundo)
        threading.Thread(target=self.res.run, args=(("asr", "mt", "tts"), lambda: None), daemon=True).start()

    def position(self, vid: str, t: float):
        """Punto de reproducción del video que se está viendo (para seguir los saltos)."""
        if self.focus["vid"] == vid:
            self.focus["t"] = float(t)
            with self._cond:
                self._cond.notify_all()

    def unwatch(self, vid: str):
        with self._cond:
            if self.focus["vid"] == vid:
                self.focus = {"vid": None, "t": 0.0}
                self._cond.notify_all()
        self._broadcast()

    def progress(self, vid: str) -> dict:
        """Fracción reconocida (tiempo cubierto) y doblada, sobre el video completo."""
        v = self.library.data["videos"].get(vid, {})
        if not v.get("media"):  # sin descargar: nada procesado (y sin abrir su transcripción)
            return {"asr": 0.0, "dub": 0.0}
        dur = v.get("duration") or 0
        tr = self.store.open(vid, v.get("title", ""))
        covered = sum(b - a for a, b in tr.covered)
        segs = [s for s in tr.segments if s.get("translation")]
        dubbed = sum(1 for s in segs if s.get("dub"))
        asr = min(1.0, covered / dur) if dur else 0.0
        dub = asr * (dubbed / len(segs)) if segs else 0.0
        return {"asr": round(asr, 3), "dub": round(dub if self.dubber else asr, 3)}

    def _vault(self, vid: str):
        return self.vaults.of(vid) if self.vaults else None

    def _url(self, vid: str, u: str) -> str:
        v = self._vault(vid)
        return v.url(u) if v else u

    def busy(self, vid: str) -> bool:
        """¿Se está descargando o procesando? (para no moverlo a otra biblioteca a medias)"""
        j = self._job(vid)
        return self.current == vid or bool(j and j.get("dl"))

    def public(self) -> dict:
        jobs = []
        for j in self.data["jobs"]:
            try:
                p = self.progress(j["id"])
            except Exception:
                p = {"asr": 0, "dub": 0}
            v = self._vault(j["id"])
            jobs.append({**j, **p, "watching": j["id"] == self.focus["vid"], "downloaded": self._has_media(j["id"]),
                         "lib": v.id if v else ""})
        return {"type": "queue", "paused": self.data["paused"], "current": self.current, "jobs": jobs, "careful": self.careful,
                "blocked_until": self.blocked_until if self.blocked_until > time.time() else 0}

    # ---------------------------------------------------------------- bucle
    def _next(self):
        fv = self.focus["vid"]
        job = self._job(fv) if fv else None
        if job and job["state"] not in ("listo", "error"):
            return job
        if self.data["paused"]:
            return None
        return next((j for j in self.data["jobs"]
                     if j["state"] == "en cola" and not j.get("download_only") and self._has_media(j["id"])), None)

    def _has_media(self, vid: str) -> bool:
        return bool((self.library.data["videos"].get(vid) or {}).get("media"))

    # ------------------------------------------------------------- descargas
    def unblock(self):
        """Cookies nuevas: las descargas siguen sin esperar el fin de la pausa."""
        with self._cond:
            self.blocked_until = 0.0
            self.careful = False  # sesión nueva: vuelve el modo normal
            for j in self.data["jobs"]:
                j.pop("retry_at", None)
            self._cond.notify_all()
        self._broadcast()

    def _next_download(self):
        # la pausa de la cola es del procesamiento (GPU); las descargas no la usan y siguen
        if time.time() < self.blocked_until:
            return None
        now = time.time()
        # pocas descargas por delante de lo procesado (con miles importados, el disco se
        # llenaría); lo priorizado o pedido para abrir se descarga enseguida
        waiting, capped = 0, None
        shuffle = self.order() == "aleatorio"
        pending = []
        for j in self.data["jobs"]:
            if j.get("retry_at", 0) > now:
                continue
            if j.get("fetch_video"):  # «Bajar video»: no cuenta para el límite (no espera a la GPU)
                if shuffle:
                    pending.append(j)
                elif capped is None:
                    capped = j
                continue
            if j["state"] != "en cola":
                continue
            v = self.library.data["videos"].get(j["id"]) or {}
            if v.get("media"):
                waiting += 0 if j.get("download_only") else 1
            elif v.get("source") == "youtube":
                if j.get("prio"):
                    return j
                if shuffle:
                    pending.append(j)
                elif capped is None and (waiting < MAX_DOWNLOADED_AHEAD or j.get("download_only")):
                    capped = j
        if shuffle and pending:
            # aleatorio: lo priorizado sigue primero; del resto, cualquiera (así se descarga variado)
            ok = [j for j in pending if waiting < MAX_DOWNLOADED_AHEAD or j.get("download_only") or j.get("fetch_video")]
            return random.choice(ok) if ok else None
        return capped

    def _download_loop(self):
        while True:
            with self._cond:
                while (job := self._next_download()) is None:
                    self._cond.wait(timeout=30)
            vid = job["id"]
            last = [0.0]

            def progress(stage, frac, title=None, stats=None, job=job):
                job["dl"] = {"stage": stage, "pct": round(frac * 100), **(stats or {})}
                v = self._vault(vid)
                events.emit("descarga.progreso", v.id if v else None, video=vid, **job["dl"])
                if time.time() - last[0] > 1 or stage == "listo":
                    last[0] = time.time()
                    self._broadcast()

            try:
                yt = (self._vault(vid) or self).youtube  # se descarga en la carpeta de su biblioteca
                info = yt.fetch(vid[3:], progress, self.session(),
                                audio_only=bool(job.get("audio_only")) and not job.get("fetch_video"), careful=self.careful)
                self.library.set_field(vid, media=info["video"] or info["audio"], audio=info["audio"],
                                       audio_only=bool(info.get("audio_only")),
                                       **{k: info[k] for k in ("title", "duration", "thumb", "channel", "categories")
                                          if info.get(k)})
                job.pop("dl", None)
                job.pop("attempts", None)
                job.pop("retry_at", None)
                if job.pop("fetch_video", None):  # ya tiene el video: queda en el estado que tenía
                    job.pop("audio_only", None)
                elif job.get("download_only"):  # «Solo descargar»: listo para ver o exportar el original
                    job["state"] = "descargado"
                self._vid_event("video.descargado", vid, audio_only=bool(info.get("audio_only")))
            except Exception as e:
                from .youtube import friendly_error

                print(f"[descarga] {vid}: {e}", flush=True)
                job.pop("dl", None)
                msg = str(e)
                if "confirm you" in msg and "bot" in msg:
                    # verificación de YouTube: todas las descargas esperan; el video no queda en error
                    self.blocked_until = time.time() + BLOCK_PAUSE_S
                    self.careful = True
                    self.notify({"type": "yt_blocked", "until": self.blocked_until,
                                 "error": friendly_error(e, self.session())})
                    events.emit("youtube.bloqueo", until=self.blocked_until)
                else:
                    job["attempts"] = job.get("attempts", 0) + 1
                    if job["attempts"] >= MAX_ATTEMPTS:
                        job.pop("fetch_video", None)
                        job.update(state="error", error=friendly_error(e, self.session()))
                        self._vid_event("video.error", vid, error=job["error"])
                    else:
                        job["retry_at"] = time.time() + RETRY_AFTER_S
            with self._cond:
                self._save()
                self._cond.notify_all()
            self._broadcast()
            self.notify({"type": "library_changed"})
            # espacio entre descargas (se interrumpe si hay que parar)
            with self._cond:
                self._cond.wait(timeout=random.uniform(*(CAREFUL_GAP_S if self.careful else DOWNLOAD_GAP_S)))

    def _loop(self):
        while True:
            with self._cond:
                while (job := self._next()) is None:
                    self._cond.wait()
                job["state"] = "procesando"
                self.current = job["id"]
                start = self.focus["t"] if self.focus["vid"] == job["id"] else 0.0
                self._save()
            self._broadcast()
            began = time.time()
            try:
                done = self._process(job["id"], start)
                if self._job(job["id"]) is job:
                    job["state"] = "listo" if done else "en cola"
                    if done:
                        job.pop("prio", None)
                        self._vid_event("video.procesado", job["id"])
                        if not any(j["state"] in ("en cola", "procesando") for j in self.data["jobs"]):
                            events.emit("cola.terminada")
            except Exception as e:
                import traceback

                traceback.print_exc()
                job.update(state="error", error=str(e)[:200])
                self._vid_event("video.error", job["id"], error=job["error"])
            with self._cond:
                self.current = None
                self._save()
                # resguardo: un trabajo que se corta al instante no se reintenta en ráfaga
                if self._job(job["id"]) is job and job["state"] == "en cola" and time.time() - began < 0.5:
                    self._cond.wait(timeout=1.0)
            self._broadcast()

    def _interrupt(self, vid: str, span_start: float, pos: float) -> bool:
        """¿Hay que dejar este trabajo? (se quitó, se pausó, se mira otro video o se saltó)."""
        cur = self._job(vid)
        if cur is None:
            return True
        fv = self.focus["vid"]
        # un trabajo con prioridad (ya descargado) pasa delante del de fondo en curso;
        # lo avanzado queda guardado y se retoma después
        if fv != vid and not cur.get("prio"):
            first = next((j for j in self.data["jobs"] if j["state"] == "en cola" and self._has_media(j["id"])), None)
            if first and first.get("prio"):
                return True
        fj = self._job(fv) if fv else None
        # el video que se está viendo pasa primero, solo si le falta algo: si ya está
        # terminado, cederle el turno dejaba este trabajo empezando y cortándose sin fin
        if fv and fv != vid and fj and fj["state"] not in ("listo", "error"):
            return True
        if self.data["paused"] and fv != vid:
            return True
        if fv == vid:
            t = self.focus["t"]
            if not self._ready_at(vid, t) and (t < span_start - 1 or t > pos + 2):
                return True  # salto a una parte sin terminar: se retoma desde ahí
        return False

    def _ready_at(self, vid: str, t: float) -> bool:
        """¿Está listo lo que se va a escuchar en t? (reconocido y con voz los próximos 10 s)"""
        tr = self.store.open(vid)
        if not any(a - 0.5 <= t < b for a, b in tr.covered):
            return False
        return all(x.get("dub") or not x.get("translation") or not self.dubber
                   for x in tr.segments if t - 0.5 <= x["start"] < t + 10)

    def _media(self, vid: str) -> Path:
        v = self.library.data["videos"].get(vid) or {}
        src = v.get("audio") or v.get("media") or ""
        vault = self._vault(vid)
        if vault:
            f = vault.file(src)
            if f:
                return f
        if src.startswith("/media/yt/"):
            return self.root / "youtube" / src.rsplit("/", 1)[1].split("?")[0]
        if src.startswith("/media/lib/"):
            return self.root / "library" / src.rsplit("/", 1)[1].split("?")[0]
        raise FileNotFoundError("el video no tiene copia en el servidor")

    def _load_audio(self, vid: str) -> np.ndarray:
        if self._audio[0] != vid:
            self._audio = (vid, decode_audio(self._media(vid)))
        return self._audio[1]

    def _process(self, vid: str, start: float) -> bool:
        print(f"[cola] {vid} desde {start:.0f}s", flush=True)
        audio = self._load_audio(vid)
        dur = len(audio) / SR
        title = (self.library.data["videos"].get(vid) or {}).get("title", "")
        if dur and not (self.library.data["videos"].get(vid) or {}).get("duration"):
            self.library.set_field(vid, duration=round(dur, 2))
        tr = self.store.open(vid, title)
        vault = self._vault(vid)
        tx = partial(self.translator.translate, glossary=vault.glossary if vault else None)  # su glosario
        st = StreamingTranscriber(self.asr)
        dubs = []
        inflight: set[int] = set()  # frases con voz en camino
        voice_end = [start]  # fin de la última frase con voz de este trabajo
        step = int(CHUNK_S * SR)

        def needs_dub(seg) -> bool:
            if not self.dubber or seg["id"] in inflight:
                return False
            d = seg.get("dub")
            return not (d and d.get("text") == seg.get("translation") and d.get("engine") == self.dubber.tts.engine
                        and d.get("voice") == seg.get("speaker"))

        def complete(lo: float, hi: float) -> bool:
            """Frases ya reconocidas en [lo, hi) a las que les falta traducción o voz
            (de procesamientos que se cortaron): se completan en orden. False si hay
            que dejar el trabajo."""
            todo = [x for x in tr.segments if lo - 0.5 <= x["start"] < hi and (not x.get("translation") or needs_dub(x))]
            if todo:
                print(f"[cola] completar {lo:.0f}-{hi:.0f}s: {len(todo)} frases", flush=True)
            for seg in sorted((x for x in tr.segments if lo - 0.5 <= x["start"] < hi), key=lambda x: x["start"]):
                if self._interrupt(vid, lo, seg["start"]):
                    return False  # se saltó a otra parte: se retoma desde ahí
                if not seg.get("translation"):
                    seg["translation"] = self.gpu.submit(self.res.run, ("mt",), tx, seg["text"]).result()
                    seg["tr_model"] = self.translator.name
                    self._bg(vid, {"type": "translations", "items": [{"id": seg["id"], "translation": seg["translation"]}]})
                if needs_dub(seg):
                    while sum(not f.done() for f in dubs) > MAX_PENDING_DUBS:
                        time.sleep(0.1)
                        if self._interrupt(vid, lo, seg["start"]):
                            return False
                    dubs.append(self._dub(tr, vid, seg, seg.get("orig_db"), inflight, voice_end))
            return True

        def handle(events):
            for ev in events:
                if not isinstance(ev, Segment):
                    continue
                es = self.gpu.submit(self.res.run, ("mt",), tx, ev.text).result()
                seg, removed = tr.add_segment(ev.start, ev.end, ev.text, es, self.translator.name)
                fixed = []
                if self.dubber:
                    seg["speaker"] = self.dubber.identify(tr, seg, ev.audio)
                    fixed = self.dubber.relabel(tr)
                    dubs.append(self._dub(tr, vid, seg, self.dubber.loudness(ev.audio), inflight, voice_end))
                    for s in fixed:
                        dubs.append(self._dub(tr, vid, s, s.get("orig_db"), inflight, voice_end))
                        self._bg(vid, {"type": "speaker", "id": s["id"], "speaker": s["speaker"]})
                self._bg(vid, {"type": "segment", "segment": seg, "removed": removed})
            if st.final_t > st.start_t:
                tr.add_covered(st.start_t, st.final_t)
                self._bg(vid, {"type": "covered", "ranges": tr.covered})
            tr.save()

        def drop_pending():
            # al saltar o dejar el trabajo: las voces encargadas que aún no empezaron se
            # cancelan (si no, la voz de lo que se va a escuchar espera detrás de ellas)
            for f in dubs:
                f.cancel()
            inflight.clear()

        def end_span(abort=False):
            if st._started:
                fn = st.abort if abort else st.flush
                handle(self.gpu.submit(self.res.run, ("asr",), fn).result())
            st.reset(0.0)

        # primero desde `start` hasta el final; después lo que quedó antes de `start`
        for lo, hi in ((start, dur), (0.0, start)):
            pos, span_start = lo, lo
            while pos < hi - 0.05:
                if self._interrupt(vid, span_start, pos):
                    end_span(abort=True)
                    drop_pending()
                    return False
                span = next(((a, b) for a, b in tr.covered if a - 0.05 <= pos < b - 0.25), None)
                if span:  # ya reconocido (antes, o por otra pestaña): completar lo que falte y seguir
                    end_span()
                    if not complete(pos, span[1]):
                        drop_pending()
                        return False
                    pos = span_start = span[1]
                    continue
                # la voz va detrás del reconocimiento: no dejar que se aleje (ni en
                # cantidad de frases pendientes ni en tiempo de video)
                while (sum(not f.done() for f in dubs) > MAX_PENDING_DUBS
                       or (inflight and pos - voice_end[0] > MAX_AHEAD_OF_VOICE_S)):
                    time.sleep(0.1)
                    if self._interrupt(vid, span_start, pos):
                        end_span(abort=True)
                        drop_pending()
                        return False
                a = int(pos * SR)
                st.feed(pos, audio[a:a + step])
                pos = min(hi, (a + step) / SR)
                if st.ready():
                    handle(self.gpu.submit(self.res.run, ("asr",), st.step).result())
                self.res.touch()
                if time.time() - self._last_note > 2:
                    self._last_note = time.time()
                    self._broadcast()
            end_span()
        for f in dubs:  # esperar la voz pendiente
            if not f.cancelled():
                f.result()
        covered = sum(b - a for a, b in tr.covered)
        return covered >= dur - 2

    def _dub(self, tr, vid, seg, orig_db, inflight: set, voice_end: list | None = None):
        if orig_db is not None:
            seg["orig_db"] = round(orig_db, 1)
        inflight.add(seg["id"])

        def job():
            t0 = time.perf_counter()
            try:
                info = self.res.run(("tts",), self.dubber.synthesize, tr, seg, seg.get("orig_db"))
            finally:
                inflight.discard(seg["id"])
            if time.perf_counter() - t0 > 5:  # aviso solo si algo anda lento (p. ej. GPU desbordada)
                print(f"[cola] voz {seg['start']:.0f}s tardó {time.perf_counter() - t0:.1f}s", flush=True)
            if info:
                info["text"] = seg["translation"]
                seg["dub"] = info
                tr.save()
                if voice_end is not None:
                    voice_end[0] = max(voice_end[0], seg["end"])
                self._bg(vid, {"type": "dub", "id": seg["id"], "speaker": seg.get("speaker"),
                               "url": self._url(vid, "/audio/" + info["file"]) + f"?v={int(time.time() * 1000)}",
                               "dur": info["dur"], "live": False})

        return self.tts_exec.submit(job)

    def _bg(self, vid, msg):
        self.notify({"type": "bg", "video": vid, "msg": msg})

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def _broadcast(self):
        try:
            msg = self.public()
            self.notify(msg)
        except Exception:
            return
        # resumen para los webhooks (se agrupa: llega cada pocos segundos)
        counts: dict = {}
        for j in msg["jobs"]:
            k = "descargando" if j.get("dl") else j["state"]
            counts[k] = counts.get(k, 0) + 1
        events.emit("cola.cambio", paused=msg["paused"], current=msg["current"], counts=counts,
                    total=len(msg["jobs"]), blocked_until=msg["blocked_until"])
