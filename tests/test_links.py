"""Enlaces de Dropbox (vt/links.py) e idioma por video (vt/store.py), sin red ni GPU."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import links  # noqa: E402
from vt.store import SAME, Store  # noqa: E402

FOLDER_FILE = ("https://www.dropbox.com/scl/fo/abc123def456ghi789jkl/AAAbbbCCCdddEEEfffGGG/21_10.mp4"
               "?rlkey=fakekey0123456789abcdefg&st=st000000&e=1&dl=0")


def test_dropbox_link_is_parsed_and_stable():
    p = links.parse(FOLDER_FILE)
    assert p["id"].startswith("lk_") and len(p["id"]) == 19
    assert p["name"] == "21_10" and p["ext"] == "mp4"
    assert "dl=1" in p["direct"] and "rlkey=fakekey0123456789abcdefg" in p["direct"]
    assert "st=" not in p["url"] and "dl=" not in p["url"]
    # el mismo archivo con otros parámetros de seguimiento es el mismo video
    again = FOLDER_FILE.replace("st=st000000", "st=otro").replace("dl=0", "dl=1")
    assert links.link_id(again) == p["id"]
    # un archivo suelto (/scl/fi/) también vale
    assert links.parse("https://www.dropbox.com/scl/fi/abc123/clase.mov?rlkey=x&dl=0")["ext"] == "mov"


def test_dropbox_folder_or_other_sites_are_rejected():
    with pytest.raises(ValueError):
        links.parse("https://www.dropbox.com/scl/fo/abc123def456ghi789jkl/AAAbbbCCCdddEEEfffGGG?rlkey=x")
    with pytest.raises(ValueError):
        links.parse("https://www.dropbox.com/scl/fi/abc123/notas.pdf?rlkey=x")
    assert links.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is None
    assert links.parse("https://evil.com/dropbox.com/a/b/c.mp4") is None
    assert links.link_id("https://notdropbox.com/scl/fi/a/b.mp4") is None


def test_spanish_video_only_transcribes(tmp_path):
    tr = Store(tmp_path).open("lk_0123456789abcdef")
    assert tr.lang == "en" and not tr.native
    tr.add_segment(0, 1, "Hello", "Hola", "opus")
    tr.add_covered(0, 1)
    assert tr.set_lang("es")
    assert tr.native and tr.segments == [] and tr.covered == []  # lo reconocido en inglés no sirve
    seg, _ = tr.add_segment(0, 1, "Hola a todos", None, "opus")
    assert seg["translation"] == "Hola a todos" and seg["tr_model"] == SAME
    assert tr.stale("opus") == []  # nunca pasa por el traductor
    assert not tr.set_lang("es") and not tr.set_lang("fr")
    assert tr.public()["lang"] == "es"


def test_fetch_from_local_server(tmp_path, monkeypatch):
    """Descarga completa (con un archivo generado por ffmpeg servido como si fuera Dropbox)."""
    src = tmp_path / "src.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", str(src)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("sin ffmpeg con libx264")

    def fake_download(url, out, progress):
        assert "dl=1" in url
        out.write_bytes(src.read_bytes())
        progress(1.0)

    monkeypatch.setattr(links.Links, "_download", staticmethod(fake_download))
    lk = links.Links(tmp_path / "library")
    p = links.parse(FOLDER_FILE)
    seen = []
    info = lk.fetch(p["id"], p["url"], lambda *a: seen.append(a[0]))
    assert info["video"].endswith(".mp4") and info["audio"].endswith(".m4a") and info["thumb"].endswith(".jpg")
    assert 1.5 < info["duration"] < 2.5 and seen[-1] == "listo"
    assert (tmp_path / "library" / f"{p['id']}.m4a").stat().st_size > 0
    # ya descargado: no se vuelve a bajar
    monkeypatch.setattr(links.Links, "_download", staticmethod(lambda *a: pytest.fail("se volvió a descargar")))
    assert lk.fetch(p["id"], p["url"])["title"] == "21_10"
    # solo audio: el video no se guarda
    (tmp_path / "library" / f"{p['id']}.json").unlink()
    monkeypatch.setattr(links.Links, "_download", staticmethod(fake_download))
    info = lk.fetch(p["id"], p["url"], audio_only=True)
    assert info["audio_only"] and not info["video"] and not (tmp_path / "library" / f"{p['id']}.mp4").exists()
