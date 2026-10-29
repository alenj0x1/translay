"""Videos desde enlaces compartidos (por ahora, Dropbox): se bajan como un archivo importado.

Quedan en <biblioteca>/library/lk_<huella>.<ext> junto a su audio (.m4a, sin
recodificar si ya es AAC) y una miniatura (.jpg) sacada del propio video. La
huella sale del enlace sin sus parámetros de seguimiento, así el mismo enlace
pegado dos veces es el mismo video.
"""

import hashlib
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

MEDIA_EXTS = {"mp4", "m4v", "webm", "mkv", "mov", "avi", "ts", "flv", "wmv", "3gp", "mpg", "mpeg",
              "mp3", "m4a", "wav", "ogg", "opus", "flac", "aac"}
_DROPBOX = re.compile(r"^(?:www\.|dl\.)?dropbox(?:usercontent)?\.com$", re.I)


def parse(url: str) -> dict | None:
    """Enlace de Dropbox a un archivo → {id, url, direct, name}; None si no lo es.

    Lanza ValueError si es de Dropbox pero no apunta a un video (p. ej. una carpeta)."""
    u = urllib.parse.urlsplit(url.strip())
    if not _DROPBOX.match(u.hostname or ""):
        return None
    q = urllib.parse.parse_qs(u.query)
    parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
    # /scl/fi/<id>/<archivo> · /scl/fo/<id>/<clave>/<archivo> · /s/<id>/<archivo>
    name = parts[-1] if len(parts) >= 3 else ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in MEDIA_EXTS:
        raise ValueError("el enlace de Dropbox no es de un video: abre el video y copia su enlace")
    keep = {k: q[k][0] for k in ("rlkey",) if k in q}  # sin "st", "e" ni "dl": cambian cada vez
    clean = urllib.parse.urlunsplit(("https", "www.dropbox.com", u.path, urllib.parse.urlencode(keep), ""))
    direct = urllib.parse.urlunsplit(("https", "www.dropbox.com", u.path,
                                      urllib.parse.urlencode({**keep, "dl": "1"}), ""))
    vid = "lk_" + hashlib.sha1(clean.encode()).hexdigest()[:16]
    return {"id": vid, "url": clean, "direct": direct, "name": name.rsplit(".", 1)[0], "ext": ext}


def link_id(url: str) -> str | None:
    try:
        p = parse(url)
    except ValueError:
        return None
    return p["id"] if p else None


class Links:
    def __init__(self, root: Path):
        self.root = root  # <biblioteca>/library: los mismos archivos que lo importado del equipo

    def fetch(self, vid: str, url: str, progress=None, audio_only: bool = False) -> dict:
        """Descarga (si hace falta) y devuelve {title, duration, video, audio, thumb, audio_only}.

        `progress(etapa, fracción, título, stats)` como en vt/youtube.py. Con audio_only se
        baja igual el archivo entero (Dropbox no da solo el audio) y se queda únicamente el .m4a."""
        p = parse(url)
        if not p or p["id"] != vid:
            raise ValueError("el enlace no corresponde a este video")
        self.root.mkdir(parents=True, exist_ok=True)
        media, m4a, thumb = self.root / f"{vid}.{p['ext']}", self.root / f"{vid}.m4a", self.root / f"{vid}.jpg"
        meta = self.root / f"{vid}.json"
        if m4a.exists() and meta.exists() and (media.exists() or audio_only):
            data = json.loads(meta.read_text(encoding="utf-8"))
            if not media.exists():
                data.update(video="", audio_only=True)
            return data

        title = p["name"]
        if not media.exists():
            self._download(p["direct"], media, lambda f, s=None: progress and progress("video", f, title, s))
        if progress:
            progress("preparando", 0.0, title)
        duration = _duration(media)
        if p["ext"] != "m4a":
            # pista de audio aparte: copia directa si es AAC; si no, se convierte
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-vn", "-c:a", "copy", str(m4a)],
                               capture_output=True)
            if r.returncode != 0 or not m4a.exists() or m4a.stat().st_size == 0:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-vn", "-c:a", "aac",
                                "-b:a", "160k", str(m4a)], check=True)
        if not thumb.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(min(10.0, duration * 0.1)), "-i", str(media),
                            "-frames:v", "1", "-vf", "scale='min(640,iw)':-2", "-q:v", "4", str(thumb)], check=False)
        has_video = thumb.exists()  # un .mp3 o .wav no da miniatura: es solo audio
        data = {"id": vid, "title": title, "duration": duration, "source_url": p["url"],
                "video": f"/media/lib/{media.name}" if has_video else "", "audio": f"/media/lib/{m4a.name}",
                "thumb": f"/media/lib/{thumb.name}" if has_video else ""}
        if audio_only or not has_video:
            if media != m4a:
                media.unlink(missing_ok=True)  # solo audio: el video completo no se guarda
            data.update(video="", audio_only=True)
        meta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if progress:
            progress("listo", 1.0, title)
        return data

    @staticmethod
    def _download(url: str, out: Path, progress):
        tmp = out.with_suffix(".part")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if "text/html" in (r.headers.get("Content-Type") or ""):
                    raise ValueError("Dropbox no entregó el archivo: revisa que el enlace sea público")
                total = int(r.headers.get("Content-Length") or 0)
                done, t0, last = 0, time.time(), 0.0
                with tmp.open("wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - last > 0.5:
                            last = now
                            speed = done / max(now - t0, 1e-3)
                            progress(done / total if total else 0.0,
                                     {"speed": speed, "eta": (total - done) / speed if total and speed else None,
                                      "done": done, "total": total})
            if total and done < total:
                raise ConnectionError("la descarga se cortó")
            tmp.replace(out)
            progress(1.0)
        finally:
            tmp.unlink(missing_ok=True)  # cortada: no queda el archivo a medias


def _duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        return 0.0
