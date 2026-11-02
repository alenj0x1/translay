"""Qué modelos usa cada perfil, cuáles faltan y cómo bajarlos.

  info()                  repo → {label, purpose, profiles}: para qué sirve cada modelo de Translay
  repos(profile)          los que usa un perfil (reconocimiento, traductor de cada idioma, personas, voz)
  plan(profile)           lo que falta bajar para ese perfil y lo que deja de usarse
  prefetch(profile)       baja lo que falta, con una línea de avance «Descargando …: NN%|» (la pantalla
                          de carga de la app de escritorio la muestra como barra)

Desde la línea de comandos (el instalador de la app de escritorio, antes de que haya servidor):

  python -m vt.modelset profiles --data-dir D    perfiles con el recomendado y cuánto baja cada uno (JSON)
  python -m vt.modelset prepare --data-dir D --profile P
                                                 guarda el perfil elegido y baja sus modelos; cada avance
                                                 sale como «PROGRESS <bytes hechos> <bytes en total> <modelo>»
"""

import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from .modelusage import VOICE_REPOS

VOICE_NAMES = {"omnivoice": "OmniVoice", "voxcpm": "VoxCPM", "chatterbox": "Chatterbox"}
VOICE_ENGINE = "omnivoice"  # el motor de voz de los perfiles con voz
# lo que pesa cada modelo al bajarlo (medido en la caché de Hugging Face); uno sin medir cuenta 500 MB
BYTES = {
    "mobiuslabsgmbh/faster-whisper-large-v3-turbo": 1_620_000_000, "Systran/faster-whisper-large-v3": 3_090_000_000,
    "Systran/faster-whisper-medium.en": 1_530_000_000, "Systran/faster-whisper-small.en": 486_000_000,
    "Systran/faster-whisper-small": 486_000_000, "Systran/faster-whisper-base.en": 145_000_000,
    "michaelfeil/ct2fast-opus-mt-en-es": 160_000_000, "ooeoeo/opus-mt-tc-big-en-es-ct2-float16": 470_000_000,
    "opus:itc-itc": 430_000_000, "OpenNMT/nllb-200-distilled-1.3B-ct2-int8": 1_400_000_000,
    "Nextcloud-AI/madlad400-3b-mt-ct2-int8": 2_980_000_000, "k2-fsa/OmniVoice": 3_270_000_000,
    "openbmb/VoxCPM2": 4_960_000_000, "ResembleAI/chatterbox": 3_210_000_000,
    "onnx-community/wespeaker-voxceleb-resnet34-LM": 27_000_000,
}
VOICE_ENV_BYTES = 4_800_000_000  # el entorno del motor de voz (app de escritorio, locks/voice.txt)


def size(repo: str) -> int:
    return BYTES.get(repo, 500_000_000)


def info() -> dict[str, dict]:
    """repo → {label, purpose, profiles}: para qué sirve cada modelo y qué perfiles lo usan."""
    from . import langs
    from .asr import MODELS as ASR
    from .profiles import PROFILES
    from .speakers import SpeakerEmbedder
    from .translate import MODELS as MT

    def pairs(name):
        p = MT[name][3]
        if p is None:
            return "de cualquier idioma al español"
        srcs = {a for a, b in p if b == langs.TARGET}
        return "del inglés al español" if srcs == {"en"} else "del portugués y otras lenguas romances al español"

    out = {repo: {"label": f"Reconocimiento · Whisper {name}", "purpose": "Pasa a texto lo que se dice en el video"}
           for name, repo in ASR.items()}
    out |= {m[1]: {"label": f"Traducción · {name}", "purpose": "Traduce " + pairs(name)} for name, m in MT.items()}
    out |= {repo: {"label": f"Voz · {VOICE_NAMES[name]}", "purpose": "Dobla al español con la voz de cada persona"}
            for name, repo in VOICE_REPOS.items()}
    out[SpeakerEmbedder.REPO] = {"label": "Personas · separar quién habla", "purpose": "Distingue quién habla en cada frase"}
    for i in out.values():
        i["profiles"] = []
    for pid, prof in PROFILES.items():
        for repo in repos(pid):
            if repo in out:
                out[repo]["profiles"].append(prof["name"])
    return out


def repos(profile: str) -> list[str]:
    """Los modelos que usa un perfil, en el orden en que se usan."""
    from . import langs
    from .asr import MODELS as ASR
    from .profiles import PROFILES
    from .speakers import SpeakerEmbedder
    from .translate import MODELS as MT, route

    prof = PROFILES[profile]
    out = [ASR[prof["asr"]]]
    for src in langs.SOURCES:
        if src != langs.TARGET and MT[route(src, prof["mt"])][1] not in out:
            out.append(MT[route(src, prof["mt"])][1])
    out.append(SpeakerEmbedder.REPO)
    if prof["voice"]:
        out.append(VOICE_REPOS[VOICE_ENGINE])
    return out


def path(repo: str) -> Path:
    if repo.startswith("opus:"):
        from .opusmt import models_dir
        return models_dir() / f"opus-{repo[5:]}"
    from huggingface_hub import constants
    return Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))


def have(repo: str) -> bool:
    """¿Ya está bajado? (una carpeta con los pesos, no a medias)."""
    if repo.startswith("opus:"):
        return (path(repo) / "model.bin").exists()
    snaps = path(repo) / "snapshots"
    return snaps.is_dir() and any(any(s.iterdir()) for s in snaps.iterdir() if s.is_dir()) \
        and not any((path(repo) / "blobs").glob("*.incomplete"))


def voice_env_ok() -> bool:
    from .tts import venv_python
    return venv_python(VOICE_ENGINE).exists()


def plan(profile: str) -> dict:
    """Lo que falta para usar `profile` y lo que deja de usarse si se pasa a él."""
    from .profiles import PROFILES

    names = info()
    need = repos(profile)
    missing = [{"repo": r, "label": names.get(r, {}).get("label", r), "purpose": names.get(r, {}).get("purpose", ""),
                "bytes": size(r)} for r in need if not have(r)]
    voice = PROFILES[profile]["voice"]
    unused = [{"repo": r, "label": i["label"], "bytes": _dir_size(path(r))}
              for r, i in names.items() if r not in need and path(r).exists()]
    return {"profile": profile, "name": PROFILES[profile]["name"], "missing": missing,
            "missing_bytes": sum(m["bytes"] for m in missing), "voice": voice,
            "voice_env": bool(voice and not voice_env_ok()), "voice_env_bytes": VOICE_ENV_BYTES,
            "unused": unused, "unused_bytes": sum(u["bytes"] for u in unused)}


def _dir_size(p: Path) -> int:
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def download(repo: str):
    """Solo los archivos que se usan, como los baja cada motor al usarlo."""
    from huggingface_hub import hf_hub_download, snapshot_download

    from .asr import MODELS as ASR
    from .speakers import SpeakerEmbedder
    from .translate import MODELS as MT, model_dir

    if repo == SpeakerEmbedder.REPO:
        hf_hub_download(repo, "onnx/model.onnx")
    elif repo.startswith("opus:") or repo in {m[1] for m in MT.values()}:
        model_dir(repo)
    elif repo in ASR.values():  # lo de faster-whisper (download_model)
        snapshot_download(repo, allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                                "tokenizer.json", "vocabulary.*"])
    else:
        snapshot_download(repo)


def prefetch(profile: str, report=None, voice: bool = True) -> list[str]:
    """Baja los modelos del perfil que falten (sin voice, salvo el de voz). report(hecho, total, nombre)
    recibe el avance en bytes (se mide el tamaño de la carpeta mientras baja); sin report, imprime
    «Descargando …: NN%|»."""
    names = info()
    todo = [r for r in repos(profile) if not have(r) and (voice or r not in VOICE_REPOS.values())]
    total = sum(size(r) for r in todo)
    done = 0
    for repo in todo:
        label = names.get(repo, {}).get("label", repo)
        stop = threading.Event()

        def watch(repo=repo, label=label, base=done):
            while not stop.wait(1.0):
                now = min(base + _dir_size(path(repo)), total)
                if report:
                    report(now, total, label)
                else:
                    print(f"Descargando {label}: {round(now * 100 / max(total, 1))}%|", flush=True)

        t = threading.Thread(target=watch, daemon=True)
        t.start()
        try:
            download(repo)
        finally:
            stop.set()
            t.join()
        done += max(size(repo), _dir_size(path(repo)))  # el avance nunca vuelve atrás
        total = max(total, done)
        if report:
            report(min(done, total), total, label)
    return todo


def remove(repo: str) -> int:
    p = path(repo)
    if not p.exists():
        return 0
    n = _dir_size(p)
    shutil.rmtree(p, ignore_errors=True)
    return n


# ------------------------------------------------------------------ línea de comandos
def _profiles(data: Path) -> dict:
    from . import hardware, profiles
    from .prefs import Prefs

    prefs = Prefs(data / "prefs.json")
    hw = hardware.detect()
    rows = profiles.evaluate(hw)
    for r in rows:
        p = plan(r["id"])
        r["download_bytes"] = p["missing_bytes"]
        r["voice_env"] = p["voice_env"]
    return {"recommended": profiles.recommend(hw), "choice": prefs.values.get("perf_profile", "auto"),
            "voice_env_bytes": VOICE_ENV_BYTES, "profiles": rows}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m vt.modelset", description="Modelos de cada perfil (app de escritorio)")
    p.add_argument("cmd", choices=("profiles", "prepare"))
    p.add_argument("--data-dir", required=True, help="Carpeta de datos de la biblioteca Principal")
    p.add_argument("--profile", default="", help="Perfil elegido (prepare): auto o uno de vt/profiles.py")
    a = p.parse_args(argv)
    data = Path(a.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    if a.cmd == "profiles":
        print(json.dumps(_profiles(data), ensure_ascii=False))
        return
    from . import hardware, profiles
    from .prefs import Prefs

    prefs = Prefs(data / "prefs.json")
    if a.profile:
        prefs.set("perf_profile", a.profile)
    active = profiles.resolve(prefs.values.get("perf_profile", "auto"), hardware.detect())
    last = [0.0]

    def report(done, total, label):
        if time.time() - last[0] > 0.5 or done >= total:
            last[0] = time.time()
            print(f"PROGRESS {done} {total} {label}", flush=True)

    prefetch(active, report, voice=voice_env_ok())
    print("PROGRESS 1 1 listo", flush=True)


if __name__ == "__main__":
    sys.exit(main())
