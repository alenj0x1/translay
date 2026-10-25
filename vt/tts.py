"""Cliente del proceso de voz (TTS con clonación).

Lanza `vt/tts_worker.py` con el Python del entorno del motor elegido
(`.venvs/<motor>`) y le pide síntesis por tuberías. Thread-safe: una petición
a la vez (el motor usa la GPU).
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .ipc import read_msg, write_msg

ROOT = Path(__file__).resolve().parent.parent

ENGINES = ("chatterbox", "voxcpm", "omnivoice")


def venv_python(engine: str) -> Path:
    exe = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return ROOT / ".venvs" / engine / exe


class TTSClient:
    def __init__(self, engine: str = "chatterbox", device: str = "cuda", log=None):
        py = venv_python(engine)
        if not py.exists():
            raise FileNotFoundError(f"no existe el entorno del motor de voz: {py}")
        self.engine = engine
        self._lock = threading.Lock()
        self._log = log or (lambda s: print(s, file=sys.stderr, flush=True))
        env = dict(os.environ, TQDM_DISABLE="1", HF_HUB_DISABLE_SYMLINKS_WARNING="1",
                   PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            [str(py), "-u", str(ROOT / "vt" / "tts_worker.py"), "--engine", engine, "--device", device],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT), env=env,
        )
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        h, _ = read_msg(self.proc.stdout)  # espera a que el modelo cargue
        if not h.get("ok"):
            raise RuntimeError(f"el motor de voz no cargó: {h.get('error')}")
        self.sr = h["sr"]

    def _pump_stderr(self):
        for line in self.proc.stderr:
            s = line.decode("utf-8", "replace").rstrip()
            if s and "Warning" not in s and "warn(" not in s:
                self._log(f"[voz] {s}")

    def synth(self, text: str, ref: str | None = None, ref_text: str | None = None,
              lang: str = "es", **params) -> tuple[np.ndarray, int, float]:
        """Devuelve (audio float32, sr, segundos de GPU)."""
        with self._lock:
            t = time.perf_counter()
            write_msg(self.proc.stdin, {"op": "synth", "text": text, "ref": ref,
                                        "ref_text": ref_text, "lang": lang, "params": params})
            h, data = read_msg(self.proc.stdout)
            if not h.get("ok"):
                raise RuntimeError(h.get("error"))
            return np.frombuffer(data, np.float32).copy(), h["sr"], time.perf_counter() - t

    def close(self):
        try:
            write_msg(self.proc.stdin, {"op": "quit"})
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
