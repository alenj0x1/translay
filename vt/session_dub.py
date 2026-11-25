"""Lo que se dice en vivo, su traducción y la cola de voz de la pestaña: el idioma detectado,
la traducción en vivo, rehacer lo traducido con otro glosario y doblar primero lo que se va a escuchar.

Parte de Session (vt/session.py): sus métodos usan el estado de la sesión (self)."""

import asyncio
from functools import partial
from . import i18n, langs
from .store import Transcript
from .streaming import Detected
from . import diag


class DubMixin:
    async def _detected(self, tr: Transcript, ev: Detected):
        """Idioma detectado al reconocer en vivo: se guarda, decide el modo y avisa."""
        print(f"[vivo] {tr.data['id']}: idioma detectado {ev.lang} ({ev.prob:.2f})", flush=True)
        tr.set_detected(ev.lang, self._own_lang(), live=True, prob=ev.prob)  # si la cola ya lo había detectado, queda el suyo
        if self.tr is tr:
            self.st.language = tr.lang
        if self.processor and not tr.ephemeral:  # los subtítulos en vivo no están en la biblioteca
            self.processor.lang_changed(tr.data["id"], tr)
        if tr.translates:  # prepara el traductor de ese idioma y traduce lo que quede pendiente
            if self._backfill:
                self._backfill.cancel()
            self._backfill = asyncio.create_task(self._translate_stale(tr))

    def _own_lang(self) -> str | None:
        """Idioma propio (Ajustes): lo que se habla en él solo se transcribe."""
        return self.prefs.own_lang if self.prefs else None

    async def _live_translation(self, src: str) -> str:
        """Traduce la frase abierta para el subtítulo en vivo (solo si cambió)."""
        if not src:
            self._live_src = self._live_es = ""
        elif self.tr is not None and self.tr.transcribe_only:
            self._live_src = self._live_es = src
        elif self.tr is not None and not self.translator.ready(self.tr.lang):
            self._live_src = self._live_es = ""  # traductor descargándose: nunca en el hilo de la GPU
        elif src != self._live_src:
            loop = asyncio.get_running_loop()
            self._live_es = await loop.run_in_executor(
                self.gpu, self.res.run, ("mt",), partial(self.translator.translate, glossary=self._gl(self.tr),
                                                         src=self.tr.lang), src) or ""
            self._live_src = src
        return self._live_es

    async def _translate_stale(self, tr: Transcript):
        """Traduce frases guardadas sin traducción (o con otro modelo), por lotes."""
        name = self.translator.name_for(tr.lang)
        if name == "none" or tr.transcribe_only:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self.translator.prepare, tr.lang)  # fuera del hilo de la GPU
        except Exception as e:  # sin conexión, por ejemplo: se avisa (la cola lo reintenta al procesar)
            print(f"[traductor] {tr.lang}: {e}", flush=True)
            await self.ws.send_json({"type": "yt_error", "error": i18n.t(
                "No se pudo preparar el traductor de {language}. Revisa la conexión. Se reintentará al procesar el video.",
                language=langs.name(tr.lang, langs.ui()))})
            return
        tx = partial(self.translator.translate_many, glossary=self._gl(tr), src=tr.lang)
        while self.tr is tr and (todo := tr.stale(name)[:16]):
            outs = await loop.run_in_executor(self.gpu, self.res.run, ("mt",), tx, [s["text"] for s in todo])
            for seg, es in zip(todo, outs):
                tr.set_translation(seg["id"], es, name)
            tr.save()
            await self.ws.send_json({"type": "translations",
                                     "items": [{"id": s["id"], "translation": es}
                                               for s, es in zip(todo, outs)]})

    # ---------------------------------------------------------------- doblaje
    def _queue_dub(self, prio: int, tr: Transcript, seg: dict, orig_db: float | None):
        """prio 0: frase en vivo (modo intérprete, va primero); 1: por delante / guardada."""
        if not self.dubber or not seg.get("translation") or tr.transcribe_only:
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
                diag.exception("sesion.voz")
                continue
            if not info:
                continue
            info["text"] = seg["translation"]
            seg["dub"] = info
            tr.save()
            await self.ws.send_json({"type": "dub", "id": seg_id, "speaker": seg.get("speaker"),
                                     "url": self._vault_of(tr.data["id"]).url("/audio/" + info["file"])
                                     + f"?v={self._dub_seq}",
                                     "dur": info["dur"], "live": prio == 0})
