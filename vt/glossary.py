"""Glosario propio: términos que no se traducen o que siempre se traducen igual.

data/glossary.json:  [{"src": "Jupyter Notebook", "dst": ""}, {"src": "prompt", "dst": "instrucción"}]
  dst vacío = no traducir (queda como en inglés)

Antes de traducir, cada término se cambia por un marcador que el traductor deja
intacto (ZQXJ1, ZQXJ2…; medido con Opus-MT: pasan 3 de 3) y después se repone por
su traducción fija. Así no se "traduce" un nombre ni se cambia un término acordado.
"""

import hashlib
import json
import re
import threading
from pathlib import Path

_MARK = re.compile(r"ZQXJ(\d+)")


class Glossary:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.entries: list[dict] = []
        if path.exists():
            try:
                self.entries = self._clean(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                self.entries = []
        self._compile()

    @staticmethod
    def _clean(items) -> list[dict]:
        out, seen = [], set()
        for e in items or []:
            src = str(e.get("src", "")).strip()[:120]
            dst = str(e.get("dst", "")).strip()[:120]
            if src and src.lower() not in seen:
                seen.add(src.lower())
                out.append({"src": src, "dst": dst})
        return out

    def _compile(self):
        # los términos más largos primero ("Jupyter Notebook" antes que "Notebook")
        ordered = sorted(self.entries, key=lambda e: -len(e["src"]))
        self._rules = [(re.compile(r"(?<![\w-])" + re.escape(e["src"]) + r"(?![\w-])", re.I), e) for e in ordered]

    @property
    def version(self) -> str:
        return hashlib.sha1(json.dumps(self.entries, sort_keys=True).encode()).hexdigest()[:8]

    def set(self, items) -> tuple[list[dict], list[dict]]:
        """Guarda el glosario. Devuelve (anterior, nuevo) para ver qué cambió."""
        with self._lock:
            old = self.entries
            self.entries = self._clean(items)
            self._compile()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
            return old, self.entries

    # ------------------------------------------------------------- traducir
    def protect(self, text: str) -> tuple[str, list[str]]:
        """Cambia cada término por un marcador; devuelve el texto y el reemplazo de cada marcador."""
        repl: list[str] = []
        for rx, e in self._rules:
            def sub(m, e=e):
                repl.append(e["dst"] or m.group(0))  # sin traducción fija: el término tal cual
                return f"ZQXJ{len(repl)}"
            text = rx.sub(sub, text)
        return text, repl

    @staticmethod
    def restore(text: str, repl: list[str]) -> str:
        if not repl or not text:
            return text
        return _MARK.sub(lambda m: repl[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(repl) else m.group(0), text)

    def matches(self, text: str, entries: list[dict] | None = None) -> bool:
        """¿La frase contiene algún término (de `entries`, o de todo el glosario)?"""
        terms = entries if entries is not None else self.entries
        low = (text or "").lower()
        return any(e["src"].lower() in low for e in terms)
