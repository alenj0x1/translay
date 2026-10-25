"""Mide reconocimiento + diarización contra la verdad de referencia.

Simula la reproducción en vivo (misma cadencia que con GPU real), asigna
persona a cada frase y compara con <nombre>.truth.json:

* WER: tasa de error de palabras de la transcripción completa.
* Diarización: % de frases con la persona correcta (con el mejor mapeo
  persona detectada → persona real) y cuántas personas se detectaron.

    python tools/eval_pipeline.py samples/podcast.mp4 samples/podcast_cafe10.mp4 …
"""

import argparse
import itertools
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.transcribe_file import decode  # noqa: E402
from vt.asr import WhisperASR  # noqa: E402
from vt.speakers import SpeakerEmbedder, SpeakerTracker  # noqa: E402
from vt.streaming import Segment, StreamingTranscriber  # noqa: E402

SR = 16000


def words(t: str) -> list[str]:
    return re.sub(r"[^\w' ]+", " ", t.lower().replace("$", " dollars ")).split()


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    return d[len(hyp)] / max(1, len(ref))


def stream(asr, audio):
    st = StreamingTranscriber(asr)
    segs, clock, i, step = [], 0.0, 0, 1600
    while i < len(audio):
        while i < len(audio) and (i + step) / SR <= clock:
            st.feed(i / SR, audio[i:i + step])
            i += step
        if st.ready():
            t = time.perf_counter()
            segs += [e for e in st.step() if isinstance(e, Segment)]
            clock += time.perf_counter() - t
        else:
            st.feed(i / SR, audio[i:i + step])
            i += step
            clock = max(clock, i / SR)
    segs += [e for e in st.flush() if isinstance(e, Segment)]
    return segs


def score_diarization(segs, labels, truth):
    real = []
    for s in segs:
        ov = {}
        for t in truth:
            o = min(s.end, t["end"]) - max(s.start, t["start"])
            if o > 0:
                ov[t["speaker"]] = ov.get(t["speaker"], 0) + o
        real.append(max(ov, key=ov.get) if ov else None)
    pairs = [(l, r) for l, r in zip(labels, real) if l is not None and r is not None]
    found = sorted({l for l, _ in pairs})
    names = sorted({r for _, r in pairs})
    best = 0
    # mapeo uno a uno: una persona detectada de más cuenta como error
    k = max(len(found), len(names))
    for perm in itertools.permutations(names + [None] * (k - len(names)), len(found)):
        m = dict(zip(found, perm))
        best = max(best, sum(m[l] == r for l, r in pairs))
    return best / max(1, len(pairs)), len(found), len(names), real


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("media", nargs="+")
    p.add_argument("--threshold", type=float, nargs="+", default=[0.30])
    p.add_argument("-v", action="store_true")
    p.add_argument("--relabel", action="store_true")
    a = p.parse_args()

    asr = WhisperASR()
    asr.warmup()
    emb = SpeakerEmbedder()
    data = []
    for m in a.media:
        path = Path(m)
        truth = json.loads((path.parent / (path.stem.split("_")[0] + ".truth.json")).read_text(encoding="utf-8"))
        segs = stream(asr, decode(m))
        embs = [emb.embed(s.audio) if s.audio is not None else None for s in segs]
        data.append((path, truth, segs, embs))

    for th in a.threshold:
        print(f"\numbral {th}")
        print(f"{'archivo':<22} {'WER':>6} {'diar':>6} {'pers':>6} {'frases':>6}")
        accs = []
        for path, truth, segs, embs in data:
            tracker = SpeakerTracker(threshold=th)
            labels, short = [], []
            for i, (e, s) in enumerate(zip(embs, segs)):
                dur = s.end - s.start
                labels.append(tracker.assign(e, dur)[0])
                if e is not None and dur < tracker.min_new_s:
                    short.append((i, e))
                cents = tracker.confirmed()
                if a.relabel and cents:  # misma regla que Dubber.relabel
                    for j, ej in short:
                        sims = sorted(((float(c @ ej), k) for k, c in cents), reverse=True)
                        cur = tracker.resolve(labels[j])
                        cur_sim = next((v for v, k in sims if k == cur), -1.0)
                        if sims[0][1] != cur and sims[0][0] - cur_sim > 0.08:
                            labels[j] = sims[0][1]
            labels = [tracker.resolve(x) for x in labels]
            w = wer(words(" ".join(t["text"] for t in truth)), words(" ".join(s.text for s in segs)))
            acc, nf, nr, real = score_diarization(segs, labels, truth)
            accs.append(acc)
            print(f"{path.stem:<22} {w:6.1%} {acc:6.0%} {nf:>3}/{nr:<2} {len(segs):>6}")
            if a.v:
                for s, l, r in zip(segs, labels, real):
                    print(f"     {s.start:6.1f} spk{l} ({r}) {s.text}")
        print(f"{'promedio':<22} {'':>6} {np.mean(accs):6.1%}")


if __name__ == "__main__":
    main()
