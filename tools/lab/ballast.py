"""Lastre de VRAM: ocupa memoria real de la GPU para que solo quede libre la de un lab.

Usa la API del driver de CUDA (nvcuda.dll / libcuda.so) con ctypes: no necesita
torch ni nada instalado. Reserva en bloques de 256 MB, los escribe (para que el
driver los tenga de verdad en la GPU) y los vuelve a tocar cada pocos segundos
para que no se desalojen. Se libera solo al terminar el proceso.

    python tools/lab/ballast.py 4096      # ocupa 4 GB; escribe «listo <MB>» y espera
"""

import ctypes
import sys
import time

BLOCK = 256 << 20


def load_cuda():
    names = ["nvcuda.dll"] if sys.platform == "win32" else ["libcuda.so.1", "libcuda.so"]
    for n in names:
        try:
            return ctypes.CDLL(n)
        except OSError:
            continue
    raise SystemExit("sin driver de CUDA")


def main():
    want_mb = int(sys.argv[1])
    cu = load_cuda()
    check = lambda r, what: r == 0 or sys.exit(f"{what}: error {r}")  # noqa: E731
    check(cu.cuInit(0), "cuInit")
    dev = ctypes.c_int()
    check(cu.cuDeviceGet(ctypes.byref(dev), 0), "cuDeviceGet")
    ctx = ctypes.c_void_p()
    check(cu.cuCtxCreate_v2(ctypes.byref(ctx), 0, dev), "cuCtxCreate")
    ptrs = []
    left = want_mb << 20
    while left > 0:
        size = min(BLOCK, left)
        p = ctypes.c_uint64()
        if cu.cuMemAlloc_v2(ctypes.byref(p), ctypes.c_size_t(size)) != 0:
            break  # no hay más: se queda con lo que logró
        cu.cuMemsetD8_v2(p, 0x5A, ctypes.c_size_t(size))
        ptrs.append((p, size))
        left -= size
    cu.cuCtxSynchronize()
    got = sum(s for _, s in ptrs) >> 20
    print(f"listo {got}", flush=True)
    # mantener el lastre residente hasta que el lab cierre stdin
    import threading

    stop = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), stop.set()), daemon=True).start()
    while not stop.wait(3.0):
        for p, size in ptrs:
            cu.cuMemsetD8_v2(p, 0x5A, ctypes.c_size_t(min(size, 1 << 20)))
        cu.cuCtxSynchronize()


if __name__ == "__main__":
    main()
