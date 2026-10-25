"""Proceso de voz: corre en el entorno del motor (.venvs/<motor>), no en el del servidor.

Protocolo (vt/ipc.py) por stdin/stdout:
  → {"op":"synth","text","lang","ref","ref_text","params"}   ← {"ok","sr"} + float32
  → {"op":"quit"}
Al arrancar responde {"ok":true,"sr":<frecuencia>} cuando el modelo cargó.
"""

import argparse
import os
import sys
import traceback

# stdout queda reservado para las tramas; lo que impriman las librerías va a stderr
_OUT = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
_IN = sys.stdin.buffer
sys.stdout = sys.stderr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np  # noqa: E402

from vt.ipc import read_msg, write_msg  # noqa: E402

LANG_NAMES = {"es": "Spanish", "en": "English"}


class Chatterbox:
    def __init__(self, device):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        import torch

        self.model = ChatterboxMultilingualTTS.from_pretrained(device=torch.device(device))
        self.sr = self.model.sr
        self._ref = None

    def synth(self, text, lang, ref, ref_text, p):
        kw = dict(exaggeration=p.get("exaggeration", 0.5), cfg_weight=p.get("cfg_weight", 0.5),
                  temperature=p.get("temperature", 0.8))
        if ref and ref != self._ref:
            kw["audio_prompt_path"] = ref
            self._ref = ref
        import torch

        # autocast fp16: el modelo de lenguaje interno corre en fp32 por defecto
        with torch.autocast("cuda", dtype=torch.float16, enabled=p.get("fp16", True)):
            wav = self.model.generate(text, language_id=lang, **kw)
        return wav.squeeze(0).float().cpu().numpy()


class VoxCPM:
    def __init__(self, device):
        import soundfile as sf
        import torch
        import torchaudio

        # torchaudio ≥2.9 exige torchcodec (atado a versiones de FFmpeg); para leer
        # el WAV de referencia basta soundfile
        def _load(path, *a, **k):
            x, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return torch.from_numpy(x.T.copy()), sr

        torchaudio.load = _load
        from voxcpm import VoxCPM as V

        self.model = V.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
        self.sr = self.model.tts_model.sample_rate

    def synth(self, text, lang, ref, ref_text, p):
        kw = dict(text=text, cfg_value=p.get("cfg_value", 2.0),
                  inference_timesteps=p.get("timesteps", 10))
        if ref and ref_text:
            kw.update(prompt_wav_path=ref, prompt_text=ref_text)
        return np.asarray(self.model.generate(**kw), np.float32)


class OmniVoice:
    def __init__(self, device):
        import torch
        from omnivoice import OmniVoice as O

        self.model = O.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=torch.float16)
        self.sr = self.model.sampling_rate
        self._prompts = {}
        self._clean = {}
        try:
            from vt.enhance_df import Enhancer

            self.enhancer = Enhancer()
        except Exception as e:  # sin realzador se clona la referencia tal cual
            print(f"DeepFilterNet no disponible: {e}", flush=True)
            self.enhancer = None

    def _clean_ref(self, ref: str, mode) -> str:
        """Limpia la referencia con DeepFilterNet si es ruidosa (SNR < 20 dB).

        Medido con tools/eval_tts.py: con ruido fuerte el parecido de voz del clon
        sube de 0.45 a 0.59 y el tono deja de desviarse; con referencias limpias no
        se toca (cualquier procesamiento le resta un poco de identidad)."""
        if not mode or self.enhancer is None:
            return ref
        key = (ref, os.path.getmtime(ref))
        if key not in self._clean:
            from vt.audiofx import read_wav, snr_estimate, write_wav

            x, sr = read_wav(ref)
            if mode == "always" or snr_estimate(x, sr) < 20:
                out = ref[:-4] + "_df.wav"
                write_wav(out, self.enhancer(x, sr), sr)
                self._clean[key] = out
            else:
                self._clean[key] = ref
        return self._clean[key]

    def synth(self, text, lang, ref, ref_text, p):
        kw = dict(text=text, language=LANG_NAMES.get(lang, lang), num_step=p.get("num_step", 16),
                  guidance_scale=p.get("guidance_scale", 2.0))
        if p.get("duration"):
            kw["duration"] = float(p["duration"])
        if ref:
            ref = self._clean_ref(ref, p.get("clean_ref", "auto"))
            key = (ref, os.path.getmtime(ref))
            if key not in self._prompts:
                self._prompts[key] = self.model.create_voice_clone_prompt(ref_audio=ref, ref_text=ref_text)
            kw["voice_clone_prompt"] = self._prompts[key]
        return np.asarray(self.model.generate(**kw)[0], np.float32).reshape(-1)


ENGINES = {"chatterbox": Chatterbox, "voxcpm": VoxCPM, "omnivoice": OmniVoice}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--engine", required=True)
    a.add_argument("--device", default="cuda")
    args = a.parse_args()
    try:
        eng = ENGINES[args.engine](args.device)
        write_msg(_OUT, {"ok": True, "sr": int(eng.sr)})
    except Exception as e:
        traceback.print_exc()
        write_msg(_OUT, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return
    while True:
        try:
            h, _ = read_msg(_IN)
        except EOFError:
            return
        if h.get("op") == "quit":
            return
        try:
            y = eng.synth(h["text"], h.get("lang", "es"), h.get("ref"), h.get("ref_text"), h.get("params") or {})
            write_msg(_OUT, {"ok": True, "sr": int(eng.sr)}, np.asarray(y, np.float32).tobytes())
        except Exception as e:
            traceback.print_exc()
            write_msg(_OUT, {"ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
