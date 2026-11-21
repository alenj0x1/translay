"""Cuadros del sistema para elegir carpeta o dónde guardar, y mostrar un archivo en su carpeta (en este equipo)."""

import threading
from pathlib import Path

from . import i18n

_has_dialogs: list[bool] = []  # ¿hay cuadros del sistema en este equipo? (se averigua una vez)
_dialog_lock = threading.Lock()


def reveal(path: Path):
    """Abre el Explorador (o el gestor de archivos) con el archivo marcado."""
    import subprocess
    import sys

    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def _dialog(ask):
    """Un cuadro nativo de tkinter delante del navegador (el servidor corre en este mismo equipo).
    "" si se canceló o no hay pantalla (Docker, servidor remoto)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return ""
    with _dialog_lock:  # dos pestañas a la vez: Tk no es seguro entre hilos
        try:
            root = tk.Tk()
        except Exception:
            return ""
        root.withdraw()
        root.attributes("-topmost", True)  # delante del navegador
        try:
            return ask(root, filedialog) or ""
        finally:
            root.destroy()


def _dialog_available() -> bool:
    """¿Hay cuadros nativos? (no en Docker ni en un servidor sin pantalla)"""
    if not _has_dialogs:
        _has_dialogs.append(_dialog(lambda root, fd: "1") == "1")
    return _has_dialogs[0]


def _start_dir(initial: str = "") -> str:
    d = Path(initial) if initial else Path.home() / "Downloads"
    return str(d) if d.is_dir() else str(Path.home())


def pick_folder(title: str = "", initial: str = "") -> str:
    """Cuadro nativo para elegir una carpeta."""
    title = title or i18n.t("Carpeta de la biblioteca")
    return _dialog(lambda root, filedialog: filedialog.askdirectory(parent=root, title=title, mustexist=False,
                                                        initialdir=_start_dir(initial)))


def pick_save(filename: str, initial: str = "", title: str = "") -> str:
    """Cuadro nativo «Guardar como» con el nombre propuesto; pregunta antes de reemplazar."""
    title = title or i18n.t("Guardar como")
    ext = Path(filename).suffix
    types = [(f"{ext[1:].upper()}", f"*{ext}")] if ext else []
    return _dialog(lambda root, filedialog: filedialog.asksaveasfilename(
        parent=root, title=title, initialdir=_start_dir(initial), initialfile=filename,
        defaultextension=ext, filetypes=types + [(i18n.t("Todos los archivos"), "*.*")]))
