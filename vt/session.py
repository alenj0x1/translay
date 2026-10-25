"""Sesión WebSocket: una por pestaña del navegador.

Protocolo
---------
Cliente → servidor
  {"type":"open", "id":<huella>, "name":<archivo>}   abre/crea la transcripción
  binario: float64 LE (tiempo de medio) + PCM int16 LE mono 16 kHz
  {"type":"seek"|"stop"|"end", "t":<s>}             cierra o descarta lo pendiente
  {"type":"pos", "t":<s>}                            punto de reproducción (orden del doblaje)
  {"type":"watch", "video":<id>, "t":<s>} / unwatch  video guardado que se está viendo: lo procesa
                                                     la cola (vt/processor.py) desde ese punto
  {"type":"youtube", "url":<enlace>}                 descarga y responde yt_progress / yt_ready
  {"type":"library"} · lib_register · lib_remove · coll_create · coll_toggle · coll_rename · coll_delete
                                                     biblioteca y colecciones (responde "library")

Servidor → cliente
  ready · transcript · partial (+ "es" en vivo) · segment · translations · dub · covered · stats

Doblaje: cada frase final pasa por una cola de voz que atiende primero lo que
se va a escuchar (las frases desde el punto de reproducción en adelante, en
orden). La voz corre en su propio hilo y proceso, así el reconocimiento no
espera a la síntesis.
"""

import asyncio
import json
import struct
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .store import Store, Transcript
from .streaming import Partial, Segment, StreamingTranscriber
from .translate import Translator


class Session:
    def __init__(self, ws, asr, gpu: ThreadPoolExecutor, store: Store,
                 translator: Translator, info: dict, dubber=None, tts_exec: ThreadPoolExecutor | None = None,
                 youtube=None, library=None, res=None, processor=None, prefs=None, notify=None):
        self.ws = ws
        self.gpu = gpu
        self.store = store
        self.translator = translator
        self.info = info
        self.st = StreamingTranscriber(asr)
        self.tr: Transcript | None = None
        self.q: asyncio.Queue = asyncio.Queue()
        self._live_src = ""
        self._live_es = ""
        self._backfill: asyncio.Task | None = None
        self.dubber = dubber
        self.tts_exec = tts_exec
        self.dub_pending: dict[int, tuple[int, Transcript, float | None]] = {}
        self.dub_event = asyncio.Event()
        self.playhead = 0.0
        self.youtube = youtube
        self.library = library
        self.res = res
        self.processor = processor
        self.watching: str | None = None
        self.prefs = prefs
        self.notify = notify or (lambda msg: None)
        self._dub_seq = 0
        self._dub_task: asyncio.Task | None = None

    async def run(self):
        worker = asyncio.create_task(self._worker())
        if self.dubber:
            self._dub_task = asyncio.create_task(self._dub_worker())
        await self.ws.send_json({"type": "ready", **self.info})
        await self.ws.send_json({"type": "power", "state": self.res.state})
        if self.prefs:
            await self.ws.send_json(self.prefs.public())
        if self.processor:
            await self.ws.send_json(self.processor.public())
        try:
            while (msg := await self.ws.recv()) is not None:
                if isinstance(msg, bytes):
                    if len(msg) > 8:
                        self.res.touch()
                        t = struct.unpack("<d", msg[:8])[0]
                        pcm = np.frombuffer(msg[8:], "<i2").astype(np.float32) / 32768.0
                        self.q.put_nowait(("audio", t, pcm))
                else:
                    m = json.loads(msg)
                    if m.get("type") == "pos":
                        self.playhead = float(m.get("t", 0))
                        if self.library and self.tr is not None:
                            self.library.position(self.tr.data["id"], self.playhead)
                        if self.watching and self.processor:
                            self.processor.position(self.watching, self.playhead)
                    elif m.get("type") == "watch" and self.processor:
                        if self.watching and self.watching != m.get("video"):
                            self.processor.unwatch(self.watching)
                        self.watching = str(m.get("video"))
                        self.processor.watch(self.watching, float(m.get("t", 0)))
                    elif m.get("type") == "unwatch" and self.processor:
                        if self.watching:
                            self.processor.unwatch(self.watching)
                        self.watching = None
                    elif self.library and m.get("type", "").startswith(("lib", "coll")):
                        await self._library(m)
                    elif m.get("type") == "prefs_set" and self.prefs:
                        if self.prefs.set(str(m.get("key")), m.get("value")):
                            self.notify(self.prefs.public())  # todas las pestañas
                    elif m.get("type") == "power_info":
                        import sys as _sys
                        import threading as _th
                        import traceback as _tb
                        names = {t.ident: t.name for t in _th.enumerate()}
                        stacks = {names.get(i, str(i)): "".join(_tb.format_stack(f)[-4:])
                                  for i, f in _sys._current_frames().items()}
                        await self.ws.send_json({"type": "power_info", **self.res.info(), "threads": stacks})
                    elif m.get("type") == "youtube":
                        asyncio.create_task(self._youtube(m.get("url", ""), bool(m.get("queue"))))
                    elif m.get("type", "").startswith("queue_") and self.processor:
                        await self._queue(m)
                    else:
                        self.q.put_nowait((m.get("type"), m))
        finally:
            self.q.put_nowait(("close", None))
            await worker
            if self._backfill:
                self._backfill.cancel()
            if self._dub_task:
                self._dub_task.cancel()
            if self.watching and self.processor:
                self.processor.unwatch(self.watching)

    async def _worker(self):
        while True:
            ops = [await self.q.get()]
            while not self.q.empty():
                ops.append(self.q.get_nowait())
            for op in ops:
                kind = op[0]
                if kind == "close":
                    await self._finish()
                    return
                if kind == "audio":
                    if self.tr is None:
                        continue
                    _, t, pcm = op
                    if self.st.is_gap(t):
                        await self._finish(abort=True)
                    self.st.feed(t, pcm)
                elif kind == "seek":
                    await self._finish(abort=True)
                elif kind in ("stop", "end"):
                    await self._finish(keep_context=True)
                elif kind == "open":
                    await self._finish()
                    self.tr = self.store.open(str(op[1].get("id", "")), op[1].get("name", ""))
                    await self.ws.send_json({"type": "transcript", **self.tr.public()})
                    if self._backfill:
                        self._backfill.cancel()
                    self._backfill = asyncio.create_task(self._translate_stale(self.tr))
                    # la voz que falte la completa la cola (vt/processor.py) al ver o
                    # procesar el video: hacerlo también aquí duplicaba el trabajo
            if self.tr is not None and self.st.ready():
                try:
                    await self._run(self.st.step)
                except Exception:  # una falla no debe detener la sesión
                    traceback.print_exc()
                    await self.ws.send_json({"type": "stats", "infer_ms": 0, "buffer_s": 0})

    async def _finish(self, keep_context: bool = False, abort: bool = False):
        """Cierra el tramo actual y reinicia el streamer.

        stop/end: se confirma todo lo pendiente (el tramo terminó de verdad).
        seek: se descarta la frase abierta (quedaría cortada a la mitad).
        La pausa no llega aquí: al reanudar, el audio sigue siendo continuo.
        """
        if self.st._started:
            await self._run(self.st.abort if abort else self.st.flush)
        self.st.reset(0.0, keep_context=keep_context)

    async def _run(self, fn):
        loop = asyncio.get_running_loop()
        t = time.perf_counter()
        events = await loop.run_in_executor(self.gpu, self.res.run, ("asr",), fn)
        ms = (time.perf_counter() - t) * 1000
        tr = self.tr
        if tr is None:
            return
        dirty = False
        for ev in events:
            if isinstance(ev, Segment):
                translation = await loop.run_in_executor(self.gpu, self.res.run, ("mt",),
                                                         self.translator.translate, ev.text)
                seg, removed = tr.add_segment(ev.start, ev.end, ev.text, translation,
                                              self.translator.name)
                if self.dubber:
                    seg["speaker"] = await loop.run_in_executor(None, self.dubber.identify, tr, seg, ev.audio)
                    self._queue_dub(0, tr, seg, self.dubber.loudness(ev.audio))
                    for fixed in self.dubber.relabel(tr):  # frases cortas con persona corregida
                        await self.ws.send_json({"type": "speaker", "id": fixed["id"], "speaker": fixed["speaker"]})
                        self._queue_dub(0, tr, fixed, fixed.get("orig_db"))
                await self.ws.send_json({"type": "segment", "segment": seg, "removed": removed})
                dirty = True
            elif isinstance(ev, Partial):
                es = await self._live_translation(f"{ev.committed} {ev.tentative}".strip())
                await self.ws.send_json({"type": "partial", "committed": ev.committed,
                                         "tentative": ev.tentative, "es": es})
        if self.st.final_t > self.st.start_t:
            before = list(map(list, tr.covered))
            tr.add_covered(self.st.start_t, self.st.final_t)
            if tr.covered != before:
                await self.ws.send_json({"type": "covered", "ranges": tr.covered})
                dirty = True
        if dirty:
            tr.save()
        await self.ws.send_json({"type": "stats", "infer_ms": round(ms),
                                 "buffer_s": round(self.st.duration, 2)})

    async def _live_translation(self, src: str) -> str:
        """Traduce la frase abierta para el subtítulo en vivo (solo si cambió)."""
        if not src:
            self._live_src = self._live_es = ""
        elif src != self._live_src:
            loop = asyncio.get_running_loop()
            self._live_es = await loop.run_in_executor(self.gpu, self.res.run, ("mt",),
                                                       self.translator.translate, src) or ""
            self._live_src = src
        return self._live_es

    async def _translate_stale(self, tr: Transcript):
        """Traduce frases guardadas sin traducción (o con otro modelo), por lotes."""
        name = self.translator.name
        if name == "none":
            return
        loop = asyncio.get_running_loop()
        while self.tr is tr and (todo := tr.stale(name)[:16]):
            outs = await loop.run_in_executor(self.gpu, self.res.run, ("mt",), self.translator.translate_many,
                                              [s["text"] for s in todo])
            for seg, es in zip(todo, outs):
                tr.set_translation(seg["id"], es, name)
            tr.save()
            await self.ws.send_json({"type": "translations",
                                     "items": [{"id": s["id"], "translation": es}
                                               for s, es in zip(todo, outs)]})

    # ---------------------------------------------------------------- doblaje
    def _queue_dub(self, prio: int, tr: Transcript, seg: dict, orig_db: float | None):
        """prio 0: frase en vivo (modo intérprete, va primero); 1: por delante / guardada."""
        if not self.dubber or not seg.get("translation"):
            return
        old = self.dub_pending.get(seg["id"])
        self.dub_pending[seg["id"]] = (min(prio, old[0]) if old else prio, tr, orig_db)
        self.dub_event.set()

    def _next_dub(self):
        """La frase pendiente que antes se va a escuchar."""
        best, best_key = None, None
        for sid, (prio, tr, _) in self.dub_pending.items():
            seg = next((x for x in tr.segments if x["id"] == sid), None)
            if seg is None:
                continue
            ahead = seg["end"] >= self.playhead - 0.5
            key = (prio, not ahead, seg["start"] if ahead else -seg["start"])
            if best_key is None or key < best_key:
                best, best_key = sid, key
        if best is None:
            self.dub_pending.clear()
            return None
        prio, tr, orig_db = self.dub_pending.pop(best)
        return prio, tr, best, orig_db

    def _next_dub(self):
        """La frase pendiente que antes se va a escuchar."""
        best, best_key = None, None
        for sid, (prio, tr, _) in self.dub_pending.items():
            seg = next((x for x in tr.segments if x["id"] == sid), None)
            if seg is None:
                continue
            ahead = seg["end"] >= self.playhead - 0.5
            key = (prio, not ahead, seg["start"] if ahead else -seg["start"])
            if best_key is None or key < best_key:
                best, best_key = sid, key
        if best is None:
            self.dub_pending.clear()
            return None
        prio, tr, orig_db = self.dub_pending.pop(best)
        return prio, tr, best, orig_db

    def _queue_stale_dubs(self, tr: Transcript):
        for seg in tr.segments:
            d = seg.get("dub")
            if seg.get("translation") and (not d or d.get("text") != seg["translation"]
                                           or d.get("engine") != self.dubber.tts.engine):
                self._queue_dub(1, tr, seg, seg.get("orig_db"))

    async def _dub_worker(self):
        loop = asyncio.get_running_loop()
        while True:
            if not self.dub_pending:
                self.dub_event.clear()
                await self.dub_event.wait()
                continue
            item = self._next_dub()
            if item is None:
                continue
            prio, tr, seg_id, orig_db = item
            seg = next((s for s in tr.segments if s["id"] == seg_id), None)
            if seg is None or tr is not self.tr:
                continue
            d = seg.get("dub")
            if (d and d.get("text") == seg.get("translation") and d.get("engine") == self.dubber.tts.engine
                    and d.get("voice") == seg.get("speaker")):
                continue
            if orig_db is not None:
                seg["orig_db"] = round(orig_db, 1)
            try:
                info = await loop.run_in_executor(self.tts_exec, self.res.run, ("tts",), self.dubber.synthesize, tr, seg,
                                                  seg.get("orig_db"))
            except Exception:  # una frase fallida no detiene el doblaje
                traceback.print_exc()
                continue
            if not info:
                continue
            info["text"] = seg["translation"]
            seg["dub"] = info
            tr.save()
            await self.ws.send_json({"type": "dub", "id": seg_id, "speaker": seg.get("speaker"),
                                     "url": "/audio/" + info["file"] + f"?v={self._dub_seq}",
                                     "dur": info["dur"], "live": prio == 0})

    # ---------------------------------------------------------------- YouTube
    async def _youtube(self, url: str, queue: bool = False):
        loop = asyncio.get_running_loop()
        if not self.youtube:
            await self.ws.send_json({"type": "yt_error", "error": "YouTube no está habilitado"})
            return
        from .youtube import video_id

        vid = video_id(url) or ""
        last = {"stage": None, "frac": 0.0, "title": ""}

        def progress(stage, frac, title=None):
            last["title"] = title or last["title"]
            # sin inundar el WebSocket: cada cambio de etapa y cada 2 %
            if stage == last["stage"] and frac - last["frac"] < 0.02 and frac < 1.0:
                return
            last.update(stage=stage, frac=frac)
            loop.call_soon_threadsafe(asyncio.ensure_future, self.ws.send_json(
                {"type": "yt_progress", "id": vid, "title": last["title"], "stage": stage,
                 "pct": round(frac * 100)}))

        try:
            info = await loop.run_in_executor(None, self.youtube.fetch, url, progress)
            if self.library:
                self.library.register("yt_" + info["id"], source="youtube", media=info["video"],
                                      **{k: info.get(k) for k in ("title", "duration", "audio", "thumb",
                                                                    "channel", "categories")})
            if queue and self.processor:  # solo a la cola: no se abre para ver
                self.processor.add("yt_" + info["id"])
                await self.ws.send_json({"type": "yt_queued", **info})
                await self._library({"type": "library"})
                return
            await self.ws.send_json({"type": "yt_ready", **info})
        except Exception as e:
            traceback.print_exc()
            await self.ws.send_json({"type": "yt_error", "error": str(e)[:300]})

    # ------------------------------------------------------------- biblioteca
    async def _library(self, m: dict):
        lib, kind = self.library, m.get("type")
        vid = str(m.get("video", ""))
        if kind == "lib_register":
            lib.register(str(m["id"]), **{k: m.get(k) for k in ("title", "duration", "source", "media",
                                                                  "audio", "thumb", "channel", "categories")})
        elif kind == "lib_remove":
            lib.remove(vid)
        elif kind == "coll_create":
            c = lib.create(m.get("name", ""))
            if vid:
                lib.toggle(c["id"], vid, True)
        elif kind == "coll_toggle":
            lib.toggle(m["coll"], vid, bool(m.get("on")))
        elif kind == "coll_rename":
            lib.rename(m["coll"], m.get("name", ""))
        elif kind == "coll_delete":
            lib.delete(m["coll"])
        data = lib.public()
        if self.processor:  # avance de cada video (para "Procesar" y las barras)
            for vid, v in data["videos"].items():
                try:
                    v["progress"] = self.processor.progress(vid)
                except Exception:
                    v["progress"] = {"asr": 0, "dub": 0}
        await self.ws.send_json({"type": "library", **data})

    # --------------------------------------------------------- cola de fondo
    async def _queue(self, m: dict):
        kind, vid = m["type"], str(m.get("video", ""))
        if kind == "queue_add":
            self.processor.add(vid)
        elif kind == "queue_remove":
            self.processor.remove(vid)
        elif kind == "queue_pause":
            self.processor.set_paused(True)
            # pausada y sin ningún video viéndose: reposo profundo inmediato
            # (también se cierra el proceso de voz: la GPU queda libre)
            if not self.st._started and not self.processor.focus["vid"]:
                await asyncio.get_running_loop().run_in_executor(None, self._sleep_when_idle)
        elif kind == "queue_resume":
            self.processor.set_paused(False)
        elif kind == "queue_clear":
            self.processor.clear_done()

    def _sleep_when_idle(self):
        # lo que estaba en curso (una traducción o una voz) termina primero
        for _ in range(60):
            if self.res.info()["busy"] == 0:
                break
            time.sleep(0.5)
        self.res.sleep(deep=True)

    def forward_bg(self, msg: dict) -> dict | None:
        """Avance en segundo plano del video que esta pestaña tiene abierto."""
        if msg.get("type") == "bg":
            return msg["msg"] if self.tr is not None and msg["video"] == self.tr.data["id"] else None
        return msg
