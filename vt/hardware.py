"""Qué equipo tiene Translay para trabajar: GPU, VRAM, RAM y CPU.

Sin dependencias nuevas: en Windows usa la API del sistema (ctypes) y `nvidia-smi`
(viene con el driver de NVIDIA); en Linux, /proc y los límites del contenedor
(cgroups, p. ej. en Docker). Lo que el sistema le da a este proceso cuenta más
que lo que tiene la máquina: afinidad de CPU, tope de memoria del contenedor o
del Job Object de Windows.

TRANSLAY_EMULATE (JSON) reemplaza lo detectado por el equipo de un lab
(tools/lab), p. ej. {"vram_mb": 4096, "ram_mb": 8192, "threads": 6} o
{"gpu": false}; así las recomendaciones se prueban como en ese equipo.

Memoria unificada (NVIDIA DGX Spark / GB10 y similares): la GPU no tiene VRAM
propia, usa la RAM del sistema, y `nvidia-smi` informa la memoria como «[N/A]».
Si además el modo de direccionamiento es ATS o HMM, la GPU se marca `unified` y
su memoria es la RAM que este proceso puede usar. TRANSLAY_UNIFIED_MEMORY=1 o 0
fuerza la detección en un sentido u otro.

    python -m vt.hardware          # lo detectado, en JSON
"""

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time

_cache: dict = {"t": 0.0, "gpu": None}


# ------------------------------------------------------------------ GPU
def _nvidia_smi() -> list[dict]:
    """GPUs NVIDIA según el driver (nombre, memoria en MB, driver, capacidad de cómputo)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    q = "name,memory.total,memory.used,memory.free,driver_version,compute_cap,utilization.gpu"
    try:
        out = subprocess.run([exe, f"--query-gpu={q}", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus = []
    for i, line in enumerate(x for x in out.splitlines() if x.strip()):
        f = [x.strip() for x in line.split(",")]
        if len(f) < 7:
            continue
        num = lambda s: int(float(s)) if s.replace(".", "", 1).isdigit() else None  # noqa: E731
        gpus.append({"index": i, "name": f[0], "vram_total_mb": num(f[1]), "vram_used_mb": num(f[2]),
                     "vram_free_mb": num(f[3]), "driver": f[4], "compute_cap": f[5], "util": num(f[6])})
    return gpus


_modes: dict[int, str | None] = {}


def _addressing_mode(index: int) -> str | None:
    """Modo de direccionamiento de la GPU («ATS», «HMM» o «None»), consultado aparte: un driver
    viejo que no conoce el campo no puede romper la consulta principal. No cambia: se pregunta una vez."""
    if index not in _modes:
        exe = shutil.which("nvidia-smi")
        mode = None
        if exe:
            try:
                out = subprocess.run([exe, "-i", str(index), "--query-gpu=addressing_mode", "--format=csv,noheader"],
                                     capture_output=True, text=True, timeout=8,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                mode = out.stdout.strip() if out.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                mode = None
        _modes[index] = mode or None
    return _modes[index]


def unified_memory(g: dict | None) -> bool:
    """La GPU comparte la RAM del sistema (sin VRAM propia que informar)."""
    if not g:
        return False
    forced = os.environ.get("TRANSLAY_UNIFIED_MEMORY", "").strip()
    if forced in ("0", "1"):
        return forced == "1"
    return g.get("vram_total_mb") is None and _addressing_mode(g.get("index", 0)) in ("ATS", "HMM")


def gpus(max_age: float = 5.0) -> list[dict]:
    """Las GPUs (con caché corta: nvidia-smi tarda ~0.2 s)."""
    if _cache["gpu"] is None or time.time() - _cache["t"] > max_age:
        _cache["gpu"] = _nvidia_smi()
        _cache["t"] = time.time()
    return _cache["gpu"]


def cuda_usable() -> bool:
    """CTranslate2 puede usar CUDA (driver y bibliotecas presentes)."""
    try:
        from . import gpu  # noqa: F401  (registra las DLL de CUDA en Windows)
        gpu.enable_cuda_dlls()
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# ------------------------------------------------------------------ RAM
def _ram_windows() -> dict:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"total_mb": m.ullTotalPhys >> 20, "available_mb": m.ullAvailPhys >> 20, "limit_mb": _job_limit_mb()}


def _job_limit_mb() -> int | None:
    """Tope de memoria del Job Object de Windows en que corre este proceso (labs, límites)."""
    try:
        k32 = ctypes.windll.kernel32

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", ctypes.c_ulong), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_ulong),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_ulong),
                        ("SchedulingClass", ctypes.c_ulong)]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXT()
        # NULL = el job del proceso actual (JobObjectExtendedLimitInformation = 9)
        if not k32.QueryInformationJobObject(None, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            return None
        flags = info.Basic.LimitFlags
        if flags & 0x200:  # JOB_OBJECT_LIMIT_JOB_MEMORY
            return info.JobMemoryLimit >> 20
        if flags & 0x100:  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
            return info.ProcessMemoryLimit >> 20
    except Exception:
        pass
    return None


def _ram_linux() -> dict:
    vals = {}
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            k, v = line.split(":", 1)
            vals[k] = int(v.split()[0]) >> 10  # kB → MB
    except OSError:
        pass
    limit = None
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = open(path, encoding="utf-8").read().strip()
            if raw.isdigit() and int(raw) < (1 << 60):
                limit = int(raw) >> 20
                break
        except OSError:
            continue
    return {"total_mb": vals.get("MemTotal"), "available_mb": vals.get("MemAvailable"), "limit_mb": limit}


def ram() -> dict:
    return _ram_windows() if sys.platform == "win32" else _ram_linux()


# ------------------------------------------------------------------ CPU
def _physical_cores_windows() -> int | None:
    try:
        k32 = ctypes.windll.kernel32
        size = ctypes.c_ulong(0)
        k32.GetLogicalProcessorInformation(None, ctypes.byref(size))
        buf = (ctypes.c_byte * size.value)()
        if not k32.GetLogicalProcessorInformation(buf, ctypes.byref(size)):
            return None
        entry = 32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24  # SYSTEM_LOGICAL_PROCESSOR_INFORMATION
        rel_off = ctypes.sizeof(ctypes.c_void_p)
        raw = bytes(buf)
        return sum(1 for i in range(0, size.value, entry)
                   if int.from_bytes(raw[i + rel_off:i + rel_off + 4], "little") == 0)  # RelationProcessorCore
    except Exception:
        return None


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "CPU"


def _usable_threads() -> int:
    """Hilos que este proceso puede usar (afinidad de los labs y de los límites)."""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    if sys.platform == "win32":  # (os.process_cpu_count no mira la afinidad en Windows)
        try:
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t),
                                                   ctypes.POINTER(ctypes.c_size_t)]
            proc, sysm = ctypes.c_size_t(), ctypes.c_size_t()
            if k32.GetProcessAffinityMask(k32.GetCurrentProcess(), ctypes.byref(proc), ctypes.byref(sysm)):
                return bin(proc.value).count("1")
        except Exception:
            pass
    return os.cpu_count() or 1


def cpu() -> dict:
    threads = os.cpu_count() or 1
    cores = _physical_cores_windows() if sys.platform == "win32" else None
    if cores is None and sys.platform != "win32":
        try:
            ids = {line for line in open("/proc/cpuinfo", encoding="utf-8") if line.startswith("core id")}
            cores = len(ids) or None
        except OSError:
            cores = None
    return {"name": _cpu_name(), "threads": threads, "cores": cores or threads, "usable_threads": _usable_threads()}


# ------------------------------------------------------------------ todo junto
def detect() -> dict:
    """El equipo como lo ve Translay. «gpu» es None si no hay GPU NVIDIA usable."""
    g = gpus()
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "gpu": dict(g[0], cuda=True) if g else None,
        "gpus": len(g),
        "ram": ram(),
        "cpu": cpu(),
        "emulated": None,
    }
    if unified_memory(info["gpu"]):
        # la memoria de la GPU es la RAM que este proceso puede usar (tope del contenedor incluido)
        r = info["ram"]
        total = r.get("limit_mb") or r.get("total_mb")
        free = r.get("available_mb")
        if total and free is not None:
            free = min(free, total)
        info["gpu"] = dict(info["gpu"], unified=True,
                           vram_total_mb=info["gpu"].get("vram_total_mb") or total,
                           vram_free_mb=info["gpu"].get("vram_free_mb") if info["gpu"].get("vram_total_mb") else free,
                           vram_used_mb=info["gpu"].get("vram_used_mb") if info["gpu"].get("vram_total_mb")
                           else (total - free if total and free is not None else None))
    lab = os.environ.get("TRANSLAY_EMULATE")
    if lab:
        try:
            e = json.loads(lab)
        except ValueError:
            e = {}
        info["emulated"] = e
        if e.get("gpu") is False:
            info["gpu"] = None
        elif info["gpu"] and e.get("vram_mb"):
            # la GPU del lab: su VRAM total; lo libre sale de nvidia-smi (el lastre ya ocupa el resto)
            info["gpu"] = dict(info["gpu"], name=e.get("gpu_name", info["gpu"]["name"]), vram_total_mb=int(e["vram_mb"]))
        if e.get("ram_mb"):
            info["ram"] = dict(info["ram"], total_mb=int(e["ram_mb"]), limit_mb=int(e["ram_mb"]))
        if e.get("threads"):
            info["cpu"] = dict(info["cpu"], threads=int(e["threads"]), usable_threads=int(e["threads"]),
                               cores=max(1, int(e["threads"]) // 2))
    return info


if __name__ == "__main__":
    print(json.dumps(detect(), indent=2, ensure_ascii=False))
