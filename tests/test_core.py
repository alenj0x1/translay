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
    restored = SpeakerTracker(state=tr.state())
    assert restored.assign(unit(b + 0.3 * rng.standard_normal(256)), 3.0)[0] == 1


if __name__ == "__main__":
    test_audiofx()
    test_speaker_tracker()
    test_streaming_commits_sentences()
    test_store_overlap_and_ranges()
    test_textproc()
    print("ok")
