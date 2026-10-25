"""Videos de YouTube: descarga local con yt-dlp para procesarlos como un archivo.

Se guardan en data/youtube/<id>.mp4 (H.264 + AAC, hasta 720p, reproducible en
cualquier navegador) y <id>.m4a (solo audio, liviano: es lo que el navegador
decodifica para procesar por delante de la reproducción). Si ya existen, no se
vuelve a descargar.
"""

import re
import subprocess
from pathlib import Path

_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")


def video_id(url: str) -> str | None:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    m = _ID.search(url)
    return m.group(1) if m else None


class YouTube:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def paths(self, vid: str) -> tuple[Path, Path]:
        return self.root / f"{vid}.mp4", self.root / f"{vid}.m4a"

    def fetch(self, url: str, progress=None) -> dict:
        """Descarga (si hace falta) y devuelve {id, title, duration, video, audio}.

        `progress(etapa, fracción)` se llama desde este hilo durante la descarga."""
        import json

        import yt_dlp

        vid = video_id(url)
        if not vid:
            raise ValueError("no es un enlace de YouTube")
        mp4, m4a = self.paths(vid)
        meta = self.root / f"{vid}.json"
        if mp4.exists() and m4a.exists() and meta.exists():
            return json.loads(meta.read_text(encoding="utf-8"))

        def hook(d):
            if progress and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                kind = "audio" if (d.get("info_dict") or {}).get("vcodec") == "none" else "video"
                progress(kind, d.get("downloaded_bytes", 0) / total if total else 0.0)

        opts = {
            # H.264 + AAC: se reproduce en el navegador sin recodificar
            "format": "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4][height<=720]/b",
            "merge_output_format": "mp4",
            "outtmpl": str(self.root / "%(id)s.%(ext)s"),
            "js_runtimes": {"node": {}},
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
        if progress:
            progress("audio", 1.0)
        # pista de audio aparte, sin recodificar
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vn", "-c:a", "copy", str(m4a)],
                       check=True)
        data = {"id": vid, "title": info.get("title") or vid, "channel": info.get("channel") or "",
                "duration": info.get("duration") or 0,
                "video": f"/media/yt/{vid}.mp4", "audio": f"/media/yt/{vid}.m4a"}
        meta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data
