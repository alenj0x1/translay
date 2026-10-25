"""Videos de YouTube: descarga local con yt-dlp para procesarlos como un archivo.

Se guardan en data/youtube/<id>.mp4 (H.264 + AAC, hasta 720p, reproducible en
cualquier navegador) y <id>.m4a (solo audio, liviano: es lo que el navegador
decodifica para procesar por delante de la reproducción). Si ya existen, no se
vuelve a descargar.
"""

import re
import subprocess
import threading
from collections import defaultdict
from pathlib import Path

_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
_LIST = re.compile(r"[?&]list=([A-Za-z0-9_-]{10,})")


def playlist_id(url: str) -> str | None:
    """Id de la playlist del enlace. Los mix automáticos (RD…) son infinitos: no cuentan."""
    m = _LIST.search(url.strip())
    return m.group(1) if m and not m.group(1).startswith(("RD", "UL")) else None


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
        # un mismo video no se descarga dos veces a la vez (la cola y quien lo abre)
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def paths(self, vid: str) -> tuple[Path, Path]:
        return self.root / f"{vid}.mp4", self.root / f"{vid}.m4a"

    def fetch(self, url: str, progress=None, session: str = "ninguna") -> dict:
        """Descarga (si hace falta) y devuelve {id, title, duration, video, audio}.

        `progress(etapa, fracción)` se llama desde este hilo durante la descarga."""
        import json

        vid = video_id(url)
        if not vid:
            raise ValueError("no es un enlace de YouTube")
        with self._locks[vid]:
            return self._fetch(vid, progress, session)

    def _fetch(self, vid: str, progress, session: str) -> dict:
        import json

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

        info = self._extras(vid, download=True, hook=hook, pp_hook=pp_hook, session=session)
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

    @staticmethod
    def quick_info(vid: str) -> dict:
        """Título y canal al instante (oEmbed público de YouTube), sin descargar."""
        import json
        import urllib.parse
        import urllib.request

        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
            f"https://www.youtube.com/watch?v={vid}")
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                d = json.loads(r.read().decode("utf-8"))
            return {"id": vid, "title": d.get("title") or vid, "channel": d.get("author_name") or ""}
        except Exception:
            return {"id": vid, "title": vid, "channel": ""}

    def playlist(self, url: str, session: str = "ninguna") -> dict:
        """Título, canal y videos de una playlist (sin descargar nada)."""
        import yt_dlp

        pid = playlist_id(url)
        if not pid:
            raise ValueError("no es un enlace de playlist")
        opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True,
                "js_runtimes": {"node": {}}, **self._session_opts(session)}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/playlist?list={pid}", download=False)
        entries, seen = [], set()
        for e in info.get("entries") or []:
            vid = (e or {}).get("id") or ""
            if len(vid) != 11 or vid in seen or (e.get("title") or "").startswith(("[Private", "[Deleted")):
                continue
            seen.add(vid)
            entries.append({"id": vid, "title": e.get("title") or vid, "duration": e.get("duration") or 0,
                            "channel": e.get("channel") or e.get("uploader") or "",
                            "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
        if not entries:
            raise ValueError("la playlist está vacía o es privada")
        return {"id": pid, "title": info.get("title") or "Playlist",
                "channel": info.get("channel") or info.get("uploader") or "",
                "url": f"https://www.youtube.com/playlist?list={pid}", "entries": entries}

    def _session_opts(self, session: str) -> dict:
        """Sesión de YouTube de la persona, solo si la eligió en Preferencias: su
        navegador (Firefox se puede leer abierto; los de tipo Chrome bloquean sus
        cookies mientras están abiertos) o un cookies.txt exportado en data/."""
        if session == "archivo":
            path = self.root.parent / "cookies.txt"
            if not path.exists():
                raise FileNotFoundError("cookies.txt")
            return {"cookiefile": str(path)}
        if session in ("firefox", "brave", "chrome", "edge"):
            return {"cookiesfrombrowser": (session,)}
        return {}

    def _extras(self, vid: str, download: bool, hook=None, pp_hook=None, session: str = "ninguna") -> dict:
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
            **self._session_opts(session),
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


def friendly_error(e: Exception, session: str = "ninguna") -> str:
    """Mensaje claro (y qué hacer) en vez del error crudo de yt-dlp."""
    msg = str(e)
    browser = {"brave": "Brave", "chrome": "Chrome", "edge": "Edge", "firefox": "Firefox"}.get(session, session)
    if "confirm you" in msg and "bot" in msg:
        if session == "ninguna":
            return ("YouTube pidió verificar que no eres un bot. En Preferencias → «Sesión de YouTube» usa "
                    "«Archivo cookies.txt» (con Brave, Chrome o Edge abiertos es lo que funciona), o espera unas horas.")
        return (f"YouTube sigue pidiendo verificación con la sesión de {browser}: revisa que hayas iniciado "
                "sesión en YouTube en ese navegador.")
    if "Could not copy" in msg and "cookie" in msg:
        return (f"No se pudo leer la sesión de {browser}: los navegadores tipo Chrome bloquean sus cookies "
                "mientras están abiertos. Ciérralo durante la descarga, usa Firefox, o exporta un cookies.txt.")
    if "decrypt" in msg.lower() or "app-bound" in msg.lower():
        return (f"{browser} cifra sus cookies y no se pueden leer desde aquí. Usa Firefox o exporta un "
                "cookies.txt (Preferencias → «Archivo cookies.txt»).")
    if isinstance(e, FileNotFoundError) and "cookies.txt" in msg:
        return "Falta el archivo data/cookies.txt (expórtalo desde tu navegador con la sesión de YouTube iniciada)."
    if "playlist" in msg.lower() and ("does not exist" in msg or "private" in msg.lower()):
        return "La playlist no existe o es privada."
    if "Video unavailable" in msg or "Private video" in msg:
        return "El video no está disponible (privado, eliminado o restringido)."
    return msg[:300]
