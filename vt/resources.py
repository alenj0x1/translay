"""Modo reposo: los modelos ocupan la GPU solo mientras se procesa un video.

Cada uso de un modelo pasa por `Resources.use(...)`: si estaba dormido se
despierta (carga) y queda marcado como ocupado. Un hilo vigila la inactividad:

  sin uso por `idle_s`  →  Whisper y el traductor pasan a la RAM (vuelven en
                           ~1 s) y el modelo de voz también (~1 s).
  sin uso por `deep_s`  →  (2 min) se cierra el proceso de voz: en la GPU queda solo
                           el contexto mínimo del servidor (~110 MB).

Medido en RTX 4060: Whisper + traductor 2.7 GB → 0.1 GB en reposo; voz
2.1 GB → 0.85 GB (RAM) → 0 GB (proceso cerrado).
"""

import threading
import time
from contextlib import contextmanager


class Resources:
    def __init__(self, asr, translator, tts=None, idle_s: float = 45, deep_s: float = 120, on_change=None):
        self.asr = asr
        self.translator = translator
        self.tts = tts
        self.idle_s = idle_s
        self.deep_s = deep_s
        self.on_change = on_change or (lambda state: None)
        self._lock = threading.RLock()
        self._busy = 0
        self._last = time.monotonic()
        self.state = "reposo"  # reposo | cargando | activo
        self._loaded = {"asr": False, "mt": False, "tts": False}
        self._part_locks = {p: threading.Lock() for p in self._loaded}
        threading.Thread(target=self._watch, daemon=True).start()

    # ------------------------------------------------------------------ uso
    @contextmanager
    def use(self, *parts: str):
        """`with res.use("asr"):` garantiza el modelo cargado durante el bloque."""
        with self._lock:
            self._busy += 1
            self._last = time.monotonic()
        try:
            self._wake(parts)
            yield
        finally:
            with self._lock:
                self._busy -= 1
                self._last = time.monotonic()

    def run(self, parts: tuple, fn, *args):
        """Ejecuta `fn(*args)` con esos modelos cargados (para run_in_executor)."""
        with self.use(*parts):
            return fn(*args)

    def info(self) -> dict:
        return {"state": self.state, "busy": self._busy, "idle_s": round(time.monotonic() - self._last, 1),
                "loaded": dict(self._loaded)}

    def touch(self):
        """Actividad sin modelo (p. ej. audio llegando): posterga el reposo."""
        self._last = time.monotonic()

    def _wake(self, parts):
        # un candado por modelo: cargar la voz (~20 s la primera vez) no frena a Whisper
        for p in parts:
            with self._part_locks[p]:
                if self._loaded[p]:
                    continue
                self._set("cargando")
                if p == "asr":
                    self.asr.load()
                elif p == "mt":
                    self.translator.load()
                elif p == "tts" and self.tts:
                    self.tts.onload()
                self._loaded[p] = True
        if all(self._loaded[p] for p in parts):
            self._set("activo")

    # ---------------------------------------------------------------- reposo
    def sleep(self, deep: bool = False):
        for lk in self._part_locks.values():
            lk.acquire()
        try:
            with self._lock:
                if self._busy:
                    return
            if self._loaded["asr"]:
                self.asr.unload()
            if self._loaded["mt"]:
                self.translator.unload()
            if self.tts and (self._loaded["tts"] or deep):
                self.tts.offload(deep=deep)
            self._loaded = {"asr": False, "mt": False, "tts": False}
            self._set("reposo")
        finally:
            for lk in self._part_locks.values():
                lk.release()

    def _watch(self):
        deep_done = True
        while True:
            time.sleep(2)
            idle = time.monotonic() - self._last
            if self._busy:
                deep_done = False
                continue
            if any(self._loaded.values()) and idle > self.idle_s:
                self.sleep()
            if not deep_done and idle > self.deep_s:
                self.sleep(deep=True)
                deep_done = True

    def _set(self, state: str):
        if state != self.state:
            print(f"[recursos] {self.state} → {state}", flush=True)
            self.state = state
            try:
                self.on_change(state)
            except Exception:
                pass
