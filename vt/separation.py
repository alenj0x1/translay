"""Fondo sin la voz original: separa el audio de cada video doblado en diálogo y fondo (música + efectos), para que la
voz doblada suene sobre el fondo entero en vez de sobre el original bajado (donde se seguía oyendo el inglés).

Cuándo: al terminar de procesarse un video que se dobla (Processor.on_done), si «Fondo sin la voz original» está
activado (Ajustes › Audio y subtítulos) y el equipo tiene el motor de voz (el entorno con torch). Uno a la vez, en un
hilo propio, en la GPU si hay (0,08 del tiempo real, 575 MB) o en la CPU con la mitad de los hilos.

Qué deja: <biblioteca>/audio/<video>/fondo.m4a (AAC estéreo) y el campo `bg` del video en la biblioteca
(/audio/<video>/fondo.m4a). El reproductor lo hace sonar sincronizado con el video y silencia el original mientras
hay doblaje (web/js/dubaudio.js); la exportación lo usa en lugar del original bajado (vt/exporter.py).

El modelo (CDX23, MIT, 54 MB) se descarga la primera vez desde su versión publicada en GitHub y se verifica con su
SHA-256 antes de usarlo; el proceso (vt/separate_worker.py) lo lee en el modo seguro de torch.
"""

import hashlib
import json
import queue
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import diag
from .tts import venv_python

MODEL_URL = "https://github.com/ZFTurbo/MVSEP-CDX23-Cinematic-Sound-Demixing/releases/download/v.1.0.0/97d170e1-dbb4db15.th"
MODEL_NAME = "97d170e1-dbb4db15.th"
MODEL_SHA256 = "dbb4db154df7e45a5cb72d1659c48937e757f6d6b0eef8ca4199e6e38f8d8f37"
ENGINE = "omnivoice"  # el entorno del motor de voz trae torch (y demucs, desktop/locks/voice.txt)
WORKER = Path(__file__).with_name("separate_worker.py")


def bg_url(vid: str) -> str:
    return f"/audio/{vid}/fondo.m4a"


class Separator:
    def __init__(self, data: Path, vaults, prefs, notify, media_of, library):
        self.models = data / "models" / "separation"
        self.vaults, self.prefs, self.notify, self.media_of, self.library = vaults, prefs, notify, media_of, library
        self.q: "queue.Queue[str]" = queue.Queue()
        self.pending: set[str] = set()
        self.current: str | None = None
        self._ok: bool | None = None
        threading.Thread(target=self._loop, name="separacion", daemon=True).start()

    # ------------------------------------------------------------ cuándo
    def available(self) -> bool:
        """¿Hay entorno de voz con demucs? (se averigua una vez)"""
        if self._ok is None:
            py = venv_python(ENGINE)
            try:
                self._ok = py.exists() and subprocess.run([str(py), "-c", "import demucs"], capture_output=True,
                                                          timeout=60).returncode == 0
            except (OSError, subprocess.SubprocessError):
                self._ok = False
        return self._ok

    def wanted(self, vid: str) -> bool:
        v = self.library.data["videos"].get(vid) or {}
        vault = self.vaults.of(vid)
        if not self.prefs.values.get("bg_separate", True) or v.get("mode") == "transcribe" or not vault:
            return False
        return not (vault.root / "audio" / vid / "fondo.m4a").exists()

    def request(self, vid: str):
        """Un video terminó (o se abrió sin fondo): a la cola de separación si hace falta."""
        if vid in self.pending or not self.wanted(vid) or not self.available():
            return
        self.pending.add(vid)
        self.q.put(vid)

    # ------------------------------------------------------------ trabajo
    def weights(self) -> Path:
        f = self.models / MODEL_NAME
        if f.exists() and _sha256(f) == MODEL_SHA256:
            return f
        self.models.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        with urllib.request.urlopen(MODEL_URL, timeout=60) as r, tmp.open("wb") as out:
            while chunk := r.read(1 << 20):
                out.write(chunk)
        if _sha256(tmp) != MODEL_SHA256:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("el modelo de separación descargado no coincide con su huella")
        tmp.replace(f)
        return f

    def _loop(self):
        while True:
            vid = self.q.get()
            self.current = vid
            try:
                if self.wanted(vid):
                    self.separate(vid)
            except Exception as e:  # noqa: BLE001  un video que falla no frena a los demás
                diag.error("separacion", f"{vid}: {e}")
            finally:
                self.pending.discard(vid)
                self.current = None

    def separate(self, vid: str):
        vault = self.vaults.of(vid)
        src = self.media_of(vid)
        if not vault or not src or not Path(src).exists():
            return
        folder = vault.root / "audio" / vid
        folder.mkdir(parents=True, exist_ok=True)
        wav, out = folder / "fondo.tmp.wav", folder / "fondo.m4a"
        dur = float((self.library.data["videos"].get(vid) or {}).get("duration") or 3600)
        cmd = [str(venv_python(ENGINE)), "-u", str(WORKER), "--weights", str(self.weights()), "--input", str(src),
               "--out", str(wav)]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=600 + dur * 3)
            if p.returncode != 0:
                raise RuntimeError((p.stderr or p.stdout).strip()[-300:])
            last = json.loads([x for x in p.stdout.splitlines() if x.startswith("{")][-1])
            tmp_out = out.with_suffix(".tmp.m4a")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", "-movflags",
                            "+faststart", str(tmp_out)], check=True, capture_output=True, timeout=600)
            tmp_out.replace(out)
        finally:
            wav.unlink(missing_ok=True)
        self.library.set_field(vid, bg=bg_url(vid))
        print(f"[separacion] {vid}: fondo listo en {time.time() - t0:.0f} s ({last.get('device')})", flush=True)
        self.notify({"type": "library_changed"})


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()
