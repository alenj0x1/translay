"""Cuándo se usó por última vez cada modelo (Preferencias → Almacenamiento).

Reconocimiento, traducción, voz y separar quién habla llaman a mark(repo) cada vez que trabajan;
se guarda en data/models.json como {"since": <inicio del registro>, "used": {repo: hora}}, a lo sumo
una vez cada SAVE_EVERY segundos por modelo (mark se llama por frase). Sin configure() (pruebas,
herramientas) no hace nada.
"""

import threading
import time
from pathlib import Path

from .jsonio import read_json, write_json

SAVE_EVERY = 600
VOICE_REPOS = {"omnivoice": "k2-fsa/OmniVoice", "voxcpm": "openbmb/VoxCPM2", "chatterbox": "ResembleAI/chatterbox"}

_path: Path | None = None
_data: dict = {"since": 0, "used": {}}
_lock = threading.Lock()


def configure(path: Path):
    global _path, _data
    _path = path
    _data = read_json(path, None) or {}
    _data.setdefault("used", {})
    if not _data.get("since"):
        _data["since"] = time.time()
        write_json(path, _data)


def mark(repo: str):
    if _path is None or not repo:
        return
    now = time.time()
    with _lock:
        if now - _data["used"].get(repo, 0) < SAVE_EVERY:
            return
        _data["used"][repo] = now
        try:
            write_json(_path, _data)
        except OSError:
            pass


def snapshot() -> dict:
    with _lock:
        return {"since": _data.get("since", 0), "used": dict(_data["used"])}
