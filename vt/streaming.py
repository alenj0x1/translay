"""Transcripción en streaming sincronizada con el tiempo del video.

Política (diseño propio, inspirada en "local agreement"):

* El audio llega en bloques de ~100 ms con su tiempo de medio (segundos del
  video). Se acumula en un búfer cuyo inicio es `t0`.
* Cada `step_s` de audio nuevo se re-transcribe el búfer completo. Las palabras
  que coinciden entre dos hipótesis consecutivas se **confirman**; el resto se
  muestra como **tentativo**.
* Una frase se **cierra** (evento `Segment`) al confirmar un final de oración,
  al detectar silencio tras la voz, o al superar `max_segment_s`.
* Al cerrar, el búfer se recorta: todo lo anterior a `final_t` es definitivo.
  Ese valor permite a la sesión saber qué tramos del video ya están cubiertos.
"""

import re
from dataclasses import dataclass, field

import numpy as np

from .asr import Word
from .vad import FRAME, SR, EnergyVAD

_SENT_END = re.compile(r"[.!?…][\"')\]]*$")
_CLAUSE_END = re.compile(r"[,;:—–-][\"')\]]*$")
_NORM = re.compile(r"[^\w']+")

# palabras con las que una oración inglesa casi nunca termina: tras ellas, una
# pausa + mayúscula es un nombre propio ("translated into Spanish"), no un corte
_NO_END = {
    "a", "an", "the", "to", "of", "in", "into", "on", "onto", "at", "by", "for", "from",
    "with", "about", "as", "and", "or", "but", "nor", "so", "than", "that", "if", "my",
    "your", "our", "their", "his", "her", "its", "is", "are", "was", "were", "be", "been",
    "am", "will", "would", "can", "could", "should", "has", "have", "had", "do", "does",
    "did", "not", "very", "like", "called", "named", "visit", "visited", "use", "using",
}
# palabras comunes que tras una coma van en minúscula ("watching, see you")
_LOWER_AFTER_COMMA = {
    "see", "the", "and", "but", "so", "we", "you", "it", "that", "this", "then", "they",
    "he", "she", "there", "what", "how", "a", "an", "in", "on", "to", "for", "or", "which",
}

# frases que Whisper inventa sobre silencio o ruido en los bordes del audio
_HALLUCINATIONS = {
    "you", "thank", "thank you", "thanks", "thank you very much", "thanks for watching",
    "thank you for watching", "bye", "okay", "so", "the end", "uh", "um",
}


def _norm(w: Word) -> str:
    return _NORM.sub("", w.text.lower())


def _text(words: list[Word]) -> str:
    return "".join(w.text for w in words).strip()


@dataclass
class Config:
    step_s: float = 0.5          # audio nuevo mínimo entre inferencias
    min_audio_s: float = 1.0     # búfer mínimo para la primera inferencia
    silence_close_s: float = 0.6 # silencio final que cierra la frase
    min_new_speech_s: float = 0.3  # voz nueva mínima para consultar al ASR
    pause_cut_s: float = 0.4     # pausa entre palabras que corta la frase
    max_segment_s: float = 12.0  # duración máxima de una frase sin puntuación
    max_buffer_s: float = 24.0   # Whisper procesa ventanas de 30 s
    prompt_chars: int = 200      # contexto previo pasado como prompt
    gap_s: float = 0.5           # salto de tiempo que se considera discontinuidad


@dataclass
class Segment:
    start: float
    end: float
    text: str
    audio: np.ndarray | None = field(default=None, repr=False)  # voz original 16 kHz


@dataclass
class Partial:
    committed: str
    tentative: str


class StreamingTranscriber:
    def __init__(self, asr, cfg: Config | None = None, vad: EnergyVAD | None = None, language: str = "en"):
        self.asr = asr
        self.language = language  # el que se habla en el video (Transcript.lang)
        self.cfg = cfg or Config()
        self.vad = vad or EnergyVAD()
        self.context = ""
        self.reset(0.0)

    # ------------------------------------------------------------------ estado
    def reset(self, t0: float = 0.0, keep_context: bool = False):
        self.audio = np.zeros(0, np.float32)
        self.flags = np.zeros(0, bool)        # voz por trama, alineado con audio
        self.t0 = t0
        self.start_t = t0                     # inicio del tramo continuo actual
        self.final_t = t0                     # todo lo anterior es definitivo
        self.commit_t = t0                    # fin de la última palabra confirmada
        self.open: list[Word] = []            # confirmadas, frase aún abierta
        self.prev: list[Word] = []            # hipótesis tentativa anterior
        self.tail: list[str] = []             # últimas palabras confirmadas (dedupe)
        self._since = 0
        self._started = False
        if not keep_context:
            self.context = ""
        self.vad.reset()

    @property
    def end_t(self) -> float:
        return self.t0 + len(self.audio) / SR

    @property
    def duration(self) -> float:
        return len(self.audio) / SR

    def is_gap(self, t: float) -> bool:
        return self._started and abs(t - self.end_t) > self.cfg.gap_s

    def feed(self, t: float, pcm: np.ndarray):
        if not self._started:
            self._started = True
            self.t0 = self.final_t = self.commit_t = self.start_t = t
        elif len(self.audio) == 0:
            self.t0 = t
        self.audio = np.concatenate([self.audio, pcm])
        self.flags = np.concatenate([self.flags, self.vad.process(pcm)])
        self._since += len(pcm)

    def ready(self) -> bool:
        return (len(self.audio) >= self.cfg.min_audio_s * SR
                and self._since >= self.cfg.step_s * SR)

    # --------------------------------------------------------------- inferencia
    def step(self) -> list:
        self._since = 0
        events: list = []
        speech = np.flatnonzero(self.flags)
        if len(speech) == 0:
            # solo silencio: cerrar lo pendiente y no gastar GPU
            events += self._close(self.prev)
            self._trim_to(self.end_t - 0.3)
            self.final_t = max(self.final_t, self.t0)
            return events + [Partial("", "")]

        last_speech_t = self.t0 + (speech[-1] + 1) * FRAME / SR
        trailing = self.end_t - last_speech_t

        # casi sin voz nueva tras lo confirmado: Whisper tiende a repetir el
        # contexto previo ("episode.", "day."), así que no se le consulta
        c = max(0, int((self.commit_t - self.t0) * SR / FRAME))
        if self.flags[c:].sum() * FRAME / SR < self.cfg.min_new_speech_s:
            if trailing >= self.cfg.silence_close_s and (self.open or self.prev):
                events += self._close(self.prev, pause=True)
                self._trim_to(max(last_speech_t, self.commit_t))
                self.final_t = max(self.final_t, self.t0)
                return events + [Partial("", "")]
            return [Partial(_text(self.open), _text(self.prev))]

        hyp = self._hypothesis()
        self._refresh(hyp)
        fresh = self._uncommitted(hyp)

        if trailing >= self.cfg.silence_close_s:
            events += self._close(fresh, pause=True)
            self._trim_to(max(last_speech_t, self.commit_t))
            self.final_t = max(self.final_t, self.t0)
            return events + [Partial("", "")]

        # la última palabra de la hipótesis se retiene: aún puede ganar puntuación
        n, limit = 0, min(len(fresh) - 1, len(self.prev))
        while n < limit and _norm(fresh[n]) == _norm(self.prev[n]):
            n += 1
        self._commit(fresh[:n])
        self.prev = fresh[n:]
        events += self._cut()

        if self.duration > self.cfg.max_buffer_s:
            # sin cortar el audio de palabras confirmadas que aún no salieron en una frase
            cut = min(self.commit_t, self.open[0].start - 0.05) if self.open else self.commit_t
            if cut > self.t0 + 1.0:
                self._trim_to(cut)
            else:  # nada confirmado en 24 s: forzar cierre
                events += self._close(self.prev)
                self._trim_to(self.end_t)
        return events + [Partial(_text(self.open), _text(self.prev))]

    def flush(self) -> list:
        """Cierra todo lo pendiente (pausa, salto, fin del video)."""
        events: list = []
        if len(self.audio) >= 0.3 * SR and self.flags.any():
            hyp = self._hypothesis()
            self._refresh(hyp)
            events += self._close(self._uncommitted(hyp))
        else:
            events += self._close([])
        self._trim_to(self.end_t)
        self.final_t = max(self.final_t, self.end_t)
        return events + [Partial("", "")]

    def abort(self) -> list:
        """Salto del usuario: descarta la frase abierta para no guardarla truncada.

        `final_t` queda al final de la última frase cerrada, así ese tramo se
        vuelve a transcribir completo la próxima vez que se reproduzca.
        """
        self.open, self.prev = [], []
        return [Partial("", "")]

    # ---------------------------------------------------------------- internos
    def _hypothesis(self) -> list[Word]:
        prompt = self.context[-self.cfg.prompt_chars:] if self.context else None
        words = [w.shifted(self.t0) for w in self.asr.transcribe(self.audio, prompt, self.language)]
        # descartar palabras que caen donde el VAD no oyó voz (alucinaciones)
        out = []
        n = len(self.flags)
        for w in words:
            a = max(0, int((w.start - 0.2 - self.t0) * SR / FRAME))
            b = min(n, int((w.end + 0.2 - self.t0) * SR / FRAME) + 1)
            if a < b and self.flags[a:b].any():
                out.append(w)
        return out

    def _refresh(self, hyp: list[Word]):
        """Actualiza mayúsculas/puntuación de palabras ya confirmadas.

        Una palabra se confirma con la versión de una hipótesis temprana (p. ej.
        "guys" sin la coma ni el "Hey" previo); hipótesis posteriores, con más
        audio, suelen escribirla mejor.
        """
        # todo o nada: mezclar versiones de hipótesis distintas produce cosas
        # como "watching, See you"
        new, j = [], 0
        for w in self.open:
            while j < len(hyp) and hyp[j].end < w.start - 0.35:
                j += 1
            if j < len(hyp) and abs(hyp[j].start - w.start) < 0.35 and _norm(hyp[j]) == _norm(w):
                new.append(hyp[j].text)
                j += 1
            else:
                return
        for w, t in zip(self.open, new):
            w.text = t

    def _uncommitted(self, words: list[Word]) -> list[Word]:
        out = [w for w in words if (w.start + w.end) / 2 > self.commit_t - 0.02]
        if out and self.tail and out[0].start - self.commit_t < 1.0:
            for k in range(min(5, len(self.tail), len(out)), 0, -1):
                if [_norm(w) for w in out[:k]] == self.tail[-k:]:
                    out = out[k:]
                    break
        return out

    def _commit(self, words: list[Word]):
        if not words:
            return
        self.open += words
        self.commit_t = max(self.commit_t, words[-1].end)
        self.tail = (self.tail + [_norm(w) for w in words])[-5:]

    def _cut(self) -> list[Segment]:
        events = []
        while self.open:
            idx = None
            for i, w in enumerate(self.open):
                if w.end - self.open[0].start < 0.8:
                    continue
                if _SENT_END.search(w.text):
                    idx = i
                    break
                # Whisper suele omitir el punto al borde del búfer: una pausa
                # seguida de mayúscula también marca fin de oración
                nxt = self.open[i + 1] if i + 1 < len(self.open) else None
                if nxt is None or _CLAUSE_END.search(w.text):
                    continue
                gap = nxt.start - w.end
                head = nxt.text.strip()
                capital = (head[:1].isupper() and head.split("'")[0] != "I"
                           and _norm(w) not in _NO_END)
                if (capital and gap >= self.cfg.pause_cut_s / 2) or gap >= self.cfg.pause_cut_s:
                    if capital:
                        w.text += "."
                    idx = i
                    break
            if idx is None and self.open[-1].end - self.open[0].start > self.cfg.max_segment_s:
                clauses = [i for i, w in enumerate(self.open) if _CLAUSE_END.search(w.text)]
                idx = clauses[-1] if clauses else len(self.open) - 1
            if idx is None:
                break
            seg, self.open = self.open[: idx + 1], self.open[idx + 1:]
            events += self._emit(seg)
            self._trim_to(seg[-1].end)
            self.final_t = max(self.final_t, seg[-1].end)
        return events

    def _close(self, fresh: list[Word], pause: bool = False) -> list[Segment]:
        self._commit(fresh)
        self.prev = []
        events = self._cut()
        if self.open:
            last = self.open[-1]
            if pause and len(self.open) >= 3 and not re.search(r"[.!?…,;:]\W*$", last.text):
                last.text += "."  # una pausa clara tras la voz cierra la oración
            events += self._emit(self.open)
            self.final_t = max(self.final_t, self.open[-1].end)
            self.open = []
        return events

    def _emit(self, words: list[Word]) -> list[Segment]:
        for a, b in zip(words, words[1:]):
            if a.text.endswith(",") and _norm(b) in _LOWER_AFTER_COMMA and b.text.strip()[:1].isupper():
                b.text = b.text.lower()
        text = _text(words)
        key = " ".join(_norm(w) for w in words)
        if key in _HALLUCINATIONS and float(np.mean([w.prob for w in words])) < 0.9:
            return []
        if text[:1].islower() and (not self.context or _SENT_END.search(self.context)):
            text = text[0].upper() + text[1:]
        self.context = (self.context + " " + text).strip()[-1000:]
        a = max(0, int((words[0].start - 0.05 - self.t0) * SR))
        b = max(a, int((words[-1].end + 0.1 - self.t0) * SR))
        clip = self.audio[a:b].copy() if b > a else None
        return [Segment(round(words[0].start, 3), round(words[-1].end, 3), text, clip)]

    def _trim_to(self, t: float):
        frames = int((t - self.t0) * SR) // FRAME
        if frames <= 0:
            return
        frames = min(frames, len(self.flags), len(self.audio) // FRAME)
        if frames <= 0:
            return
        self.audio = self.audio[frames * FRAME:]
        self.flags = self.flags[frames:]
        self.t0 += frames * FRAME / SR
