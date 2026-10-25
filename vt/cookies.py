"""Sesión de YouTube para yt-dlp: importarla desde un navegador o desde un cookies.txt.

Solo se guardan las cookies de YouTube y Google (las que yt-dlp necesita), en
data/cookies.txt, formato Netscape. Nada sale del equipo.
"""

import http.cookiejar
import os
import time
from pathlib import Path

_LOCAL = os.environ.get("LOCALAPPDATA", "")
_ROAM = os.environ.get("APPDATA", "")
# navegador (nombre de yt-dlp) → (nombre visible, carpeta del perfil)
BROWSERS = {
    "brave": ("Brave", Path(_LOCAL, "BraveSoftware", "Brave-Browser", "User Data")),
    "chrome": ("Chrome", Path(_LOCAL, "Google", "Chrome", "User Data")),
    "edge": ("Edge", Path(_LOCAL, "Microsoft", "Edge", "User Data")),
    "firefox": ("Firefox", Path(_ROAM, "Mozilla", "Firefox", "Profiles")),
    "opera": ("Opera", Path(_ROAM, "Opera Software", "Opera Stable")),
    "vivaldi": ("Vivaldi", Path(_LOCAL, "Vivaldi", "User Data")),
    "chromium": ("Chromium", Path(_LOCAL, "Chromium", "User Data")),
}
CHROMIUM = {"brave", "chrome", "edge", "opera", "vivaldi", "chromium"}
_KEEP = ("youtube.com", "google.com")          # dominios que se conservan
_LOGIN = {"SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID"}  # señales de sesión iniciada


def detect() -> list[dict]:
    return [{"key": k, "name": name} for k, (name, path) in BROWSERS.items() if path.exists()]


def _keep(domain: str) -> bool:
    d = domain.lstrip(".").lower()
    return any(d == k or d.endswith("." + k) for k in _KEEP)


def _save(cookies, out: Path) -> dict:
    jar = http.cookiejar.MozillaCookieJar(str(out))
    n, names = 0, set()
    for c in cookies:
        if _keep(c.domain):
            jar.set_cookie(c)
            n += 1
            names.add(c.name)
    if not n:
        raise ValueError("no hay cookies de YouTube")
    tmp = out.with_suffix(".tmp")
    jar.filename = str(tmp)
    jar.save(ignore_discard=True, ignore_expires=True)
    tmp.replace(out)
    return {"count": n, "logged_in": bool(names & _LOGIN)}


def import_browser(key: str, out: Path) -> dict:
    """Lee las cookies de YouTube del navegador (una vez) y las guarda en `out`."""
    from yt_dlp.cookies import extract_cookies_from_browser

    if key not in BROWSERS:
        raise ValueError("navegador desconocido")
    jar = extract_cookies_from_browser(key)
    info = _save(jar, out)
    return {**info, "source": BROWSERS[key][0]}


def import_file(data: bytes, out: Path) -> dict:
    """Valida un cookies.txt (formato Netscape) y guarda solo lo de YouTube/Google."""
    text = data.decode("utf-8-sig", errors="replace")
    if "youtube.com" not in text:
        raise ValueError("el archivo no tiene cookies de youtube.com")
    tmp = out.with_suffix(".import")
    # MozillaCookieJar exige esta cabecera; algunas extensiones no la escriben
    if not text.lstrip().startswith("# Netscape HTTP Cookie File"):
        text = "# Netscape HTTP Cookie File\n" + text
    tmp.write_text(text, encoding="utf-8")
    try:
        jar = http.cookiejar.MozillaCookieJar(str(tmp))
        jar.load(ignore_discard=True, ignore_expires=True)
    except (http.cookiejar.LoadError, OSError) as e:
        raise ValueError(f"no es un cookies.txt válido ({e})")
    finally:
        tmp.unlink(missing_ok=True)
    return {**_save(jar, out), "source": "archivo"}


def status(out: Path) -> dict:
    if not out.exists():
        return {"present": False}
    jar = http.cookiejar.MozillaCookieJar(str(out))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (http.cookiejar.LoadError, OSError):
        return {"present": False}
    names = {c.name for c in jar}
    return {"present": True, "count": len(jar), "logged_in": bool(names & _LOGIN),
            "updated": time.strftime("%d/%m %H:%M", time.localtime(out.stat().st_mtime))}


def friendly(e: Exception, key: str) -> str:
    msg = str(e)
    name = BROWSERS.get(key, (key,))[0]
    if "Could not copy" in msg:
        return f"{name} tiene bloqueadas sus cookies mientras está abierto: ciérralo, importa, y vuelve a abrirlo."
    if "no hay cookies de YouTube" in msg:
        return (f"No se encontraron cookies de YouTube en {name}. Si iniciaste sesión ahí, puede que las "
                "cifre (versiones recientes): usa «Subir cookies.txt».")
    if "decrypt" in msg.lower() or "app-bound" in msg.lower():
        return f"{name} cifra sus cookies y no se pueden leer desde aquí: usa «Subir cookies.txt»."
    return msg[:300]
