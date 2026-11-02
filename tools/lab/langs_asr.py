"""Recognition lab per language: how well each Whisper model transcribes and detects the spoken language.

Data: FLEURS (Google, CC-BY-4.0), read sentences with their text (dev: en_us, pt_br, es_419) in
data/labs/languages/fleurs/<lang>/dev/*.wav and <lang>.dev.tsv (tools/lab/langs_data.py downloads them).

Measures, per model (and precision):
  WER        misrecognized words (%; lower is better), with the language given
  detection  % of clips whose language is detected right, and ms per detection
  ×          seconds of audio per wall-clock second while transcribing

--noise mixes noise at a signal-to-noise ratio (dB), like a real video:
  pink:5     pink noise at 5 dB
  babble:10  6 voices in the other languages at 10 dB (the hardest case for detection)

    python tools/lab/langs_asr.py --langs en pt es --models large-v3-turbo:float16 small:int8_float16 -n 120
    python tools/lab/langs_asr.py --models large-v3-turbo:int8_float16 --noise babble:5 pink:5
"""

import argparse
import csv
import json
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt.asr import MODELS, WhisperASR  # noqa: E402

DATA = ROOT / "data" / "labs" / "languages"
FLEURS = {"en": "en_us", "pt": "pt_br", "es": "es_419"}


def load(lang: str, n: int) -> list[tuple[np.ndarray, str]]:
    """One clip per sentence (its first recording), with the normalized text."""
    folder = DATA / "fleurs" / FLEURS[lang]
    seen, out = set(), []
    with open(DATA / "fleurs" / f"{FLEURS[lang]}.dev.tsv", encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            path = folder / "dev" / row[1]
            if row[0] in seen or not path.exists():
                continue
            seen.add(row[0])
            out.append((read_wav(path), row[2]))
            if len(out) >= n:
                break
    return out


def read_wav(path: Path) -> np.ndarray:
    """FLEURS WAV: 16 kHz mono, float32 samples (format 3, which the wave module can't read)."""
    raw = path.read_bytes()
    i = 12
    while i < len(raw):
        tag, size = raw[i:i + 4], int.from_bytes(raw[i + 4:i + 8], "little")
        if tag == b"data":
            return np.frombuffer(raw[i + 8:i + 8 + size], np.float32).copy()
        i += 8 + size + (size & 1)
    raise ValueError(f"WAV without data: {path}")


def words(s: str) -> list[str]:
    return re.sub(r"[^\w\s']", " ", unicodedata.normalize("NFC", s.lower())).split()


def edits(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def pink(n: int, rng) -> np.ndarray:
    """Pink (1/f) noise, shaped in the frequency domain."""
    f = np.fft.rfft(rng.standard_normal(n))
    f /= np.sqrt(np.maximum(np.arange(len(f)), 1))
    return np.fft.irfft(f, n).astype(np.float32)


def mix(data: dict, kind: str, snr: float, seed: int = 7) -> dict:
    """The same clips with noise at `snr` dB. Babble uses voices from the other languages."""
    rng = np.random.default_rng(seed)
    out = {}
    for lang, items in data.items():
        others = [pcm for k, v in data.items() if k != lang for pcm, _ in v]
        noisy = []
        for pcm, ref in items:
            if kind == "pink":
                nz = pink(len(pcm), rng)
            else:
                nz = np.zeros_like(pcm)
                for j in rng.choice(len(others), 6, replace=False):
                    o = np.resize(others[j], len(pcm))
                    nz += o / (np.sqrt(np.mean(o ** 2)) + 1e-9)
            gain = np.sqrt(np.mean(pcm ** 2) / (np.mean(nz ** 2) + 1e-12) / 10 ** (snr / 10))
            y = pcm + gain * nz
            noisy.append((y / max(1.0, float(np.abs(y).max())), ref))
        out[lang] = noisy
    return out


def run(asr, label: str, data: dict) -> dict:
    res = {"model": label, "langs": {}}
    for lang, items in data.items():
        errs = total = 0
        audio_s = clock = 0.0
        hits, det_ms, conf = 0, [], []
        for pcm, ref in items:
            t = time.perf_counter()
            got = "".join(w.text for w in asr.transcribe(pcm, language=lang))
            clock += time.perf_counter() - t
            audio_s += len(pcm) / 16000
            r = words(ref)
            errs += edits(r, words(got))
            total += len(r)

            t = time.perf_counter()
            code, prob = asr.detect(pcm)
            det_ms.append((time.perf_counter() - t) * 1000)
            hits += code == lang
            conf.append(prob)
        x = res["langs"][lang] = {
            "wer": round(100 * errs / total, 2), "detect": round(100 * hits / len(items), 1),
            "detect_ms": round(statistics.median(det_ms), 1), "detect_conf": round(statistics.median(conf), 3),
            "speed": round(audio_s / clock, 1), "n": len(items)}
        print(f"  {label:<36} {lang}  WER {x['wer']:>5}%  detection {x['detect']:>5}% "
              f"({x['detect_ms']} ms, conf. {x['detect_conf']})  {x['speed']}×", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--langs", nargs="+", default=["en", "pt", "es"], choices=list(FLEURS))
    ap.add_argument("--models", nargs="+", default=["large-v3-turbo:float16"],
                    help=f"model:precision ({', '.join(MODELS)})")
    ap.add_argument("-n", type=int, default=120, help="clips per language")
    ap.add_argument("--noise", nargs="*", default=[], help="kind:dB (pink:5, babble:10)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default=str(DATA / "asr"))
    a = ap.parse_args()

    data = {lang: load(lang, a.n) for lang in a.langs}
    print(", ".join(f"{k}: {len(v)} clips" for k, v in data.items()), flush=True)
    sets = [(nz, mix(data, nz.split(":")[0], float(nz.split(":")[1]))) for nz in a.noise] or [("clean", data)]
    results = []
    for spec in a.models:
        name, _, ct = spec.partition(":")
        asr = WhisperASR(name, device=a.device, compute_type=ct or "float16")
        asr.warmup()
        results += [run(asr, f"{spec} · {label}", d) for label, d in sets]
        del asr

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = "-".join(a.noise).replace(":", "") or "clean"
    (out / f"results-{tag}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# Recognition per language · FLEURS dev\n",
          "| Model | Language | WER % | Detection % | Detection ms | Confidence | × real time |",
          "|---|---|---|---|---|---|---|"]
    md += [f"| {r['model']} | {lang} | {x['wer']} | {x['detect']} | {x['detect_ms']} | {x['detect_conf']} | {x['speed']} |"
           for r in results for lang, x in r["langs"].items()]
    (out / f"results-{tag}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"→ {out / f'results-{tag}.md'}")


if __name__ == "__main__":
    main()
