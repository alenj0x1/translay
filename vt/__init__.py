"""vt — servidor de Translay: traduce y dobla videos del inglés al español.

Etapas del pipeline (cada una reemplazable de forma independiente):

    audio → VAD → reconocimiento en streaming (Whisper) → traducción (Opus-MT)
          → diarización (WeSpeaker) → voz clonada (OmniVoice, proceso aparte)

Arquitectura: docs/src/content/docs/funcionamiento/arquitectura.mdx
"""

__version__ = "1.1.0"
