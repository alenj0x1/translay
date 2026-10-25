"""Compara motores de voz (clonación EN → voz ES) con métricas objetivas.

Para cada diálogo de prueba, arma la referencia de cada persona con su voz
original (según <nombre>.truth.json), traduce sus frases al español y las
sintetiza con su voz clonada. Mide:

  sim     parecido de voz: coseno de huellas (WeSpeaker) clon ES ↔ original EN
  id      % de frases donde el clon se parece más a su persona que a las demás
  wer     inteligibilidad: Whisper (es) transcribe el clon vs. el texto pedido
  f0      tono: mediana F0 del clon / mediana F0 del original (1.00 = igual)
  rtf     segundos de GPU por segundo de audio generado
  dur     duración del clon / duración de la frase original en inglés

Los audios quedan en samples/tts_eval/<motor>/ para escucharlos.

    python tools/eval_tts.py --engines chatterbox omnivoice voxcpm --samples podcast panel friends
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vt.asr import WhisperASR  # noqa: E402
from vt.audiofx import denoise, enhance, median_f0, read_wav, resample, snr_estimate, trim_silence, write_wav  # noqa: E402
from vt.speakers import SpeakerEmbedder  # noqa: E402
from vt.translate import load_translator  # noqa: E402
from vt.tts import TTSClient  # noqa: E402

OUT = ROOT / "samples" / "tts_eval"


def decode(path, sr):
    import av

    out = []
    with av.open(str(path)) as c:
        res = av.AudioResampler(format="s16", layout="mono", rate=sr)
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) / 32768.0


def norm_words(t):
    t = t.lower()
    t = re.sub(r"[¿¡.,;:!?\"“”()«»—–-]", " ", t)
    return t.split()


def wer(ref, hyp):
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(1, len(ref))


def build_refs(sample, media, truth, ref_sr, max_s, clean, ref_wav=None):
    """Referencia por persona: sus frases más largas, hasta max_s segundos."""
    if ref_wav:
        audio, sr = read_wav(ref_wav.format(s=sample))
        audio = resample(audio, sr, ref_sr)
    else:
        audio = decode(media, ref_sr)
    refs = {}
    for spk in sorted({t["speaker"] for t in truth}):
        utts = sorted([t for t in truth if t["speaker"] == spk], key=lambda t: t["end"] - t["start"], reverse=True)
        parts, texts, total = [], [], 0.0
        for t in utts:
            if total >= max_s:
                break
            parts.append(audio[int(t["start"] * ref_sr): int(t["end"] * ref_sr)])
            parts.append(np.zeros(int(0.15 * ref_sr), np.float32))
            texts.append(t["text"])
            total += t["end"] - t["start"]
        x = np.concatenate(parts[:-1])
        if clean == "gate" and snr_estimate(x, ref_sr) < 25:
            x = denoise(x, ref_sr)
        elif clean == "wiener" and snr_estimate(x, ref_sr) < 25:
            x = enhance(x, ref_sr)
        path = OUT / "refs" / f"{media.stem}_{spk}_{ref_sr // 1000}k.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_wav(path, x, ref_sr)
        refs[spk] = (str(path), " ".join(texts), x)
    return refs


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--engines", nargs="+", default=["chatterbox", "omnivoice", "voxcpm"])
    p.add_argument("--samples", nargs="+", default=["podcast", "panel", "friends"])
    p.add_argument("--noise", default="", help="sufijo de variante con ruido, p. ej. _cafe10")
    p.add_argument("--ref-sr", type=int, default=16000)
    p.add_argument("--ref-s", type=float, default=10.0)
    p.add_argument("--clean", default="none", choices=["none", "gate", "wiener"])
    p.add_argument("--ref-wav", help="audio para las referencias, p. ej. samples/tts_eval/{s}_pink5_df.wav")
    p.add_argument("--lines", type=int, default=6, help="frases por diálogo")
    p.add_argument("--fit", action="store_true", help="pide la duración de la frase original (si el motor lo permite)")
    p.add_argument("--params", default="{}", help="JSON con parámetros del motor")
    a = p.parse_args()

    # Fase 0: frases y referencias (el traductor se libera antes de la voz)
    emb = SpeakerEmbedder()
    mt = load_translator("opus-big")
    jobs = []  # (sample, idx, spk, en, es, orig_dur, ref)
    orig_emb, orig_f0 = {}, {}
    for s in a.samples:
        truth = json.loads((ROOT / "samples" / f"{s}.truth.json").read_text(encoding="utf-8"))
        media = ROOT / "samples" / f"{s}{a.noise}.mp4"
        refs = build_refs(s, media, truth, a.ref_sr, a.ref_s, a.clean, a.ref_wav)
        clean16 = decode(ROOT / "samples" / f"{s}.mp4", 16000)  # métricas contra la voz limpia
        for spk in refs:
            seg = np.concatenate([clean16[int(t["start"] * 16000): int(t["end"] * 16000)]
                                  for t in truth if t["speaker"] == spk])
            orig_emb[(s, spk)] = emb.embed(seg)
            orig_f0[(s, spk)] = median_f0(seg, 16000)
        lines = truth[: a.lines] if a.lines else truth
        es = mt.translate_many([t["text"] for t in lines])
        for i, (t, e) in enumerate(zip(lines, es)):
            jobs.append((s, i, t["speaker"], t["text"], e, t["end"] - t["start"], refs[t["speaker"]]))
    del mt

    # Fase 1: síntesis con el motor solo en la GPU (velocidad real)
    params = json.loads(a.params)
    gen = {}
    for engine in a.engines:
        t0 = time.perf_counter()
        tts = TTSClient(engine)
        load = time.perf_counter() - t0
        tts.synth("Hola, esto es una prueba.", ref=jobs[0][6][0], ref_text=jobs[0][6][1], **params)
        out = OUT / engine
        out.mkdir(parents=True, exist_ok=True)
        gen[engine] = []
        for s, i, spk, en, es, odur, (ref, ref_text, _) in jobs:
            extra = dict(params)
            if a.fit:
                extra["duration"] = round(odur * 1.1, 2)
            y, sr, gpu = tts.synth(es, ref=ref, ref_text=ref_text, **extra)
            y = trim_silence(y, sr)
            write_wav(out / f"{s}{a.noise}_{i:02}_{spk}.wav", y, sr)
            gen[engine].append((y, sr, gpu))
        tts.close()
        print(f"{engine}: carga {load:.0f}s, síntesis {sum(g for _, _, g in gen[engine]):.0f}s", flush=True)

    # Fase 2: puntuación (Whisper entra cuando la GPU ya está libre)
    asr = WhisperASR(language="es")
    summary = []
    for engine in a.engines:
        rows = []
        print(f"\n=== {engine}")
        for (s, i, spk, en, es, odur, _), (y, sr, gpu) in zip(jobs, gen[engine]):
            y16 = resample(y, sr, 16000)
            e = emb.embed(y16)
            own = float(e @ orig_emb[(s, spk)]) if e is not None else 0
            others = [float(e @ v) for (ss, sp), v in orig_emb.items() if ss == s and sp != spk and e is not None]
            hyp = " ".join(w.text for w in asr.transcribe(y16))
            w = wer(norm_words(es), norm_words(hyp))
            f0r = median_f0(y16, 16000) / (orig_f0[(s, spk)] or 1)
            dur = len(y) / sr
            rows.append((own, own > max(others, default=-1), w, f0r, gpu / max(dur, 0.1), dur / odur))
            print(f"  {s}#{i:02} {spk:<11} sim {own:.2f} wer {w:5.1%} f0 {f0r:.2f} rtf {gpu / dur:.2f} "
                  f"dur {dur / odur:.2f} | {es}")
            if w > 0.25:
                print(f"{'':16}↳ oyó: {hyp}")
        r = np.array(rows, dtype=float)
        summary.append((engine, r[:, 0].mean(), r[:, 1].mean(), r[:, 2].mean(), np.median(r[:, 3]),
                        np.abs(np.log(np.maximum(r[:, 3], 1e-3))).mean(), r[:, 4].mean(), r[:, 5].mean()))
    print(f"\n{'motor':<12} {'sim':>5} {'id':>5} {'wer':>6} {'f0':>5} {'|Δf0|':>6} {'rtf':>5} {'dur':>5}")
    for e, sim, ide, w, f0, df0, rtf, dur in summary:
        print(f"{e:<12} {sim:5.2f} {ide:5.0%} {w:6.1%} {f0:5.2f} {df0:6.2f} {rtf:5.2f} {dur:5.2f}")


if __name__ == "__main__":
    main()
