"""Separa el audio de un video en diálogo y fondo (música + efectos). Corre en el entorno del motor de voz (torch);
lo lanza vt/separation.py, uno a la vez.

    python separate_worker.py --weights <97d170e1-dbb4db15.th> --input <video o audio> --out <fondo.wav> [--cpu]

Modelo: CDX23, HT-Demucs entrenado en Divide and Remaster (diálogo, efectos, música), MIT
(github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing). Medido en tools/lab/dub_quality.py: deja la voz
original 17 a 41 dB más baja que bajar el volumen del original y conserva el fondo casi entero, a 0,08 del tiempo
real en una RTX 4060 (575 MB de memoria de la GPU).

El audio va por tramos de 60 s con 2 s de cruce (memoria acotada aunque el video dure horas). Los pesos se leen en
el modo seguro de torch, permitiendo solo las dos clases que trae el archivo. Imprime una línea JSON por avance
({"progress": 0..1}) y al final {"done": true, "seconds": s, "device": "cuda"|"cpu"}.
"""

import argparse
import json
import subprocess
import sys
import time
from fractions import Fraction

import numpy as np
import torch

SR = 44100
CHUNK_S = 60
CROSS_S = 2


def load_audio(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cpu", action="store_true")
    a = ap.parse_args()
    from demucs.apply import apply_model
    from demucs.htdemucs import HTDemucs
    from demucs.states import load_model

    device = "cpu" if a.cpu or not torch.cuda.is_available() else "cuda"
    if device == "cpu":
        torch.set_num_threads(max(1, (torch.get_num_threads() or 2) // 2))  # la mitad: la app sigue respondiendo
    with torch.serialization.safe_globals([HTDemucs, Fraction]):
        model = load_model(a.weights).to(device).eval()
    x = load_audio(a.input)
    n = x.shape[1]
    out = np.zeros_like(x)
    step, cross = CHUNK_S * SR, CROSS_S * SR
    t0 = time.perf_counter()
    pos = 0
    while pos < n:
        lo, hi = max(0, pos - cross), min(n, pos + step)
        with torch.no_grad():
            est = apply_model(model, torch.from_numpy(x[:, lo:hi])[None].to(device), shifts=1, overlap=0.5)[0].cpu().numpy()
        bg = est[0] + est[1]  # salida: música, efectos, diálogo
        if lo < pos:  # cruce lineal con el tramo anterior
            w = np.linspace(0, 1, pos - lo, dtype=np.float32)
            out[:, lo:pos] = out[:, lo:pos] * (1 - w) + bg[:, : pos - lo] * w
        out[:, pos:hi] = bg[:, pos - lo:]
        pos = hi
        print(json.dumps({"progress": round(pos / n, 3)}), flush=True)
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-", a.out],
                       input=np.ascontiguousarray(out.T, np.float32).tobytes(), capture_output=True)
    if p.returncode:
        sys.exit(p.stderr.decode(errors="replace")[-400:])
    print(json.dumps({"done": True, "seconds": round(time.perf_counter() - t0, 1), "device": device}), flush=True)


if __name__ == "__main__":
    main()
