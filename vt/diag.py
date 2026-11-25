"""Registro de errores e informe de diagnóstico.

Cada error deja una línea en app.log, con hora y contexto:

  2026-11-25 10:42:07 ERROR sesion.lib_register: sin permiso (invitado, biblioteca publica)

Fuentes: excepciones de los trabajos de fondo (exception()), errores no atrapados de hilos y del bucle
de asyncio, pedidos que el servidor rechaza por permisos, y los errores de la interfaz (la página los
manda por el WebSocket: errores de JavaScript y acciones que intentó sin permiso). Nunca se registran
contraseñas ni tokens: la carpeta del usuario queda como «~» y los secretos de las direcciones (token=, key=,
la última parte de un webhook) como «***». El contexto solo admite letras, números y «._-» (nadie puede
escribir líneas falsas), y lo que llega de las páginas tiene un tope por minuto (un invitado no puede llenar
el disco ni empujar fuera los errores reales).

Las pruebas de punta a punta (tests/e2e/run.py) leen este archivo y fallan una suite si apareció un ERROR
que no esperaban. El informe (report()) junta versión, sistema, perfil y las últimas líneas de cada registro
en un archivo de texto que la persona puede enviar; nada se manda solo.

El registro va en TRANSLAY_LOG_DIR (la app de escritorio pasa su carpeta logs/, junto a server.log) o en
<datos>/logs. Se recorta a MAX_BYTES (queda la mitad más nueva).
"""

import os
import platform
import re
import sys
import threading
import time
import traceback
from pathlib import Path

MAX_BYTES = 2 << 20
PAGE_PER_MIN = 60  # líneas por minuto que pueden venir de las páginas (interfaz.*, permiso.*)
# las pruebas e2e lo apagan: un error repetido en el reintento de una suite tiene que volver a verse
DEDUP_S = 0 if os.environ.get("TRANSLAY_LOG_ALL") else 10
_SECRET = re.compile(r"((?:token|key|secret|password|pw|sig|vt_s)=)[^&\s\"';]+|(/webhooks?/[^/\s]+/)[^/\s\"']+"
                     r"|(/services/[^/\s]+/[^/\s]+/)[^/\s\"']+|((?:Bearer|Basic) )\S+|()\bvt_[A-Za-z0-9_-]{20,}", re.I)
# la carpeta de cualquier usuario de Windows, con barras simples, dobles (repr de una ruta) o de URL
_USERS = re.compile(r"[A-Za-z]:(?:\\{1,2}|/|%5C)+Users(?:\\{1,2}|/|%5C)+[^\\/'\"\s%]+", re.I)
_page_minute = [0.0, 0]  # [inicio del minuto, líneas]
_lock = threading.Lock()
_path: Path | None = None
_recent: dict[str, float] = {}  # el mismo error repetido en ráfaga se anota una vez cada 10 s


def setup(data_dir: Path) -> Path:
    """Elige el archivo y engancha los errores no atrapados (hilos, asyncio se engancha en hook_loop)."""
    global _path
    folder = Path(os.environ.get("TRANSLAY_LOG_DIR") or (Path(data_dir) / "logs"))
    folder.mkdir(parents=True, exist_ok=True)
    _path = folder / "app.log"
    prev_thread = threading.excepthook

    def on_thread(args):
        if args.exc_type is not SystemExit:
            error(f"hilo.{args.thread.name if args.thread else '?'}", _summary(args.exc_type, args.exc_value))
        prev_thread(args)

    threading.excepthook = on_thread
    prev_sys = sys.excepthook

    def on_sys(t, v, tb):
        error("servidor", _summary(t, v))
        prev_sys(t, v, tb)

    sys.excepthook = on_sys
    return _path


def hook_loop(loop):
    """Errores de tareas de asyncio que nadie esperó."""
    def handler(lp, ctx):
        exc = ctx.get("exception")
        if isinstance(exc, ConnectionError):  # un navegador que se cerró o cortó: normal, no es un error de la app
            return
        error("asyncio", _summary(type(exc), exc) if exc else str(ctx.get("message", "?"))[:300])
        lp.default_exception_handler(ctx)

    loop.set_exception_handler(handler)


def path() -> Path | None:
    return _path


def _summary(t, v) -> str:
    return f"{getattr(t, '__name__', t)}: {v}".strip()[:500]


def _short_home() -> str:
    """La forma corta 8.3 de la carpeta del usuario (C:\\Users\\ALEJAN~1), que aparece en las rutas temporales."""
    if sys.platform != "win32":
        return ""
    import ctypes

    buf = ctypes.create_unicode_buffer(512)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(Path.home()), buf, len(buf))
    return buf.value if 0 < n < len(buf) else ""


_NAMES = [x for x in {Path.home().name, Path(_short_home()).name if _short_home() else ""} if len(x) >= 3]


def scrub(text: str) -> str:
    """Sin la carpeta ni el nombre del usuario y sin secretos (tokens, claves, cookies, webhooks)."""
    text = _USERS.sub("~", text)
    for name in _NAMES:  # el nombre suelto (en un mensaje, en minúsculas…)
        text = re.sub(re.escape(name), "~", text, flags=re.I)
    return _SECRET.sub(lambda m: next((g for g in m.groups() if g is not None), "") + "***", text)


def error(context: str, message: str):
    """Una línea ERROR. Contexto corto (módulo.qué, solo letras, números y «._-»), mensaje en una línea."""
    context = "".join(ch for ch in str(context)[:60] if ch.isalnum() or ch in "._-") or "?"
    message = scrub(" ".join(str(message).split()))[:500]
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR {context}: {message}"
    key = f"{context}|{message}"[:300]
    now = time.time()
    with _lock:
        if now - _recent.get(key, 0) < DEDUP_S:
            return
        if context.startswith(("interfaz.", "permiso.")):  # lo que llega de las páginas tiene tope
            if now - _page_minute[0] > 60:
                _page_minute[:] = [now, 0]
            _page_minute[1] += 1
            if _page_minute[1] > PAGE_PER_MIN:
                return
        _recent[key] = now
        if len(_recent) > 500:
            _recent.clear()
        print(line, flush=True)
        if _path is None:
            return
        try:
            if _path.exists() and _path.stat().st_size > MAX_BYTES:
                keep = _path.read_bytes()[-MAX_BYTES // 2:]
                _path.write_bytes(keep[keep.find(b"\n") + 1:])
            with _path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def exception(context: str):
    """Dentro de un except: imprime el traceback (como antes) y deja la línea ERROR con la última línea."""
    traceback.print_exc()
    t, v, _ = sys.exc_info()
    error(context, _summary(t, v))


def _tail(p: Path, n: int) -> str:
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return f"(no se pudo leer: {e})"
    return "\n".join(lines[-n:]) if lines else "(vacío)"


def windows_build() -> str:
    if sys.platform != "win32":
        return platform.platform()
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            name = winreg.QueryValueEx(k, "ProductName")[0]
            build = winreg.QueryValueEx(k, "CurrentBuild")[0]
            ubr = winreg.QueryValueEx(k, "UBR")[0]
            disp = winreg.QueryValueEx(k, "DisplayVersion")[0]
        return f"{name} {disp} (compilación {build}.{ubr})"
    except OSError:
        return platform.platform()


def report(info: dict, lines: int = 300) -> str:
    """El informe en texto: versión, sistema, lo que pasa la app (info) y las últimas líneas de cada registro, con la
    carpeta del usuario y los secretos tapados (scrub). La persona lo lee antes de enviarlo."""
    from . import __version__

    head = [f"Informe de diagnóstico de Translay · {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Versión: {__version__}", f"Sistema: {windows_build()}", f"Python: {platform.python_version()}"]
    head += [f"{k}: {scrub(str(v))}" for k, v in info.items()]
    parts = ["\n".join(head)]
    folder = _path.parent if _path else None
    logs = sorted(folder.glob("*.log")) if folder and folder.exists() else []
    for p in logs:
        parts.append(f"===== {p.name} (últimas {lines} líneas)\n{scrub(_tail(p, lines))}")
    if not logs:
        parts.append("===== (sin registros)")
    return "\n\n".join(parts) + "\n"
