"""Subtítulos en vivo sobre cualquier ventana (app de escritorio, web/live.html): la sesión efímera reconoce y
traduce lo que suena, pero no guarda nada, y solo la pide el dueño en este equipo.

    python -m pytest tests/test_live.py
"""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vt.asr import Word  # noqa: E402
from vt.auth import Access  # noqa: E402
from vt.session import Session  # noqa: E402
from vt.store import LiveTranscript  # noqa: E402
from vt.streaming import StreamingTranscriber  # noqa: E402

SR = 16000
SCRIPT = [(0.2, 0.6, " Hello"), (0.7, 1.1, " world."), (1.5, 1.9, " This"),
          (2.0, 2.3, " is"), (2.4, 2.9, " a"), (3.0, 3.5, " test.")]


class FakeASR:
    def __init__(self, ref):
        self.ref = ref

    def transcribe(self, audio, prompt=None, language=None):
        t0 = self.ref[0].t0
        end = t0 + len(audio) / SR
        return [Word(a - t0, b - t0, w, 0.99) for a, b, w in SCRIPT if b <= end and a >= t0 - 0.01]

    def detect(self, audio):
        return "en", 0.99


class FakeTranslator:
    def ready(self, lang):
        return True

    def name_for(self, lang):
        return "fake"

    def prepare(self, lang):
        pass

    def translate(self, text, glossary=None, src="en"):
        return f"ES {text}"

    def translate_many(self, texts, glossary=None, src="en"):
        return [f"ES {x}" for x in texts]


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, m):
        self.sent.append(m)


class Forbidden:
    """Lo que la sesión efímera nunca debe tocar: la biblioteca, el Store, la cola, la voz."""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, attr):
        raise AssertionError(f"la sesión en vivo usó {self.name}.{attr}")


def _session(access=None):
    s = Session.__new__(Session)
    ref = []
    s.st = StreamingTranscriber(FakeASR(ref), language="")
    ref.append(s.st)
    s.ws, s.q, s.tr = FakeWS(), asyncio.Queue(), None
    s.gpu = ThreadPoolExecutor(1)
    s.res = type("Res", (), {"run": lambda self, names, fn, *a: fn(*a)})()
    s.translator = FakeTranslator()
    s._store = Forbidden("store")
    s.processor = Forbidden("processor")
    s.dubber = Forbidden("dubber")
    s.exporter = None
    s.prefs = None
    s._backfill = None
    s._live_src = s._live_es = ""
    s.vault = type("Vault", (), {"id": "principal", "glossary": None})()
    s.vaults = type("Vaults", (), {"of": lambda self, vid: None})()
    s.access = access or Access(owner=True, local=True)
    return s


def _speech():
    t = np.arange(int(3.6 * SR)) / SR
    return np.concatenate([(0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), np.zeros(SR, np.float32)])


def test_live_session_translates_and_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = _session()
    s.q.put_nowait(("open", {"type": "open", "id": "live_prueba01", "ephemeral": True}))
    audio = _speech()
    for i in range(0, len(audio), 1600):
        s.q.put_nowait(("audio", i / SR, audio[i:i + 1600]))
    s.q.put_nowait(("end", {"type": "end"}))
    s.q.put_nowait(("close", None))

    async def go():
        await s._worker()
        if s._backfill:
            await s._backfill

    asyncio.run(go())
    kinds = [m["type"] for m in s.ws.sent]
    assert s.ws.sent[0]["type"] == "transcript" and s.ws.sent[0]["ephemeral"]
    segs = [m["segment"] for m in s.ws.sent if m["type"] == "segment"]
    assert [x["text"] for x in segs] == ["Hello world.", "This is a test."]
    assert all(x["translation"] == f"ES {x['text']}" for x in segs)
    assert "partial" in kinds
    assert isinstance(s.tr, LiveTranscript) and s.tr.path is None
    assert list(tmp_path.rglob("*")) == []  # nada en disco


def test_live_transcript_keeps_only_recent_sentences():
    tr = LiveTranscript("live_prueba02")
    for i in range(LiveTranscript.KEEP + 10):
        tr.add_segment(i, i + 0.5, f"frase {i}", None)
        tr.add_covered(i, i + 0.5)
    assert len(tr.segments) == LiveTranscript.KEEP and tr.segments[-1]["text"] == f"frase {LiveTranscript.KEEP + 9}"
    assert len(tr.covered) <= LiveTranscript.KEEP
    tr.save()  # sin archivo: no hace nada


def test_live_session_only_for_the_local_owner():
    live = {"type": "open", "id": "live_prueba03", "ephemeral": True}
    assert _session(Access(owner=True, local=True))._allowed("open", live)
    assert not _session(Access(owner=True, local=False))._allowed("open", live)  # el dueño desde otro equipo
    guest = Access(perms={"principal": "importar"}, local=True)
    assert not _session(guest)._allowed("open", live)
    assert _session(guest)._allowed("open", {"type": "open", "id": "abcdef0123456789"})  # abrir un video sigue igual


def test_page_mirrors_the_live_rule():
    """La página no pide la sesión en vivo si el servidor la rechazaría (web/js/access.js › mayRequest)."""
    js = (ROOT / "web" / "js" / "access.js").read_text(encoding="utf-8")
    assert 'if (t === "open" && obj.ephemeral) return !!(a.owner && a.local);' in js
