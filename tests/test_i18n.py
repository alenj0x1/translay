"""Catálogos de idioma (vt/i18n.py, web/i18n/*.json): completos y con las mismas variables que el texto original."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import i18n as extract  # noqa: E402  tools/i18n.py
from vt import i18n, langs  # noqa: E402

VAR = re.compile(r"\{(\w+)\}")


def test_every_text_is_translated_with_the_same_variables():
    keys = extract.collect()
    assert len(keys) > 300
    for lang in extract.LANGS:
        cat = extract.load(lang)
        missing = [k for k in keys if not cat.get(k)]
        assert not missing, f"{lang}: faltan {len(missing)}, p. ej. {missing[:5]} (python tools/i18n.py --fill)"
        wrong = [k for k in keys if set(VAR.findall(k)) != set(VAR.findall(cat[k]))]
        assert not wrong, f"{lang}: variables distintas en {wrong[:5]}"


def test_every_ui_language_has_a_catalog():
    for code in langs.TARGETS:
        assert code == i18n.SOURCE or (i18n.FOLDER / f"{code}.json").exists()


def test_t_falls_back_and_fills_variables(tmp_path):
    assert i18n.t("Texto que no existe {n}", "en", n=3) == "Texto que no existe 3"
    assert i18n.t("Agregar", "es") == "Agregar"
    out = i18n.script("en", tmp_path)
    data = json.loads(out.read_text(encoding="utf-8").removeprefix("window.I18N = ").rstrip().rstrip(";"))
    assert data["lang"] == "en" and isinstance(data["strings"], dict)
