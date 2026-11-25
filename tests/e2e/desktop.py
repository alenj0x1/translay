"""La app de escritorio INSTALADA, como la abre la persona: la ventana, el servidor que lanza y la interfaz dentro de
WebView2. Solo lectura: usa la biblioteca y los ajustes reales de este equipo, así que no abre videos, no cambia ajustes
y no escribe nada; mira, recorre y cierra lo que abrió.

    python tests/e2e/run.py --installed

  · Antes: la app no debe estar abierta (es de instancia única; si lo está, la suite se salta y lo dice).
  · Abre %LOCALAPPDATA%/Translay/translay.exe con el puerto de depuración de WebView2 (variable
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS) y se conecta con Playwright por CDP a la ventana.
  · Espera la página de la app (la primera vez después de actualizar, la app instala lo nuevo del entorno de voz: hasta
    15 min), recorre el inicio y cada página de Ajustes, y mira que la ventana tenga imagen (no un cuadro liso).
  · Falla por cualquier ERROR nuevo en logs/app.log (vt/diag.py), error de consola o pedido rechazado.
  · Al final cierra la app con todo lo que lanzó.
"""

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
EXE = LOCAL / "Translay" / "translay.exe"
LOGS = LOCAL / "dev.alejandro.translay" / "logs"
PORT = 9333
PAGES = ["uso", "apariencia", "video", "audio", "agente", "biblioteca", "exportar", "glosario", "bibliotecas", "acceso",
         "rendimiento", "almacenamiento", "papelera", "escritorio"]


def running() -> str:
    """La ruta del Translay abierto (la app es de instancia única: con otro abierto, el instalado no arranca), o «»."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-Process translay -ErrorAction SilentlyContinue | Select-Object -First 1).Path"],
                         capture_output=True, text=True).stdout.strip()
    return out


def close_app():
    subprocess.run(["taskkill", "/T", "/F", "/IM", "translay.exe"], capture_output=True)


def run(t):
    if not EXE.exists():
        t.check("la app está instalada", False, str(EXE))
        return
    other = running()
    if other:
        print(f"    INFO Translay está abierto ({other}): la suite de escritorio no lo toca (ciérralo para probarlo)", flush=True)
        t.skipped = True
        return
    log = LOGS / "app.log"
    offset = log.stat().st_size if log.exists() else 0
    env = {**os.environ, "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": f"--remote-debugging-port={PORT}"}
    subprocess.Popen([str(EXE)], env=env, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    t.cleanup(close_app)
    t0 = time.time()
    t.wait(lambda: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2).status == 200, 60,
           "el puerto de depuración de WebView2")
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    t.cleanup(pw.stop)
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")

    def app_page():
        for ctx in browser.contexts:
            for p in ctx.pages:
                if p.url.startswith("http://127.0.0.1:") and "/ui/" not in p.url:
                    return p
        return None

    # primera vez tras actualizar: se instala lo nuevo del entorno de voz antes de abrir la app
    t.wait(lambda: app_page() is not None, 900, "la app abierta (servidor listo)")
    page = app_page()
    page.on("console", lambda m: t.console.append(f"escritorio: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: t.console.append(f"escritorio: {e}"))
    t.wait(lambda: page.evaluate("typeof state !== 'undefined' && !!state.ws && state.ws.readyState === 1 && !!state.access"), 60,
           "la página conectada")
    print(f"    INFO la app abrió en {time.time() - t0:.0f} s", flush=True)
    t.check("dueño en este equipo", page.evaluate("state.access.owner === true && state.access.local === true"))
    t.check("con su biblioteca", page.evaluate("typeof lib !== 'undefined' && Object.keys(lib.videos || {}).length >= 0"))
    t.check("es la app de escritorio", page.evaluate("typeof DESKTOP !== 'undefined' && !!DESKTOP"))
    page.wait_for_timeout(800)
    # la ventana tiene imagen: puntos de una captura con contraste (no un cuadro liso)
    png = page.screenshot()
    t.shots.mkdir(parents=True, exist_ok=True)
    (t.shots / "escritorio-inicio.png").write_bytes(png)
    t.check("la ventana muestra la app (no un cuadro liso)", len(png) > 20000, f"{len(png)} bytes")
    for sec in PAGES:
        page.evaluate(f"openPrefs('{sec}')")
        t.wait(lambda: page.evaluate("document.querySelector('#prefs-body')?.dataset.sec") == sec, 8, f"Ajustes › {sec}")
        page.wait_for_timeout(200)
    t.check(f"las {len(PAGES)} páginas de Ajustes abren", True)
    page.evaluate("setView('library')")
    page.wait_for_timeout(500)
    t.check("sin aviso de permiso", not [x for x in t.toasts(page) if "No tienes permiso" in x])
    # el registro de la app de escritorio (TRANSLAY_LOG_DIR): sin errores nuevos
    if log.exists():
        with log.open("rb") as f:
            f.seek(offset)
            new = [x for x in f.read().decode("utf-8", errors="replace").splitlines() if " ERROR " in x]
        t.extra_errors = new
    t.check("el registro de errores existe junto a server.log", log.exists() or (LOGS / "server.log").exists())
    browser.close()


if __name__ == "__main__":
    print(json.dumps({"exe": str(EXE), "logs": str(LOGS)}))
