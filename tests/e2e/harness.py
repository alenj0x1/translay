"""Lo común de las pruebas de punta a punta: el servidor de prueba, los navegadores (dueño e invitado) y los
chequeos que miran lo que ve la persona.

Una suite es un módulo de tests/e2e/suites/ con `run(t)`. `t` (Run) da:

  t.page(who="dueño"|"invitado", path="/", mobile=False, dark=False)  página nueva, ya vigilada
  t.check(nombre, condición, detalle="")    un chequeo (falla la suite al final, sigue con el resto)
  t.expect_error(texto)                     un ERROR del registro que esta suite provoca a propósito
  t.expect_console(texto) / t.expect_http(url)  lo mismo para la consola y los pedidos rechazados
  t.wait(fn, segundos, qué)                 espera una condición con plazo (nunca un sleep a ciegas)
  t.toasts(page)                            los avisos visibles
  t.cleanup(fn)                             algo que se deshace al terminar la suite, falle o no

Lo que falla una suite sin que la suite lo pida (app-diagnostics):
  · cada línea « ERROR » nueva en app.log mientras corrió;
  · cada error de consola de sus páginas y cada pedido con respuesta 400 o más (visto por CDP, también los
    que hace el navegador por su cuenta, como /favicon.ico);
  · cada aviso de permiso («No tienes permiso…»).
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
MARK = "translay-e2e"  # en la línea de comandos de lo que lanza la corrida (para barrer restos)
GUEST = {"X-Forwarded-For": "203.0.113.9"}  # pasa por un «proxy»: el servidor lo trata como de otro equipo
PERMISSION_TOAST = "No tienes permiso"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sweep(marker: str = MARK):
    """Termina, con su árbol, los Chrome y servidores de una corrida anterior (nunca esta ni sus padres)."""
    ps = ("$all = Get-CimInstance Win32_Process; $skip = @(); $p = %d; "
          "while ($p) { $skip += $p; $p = ($all | Where-Object ProcessId -eq $p).ParentProcessId; if ($skip -contains $p) { break } }; "
          "$all | Where-Object { $_.CommandLine -like '*%s*' -and ($_.Name -eq 'chrome.exe' -or $_.CommandLine -like '*run.py*') "
          "-and $_.CommandLine -notlike '*tests*e2e*run.py*' -and $skip -notcontains $_.ProcessId } | ForEach-Object { $_.ProcessId }"
          ) % (os.getpid(), marker)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    for pid in out.split():
        subprocess.run(["taskkill", "/T", "/F", "/PID", pid], capture_output=True)


class Server:
    """Translay sobre la carpeta de datos de prueba: CPU, sin voz (las suites miran la interfaz y los permisos)."""

    def __init__(self, data: Path, log: Path):
        self.data, self.log, self.port, self.p = data, log, free_port(), None
        self.report_dir = log.parent / "informes"  # «Guardar informe» escribe aquí, no en Descargas

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    @property
    def app_log(self) -> Path:
        return self.data / "logs" / "app.log"

    def start(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
        env.pop("TRANSLAY_LOG_DIR", None)
        # el informe va a la carpeta de la corrida (sin abrir el Explorador) y el registro anota cada error, también
        # el que se repite enseguida (un reintento tiene que volver a verlo)
        env.update(TRANSLAY_REPORT_DIR=str(self.report_dir), TRANSLAY_LOG_ALL="1")
        f = self.log.open("a", encoding="utf-8")
        self.p = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "--no-browser", "--port", str(self.port), "--data-dir",
                                   str(self.data), "--device", "cpu", "--voice", "none", f"--allow-origin=http://{MARK}.invalid"],
                                  cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 180:  # el primer arranque prepara modelos de reconocimiento en la CPU
            if self.p.poll() is not None:
                raise RuntimeError(f"el servidor de prueba se cerró al arrancar (ver {self.log})")
            try:
                urllib.request.urlopen(self.url + "/", timeout=2).read(64)
                return time.time() - t0
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("el servidor de prueba no respondió en 3 minutos")

    def stop(self):
        if self.p and self.p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.p.pid)], capture_output=True)
            self.p.wait(15)

    def log_size(self) -> int:
        return self.app_log.stat().st_size if self.app_log.exists() else 0

    def errors_since(self, offset: int) -> list[str]:
        if not self.app_log.exists():
            return []
        with self.app_log.open("rb") as f:
            f.seek(offset)
            text = f.read().decode("utf-8", errors="replace")
        return [line for line in text.splitlines() if " ERROR " in line]


class SuiteFailed(Exception):
    pass


class Run:
    def __init__(self, name: str, server: Server, browser, shots: Path):
        self.name, self.server, self.browser, self.shots = name, server, browser, shots
        self.checks: list[tuple[str, bool, str]] = []
        self.expected_errors: list[str] = []
        self.expected_console: list[str] = []
        self.expected_http: list[str] = []
        self.console: list[str] = []
        self.http: list[str] = []
        self.contexts = []
        self.undo = []

    # ---------------------------------------------------------------- páginas
    def page(self, who: str = "dueño", path: str = "/", mobile: bool = False, dark: bool = False, wait_ready: bool = True):
        opts = {"viewport": {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
                "color_scheme": "dark" if dark else "light", "locale": "es-419"}
        if mobile:
            opts.update(is_mobile=True, has_touch=True, device_scale_factor=2)
        if who == "invitado":
            opts["extra_http_headers"] = GUEST
        ctx = self.browser.new_context(**opts)
        self.contexts.append(ctx)
        page = ctx.new_page()
        tag = f"{who}{' celular' if mobile else ''}{' oscuro' if dark else ''}"
        page.on("console", lambda m: self.console.append(f"{tag}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: self.console.append(f"{tag}: {e}"))
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.on("Network.responseReceived",
               lambda e: self.http.append(f"{tag}: {e['response']['status']} {e['response']['url']}")
               if e["response"]["status"] >= 400 else None)
        page.goto(self.server.url + path)
        if wait_ready:
            self.wait(lambda: page.evaluate("typeof state !== 'undefined' && !!state.ws && state.ws.readyState === 1 && !!state.access"), 20,
                      f"la página conectada ({tag} {path})")
            page.wait_for_timeout(600)  # los primeros mensajes (biblioteca, preferencias) se dibujan
        return page

    # ---------------------------------------------------------------- chequeos
    def check(self, name: str, ok, detail: str = ""):
        ok = bool(ok)
        self.checks.append((name, ok, detail))
        print(f"    {'ok ' if ok else 'FAIL'} {name}" + (f" · {detail}" if detail and not ok else ""), flush=True)
        return ok

    def wait(self, fn, seconds: float, what: str):
        t0 = time.time()
        last = None
        while time.time() - t0 < seconds:
            try:
                if fn():
                    return time.time() - t0
            except Exception as e:  # noqa: BLE001  la página se está rearmando: no esta vez
                last = e
            time.sleep(0.15)
        raise SuiteFailed(f"no pasó en {seconds:.0f} s: {what}" + (f" ({last})" if last else ""))

    def toasts(self, page) -> list[str]:
        return page.evaluate("[...document.querySelectorAll('.toast')].map(x => x.textContent.trim()).filter(Boolean)")

    def no_permission_toast(self, page, where: str):
        bad = [x for x in self.toasts(page) if PERMISSION_TOAST in x]
        return self.check(f"sin aviso de permiso ({where})", not bad, "; ".join(bad))

    def expect_error(self, text: str):
        self.expected_errors.append(text)

    def expect_console(self, text: str):
        self.expected_console.append(text)

    def expect_http(self, text: str):
        self.expected_http.append(text)

    def cleanup(self, fn):
        self.undo.append(fn)

    def screenshot(self, page, label: str) -> Path:
        self.shots.mkdir(parents=True, exist_ok=True)
        p = self.shots / f"{self.name}-{re.sub(r'[^a-z0-9]+', '-', label.lower())[:40]}.png"
        try:
            page.screenshot(path=str(p))
        except Exception:  # noqa: BLE001
            pass
        return p

    def close(self):
        for fn in reversed(self.undo):
            try:
                fn()
            except Exception as e:  # noqa: BLE001  deshacer lo más posible
                print(f"    INFO no se pudo deshacer algo: {e}", flush=True)
        for ctx in self.contexts:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

    def unexpected(self, errors: list[str]) -> dict:
        keep = lambda items, allowed: [x for x in items if not any(a in x for a in allowed)]  # noqa: E731
        return {"registro": keep(errors, self.expected_errors), "consola": keep(self.console, self.expected_console),
                "http": keep(self.http, self.expected_http)}


def git_state() -> dict:
    def g(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": g("rev-parse", "HEAD"), "dirty": bool(g("status", "--porcelain", "--untracked-files=no"))}


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
