"""Separa el audio de un video en diálogo y fondo (música + efectos). Corre en el entorno de voz
(.venvs/omnivoice, con torch); lo llama tools/lab/dub_quality.py para las variantes con separación.

    .venvs/omnivoice/Scripts/python.exe tools/lab/separate.py --model cdx23 entrada.wav carpeta_salida/

Modelos (en data/labs/models/):
  cdx23      HT-Demucs entrenado en Divide and Remaster (diálogo, efectos, música), un modelo. MIT.
             github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing (v.1.0.0)
  cdx23-hq   los tres modelos de CDX23 promediados (unas 3 veces más lento).
  bandit2    Bandit v2, checkpoint multilingüe (habla, música, efectos), 48 kHz. Pesos CC BY-SA 4.0
             (zenodo.org/records/12701995), código Apache-2.0 (github.com/kwatcharasupat/bandit-v2).
  bandit2-spa el checkpoint de Bandit v2 entrenado con diálogo en español.

Escribe dialogo.wav y fondo.wav (estéreo, a la frecuencia del modelo) e imprime en JSON los segundos que
tardó, el tiempo real (rtf) y la memoria de la gráfica que usó como máximo.
"""

import argparse
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "data" / "labs" / "models"


def load_audio(path: Path, sr: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()  # (2, n)


def save(path: Path, x: np.ndarray, sr: int):
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(sr), "-i", "-", str(path)],
                       input=np.ascontiguousarray(x.T, np.float32).tobytes(), capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))


def cdx23(audio_path: Path, hq: bool, device: str):
    from demucs.apply import apply_model
    from demucs.states import load_model

    names = ["97d170e1-a778de4a.th", "97d170e1-dbb4db15.th", "97d170e1-e41a5468.th"] if hq else ["97d170e1-dbb4db15.th"]
    sr = 44100
    x = load_audio(audio_path, sr)
    t0 = time.perf_counter()
    outs = []
    from fractions import Fraction

    from demucs.htdemucs import HTDemucs

    for n in names:
        # los pesos se leen en modo seguro: solo se permiten las dos clases que trae el archivo
        with torch.serialization.safe_globals([HTDemucs, Fraction]):
            model = load_model(str(MODELS / "cdx23" / n)).to(device).eval()
        with torch.no_grad():
            # como su inference.py: una pasada, 80 % de solapamiento; salida = música, efectos, diálogo
            outs.append(apply_model(model, torch.from_numpy(x)[None].to(device), shifts=1, overlap=0.8)[0].cpu().numpy())
        del model
    est = np.mean(outs, axis=0)
    return est[2], est[0] + est[1], sr, time.perf_counter() - t0


def bandit2(audio_path: Path, ckpt: str, device: str):
    code = MODELS / "bandit2" / "code"
    # su clase base es un LightningModule solo de nombre: un módulo mínimo evita instalar pytorch_lightning
    pl = types.ModuleType("pytorch_lightning")
    pl.LightningModule = torch.nn.Module
    sys.modules.setdefault("pytorch_lightning", pl)
    # torchaudio ya no trae torchaudio.io; su código solo lo usa para leer archivos (aquí llega el audio ya leído)
    tio = types.ModuleType("torchaudio.io")
    tio.StreamReader = None
    sys.modules.setdefault("torchaudio.io", tio)
    sys.path.insert(0, str(code))
    from src.models.bandit.bandit import Bandit
    from src.system.inference_handler import StandardTensorChunkedInferenceHandler

    sr = 48000
    model = Bandit(in_channels=1, stems=["speech", "music", "sfx"], band_type="musical", n_bands=64,
                   normalize_channel_independently=False, treat_channel_as_feature=True, n_sqm_modules=8, emb_dim=128,
                   rnn_dim=256, bidirectional=True, rnn_type="GRU", mlp_dim=512, hidden_activation="Tanh",
                   complex_mask=True, use_freq_weights=True, n_fft=2048, win_length=2048, hop_length=512,
                   window_fn="hann_window", power=None, center=True, normalized=True, pad_mode="reflect",
                   onesided=True, fs=sr)
    sd = torch.load(str(MODELS / "bandit2" / ckpt), map_location="cpu", weights_only=True)["state_dict"]
    sd = {k[len("model."):]: v for k, v in sd.items() if k.startswith("model.")}
    missing, unexpected = model.load_state_dict(sd, strict=False)
    if missing:
        raise RuntimeError(f"faltan pesos: {missing[:5]}")
    model.to(device).eval()
    handler = StandardTensorChunkedInferenceHandler(chunk_size_seconds=8.0, hop_size_seconds=1.0, inference_batch_size=4,
                                                    fs=sr).to(device)
    x = load_audio(audio_path, sr)
    t0 = time.perf_counter()
    with torch.inference_mode():
        out = handler(torch.from_numpy(x)[None].to(device), model)["estimates"]
    get = lambda s: out[s]["audio"][0].float().cpu().numpy()  # noqa: E731
    return get("speech"), get("music") + get("sfx"), sr, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=["cdx23", "cdx23-hq", "bandit2", "bandit2-spa"])
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("audio")
    ap.add_argument("out")
    a = ap.parse_args()
    device = "cpu" if a.cpu or not torch.cuda.is_available() else "cuda"
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    src, out = Path(a.audio), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.model.startswith("cdx23"):
        dialog, background, sr, secs = cdx23(src, a.model.endswith("hq"), device)
    else:
        dialog, background, sr, secs = bandit2(src, "checkpoint-spa.ckpt" if a.model.endswith("spa") else "checkpoint-multi.ckpt",
                                               device)
    save(out / "dialogo.wav", dialog, sr)
    save(out / "fondo.wav", background, sr)
    dur = dialog.shape[-1] / sr
    print(json.dumps({"model": a.model, "device": device, "seconds": round(secs, 2), "rtf": round(secs / dur, 3),
                      "vram_mb": round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else 0,
                      "sr": sr}))


if __name__ == "__main__":
    main()
