"""Labs: corre el banco (tools/lab/bench.py) como si fuera otro equipo.

Cada lab es un equipo real de referencia; en esta máquina se reproduce con límites
de verdad, no con estimaciones:

  VRAM   un lastre (tools/lab/ballast.py) ocupa el resto de la GPU: queda la VRAM del lab
         con el mismo escritorio encima; si no alcanza, el driver desborda a memoria
         compartida y todo se vuelve lento, igual que en esa tarjeta.
  RAM    tope de memoria residente para Translay (lo que le deja Windows con el
         navegador abierto en un equipo con esa RAM); lo que no entra se pagina a disco.
  CPU    afinidad a los hilos del lab.
  sin GPU  CUDA oculto: todo corre en la CPU.

Cada configuración (modelos y parámetros) se corre en cada lab; el resultado queda en
data/labs/<corrida>/ (un JSON por prueba y resumen.md).

    python tools/lab/run.py --labs gpu-4g gpu-6g --configs calidad equilibrado --media samples/podcast.mp4
    python tools/lab/run.py --list
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt.limits import Job  # noqa: E402
from vt.hardware import gpus  # noqa: E402

# equipos de referencia. ram_mb: la del equipo; a Translay le queda ram_mb - OS_MB
OS_MB = 3584  # Windows + navegador abierto
LABS = {
    "rtx4060-8g": {"name": "Este equipo (RTX 4060 8 GB)", "vram_mb": None, "ram_mb": None, "threads": None},
    "gpu-6g": {"name": "GPU de 6 GB · 16 GB RAM · 8 hilos (RTX 2060 / 3060 portátil)",
               "vram_mb": 6144, "ram_mb": 16384, "threads": 8},
    "gpu-4g": {"name": "GPU de 4 GB · 8 GB RAM · 8 hilos (GTX 1650 / RTX 3050 portátil)",
               "vram_mb": 4096, "ram_mb": 8192, "threads": 8},
    "gpu-2g": {"name": "GPU de 2 GB · 8 GB RAM · 4 hilos (MX 450)", "vram_mb": 2048, "ram_mb": 8192, "threads": 4},
    "cpu-8": {"name": "Sin GPU · 16 GB RAM · 8 hilos", "gpu": False, "ram_mb": 16384, "threads": 8},
    "cpu-4": {"name": "Sin GPU · 8 GB RAM · 4 hilos", "gpu": False, "ram_mb": 8192, "threads": 4},
}

# configuraciones a comparar (argumentos de bench.py)
CONFIGS = {
    "calidad": ["--asr", "large-v3-turbo", "--asr-ct", "float16", "--mt", "opus-big", "--voice", "omnivoice", "--steps", "16"],
    "equilibrado": ["--asr", "large-v3-turbo", "--asr-ct", "int8_float16", "--mt", "opus-big", "--mt-ct", "int8_float16",
                    "--voice", "omnivoice", "--steps", "8"],
    "ligero": ["--asr", "small.en", "--asr-ct", "int8_float16", "--beam", "3", "--mt", "opus-base", "--mt-ct", "int8",
               "--voice", "omnivoice", "--steps", "8"],
    "texto": ["--asr", "large-v3-turbo", "--asr-ct", "int8_float16", "--mt", "opus-big", "--voice", "none"],
    "texto-ligero": ["--asr", "small.en", "--asr-ct", "int8", "--beam", "3", "--mt", "opus-base", "--mt-ct", "int8",
                     "--voice", "none"],
}


def run_one(lab_id: str, cfg_id: str, media: str, out: Path, limit_s: float) -> dict:
    lab = LABS[lab_id]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", TRANSLAY_LAB=json.dumps({"id": lab_id, **lab}))
    emulate = {}
    args = [sys.executable, str(ROOT / "tools" / "lab" / "bench.py"), media, *CONFIGS[cfg_id], "--out", str(out)]
    if limit_s:
        args += ["--limit-s", str(limit_s)]
    if lab.get("gpu") is False:
        env["CUDA_VISIBLE_DEVICES"] = ""  # el proceso de voz tampoco ve la GPU
        args += ["--device", "cpu"]
        emulate["gpu"] = False
    ballast = None
    g = gpus(0)
    if lab.get("vram_mb") and g:
        size = max(0, g[0]["vram_total_mb"] - lab["vram_mb"])
        ballast = subprocess.Popen([sys.executable, str(ROOT / "tools" / "lab" / "ballast.py"), str(size)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        got = ballast.stdout.readline().strip()
        emulate["vram_mb"] = lab["vram_mb"]
        print(f"  lastre de VRAM: {got} MB (quedan {lab['vram_mb']} MB de tarjeta)", flush=True)
    ram_cap = (lab["ram_mb"] - OS_MB) if lab.get("ram_mb") else None
    if lab.get("ram_mb"):
        emulate["ram_mb"] = lab["ram_mb"]
    if lab.get("threads"):
        emulate["threads"] = lab["threads"]
    env["TRANSLAY_EMULATE"] = json.dumps(emulate)
    job = Job(ram_mb=ram_cap, ram_mode="paging", threads=lab.get("threads"))
    t = time.time()
    p = subprocess.Popen(args, env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    job.add(p)
    log = p.communicate()[0]
    peak = job.peak_mb()
    job.close()
    if ballast:
        ballast.stdin.close()
        ballast.wait(15)
    try:
        res = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res = {"ok": False, "error": "el banco no terminó (¿sin memoria?)", "log": log[-1500:]}
    res.update(lab=lab_id, config_id=cfg_id, ram_peak_mb=peak, ram_cap_mb=ram_cap, runner_s=round(time.time() - t, 1))
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def summary(rows: list[dict]) -> str:
    head = "| lab | config | ok | velocidad | espera en vivo | VRAM pico | RAM pico / tope | WER | personas | error |\n" \
           "|---|---|---|---|---|---|---|---|---|---|\n"
    lines = []
    for r in rows:
        lines.append("| {lab} | {cfg} | {ok} | {sp} | {wait} | {vram} | {ram} | {wer} | {spk} | {err} |".format(
            lab=r["lab"], cfg=r["config_id"], ok="sí" if r.get("ok") else "no",
            sp=f"{r['speed']}×" if r.get("speed") else "—", wait=f"{r['wait_s']} s" if r.get("wait_s") is not None else "—",
            vram=f"{r['vram_peak_mb']} MB" if r.get("vram_peak_mb") is not None else "—",
            ram=f"{r.get('ram_peak_mb')} / {r.get('ram_cap_mb') or '—'} MB",
            wer=f"{r['wer'] * 100:.1f} %" if r.get("wer") is not None else "—",
            spk=f"{r['speakers_ok'] * 100:.0f} %" if r.get("speakers_ok") is not None else "—",
            err=(r.get("error") or "")[:60]))
    return head + "\n".join(lines) + "\n"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--labs", nargs="+", default=list(LABS))
    p.add_argument("--configs", nargs="+", default=list(CONFIGS))
    p.add_argument("--media", default=str(ROOT / "samples" / "podcast.mp4"))
    p.add_argument("--limit-s", type=float, default=0, help="procesar solo los primeros N segundos del video")
    p.add_argument("--name", default=datetime.now().strftime("%Y%m%d-%H%M"))
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    if a.list:
        for k, v in LABS.items():
            print(f"{k:12} {v['name']}")
        print("\nconfiguraciones:", ", ".join(CONFIGS))
        return
    outdir = ROOT / "data" / "labs" / a.name
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for lab_id in a.labs:
        for cfg_id in a.configs:
            if LABS[lab_id].get("gpu") is False and cfg_id in ("calidad", "equilibrado"):
                pass  # en CPU también se miden (para saber cuánto tarda de verdad)
            print(f"→ {lab_id} · {cfg_id}", flush=True)
            r = run_one(lab_id, cfg_id, a.media, outdir / f"{lab_id}__{cfg_id}.json", a.limit_s)
            print(f"  {'ok' if r.get('ok') else 'falló'} · velocidad {r.get('speed')}× · espera {r.get('wait_s')} s · "
                  f"VRAM {r.get('vram_peak_mb')} MB · RAM {r.get('ram_peak_mb')} MB {r.get('error') or ''}", flush=True)
            rows.append(r)
            (outdir / "resumen.md").write_text(summary(rows), encoding="utf-8")
    print("\n" + summary(rows))


if __name__ == "__main__":
    main()
