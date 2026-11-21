"""Silenciar las otras aplicaciones mientras se graba una ventana (Windows).

En Windows 10 el navegador no puede grabar solo el sonido de una ventana: trae el de todo el
equipo (la captura por proceso llegó con la compilación 20348, Windows 11). Con la preferencia
«Silenciar las otras apps al grabar una ventana» (apagada por defecto), mientras dura la
grabación se silencian las sesiones de audio de todas las aplicaciones menos la de la ventana
elegida, y al terminar se les devuelve el sonido.

Solo se tocan las sesiones que estaban con sonido, y solo esas se restauran: lo que la persona
ya tenía silenciado sigue así. La lista se guarda en disco (`muted.json`) para restaurarla al
arrancar si Translay se cerró de golpe en medio de una grabación.

Core Audio por ctypes (sin dependencias): IMMDeviceEnumerator → cada salida activa →
IAudioSessionManager2 → sus sesiones (IAudioSessionControl2: proceso) → ISimpleAudioVolume
(SetMute). La ventana se conoce por la etiqueta de la pista que da Chrome («window:<HWND>:0»):
se mantienen con sonido las sesiones del mismo programa que la ventana (el audio de un navegador
sale de otro proceso suyo, con el mismo ejecutable). Sin una ventana reconocible no se silencia
nada: es mejor grabar de más que dejar mudo lo que se quería grabar.
"""

import ctypes
import os
import re
import sys
import threading
from ctypes import POINTER, byref, c_int, c_uint, c_void_p, wintypes
from pathlib import Path

from .jsonio import read_json, write_json

AVAILABLE = sys.platform == "win32"
LABEL_RE = re.compile(r"^window:(\d+):")
_lock = threading.Lock()


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, s: str):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p("{" + s + "}"), byref(self))


CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IAudioSessionManager2 = "77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"
IID_IAudioSessionControl2 = "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"
IID_ISimpleAudioVolume = "87CE5498-68D6-44E5-9215-6DA47EF883D8"
E_RENDER, DEVICE_STATE_ACTIVE, CLSCTX_ALL = 0, 1, 23
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _call(obj, index: int, *args, argtypes=()):
    """Método `index` de la tabla virtual de una interfaz COM (IUnknown: 0..2)."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


def _release(obj):
    if obj:
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtbl[2])(obj)


def _qi(obj, iid: str):
    out = c_void_p()
    _call(obj, 0, byref(GUID(iid)), byref(out), argtypes=(POINTER(GUID), POINTER(c_void_p)))
    return out


def exe_of(pid: int) -> str:
    """Nombre del ejecutable de un proceso, en minúsculas («chrome.exe»), o «» si no se puede saber."""
    if not AVAILABLE or not pid:
        return ""
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        k32.CloseHandle(h)


def window_exe(label: str) -> str:
    """El programa de la ventana que graba Chrome, por la etiqueta de su pista («window:<HWND>:0»).
    Las apps de la tienda dibujan dentro de ApplicationFrameHost: se busca la ventana hija de la app."""
    m = LABEL_RE.match(label or "")
    if not AVAILABLE or not m:
        return ""
    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND(int(m.group(1)))
    if not user32.IsWindow(hwnd):
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    exe = exe_of(pid.value)
    if exe == "applicationframehost.exe":
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def child(h, _):
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, byref(p))
            if p.value != pid.value:
                found.append(p.value)
                return False
            return True

        user32.EnumChildWindows(hwnd, child, 0)
        exe = exe_of(found[0]) if found else exe
    return exe


def _sessions():
    """(pid, ISimpleAudioVolume) de cada sesión de audio de cada salida activa. Quien llama libera."""
    out = []
    enum = c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(byref(GUID(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                                         byref(GUID(IID_IMMDeviceEnumerator)), byref(enum))
    coll = c_void_p()
    try:
        _call(enum, 3, E_RENDER, DEVICE_STATE_ACTIVE, byref(coll), argtypes=(c_int, wintypes.DWORD, POINTER(c_void_p)))
        n = c_uint()
        _call(coll, 3, byref(n), argtypes=(POINTER(c_uint),))
        for i in range(n.value):
            dev, mgr, senum = c_void_p(), c_void_p(), c_void_p()
            try:
                _call(coll, 4, i, byref(dev), argtypes=(c_uint, POINTER(c_void_p)))
                _call(dev, 3, byref(GUID(IID_IAudioSessionManager2)), CLSCTX_ALL, None, byref(mgr),
                      argtypes=(POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)))
                _call(mgr, 5, byref(senum), argtypes=(POINTER(c_void_p),))
                count = c_int()
                _call(senum, 3, byref(count), argtypes=(POINTER(c_int),))
                for j in range(count.value):
                    ctl = c_void_p()
                    _call(senum, 4, j, byref(ctl), argtypes=(c_int, POINTER(c_void_p)))
                    try:
                        ctl2 = _qi(ctl, IID_IAudioSessionControl2)
                        pid = wintypes.DWORD()
                        _call(ctl2, 14, byref(pid), argtypes=(POINTER(wintypes.DWORD),))  # GetProcessId
                        vol = _qi(ctl, IID_ISimpleAudioVolume)
                        _release(ctl2)
                        out.append((pid.value, vol))
                    except OSError:
                        pass
                    finally:
                        _release(ctl)
            except OSError:
                continue
            finally:
                for o in (senum, mgr, dev):
                    _release(o)
    finally:
        _release(coll)
        _release(enum)
    return out


def _get_mute(vol) -> bool:
    b = wintypes.BOOL()
    _call(vol, 6, byref(b), argtypes=(POINTER(wintypes.BOOL),))
    return bool(b.value)


def _set_mute(vol, on: bool):
    _call(vol, 5, wintypes.BOOL(on), None, argtypes=(wintypes.BOOL, c_void_p))


def _with_com(fn):
    # S_OK o S_FALSE (ya iniciado igual): cada uno pide su CoUninitialize; otro modo en el hilo: se usa ese
    started = ctypes.windll.ole32.CoInitializeEx(None, 0) in (0, 1)  # COINIT_MULTITHREADED
    try:
        return fn()
    finally:
        if started:
            ctypes.windll.ole32.CoUninitialize()


class AppMute:
    """Una sola grabación silencia a la vez. `state` guarda [pid, exe] de lo silenciado por Translay."""

    def __init__(self, state: Path):
        self.state = state
        self.owner = None  # quién lo pidió (la sesión de la pestaña que graba)

    def mute_others(self, label: str, owner) -> dict:
        """Silencia todo menos el programa de la ventana. {"muted": n, "keep": exe} o {"error": motivo}."""
        if not AVAILABLE:
            return {"error": "unsupported"}
        keep = window_exe(label)
        if not keep:
            return {"error": "no_window"}
        with _lock:
            self._restore_locked()
            own_pid = os.getpid()

            def run():
                done = []
                for pid, vol in _sessions():
                    try:
                        if pid != own_pid and exe_of(pid) != keep and not _get_mute(vol):  # 0: sonidos del sistema
                            _set_mute(vol, True)
                            done.append([pid, exe_of(pid)])
                    except OSError:
                        pass
                    finally:
                        _release(vol)
                return done

            done = _with_com(run)
            write_json(self.state, done)
            self.owner = owner
        return {"muted": len(done), "keep": keep}

    def restore(self, owner=None) -> int:
        """Devuelve el sonido a lo que Translay silenció (de quien lo pidió, o todo si owner es None)."""
        if not AVAILABLE:
            return 0
        with _lock:
            if owner is not None and owner is not self.owner:
                return 0
            return self._restore_locked()

    def _restore_locked(self) -> int:
        saved = read_json(self.state, None) or []
        if not saved:
            return 0
        want = {(int(p), str(e)) for p, e in saved}

        def run():
            n = 0
            for pid, vol in _sessions():
                try:
                    if (pid, exe_of(pid)) in want and _get_mute(vol):
                        _set_mute(vol, False)
                        n += 1
                except OSError:
                    pass
                finally:
                    _release(vol)
            return n

        n = _with_com(run)
        write_json(self.state, [])
        self.owner = None
        return n
