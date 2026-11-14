"""Laboratorio: cuánto le quita el agente al resto del equipo mientras responde.

  python tools/lab/footprint.py                         todas las variantes, 2 rondas (~12 min)
  python tools/lab/footprint.py --variants base combo --rounds 3
  python tools/lab/footprint.py --report

Lo que mide es lo que nota la persona que sigue usando el equipo, no el uso en % del administrador de tareas:
  fluidez   una ventana chica de Brave/Chrome anima un sombreador WebGL (como un video o una página con
            movimiento) y reporta el intervalo de cada cuadro: p95 en ms y % de cuadros trabados (más del
            doble del intervalo normal medido sin el agente)
  cpu       otro proceso, con prioridad normal, hace trabajo fijo (sha256 en 4 hilos): cuánto rinde frente
            al reposo (100 % = como si el agente no estuviera)
  latencia  cuánto se pasa un sleep de 1 ms en ese proceso (p95): lo que tarda el sistema en atender a
            otra app que despierta (teclear, mover una ventana)
y el costo para el agente: tiempo hasta la primera palabra, velocidad al escribir y duración total.

Cada muestra: 4 s de reposo (la referencia de ese momento) y una respuesta completa sin caché (el peor caso: la
primera pregunta sobre un video de 20 min, unas 24 mil palabras, como la app en una GPU dedicada). Las
fases «leyendo» (antes de la primera palabra) y «escribiendo» se miden por separado.

Variantes (el mismo modelo y motor que usa la app en este equipo: qwen3.5-4b por Vulkan):
  base     como hoy: prioridad normal, la mitad de los hilos, tandas de 512
  prio     el proceso y su trabajo en la GPU con prioridad baja (SetPriorityClass + D3DKMT)
  poll0    los hilos esperan dormidos en vez de girar (--poll 0)
  ub128    tandas de 128 al leer (-b 256 -ub 128): la GPU queda libre más seguido
  ub32     tandas de 32
  t3       3 hilos en vez de 6
  combo    prio + poll0 + ub128

Resultados: data/labs/footprint/out/<fecha>.jsonl (una línea por muestra, con los datos crudos de cada fase).
"""

from __future__ import annotations

import argparse
import ctypes
import http.server
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from vt import agent, llm  # noqa: E402
from agent import load_video, gpu_busy  # noqa: E402

LAB = ROOT / "data" / "labs" / "footprint"
OUT = LAB / "out"
AGENT_LAB = ROOT / "data" / "labs" / "agent"
BROWSERS = [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]

VARIANTS = {
    "base": dict(),
    "prio": dict(prio=True),
    "poll0": dict(args=["--poll", "0"]),
    "ub128": dict(args=["-b", "256", "-ub", "128"]),
    "ub64": dict(args=["-b", "128", "-ub", "64"]),
    "ub32": dict(args=["-b", "64", "-ub", "32"]),
    "t3": dict(threads=3),
    "combo": dict(prio=True, args=["--poll", "0", "-b", "256", "-ub", "128"]),
}
MODEL, CTX, BUDGET, THREADS = "qwen3.5-4b", 32768, 24000, 6
QUESTION = "¿Qué ideas principales explica el video? Resúmelas en cinco puntos."

# ------------------------------------------------------------------ prioridad (CPU y GPU)
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
D3DKMT_BELOW_NORMAL = 1


def lower_priority(pid: int) -> dict:
    """Prioridad baja para el proceso (CPU) y para su trabajo en la GPU (planificador de WDDM)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x0200 | 0x0400, False, pid)  # PROCESS_SET_INFORMATION | QUERY_INFORMATION
    if not h:
        return {"cpu": False, "gpu": False}
    try:
        cpu = bool(k32.SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS))
        try:
            gdi = ctypes.WinDLL("gdi32")
            gpu = gdi.D3DKMTSetProcessSchedulingPriorityClass(h, D3DKMT_BELOW_NORMAL) == 0
        except (OSError, AttributeError):
            gpu = False
        return {"cpu": cpu, "gpu": gpu}
    finally:
        k32.CloseHandle(h)


# ------------------------------------------------------------------ sonda de fluidez (navegador)
PAGE = """<!doctype html><meta charset=utf-8><title>sonda</title>
<style>html,body{margin:0;height:100%;background:#000}canvas{width:100%;height:100%;display:block}</style>
<canvas id=c></canvas><script>
const c=document.getElementById('c'),g=c.getContext('webgl');
c.width=innerWidth*devicePixelRatio;c.height=innerHeight*devicePixelRatio;g.viewport(0,0,c.width,c.height);
const vs='attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
const fs='precision highp float;uniform float t;uniform vec2 r;void main(){vec2 u=gl_FragCoord.xy/r;float a=0.;'+
 'for(int i=0;i<24;i++){a+=sin(u.x*float(i)*3.+t*1.3)*cos(u.y*float(i)*2.+t);}gl_FragColor=vec4(.5+.5*sin(a),.4,.6,1.);}';
function sh(type,src){const s=g.createShader(type);g.shaderSource(s,src);g.compileShader(s);return s}
const pr=g.createProgram();g.attachShader(pr,sh(g.VERTEX_SHADER,vs));g.attachShader(pr,sh(g.FRAGMENT_SHADER,fs));g.linkProgram(pr);g.useProgram(pr);
const b=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,b);g.bufferData(g.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),g.STATIC_DRAW);
const loc=g.getAttribLocation(pr,'p');g.enableVertexAttribArray(loc);g.vertexAttribPointer(loc,2,g.FLOAT,false,0,0);
const ut=g.getUniformLocation(pr,'t'),ur=g.getUniformLocation(pr,'r');let buf=[];
function f(now){g.uniform1f(ut,now/1000);g.uniform2f(ur,c.width,c.height);g.drawArrays(g.TRIANGLES,0,3);
 buf.push(performance.timeOrigin+now);requestAnimationFrame(f)}
requestAnimationFrame(f);
setInterval(()=>{const x=buf;buf=[];fetch('/f',{method:'POST',body:JSON.stringify(x)}).catch(()=>{})},500);
</script>"""


class Frames:
    """Recibe los tiempos de cada cuadro que pinta la ventana de la sonda."""

    def __init__(self):
        self.t: list[float] = []  # epoch en ms
        self.lock = threading.Lock()
        frames = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with frames.lock:
                    frames.t.extend(data)
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def between(self, a: float, b: float) -> list[float]:
        with self.lock:
            return [x for x in self.t if a <= x <= b]


def open_browser(port: int) -> tuple[subprocess.Popen, str]:
    exe = next((b for b in BROWSERS if Path(b).exists()), None)
    if not exe:
        raise SystemExit("falta Brave o Chrome para la sonda de fluidez")
    prof = tempfile.mkdtemp(prefix="footprint-")
    p = subprocess.Popen([exe, f"--user-data-dir={prof}", f"--app=http://127.0.0.1:{port}/", "--window-position=0,0",
                          "--window-size=420,300", "--no-first-run", "--no-default-browser-check",
                          "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                          "--disable-backgrounding-occluded-windows"])
    return p, prof


# ------------------------------------------------------------------ sonda de CPU y latencia (otro proceso)
def worker_main(path: str):
    """Corre en su propio proceso: 4 hilos de sha256 (C, sin el GIL) y un hilo que mide sleep(1 ms)."""
    import hashlib

    ctypes.WinDLL("winmm").timeBeginPeriod(1)
    data = os.urandom(1 << 20)
    count = [0]
    lock = threading.Lock()

    def work():
        while True:
            hashlib.sha256(data).digest()
            with lock:
                count[0] += 1
    for _ in range(4):
        threading.Thread(target=work, daemon=True).start()
    lat: list[float] = []

    def sleeper():
        while True:
            t = time.perf_counter()
            time.sleep(0.001)
            lat.append((time.perf_counter() - t) * 1000)
    threading.Thread(target=sleeper, daemon=True).start()
    with open(path, "a", encoding="utf-8") as out:
        while True:
            time.sleep(0.25)
            with lock:
                n, count[0] = count[0], 0
            l, lat[:] = lat[:], []
            out.write(json.dumps({"t": time.time() * 1000, "n": n, "lat": [round(x, 2) for x in l]}) + "\n")
            out.flush()


def read_worker(path: Path, a: float, b: float) -> tuple[list[int], list[float]]:
    n, lat = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if a <= d["t"] <= b:
            n.append(d["n"])
            lat += d["lat"]
    return n, lat


# ------------------------------------------------------------------ medición
def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def phase(frames: Frames, wpath: Path, a: float, b: float, ref: dict | None) -> dict:
    t = frames.between(a, b)
    iv = [y - x for x, y in zip(t, t[1:])]
    n, lat = read_worker(wpath, a, b)
    out = {"s": round((b - a) / 1000, 2), "frames": len(t), "fps": round(len(t) / max(0.001, (b - a) / 1000), 1),
           "frame_p50": round(statistics.median(iv), 2) if iv else None, "frame_p95": round(pct(iv, .95), 2),
           "frame_max": round(max(iv), 1) if iv else None, "cpu_units": round(statistics.mean(n), 1) if n else 0,
           "lat_p95": round(pct(lat, .95), 2), "lat_p99": round(pct(lat, .99), 2)}
    if ref:
        normal = ref["frame_p50"] or 16.7
        out["jank"] = round(100 * sum(1 for x in iv if x > 2 * normal) / max(1, len(iv)), 1)
        out["cpu_pct"] = round(100 * out["cpu_units"] / max(1, ref["cpu_units"]), 1)
    return out


def idle_ms() -> int:
    """Hace cuánto la persona tocó el teclado o el mouse (si lo usa durante la muestra, la contamina)."""
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    li = LII(ctypes.sizeof(LII), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return ctypes.windll.kernel32.GetTickCount() - li.dwTime


def sample(srv: llm.Server, msgs: list[dict], frames: Frames, wpath: Path) -> dict:
    a = time.time() * 1000
    time.sleep(4)
    b = time.time() * 1000
    ref = phase(frames, wpath, a, b, None)
    first = [None]

    def on_text(_):
        if first[0] is None:
            first[0] = time.time() * 1000
    t0 = time.time() * 1000
    r = srv.chat(msgs, max_tokens=300, temperature=0.3, on_text=on_text, cache_prompt=False,
                 chat_template_kwargs={"enable_thinking": False})
    t1 = time.time() * 1000
    time.sleep(0.6)  # la sonda reporta cada 0.5 s
    f = first[0] or t1
    return {"touched": idle_ms() < (t1 - a + 600), "ref": ref, "leyendo": phase(frames, wpath, t0, f, ref), "escribiendo": phase(frames, wpath, f, t1, ref),
            "ttft_s": r["ttft_s"], "total_s": r["total_s"], "gen_tps": r["gen_tps"], "pp_tps": r.get("pp_tps"),
            "prompt_n": r["prompt_n"], "gen_n": r["gen_n"]}


def run(variants: list[str], rounds: int):
    for _ in range(12):
        if gpu_busy() < 20:
            break
        time.sleep(5)
    else:
        raise SystemExit("la GPU está ocupada por otro programa: la medición no sería válida")
    exe = llm.ensure("vulkan", AGENT_LAB)
    model = llm.model_file(MODEL)
    devs = llm.devices(exe)
    dev = next((d["id"] for d in devs if not d["integrated"]), None)
    if not dev:
        raise SystemExit(f"sin GPU dedicada por Vulkan: {devs}")
    info, tr, screen = load_video("talk-agents")
    msgs, mode = agent.messages(info, tr, screen, QUESTION, [], None, BUDGET)
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{time.strftime('%Y%m%d-%H%M')}.jsonl"
    wpath = LAB / "worker.jsonl"
    wpath.unlink(missing_ok=True)
    frames = Frames()
    browser, prof = open_browser(frames.port)
    worker = subprocess.Popen([sys.executable, __file__, "--worker", str(wpath)])
    srv = None
    try:
        deadline = time.time() + 30
        while time.time() < deadline and len(frames.between(time.time() * 1000 - 2000, time.time() * 1000)) < 30:
            time.sleep(0.5)
        if len(frames.between(time.time() * 1000 - 2000, time.time() * 1000)) < 30:
            raise SystemExit("la ventana de la sonda no está pintando (¿tapada o sin WebGL?)")
        print(f"sonda lista · {dev} · {MODEL} · ctx {CTX} · {mode} · resultados en {out_path}", flush=True)
        for rnd in range(rounds):
            order = variants[:] if rnd % 2 == 0 else variants[::-1]
            for name in order:
                v = VARIANTS[name]
                srv = llm.Server(exe, model, ctx=CTX, threads=v.get("threads", THREADS), gpu_layers=99, device=dev,
                                 extra=v.get("args", []))
                srv.start()
                pr = lower_priority(srv.proc.pid) if v.get("prio") else None
                srv.chat(msgs[:1] + [{"role": "user", "content": "Responde solo: listo"}], max_tokens=1,
                         chat_template_kwargs={"enable_thinking": False})  # calentar
                for k in range(2):
                    time.sleep(random.uniform(0.5, 2))
                    s = sample(srv, msgs, frames, wpath)
                    s.update(variant=name, round=rnd, k=k, prio=pr, args=v.get("args", []), threads=v.get("threads", THREADS),
                             at=time.strftime("%H:%M:%S"))
                    with out_path.open("a", encoding="utf-8") as fo:
                        fo.write(json.dumps(s, ensure_ascii=False) + "\n")
                    le, es = s["leyendo"], s["escribiendo"]
                    print(f"r{rnd} {name:6} {'TOCADO ' if s['touched'] else ''}leyendo jank {le.get('jank')}% p95 {le['frame_p95']}ms cpu {le.get('cpu_pct')}% "
                          f"lat {le['lat_p95']}ms · escribiendo jank {es.get('jank')}% p95 {es['frame_p95']}ms "
                          f"cpu {es.get('cpu_pct')}% · ttft {s['ttft_s']}s {s['gen_tps'] and round(s['gen_tps'])} t/s",
                          flush=True)
                srv.stop()
                srv = None
    finally:
        if srv:
            srv.stop()
        worker.kill()
        browser.kill()
        frames.srv.shutdown()
    report([out_path])


def report(files: list[Path] | None = None):
    files = files or sorted(OUT.glob("*.jsonl"))
    rows: dict[str, list[dict]] = {}
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            if not d.get("touched"):  # la persona usó el equipo durante la muestra: no cuenta
                rows.setdefault(d["variant"], []).append(d)

    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 1) if xs else None
    print(f"{'variante':8} {'n':>2} | leyendo: {'jank%':>6} {'p95ms':>6} {'cpu%':>5} {'lat':>5} | escribiendo: "
          f"{'jank%':>6} {'p95ms':>6} {'cpu%':>5} {'lat':>5} | {'ttft':>5} {'t/s':>5} {'total':>6}")
    for name in VARIANTS:
        rs = rows.get(name)
        if not rs:
            continue
        le = [r["leyendo"] for r in rs]
        es = [r["escribiendo"] for r in rs]
        print(f"{name:8} {len(rs):>2} | leyendo: {med([x.get('jank') for x in le]):>6} {med([x['frame_p95'] for x in le]):>6} "
              f"{med([x.get('cpu_pct') for x in le]):>5} {med([x['lat_p95'] for x in le]):>5} | escribiendo: "
              f"{med([x.get('jank') for x in es]):>6} {med([x['frame_p95'] for x in es]):>6} {med([x.get('cpu_pct') for x in es]):>5} "
              f"{med([x['lat_p95'] for x in es]):>5} | {med([r['ttft_s'] for r in rs]):>5} {med([r['gen_tps'] for r in rs]):>5} "
              f"{med([r['total_s'] for r in rs]):>6}")
    refs = [r["ref"] for rs in rows.values() for r in rs]
    print(f"reposo: cuadro p50 {med([x['frame_p50'] for x in refs])} ms, p95 {med([x['frame_p95'] for x in refs])} ms, "
          f"cpu {med([x['cpu_units'] for x in refs])} u/0.25s, lat p95 {med([x['lat_p95'] for x in refs])} ms")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS), choices=list(VARIANTS))
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.worker:
        return worker_main(a.worker)
    if a.report:
        return report()
    run(a.variants, a.rounds)


if __name__ == "__main__":
    main()
