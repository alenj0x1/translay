"""Etapa de traducción, de un idioma de origen al de destino (`vt/langs.py`).

Todos los traductores comparten la interfaz `translate(text, context) -> str`
y corren sobre CTranslate2 (misma GPU que Whisper). Cada traductor sirve un par
(origen → destino). Familias soportadas:

* Marian / Opus-MT (Helsinki-NLP): pequeños y muy rápidos. De un par (`en-es`) o
  multilingües con etiqueta de destino al inicio (`>>spa<<`).
* NLLB-200 (Meta): multilingüe, tokens de idioma (`por_Latn` → `spa_Latn`).
* MADLAD-400 (Google, T5): multilingüe, prefijo de destino (`<2es>`).
"""

import threading
from pathlib import Path
from typing import Protocol

from . import langs
from .gpu import enable_cuda_dlls
from .glossary import Glossary
from .textproc import match_shape, polish, preedit, split_sentences

ANY = None  # pares: cualquier origen y destino del registro de idiomas
_ITC = ("es", "pt", "fr", "it", "ca", "ro", "gl")  # lenguas romances de Opus-MT itc-itc

# nombre → (familia, repo, precisión, pares). La precisión se eligió midiendo con
# tools/eval_translation.py: cuantizar Opus-big a int8 empeora la traducción.
# repo «opus:…» es una publicación oficial de OPUS-MT que se convierte aquí (vt/opusmt.py);
# también puede ser una carpeta local con un modelo CTranslate2.
MODELS = {
    "opus-base": ("marian", "michaelfeil/ct2fast-opus-mt-en-es", "float16", {("en", "es")}),
    "opus-big": ("marian", "ooeoeo/opus-mt-tc-big-en-es-ct2-float16", "float16", {("en", "es")}),
    "opus-itc": ("marian", "opus:itc-itc", "float16", {(a, b) for a in _ITC for b in _ITC if a != b}),
    "nllb-1.3b": ("nllb", "OpenNMT/nllb-200-distilled-1.3B-ct2-int8", "int8_float16", ANY),
    "madlad-3b": ("madlad", "Nextcloud-AI/madlad400-3b-mt-ct2-int8", "int8_float16", ANY),
}

# traductor de cada idioma de origen (al español), según tools/lab/langs_mt.py:
# «big» para los perfiles de calidad, «base» para los ligeros. Un idioma sin ruta usa
# FALLBACK, que traduce cualquier par.
ROUTES = {
    "en": {"big": "opus-big", "base": "opus-base"},
    "pt": {"big": "opus-itc", "base": "opus-itc"},  # chrF 54.3, como MADLAD-3B (54.5) y 10× más rápido
}
FALLBACK = "nllb-1.3b"


_FILES = ["*.json", "*.bin", "*.spm", "*.model", "*.txt"]  # lo que usa CTranslate2 de cada repo


def model_dir(repo: str, download: bool = True) -> Path | None:
    """Carpeta del modelo: una publicación de OPUS-MT convertida aquí («opus:…»), una carpeta local o un
    repo de Hugging Face. download=False solo mira si ya está (None si falta)."""
    if repo.startswith("opus:"):
        from .opusmt import ensure, models_dir
        if download:
            return ensure(repo[5:])
        path = models_dir() / f"opus-{repo[5:]}"
        return path if (path / "model.bin").exists() else None
    if Path(repo).is_dir():
        return Path(repo)
    from huggingface_hub import snapshot_download
    try:
        return Path(snapshot_download(repo, allow_patterns=_FILES, local_files_only=not download))
    except Exception:  # noqa: BLE001 — sin descargar: no está en la caché
        if download:
            raise
        return None


def supports(model: str, src: str, tgt: str) -> bool:
    # un repo que no está en MODELS (--translator) se toma como Marian inglés → español; una
    # carpeta local (labs) puede ser de cualquier par
    if model not in MODELS and Path(model).is_dir():
        return True
    pairs = MODELS[model][3] if model in MODELS else {("en", langs.TARGET)}
    return pairs is ANY or (src, tgt) in pairs


def route(src: str, tier: str = "big", tgt: str = langs.TARGET) -> str:
    """Traductor para un idioma de origen."""
    name = ROUTES.get(src, {}).get(tier) or FALLBACK
    return name if supports(name, src, tgt) else FALLBACK


class Translator(Protocol):
    name: str

    def translate(self, text: str, context: str = "") -> str | None: ...


class NullTranslator:
    name = "none"

    def load(self):
        pass

    def unload(self):
        pass

    def translate(self, text: str, context: str = "", glossary=None) -> str | None:
        return None

    def translate_many(self, texts: list[str], glossary=None) -> list[str | None]:
        return [None] * len(texts)


class CT2Translator:
    """Traductor seq2seq sobre CTranslate2."""

    def __init__(self, model: str = "opus-big", device: str = "cuda",
                 compute_type: str | None = None, beam_size: int = 4, src: str = "en", tgt: str = langs.TARGET):
        enable_cuda_dlls()
        import ctranslate2

        family, repo, default_ct, _ = MODELS.get(model, ("marian", model, "float16", ANY))
        if not supports(model, src, tgt):
            raise ValueError(f"el traductor {model} no traduce {src}→{tgt}")
        compute_type = compute_type or default_ct
        self.name = model
        self.family = family
        self.beam_size = beam_size
        self.src, self.tgt = langs.get(src), langs.get(tgt)
        path = model_dir(repo)
        self.model = ctranslate2.Translator(str(path), device=device, compute_type=compute_type)
        self._lock = threading.Lock()

        if family == "marian":
            import sentencepiece as spm
            self._src = spm.SentencePieceProcessor(model_file=str(path / "source.spm"))
            self._tgt = spm.SentencePieceProcessor(model_file=str(path / "target.spm"))
            # multilingüe: la oración empieza con la etiqueta del destino (>>spa<<)
            vocab = path / "shared_vocabulary.json"
            tag = f">>{self.tgt.iso3}<<"
            self._tag = [tag] if vocab.exists() and f'"{tag}"' in vocab.read_text(encoding="utf-8") else []
        elif family == "madlad":
            import sentencepiece as spm
            self._src = self._tgt = spm.SentencePieceProcessor(model_file=str(path / "spiece.model"))
        elif family == "nllb":
            from tokenizers import Tokenizer
            self._tok = Tokenizer.from_file(str(path / "tokenizer.json"))
        else:
            raise ValueError(f"familia desconocida: {family}")

    # reposo: los pesos pasan a la RAM y vuelven en ~1 s (ver vt/resources.py)
    def load(self):
        if not self.model.model_is_loaded:
            self.model.load_model()

    def unload(self):
        if self.model.model_is_loaded:
            self.model.unload_model(to_cpu=True)

    # ----------------------------------------------------------- tokenización
    def _encode(self, text: str) -> list[str]:
        if self.family == "marian":
            return self._tag + self._src.encode(text, out_type=str) + ["</s>"]
        if self.family == "madlad":
            return self._src.encode(f"<2{self.tgt.code}> " + text, out_type=str) + ["</s>"]
        return [self.src.nllb] + self._tok.encode(text, add_special_tokens=False).tokens + ["</s>"]

    def _decode(self, tokens: list[str]) -> str:
        if self.family == "nllb":
            tokens = [t for t in tokens if t != self.tgt.nllb]
            ids = [self._tok.token_to_id(t) for t in tokens]
            return self._tok.decode([i for i in ids if i is not None])
        return self._tgt.decode(tokens)

    # ------------------------------------------------------------- traducción
    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        src = [self._encode(t) for t in texts]
        prefix = [[self.tgt.nllb]] * len(texts) if self.family == "nllb" else None
        with self._lock:
            res = self.model.translate_batch(
                src, target_prefix=prefix, beam_size=self.beam_size,
                max_decoding_length=256, repetition_penalty=1.1, no_repeat_ngram_size=4,
            )
        return [self._decode(r.hypotheses[0]) for r in res]

    def translate_many(self, texts: list[str], batch: int = 24, glossary=None) -> list[str | None]:
        """Traduce varias frases; cada una se divide en oraciones y se re-arma."""
        sents, owner = [], []
        for i, t in enumerate(texts):
            for s in split_sentences(t or "", self.src.code):
                sents.append(s)
                owner.append(i)
        # glosario propio (vt/glossary.py): los términos pasan como marcadores intactos
        # el de la biblioteca del video (cada biblioteca tiene el suyo)
        gl = glossary if glossary is not None else getattr(self, "glossary", None)
        guarded = [gl.protect(preedit(s, self.src.code)) if gl else (preedit(s, self.src.code), []) for s in sents]
        outs: list[str] = []
        for k in range(0, len(sents), batch):
            outs += self.translate_batch([g[0] for g in guarded[k:k + batch]])
        pieces: list[list[str]] = [[] for _ in texts]
        for i, s, es, (_, repl) in zip(owner, sents, outs, guarded):
            pieces[i].append(match_shape(s, polish(Glossary.restore(es, repl))))
        return [" ".join(p) if p else None for p in pieces]

    def translate(self, text: str, context: str = "", glossary=None) -> str | None:
        return self.translate_many([text], glossary=glossary)[0]


def load_translator(name: str, device: str = "cuda", compute_type: str | None = None,
                    src: str = "en", tgt: str = langs.TARGET) -> Translator:
    """compute_type: None = el del modelo; en CPU, int8 (float16 no corre en CPU)."""
    if name in ("", "none"):
        return NullTranslator()
    if device == "cpu" and compute_type in (None, "float16", "int8_float16"):
        compute_type = "int8"
    return CT2Translator(name, device=device, compute_type=compute_type, src=src, tgt=tgt)


class Translators:
    """Un traductor por idioma de origen, creado la primera vez que se necesita.

    Solo uno ocupa la GPU a la vez: al pasar a otro idioma, el anterior va a la RAM
    (vuelve en ~1 s), así la memoria medida en los perfiles no crece con los idiomas.
    `load`/`unload` son los de vt/resources.py (reposo). Se usa desde el hilo de la GPU.

    tier: «big» o «base» (de ROUTES). force: un modelo para todos los idiomas que traduce
    (--translator); «none» no traduce.
    """

    def __init__(self, tier: str = "big", device: str = "cuda", compute_type: str | None = None,
                 force: str | None = None, tgt: str = langs.TARGET):
        self.tier, self.device, self.compute_type, self.force, self.tgt = tier, device, compute_type, force, tgt
        self._by_lang: dict[str, Translator] = {}
        self._active: str | None = None
        self._ready: set[str] = set()  # modelos ya descargados
        self._lock = threading.RLock()
        self._sleeping = False

    @property
    def name(self) -> str:
        """El del inglés (compatibilidad: estado e información del servidor)."""
        return self.name_for("en")

    def name_for(self, src: str) -> str:
        if self.force == "none":
            return "none"
        if self.force and supports(self.force, src, self.tgt):
            return self.force
        return route(src, self.tier, self.tgt)

    def prepare(self, src: str):
        """Descarga (o convierte) el traductor de un idioma, si falta. Fuera del hilo de la
        GPU: bajar ~0.8-1.4 GB no puede frenar el reconocimiento ni la voz de otro video."""
        name = self.name_for(src)
        if name in self._ready or name == "none" or name not in MODELS:
            return
        model_dir(MODELS[name][1])
        self._ready.add(name)

    def ready(self, src: str) -> bool:
        """¿Está descargado el traductor de este idioma? (sin descargar nada)"""
        name = self.name_for(src)
        if name in self._ready or name in self._by_lang or name == "none" or name not in MODELS:
            return True
        if model_dir(MODELS[name][1], download=False) is None:
            return False
        self._ready.add(name)
        return True

    def get(self, src: str) -> Translator:
        with self._lock:
            name = self.name_for(src)
            t = self._by_lang.get(name)
            if t is None:
                # los modelos que sirven a varios idiomas se comparten (opus-itc, nllb)
                t = load_translator(name, self.device, self.compute_type, src=src, tgt=self.tgt)
                self._by_lang[name] = t
                self._ready.add(name)
            if isinstance(t, CT2Translator):
                t.src = langs.get(src)  # mismo modelo, otro origen (reglas de texto, token de NLLB)
            if self._active != name:
                if self._active in self._by_lang:
                    self._by_lang[self._active].unload()
                if not self._sleeping:
                    t.load()
                self._active = name
            return t

    def translate(self, text: str, context: str = "", glossary=None, src: str = "en") -> str | None:
        return self.get(src).translate(text, context, glossary=glossary)

    def translate_many(self, texts: list[str], glossary=None, src: str = "en") -> list[str | None]:
        return self.get(src).translate_many(texts, glossary=glossary)

    def load(self):
        with self._lock:
            self._sleeping = False
            if self._active in self._by_lang:
                self._by_lang[self._active].load()

    def unload(self):
        with self._lock:
            self._sleeping = True
            for t in self._by_lang.values():
                t.unload()
