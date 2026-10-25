"""Motor de reconocimiento de voz (ASR).

Envuelve Whisper (pesos convertidos a CTranslate2) detrás de una interfaz
mínima: audio float32 16 kHz → lista de palabras con tiempos. El streaming,
la segmentación y la sincronía con el video viven en `vt.streaming`.
"""

from dataclasses import dataclass

import numpy as np

from .gpu import enable_cuda_dlls

MODELS = {
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium.en": "Systran/faster-whisper-medium.en",
    "small.en": "Systran/faster-whisper-small.en",
    "small": "Systran/faster-whisper-small",
    "base.en": "Systran/faster-whisper-base.en",
}


@dataclass
class Word:
    start: float
    end: float
    text: str  # incluye espacio inicial y puntuación, tal como lo emite Whisper
    prob: float = 1.0

    def shifted(self, dt: float) -> "Word":
        return Word(self.start + dt, self.end + dt, self.text, self.prob)


class WhisperASR:
    def __init__(self, model="large-v3-turbo", device="cuda",
                 compute_type="float16", beam_size=5, language="en"):
        enable_cuda_dlls()
        from faster_whisper import WhisperModel

        self.name = model
        self.device = device
        self.language = language
        self.beam_size = beam_size
        self.model = WhisperModel(MODELS.get(model, model), device=device,
                                  compute_type=compute_type)

    # reposo: los pesos pasan a la RAM y vuelven en ~1 s (ver vt/resources.py)
    def load(self):
        if not self.model.model.model_is_loaded:
            self.model.model.load_model()

    def unload(self):
        if self.model.model.model_is_loaded:
            self.model.model.unload_model(to_cpu=True)

    def warmup(self):
        self.transcribe(np.zeros(16000, np.float32))

    def transcribe(self, audio: np.ndarray, prompt: str | None = None) -> list[Word]:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            temperature=0.0,
            vad_filter=False,
        )
        words: list[Word] = []
        for s in segments:
            # descartes típicos de alucinación
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            if s.compression_ratio > 2.4:
                continue
            for w in s.words or []:
                words.append(Word(w.start, w.end, w.word, w.probability))
        return words
