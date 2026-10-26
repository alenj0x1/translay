"""JSON en disco sin quedar a medias: se escribe aparte y se reemplaza de una vez.

write_json guarda primero en un temporal único (dos hilos no se pisan) y deja la versión
anterior como <archivo>.bak; read_json, si el archivo está dañado (un corte de luz a mitad
de algo que no pasó por aquí), usa esa copia.
"""

import json
import os
import shutil
import threading
import uuid
from pathlib import Path

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(path: Path) -> threading.Lock:
    with _guard:
        return _locks.setdefault(str(path), threading.Lock())


def _dumps(data, indent):
    for i in range(3):  # otro hilo puede estar cambiando los datos mientras se serializan
        try:
            return json.dumps(data, ensure_ascii=False, indent=indent)
        except RuntimeError:
            if i == 2:
                raise


def write_json(path: Path, data, indent: int | None = 1):
    with _lock(path):
        text = _dumps(data, indent)
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(text, encoding="utf-8")
        if path.exists():  # la versión anterior queda de respaldo (el archivo nunca falta)
            bak = path.with_name(path.name + ".bak")
            try:
                bak.unlink(missing_ok=True)
                os.link(path, bak)
            except OSError:
                try:
                    shutil.copyfile(path, bak)
                except OSError:
                    pass
        os.replace(tmp, path)


def read_json(path: Path, default=None):
    for f in (path, path.with_name(path.name + ".bak")):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return default
