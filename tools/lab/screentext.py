"""Laboratorio del texto en pantalla (vt/screentext.py, vt/textkind.py) con videos reales.

  python tools/lab/screentext.py                 baja los tramos que falten y los lee todos
  python tools/lab/screentext.py --only fire-py  solo esos (por nombre)
  python tools/lab/screentext.py --sheets 8      además, 8 hojas de revisión por video

Escenarios: programación (código, comandos, comentarios), charlas con diapositivas, clases,
marketing con mucho texto que cambia rápido (tipografía cinética) y explicativos animados.
Se baja solo un tramo de cada video (720p, H.264) a data/labs/screentext/videos/.

Salida en data/labs/screentext/out/<nombre>/:
  items.json     cada elemento con su tipo, tiempo, caja y lectura
  kinds.txt      los renglones agrupados por tipo, para revisar a ojo qué se tradujo y qué no
  sheet-NN.png   cuadros con las cajas pintadas por tipo (azul texto, verde comentario, rojo código,
                 naranja comando, violeta enlace) y su número en kinds.txt
  stats.json     tiempo de CPU frente al tiempo de video, cuadros leídos y reutilizados
"""

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt import screentext, textkind  # noqa: E402
from vt.ocr import OCR  # noqa: E402

LAB = ROOT / "data" / "labs" / "screentext"
# nombre → (id de YouTube, desde, hasta, escenario)
VIDEOS = {
    "talk-agents": ("pz74r-4dGfQ", 240, 480, "charla técnica con diapositivas y código"),
    "fire-py": ("x7X9w_GIm1s", 0, 144, "programación rápida: código y texto (Fireship)"),
    "fire-docker": ("Gjnup-PuquQ", 0, 127, "comandos y código (Fireship)"),
    "vscode-py": ("6i3e-j3wSf0", 150, 330, "editor VS Code, curso de Python"),
    "linux-cmds": ("gd7BXuUQ91w", 60, 240, "terminal: muchos comandos"),
    "slides-mck": ("HnlWiVs9P5o", 60, 240, "diapositivas de consultoría con mucho texto"),
    "econ": ("o6UXRZ2XwgU", 300, 480, "clase explicativa de economía"),
    "mit-lecture": ("_OkTw766oCs", 600, 780, "clase con pizarrón (MIT)"),
    "funnel": ("jQjOD579jhI", 0, 149, "marketing: embudo explicado"),
    "kinetic-grow": ("VpTlfD5gqlg", 0, 25, "marketing en tipografía cinética (texto rápido)"),
    "kinetic-brand": ("TDC7eVrkduY", 0, 37, "marca en tipografía cinética"),
    "explainer-16": ("k0OmnkE6f4E", 0, 185, "16 estilos de video explicativo (marketing)"),
    "ted-vitamins": ("ISZLTJH5lYg", 0, 150, "animación educativa (TED-Ed)"),
    # retos: texto y código mezclados, sintaxis que parece prosa, prosa que parece código
    "jupyter-md": ("uVLzL5E-YBM", 60, 240, "reto: Jupyter con celdas de Markdown (#, *, listas) y código"),
    "regex": ("sXQxhojSdZM", 0, 142, "reto: expresiones regulares (símbolos sin palabras)"),
    "html": ("salY_Sm6mv4", 30, 210, "reto: HTML con texto dentro de etiquetas"),
    "compose": ("Qw9zlE3t8Ko", 120, 300, "reto: YAML de Docker Compose (clave: valor parece texto)"),
    "traceback": ("g9O9j34Vxww", 60, 240, "reto: trazas de error (prosa dentro de la terminal)"),
    "excel": ("xIynD1gFOLo", 60, 240, "reto: fórmulas de Excel y celdas con texto"),
    "sql": ("kbKty5ZVKMY", 120, 300, "reto: SQL (palabras clave en inglés común)"),
    "git": ("rE2zRhZdjFU", 120, 300, "reto: git en la terminal (salida con mensajes en prosa)"),
    "3b1b": ("fNk_zzaMoSs", 60, 240, "reto: matemáticas animadas (fórmulas y palabras sueltas)"),
    # vuelta 7: noticias, presentaciones, demos de producto
    "news-gfx": ("1mqz2tOI2tY", 0, 107, "reto: gráficos de noticias (zócalos, cintillo, reloj)"),
    "slides-dos": ("tEF2vNP3S9A", 0, 180, "clase sobre diapositivas (viñetas, ejemplos buenos y malos)"),
    "saas-demo": ("NqfVmc8wrlU", 30, 210, "demo de un producto SaaS (interfaz de una app web)"),
    "bullets-ppt": ("Ksvrn0VqOOY", 60, 240, "reto: armar viñetas en PowerPoint (interfaz de Office y texto)"),
}
COLORS = {"text": (40, 120, 255), "comment": (30, 170, 60), "code": (230, 40, 40), "command": (245, 140, 0),
          "link": (150, 60, 220), "email": (150, 60, 220)}


def fetch(name: str) -> Path:
    vid, a, b, _ = VIDEOS[name]
    out = LAB / "videos" / f"{name}.mp4"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "-f",
           "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720]", "--merge-output-format", "mp4",
           "--download-sections", f"*{a}-{b}", "-o", str(out),
           f"https://www.youtube.com/watch?v={vid}"]
    subprocess.run(cmd, check=True, timeout=900)
    return out


def sheets(path: Path, items: list[dict], out: Path, n: int):
    """Cuadros con las cajas de lo que había en pantalla, pintadas por tipo y numeradas."""
    import av
    from PIL import Image, ImageDraw

    if not items or n <= 0:
        return
    ends = max(it["end"] for it in items)
    # los momentos con más elementos a la vez, repartidos en el video
    marks = sorted({round(it["start"] + min(1.0, (it["end"] - it["start"]) / 2), 1) for it in items})
    step = max(1, len(marks) // n)
    times = marks[::step][:n]
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        for k, t in enumerate(times):
            c.seek(int(max(0, t - 2) / s.time_base), stream=s)
            fr = next((f for f in c.decode(s) if f.time is not None and f.time >= t), None)
            if fr is None or t > ends:
                continue
            img = fr.to_image()
            d = ImageDraw.Draw(img)
            for it in items:
                if it["start"] <= t < it["end"]:
                    x, y, w, h = it["box"]
                    W, H = img.size
                    col = COLORS.get(it["kind"], (128, 128, 128))
                    d.rectangle([x * W, y * H, (x + w) * W, (y + h) * H], outline=col, width=3)
                    d.text((x * W + 2, max(0, y * H - 12)), f"{it['id']}", fill=col)
            img.save(out / f"sheet-{k:02d}.png")


def run(name: str, ocr, n_sheets: int) -> dict:
    path = fetch(name)
    out = LAB / "out" / name
    out.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    t0 = time.perf_counter()
    cpu0 = time.process_time()

    def emit(found, upto):
        items.extend(found)
    screentext.scan(path, ocr, emit=emit)
    wall, cpu = time.perf_counter() - t0, time.process_time() - cpu0
    for i, it in enumerate(sorted(items, key=lambda x: (x["start"], x["box"][1]))):
        it["id"] = i
    items.sort(key=lambda x: x["id"])
    import av

    with av.open(str(path)) as c:
        dur = float(c.duration or 0) / 1e6
    kinds = Counter(it["kind"] for it in items)
    stats = {"name": name, "scenario": VIDEOS[name][3], "video_s": round(dur, 1), "wall_s": round(wall, 1),
             "cpu_s": round(cpu, 1), "x_realtime": round(dur / wall, 2) if wall else None,
             "items": len(items), "kinds": dict(kinds)}
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = []
    for k in [k for k in textkind.KINDS if k != "noise"]:
        sel = [it for it in items if it["kind"] == k]
        if not sel:
            continue
        lines.append(f"== {textkind.KINDS[k].label} ({len(sel)})")
        for it in sel:
            txt = it["text"].replace("\n", " ⏎ ")
            lines.append(f"  #{it['id']:<4} {it['start']:7.2f}-{it['end']:7.2f} [{it['conf']:.2f}] {txt}")
    (out / "kinds.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sheets(path, items, out, n_sheets)
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="nombres de VIDEOS")
    ap.add_argument("--sheets", type=int, default=6, help="hojas de revisión por video")
    ap.add_argument("--threads", type=int, default=3, help="hilos del OCR (en la app: un cuarto del equipo)")
    a = ap.parse_args()
    ocr = OCR(a.threads)
    rows = []
    for name in a.only or VIDEOS:
        try:
            st = run(name, ocr, a.sheets)
        except Exception as e:  # noqa: BLE001 — un video que falla no frena a los demás
            print(f"{name}: falló ({e})", flush=True)
            continue
        rows.append(st)
        print(f"{name:14} {st['video_s']:6.0f} s de video en {st['wall_s']:5.0f} s ({st['x_realtime']}x) · "
              f"{st['items']} elementos {st['kinds']}", flush=True)
    (LAB / "out" / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
