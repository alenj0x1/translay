"""vt — traductor de video EN→ES en tiempo real.

Etapas del pipeline (cada una reemplazable de forma independiente):

    audio (navegador) → VAD → ASR en streaming → traducción → (futuro) voz ES

Fase 1: solo detección de texto (ASR). La traducción existe como interfaz
(`vt.translate`) con una implementación nula.
"""

__version__ = "0.1.0"
