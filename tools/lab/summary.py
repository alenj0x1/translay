"""Lab del resumen: cada modelo candidato sobre transcripciones reales.

Mide tiempo, pico de VRAM (nvidia-smi) o de RAM (en la CPU), cuántos puntos salen por
minuto de video, si el texto quedó en español y si los minutos son de frases reales.
Guarda cada resumen en data/labs/summary/out/<modelo>/<video>.json para leerlo a mano.

    python tools/lab/summary.py                       # todos los modelos en la GPU
    python tools/lab/summary.py --device cpu --models qwen3-1.7b qwen3-0.6b
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt import summarize  # noqa: E402

LAB = ROOT / "data" / "labs" / "summary"
# videos del lab: clase del MIT (43 min, inglés), TED (14 min, inglés), comedia (12 min, portugués),
# charla (16 min, español) y uno corto (4 min, inglés)
VIDEOS = [
    (LAB / "nykOeWgQcHM.json", "1. What is Computation? (MIT 6.0001)"),
    (LAB / "arj7oStGLkU.json", "Inside the Mind of a Master Procrastinator | Tim Urban | TED"),
    (ROOT / "data/libraries/comedia/transcripts/yt_vvThhk2btO8.json", ""),
    (ROOT / "data/libraries/tiffany/transcripts/cap_a5f9d1d8ab518eebf2814f74.json", ""),
    (ROOT / "data/transcripts/yt_qVr_3bE1JwQ.json", ""),
]
EXTRA = {"gemma3-4b": summarize.Model("Gemma 3 4B", "gemma", "jncraton/gemma-3-4b-it-ct2-int8", False, 0, 0, "Gemma")}
ES = {"el", "la", "de", "que", "en", "los", "las", "un", "una", "se", "del", "por", "con", "para", "es", "y"}
EN = {"the", "of", "and", "to", "is", "in", "that", "it", "for", "with", "this", "on"}


def vram_used() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.split()[0])


def rss_mb() -> int:
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)] + \
                   [(f"x{i}", ctypes.c_size_t) for i in range(6)]
    c = PMC()
    c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.PeakWorkingSetSize // 2**20


def spanish(text: str) -> float:
    w = re.findall(r"[a-záéíóúñü]+", text.lower())
    es, en = sum(x in ES for x in w), sum(x in EN for x in w)
    return round(es / max(1, es + en), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=[*summarize.ORDER, *EXTRA])
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--videos", type=int, default=len(VIDEOS))
    a = ap.parse_args()
    results = []
    for key in a.models:
        if key in EXTRA:
            summarize.MODELS[key] = EXTRA[key]
        s = summarize.Summarizer(key, a.device, threads=os.cpu_count() // 2)
        base = vram_used() if a.device == "cuda" else 0
        peak = [0]
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                peak[0] = max(peak[0], vram_used() - base)
                time.sleep(0.3)
        if a.device == "cuda":
            threading.Thread(target=watch, daemon=True).start()
        t = time.perf_counter()
        s.load()
        load_s = time.perf_counter() - t
        for path, title in VIDEOS[:a.videos]:
            d = json.loads(path.read_text(encoding="utf-8"))
            segs = d["segments"]
            lang = d.get("lang") or "en"
            dur = segs[-1]["end"] / 60
            t = time.perf_counter()
            r = s.summarize(segs, lang, title)
            secs = time.perf_counter() - t
            out = LAB / "out" / f"{key}-{a.device}" / f"{path.stem}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            row = {"model": key, "device": a.device, "video": path.stem, "lang": lang, "min": round(dur, 1),
                   "seconds": round(secs, 1), "points": len(r["points"]),
                   "points_per_10min": round(len(r["points"]) / dur * 10, 1),
                   "spanish": spanish(r["overview"] + " " + " ".join(p["text"] for p in r["points"])),
                   "overview_words": len(r["overview"].split())}
            print(json.dumps(row, ensure_ascii=False), flush=True)
            results.append(row)
        stop.set()
        mem = peak[0] if a.device == "cuda" else rss_mb()
        print(json.dumps({"model": key, "device": a.device, "load_s": round(load_s, 1), "peak_mb": mem}), flush=True)
        results.append({"model": key, "device": a.device, "load_s": round(load_s, 1), "peak_mb": mem})
        s.unload()
    with open(LAB / f"results-{a.device}.jsonl", "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
