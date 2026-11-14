"""Idiomas de la interfaz: catálogos de textos compartidos por la vista y el servidor.

El texto se escribe en español en el código (`t("Agregar")` en web/js, `i18n.t("Agregar")` aquí) y cada idioma
tiene su catálogo en web/i18n/<idioma>.json: texto en español → texto en ese idioma. Lo que falta en un
catálogo se muestra en español. Agregar un idioma = agregar su catálogo (y su entrada en vt/langs.py).

Variables con llaves: `t("Quedan {n} videos", n=3)`. El mismo texto con variables es la clave del catálogo.

  t(texto, lang=None, **vars)    el texto en el idioma `lang` (por defecto, el de la app: langs.ui())
  catalog(lang)                  {texto: traducción} de un idioma
  script(lang, folder)           web/i18n/<idioma>.json como script (window.I18N) para la página

tools/i18n.py junta los textos del código, avisa los que faltan en cada catálogo y los agrega vacíos.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import langs

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "web" / "i18n"
SOURCE = "es"  # el idioma en que está escrito el código
_VAR = re.compile(r"\{(\w+)\}")


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    if lang == SOURCE:
        return {}
    f = FOLDER / f"{lang}.json"
    if not f.exists():
        return {}
    return {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if v}


def t(text: str, lang: str | None = None, **vars) -> str:
    out = catalog(lang or langs.ui()).get(text) or text
    if vars:
        out = _VAR.sub(lambda m: str(vars[m.group(1)]) if m.group(1) in vars else m.group(0), out)
    return out


def tree(value, lang: str | None = None):
    """Traduce los textos de una estructura (listas y diccionarios de preferencias). Solo las cadenas que están en
    el catálogo cambian: claves, códigos y valores quedan igual."""
    cat = catalog(lang or langs.ui())
    if not cat:
        return value
    if isinstance(value, str):
        return cat.get(value) or value
    if isinstance(value, list):
        return [tree(v, lang) for v in value]
    if isinstance(value, dict):
        return {k: tree(v, lang) for k, v in value.items()}
    return value


def script(lang: str, folder: Path) -> Path:
    """El catálogo como script para la página (se carga antes que el resto: los textos están al pintar)."""
    lang = lang if lang in langs.TARGETS else SOURCE
    src = FOLDER / f"{lang}.json"
    out = folder / f"{lang}.js"
    if not out.exists() or (src.exists() and src.stat().st_mtime > out.stat().st_mtime):
        folder.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"lang": lang, "strings": catalog(lang)}, ensure_ascii=False)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(f"window.I18N = {body};\n", encoding="utf-8")
        tmp.replace(out)
    return out
