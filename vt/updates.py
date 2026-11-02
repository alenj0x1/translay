"""¿Hay una versión nueva de Translay? La busca en la última versión publicada en GitHub.

Solo avisa: la descarga la abre el navegador y el instalador lo ejecuta la persona. La app no
baja ni ejecuta nada por su cuenta (un programa que descarga y ejecuta otro es lo que Windows
Defender confunde con un troyano).

  check() → {"available", "current", "version", "notes", "url", "download"} (consulta cacheada 1 h)
"""

import json
import re
import threading
import time
import urllib.request

from . import __version__

API = "https://api.github.com/repos/alenj0x1/translay/releases/latest"
RELEASES = "https://github.com/alenj0x1/translay/releases/"
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def _parse(v: str) -> tuple:
    """1.7.0 → (1, 7, 0, 1); 1.7.0-beta.1 → (1, 7, 0, 0, …): una preliminar va antes que la final."""
    main, _, pre = v.lstrip("v").partition("-")
    nums = tuple(int(x) for x in re.findall(r"\d+", main)[:3])
    return nums + ((1,) if not pre else (0, pre))


def newer(remote: str, current: str = __version__) -> bool:
    try:
        return _parse(remote) > _parse(current)
    except ValueError:
        return False


def spanish_notes(body: str) -> str:
    """Las notas traen inglés y, debajo de «### Español», español: la app muestra el español."""
    part = body.split("### Español", 1)
    return (part[1] if len(part) > 1 else body).strip()


def check(force: bool = False) -> dict:
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["at"] < 3600:
            return _cache["data"]
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"Translay/{__version__}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        rel = json.load(r)
    version = str(rel.get("tag_name", "")).lstrip("v")
    url = str(rel.get("html_url", ""))
    installer = next((a["browser_download_url"] for a in rel.get("assets", [])
                      if str(a.get("name", "")).endswith("_x64-setup.exe")), url)
    if not url.startswith(RELEASES) or not str(installer).startswith(RELEASES):
        raise ValueError("respuesta inesperada de GitHub")
    data = {"available": newer(version), "current": __version__, "version": version,
            "notes": spanish_notes(str(rel.get("body", ""))), "url": url, "download": installer}
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data
