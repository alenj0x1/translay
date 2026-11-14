"""Biblioteca de demostración: muchos videos con miniaturas cuidadas, canales con avatar y banner, categorías y
colecciones, para probar la interfaz con contenido de verdad y tomar capturas que se vean bien.

  python tools/demo_library.py --data <carpeta de datos de prueba> --from <id de un video ya procesado>

Usa un video ya procesado de esa carpeta (su archivo, su miniatura y su transcripción) como base de cada video
nuevo: todos se pueden abrir y reproducir. Las miniaturas, avatares y banners se dibujan aquí (colores planos,
formas simples y el título; nada de degradados). No toca una biblioteca real: escribe en la carpeta que le pasas y
guarda una copia de library.json antes (library.json.antes-demo).
"""

import argparse
import json
import random
import re
import shutil
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_SEMI = r"C:\Windows\Fonts\seguisb.ttf"

# canal, categoría (de YouTube), color de fondo, color de las formas, color del texto, forma, títulos
CHANNELS = [
    ("Cocina Fácil", "Howto & Style", "#2f3a2c", "#a9c98f", "#f4f1e8", "circle",
     ["Pan casero en una hora", "Tres salsas que salvan cualquier plato", "El arroz perfecto, paso a paso",
      "Cómo afilar un cuchillo", "Postres sin horno", "Caldo base para toda la semana"]),
    ("Código Claro", "Science & Technology", "#1d2433", "#7aa2f7", "#e8ecf7", "brackets",
     ["Python desde cero: variables", "Git sin miedo", "Tu primera API en 20 minutos",
      "Depurar como un profesional", "Expresiones regulares explicadas", "SQL para no programadores"]),
    ("Historia en 10", "Education", "#3a2a24", "#e0a36b", "#f6ece2", "arch",
     ["La caída de Constantinopla", "Cómo se construyó Machu Picchu", "La imprenta cambió el mundo",
      "La Ruta de la Seda", "El año sin verano", "Los mapas que mintieron"]),
    ("Ciencia de Bolsillo", "Science & Technology", "#22313a", "#7fd1c7", "#e6f4f2", "orbit",
     ["Por qué el cielo es azul", "Cómo funciona una vacuna", "El tamaño real del universo",
      "Qué es la entropía", "La física de una bicicleta", "Los colores que no existen"]),
    ("Viajes Lentos", "Travel & Events", "#2d2a3e", "#c3a6e8", "#f1ecf8", "mountain",
     ["Japón en tren", "Una semana en Oaxaca", "Islandia en invierno", "Lisboa caminando",
      "La Patagonia sin prisa", "Marruecos: del desierto al mar"]),
    ("Música Teórica", "Music", "#3a2432", "#f0a6c5", "#f8eaf1", "wave",
     ["Por qué una canción te emociona", "Escalas en cinco minutos", "El ritmo explicado con palmas",
      "Armonía para principiantes", "Cómo se mezcla una canción", "La historia del sintetizador"]),
]
COLLECTIONS = [("Para el fin de semana", [0, 8, 26, 27]), ("Aprender a programar", [6, 7, 8, 9, 10, 11]),
               ("Recetas por probar", [0, 1, 2, 4]), ("Favoritos", [12, 18, 24, 30, 33])]


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def shape(d: ImageDraw.ImageDraw, kind: str, W: int, H: int, col: str, seed: int):
    r = random.Random(seed)
    if kind == "circle":
        R = int(H * r.uniform(0.55, 0.7))
        d.ellipse([W - R - int(W * 0.04), H - R - int(H * 0.08), W + int(R * 0.35), H + int(R * 0.35)], fill=col)
        d.ellipse([int(W * 0.72), int(H * 0.1), int(W * 0.8), int(H * 0.24)], fill=col)
    elif kind == "brackets":
        w = int(H * 0.06)
        for x0, flip in ((int(W * 0.66), 1), (int(W * 0.88), -1)):
            pts = [(x0 + flip * int(H * 0.12), int(H * 0.22)), (x0, int(H * 0.5)), (x0 + flip * int(H * 0.12), int(H * 0.78))]
            d.line(pts, fill=col, width=w, joint="curve")
        d.rounded_rectangle([int(W * 0.74), int(H * 0.47), int(W * 0.8), int(H * 0.53)], 6, fill=col)
    elif kind == "arch":
        x0, x1 = int(W * 0.62), int(W * 0.94)
        d.rounded_rectangle([x0, int(H * 0.3), x1, H + 40], 999, fill=col)
        d.rectangle([x0 + int((x1 - x0) * 0.3), int(H * 0.55), x1 - int((x1 - x0) * 0.3), H], fill=None, outline=None)
    elif kind == "orbit":
        cx, cy, R = int(W * 0.8), int(H * 0.48), int(H * 0.3)
        d.ellipse([cx - R, cy - R // 3, cx + R, cy + R // 3], outline=col, width=int(H * 0.025))
        d.ellipse([cx - R // 3, cy - R // 3, cx + R // 3, cy + R // 3], fill=col)
        d.ellipse([cx + R - 14, cy - 14, cx + R + 14, cy + 14], fill=col)
    elif kind == "mountain":
        base = H + 10
        d.polygon([(int(W * 0.5), base), (int(W * 0.72), int(H * 0.28)), (int(W * 0.95), base)], fill=col)
        d.polygon([(int(W * 0.7), base), (int(W * 0.86), int(H * 0.45)), (W + 40, base)], fill=col)
        d.ellipse([int(W * 0.84), int(H * 0.1), int(W * 0.92), int(H * 0.24)], fill=col)
    elif kind == "wave":
        n, bw = 7, int(W * 0.03)
        for i in range(n):
            h = int(H * (0.18 + 0.5 * abs(((i * 37 + seed) % 10) / 10)))
            x = int(W * 0.6) + i * int(bw * 1.7)
            d.rounded_rectangle([x, H // 2 - h // 2, x + bw, H // 2 + h // 2], bw // 2, fill=col)


def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + [cur] if cur else lines


def thumb(path: Path, title: str, ch: tuple, seed: int):
    name, _, bg, fg, ink, kind, _ = ch
    W, H = 1280, 720
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    shape(d, kind, W, H, fg, seed)
    f = font(FONT_BOLD, 76)
    lines = wrap(d, title, f, int(W * 0.56))[:3]
    y = H // 2 - len(lines) * 46
    for ln in lines:
        d.text((int(W * 0.07), y), ln, font=f, fill=ink)
        y += 92
    d.text((int(W * 0.07), int(H * 0.1)), name.upper(), font=font(FONT_SEMI, 30), fill=fg)
    im.resize((640, 360), Image.LANCZOS).save(path, quality=88)


def channel_art(folder: Path, ch: tuple):
    name, _, bg, fg, ink, kind, _ = ch
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "x"
    av = Image.new("RGB", (240, 240), fg)
    d = ImageDraw.Draw(av)
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    f = font(FONT_BOLD, 100)
    d.text((120, 120), initials, font=f, fill=bg, anchor="mm")
    av.save(folder / f"{slug}_avatar.jpg", quality=90)
    W, H = 2048, 340
    bn = Image.new("RGB", (W, H), bg)
    shape(ImageDraw.Draw(bn), kind, W, H, fg, 7)
    bn.save(folder / f"{slug}_banner.jpg", quality=88)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True, help="carpeta de datos de prueba (la del servidor de pruebas)")
    ap.add_argument("--from", dest="base", required=True, help="id de un video ya procesado que sirve de base")
    a = ap.parse_args()
    data = Path(a.data)
    lib_file = data / "library.json"
    lib = json.loads(lib_file.read_text(encoding="utf-8"))
    shutil.copy2(lib_file, data / "library.json.antes-demo")
    # se puede correr de nuevo: lo de una demo anterior se reemplaza
    lib["videos"] = {k: v for k, v in lib["videos"].items() if not k.startswith("demo0")}
    lib["collections"] = [c for c in lib["collections"] if not c["id"].startswith("demo-")]
    base = lib["videos"][a.base]
    media = data / "library" / Path(base["media"]).name
    tr_base = json.loads((data / "transcripts" / f"{a.base}.json").read_text(encoding="utf-8"))
    chan_dir = data / "youtube" / "channels"
    chan_dir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(7)
    now = time.time()
    ids = []
    n = 0
    for ch in CHANNELS:
        channel_art(chan_dir, ch)
        for title in ch[6]:
            vid = f"demo{n:04d}"
            ids.append(vid)
            shutil.copy2(media, data / "library" / f"{vid}.mp4")
            thumb(data / "library" / f"{vid}.jpg", title, ch, n)
            dur = rnd.choice([312, 488, 605, 734, 921, 1145, 1388, 1712])
            # la transcripción del video base, estirada a la duración inventada: así cuenta como traducida y doblada
            # completa (sin «Doblado 2 %» en las tarjetas)
            k = dur / max(1e-6, base.get("duration") or 1)
            segs = [dict(sg, start=round(sg["start"] * k, 2), end=round(sg["end"] * k, 2)) for sg in tr_base["segments"]]
            # lo reconocido también: el avance se mide por el tiempo cubierto, no por las frases
            covered = [[round(x * k, 2), round(y * k, 2)] for x, y in tr_base.get("covered") or []] or [[0, dur]]
            # la voz doblada de cada frase, copiada a la carpeta del video: no depende de que el video base siga
            # (si se borra, la demo no queda pidiendo audios que ya no están)
            for sg in segs:
                d = sg.get("dub")
                if d and d.get("file"):
                    src = data / "audio" / d["file"]
                    if src.exists():
                        (data / "audio" / vid).mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, data / "audio" / vid / src.name)
                        sg["dub"] = dict(d, file=f"{vid}/{src.name}")
            tr = dict(tr_base, id=vid, name=title, segments=segs, covered=covered)
            tr.pop("summary", None)  # el resumen del video base hablaría de otra cosa
            (data / "transcripts" / f"{vid}.json").write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
            watched = rnd.random() < 0.35
            lib["videos"][vid] = {
                "id": vid, "title": title, "source": "youtube", "channel": ch[0], "categories": [ch[1]],
                "duration": dur, "media": f"/media/lib/{vid}.mp4", "thumb": f"/media/lib/{vid}.jpg",
                "lang": "en", "mode": "translate", "progress": {"asr": 1.0, "dub": 1.0},
                "added": now - n * 3600 * rnd.uniform(2, 9), "opened": now - n * 1800 if watched else 0,
                "position": round(dur * rnd.uniform(0.15, 0.8), 1) if watched else 0,
                "url": f"https://www.youtube.com/watch?v=demo{n:07d}",
            }
            n += 1
    for name, idx in COLLECTIONS:
        lib["collections"].append({"id": f"demo-{re.sub(r'[^a-z]+', '-', name.lower())}", "name": name,
                                   "items": [ids[i] for i in idx if i < len(ids)], "created": now})
    lib_file.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{n} videos, {len(CHANNELS)} canales, {len(COLLECTIONS)} colecciones en {data}")


if __name__ == "__main__":
    main()
