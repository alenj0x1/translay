"""Detector de voz por energía con piso de ruido adaptativo.

Trabaja en tramas de 30 ms a 16 kHz. Su función es evitar que el ASR corra
sobre silencio (donde Whisper alucina) y detectar pausas que cierran frases.
Es deliberadamente simple: la interfaz `process(pcm) -> flags` permite cambiarlo
luego por un VAD neuronal sin tocar el resto.
"""

import numpy as np

SR = 16000
FRAME = 480  # 30 ms


class EnergyVAD:
    def __init__(self, margin_db=10.0, abs_min_db=-48.0, floor_min_db=-75.0,
                 hangover_frames=8):
        self.margin_db = margin_db
        self.abs_min_db = abs_min_db
        self.floor_min_db = floor_min_db
        self.hangover_frames = hangover_frames
        self.reset()

    def reset(self):
        self.floor = -60.0
        self._hang = 0
        self._rem = np.zeros(0, np.float32)

    def process(self, pcm: np.ndarray) -> np.ndarray:
        """Devuelve un flag de voz por cada trama completa de 30 ms."""
        buf = np.concatenate([self._rem, pcm]) if len(self._rem) else pcm
        n = len(buf) // FRAME
        self._rem = buf[n * FRAME:].copy()
        if n == 0:
            return np.zeros(0, bool)
        frames = buf[: n * FRAME].reshape(n, FRAME)
        db = 10.0 * np.log10(np.mean(frames * frames, axis=1) + 1e-10)
        flags = np.empty(n, bool)
        for i, d in enumerate(db):
            # el piso baja rápido y sube lento (constante ~10 s)
            if d < self.floor:
                self.floor = 0.7 * self.floor + 0.3 * d
            else:
                self.floor += 0.003 * (d - self.floor)
            self.floor = max(self.floor, self.floor_min_db)
            speech = d > max(self.floor + self.margin_db, self.abs_min_db)
            if speech:
                self._hang = self.hangover_frames
            elif self._hang > 0:
                self._hang -= 1
                speech = True
            flags[i] = speech
        return flags
