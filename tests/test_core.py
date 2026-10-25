"""Pruebas sin GPU del núcleo: streaming (con un ASR falso) y almacenamiento.

    python -m pytest tests   ó   python tests/test_core.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt.asr import Word  # noqa: E402
from vt.store import Store, merge_ranges  # noqa: E402
from vt.streaming import Segment, StreamingTranscriber  # noqa: E402
from vt.textproc import match_shape, polish, preedit, split_sentences  # noqa: E402

SR = 16000
SCRIPT = [(0.2, 0.6, " Hello"), (0.7, 1.1, " world."), (1.5, 1.9, " This"),
          (2.0, 2.3, " is"), (2.4, 2.9, " a"), (3.0, 3.5, " test.")]


class FakeASR:
    """Devuelve las palabras del guion cuyo audio ya está en el búfer."""

    def __init__(self, st_ref):
        self.st_ref = st_ref

    def transcribe(self, audio, prompt=None):
        t0 = self.st_ref[0].t0
        end = t0 + len(audio) / SR
        return [Word(a - t0, b - t0, w, 0.99) for a, b, w in SCRIPT if b <= end and a >= t0 - 0.01]


def tone(seconds):
    t = np.arange(int(seconds * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_streaming_commits_sentences():
    ref = []
    st = StreamingTranscriber(FakeASR(ref))
    ref.append(st)
    audio = np.concatenate([tone(3.6), np.zeros(SR, np.float32)])
    segs = []
    for i in range(0, len(audio), 1600):
        st.feed(i / SR, audio[i:i + 1600])
        if st.ready():
            segs += [e for e in st.step() if isinstance(e, Segment)]
    segs += [e for e in st.flush() if isinstance(e, Segment)]
    assert [s.text for s in segs] == ["Hello world.", "This is a test."]
    assert st.final_t >= 3.5


def test_store_overlap_and_ranges():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        tr = store.open("abcdef0123456789", "demo.mp4")
        tr.add_segment(0.0, 2.0, "Then, a neural network converges.", None)
        seg, removed = tr.add_segment(0.1, 3.0, "Then, a neural network converts the sound.", None)
        assert removed == [1] and len(tr.segments) == 1
        tr.add_covered(0, 10)
        tr.add_covered(10.1, 20)
        assert tr.covered == [[0, 20]]
        tr.save()
        assert Store(Path(d)).open("abcdef0123456789").segments[0]["id"] == seg["id"]
    assert merge_ranges([[5, 6], [0, 1], [0.9, 2]]) == [[0, 2], [5, 6]]


def test_textproc():
    assert split_sentences("Mr. Smith went to the U.S. Army. He left.") == [
        "Mr. Smith went to the U.S. Army.", "He left."]
    assert split_sentences("Are you ready? Because yes.") == ["Are you ready?", "Because yes."]
    assert split_sentences("I paid $5. It was 3.5 percent.") == ["I paid $5.", "It was 3.5 percent."]
    assert preedit("Let's call it a day.") == "Let's stop for today."
    assert preedit("Would you go back?") == "Would you return?"
    assert preedit("that's pretty much it, let us know") == "that's all, tell us"
    assert match_shape("the text will be", "El texto será.") == "el texto será"
    assert match_shape("Finally, in a version,", "Finalmente, en una versión.") == "Finalmente, en una versión,"
    assert match_shape("which is fine", "que está bien") == "lo que está bien"
    assert polish("Cuesta $ 799 , mira el vídeo") == "Cuesta $799, mira el video"
    assert polish("Hoy quiero hablaros de esto y os voy a mostrar") == "Hoy quiero hablarles de esto y les voy a mostrar"
    assert preedit("Opus has been out for a bit") == "Opus has been available for a bit"


def test_audiofx():
    from vt.audiofx import median_f0, resample, time_stretch

    sr = 16000
    t = np.arange(sr * 2) / sr
    x = (0.4 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    y = time_stretch(x, sr, 1.3)
    assert abs(len(y) - len(x) / 1.3) < sr * 0.02
    assert abs(median_f0(y, sr) - 150) < 3          # el tono no cambia
    z = resample(x, sr, 24000)
    assert len(z) == 48000 and abs(median_f0(resample(z, 24000, sr), sr) - 150) < 3


def test_speaker_tracker():
    from vt.speakers import SpeakerTracker

    rng = np.random.default_rng(0)
    a, b = rng.standard_normal(256), rng.standard_normal(256)
    unit = lambda v: v / np.linalg.norm(v)  # noqa: E731
    tr = SpeakerTracker()
    ids = [tr.assign(unit(v + 0.3 * rng.standard_normal(256)), 3.0)[0] for v in (a, b, a, b, a)]
    assert ids == [0, 1, 0, 1, 0]
    # una frase corta parecida a alguien no crea persona nueva
    assert tr.assign(unit(a + 0.8 * rng.standard_normal(256)), 0.9)[0] == 0
    tr.assign(unit(b), np.float64(2.5))  # duraciones numpy (vienen de los tiempos de Whisper)
    import json
    json.dumps(tr.state())  # el estado se guarda en el JSON de la transcripción
    # una referencia larga se recorta a ~8 s (y su texto en la misma proporción)
    t = np.arange(16000 * 15) / 16000
    long = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    assert tr.add_reference(0, long, " ".join(["palabra"] * 30))
    _, clip, text = tr.refs[0][-1] if len(tr.refs[0][-1]) == 3 else (None, None, None)
    assert 6 * 16000 <= len(clip) <= 8 * 16000 and 12 <= len(text.split()) <= 16
    restored = SpeakerTracker(state=tr.state())
    assert restored.assign(unit(b + 0.3 * rng.standard_normal(256)), 3.0)[0] == 1


def test_cookies_import():
    from vt import cookies

    rows = [  # cookies inventadas: solo para la prueba
        (".youtube.com", "LOGIN_INFO", "falso123"),
        (".youtube.com", "PREF", "f6=40000000"),
        (".google.com", "SID", "falso456"),
        (".banco-ejemplo.com", "SESSION", "no-se-guarda"),
    ]
    lines = ["# Netscape HTTP Cookie File"]
    lines += ["\t".join([dom, "TRUE", "/", "TRUE", "2000000000", name, val]) for dom, name, val in rows]
    fake = "\n".join(lines).encode()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "cookies.txt"
        info = cookies.import_file(fake, out)
        assert info["count"] == 3 and info["logged_in"]
        assert "banco-ejemplo" not in out.read_text(encoding="utf-8")  # solo YouTube/Google
        assert cookies.status(out)["present"]
        try:
            cookies.import_file(b"esto no es un cookies.txt", out)
            raise AssertionError("debió rechazarse")
        except ValueError:
            pass


def test_playlist_library_and_srt():
    from vt.exporter import safe_name, srt
    from vt.library import Library
    from vt.youtube import playlist_id

    assert playlist_id("https://www.youtube.com/watch?v=ejjBbaq9RmY&list=PLKfy8g4yBtRY") == "PLKfy8g4yBtRY"
    assert playlist_id("https://www.youtube.com/watch?v=ejjBbaq9RmY&list=RDejjBbaq9RmY") is None  # mix
    with tempfile.TemporaryDirectory() as d:
        lib = Library(Path(d) / "library.json")
        info = {"id": "PLprueba123", "title": "Mi lista", "url": "u", "channel": "c",
                "entries": [{"id": f"vid{i:08d}", "title": f"T{i}", "duration": 60, "channel": "c", "thumb": ""}
                            for i in range(3)]}
        c = lib.import_playlist(info)
        assert c["items"] == ["yt_vid00000000", "yt_vid00000001", "yt_vid00000002"]
        pub = lib.public()
        by = {x["id"]: x for x in pub["collections"]}
        assert by["recent"]["items"] == [] and len(by["all"]["items"]) == 3  # sin descargar: solo en Todos
        assert lib.import_playlist(info)["id"] == c["id"]  # reimportar no duplica
        lib.set_field("yt_vid00000000", media="/media/yt/x.mp4")
        assert sorted(lib.delete(c["id"])) == ["yt_vid00000001", "yt_vid00000002"]  # lo descargado se queda
    segs = [{"start": 1.0, "end": 2.5, "text": "Hi.", "translation": "Hola."}, {"start": 3, "end": 3.1, "text": "x"}]
    out = srt(segs, "translation")
    assert out.startswith("1\n00:00:01,000 --> 00:00:02,500\nHola.") and "x" not in out
    assert safe_name('a/b:c?"d') == "a b c d"


if __name__ == "__main__":
    test_playlist_library_and_srt()
    test_cookies_import()
    test_audiofx()
    test_speaker_tracker()
    test_streaming_commits_sentences()
    test_store_overlap_and_ranges()
    test_textproc()
    print("ok")
