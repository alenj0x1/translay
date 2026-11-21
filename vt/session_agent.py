"""El agente del video desde la pestaña: preguntas, dictado por micrófono y el contexto para
otro agente.

Parte de Session (vt/session.py): sus métodos usan el estado de la sesión (self)."""

import asyncio
import numpy as np
from functools import partial
from pathlib import Path
from . import i18n, langs
from .store import _SAFE_ID as _SAFE_VID

DICTATE_BYTES = 4 * 1024 * 1024  # ~1 min de opus con holgura (llega en base64 por el WebSocket)
DICTATE_S = 60                  # el dictado del chat del agente: hasta un minuto por vez


class AgentMixin:
    @property
    def _agent(self):
        return getattr(self.processor, "agent", None) if self.processor else None

    async def _agent_msg(self, m: dict):
        """El agente del video (vt/agentsvc.py): abrir la conversación, preguntar, detener o borrarla."""
        vid = str(m.get("video", ""))
        v = self.vaults.of(vid) if _SAFE_VID.match(vid) else None
        if not v or not self.access.can_view(v.id):
            return
        ag, t = self._agent, m["type"]
        pos = m.get("position") if isinstance(m.get("position"), (int, float)) else None
        loop = asyncio.get_running_loop()
        if t == "agent_open":
            out = await loop.run_in_executor(None, ag.public, vid, pos)
            await self.ws.send_json({"type": "agent_chat", "video": vid, **out})
        elif t == "agent_ask" and str(m.get("q", "")).strip():
            ag.ask(vid, str(m["q"]), pos, str(m.get("id", ""))[:40])
        elif t == "agent_continue":
            ag.ask(vid, "", pos, str(m.get("id", ""))[:40], cont=True)
        elif t == "agent_stop":
            ag.stop()
        elif t == "agent_power":
            await loop.run_in_executor(None, ag.power, bool(m.get("on")), vid, pos)
        elif t == "agent_dictate":
            await self._dictate(vid, m)
        elif t == "agent_clear":
            await loop.run_in_executor(None, ag.clear, vid)
            out = await loop.run_in_executor(None, ag.public, vid, pos)
            await self.ws.send_json({"type": "agent_chat", "video": vid, **out})

    async def _dictate(self, vid: str, m: dict):
        """Dictado en el chat del agente: el audio grabado en el navegador (base64, hasta DICTATE_S) se
        transcribe con el mismo Whisper de Translay, en la cola de la GPU, en el idioma de destino."""
        import base64
        import tempfile

        from .processor import SR, decode_audio

        qid = str(m.get("id", ""))[:40]

        async def reply(text="", error=""):
            await self.ws.send_json({"type": "agent_dictated", "video": vid, "id": qid, "text": text, "error": error})

        asr = self.st.asr
        if asr.name.endswith(".en"):
            return await reply(error=i18n.t(
                "El dictado necesita un modelo de reconocimiento en {language}. Elige otro perfil en Ajustes › Rendimiento.",
                language=langs.name(langs.target(), langs.ui())))
        try:
            raw = base64.b64decode(str(m.get("audio", "")), validate=True)
        except ValueError:
            return await reply(error=i18n.t("No se pudo leer la grabación."))
        if not raw or len(raw) > DICTATE_BYTES:
            return await reply(error=i18n.t("La grabación supera un minuto. Dicta en partes más cortas."))
        loop = asyncio.get_running_loop()

        def decode() -> np.ndarray:
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "dictado.webm"
                f.write_bytes(raw)
                return decode_audio(f)[: DICTATE_S * SR]

        try:
            audio = await loop.run_in_executor(None, decode)
        except Exception:
            return await reply(error=i18n.t("No se pudo leer la grabación."))
        if audio.size < SR // 4:
            return await reply()
        words = await loop.run_in_executor(self.gpu, self.res.run, ("asr",),
                                           partial(asr.transcribe, audio, None, langs.target()))
        await reply(text="".join(w.text for w in words).strip())

    async def _agent_context(self, m: dict):
        """«Copiar para un agente»: todo el video en Markdown (vt/videocontext.py), con hasta dónde se vio."""
        vid = str(m.get("video", ""))
        v = self.vaults.of(vid) if _SAFE_VID.match(vid) else None
        if not v or not self.access.can_view(v.id):
            return
        pos = m.get("position")

        def build():
            from .videocontext import markdown

            screen = self.processor.screen.load(vid) if self.processor and self.processor.screen else None
            return markdown(v.library.data["videos"].get(vid) or {}, v.store.open(vid), screen,
                            float(pos) if isinstance(pos, (int, float)) else None)
        text = await asyncio.get_running_loop().run_in_executor(None, build)
        await self.ws.send_json({"type": "agent_context", "video": vid, "text": text})
