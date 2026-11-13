"""Cuenta de YouTube conectada: un perfil de navegador propio de Translay.

La persona inicia sesión una vez en una ventana de su navegador (Brave, Chrome, Edge,
Vivaldi o Chromium) abierta con un perfil aparte, en data/yt-session/profile, y la
cierra. Translay
nunca toca su perfil personal: Chrome 136+ solo deja manejar perfiles que no son el
predeterminado, y cada perfil tiene su propia clave de cifrado.

Translay habla con el navegador por un canal privado entre los dos procesos
(--remote-debugging-pipe con --remote-debugging-io-pipes), no por un puerto de red, y
solo le pide las cookies (Storage.getCookies): nunca ejecuta código en las páginas ni
lee su contenido. De lo que devuelve se guarda solo lo de youtube.com, cifrado con
DPAPI (solo lo descifra este usuario de Windows), y se pasa a yt-dlp en memoria, sin
cookies.txt en texto plano. No se guarda el correo, el nombre ni nada de la cuenta.

Renovar abre el mismo perfil sin ventana, carga YouTube (eso hace que Google renueve
la sesión) y vuelve a leer las cookies. Desconectar cierra la sesión en Google (las
cookies copiadas dejan de servir) y borra el perfil.
"""

import http.cookiejar
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_PF = os.environ.get("ProgramFiles", r"C:\Program Files")
_PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
_LOCAL = os.environ.get("LOCALAPPDATA", "")
# navegador → (nombre visible, rutas posibles del ejecutable, ProgId de «navegador predeterminado»)
BROWSERS = {
    "brave": ("Brave", [Path(b, "BraveSoftware", "Brave-Browser", "Application", "brave.exe") for b in (_PF, _PF86, _LOCAL)],
              "BraveHTML"),
    "chrome": ("Chrome", [Path(b, "Google", "Chrome", "Application", "chrome.exe") for b in (_PF, _PF86, _LOCAL)],
               "ChromeHTML"),
    "edge": ("Edge", [Path(b, "Microsoft", "Edge", "Application", "msedge.exe") for b in (_PF86, _PF)], "MSEdgeHTM"),
    "vivaldi": ("Vivaldi", [Path(b, "Vivaldi", "Application", "vivaldi.exe") for b in (_LOCAL, _PF)], "VivaldiHTM"),
    "chromium": ("Chromium", [Path(_LOCAL, "Chromium", "Application", "chrome.exe")], "ChromiumHTM"),
}
LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
LOGOUT_URL = "https://accounts.google.com/Logout?continue=https%3A%2F%2Fwww.youtube.com%2F"
_LOGIN = {"SID", "__Secure-1PSID", "__Secure-3PSID"}  # sesión iniciada (en .youtube.com)
LOGIN_TIMEOUT_S = 10 * 60
RENEW_AFTER_S = 7 * 24 * 3600    # antes de descargar, si la última renovación es más vieja
RENEW_GAP_S = 10 * 60             # tras una verificación de YouTube, no renovar más seguido que esto
# lo que el perfil no necesita guardar (solo hacen falta las cookies)
_SCRUB = ("History", "History-journal", "Visited Links", "Top Sites", "Top Sites-journal", "Favicons",
          "Favicons-journal", "Shortcuts", "Shortcuts-journal", "Web Data", "Web Data-journal", "Cache",
          "Code Cache", "GPUCache", "Service Worker", "Session Storage", "Sessions", "Login Data",
          "Login Data-journal", "Login Data For Account", "Login Data For Account-journal", "Account Web Data",
          "Account Web Data-journal", "Local Storage", "IndexedDB", "DIPS", "MediaDeviceSalts",
          "MediaDeviceSalts-journal")


class Cancelled(Exception):
    """La persona cerró la ventana sin iniciar sesión."""


def available() -> bool:
    return sys.platform == "win32"


def _exe(key: str) -> Path | None:
    return next((p for p in BROWSERS[key][1] if p.exists()), None) if key in BROWSERS else None


def _default_key() -> str | None:
    if not available():
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations"
                            r"\UrlAssociations\https\UserChoice") as k:
            prog = winreg.QueryValueEx(k, "ProgId")[0]
    except OSError:
        return None
    return next((k for k, (_, _, p) in BROWSERS.items() if prog.startswith(p)), None)


def detect() -> list[dict]:
    """Navegadores compatibles instalados; el predeterminado, primero."""
    if not available():
        return []
    found = [k for k in BROWSERS if _exe(k)]
    d = _default_key()
    if d in found:
        found.remove(d)
        found.insert(0, d)
    return [{"key": k, "name": BROWSERS[k][0], "default": k == d} for k in found]


# ---------------------------------------------------------------- DPAPI
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(dst)):  # 0x1: sin preguntar nada
        raise OSError("DPAPI no pudo " + ("cifrar" if protect else "descifrar"))
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


# ---------------------------------------------------------------- canal con el navegador
class _Browser:
    """Un navegador abierto con el perfil de Translay y un canal privado de órdenes."""

    def __init__(self, exe: Path, profile: Path, url: str, headless: bool):
        import msvcrt

        r_in, w_in = os.pipe()     # Translay escribe → el navegador lee
        r_out, w_out = os.pipe()   # el navegador escribe → Translay lee
        h_read, h_write = msvcrt.get_osfhandle(r_in), msvcrt.get_osfhandle(w_out)
        os.set_handle_inheritable(h_read, True)
        os.set_handle_inheritable(h_write, True)
        si = subprocess.STARTUPINFO()
        si.lpAttributeList = {"handle_list": [h_read, h_write]}  # solo estos dos, nada más se hereda
        args = [str(exe), f"--user-data-dir={profile}", "--remote-debugging-pipe",
                f"--remote-debugging-io-pipes={h_read},{h_write}", "--no-first-run",
                "--no-default-browser-check", "--disable-sync", "--disable-background-networking",
                *(["--headless=new"] if headless else ["--new-window"]), url]
        self.proc = subprocess.Popen(args, startupinfo=si, close_fds=True)
        os.close(r_in)
        os.close(w_out)
        self._w = os.fdopen(w_in, "wb", buffering=0)
        self._r = r_out
        self._q: queue.Queue = queue.Queue()
        self._id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        try:
            while chunk := os.read(self._r, 65536):
                buf += chunk
                while b"\0" in buf:
                    msg, buf = buf.split(b"\0", 1)
                    self._q.put(json.loads(msg))
        except (OSError, ValueError):
            pass
        finally:
            try:
                os.close(self._r)
            except OSError:
                pass
        self._q.put(None)

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 20):
        self._id += 1
        i = self._id
        msg = {"id": i, "method": method, "params": params or {}, **({"sessionId": session} if session else {})}
        try:
            self._w.write(json.dumps(msg).encode() + b"\0")
        except OSError:
            raise Cancelled()
        end = time.time() + timeout
        while True:
            try:
                m = self._q.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                raise TimeoutError(f"el navegador no respondió a {method}")
            if m is None:
                raise Cancelled()
            if m.get("id") == i:
                if "error" in m:
                    raise RuntimeError(m["error"].get("message", method))
                return m.get("result", {})

    def cookies(self) -> list[dict]:
        return self.call("Storage.getCookies").get("cookies", [])

    def open(self, url: str, user_agent: str = "") -> None:
        """Una pestaña sin ventana con `url`; con el navegador real como agente (no «HeadlessChrome»)."""
        tid = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        if user_agent:
            self.call("Network.setUserAgentOverride", {"userAgent": user_agent}, session=sid)
        self.call("Page.navigate", {"url": url}, session=sid)

    def close(self):
        try:
            self.call("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        try:
            self._w.close()
        except OSError:
            pass


def _profile_in_use(profile: Path) -> bool:
    """¿Hay un navegador abierto con este perfil? Mientras corre, Chromium tiene su
    archivo «lockfile» abierto sin compartir y no se puede borrar."""
    lock = profile / "lockfile"
    if not lock.exists():
        return False
    try:
        lock.unlink()
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _cookie(c: dict) -> http.cookiejar.Cookie:
    dom = c["domain"]
    exp = None if c.get("session") or c.get("expires", -1) < 0 else int(c["expires"])
    return http.cookiejar.Cookie(0, c["name"], c["value"], None, False, dom, True, dom.startswith("."),
                                 c.get("path", "/"), True, bool(c.get("secure")), exp, exp is None, None, None,
                                 {"HttpOnly": ""} if c.get("httpOnly") else {})


def _youtube(c: dict) -> bool:
    d = c.get("domain", "").lstrip(".").lower()
    return d == "youtube.com" or d.endswith(".youtube.com")


def _logged_in(cookies: list[dict]) -> bool:
    return any(_youtube(c) and c["name"] in _LOGIN for c in cookies)


# ---------------------------------------------------------------- la sesión
class Session:
    def __init__(self, data: Path):
        self.dir = data / "yt-session"
        self.profile = self.dir / "profile"
        self.store = self.dir / "cookies.bin"
        self.meta_path = self.dir / "session.json"
        self._lock = threading.Lock()
        self.busy: str | None = None      # "conectando" · "renovando" · "desconectando"
        self._jar: list | None = None     # cookies descifradas en memoria
        self._last_try = 0.0

    # --- estado
    def meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def connected(self) -> bool:
        return self.store.exists() and bool(self.meta().get("browser"))

    def status(self) -> dict:
        m = self.meta()
        return {"available": available(), "connected": self.connected(), "browser": m.get("browser"),
                "browser_name": BROWSERS.get(m.get("browser"), (m.get("browser"),))[0],
                "renewed": m.get("renewed"), "expired": bool(m.get("expired")), "busy": self.busy,
                "browsers": detect()}

    def _write_meta(self, **kw):
        m = {**self.meta(), **kw}
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(m), encoding="utf-8")
        tmp.replace(self.meta_path)

    def _save(self, cookies: list[dict]) -> int:
        keep = [c for c in cookies if _youtube(c)]
        blob = _dpapi(json.dumps(keep).encode(), True)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(self.store)
        self._jar = keep
        return len(keep)

    def jar(self) -> list[http.cookiejar.Cookie]:
        """Las cookies para yt-dlp (en memoria; nunca un archivo en texto plano).
        Si no se pueden leer (otro usuario de Windows, archivo dañado), la descarga
        falla con un mensaje claro en vez de seguir sin sesión."""
        if self._jar is None:
            try:
                self._jar = json.loads(_dpapi(self.store.read_bytes(), False))
            except (OSError, ValueError):
                raise ValueError("No se pudo leer la cuenta de YouTube guardada: vuelve a conectarla en "
                                 "Ajustes → YouTube.") from None
        return [_cookie(c) for c in self._jar]

    def _scrub(self):
        """Del perfil solo hacen falta las cookies: historial, caché y demás se borran."""
        base = self.profile / "Default"
        for name in _SCRUB:
            p = base / name
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)

    def _prepare_profile(self):
        """Perfil nuevo sin sincronización, sin cuenta del navegador y sin guardar contraseñas."""
        prefs = self.profile / "Default" / "Preferences"
        if prefs.exists():
            return
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(json.dumps({
            "credentials_enable_service": False, "credentials_enable_autosignin": False,
            "profile": {"password_manager_enabled": False}, "signin": {"allowed": False},
            "autofill": {"profile_enabled": False, "credit_card_enabled": False},
            "browser": {"has_seen_welcome_page": True}}), encoding="utf-8")

    # --- acciones (bloquean: corren en un hilo)
    def connect(self, key: str, on_change=None) -> dict:
        """Abre la ventana para iniciar sesión y, cuando la persona la cierra, lee la sesión.

        La ventana es el navegador tal cual, sin el canal de órdenes: Google rechaza
        iniciar sesión en un navegador controlado («This browser or app may not be
        secure»). El canal se usa después, ya sin ventana, solo para leer las cookies."""
        exe = _exe(key)
        if not available() or not exe:
            raise ValueError("ese navegador no está instalado")
        if not self._lock.acquire(blocking=False):
            raise ValueError("ya hay una conexión en curso")
        try:
            self.busy = "conectando"
            on_change and on_change()
            self.dir.mkdir(parents=True, exist_ok=True)
            self._prepare_profile()
            t0 = time.time()
            win = subprocess.Popen([str(exe), f"--user-data-dir={self.profile}", "--no-first-run",
                                    "--no-default-browser-check", "--disable-sync", "--new-window", LOGIN_URL])
            try:
                win.wait(timeout=LOGIN_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                win.kill()
                raise TimeoutError("pasaron 10 minutos sin cerrar la ventana")
            # algunos ejecutables relanzan el navegador y salen enseguida: la ventana sigue
            # abierta mientras el perfil esté en uso
            while _profile_in_use(self.profile):
                if time.time() - t0 > LOGIN_TIMEOUT_S:
                    raise TimeoutError("pasaron 10 minutos sin cerrar la ventana")
                time.sleep(1)
            if time.time() - t0 < 4:  # se cerró al arrancar (p. ej. Edge con una actualización a medias)
                raise ValueError(f"{BROWSERS[key][0]} no se pudo abrir: prueba con otro navegador")
            b = _Browser(exe, self.profile, "about:blank", headless=True)
            try:
                ua = b.call("Browser.getVersion").get("userAgent", "").replace("HeadlessChrome", "Chrome")
                cookies = b.cookies()
            finally:
                b.close()
            self._scrub()
            if not _logged_in(cookies):
                raise Cancelled()
            n = self._save(cookies)
            now = time.time()
            self._write_meta(browser=key, ua=ua, connected=now, renewed=now, expired=False)
            return {"count": n}
        finally:
            self.busy = None
            self._lock.release()
            on_change and on_change()

    def renew(self, on_change=None) -> bool:
        """Abre el perfil sin ventana, carga YouTube y guarda las cookies renovadas.
        True solo si quedaron cookies nuevas con la sesión iniciada; si la sesión se
        cerró, queda marcada como vencida (hay que volver a conectar)."""
        m = self.meta()
        exe = _exe(m.get("browser", ""))
        if not self.connected() or not exe:
            return False
        if time.time() - self._last_try < RENEW_GAP_S:
            return False
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._last_try = time.time()
            self.busy = "renovando"
            on_change and on_change()
            try:
                b = _Browser(exe, self.profile, "about:blank", headless=True)
                try:
                    b.open("https://www.youtube.com/", m.get("ua", "").replace("HeadlessChrome", "Chrome"))
                    time.sleep(8)
                    cookies = b.cookies()
                finally:
                    b.close()
            except Exception as e:  # sin navegador o sin red: se siguen usando las que hay
                print(f"[youtube] no se pudo renovar la sesión: {e}", flush=True)
                return False
            self._scrub()
            if not _logged_in(cookies):
                self._write_meta(expired=True)
                return False
            self._save(cookies)
            self._write_meta(renewed=time.time(), expired=False)
            return True
        finally:
            self.busy = None
            self._lock.release()
            on_change and on_change()

    def mark_stale(self) -> None:
        """YouTube dio las cookies por vencidas: la próxima descarga renueva antes."""
        if self.connected():
            self._write_meta(renewed=0)

    def ensure_fresh(self, on_change=None) -> None:
        """Antes de descargar: renueva si pasó más de una semana. Si la sesión ya se
        cerró en Google, no se insiste: hace falta volver a conectar."""
        m = self.meta()
        if self.connected() and not m.get("expired") and time.time() - (m.get("renewed") or 0) > RENEW_AFTER_S:
            self.renew(on_change)

    def disconnect(self, on_change=None) -> None:
        """Cierra la sesión en Google (las cookies copiadas dejan de servir) y borra todo."""
        if not self._lock.acquire(timeout=30):  # conectando: la ventana sigue abierta
            raise ValueError("Primero cierra la ventana de inicio de sesión.")
        try:
            self.busy = "desconectando"
            on_change and on_change()
            try:
                exe = _exe(self.meta().get("browser", ""))
                if exe and self.profile.exists():
                    try:
                        b = _Browser(exe, self.profile, "about:blank", headless=True)
                        try:
                            b.open(LOGOUT_URL, self.meta().get("ua", "").replace("HeadlessChrome", "Chrome"))
                            time.sleep(5)
                        finally:
                            b.close()
                    except Exception as e:  # sin red o sin navegador: igual se borra lo local
                        print(f"[youtube] no se pudo cerrar la sesión en Google: {e}", flush=True)
                shutil.rmtree(self.dir, ignore_errors=True)
                self._jar = None
            finally:
                self.busy = None
        finally:
            self._lock.release()
        on_change and on_change()


_sessions: dict[Path, Session] = {}


def get(data: Path) -> Session:
    """Una sola sesión por carpeta de datos (la comparten la cola, el servidor y cada biblioteca)."""
    data = Path(data).resolve()
    if data not in _sessions:
        _sessions[data] = Session(data)
    return _sessions[data]
