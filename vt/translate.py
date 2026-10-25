"""Etapa de traducción EN→ES.

Todos los traductores comparten la interfaz `translate(text, context) -> str`
y corren sobre CTranslate2 (misma GPU que Whisper). Familias soportadas:

* Marian / Opus-MT (Helsinki-NLP): pequeños y muy rápidos.
* NLLB-200 (Meta): multilingüe, tokens de idioma `eng_Latn` → `spa_Latn`.
* MADLAD-400 (Google, T5): prefijo `<2es>`.
"""

import threading
from pathlib import Path
from typing import Protocol

from .gpu import enable_cuda_dlls
from .textproc import match_shape, polish, preedit, split_sentences

# nombre → (familia, repo, precisión). La precisión se eligió midiendo con
# tools/eval_translation.py: cuantizar Opus-big a int8 empeora la traducción.
MODELS = {
    "opus-base": ("marian", "michaelfeil/ct2fast-opus-mt-en-es", "float16"),
    "opus-big": ("marian", "ooeoeo/opus-mt-tc-big-en-es-ct2-float16", "float16"),
    "nllb-1.3b": ("nllb", "OpenNMT/nllb-200-distilled-1.3B-ct2-int8", "int8_float16"),
    "madlad-3b": ("madlad", "Nextcloud-AI/madlad400-3b-mt-ct2-int8", "int8_float16"),
}


class Translator(Protocol):
    name: str

    def translate(self, text: str, context: str = "") -> str | None: ...


class NullTranslator:
    name = "none"

    def translate(self, text: str, context: str = "") -> str | None:
        return None

    def translate_many(self, texts: list[str]) -> list[str | None]:
        return [None] * len(texts)


class CT2Translator:
    """Traductor seq2seq sobre CTranslate2."""

    def __init__(self, model: str = "opus-big", device: str = "cuda",
                 compute_type: str | None = None, beam_size: int = 4):
        enable_cuda_dlls()
        import ctranslate2
        from huggingface_hub import snapshot_download

        family, repo, default_ct = MODELS.get(model, ("marian", model, "float16"))
        compute_type = compute_type or default_ct
        self.name = model
        self.family = family
        self.beam_size = beam_size
        path = Path(snapshot_download(repo, allow_patterns=["*.json", "*.bin", "*.spm", "*.model", "*.txt"]))
        self.model = ctranslate2.Translator(str(path), device=device, compute_type=compute_type)
        self._lock = threading.Lock()

        if family == "marian":
            import sentencepiece as spm
            self._src = spm.SentencePieceProcessor(model_file=str(path / "source.spm"))
            self._tgt = spm.SentencePieceProcessor(model_file=str(path / "target.spm"))
        elif family == "madlad":
            import sentencepiece as spm
            self._src = self._tgt = spm.SentencePieceProcessor(model_file=str(path / "spiece.model"))
        elif family == "nllb":
            from tokenizers import Tokenizer
            self._tok = Tokenizer.from_file(str(path / "tokenizer.json"))
        else:
            raise ValueError(f"familia desconocida: {family}")

    # ----------------------------------------------------------- tokenización
    def _encode(self, text: str) -> list[str]:
        if self.family == "marian":
            return self._src.encode(text, out_type=str) + ["</s>"]
        if self.family == "madlad":
            return self._src.encode("<2es> " + text, out_type=str) + ["</s>"]
        return ["eng_Latn"] + self._tok.encode(text, add_special_tokens=False).tokens + ["</s>"]

    def _decode(self, tokens: list[str]) -> str:
        if self.family == "nllb":
            tokens = [t for t in tokens if t != "spa_Latn"]
            ids = [self._tok.token_to_id(t) for t in tokens]
            return self._tok.decode([i for i in ids if i is not None])
        return self._tgt.decode(tokens)

    # ------------------------------------------------------------- traducción
    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        src = [self._encode(t) for t in texts]
        prefix = [["spa_Latn"]] * len(texts) if self.family == "nllb" else None
        with self._lock:
            res = self.model.translate_batch(
                src, target_prefix=prefix, beam_size=self.beam_size,
                max_decoding_length=256, repetition_penalty=1.1, no_repeat_ngram_size=4,
            )
        return [self._decode(r.hypotheses[0]) for r in res]

    def translate_many(self, texts: list[str], batch: int = 24) -> list[str | None]:
        """Traduce varias frases; cada una se divide en oraciones y se re-arma."""
        sents, owner = [], []
        for i, t in enumerate(texts):
            for s in split_sentences(t or ""):
                sents.append(s)
                owner.append(i)
        outs: list[str] = []
        for k in range(0, len(sents), batch):
            outs += self.translate_batch([preedit(s) for s in sents[k:k + batch]])
        pieces: list[list[str]] = [[] for _ in texts]
        for i, s, es in zip(owner, sents, outs):
            pieces[i].append(match_shape(s, polish(es)))
        return [" ".join(p) if p else None for p in pieces]

    def translate(self, text: str, context: str = "") -> str | None:
        return self.translate_many([text])[0]


def load_translator(name: str, device: str = "cuda") -> Translator:
    if name in ("", "none"):
        return NullTranslator()
    return CT2Translator(name, device=device)
