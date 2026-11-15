"""Catálogos de idioma de la interfaz (vt/i18n.py): junta los textos del código y los compara con cada catálogo.

    python tools/i18n.py              cuántos textos hay y cuáles faltan o sobran en cada catálogo
    python tools/i18n.py --fill       agrega a cada catálogo los que faltan, vacíos (para traducirlos)
    python tools/i18n.py --prune      quita de los catálogos los que el código ya no usa
    python tools/i18n.py --missing pt los que faltan en un idioma, como JSON (para traducirlos de una vez)

De dónde salen los textos:
  web/js/*.js, desktop/ui/*.js   t("…") y t(`…`) (sin ${…}: las variables van como {nombre})
  web/index.html    textos y atributos fijos (placeholder, title, aria-label, data-tip, alt, data-label)
  vt/*.py           i18n.t("…") y las preferencias de vt/prefs.py (secciones, opciones, grupos y descripciones)

tests/test_i18n.py exige que en/pt tengan todos, con las mismas {variables}.
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FOLDER = ROOT / "web" / "i18n"
LANGS = ("en", "pt")
ATTRS = ("placeholder", "title", "aria-label", "data-tip", "alt", "data-label")
_LETTER = re.compile(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]")
_JS = re.compile(r"""(?<![\w.$])t\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|`((?:\\.|[^`\\$])*)`)""")
_PY = re.compile(r"""\b(?:i18n\.t|_t)\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)')""")


def _unescape(s: str) -> str:
    return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8") if "\\" in s else s


def from_js() -> dict[str, str]:
    out = {}
    # Translay's page and the desktop app's setup and startup screens (desktop/ui), which use the same catalogues
    for f in [*sorted((ROOT / "web" / "js").glob("*.js")), *sorted((ROOT / "desktop" / "ui").glob("*.js"))]:
        if f.name in ("i18n.js",):
            continue
        for m in _JS.finditer(f.read_text(encoding="utf-8")):
            s = _unescape(next(g for g in m.groups() if g is not None))
            if _LETTER.search(s):
                out.setdefault(s, f.relative_to(ROOT).as_posix())
    return out


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ATTRS and v and _LETTER.search(v):
                self.found.append(v.strip())

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        s = data.strip()
        if not self.skip and s and _LETTER.search(s):
            self.found.append(s)


def from_html() -> dict[str, str]:
    out = {}
    for page in ("web/index.html", "desktop/ui/index.html"):
        p = _Html()
        p.feed((ROOT / page).read_text(encoding="utf-8"))
        for s in p.found:
            if s not in ("Translay", "translay"):
                out.setdefault(s, page)
    return out


def from_py() -> dict[str, str]:
    out = {}
    for f in sorted((ROOT / "vt").glob("*.py")):
        for m in _PY.finditer(f.read_text(encoding="utf-8")):
            s = _unescape(next(g for g in m.groups() if g is not None))
            if _LETTER.search(s):
                out.setdefault(s, f"vt/{f.name}")
    from vt import prefs

    def add(s):
        if isinstance(s, str) and _LETTER.search(s) and not s.startswith("#"):
            out.setdefault(s, "vt/prefs.py")
    native = set(__import__("vt.langs", fromlist=["NATIVE"]).NATIVE.values())
    for sec in prefs.SECTIONS:
        add(sec[1]), add(sec[2])
    for p in prefs.SCHEMA:
        add(p["label"]), add(p.get("group")), add(p.get("desc"))
        for o in p.get("options") or []:
            add(o[1])
        for v in (p.get("alt") or {}).values():
            if isinstance(v, str):
                add(v)
            else:
                for o in v:
                    add(o[1])
    for title, desc in prefs.ALT_SECTIONS.values():
        add(title), add(desc)
    for name, _ in prefs.SECTION_GROUPS:
        add(name)
    for n in native:
        out.pop(n, None)  # cada idioma se nombra a sí mismo: no se traduce
    return out


def collect() -> dict[str, str]:
    return {**from_py(), **from_html(), **from_js()}


def load(lang: str) -> dict[str, str]:
    f = FOLDER / f"{lang}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save(lang: str, data: dict[str, str]):
    FOLDER.mkdir(parents=True, exist_ok=True)
    (FOLDER / f"{lang}.json").write_text(json.dumps(dict(sorted(data.items(), key=lambda kv: kv[0].lower())),
                                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--missing", metavar="LANG")
    a = ap.parse_args()
    keys = collect()
    if a.missing:
        cat = load(a.missing)
        print(json.dumps({k: "" for k in keys if not cat.get(k)}, ensure_ascii=False, indent=1))
        return
    print(f"{len(keys)} textos en el código")
    for lang in LANGS:
        cat = load(lang)
        missing = [k for k in keys if not cat.get(k)]
        unused = [k for k in cat if k not in keys]
        print(f"  {lang}: faltan {len(missing)}, sobran {len(unused)}")
        if a.fill:
            cat.update({k: "" for k in missing if k not in cat})
        if a.prune:
            cat = {k: v for k, v in cat.items() if k in keys}
        if a.fill or a.prune:
            save(lang, cat)


if __name__ == "__main__":
    main()
