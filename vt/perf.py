"""Rendimiento: el equipo, el perfil, los límites y cómo va ahora mismo.

Preferencias → Rendimiento (web/js/perf.js) pide `perf_get` y cambia con `perf_set`.
El perfil (vt/profiles.py) decide los modelos al arrancar: cambiarlo pide reiniciar el
servidor (`server_restart`); los límites de RAM y CPU se aplican al momento (vt/limits.py).

Alertas (lo que explica por qué algo va lento):
  · el equipo no alcanza para el perfil elegido (forzado / muy forzado)
  · un límite demasiado bajo, o más bajo que lo que pide el perfil
  · ahora mismo: frases de voz que tardan mucho más que lo normal (la GPU desborda a
    memoria compartida), poca RAM libre en el sistema, la GPU usada por otro programa
"""

import os
import statistics
import subprocess
import sys
import threading
import time

from . import hardware, limits, profiles

KEYS = {"perf_profile": "profile", "limit_vram_mb": "vram_mb", "limit_ram_mb": "ram_mb", "limit_threads": "threads"}


class Perf:
    def __init__(self, prefs, res=None, active: str = "", cli: dict | None = None, device: str = "cuda"):
        self.prefs = prefs
        self.res = res  # vt/resources.py: tiempos recientes de cada cálculo
        self.active = active  # perfil con que arrancó el servidor
        self.cli = cli or {}  # lo que se forzó por línea de comandos (gana sobre el perfil)
        self.device = device  # en CPU (por --device o sin CUDA), el perfil se evalúa como sin GPU
        self.started = time.time()
        self._hw = None
        self._hw_t = 0.0

    # ------------------------------------------------------------------ estado
    def hw(self) -> dict:
        if self._hw is None or time.time() - self._hw_t > 10:
            self._hw = hardware.detect()
            if self.device != "cuda":
                self._hw = dict(self._hw, gpu=None)
            self._hw_t = time.time()
        return self._hw

    def limits(self) -> dict:
        v = self.prefs.values
        return {k2: int(v.get(k1) or 0) or None for k1, k2 in KEYS.items() if k1 != "perf_profile"}

    def choice(self) -> str:
        return self.prefs.values.get("perf_profile", "auto")

    def wanted(self) -> str:
        """El perfil que se usaría al arrancar ahora."""
        return profiles.resolve(self.choice(), self.hw(), self.limits())

    # ------------------------------------------------------------------ en vivo
    def live(self) -> dict:
        now = time.time()
        recent = [x for x in (list(self.res.recent) if self.res else []) if now - x[2] < 600]
        tts = [d for p, d, _ in recent if p == "tts"]
        med = statistics.median(tts) if len(tts) >= 4 else None
        slow = [d for d in tts if med and d > max(6.0, med * 6)]
        g = self.hw().get("gpu")
        return {"tts_count": len(tts), "tts_p50": round(med, 2) if med else None,
                "tts_slow": len(slow), "tts_max": round(max(tts), 1) if tts else None,
                "vram_free_mb": g.get("vram_free_mb") if g else None,
                "ram_available_mb": (self.hw().get("ram") or {}).get("available_mb"),
                "state": self.res.state if self.res else None}

    def alerts(self, rows: list[dict], live: dict) -> list[dict]:
        out = []
        hw, lim = self.hw(), self.limits()
        eff = profiles.effective(hw, lim)
        act = next((r for r in rows if r["id"] == self.active), None)
        if not hw.get("gpu"):
            out.append({"level": "warn", "text": "No hay una GPU NVIDIA: Translay corre en la CPU, solo con subtítulos "
                        "(la voz en español tardaría decenas de minutos por minuto de video)."})
        if act and act["state"] in ("forzado", "muy-forzado"):
            out.append({"level": "bad" if act["state"] == "muy-forzado" else "warn",
                        "text": f"«{act['name']}» va {act['state_label'].lower()} en este equipo: procesa a "
                                f"{act['speed']}× el tiempo real, así que no alcanza para ver en vivo. Prueba con "
                                f"«{profiles.PROFILES[profiles.recommend(hw, lim)]['name']}»."})
        for n in (act or {}).get("notes", []):
            out.append({"level": "warn", "text": n})
        if (hw.get("gpu") or {}).get("unified"):
            out.append({"level": "info", "text": "Memoria unificada: la GPU usa la RAM del sistema (como en DGX Spark)."})
        if lim.get("vram_mb") and lim["vram_mb"] < 2048:
            out.append({"level": "warn", "text": "Con menos de 2 GB de VRAM solo entran los subtítulos ligeros."})
        if lim.get("ram_mb") and lim["ram_mb"] < 3072:
            out.append({"level": "bad", "text": "Con menos de 3 GB de RAM Translay va a pasar casi todo al disco: "
                                               "hasta los subtítulos van a ir muy lentos."})
        if lim.get("threads") == 1:
            out.append({"level": "warn", "text": "Con un solo hilo, preparar audio y descargar compiten con el reconocimiento."})
        if self.wanted() != self.active:
            out.append({"level": "info", "text": "Hay cambios de perfil que se aplican al reiniciar Translay.",
                        "action": "restart"})
        if live.get("tts_slow"):
            out.append({"level": "bad", "text": f"{live['tts_slow']} frases de voz tardaron mucho más de lo normal en los "
                        f"últimos minutos (hasta {live['tts_max']} s): la GPU se queda sin memoria y desborda a la "
                        "compartida. Un perfil más liviano o cerrar otros programas que usan la GPU lo arregla."})
        ram_av = live.get("ram_available_mb")
        if ram_av is not None and ram_av < 1024:
            out.append({"level": "warn", "text": f"El sistema tiene solo {ram_av} MB de RAM libres: Windows está usando el "
                        "disco y todo va más lento. Cerrar programas pesados ayuda."})
        if eff["gpu"] and live.get("vram_free_mb") is not None and live["vram_free_mb"] < 600 and self.res and \
                self.res.state == "reposo":
            out.append({"level": "warn", "text": "Otro programa está usando casi toda la VRAM: cuando Translay despierte "
                        "no va a tener lugar y va a ir muy forzado."})
        return out

    def public(self) -> dict:
        hw, lim = self.hw(), self.limits()
        rows = profiles.evaluate(hw, lim)
        live = self.live()
        return {"type": "perf", "hardware": hw, "effective": profiles.effective(hw, lim), "limits": lim,
                "choice": self.choice(), "active": self.active, "wanted": self.wanted(),
                "recommended": profiles.recommend(hw, lim), "profiles": rows, "live": live,
                "alerts": self.alerts(rows, live), "cli": self.cli, "uptime_s": round(time.time() - self.started)}

    # ------------------------------------------------------------------ cambios
    def set(self, m: dict) -> str | None:
        """Guarda perfil y límites; los límites rigen al momento. Devuelve un error, si hubo."""
        if "profile" in m:
            self.prefs.set("perf_profile", str(m["profile"]))
        for k1, k2 in KEYS.items():
            if k1 != "perf_profile" and k2 in m:
                self.prefs.set(k1, int(m[k2] or 0))
        lim = self.limits()
        err = limits.apply_self(lim.get("ram_mb"), lim.get("threads"))
        self._hw = None  # los hilos usables cambian con el límite
        return err

    def restart(self, before=None):
        """Reinicia el servidor con los mismos argumentos (el perfil nuevo carga sus modelos)."""
        def go():
            time.sleep(0.4)  # que llegue la respuesta a la página
            try:
                if before:
                    before()
            finally:
                cmd = [sys.executable] + sys.argv
                try:  # fuera del job de los límites: el nuevo pone los suyos (si no, se acumularían)
                    subprocess.Popen(cmd, cwd=os.getcwd(), creationflags=getattr(limits, "CREATE_BREAKAWAY_FROM_JOB", 0))
                except OSError:
                    subprocess.Popen(cmd, cwd=os.getcwd())
                os._exit(0)

        threading.Thread(target=go, daemon=True).start()
