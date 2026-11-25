"""Naturalidad (UTMOS22 Strong, 1–5) de cada archivo de audio. Corre en el entorno de OmniVoice, que trae el
modelo (omnivoice.eval); lo llama tools/lab/dub_quality.py.

    .venvs/omnivoice/Scripts/python.exe tools/lab/utmos_score.py <utmos22_strong_step7459_v1.pt> a.wav b.wav …

Imprime {ruta: nota} en JSON. Usa la gráfica si hay, si no el procesador.
"""

import json
import sys

import torch
from omnivoice.eval.models.utmos import UTMOS22Strong
from omnivoice.eval.utils import load_eval_waveform


def main():
    weights, paths = sys.argv[1], sys.argv[2:]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = UTMOS22Strong()
    model.load_state_dict(torch.load(weights, map_location="cpu"))
    model.to(device).eval()
    out = {}
    with torch.no_grad():
        for p in paths:
            wav = load_eval_waveform(p, 16000, device=device)
            out[p] = round(float(model(wav.unsqueeze(0), 16000).item()), 3)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
