"""Separa el audio de un video en diálogo y fondo (música + efectos). Corre en el entorno del motor de voz (torch);
lo lanza vt/separation.py, uno a la vez.

    python separate_worker.py --weights <97d170e1-dbb4db15.th> --input <video o audio> --out <fondo.wav> [--cpu]

Modelo: CDX23, HT-Demucs entrenado en Divide and Remaster (diálogo, efectos, música), MIT
(github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing). Medido en tools/lab/dub_quality.py: deja la voz
original 17 a 41 dB más baja que bajar el volumen del original y conserva el fondo casi entero, a 0,08 del tiempo
real en una RTX 4060 (575 MB de memoria de la GPU).

Todo va por tramos de 60 s con 2 s de cruce, de punta a punta: el audio se lee de ffmpeg de a un tramo y cada tramo
terminado se escribe al ffmpeg de salida, así la memoria queda acotada aunque el video dure horas. Los pesos se leen
en el modo seguro de torch, permitiendo solo las dos clases que trae el archivo. Imprime una línea JSON por tramo
({"progress": segundos}) y al final {"done": true, "seconds": s, "device": "cuda"|"cpu"}.
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
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.input, "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-", a.out],
                           stdin=subprocess.PIPE)
    step, cross = CHUNK_S * SR, CROSS_S * SR
    carry = np.zeros((2, 0), np.float32)  # los últimos 2 s de entrada del tramo anterior (contexto del cruce)
    tail = None  # el fondo de esos 2 s según el tramo anterior: se mezcla con el del siguiente
    done_s, t0 = 0.0, time.perf_counter()

    def write(x):
        enc.stdin.write(np.ascontiguousarray(x.T, np.float32).tobytes())

    try:
        while True:
            raw = dec.stdout.read(step * 2 * 4)
            if not raw:
                break
            x = np.frombuffer(raw[: len(raw) // 8 * 8], np.float32).reshape(-1, 2).T
            inp = np.concatenate([carry, x], axis=1)
            with torch.no_grad():
                est = apply_model(model, torch.from_numpy(np.ascontiguousarray(inp))[None].to(device), shifts=1,
                                  overlap=0.5)[0].cpu().numpy()
            bg = est[0] + est[1]  # salida: música, efectos, diálogo
            k = carry.shape[1]
            if tail is not None and k:  # cruce lineal con lo que dejó el tramo anterior
                w = np.linspace(0, 1, k, dtype=np.float32)
                bg[:, :k] = tail * (1 - w) + bg[:, :k] * w
            keep = min(cross, inp.shape[1])
            write(bg[:, : inp.shape[1] - keep])  # lo terminado; los últimos 2 s esperan al tramo siguiente
            tail, carry = bg[:, inp.shape[1] - keep:], inp[:, inp.shape[1] - keep:]
            done_s += x.shape[1] / SR
            print(json.dumps({"progress": round(done_s, 1)}), flush=True)
        if tail is not None:
            write(tail)
    finally:
        enc.stdin.close()
        enc.wait()
        dec.wait()
    if enc.returncode or dec.returncode:
        sys.exit("ffmpeg falló al leer o escribir el audio")
    print(json.dumps({"done": True, "seconds": round(time.perf_counter() - t0, 1), "device": device}), flush=True)


if __name__ == "__main__":
    main()
