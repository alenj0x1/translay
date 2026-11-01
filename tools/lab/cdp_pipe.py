"""Lab: hablar con un navegador tipo Chrome por un canal privado (sin puerto de red).

Prueba que en Windows se puede abrir Brave/Chrome/Edge con un perfil propio y
`--remote-debugging-pipe`, pasando los dos extremos del canal con
`--remote-debugging-io-pipes=<leer>,<escribir>`, y pedirle las cookies con
Storage.getCookies. Mide cuánto tarda cada paso.

    python tools/lab/cdp_pipe.py --browser brave --headless

Resultados (2026-11-01, i5-12400, Windows 10):
- Brave 156 y Chrome 156: conectan en 0.2-0.5 s; cierran en ~3.5 s en total.
- Edge 156: se cierra al arrancar, incluso sin el canal ni el modo sin ventana
  (tenía una actualización a medias); la app lo informa y ofrece otro navegador.
- Google rechaza iniciar sesión en una ventana abierta con el canal («This browser
  or app may not be secure»): la ventana de inicio de sesión va sin canal y las
  cookies se leen después, sin ventana. Así funcionó con Brave.
- Con la sesión: solo las cookies de .youtube.com (20) bastan para yt-dlp (se
  reconoce la lista privada WL); renovar sin ventana tarda ~9 s y mantiene la sesión.
"""

import argparse
import json
import msvcrt
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

EXES = {
    "brave": [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
    "edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="brave", choices=EXES)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--exe", help="ruta del ejecutable (por defecto, la instalada)")
    ap.add_argument("--url", default="https://www.youtube.com/robots.txt")
    a = ap.parse_args()
    exe = a.exe or next(p for p in EXES[a.browser] if Path(p).exists())
    prof = Path(tempfile.mkdtemp(prefix="vt-lab-"))
    # navegador lee de r_in y escribe en w_out
    r_in, w_in = os.pipe()
    r_out, w_out = os.pipe()
    h_read, h_write = msvcrt.get_osfhandle(r_in), msvcrt.get_osfhandle(w_out)
    os.set_handle_inheritable(h_read, True)
    os.set_handle_inheritable(h_write, True)
    si = subprocess.STARTUPINFO()
    si.lpAttributeList = {"handle_list": [h_read, h_write]}
    args = [exe, f"--user-data-dir={prof}", "--remote-debugging-pipe",
            f"--remote-debugging-io-pipes={h_read},{h_write}", "--no-first-run", "--no-default-browser-check",
            *(["--headless=new"] if a.headless else []), a.url]
    t0 = time.time()
    p = subprocess.Popen(args, startupinfo=si, close_fds=True)
    os.close(r_in)
    os.close(w_out)
    out, buf = os.fdopen(w_in, "wb", buffering=0), b""

    def call(i, method, params=None):
        nonlocal buf
        out.write(json.dumps({"id": i, "method": method, "params": params or {}}).encode() + b"\0")
        while True:
            while b"\0" not in buf:
                chunk = os.read(r_out, 65536)
                if not chunk:
                    raise EOFError("el navegador cerró el canal")
                buf += chunk
            msg, buf = buf.split(b"\0", 1)
            m = json.loads(msg)
            if m.get("id") == i:
                return m

    try:
        v = call(1, "Browser.getVersion")
        print(f"conectado en {time.time() - t0:.2f}s: {v['result']['product']}")
        time.sleep(3)
        c = call(2, "Storage.getCookies")
        cookies = c["result"]["cookies"]
        print(f"cookies: {len(cookies)} ({sorted({x['domain'] for x in cookies})}) en {time.time() - t0:.2f}s")
        call(3, "Browser.close")
    finally:
        p.wait(timeout=15)
        shutil.rmtree(prof, ignore_errors=True)
    print(f"cerrado en {time.time() - t0:.2f}s")


if __name__ == "__main__":
    sys.exit(main())
