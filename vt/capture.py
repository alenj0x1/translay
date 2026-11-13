"""Grabaciones de pantalla que llegan por partes (web/js/capture.js).

El navegador graba con MediaRecorder y guarda cada parte (1 s de WebM) en
IndexedDB antes de subirla; la borra cuando el servidor la confirma. Así, si se
corta la red, se cae el servidor o se cierra la pestaña, lo grabado sigue en el
equipo y se retoma desde lo confirmado.

Subida (PUT /api/capture/<id>/<n>): el servidor solo agrega la parte que sigue.
  n == siguiente   se agrega, se fuerza a disco y responde 200 «next=n+1»
  n <  siguiente   ya estaba (reintento): 200 con la siguiente esperada
  n >  siguiente   falta una anterior: 409 con la siguiente esperada
Terminar (PUT /api/capture/<id>/end?parts=N&q=media&fps=30&crop=x,y,w,h&sizes=WxH,…&title=…):
con las N partes recibidas arma el archivo final en la biblioteca y lo registra.
Repetirlo (la red se cortó mientras convertía) espera la misma conversión o
responde que ya está.

<biblioteca>/library/captures/<id>.webm.part   lo recibido
<biblioteca>/library/captures/<id>.json        {"next": n, "bytes": b, "done": archivo}

Si lo que se graba cambia de tamaño a mitad (se pasa de compartir un celular a una
pantalla), `sizes` trae los tamaños que tuvo: el video final usa un lienzo que entra a
todos (el alto de la calidad y el ancho del más ancho) y cada parte se ajusta dentro sin
deformarse, con franjas negras donde sobra. La zona elegida se descarta en ese caso (la
interfaz no la manda: ya no corresponde a la nueva fuente).

El archivo final se comprime en la CPU según la calidad elegida (QUALITY): H.264
con calidad constante (CRF) y un tope de tasa, recortado a la zona y escalado a
la altura de la calidad; «Solo audio» queda en M4A. El tope es el que usa la
interfaz para estimar el peso: una pantalla con poco movimiento pesa bastante menos.
"""

import asyncio
import os
import re
import subprocess
from pathlib import Path

from .jsonio import read_json, write_json

ID_RE = re.compile(r"cap_[A-Za-z0-9]{8,64}")
MAX_PART = 32 << 20  # 1 s de video nunca llega a esto
CONVERT_ERR = "No se pudo armar el video de la grabación"
# altura máxima y tope de video (kbit/s) a 30 cuadros; a 15 cuadros, 2/3 del tope.
# Mismos valores en web/js/capture.js (estimación del peso)
QUALITY = {"alta": (1080, 4000), "media": (720, 2000), "ligera": (480, 900), "audio": (0, 0)}
AUDIO_KBPS = {"audio": 96}  # el resto: 128
# ffmpeg con la mitad del equipo: la app sigue respondiendo mientras comprime
THREADS = max(1, (os.cpu_count() or 2) // 2)


def parse_crop(s: str) -> tuple[int, int, int, int] | None:
    """«x,y,w,h» en píxeles del video; pares (H.264 lo exige) y de al menos 16 px."""
    try:
        x, y, w, h = (max(0, int(float(v))) for v in s.split(","))
    except ValueError:
        return None
    x, y, w, h = x & ~1, y & ~1, w & ~1, h & ~1
    return (x, y, w, h) if w >= 16 and h >= 16 else None


def parse_sizes(s: str) -> list[tuple[int, int]]:
    """«WxH,WxH…»: los tamaños que tuvo la fuente durante la grabación (sin repetir, hasta 16)."""
    out: list[tuple[int, int]] = []
    for part in (s or "").split(",")[:16]:
        try:
            w, h = (int(float(v)) for v in part.lower().split("x"))
        except ValueError:
            continue
        if 16 <= w <= 16384 and 16 <= h <= 16384 and (w, h) not in out:
            out.append((w, h))
    return out


def canvas(sizes: list[tuple[int, int]], height: int) -> tuple[int, int] | None:
    """Lienzo para una fuente que cambió de tamaño (o None si no cambió de forma): el alto de la
    calidad (sin pasar del más alto) y el ancho que necesita la más ancha a ese alto. Lados pares."""
    if len(sizes) < 2:
        return None
    ratios = [w / h for w, h in sizes]
    if max(ratios) / min(ratios) < 1.05 and max(h for _, h in sizes) / min(h for _, h in sizes) < 1.3:
        return None  # casi lo mismo (una ventana que se acomodó): como siempre
    h = min(height, max(hh for _, hh in sizes)) // 2 * 2
    w = int(h * max(ratios)) // 2 * 2
    return min(w, 7680), h


def parse_opts(query: dict) -> dict:
    q = query.get("q", "media")
    return {"quality": q if q in QUALITY else "media", "fps": 15 if query.get("fps") == "15" else 30,
            "crop": parse_crop(query.get("crop", "")), "sizes": parse_sizes(query.get("sizes", ""))}


def out_ext(quality: str) -> str:
    return "m4a" if quality == "audio" else "mp4"


def video_kbps(quality: str, fps: int) -> int:
    kbps = QUALITY[quality][1]
    return kbps if fps >= 30 else kbps * 2 // 3


def convert_cmd(src: Path, out: Path, quality: str, fps: int, crop, sizes=None) -> list[str]:
    cmd = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-threads", str(THREADS), "-i", str(src)]
    akbps = AUDIO_KBPS.get(quality, 128)
    if quality == "audio":
        return cmd + ["-vn", "-c:a", "aac", "-b:a", f"{akbps}k", "-movflags", "+faststart", "-f", "mp4", str(out)]
    height, kbps = QUALITY[quality][0], video_kbps(quality, fps)
    vf = []
    box = canvas(sizes or [], height)
    if box:
        # la fuente cambió de forma: cada tramo, entero y centrado en el mismo lienzo (ffmpeg rearma
        # los filtros con cada tamaño nuevo, así el ajuste se recalcula)
        w, h = box
        vf += [f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2",
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black", "setsar=1", f"fps={fps}"]
        return cmd + ["-vf", ",".join(vf), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                      "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p",
                      "-c:a", "aac", "-b:a", f"{akbps}k", "-movflags", "+faststart", "-f", "mp4", str(out)]
    if crop:
        x, y, w, h = crop
        # la fuente puede achicarse a mitad de la grabación (una ventana): la zona se ajusta a lo que hay
        vf.append(f"crop=w='min({w}\\,iw)':h='min({h}\\,ih)':x='min({x}\\,iw-ow)':y='min({y}\\,ih-oh)'")
    # nunca más grande que lo grabado; lados pares (H.264)
    vf += [f"scale=-2:'min({height}\\,trunc(ih/2)*2)'", f"fps={fps}"]
    return cmd + ["-vf", ",".join(vf), "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                  "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", f"{akbps}k", "-movflags", "+faststart", "-f", "mp4", str(out)]


def probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def probe_sizes(path: Path) -> list[tuple[int, int]]:
    """Tamaños que tiene el video a lo largo del archivo, mirando solo los cuadros clave (rápido
    aun con una hora de grabación). Respaldo de `sizes`: una grabación retomada no lo trae."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                            "-show_entries", "frame=width,height", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_sizes(",".join(line.strip().strip(",").replace(",", "x") for line in r.stdout.split() if line.strip()))


def make_thumb(media: Path, out: Path, duration: float):
    """Fotograma al 10 % (máx. 30 s), como las miniaturas de los archivos importados."""
    t = min(30.0, duration * 0.1)
    subprocess.run(["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(media),
                    "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)],
                   capture_output=True, timeout=120, check=True)


class Captures:
    def __init__(self, folder_of):
        self.folder_of = folder_of  # (id, biblioteca) → carpeta library/ de esa biblioteca
        self._locks: dict[str, asyncio.Lock] = {}
        self._finishing: dict[str, asyncio.Task] = {}

    def _paths(self, cid: str, lib: str | None) -> tuple[Path, Path, Path]:
        d = self.folder_of(cid, lib) / "captures"
        d.mkdir(parents=True, exist_ok=True)
        return d, d / f"{cid}.webm.part", d / f"{cid}.json"

    def _state(self, meta: Path) -> dict:
        return read_json(meta, None) or {"next": 0, "bytes": 0}

    async def part(self, cid: str, seq: int, body, lib: str | None) -> tuple[int, str]:
        data = b""
        async for c in body:
            data += c
            if len(data) > MAX_PART:
                return 413, "parte demasiado grande"
        async with self._locks.setdefault(cid, asyncio.Lock()):
            _, part, meta = self._paths(cid, lib)
            st = self._state(meta)
            if st.get("done"):
                return 200, f"next={st['next']}"
            if seq != st["next"]:
                return (200 if seq < st["next"] else 409), f"next={st['next']}"
            await asyncio.to_thread(self._append, part, st["bytes"], data)
            st = {"next": seq + 1, "bytes": st["bytes"] + len(data)}
            await asyncio.to_thread(write_json, meta, st)
            return 200, f"next={st['next']}"

    @staticmethod
    def _append(part: Path, at: int, data: bytes):
        # lo confirmado manda: si el servidor se cayó entre escribir y anotar, se descarta el sobrante
        with part.open("r+b" if part.exists() else "wb") as f:
            f.truncate(at)
            f.seek(at)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

    async def finish(self, cid: str, parts: int, opts: dict, lib: str | None, register) -> tuple[int, str]:
        """opts: quality, fps, crop. register(archivo, miniatura, duración) lo agrega a la biblioteca."""
        async with self._locks.setdefault(cid, asyncio.Lock()):
            d, part, meta = self._paths(cid, lib)
            st = self._state(meta)
            if st.get("done"):
                return 200, st["done"]
            if st["next"] < parts:
                return 409, f"next={st['next']}"
            if st["bytes"] == 0:
                return 400, "La grabación está vacía"
            task = self._finishing.get(cid)
            if task is None:
                task = self._finishing[cid] = asyncio.create_task(self._convert(d, part, meta, st, cid, opts, register))
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._finishing.pop(cid, None)

    async def _convert(self, d: Path, part: Path, meta: Path, st: dict, cid: str, opts: dict, register) -> tuple[int, str]:
        lib_dir = d.parent
        out = lib_dir / f"{cid}.{out_ext(opts['quality'])}"
        tmp = out.with_name(out.name + ".tmp")
        sizes = list(opts.get("sizes") or [])
        if opts["quality"] != "audio":
            sizes += [x for x in await asyncio.to_thread(probe_sizes, part) if x not in sizes]
        crop = opts["crop"] if not canvas(sizes, QUALITY[opts["quality"]][0]) else None  # otra fuente: la zona ya no vale
        cmd = convert_cmd(part, tmp, opts["quality"], opts["fps"], crop, sizes)
        try:
            r = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"[captura] {cid}: {r.stderr.strip()[-400:]}", flush=True)
                return 500, CONVERT_ERR
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
        dur = await asyncio.to_thread(probe_duration, out)
        thumb = lib_dir / f"{cid}.jpg" if opts["quality"] != "audio" else None
        if thumb:
            try:
                await asyncio.to_thread(make_thumb, out, thumb, dur)
            except (OSError, subprocess.SubprocessError):
                thumb = None
        register(out, thumb, dur)
        await asyncio.to_thread(write_json, meta, {**st, "done": out.name})
        part.unlink(missing_ok=True)  # lo recibido ya es el video final
        return 200, out.name
