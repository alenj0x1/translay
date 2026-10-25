"""Genera diálogos de prueba multi-voz con Kokoro (inglés) y variantes con ruido.

Se ejecuta con el entorno de Kokoro:

    .venvs/kokoro/Scripts/python tools/make_dialogue.py tools/samples/podcast.txt \
        --noise clean cafe:10 music:12 pink:5

Guion: una línea por intervención "voz|texto" (voces de Kokoro: af_heart,
am_michael, bf_emma, bm_lewis…); línea vacía = pausa larga.

Salida en samples/: <nombre>[_<ruido><snr>].mp4 y <nombre>.truth.json con la
verdad de referencia (quién habla, cuándo, qué dice) para medir diarización.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vt.audiofx import mix_at_snr, noise, write_wav  # noqa: E402

SR = 24000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("script")
    p.add_argument("--noise", nargs="*", default=["clean"])
    p.add_argument("--out", default=str(ROOT / "samples"))
    a = p.parse_args()

    from kokoro import KPipeline

    pipes = {"a": KPipeline(lang_code="a"), "b": KPipeline(lang_code="b")}
    name = Path(a.script).stem
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    audio, truth, t = [], [], 0.0
    rng = np.random.default_rng(7)
    for line in Path(a.script).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            gap = 0.9
        else:
            voice, text = line.split("|", 1)
            voice, text = voice.strip(), text.strip()
            chunks = [r.audio.numpy() for r in pipes[voice[0]](text, voice=voice, speed=1.0)]
            y = np.concatenate(chunks).astype(np.float32)
            truth.append({"speaker": voice, "start": round(t, 3), "end": round(t + len(y) / SR, 3), "text": text})
            audio.append(y)
            t += len(y) / SR
            gap = float(rng.uniform(0.25, 0.55))  # cambio de turno natural
        audio.append(np.zeros(int(gap * SR), np.float32))
        t += gap
    clean = np.concatenate(audio)
    clean = clean / np.abs(clean).max() * 0.8
    (out / f"{name}.truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")

    pool = [a for a in audio if len(a) > SR]
    for spec in a.noise:
        kind, _, snr = spec.partition(":")
        if kind == "clean":
            y, tag = clean, ""
        else:
            nz = noise(kind, len(clean), SR, seed=3, speech_pool=pool)
            y, tag = mix_at_snr(clean, nz, float(snr), SR), f"_{kind}{snr}"
        wav = out / f"_{name}{tag}.wav"
        mp4 = out / f"{name}{tag}.mp4"
        write_wav(wav, y, SR)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=0xF4F1EA:s=1280x720:r=25", "-i", str(wav), "-vf",
                        "drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':text='%{pts\\:hms}':"
                        "fontsize=96:fontcolor=0x111111:x=(w-tw)/2:y=(h-th)/2",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-b:a", "160k", str(mp4)], check=True)
        wav.unlink()
        print(f"OK {mp4.name} ({len(y) / SR:.1f}s)")


if __name__ == "__main__":
    main()
