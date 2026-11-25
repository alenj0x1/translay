"""Hallucination lab: what Whisper writes when there is no voice, per language.

Whisper was trained on subtitles, so on silence and noise it tends to write the credits and closings
those subtitles had ("Thanks for watching", "Amara.org"). The live recognizer drops such a phrase when it
is the whole sentence and its confidence is low (HALLUCINATIONS in vt/streaming.py); this lab finds which
phrases a language really gets, instead of guessing them.

Feeds clips with no voice at all, with the language given (as when the video's language is known):
  silence     digital silence and near-silence (dither)
  noise       white, pink and brown noise, from very quiet to loud
  hum         50/60 Hz mains hum with harmonics
  tones       chords of sine tones (a stand-in for background music)
and counts the phrases each model writes (normalized as in vt/streaming.py), with their mean word
confidence. A phrase that appears again and again is a candidate for HALLUCINATIONS.

    python tools/lab/langs_silence.py --langs ja ko --models large-v3-turbo:float16 small:int8_float16
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt.asr import MODELS, WhisperASR  # noqa: E402
from vt.streaming import NO_SPACES, _norm  # noqa: E402

SR = 16000
DATA = ROOT / "data" / "labs" / "languages"


def colored(kind: str, n: int, rng) -> np.ndarray:
    x = rng.standard_normal(n)
    if kind == "white":
        return x
    f = np.fft.rfft(x)
    k = np.maximum(np.arange(len(f)), 1)
    f /= np.sqrt(k) if kind == "pink" else k
    return np.fft.irfft(f, n)


def clips(seed: int = 3) -> list[tuple[str, np.ndarray]]:
    """(label, audio) with no voice: about 100 clips from 2 to 12 s."""
    rng = np.random.default_rng(seed)
    out = []

    def norm(x, dbfs):
        x = x / (np.sqrt(np.mean(x ** 2)) + 1e-12)
        return (x * 10 ** (dbfs / 20)).astype(np.float32)

    for s in (2, 5, 10):
        out.append((f"silence {s}s", np.zeros(s * SR, np.float32)))
        out.append((f"dither {s}s", norm(rng.standard_normal(s * SR), -80)))
    for kind in ("white", "pink", "brown"):
        for db in (-60, -45, -35, -25, -18):
            for s in (3, 8):
                out.append((f"{kind} {db}dB {s}s", norm(colored(kind, s * SR, rng), db)))
    t = np.arange(10 * SR) / SR
    for hz in (50, 60):
        for db in (-45, -30, -20):
            x = sum(np.sin(2 * np.pi * hz * h * t) / h for h in (1, 2, 3, 5))
            out.append((f"hum {hz}Hz {db}dB", norm(x + 0.05 * rng.standard_normal(len(t)), db)))
    chords = [(220, 277, 330), (196, 247, 294), (262, 330, 392), (174, 220, 262)]
    for i in range(24):
        s = int(rng.integers(3, 13))
        tt = np.arange(s * SR) / SR
        x = np.zeros(len(tt))
        step = SR // 2
        for k in range(0, len(tt), step):  # a chord every half second, like a slow loop
            c = chords[(k // step + i) % len(chords)]
            seg = tt[k:k + step]
            x[k:k + step] = sum(np.sin(2 * np.pi * f * seg) for f in c) * np.exp(-3 * (seg - seg[0]))
        out.append((f"tones {i} {s}s", norm(x + 0.02 * rng.standard_normal(len(x)), float(rng.choice([-35, -25, -18])))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--langs", nargs="+", default=["ja", "ko"])
    ap.add_argument("--models", nargs="+", default=["large-v3-turbo:float16"],
                    help=f"model:precision ({', '.join(MODELS)})")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default=str(DATA / "silence"))
    a = ap.parse_args()

    data = clips()
    print(f"{len(data)} clips without voice, {sum(len(x) for _, x in data) / SR:.0f} s", flush=True)
    results = []
    for spec in a.models:
        name, _, ct = spec.partition(":")
        asr = WhisperASR(name, device=a.device, compute_type=ct or "float16")
        asr.warmup()
        for lang in a.langs:
            sep = "" if lang in NO_SPACES else " "
            seen, conf, where = Counter(), defaultdict(list), defaultdict(list)
            empty = 0
            for label, pcm in data:
                ws = asr.transcribe(pcm, language=lang)
                key = sep.join(k for k in (_norm(w) for w in ws) if k)
                if not key:
                    empty += 1
                    continue
                seen[key] += 1
                conf[key].append(float(np.mean([w.prob for w in ws])))
                where[key].append(label)
            top = [{"text": k, "n": n, "conf": round(float(np.mean(conf[k])), 3), "clips": where[k][:6]}
                   for k, n in seen.most_common()]
            results.append({"model": spec, "lang": lang, "clips": len(data), "empty": empty, "phrases": top})
            print(f"  {spec:<26} {lang}: {len(data) - empty}/{len(data)} clips with text", flush=True)
            for p in top[:12]:
                print(f"      {p['n']:>3}×  conf {p['conf']:.2f}  {p['text']}", flush=True)
        del asr

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# What Whisper writes without voice\n"]
    for r in results:
        md += [f"## {r['model']} · {r['lang']} · {r['clips'] - r['empty']}/{r['clips']} clips with text\n",
               "| × | Confidence | Phrase (normalized) | Clips |", "|---|---|---|---|"]
        md += [f"| {p['n']} | {p['conf']} | {p['text']} | {', '.join(p['clips'])} |" for p in r["phrases"]]
        md.append("")
    (out / "results.md").write_text("\n".join(md), encoding="utf-8")
    print(f"→ {out / 'results.md'}")


if __name__ == "__main__":
    main()
