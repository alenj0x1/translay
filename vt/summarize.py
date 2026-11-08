"""Resumen de un video: de qué se trató y todos sus puntos importantes, en español.

Corre sobre CTranslate2, el mismo motor de Whisper y del traductor (sin dependencias
nuevas), con un modelo de lenguaje pequeño. El modelo se elige según el equipo
(`recommend`) o en Preferencias › Resumen; los números salen de tools/lab/summary.py.

Cómo se arma (piezas propias):

1. Las frases se juntan en líneas con su minuto («[12:34] …»).
2. La transcripción se corta en tramos de ~1000 tokens del propio modelo; de cada tramo
   salen sus puntos importantes, cada uno con el minuto en que se dice. No hay un
   número fijo de puntos: un video largo tiene más tramos y, por eso, más puntos.
3. Con todos los puntos se escribe el panorama: de qué se trató el video. Si los puntos
   no caben en un tramo (un video de horas), primero se cuenta cada grupo en un párrafo y
   el panorama sale de esos párrafos: así ninguna llamada al modelo pasa de ~1000 tokens.

Los tramos se miden en tokens y no en palabras: el portugués usa más tokens por palabra, y
la atención crece con el cuadrado del largo. Con 1500 palabras en portugués la 4B llegaba a
6,8 GB y desbordaba la GPU de 8 GB (356 s); con tramos de 1000 tokens, 6,3 GB y la mitad del
tiempo por tramo, con la misma cantidad de puntos.

El minuto de cada punto se ajusta al de una frase real del tramo (un modelo pequeño
puede inventar uno). Se resume desde lo que se dice en el idioma original: los
modelos lo entienden mejor que una traducción, y escriben en español.

El resultado se guarda en la transcripción del video (`summary`), con el modelo y la
fecha; se vuelve a hacer solo si se pide.
"""

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import langs
from .gpu import enable_cuda_dlls


@dataclass(frozen=True)
class Model:
    name: str        # para la interfaz
    family: str      # plantilla de chat: «qwen» o «gemma»
    repo: str        # Hugging Face (CTranslate2 int8)
    think: bool      # modelo con «pensamiento»: se le pide responder sin pensar
    vram_mb: int     # pico medido en la GPU (tools/lab/summary.py)
    ram_mb: int      # pico medido en la CPU
    license: str


# de mejor a más liviano; el pico en la GPU (y en la RAM, en la CPU) medido con tools/lab/summary.py
MODELS: dict[str, Model] = {
    "qwen3-4b": Model("Qwen3 4B", "qwen", "jncraton/Qwen3-4B-Instruct-2507-ct2-int8", False, 6900, 5400, "Apache 2.0"),
    "qwen3-1.7b": Model("Qwen3 1.7B", "qwen", "jncraton/Qwen3-1.7B-ct2-int8", True, 3000, 2600, "Apache 2.0"),
    "qwen3-0.6b": Model("Qwen3 0.6B", "qwen", "jncraton/Qwen3-0.6B-ct2-int8", True, 1800, 1100, "Apache 2.0"),
}
ORDER = list(MODELS)
FILES = ["*.json", "*.bin"]

MARGIN_MB = 500      # además del pico medido de cada modelo (lo que usa el sistema en la GPU)
LINE_S = 30           # las frases se juntan en líneas de hasta ~30 s
CHUNK_TOKENS = 1000   # por tramo: con 1400 la 4B llegaba a 6,9 GB y tardaba el doble; con 1000, 6,3 GB
MAX_POINT_TOKENS = 700
MAX_OVERVIEW_TOKENS = 500
MAX_PART_TOKENS = 300

_TIME = re.compile(r"^\s*(?:[-*•]\s*)?\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–—:.)]?\s*(.+)$")


def recommend(hw: dict, limits: dict | None = None) -> str:
    """El mejor modelo que entra en el equipo: en la GPU si su pico cabe en ella (mientras resume
    tiene la GPU para sí, `Resources.exclusive`); si no, el 1.7B en la CPU (43 min de video en
    11 min con 6 hilos) y, solo si tampoco entra, el más liviano, que resume sin detalle."""
    limits = limits or {}
    gpu = hw.get("gpu") or {}
    vram = gpu.get("vram_total_mb") or 0
    if limits.get("vram_mb"):
        vram = min(vram, limits["vram_mb"]) if vram else 0
    ram = (hw.get("ram") or {}).get("total_mb") or 0
    if limits.get("ram_mb"):
        ram = min(ram, limits["ram_mb"]) if ram else limits["ram_mb"]
    for key in ORDER[:-1]:
        if vram and MODELS[key].vram_mb + MARGIN_MB <= vram:
            return key
    for key in ORDER[1:-1]:  # en la CPU, el de 4B es demasiado lento
        if ram and MODELS[key].ram_mb * 3 <= ram:
            return key
    return ORDER[-1]


def stamp(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def lines(segments: list[dict]) -> list[tuple[float, str]]:
    """Frases juntas en líneas de hasta LINE_S segundos: (inicio, texto)."""
    out: list[tuple[float, str]] = []
    start, buf = None, []
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        if start is not None and s["start"] - start >= LINE_S:
            out.append((start, " ".join(buf)))
            start, buf = None, []
        if start is None:
            start = s["start"]
        buf.append(text)
    if buf:
        out.append((start, " ".join(buf)))
    return out


def words(text: str) -> int:
    return round(len(text.split()) * 1.4)  # sin el tokenizador: ~1,4 tokens por palabra en inglés


def chunks(ls: list[tuple[float, str]], limit: int = CHUNK_TOKENS, count=words) -> list[list[tuple[float, str]]]:
    """Líneas en tramos de hasta `limit` tokens (`count` los cuenta: el tokenizador del modelo)."""
    out, cur, n = [], [], 0
    for t, text in ls:
        w = count(text)
        if cur and n + w > limit:
            out.append(cur)
            cur, n = [], 0
        cur.append((t, text))
        n += w
    if cur:
        out.append(cur)
    # un último tramo muy corto se suma al anterior (no da para puntos propios)
    if len(out) > 1 and sum(count(x) for _, x in out[-1]) < limit // 4:
        out[-2].extend(out.pop())
    return out


def parse_points(text: str, chunk: list[tuple[float, str]]) -> list[dict]:
    """Líneas «[mm:ss] punto» → [{t, text}], con el minuto ajustado a una línea real del tramo."""
    starts = [t for t, _ in chunk]
    lo, hi = starts[0], starts[-1] + LINE_S
    out = []
    for raw in text.splitlines():
        m = _TIME.match(raw)
        if not m:
            continue
        a, b, c, body = m.groups()
        t = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
        body = body.strip().strip("*").strip()
        if len(body) < 8:
            continue
        # fuera del tramo (un minuto inventado): después del final, la última línea; antes del
        # comienzo, donde iba el punto anterior de la lista (la lista viene en orden)
        if t > hi:
            t = starts[-1]
        elif t < lo - 5:
            t = out[-1]["t"] if out else lo
        t = max(s for s in starts if s <= max(t, lo))  # la línea donde empieza
        out.append({"t": round(t, 2), "text": body})
    # sin duplicados exactos y en orden
    seen, uniq = set(), []
    for p in sorted(out, key=lambda p: p["t"]):
        k = p["text"].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _target() -> str:
    return langs.name(langs.TARGET)


def points_prompt(chunk: list[tuple[float, str]], lang: str, part: int, parts: int) -> tuple[str, str]:
    where = f" (parte {part} de {parts})" if parts > 1 else ""
    system = (f"Eres un asistente que resume videos. Escribes siempre en {_target()} latinoamericano, "
              "claro y fiel a lo que se dice, sin inventar nada.")
    body = "\n".join(f"[{stamp(t)}] {x}" for t, x in chunk)
    user = (f"Esta es la transcripción de un video{where}, en {langs.name(lang)}. Cada línea empieza con su minuto.\n\n"
            f"{body}\n\n"
            f"Haz en {_target()} la lista de los puntos importantes que se tratan en este fragmento: todos los "
            "que haya, sin repetir y sin relleno. No traduzcas ni copies frases: resume con tus palabras qué se "
            "dice. Cada punto es una sola oración breve (máximo 30 palabras) que se entiende sola, por ejemplo "
            "«Explica que…» o «Cuenta cómo…». Un punto por línea, con el formato:\n"
            "[mm:ss] punto\n"
            "donde mm:ss es el minuto en que empieza a tratarse. Responde solo con la lista.")
    return system, user


def part_prompt(items: list[str], part: int, parts: int) -> tuple[str, str]:
    system = (f"Eres un asistente que resume videos. Escribes siempre en {_target()} latinoamericano, "
              "claro y fiel a lo que se dice, sin inventar nada.")
    body = "\n".join(f"- {x}" for x in items)
    user = (f"Estos son los puntos importantes de la parte {part} de {parts} de un video, en orden:\n\n{body}\n\n"
            f"Escribe en {_target()} un solo párrafo que cuente qué se trata en esta parte, sin listas ni títulos. "
            "Responde solo con el párrafo.")
    return system, user


def overview_prompt(title: str, items: list[str], lang: str, parts: bool = False) -> tuple[str, str]:
    system = (f"Eres un asistente que resume videos. Escribes siempre en {_target()} latinoamericano, "
              "claro y fiel a lo que se dice, sin inventar nada.")
    body = "\n".join(f"- {x}" for x in items)
    what = "lo que se trata en cada parte del video" if parts else "los puntos importantes que se tratan en el video"
    user = ((f"Video: «{title}»\n\n" if title else "") +
            f"Estos son {what}, en orden:\n\n{body}\n\n"
            f"Escribe en {_target()} un resumen de qué se trató el video: el tema, cómo se desarrolla y a qué "
            "conclusiones llega. Uno a tres párrafos según cuánto se trató, sin listas, sin títulos y sin "
            "empezar con «En este video». Responde solo con el resumen.")
    return system, user


class Summarizer:
    """Un modelo cargado bajo demanda. `summarize()` hace el resumen completo de un video."""

    def __init__(self, key: str, device: str = "cuda", threads: int = 0):
        if key not in MODELS:
            key = ORDER[0]
        self.key = key
        self.model = MODELS[key]
        self.device = device
        self.threads = threads
        self._gen = None
        self._tok = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._gen is not None

    def model_dir(self, download: bool = True) -> Path | None:
        from huggingface_hub import snapshot_download
        try:
            return Path(snapshot_download(self.model.repo, allow_patterns=FILES, local_files_only=not download))
        except Exception:  # noqa: BLE001 — sin descargar: no está en la caché
            if download:
                raise
            return None

    def load(self):
        with self._lock:
            if self._gen is not None:
                return
            import ctranslate2
            from tokenizers import Tokenizer

            path = self.model_dir()
            if self.device == "cuda":
                enable_cuda_dlls()
            ct = "int8_float16" if self.device == "cuda" else "int8"
            kw = {"intra_threads": self.threads} if self.device == "cpu" and self.threads else {}
            self._gen = ctranslate2.Generator(str(path), device=self.device, compute_type=ct, **kw)
            self._tok = Tokenizer.from_file(str(path / "tokenizer.json"))

    def unload(self):
        with self._lock:
            self._gen = None
            self._tok = None

    # ------------------------------------------------------------ generación
    def _prompt(self, system: str, user: str) -> str:
        if self.model.family == "gemma":
            return f"<bos><start_of_turn>user\n{system}\n\n{user}<end_of_turn>\n<start_of_turn>model\n"
        p = f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
        return p + ("<think>\n\n</think>\n\n" if self.model.think else "")

    def _end(self) -> list[str]:
        return ["<end_of_turn>", "<eos>"] if self.model.family == "gemma" else ["<|im_end|>", "<|endoftext|>"]

    def tokens(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False).ids) if self._tok else words(text)

    def generate(self, system: str, user: str, max_tokens: int) -> str:
        self.load()
        enc = self._tok.encode(self._prompt(system, user), add_special_tokens=False)
        r = self._gen.generate_batch([enc.tokens], max_length=max_tokens, sampling_topk=1,
                                     repetition_penalty=1.1, no_repeat_ngram_size=6,
                                     end_token=self._end(), include_prompt_in_result=False)
        text = self._tok.decode(r[0].sequences_ids[0], skip_special_tokens=True)
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    def summarize(self, segments: list[dict], lang: str, title: str = "", progress=None,
                  cancelled=lambda: False, run=None) -> dict | None:
        """{overview, points: [{t, text}], model, lang, created, seconds}. None si se canceló.

        progress(hechos, total): avance por pasos (uno por tramo, uno por grupo de puntos si son
        muchos y uno para el panorama).
        run(fn): cómo se ejecuta cada llamada al modelo (la cola la turna con la GPU)."""
        run = run or (lambda fn: fn())
        t0 = time.perf_counter()
        self.load()
        cs = chunks(lines(segments), count=self.tokens)
        if not cs:
            return {"overview": "", "points": [], "model": self.key, "lang": langs.TARGET,
                    "created": time.time(), "seconds": 0.0, "empty": True}
        total = len(cs) + 1
        points: list[dict] = []
        for i, c in enumerate(cs):
            if cancelled():
                return None
            if progress:
                progress(i, total)
            system, user = points_prompt(c, lang, i + 1, len(cs))
            out = run(lambda: self.generate(system, user, MAX_POINT_TOKENS))
            points.extend(parse_points(out, c))
        # el panorama: de todos los puntos o, si no caben en un tramo, de un párrafo por grupo
        items = [p["text"] for p in points] or [x for c in cs for _, x in c[:3]]
        groups = [[x for _, x in g] for g in chunks([(0.0, x) for x in items], count=self.tokens)]
        total += len(groups) if len(groups) > 1 else 0
        if len(groups) > 1:
            items = []
            for i, g in enumerate(groups):
                if cancelled():
                    return None
                if progress:
                    progress(len(cs) + i, total)
                system, user = part_prompt(g, i + 1, len(groups))
                items.append(run(lambda: self.generate(system, user, MAX_PART_TOKENS)).strip())
        if cancelled():
            return None
        if progress:
            progress(total - 1, total)
        system, user = overview_prompt(title, items, lang, parts=len(groups) > 1)
        overview = run(lambda: self.generate(system, user, MAX_OVERVIEW_TOKENS))
        if progress:
            progress(total, total)
        return {"overview": overview.strip(), "points": points, "model": self.key, "lang": langs.TARGET,
                "created": time.time(), "seconds": round(time.perf_counter() - t0, 1)}


def as_text(title: str, summary: dict) -> str:
    """El resumen como texto: título, de qué se trató y los puntos con su minuto."""
    out = [title, "", "Resumen", "", (summary.get("overview") or "").strip(), ""]
    if summary.get("points"):
        out += ["Puntos importantes", ""] + [f"[{stamp(p['t'])}] {p['text']}" for p in summary["points"]] + [""]
    m = MODELS.get(summary.get("model", ""))
    if m:
        out.append(f"Hecho con {m.name} en Translay.")
    return "\n".join(out) + "\n"
