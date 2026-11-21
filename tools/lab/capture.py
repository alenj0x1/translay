"""Lab: ¿se pierde alguna grabación de pantalla?

Graba de verdad con Chrome (sin ventana, perfil propio) una pestaña «Fuente LAB» con
imagen animada y un tono, contra un servidor de Translay propio (carpeta de datos
temporal, CPU, sin voz, «Al agregar: solo descargar» para no procesar), y provoca
cada forma de corte que puede pasarle a quien graba:

  normal          se detiene con el botón
  fuente_cerrada  se cierra la pestaña que se graba y después el navegador, sin volver
  fuente_y_detener se cierra la pestaña que se graba y después se detiene con el botón
  app_cerrada     se cierra la pestaña de Translay y se vuelve a abrir
  navegador_muere se mata el navegador entero y se vuelve a abrir
  servidor        se reinicia el servidor a mitad de la grabación
  otro_origen     se mata el navegador y se vuelve por 127.0.0.1 en vez de localhost
  nunca_vuelve    se mata el navegador y nadie vuelve a abrir Translay
  solo_audio      «Solo audio»: se cierra la fuente y después el navegador, sin volver

Línea base (2026-11-21, 2 vueltas): normal, app_cerrada, navegador_muere y servidor 2/2;
fuente_cerrada, otro_origen, nunca_vuelve y solo_audio 0/2 (lo recibido quedaba en el
servidor y nadie lo armaba). Arreglo: el servidor termina solo la grabación sin partes por
60 s (vt/capture.py, sweep).

Lo que se mide es lo que ve la persona: el video aparece en la biblioteca con su
archivo, y dura lo que se grabó (no un registro interno). Por escenario se anota
además si quedó una tarjeta sin archivo y lo que quedó a medias en el servidor.

    python tools/lab/capture.py                     # todos, una vuelta
    python tools/lab/capture.py --only normal,servidor --rounds 2

Datos crudos en data/labs/capture/<fecha>/ (resultados.json y el registro del servidor).
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
MARK = "vt-lab-capture"  # en la línea de comandos de todo lo que lanza el lab (para barrer restos)
SRC_TITLE = "Fuente LAB"
SRC_HTML = f"""<!doctype html><title>{SRC_TITLE}</title><body style="margin:0;background:#123">
<canvas id=c width=640 height=360></canvas><script>
const c=document.getElementById('c').getContext('2d');let f=0;
(function d(){{f++;c.fillStyle='#'+((f*2654435761)>>>8&0xffffff).toString(16).padStart(6,'0');
c.fillRect(0,0,640,360);c.fillStyle='#fff';c.font='64px sans-serif';c.fillText(String(f),40,200);requestAnimationFrame(d)}})();
const a=new AudioContext(),o=a.createOscillator();o.frequency.value=440;o.connect(a.destination);o.start();
</script>"""

SCENARIOS = ["normal", "fuente_cerrada", "fuente_y_detener", "app_cerrada", "navegador_muere", "servidor", "otro_origen",
             "nunca_vuelve", "solo_audio"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def kill_marked(marker: str):
    """Termina, con su árbol, los Chrome y servidores del lab cuya línea de comandos tenga `marker`.
    Nunca el lab mismo ni sus padres: la consola que lo lanzó puede llevar la marca en su comando
    (la primera corrida se mató sola porque su salida se llamaba vt-lab-capture-base.txt)."""
    ps = ("$all = Get-CimInstance Win32_Process; $skip = @(); $p = %d; "
          "while ($p) { $skip += $p; $p = ($all | Where-Object ProcessId -eq $p).ParentProcessId; if ($skip -contains $p) { break } }; "
          "$all | Where-Object { $_.CommandLine -like '*%s*' -and ($_.Name -eq 'chrome.exe' -or $_.CommandLine -like '*run.py*') "
          "-and $skip -notcontains $_.ProcessId } | ForEach-Object { $_.ProcessId }") % (os.getpid(), marker)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    for pid in out.split():
        subprocess.run(["taskkill", "/T", "/F", "/PID", pid], capture_output=True)


class Server:
    def __init__(self, data: Path, port: int, log: Path):
        self.data, self.port, self.log, self.p = data, port, log, None

    def start(self):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "VT_LAB": MARK}
        f = self.log.open("a", encoding="utf-8")
        f.write(f"\n===== arranque {time.strftime('%H:%M:%S')}\n")
        f.flush()
        self.p = subprocess.Popen([sys.executable, str(ROOT / "run.py"), "--no-browser", "--port", str(self.port),
                                   "--data-dir", str(self.data), "--device", "cpu", "--voice", "none", "--translator", "none"] ,
                                  cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 120:
            if self.p.poll() is not None:
                raise RuntimeError(f"el servidor se cerró al arrancar (ver {self.log})")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=2).read(64)
                return time.time() - t0
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("el servidor no respondió en 2 min")

    def stop(self):
        if self.p and self.p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.p.pid)], capture_output=True)
            self.p.wait(10)


def library(data: Path) -> dict:
    try:
        return json.loads((data / "library.json").read_text(encoding="utf-8")).get("videos", {})
    except (OSError, ValueError):
        return {}


def probe(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def run_scenario(pw, name: str, work: Path, rec_s: float, wait_s: float) -> dict:
    data, prof = work / f"{name}-data", work / f"{name}-perfil"
    data.mkdir(parents=True)
    (data / "prefs.json").write_text(json.dumps({"import_mode": "descargar", "welcomed": True}), encoding="utf-8")
    port = free_port()
    srv = Server(data, port, work / f"{name}-servidor.log")
    res = {"escenario": name, "grabado_s": rec_s, "eventos": []}

    def ev(msg):
        res["eventos"].append(f"{time.strftime('%H:%M:%S')} {msg}")
        print(f"  [{name}] {msg}", flush=True)

    res["arranque_servidor_s"] = round(srv.start(), 1)
    args = [f"--auto-select-tab-capture-source-by-title={SRC_TITLE}", "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required", f"--{MARK}"]

    def launch():
        return pw.chromium.launch_persistent_context(str(prof), executable_path=CHROME, headless=True, args=args,
                                                     viewport={"width": 1280, "height": 800})

    def open_app(ctx, host="localhost"):
        page = ctx.new_page()
        page.goto(f"http://{host}:{port}/")
        page.wait_for_function("typeof openCapture === 'function' && typeof capRec === 'object'", timeout=30000)
        return page

    ctx = launch()
    try:
        src = ctx.new_page()
        src.set_content(SRC_HTML)
        app = open_app(ctx)
        time.sleep(2)  # que llegue el «ready» del servidor
        if name == "solo_audio":
            app.evaluate("capOpts.q = 'audio'")
        app.evaluate("openCapture()")
        app.wait_for_function("capDlg.open && capUI.stream", timeout=15000)
        app.evaluate("capDlg.close('ok')")
        app.wait_for_function("capRec.rec && capRec.rec.state === 'recording'", timeout=15000)
        cid = app.evaluate("capRec.id")
        res["id"] = cid
        t0 = time.time()
        ev(f"grabando {cid}")

        if name == "servidor":
            time.sleep(rec_s / 3)
            srv.stop()
            ev("servidor detenido")
            time.sleep(3)
            srv.start()
            ev("servidor de vuelta")
            time.sleep(max(0, rec_s - (time.time() - t0)))
            app.evaluate("stopRecording()")
        else:
            time.sleep(rec_s)
            if name == "normal":
                app.evaluate("stopRecording()")
            elif name in ("fuente_cerrada", "solo_audio", "fuente_y_detener"):
                # Chrome no avisa que la pestaña grabada se cerró (las pistas siguen «vivas», sin ended ni
                # mute: medido 2026-11-21): la grabación sigue hasta que la persona la detiene o cierra todo
                src.close()
                ev("fuente cerrada")
                time.sleep(5)
                if name == "fuente_y_detener":
                    app.evaluate("stopRecording()")
                    ev("detenida con el botón")
                else:
                    kill_marked(str(prof.name))
                    ev("navegador cerrado sin volver")
                    try:
                        ctx.close()
                    except Exception:  # noqa: BLE001  ya no existe
                        pass
                    ctx = None
            elif name == "app_cerrada":
                app.close(run_before_unload=False)
                ev("Translay cerrado")
                time.sleep(3)
                app = open_app(ctx)
                ev("Translay abierto de nuevo")
            elif name in ("navegador_muere", "otro_origen", "nunca_vuelve"):
                kill_marked(str(prof.name))
                ev("navegador muerto")
                try:
                    ctx.close()
                except Exception:  # ya no existe
                    pass
                ctx = None
                time.sleep(3)
                if name != "nunca_vuelve":
                    ctx = launch()
                    app = open_app(ctx, "127.0.0.1" if name == "otro_origen" else "localhost")
                    ev("navegador abierto de nuevo")
        res["real_s"] = round(time.time() - t0, 1)

        # lo que ve la persona: el video en la biblioteca, con archivo
        deadline = time.time() + wait_s
        v = {}
        while time.time() < deadline:
            v = library(data).get(cid, {})
            if v.get("media"):
                break
            time.sleep(1)
        media = v.get("media", "")
        f = data / "library" / media.rsplit("/", 1)[-1] if media else None
        res["en_biblioteca"] = bool(v)
        res["con_archivo"] = bool(f and f.exists())
        res["tarjeta_sin_archivo"] = bool(v) and not res["con_archivo"]
        res["duracion_s"] = round(probe(f), 1) if res["con_archivo"] else 0.0
        res["espera_s"] = round(wait_s - max(0, deadline - time.time()), 1)
        part = data / "library" / "captures" / f"{cid}.webm.part"
        res["quedo_en_servidor_mb"] = round(part.stat().st_size / 1e6, 2) if part.exists() else 0.0
        if ctx:
            try:
                res["quedo_en_navegador"] = app.evaluate("capGetAll().then(l => l.length)")
            except Exception as e:  # noqa: BLE001
                res["quedo_en_navegador"] = f"? {e.__class__.__name__}"
        ok = res["con_archivo"] and res["duracion_s"] >= rec_s - 2.5
        res["ok"] = ok
        ev(("OK" if ok else "FALLA") + f": biblioteca={res['en_biblioteca']} archivo={res['con_archivo']} "
           f"dura={res['duracion_s']}s de {rec_s}s, servidor guarda {res['quedo_en_servidor_mb']} MB")
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
        kill_marked(str(prof.name))
        srv.stop()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="escenarios separados por coma (por defecto, todos)")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=12, help="segundos que se graba")
    ap.add_argument("--wait", type=float, default=150, help="segundos que se espera a que aparezca en la biblioteca")
    ap.add_argument("--label", default="", help="nombre de la corrida (p. ej. base o arreglo)")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    names = [n for n in a.only.split(",") if n] or SCENARIOS
    bad = [n for n in names if n not in SCENARIOS]
    if bad:
        sys.exit(f"escenarios desconocidos: {bad}")
    if not Path(CHROME).exists() or not shutil.which("ffprobe"):
        sys.exit("hace falta Chrome y ffprobe")
    kill_marked(MARK)  # restos de una corrida anterior
    out = ROOT / "data" / "labs" / "capture" / (time.strftime("%Y%m%d-%H%M%S") + (f"-{a.label}" if a.label else ""))
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix=MARK + "-"))
    results = []
    try:
        with sync_playwright() as pw:
            for rnd in range(a.rounds):
                for n in names:
                    print(f"vuelta {rnd + 1} · {n}", flush=True)
                    try:
                        r = run_scenario(pw, n, work / f"r{rnd}", a.seconds, a.wait)
                    except Exception as e:  # noqa: BLE001  el lab sigue con el próximo
                        r = {"escenario": n, "ok": False, "error": f"{e.__class__.__name__}: {e}"[:400]}
                        print(f"  [{n}] ERROR {r['error']}", flush=True)
                    r["vuelta"] = rnd + 1
                    results.append(r)
                    (out / "resultados.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        kill_marked(MARK)
        for log in work.rglob("*-servidor.log"):
            shutil.copy(log, out / f"{log.parent.name}-{log.name}")
        shutil.rmtree(work, ignore_errors=True)
    print("\nresumen")
    for n in names:
        rs = [r for r in results if r["escenario"] == n]
        print(f"  {n:16s} {sum(r['ok'] for r in rs)}/{len(rs)}  "
              + "  ".join(f"{r.get('duracion_s', 0)}s" + ("" if r.get("ok") else " ✗") for r in rs))
    print(f"datos: {out}")


if __name__ == "__main__":
    main()
