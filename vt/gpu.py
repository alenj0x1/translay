"""Arranque de CUDA en Windows.

Los wheels `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` instalan las DLL dentro de
site-packages, pero ctranslate2 no las encuentra solo. Las registramos antes de
importar cualquier motor que las use.
"""

import glob
import os
import sys

_done = False


# CTranslate2 (Whisper y traductor) guarda memoria liberada para reusarla; en una GPU
# de 8 GB compartida con el modelo de voz se limita ese caché a 400 MB
# (crecimiento de bins, bin mínimo, bin máximo, bytes en caché).
os.environ.setdefault("CT2_CUDA_CACHING_ALLOCATOR_CONFIG", "4,3,12,419430400")


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
