"""Diarización en línea: quién habla en cada frase, y su voz de referencia.

* `fbank`: banco de filtros mel tipo Kaldi (80 bandas, 25/10 ms), propio.
* `SpeakerEmbedder`: huella de voz de 256 dimensiones con WeSpeaker ResNet34
  (ONNX, CPU, ~10 ms por frase).
* `SpeakerTracker`: agrupa frases por persona de forma incremental (similitud
  coseno contra centroides) y junta, por persona, los mejores fragmentos de su
  voz original — los más largos y limpios — para clonarla en español.
"""

import numpy as np

from .audiofx import denoise, snr_estimate, trim_silence

SR = 16000


def _mel_banks(n_mels=80, n_fft=512, sr=SR, low=20.0, high=None):
    high = high or sr / 2
    mel = lambda f: 1127.0 * np.log(1 + f / 700.0)  # noqa: E731
    m_lo, m_hi = mel(low), mel(high)
    centers = np.linspace(m_lo, m_hi, n_mels + 2)
    fft_mel = mel(np.arange(n_fft // 2 + 1) * sr / n_fft)
    banks = np.zeros((n_mels, n_fft // 2 + 1))
    for i in range(n_mels):
        l, c, r = centers[i], centers[i + 1], centers[i + 2]
        up = (fft_mel - l) / (c - l)
        down = (r - fft_mel) / (r - c)
        banks[i] = np.maximum(0, np.minimum(up, down))
    return banks


_BANKS = _mel_banks()


def fbank(x: np.ndarray) -> np.ndarray:
    """Fbank Kaldi (snip_edges, hamming, preénfasis 0.97, potencia, log)."""
    x = x.astype(np.float64) * 32768.0
    win, hop, n_fft = 400, 160, 512
    if len(x) < win:
        return np.zeros((0, 80), np.float32)
    k = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(k)[:, None]
    fr = x[idx]
    fr = fr - fr.mean(axis=1, keepdims=True)
    fr = np.concatenate([fr[:, :1] * (1 - 0.97), fr[:, 1:] - 0.97 * fr[:, :-1]], axis=1)
    fr = fr * np.hamming(win)
    spec = np.abs(np.fft.rfft(fr, n=n_fft, axis=1)) ** 2
    feats = np.log(np.maximum(spec @ _BANKS.T, np.finfo(np.float32).eps))
    feats -= feats.mean(axis=0, keepdims=True)  # CMN
    return feats.astype(np.float32)


# Una referencia de voz larga vuelve lentísima la clonación cuando Whisper también
# ocupa la GPU (medido: 15 s → 61 s por frase; 9 s → 4 s). OmniVoice recomienda 3–10 s.
MAX_CLIP_S = 8.0


# Una referencia nunca se recorta: si el texto no coincide exactamente con el audio, el
# motor "continúa" la referencia y la voz generada arrastra las palabras sobrantes (se
# oía "and so" o "stands" en cada frase doblada). Solo se usan frases completas de hasta
# MAX_CLIP_S; una más larga (hasta MAX_FALLBACK_S) únicamente si la persona aún no tiene otra.
MAX_FALLBACK_S = 12.0


class SpeakerEmbedder:
    REPO = "onnx-community/wespeaker-voxceleb-resnet34-LM"

    def __init__(self):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(self.REPO, "onnx/model.onnx")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])

    def embed(self, x: np.ndarray) -> np.ndarray | None:
        if len(x) < SR * 0.6:
            return None
        f = fbank(x)
        e = self.sess.run(None, {"input_features": f[None]})[0][0]
        return e / (np.linalg.norm(e) + 1e-9)


class SpeakerTracker:
    """Agrupamiento incremental. Estado serializable para persistirlo por video."""

    def __init__(self, threshold: float = 0.30, min_new_s: float = 1.6, short_new: float = 0.15,
                 max_ref_s: float = 9.0, state: dict | None = None):
        self.threshold = threshold
        self.short_new = short_new
        self.merge_th = 0.5
        self.alias: dict[int, int] = {}
        self.min_new_s = min_new_s
        self.max_ref_s = max_ref_s
        self.speakers: list[dict] = []  # {id, sum, n}
        if state:
            self.alias = {int(k): v for k, v in state.get("alias", {}).items()}
            for s in state.get("speakers", []):
                self.speakers.append({"id": s["id"], "sum": np.array(s["sum"], np.float32), "n": s["n"],
                                      "long": s.get("long", 1)})
        self.refs: dict[int, list[tuple[float, np.ndarray, str]]] = {}
        self._next = (state or {}).get("next", len(self.speakers))

    def state(self) -> dict:
        return {"speakers": [{"id": s["id"], "sum": s["sum"].round(5).tolist(), "n": s["n"],
                              "long": int(s.get("long", 0))}
                             for s in self.speakers],
                "alias": {str(k): v for k, v in self.alias.items()},
                "next": self._next}

    def assign(self, emb: np.ndarray | None, dur: float = 3.0) -> tuple[int | None, float]:
        """Devuelve (id de persona, similitud). Sin huella fiable: (None, 0).

        Las frases cortas (< `min_new_s`) dan huellas poco fiables: nunca crean
        una persona nueva salvo que no se parezcan a nadie (< `short_new`), y
        nunca modifican centroides: se asignan a la más parecida.
        Los centroides se ponderan por duración (las frases largas pesan más).
        """
        if emb is None:
            return None, 0.0
        best, sim = None, -1.0
        for s in self.speakers:
            c = s["sum"] / (np.linalg.norm(s["sum"]) + 1e-9)
            v = float(c @ emb)
            if v > sim:
                best, sim = s, v
        short = dur < self.min_new_s
        if short and best is not None and sim >= self.short_new:
            return best["id"], sim  # no toca el centroide
        if best is None or sim < (self.short_new if short else self.threshold):
            best = {"id": self._next, "sum": np.zeros_like(emb), "n": 0}
            self._next += 1
            self.speakers.append(best)
            sim = 1.0
        best["sum"] = best["sum"] + emb * min(dur, 6.0)
        best["n"] += 1
        best["long"] = int(best.get("long", 0)) + int(dur >= self.min_new_s)
        return self._merge(best)["id"], sim

    def confirmed(self) -> list[tuple[int, np.ndarray]]:
        """(id, centroide) de las personas con al menos una frase larga."""
        return [(s["id"], self._centroid(s)) for s in self.speakers if s.get("long", 0) > 0]

    def _centroid(self, s: dict) -> np.ndarray:
        return s["sum"] / (np.linalg.norm(s["sum"]) + 1e-9)

    def _merge(self, s: dict) -> dict:
        """Une `s` con otra persona si sus huellas ya son casi iguales."""
        c = self._centroid(s)
        for o in self.speakers:
            if o is not s and float(self._centroid(o) @ c) > self.merge_th:
                keep, drop = (o, s) if o["id"] < s["id"] else (s, o)
                keep["sum"] = keep["sum"] + drop["sum"]
                keep["n"] += drop["n"]
                keep["long"] = keep.get("long", 0) + drop.get("long", 0)
                self.speakers.remove(drop)
                self.alias[drop["id"]] = keep["id"]
                self.refs.setdefault(keep["id"], []).extend(self.refs.pop(drop["id"], []))
                return keep
        return s

    def resolve(self, spk: int | None) -> int | None:
        while spk in self.alias:
            spk = self.alias[spk]
        return spk

    def voice_for(self, spk: int | None) -> int | None:
        """Persona cuya referencia usar: la propia, o la más parecida con referencia."""
        spk = self.resolve(spk)
        if spk is None or self.refs.get(spk):
            return spk
        me = next((s for s in self.speakers if s["id"] == spk), None)
        cands = [s for s in self.speakers if self.refs.get(s["id"])]
        if me is None or not cands:
            return None
        c = self._centroid(me)
        return max(cands, key=lambda o: float(self._centroid(o) @ c))["id"]

    def add_reference(self, spk: int, x: np.ndarray, text: str = "") -> bool:
        """Guarda el fragmento si mejora la referencia. True si la referencia cambió."""
        x = trim_silence(x, SR)
        dur = len(x) / SR
        if dur < 1.0:
            return False
        refs = self.refs.setdefault(spk, [])
        if dur > MAX_CLIP_S:  # frase larga: solo como último recurso, entera
            if refs or dur > MAX_FALLBACK_S:
                return False
        else:  # una frase de largo normal reemplaza a la de último recurso
            refs[:] = [r for r in refs if len(r[1]) / SR <= MAX_CLIP_S]
        score = min(dur, 6.0) * float(np.clip(snr_estimate(x, SR) / 30.0, 0.2, 1.0))
        total = sum(len(r[1]) for r in refs) / SR
        # con la referencia ya completa solo se cambia por un fragmento claramente
        # mejor: cada cambio obliga al motor a recalcular la voz (1–2 s de GPU)
        if total >= self.max_ref_s * 0.75 and score <= min(r[0] for r in refs) * 1.3:
            return False
        refs.append((score, x, text))
        refs.sort(key=lambda r: -r[0])
        while sum(len(r[1]) for r in refs) / SR > self.max_ref_s and len(refs) > 1:
            refs.pop()
        return True

    def reference(self, spk: int, clean: bool = False) -> tuple[np.ndarray, str] | None:
        """(audio de referencia, su transcripción) de la persona."""
        refs = self.refs.get(spk)
        if not refs:
            return None
        gap = np.zeros(int(SR * 0.15), np.float32)
        parts = []
        for r in refs:
            parts += [r[1], gap]
        x = np.concatenate(parts[:-1])
        text = " ".join(r[2] for r in refs if r[2])
        # la limpieza fina (DeepFilterNet) la hace el proceso de voz; la compuerta
        # propia resta identidad, por eso queda desactivada por defecto
        return (denoise(x, SR) if clean and snr_estimate(x, SR) < 25 else x), text
