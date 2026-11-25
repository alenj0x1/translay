"""Datos de prueba para las pruebas de punta a punta: una carpeta de datos nueva, armada con el mismo código del
servidor (vt.vaults, vt.store), sin depender de videos privados ni de la red.

  Principal  3 videos (uno con dos personas), privada
  Pública    2 videos, pública con permiso «ver»
  Abierta    1 video, pública con permiso «importar»

Cada video es un clip corto generado con ffmpeg (imagen de prueba y un tono), con su miniatura y una transcripción
traducida (procesado entero, salvo el segundo de cada biblioteca, que queda a medias). Las frases dobladas no tienen audio propio: el reproductor usa el original (lo que importa aquí es la
interfaz y los permisos, no la voz).

    python tests/e2e/fixture.py <carpeta>
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LINES = [
    ("Welcome to the kitchen.", "Bienvenido a la cocina."),
    ("Today we make bread at home.", "Hoy hacemos pan en casa."),
    ("First, mix the flour and the water.", "Primero, mezcla la harina y el agua."),
    ("Let it rest for one hour.", "Déjalo reposar una hora."),
    ("Then bake it until it is golden.", "Luego hornéalo hasta que esté dorado."),
]
LIBRARIES = [
    # (id esperado, nombre, acceso, permiso, videos)
    ("principal", "Principal", "privada", "ver", [("e2emain0001", "Pan casero"), ("e2emain0002", "Salsas rápidas"),
                                                   ("e2emain0003", "Charla de dos personas")]),
    ("publica", "Pública", "publica", "ver", [("e2epub00001", "Video público uno"), ("e2epub00002", "Video público dos")]),
    ("abierta", "Abierta", "publica", "importar", [("e2eopen0001", "Video para importar")]),
]
SECONDS = 12


def clip(out: Path, seconds: int, freq: int):
    if out.exists():
        return
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-c:v", "libx264", "-preset",
                    "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True)


def thumb(src: Path, out: Path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2", "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2",
                    str(out)], check=True)


def build(data: Path, cache: Path | None = None) -> dict:
    """cache: carpeta donde quedan los clips generados para la próxima vez (se copian a la biblioteca)."""
    import shutil

    from vt.vaults import Vaults

    data.mkdir(parents=True, exist_ok=True)
    (data / "prefs.json").write_text(json.dumps({"welcomed": True, "import_mode": "descargar", "theme_mode": "claro"}),
                                     encoding="utf-8")
    vaults = Vaults(data)
    made = {}
    for n, (want, name, mode, perm, videos) in enumerate(LIBRARIES):
        v = vaults.main if want == "principal" else vaults.create(name)
        assert v.id == want, (v.id, want)
        if mode != "privada":
            v.meta["access"] = {"mode": mode, "perm": perm}
            v.save_meta()
        lib_dir = v.root / "library"
        lib_dir.mkdir(parents=True, exist_ok=True)
        for k, (vid, title) in enumerate(videos):
            media = lib_dir / f"{vid}.mp4"
            src = (cache or lib_dir) / f"{vid}.mp4"
            src.parent.mkdir(parents=True, exist_ok=True)
            clip(src, SECONDS, 300 + 80 * (n * 3 + k))
            if src != media:
                shutil.copyfile(src, media)
            thumb(media, lib_dir / f"{vid}.jpg")
            v.library.register(vid, title=title, duration=float(SECONDS), source="file", media=f"/media/lib/{vid}.mp4",
                               thumb=f"/media/lib/{vid}.jpg")
            tr = v.store.open(vid, f"{vid}.mp4")
            tr.set_lang("en")
            for i, (en, es) in enumerate(LINES):
                seg, _ = tr.add_segment(i * 2.2 + 0.3, i * 2.2 + 2.1, en, es, "fixture")
                seg["speaker"] = i % 2 if "dos personas" in title else 0
            if k != 1:
                tr.add_covered(0.0, float(SECONDS))  # procesado entero (el segundo de cada biblioteca queda a medias)
            else:
                tr.add_covered(0.0, 4.0)  # a medias: lo que falta solo lo procesa la cola del dueño
            tr.save()
            if vid == "e2emain0001":  # un fondo separado (vt/separation.py): lo que el reproductor hace sonar doblado
                bg = v.root / "audio" / vid / "fondo.m4a"
                bg.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=180:duration={SECONDS}",
                                "-ac", "2", "-c:a", "aac", str(bg)], check=True)
                v.library.set_field(vid, bg=f"/audio/{vid}/fondo.m4a")
                # y su voz doblada en cada frase: sin ella el original no calla (falta voz donde iría)
                for seg in tr.segments:
                    name = f"{seg['id']}.{tr.target}.wav"
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=520:duration=1.6",
                                    "-ar", "24000", "-ac", "1", str(bg.parent / name)], check=True)
                    seg["dub"] = {"file": f"{vid}/{name}", "dur": 1.6, "rate": 1.0, "voice": seg.get("speaker")}
                tr.save()
            made.setdefault(v.id, []).append(vid)
    return made


if __name__ == "__main__":
    print(json.dumps(build(Path(sys.argv[1])), indent=1))
