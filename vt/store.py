"""Persistencia de transcripciones por video.

Cada video se identifica con una huella de su contenido (calculada en el
navegador). Se guarda un JSON por video con:

* `segments`: frases con tiempo de inicio/fin, texto y traducción.
* `covered`: rangos del video ya procesados (incluye silencios), para no
  volver a transcribirlos al retroceder o reabrir el video.
"""

import json
import re
import threading
import time
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


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

    @property
    def segments(self) -> list[dict]:
        return self.data["segments"]

    @property
    def covered(self) -> list[list[float]]:
        return self.data["covered"]

    def add_segment(self, start: float, end: float, text: str,
                    translation: str | None, tr_model: str | None = None) -> tuple[dict, list[int]]:
        """Inserta una frase; reemplaza las que se solapan. Devuelve (nueva, ids borrados)."""
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
        """Frases sin traducir o traducidas con otro modelo."""
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
        with self._lock:
            self.data["updated"] = time.time()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def public(self) -> dict:
        return {"id": self.data["id"], "segments": self.segments, "covered": self.covered}


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Transcript] = {}

    def open(self, vid: str, name: str = "") -> Transcript:
        if not _SAFE_ID.match(vid):
            raise ValueError("id de video inválido")
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
