"""La app de escritorio INSTALADA, como la abre la persona: la ventana, el servidor que lanza, la interfaz y la franja
de subtítulos en vivo. Solo lectura: usa la biblioteca y los ajustes reales de este equipo, así que no abre videos, no
cambia ajustes y no escribe nada; mira, recorre y cierra lo que abrió.

    python tests/e2e/run.py --installed

  · Antes: la app no debe estar abierta (es de instancia única; si lo está, la suite se salta y lo dice).
  · Abre %LOCALAPPDATA%/Translay/translay.exe y espera a que su servidor diga «Listo» en logs/server.log (la primera
    vez después de actualizar, la app instala lo nuevo del entorno de voz: hasta 15 min).
  · La ventana, por UI Automation (tests/e2e/uia.ps1): está visible, tiene imagen (no un cuadro liso) y sus botones.
    WebView2 no abre el puerto de depuración en la app publicada (Tauri le pasa sus propios argumentos y la variable
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS no corre), y no se abre uno para las pruebas: no se baja la seguridad de la app.
  · Subtítulos en vivo: un clic real en su botón de la barra de título abre la franja, que deja pasar los clics
    (WindowFromPoint en su centro da otra ventana); otro clic la cierra.
  · La misma página del mismo servidor, con Chrome: dueño en este equipo, inicio y cada página de Ajustes.
  · Falla por cualquier ERROR nuevo en logs/app.log (vt/diag.py), error de consola o pedido rechazado.
  · Al final cierra la app con todo lo que lanzó y deja el cursor donde estaba.
"""

import ctypes
import json
import os
import re
import subprocess
import time
from pathlib import Path

LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
EXE = LOCAL / "Translay" / "translay.exe"
LOGS = LOCAL / "dev.alejandro.translay" / "logs"
UIA = Path(__file__).with_name("uia.ps1")
PAGES = ["uso", "apariencia", "video", "audio", "agente", "biblioteca", "exportar", "glosario", "bibliotecas", "acceso",
         "rendimiento", "almacenamiento", "papelera"]  # «escritorio» solo existe dentro de la ventana de la app
user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def running() -> str:
    """La ruta del Translay abierto (la app es de instancia única: con otro abierto, el instalado no arranca), o «»."""
    return subprocess.run(["powershell", "-NoProfile", "-Command",
                           "(Get-Process translay -ErrorAction SilentlyContinue | Select-Object -First 1).Path"],
                          capture_output=True, text=True).stdout.strip()


def close_app():
    subprocess.run(["taskkill", "/T", "/F", "/IM", "translay.exe"], capture_output=True)


def uia(mode: str, pid: int, target: str = ""):
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(UIA), mode, str(pid), target],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    try:
        return json.loads(out or "null")
    except ValueError:
        return None


def root_at(x: int, y: int) -> int:
    """La ventana de primer nivel en ese punto de la pantalla (lo que recibiría un clic)."""
    h = user32.WindowFromPoint(POINT(x, y))
    return user32.GetAncestor(h, 2) or 0  # GA_ROOT


def real_click(t, pid: int, target: str, what: str):
    """Un clic de verdad en el centro de un elemento quieto y que está sobre su propia ventana (si no, no se hace)."""
    last = None
    for _ in range(20):
        e = uia("find", pid, target)
        if e and e["w"] > 0 and e == last:
            break
        last = e
        time.sleep(0.3)
    t.check(f"{what}: el botón está en la ventana", bool(last and last["w"] > 0), str(last))
    if not last:
        return False
    x, y = last["x"] + last["w"] // 2, last["y"] + last["h"] // 2
    owner = root_at(x, y)
    t.check(f"{what}: nada lo tapa", owner == last["main"], f"en ({x}, {y}) está la ventana {owner}, no {last['main']}")
    if owner != last["main"]:
        return False
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # botón izquierdo abajo
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # y arriba
    return True


def picture(x: int, y: int, w: int, h: int) -> float:
    """Cuánto varía la imagen de esa zona de la pantalla (0 = un cuadro liso)."""
    from PIL import ImageGrab, ImageStat

    im = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("L")
    return ImageStat.Stat(im).stddev[0]


def run(t):
    if not EXE.exists():
        t.check("la app está instalada", False, str(EXE))
        return
    other = running()
    if other:
        print(f"    INFO Translay está abierto ({other}): la suite de escritorio no lo toca (ciérralo para probarlo)", flush=True)
        t.skipped = True
        return
    log, slog = LOGS / "app.log", LOGS / "server.log"
    offset = log.stat().st_size if log.exists() else 0
    cursor = POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    t.cleanup(lambda: user32.SetCursorPos(cursor.x, cursor.y))
    t0 = time.time()
    proc = subprocess.Popen([str(EXE)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    t.cleanup(close_app)

    # el servidor: server.log se reescribe en cada arranque; «Listo: <url>» cuando está para usarse
    def ready():
        try:
            if slog.stat().st_mtime < t0 - 1:
                return None
            m = re.search(r"Listo: (http://127\.0\.0\.1:\d+)", slog.read_text(encoding="utf-8", errors="replace"))
            return m.group(1) if m else None
        except OSError:
            return None
    t.wait(lambda: ready() is not None, 900, "el servidor de la app listo")  # tras actualizar: el entorno de voz
    url = ready()
    print(f"    INFO la app abrió en {time.time() - t0:.0f} s · {url}", flush=True)
    pid = proc.pid

    # la ventana: visible, del tamaño de una app, con imagen y con sus botones
    def main_window():
        ws = uia("windows", pid) or []
        big = [w for w in ws if w["visible"] and w["h"] > 300]
        return big[0] if big else None
    t.wait(lambda: main_window() is not None, 60, "la ventana visible")
    t.wait(lambda: len(uia("names", pid) or []) >= 5, 60, "la página dentro de la ventana")
    win = main_window()
    names = uia("names", pid) or []
    t.check("la ventana tiene los botones de la app", len(names) >= 5, ", ".join(names[:12]))
    user32.SetForegroundWindow(win["hwnd"])
    time.sleep(0.6)
    var = picture(win["x"], win["y"], win["w"], win["h"])
    t.check("la ventana muestra la app (no un cuadro liso)", var > 8, f"variación {var:.1f}")

    # subtítulos en vivo: clic real en su botón; la franja aparece, deja pasar los clics; otro clic la cierra
    if real_click(t, pid, "live-btn", "subtítulos en vivo"):
        def strip():
            ws = uia("windows", pid) or []
            # la franja (128 px lógicos), no las ventanitas auxiliares de 16 px (instancia única, bandeja)
            low = [w for w in ws if w["visible"] and 60 <= w["h"] <= 300 and w["title"] == "Translay"]
            return low[0] if low else None
        t.wait(lambda: strip() is not None, 20, "la franja de subtítulos en vivo")
        s = strip()
        cx, cy = s["x"] + s["w"] // 2, s["y"] + s["h"] // 2
        t.check("la franja deja pasar los clics", root_at(cx, cy) != s["hwnd"], f"en su centro está {root_at(cx, cy)}")
        t.check("la franja no toma el foco", user32.GetForegroundWindow() != s["hwnd"])
        if real_click(t, pid, "live-btn", "ocultar los subtítulos"):
            t.wait(lambda: strip() is None, 20, "la franja se cierra")

    # la misma página, con Chrome sobre el mismo servidor: dueño local, inicio y cada página de Ajustes
    from types import SimpleNamespace

    from playwright.sync_api import sync_playwright

    from harness import CHROME

    pw = sync_playwright().start()
    t.cleanup(pw.stop)
    t.browser = pw.chromium.launch(executable_path=CHROME, headless=True)
    t.cleanup(t.browser.close)
    t.server = SimpleNamespace(url=url)
    page = t.page()
    t.check("dueño en este equipo", page.evaluate("state.access.owner === true && state.access.local === true"))
    for sec in PAGES:
        page.evaluate(f"openPrefs('{sec}')")
        t.wait(lambda: page.evaluate("document.querySelector('#prefs-body')?.dataset.sec") == sec, 8, f"Ajustes › {sec}")
        page.wait_for_timeout(150)
    t.check(f"las {len(PAGES)} páginas de Ajustes abren", True)
    page.evaluate("setView('library')")
    page.wait_for_timeout(500)
    t.check("sin aviso de permiso", not [x for x in t.toasts(page) if "No tienes permiso" in x])
    # el registro de la app de escritorio (TRANSLAY_LOG_DIR): sin errores nuevos
    if log.exists():
        with log.open("rb") as f:
            f.seek(offset)
            t.extra_errors = [x for x in f.read().decode("utf-8", errors="replace").splitlines() if " ERROR " in x]
    t.check("server.log en la carpeta de registros de la app", slog.exists())


if __name__ == "__main__":
    print(json.dumps({"exe": str(EXE), "logs": str(LOGS)}))
