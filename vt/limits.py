"""Límites reales para un proceso y sus hijos: los que elige la persona (Preferencias →
Rendimiento) y los de los labs (tools/lab).

Windows: un Job Object (el mismo mecanismo que usa el sistema para contenedores):
  RAM    "paging": tope duro de memoria residente por proceso (SetProcessWorkingSetSizeEx,
                   no pide permisos de administrador), repartido entre los procesos del job:
                   lo que no entra se pagina, como en un equipo con poca RAM física.
         "hard":   tope de memoria comprometida — al pasarlo, las reservas fallan.
  CPU    afinidad a N hilos lógicos y, opcional, un % máximo de uso (tope duro).
Los hijos (el proceso de voz) heredan el job: el tope vale para todo Translay.

    job = Job(ram_mb=6144, ram_mode="paging", threads=4, cpu_pct=None)
    p = subprocess.Popen(...); job.add(p); …; job.peak_mb()

    apply_self(ram_mb, threads)   el servidor de Translay entra en su propio job (la voz lo hereda)
"""

import ctypes
import sys
import threading
from ctypes import wintypes

JOB_OBJECT_LIMIT_WORKINGSET = 0x1
JOB_OBJECT_LIMIT_AFFINITY = 0x10
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
ExtendedLimitInformation = 9
CpuRateControlInformation = 15


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _EXT(ctypes.Structure):
    _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _CPU(ctypes.Structure):
    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


class Job:
    def __init__(self, ram_mb: int | None = None, ram_mode: str = "paging", threads: int | None = None,
                 cpu_pct: int | None = None, kill_on_close: bool = True):
        if sys.platform != "win32":
            raise RuntimeError("los límites con Job Object son de Windows (en Linux: cgroups / docker --memory --cpus)")
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.CreateJobObjectW.restype = wintypes.HANDLE
        self.k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.c_void_p]
        self.handle = self.k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _EXT()
        # cerrar el lab cierra todo lo que lanzó (el del servidor no: al reiniciarse, su reemplazo sigue vivo)
        self.kill = kill_on_close
        # el servidor deja salir a su reemplazo al reiniciarse (si no, heredaría estos límites para siempre)
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE if kill_on_close else JOB_OBJECT_LIMIT_BREAKAWAY_OK
        self.ws_mb = None
        self.threads = threads
        if ram_mb:
            if ram_mode == "hard":
                flags |= JOB_OBJECT_LIMIT_JOB_MEMORY
                info.JobMemoryLimit = ram_mb << 20
            else:  # el tope del job pide administrador: se pone proceso por proceso
                self.ws_mb = ram_mb
        if threads:
            flags |= JOB_OBJECT_LIMIT_AFFINITY
            info.Basic.Affinity = (1 << threads) - 1  # los primeros N hilos lógicos
        info.Basic.LimitFlags = flags
        if not self.k32.SetInformationJobObject(self.handle, ExtendedLimitInformation, ctypes.byref(info),
                                                ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if cpu_pct:
            c = _CPU(ControlFlags=0x1 | 0x4, CpuRate=int(cpu_pct * 100))  # ENABLE | HARD_CAP; 1/100 de %
            if not self.k32.SetInformationJobObject(self.handle, CpuRateControlInformation, ctypes.byref(c),
                                                    ctypes.sizeof(c)):
                raise ctypes.WinError(ctypes.get_last_error())

    def add(self, proc=None):
        """Mete un subprocess.Popen (o este mismo proceso, sin argumento) y lo que lance después."""
        if proc is None:
            self.k32.GetCurrentProcess.restype = wintypes.HANDLE
            h = self.k32.GetCurrentProcess()
        else:
            h = wintypes.HANDLE(int(proc._handle))
        if not self.k32.AssignProcessToJobObject(self.handle, h):
            raise ctypes.WinError(ctypes.get_last_error())
        if (self.ws_mb or self.threads) and not getattr(self, "_watch", None):
            self._watch = threading.Event()
            threading.Thread(target=self._cap_loop, daemon=True).start()

    def pids(self) -> list[int]:
        """Procesos vivos del job (JobObjectBasicProcessIdList)."""
        class LIST(ctypes.Structure):
            _fields_ = [("Assigned", wintypes.DWORD), ("InList", wintypes.DWORD), ("Ids", ctypes.c_size_t * 64)]
        lst = LIST()
        self.k32.QueryInformationJobObject(self.handle, 3, ctypes.byref(lst), ctypes.sizeof(lst), None)
        return [lst.Ids[i] for i in range(min(lst.InList, 64))]

    def update(self, ram_mb: int | None, threads: int | None):
        """Cambia los límites en caliente (RAM por proceso y afinidad)."""
        self.ws_mb = ram_mb or None
        self.threads = threads or None
        info = _EXT()
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE if self.kill else JOB_OBJECT_LIMIT_BREAKAWAY_OK
        if threads:
            flags |= JOB_OBJECT_LIMIT_AFFINITY
            info.Basic.Affinity = (1 << threads) - 1
        info.Basic.LimitFlags = flags
        self.k32.SetInformationJobObject(self.handle, ExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
        self._seen = None  # se reparte de nuevo
        if not threads:  # sin tope de hilos: cada proceso vuelve a poder usar todos
            import os

            self.k32.OpenProcess.restype = wintypes.HANDLE
            self.k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
            for pid in self.pids():
                h = self.k32.OpenProcess(0x0200 | 0x0400, False, pid)
                if h:
                    self.k32.SetProcessAffinityMask(h, (1 << (os.cpu_count() or 1)) - 1)
                    self.k32.CloseHandle(h)
        if not ram_mb:  # sin tope: se le devuelve a cada proceso su memoria sin límite
            self.k32.OpenProcess.restype = wintypes.HANDLE
            self.k32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
            for pid in self.pids():
                h = self.k32.OpenProcess(0x0100 | 0x0200 | 0x0400, False, pid)
                if h:  # topes blandos otra vez (MIN_DISABLE | MAX_DISABLE)
                    self.k32.SetProcessWorkingSetSizeEx(h, 1 << 20, 256 << 20, 0x2 | 0x8)
                    self.k32.CloseHandle(h)
        if (self.ws_mb or self.threads) and not getattr(self, "_watch", None):
            self._watch = threading.Event()
            threading.Thread(target=self._cap_loop, daemon=True).start()

    def _is_python(self, pid: int) -> bool:
        """Solo el servidor y la voz (Python) se reparten la RAM: nvidia-smi, ffmpeg o yt-dlp duran
        segundos y no deben achicar el tope de los demás."""
        k32 = self.k32
        h = k32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return bool(ok) and "python" in buf.value.lower()
        finally:
            k32.CloseHandle(h)

    def _cap_loop(self):
        """Reparte el tope de RAM entre los procesos del job (el de la voz aparece después) y les
        pone la afinidad de CPU (el límite del job no cambia la de un proceso que ya corría)."""
        k32 = self.k32
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
        k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        self._seen = None
        first = True
        while self.handle and (first or not self._watch.wait(0.5)):
            first = False
            ids = tuple(sorted(p for p in self.pids() if self._is_python(p)))
            if not ids or ids == self._seen:
                continue
            self._seen = ids
            share = max(64, self.ws_mb // len(ids)) if self.ws_mb else None
            for pid in ids:
                h = k32.OpenProcess(0x0100 | 0x0200 | 0x0400, False, pid)  # SET_QUOTA | SET_INFORMATION | QUERY_INFORMATION
                if not h:
                    continue
                if share:
                    k32.SetProcessWorkingSetSizeEx(h, 1 << 20, share << 20, 0x4 | 0x2)  # HARDWS_MAX | MIN_DISABLE
                if self.threads:
                    k32.SetProcessAffinityMask(h, (1 << self.threads) - 1)
                k32.CloseHandle(h)

    def peak_mb(self) -> int:
        """Pico de memoria comprometida de todo el job (servidor + voz), en MB."""
        info = _EXT()
        self.k32.QueryInformationJobObject(self.handle, ExtendedLimitInformation, ctypes.byref(info),
                                           ctypes.sizeof(info), None)
        return info.PeakJobMemoryUsed >> 20

    def close(self):
        if getattr(self, "_watch", None):
            self._watch.set()
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


# ------------------------------------------------------------------ el servidor
_self_job: Job | None = None


def apply_self(ram_mb: int | None = None, threads: int | None = None) -> str | None:
    """Pone (o cambia, o quita) los límites del servidor de Translay y de su proceso de voz.
    Devuelve un error legible si no se pudo (p. ej. fuera de Windows)."""
    global _self_job
    if sys.platform != "win32":
        return "Los límites de RAM y CPU desde Translay son de Windows; en Docker usa --memory y --cpus." if (ram_mb or threads) else None
    try:
        if _self_job is None:
            if not ram_mb and not threads:
                return None
            _self_job = Job(ram_mb=ram_mb, ram_mode="paging", threads=threads, kill_on_close=False)
            _self_job.add()
        else:
            _self_job.update(ram_mb, threads)
    except OSError as e:
        return f"No se pudieron aplicar los límites: {e}"
    return None
