"""Persistencia de transcripciones por video.

Cada video se identifica con una huella de su contenido (calculada en el
navegador). Se guarda un JSON por video con:

* `segments`: frases con tiempo de inicio/fin, texto y traducción.
* `covered`: rangos del video ya procesados (incluye silencios), para no
  volver a transcribirlos al retroceder o reabrir el video.
* `lang`: idioma en que se habla ("en" si no está). Un video que ya está en
  español solo se transcribe: su "traducción" es el mismo texto y no lleva voz.
"""

import json
import re
import threading
import time
import uuid
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
LANGS = ("en", "es")  # idiomas que se reconocen; se traduce de inglés a español
TARGET = "es"
SAME = "original"     # tr_model de las frases que ya estaban en español (sin traducir)


def merge_ranges(ranges: list[list[float]], tol: float = 0.25) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in out]


class Transcript:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data
        self._lock = threading.Lock()  # la vista y la cola en segundo plano pueden escribir a la vez
        self.deleted = False  # video eliminado: lo que siga procesándose ya no se guarda

    @property
    def lang(self) -> str:
        return self.data.get("lang") or "en"

    @property
    def native(self) -> bool:
        """¿Ya está en español? Entonces solo se transcribe."""
        return self.lang == TARGET

    def set_lang(self, lang: str) -> bool:
        """Cambia el idioma del video. Lo reconocido en el otro idioma no sirve: se borra
        (frases, tramos cubiertos y comentarios) para volver a procesarlo. True si cambió."""
        if lang not in LANGS or lang == self.lang:
            return False
        with self._lock:
            self.data.update(lang=lang, segments=[], covered=[], comments={})
        return True

    @property
    def segments(self) -> list[dict]:
        return self.data["segments"]

    @property
    def covered(self) -> list[list[float]]:
        return self.data["covered"]

    def add_segment(self, start: float, end: float, text: str,
                    translation: str | None, tr_model: str | None = None) -> tuple[dict, list[int]]:
        """Inserta una frase; reemplaza las que se solapan. Devuelve (nueva, ids borrados)."""
        if self.native:
            translation, tr_model = text, SAME
        removed = []
        keep = []
        for s in self.segments:
            overlap = min(end, s["end"]) - max(start, s["start"])
            shorter = max(1e-3, min(end - start, s["end"] - s["start"]))
            if overlap / shorter > 0.5:
                removed.append(s["id"])
            else:
                keep.append(s)
        self.data["next_id"] += 1
        seg = {"id": self.data["next_id"], "start": start, "end": end,
               "text": text, "translation": translation, "tr_model": tr_model}
        keep.append(seg)
        keep.sort(key=lambda s: s["start"])
        self.data["segments"] = keep
        return seg, removed

    def stale(self, tr_model: str) -> list[dict]:
        """Frases sin traducir o traducidas con otro modelo (ninguna si ya está en español)."""
        if self.native:
            return []
        return [s for s in self.segments if s.get("tr_model") != tr_model]

    def set_translation(self, seg_id: int, translation: str | None, tr_model: str) -> bool:
        for s in self.segments:
            if s["id"] == seg_id:
                s["translation"], s["tr_model"] = translation, tr_model
                return True
        return False

    def add_covered(self, a: float, b: float):
        if b - a > 0.05:
            self.data["covered"] = merge_ranges(self.covered + [[a, b]])

    def save(self):
        if self.deleted:
            return
        with self._lock:
            self.data["updated"] = time.time()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def public(self) -> dict:
        return {"id": self.data["id"], "segments": self.segments, "covered": self.covered,
                "comments": self.comments, "lang": self.lang, "speaker_names": self.data.get("speaker_names") or {},
                "voice_map": self.data.get("voice_map") or {}}

    # ------------------------------------------------- comentarios por frase
    @property
    def comments(self) -> dict:
        """id de frase (texto) → [{id, text, created, updated}]"""
        return self.data.setdefault("comments", {})

    def add_comment(self, seg_id: int, text: str) -> dict:
        c = {"id": uuid.uuid4().hex[:8], "text": text.strip()[:4000], "created": time.time(), "updated": None}
        self.comments.setdefault(str(seg_id), []).append(c)
        return c

    def edit_comment(self, seg_id: int, cid: str, text: str):
        for c in self.comments.get(str(seg_id), []):
            if c["id"] == cid:
                c.update(text=text.strip()[:4000], updated=time.time())

    def delete_comment(self, seg_id: int, cid: str):
        key = str(seg_id)
        items = [c for c in self.comments.get(key, []) if c["id"] != cid]
        if items:
            self.comments[key] = items
        else:
            self.comments.pop(key, None)


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Transcript] = {}
        # la cola, las descargas y las pestañas abren a la vez: un solo objeto por video
        self._open_lock = threading.Lock()

    def open(self, vid: str, name: str = "") -> Transcript:
        if not _SAFE_ID.match(vid):
            raise ValueError("id de video inválido")
        t = self._cache.get(vid)
        if t is not None:
            return t
        with self._open_lock:
            if vid in self._cache:
                return self._cache[vid]
            path = self.root / f"{vid}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = {"id": vid, "name": name, "segments": [], "covered": [],
                        "next_id": 0, "created": time.time()}
            t = Transcript(path, data)
            self._cache[vid] = t
            return t

    def forget(self, vid: str):
        """Suelta la transcripción abierta (su archivo se movió, p. ej. a la papelera)."""
        with self._open_lock:
            t = self._cache.pop(vid, None)
        if t:
            t.deleted = True

    def delete(self, vid: str):
        if not _SAFE_ID.match(vid):
            return
        with self._open_lock:
            t = self._cache.pop(vid, None)
        if t:
            t.deleted = True
        (self.root / f"{vid}.json").unlink(missing_ok=True)
