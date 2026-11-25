"""Editor de frases: corregir la traducción de una frase del video abierto, rehacer su voz y elegir entre tomas.

  seg_edit {video, seg, translation, takes}  la traducción a mano; la frase queda marcada (`manual`) para que el glosario
                                        no la pise al retraducir. Con takes=n se generan n tomas del texto nuevo y la
                                        primera pasa a sonar; sin takes, su voz se rehace primero en la cola de la pestaña
  seg_takes {video, seg, n}            n tomas de la voz de la frase (2 a 4; el motor de voz da una distinta cada vez),
                                        guardadas como <frase>.<idioma>.t<k>.wav; responde «takes» con cada una
  seg_take {video, seg, k}             la toma k pasa a ser la voz de la frase; responde «dub» como cualquier frase

Solo el dueño (como comentarios, personas y glosario). Parte de Session (vt/session.py)."""

import asyncio

from . import diag

MAX_TEXT = 600


class EditMixin:
    def _drop_takes(self, tr, seg):
        """Las tomas anteriores de la frase dejan de existir (sus archivos también), salvo la que suena."""
        root = self._vault_of(tr.data["id"]).root / "audio"
        playing = (seg.get("dub") or {}).get("file")
        for t in seg.pop("takes", None) or []:
            if t.get("file") and t["file"] != playing:
                (root / t["file"]).unlink(missing_ok=True)

    def _edit_target(self, m: dict):
        """La transcripción abierta y la frase pedida, si son del video que esta pestaña tiene abierto."""
        tr = self.tr
        if tr is None or str(m.get("video", "")) != tr.data["id"]:
            return None, None
        try:
            sid = int(m.get("seg"))
        except (TypeError, ValueError):
            return tr, None
        return tr, next((s for s in tr.segments if s["id"] == sid), None)

    def _dub_msg(self, tr, seg, info) -> dict:
        self._dub_seq = getattr(self, "_dub_seq", 0) + 1
        return {"type": "dub", "id": seg["id"], "speaker": seg.get("speaker"),
                "url": self._vault_of(tr.data["id"]).url("/audio/" + info["file"]) + f"?v={self._dub_seq}",
                "dur": info["dur"], "live": False}

    async def _seg_edit(self, m: dict):
        tr, seg = self._edit_target(m)
        if seg is None or tr.transcribe_only:
            return
        text = " ".join(str(m.get("translation", "")).split())[:MAX_TEXT]
        if not text:
            return
        if text == seg.get("translation"):  # mismo texto: solo las tomas, si las pidió (la primera pasa a sonar)
            if m.get("takes"):
                await self._takes_and_play(tr, seg, m)
            return
        tr.set_translation(seg["id"], text, "manual")
        seg["manual"] = True
        self._drop_takes(tr, seg)  # las tomas eran del texto anterior
        tr.save()
        items = [{"id": seg["id"], "translation": text}]
        await self.ws.send_json({"type": "translations", "items": items})
        self.notify({"type": "bg", "video": tr.data["id"], "msg": {"type": "translations", "items": items}})
        if m.get("takes") and self.dubber:  # «Rehacer voz»: tres tomas del texto nuevo; la primera pasa a sonar
            await self._takes_and_play(tr, seg, m)
        elif self.dubber:
            self._queue_dub(0, tr, seg, seg.get("orig_db"))  # primero en la cola de voz de esta pestaña
        elif self.processor:
            self.processor.add(tr.data["id"])

    async def _takes_and_play(self, tr, seg, m: dict):
        await self._seg_takes({**m, "n": m.get("takes")})
        takes = seg.get("takes") or []
        if takes:
            seg["dub"] = dict(takes[0])
            tr.save()
            await self.ws.send_json(self._dub_msg(tr, seg, seg["dub"]))

    async def _seg_takes(self, m: dict):
        tr, seg = self._edit_target(m)
        try:
            n = max(2, min(4, int(float(m.get("n") or 3))))
        except (TypeError, ValueError, OverflowError):
            n = 3
        if seg is None or tr.transcribe_only or not self.dubber or not seg.get("translation"):
            # siempre hay respuesta: el editor no se queda en «Generando tomas…»
            return await self.ws.send_json({"type": "takes", "id": (seg or {}).get("id", m.get("seg")), "items": []})
        self._drop_takes(tr, seg)
        loop = asyncio.get_running_loop()
        takes = []
        for k in range(1, n + 1):
            try:
                info = await loop.run_in_executor(self.tts_exec, self.res.run, ("tts",), self.dubber.synthesize, tr, seg,
                                                  seg.get("orig_db"), None, None, f".t{k}")
            except Exception:  # noqa: BLE001  una toma que falla no corta las demás
                diag.exception("editor.toma")
                continue
            if info:
                info["text"] = seg["translation"]
                takes.append(info)
        seg["takes"] = takes
        tr.save()
        vault = self._vault_of(tr.data["id"])
        await self.ws.send_json({"type": "takes", "id": seg["id"],
                                 "items": [{"url": vault.url("/audio/" + t["file"]), "dur": t["dur"]} for t in takes]})

    async def _seg_take(self, m: dict):
        tr, seg = self._edit_target(m)
        takes = (seg or {}).get("takes") or []
        try:
            k = int(float(m.get("k")))
        except (TypeError, ValueError, OverflowError):
            return
        if not 0 <= k < len(takes) or takes[k].get("text") != seg.get("translation"):
            return
        seg["dub"] = dict(takes[k])
        tr.save()
        await self.ws.send_json(self._dub_msg(tr, seg, seg["dub"]))
