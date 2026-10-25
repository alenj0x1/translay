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

        vid = video_id(url)
        if not vid:
            raise ValueError("no es un enlace de YouTube")
        mp4, m4a = self.paths(vid)
        meta = self.root / f"{vid}.json"
        if mp4.exists() and m4a.exists() and meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            if "categories" not in data or not (self.root / f"{vid}.jpg").exists():
                data.update(self._extras(vid, download=False))  # descargado antes de tener miniaturas
                meta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data

        # etapas visibles: buscando → video → audio → uniendo → preparando → listo
        def hook(d):
            if not progress:
                return
            title = (d.get("info_dict") or {}).get("title")
            # yt-dlp baja video y audio por separado: se distinguen por el archivo
            kind = "audio" if str(d.get("filename", "")).endswith((".m4a", ".webm.part", ".m4a.part")) else "video"
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                progress(kind, d.get("downloaded_bytes", 0) / total if total else 0.0, title)
            elif d.get("status") == "finished":
                progress(kind, 1.0, title)

        def pp_hook(d):
            if progress and d.get("postprocessor") == "Merger":
                progress("uniendo", 0.0 if d.get("status") == "started" else 1.0, None)

        info = self._extras(vid, download=True, hook=hook, pp_hook=pp_hook)
        if progress:
            progress("preparando", 0.0, info["title"])
        # pista de audio aparte, sin recodificar
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vn", "-c:a", "copy", str(m4a)],
                       check=True)
        data = {"id": vid, "video": f"/media/yt/{vid}.mp4", "audio": f"/media/yt/{vid}.m4a", **info}
        meta.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if progress:
            progress("listo", 1.0, info["title"])
        return data

    def _extras(self, vid: str, download: bool, hook=None, pp_hook=None) -> dict:
        """Título, canal, categorías, duración y miniatura (JPG) del video."""
        import yt_dlp

        opts = {
            # H.264 + AAC: se reproduce en el navegador sin recodificar
            "format": "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4][height<=720]/b",
            "merge_output_format": "mp4",
            "outtmpl": str(self.root / "%(id)s.%(ext)s"),
            "js_runtimes": {"node": {}},
            "progress_hooks": [hook] if hook else [],
            "postprocessor_hooks": [pp_hook] if pp_hook else [],
            "writethumbnail": True,
            "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "jpg"}],
            "skip_download": not download,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
        thumb = self.root / f"{vid}.jpg"
        if not thumb.exists():  # sin descarga, yt-dlp no convierte la miniatura (queda webp/png)
            for src in self.root.glob(f"{vid}.*"):
                if src.suffix.lower() in (".webp", ".png", ".jpeg"):
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), str(thumb)], check=False)
                    if thumb.exists():
                        src.unlink(missing_ok=True)
                    break
        return {"title": info.get("title") or vid, "channel": info.get("channel") or "",
                "categories": info.get("categories") or [], "duration": info.get("duration") or 0,
                "thumb": f"/media/yt/{vid}.jpg" if thumb.exists() else ""}
