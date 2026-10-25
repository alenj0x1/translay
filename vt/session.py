"""Sesión WebSocket: una por pestaña del navegador.

Protocolo
---------
Cliente → servidor
  {"type":"open", "id":<huella>, "name":<archivo>}   abre/crea la transcripción
  binario: float64 LE (tiempo de medio) + PCM int16 LE mono 16 kHz
  {"type":"seek"|"stop"|"end", "t":<s>}             cierra o descarta lo pendiente

Servidor → cliente
  ready · transcript · partial (+ "es" en vivo) · segment · translations · dub · covered · stats

Doblaje: cada frase final pasa por una cola de voz (prioridad: en vivo > frases
guardadas sin doblar). La voz corre en su propio hilo y proceso, así el
reconocimiento no espera a la síntesis.
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
                 translator: Translator, info: dict, dubber=None, tts_exec: ThreadPoolExecutor | None = None):
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
        self.dub_q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._dub_seq = 0
        self._dub_task: asyncio.Task | None = None

    async def run(self):
        worker = asyncio.create_task(self._worker())
        if self.dubber:
            self._dub_task = asyncio.create_task(self._dub_worker())
        await self.ws.send_json({"type": "ready", **self.info})
        try:
            while (msg := await self.ws.recv()) is not None:
                if isinstance(msg, bytes):
                    if len(msg) > 8:
                        t = struct.unpack("<d", msg[:8])[0]
                        pcm = np.frombuffer(msg[8:], "<i2").astype(np.float32) / 32768.0
                        self.q.put_nowait(("audio", t, pcm))
                else:
                    m = json.loads(msg)
                    self.q.put_nowait((m.get("type"), m))
        finally:
            self.q.put_nowait(("close", None))
            await worker
            if self._backfill:
                self._backfill.cancel()
            if self._dub_task:
                self._dub_task.cancel()

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
                    if self.dubber:
                        self._queue_stale_dubs(self.tr)
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
        events = await loop.run_in_executor(self.gpu, fn)
        ms = (time.perf_counter() - t) * 1000
        tr = self.tr
        if tr is None:
            return
        dirty = False
        for ev in events:
            if isinstance(ev, Segment):
                translation = await loop.run_in_executor(self.gpu, self.translator.translate, ev.text)
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
            self._live_es = await loop.run_in_executor(self.gpu, self.translator.translate, src) or ""
            self._live_src = src
        return self._live_es

    async def _translate_stale(self, tr: Transcript):
        """Traduce frases guardadas sin traducción (o con otro modelo), por lotes."""
        name = self.translator.name
        if name == "none":
            return
        loop = asyncio.get_running_loop()
        while self.tr is tr and (todo := tr.stale(name)[:16]):
            outs = await loop.run_in_executor(self.gpu, self.translator.translate_many,
                                              [s["text"] for s in todo])
            for seg, es in zip(todo, outs):
                tr.set_translation(seg["id"], es, name)
                self._queue_dub(1, tr, seg, None)
            tr.save()
            await self.ws.send_json({"type": "translations",
                                     "items": [{"id": s["id"], "translation": es}
                                               for s, es in zip(todo, outs)]})

    # ---------------------------------------------------------------- doblaje
    def _queue_dub(self, prio: int, tr: Transcript, seg: dict, orig_db: float | None):
        if not self.dubber or not seg.get("translation"):
            return
        self._dub_seq += 1
        key = seg["start"] if prio else self._dub_seq  # guardadas: en orden del video
        self.dub_q.put_nowait((prio, key, self._dub_seq, tr, seg["id"], orig_db))

    def _queue_stale_dubs(self, tr: Transcript):
        for seg in tr.segments:
            d = seg.get("dub")
            if seg.get("translation") and (not d or d.get("text") != seg["translation"]
                                           or d.get("engine") != self.dubber.tts.engine):
                self._queue_dub(1, tr, seg, seg.get("orig_db"))

    async def _dub_worker(self):
        loop = asyncio.get_running_loop()
        while True:
            prio, _, _, tr, seg_id, orig_db = await self.dub_q.get()
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
                info = await loop.run_in_executor(self.tts_exec, self.dubber.synthesize, tr, seg,
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
