"""Arranque de CUDA en Windows.

Los wheels `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` instalan las DLL dentro de
site-packages, pero ctranslate2 no las encuentra solo. Las registramos antes de
importar cualquier motor que las use.
"""

import glob
import os
import sys

_done = False


def enable_cuda_dlls() -> list[str]:
    global _done
    if _done or sys.platform != "win32":
        return []
    _done = True
    try:
        import nvidia  # paquete namespace de los wheels de NVIDIA
    except ImportError:
        return []
    added = []
    for root in list(nvidia.__path__):
        for d in glob.glob(os.path.join(root, "*", "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            added.append(d)
    return added
