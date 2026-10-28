"""Pruebas sin GPU de lo que usa la app de escritorio (desktop/): carpetas configurables y la fuente local.

    python -m pytest tests/test_desktop.py
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vt import httpws, tts  # noqa: E402


def test_venvs_default(monkeypatch):
    monkeypatch.delenv("TRANSLAY_VENVS", raising=False)
    mod = importlib.reload(tts)
    assert mod.venv_python("omnivoice").parts[-4:-2] == (".venvs", "omnivoice")


def test_venvs_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSLAY_VENVS", str(tmp_path))
    mod = importlib.reload(tts)
    assert mod.venv_python("omnivoice").is_relative_to(tmp_path / "omnivoice")
    monkeypatch.delenv("TRANSLAY_VENVS")
    importlib.reload(tts)


def test_font_served_locally():
    # la interfaz no depende de Google Fonts (sin internet y en la app de escritorio)
    assert httpws._MIME[".woff2"] == "font/woff2"
    css = (ROOT / "web" / "css" / "fonts.css").read_text(encoding="utf-8")
    for weight in (400, 500, 600, 700, 800):
        font = ROOT / "web" / "fonts" / f"plus-jakarta-sans-latin-{weight}-normal.woff2"
        assert font.exists() and font.name in css
    assert "fonts.googleapis" not in (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_lock_files_pinned():
    # los paquetes que instala la app vienen con versión exacta y huella
    for name in ("server.txt", "voice.txt"):
        text = (ROOT / "desktop" / "locks" / name).read_text(encoding="utf-8")
        reqs = [line for line in text.splitlines() if line and not line.startswith((" ", "#"))]
        assert reqs and all("==" in line for line in reqs)
        assert text.count("--hash=sha256:") >= len(reqs)
