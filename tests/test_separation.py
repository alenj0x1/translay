"""Fondo sin la voz original (vt/separation.py): cuándo se separa un video y que el modelo se verifique."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vt import separation  # noqa: E402


class FakeVault:
    def __init__(self, root):
        self.root = root


class FakeVaults:
    def __init__(self, root):
        self.v = FakeVault(root)

    def of(self, vid):
        return self.v if vid.startswith("v") else None


class FakePrefs:
    def __init__(self, on=True):
        self.values = {"bg_separate": on}


class FakeLibrary:
    def __init__(self, videos):
        self.data = {"videos": videos}
        self.fields = {}

    def set_field(self, vid, **kw):
        self.fields.setdefault(vid, {}).update(kw)


def make(tmp_path, on=True, videos=None, monkeypatch=None):
    sep = separation.Separator.__new__(separation.Separator)  # sin el hilo de trabajo
    sep.models = tmp_path / "models"
    sep.vaults, sep.prefs, sep.notify = FakeVaults(tmp_path), FakePrefs(on), lambda m: None
    sep.media_of = lambda vid: None
    sep.library = FakeLibrary(videos or {"v1": {"mode": "translate"}, "v2": {"mode": "transcribe"}})
    sep.pending, sep._ok, sep.enabled = set(), True, True
    import queue

    sep.q = queue.Queue()
    return sep


def test_only_dubbed_videos_without_background(tmp_path):
    sep = make(tmp_path)
    assert sep.wanted("v1")
    assert not sep.wanted("v2")  # solo se transcribe: no hay voz doblada que poner encima
    assert not sep.wanted("x1")  # sin biblioteca
    (tmp_path / "audio" / "v1").mkdir(parents=True)
    (tmp_path / "audio" / "v1" / "fondo.m4a").write_bytes(b"x")
    assert not sep.wanted("v1")  # ya tiene su fondo


def test_setting_off_or_no_voice_engine(tmp_path):
    assert not make(tmp_path, on=False).wanted("v1")
    sep = make(tmp_path)
    sep.enabled = False  # el servidor corre sin voz: no hay doblaje sobre el que poner el fondo
    sep.request("v1")
    assert sep.q.empty() and not sep.available()
    sep.enabled = True  # el entorno se comprueba después, en el hilo de separación (no frena la cola)
    sep.request("v1")
    sep.request("v1")  # una sola vez en la cola
    assert sep.q.qsize() == 1


def test_model_is_checked_against_its_hash(tmp_path, monkeypatch):
    sep = make(tmp_path)
    sep.models.mkdir(parents=True)
    bad = sep.models / separation.MODEL_NAME
    bad.write_bytes(b"no es el modelo")

    class FakeResponse:
        def __init__(self):
            self.data = [b"tampoco", b""]

        def read(self, n):
            return self.data.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(separation.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    with pytest.raises(RuntimeError, match="huella"):
        sep.weights()
    assert not (sep.models / (separation.MODEL_NAME[:-3] + ".part")).exists()


def test_background_url():
    assert separation.bg_url("abc") == "/audio/abc/fondo.m4a"
