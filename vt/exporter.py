"""Exportar: video o audio traducido (y el original) de uno o varios videos.

Tipos
  es_video    MP4 con la voz en español (pista principal), el original como segunda
              pista y subtítulos en español y en el idioma original (se activan en el reproductor)
  es_audio    M4A, MP3 u Opus con la voz en español
  orig_video  el video original
  orig_audio  el audio original, M4A, MP3 u Opus
  srt_es · srt_orig · txt   subtítulos traducidos, subtítulos en el idioma original y transcripción
                            bilingüe (con la hora, la persona y los comentarios)
  txt_es · txt_orig         solo el texto, en párrafos: en español o en el idioma original
  summary                   el resumen del video (de qué se trató y sus puntos importantes, vt/summarize.py);
                            si aún no tiene, se hace antes de exportar

Calidad: el audio en «alta», «media» o «liviana» (AUDIO_CODEC: menos kbps y, la liviana,
en mono, que para una voz alcanza); el video «original» (sin recodificar) o bajado a 480p
o 360p con H.264 (VIDEO_HEIGHT: tarda más, usa la CPU). El audio original en «alta» y en
su mismo formato se entrega tal cual.

Destino: sin `dest`, el resultado queda en data/exports/<id>/ y el navegador lo descarga
(se borra al quitarlo de la lista o a las 24 h). Con `dest` (una carpeta de este equipo,
p. ej. en otro disco) todo se arma en `dest/.translay-exportando-<id>/` y el resultado se
mueve ahí: no pasa por el disco de los datos ni queda una segunda copia. Varios archivos van
sueltos en una carpeta con las mismas subcarpetas que el .zip (_Folder), no en un .zip.
Un solo archivo con `filename` (el que se eligió en «Guardar como») se guarda con ese nombre.
Lo guardado en una carpeta queda en la lista con su ruta (data/exports.json, las últimas
HISTORY), también después de reiniciar, mientras el archivo siga ahí.

Un video que solo se transcribe no tiene traducción ni voz: sus tipos traducidos se
omiten (si no queda nada, el video va a «omitidos.txt»).

La mezcla en español es la misma que se escucha en la vista: cada frase doblada
en su momento y el original bajo la voz (nivel de Ajustes). Donde no hay
voz, el original queda a volumen normal. Se arma por bloques (un video largo no
pasa entero por memoria) con ffmpeg en la CPU: no usa la GPU.

Lo traducido espera a que el doblaje termine (el video entra a la cola si
hace falta). Un solo archivo se entrega tal cual; varios, en un .zip, sueltos
o en carpetas como los grupos de la biblioteca (`layout`). Si un
video de un lote no se puede exportar (p. ej. ya no está en YouTube y no tiene
copia en el equipo), se omite y el resto sigue; el .zip lleva «omitidos.txt».
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np

from . import events, langs
from .audiofx import read_wav, resample

SR = 48000
# conversiones a la vez (ffmpeg usa un núcleo por audio); deja la mitad del equipo libre
WORKERS = max(1, min(6, (os.cpu_count() or 2) // 2))
BLOCK = SR * 10
DUCK_LEVELS = {"silencio": 0.0, "bajo": 0.14, "medio": 0.3}
# texto: subtítulos (SRT) y transcripción bilingüe con comentarios (TXT); no necesitan el doblaje
TEXT_KINDS = ("srt_es", "srt_orig", "txt", "txt_es", "txt_orig", "summary")
TRANSLATED = ("es_video", "es_audio", "srt_es", "txt_es")  # necesitan traducción (y voz)
SAME_IN_TARGET = ("srt_es", "txt_es")  # de un video ya en español: el mismo texto que el original
ALIASES = {"srt_en": "srt_orig"}  # nombre de antes de los idiomas (la API lo sigue aceptando)
KINDS = {"es_video": ("español", "mp4"), "es_audio": ("español", "m4a"),
         "srt_es": ("subtítulos español", "srt"), "srt_orig": ("subtítulos originales", "srt"),
         "txt": ("transcripción", "txt"),
         "txt_es": ("texto en español", "txt"), "txt_orig": ("texto original", "txt"), "summary": ("resumen", "txt"),
         "orig_video": ("original", "mp4"), "orig_audio": ("audio original", "m4a")}
# formato → calidad → (códec, kbps, canales); un MB por hora ≈ kbps × 0,45
AUDIO_CODEC = {"m4a": {"alta": ("aac", 160, 2), "media": ("aac", 96, 2), "liviana": ("aac", 64, 1)},
               "mp3": {"alta": ("libmp3lame", 192, 2), "media": ("libmp3lame", 128, 2), "liviana": ("libmp3lame", 64, 1)},
               "opus": {"alta": ("libopus", 128, 2), "media": ("libopus", 64, 2), "liviana": ("libopus", 32, 1)}}
AUDIO_FORMATS = tuple(AUDIO_CODEC)
QUALITIES = ("alta", "media", "liviana")
ORIG_TRACK_KBPS = {"alta": 128, "media": 96, "liviana": 64}  # el original como segunda pista del MP4
VIDEO_HEIGHT = {"original": 0, "480p": 480, "360p": 360}
SWEEP_AGE = 86400  # lo exportado para descargar se borra a las 24 h (si no se quitó antes de la lista)
HISTORY = 100  # exportaciones guardadas en una carpeta que se recuerdan con su ruta


def audio_args(fmt: str, quality: str = "alta") -> list[str]:
    codec, kbps, ch = AUDIO_CODEC[fmt][quality]
    return ["-c:a", codec, "-b:a", f"{kbps}k", *(["-ac", "1"] if ch == 1 else [])]
# carpetas del .zip, como los grupos de la biblioteca: ninguna, una por canal, por colección propia
# o por playlist (la primera que tenga el video; las categorías no, un video suele tener varias)
# y «folder»: todo en una sola carpeta (lo exportado desde un canal, colección o playlist)
LAYOUTS = ("flat", "channel", "collection", "playlist", "folder")


def reason(e: Exception) -> str:
    """El motivo en palabras de la app, no el texto crudo de yt-dlp o ffmpeg."""
    text = str(e)
    if "removed by the uploader" in text or "Video unavailable" in text or "Private video" in text:
        return "ya no está disponible en YouTube y no tiene copia en el equipo"
    if isinstance(e, subprocess.CalledProcessError):
        return "ffmpeg no pudo convertir el archivo"
    return re.sub(r"^ERROR:\s*(\[\w+\]\s*)?", "", text)[:200]


def safe_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "video")
    return re.sub(r"\s+", " ", text).strip(" .")[:110] or "video"


def safe_file(name: str) -> str:
    """Como safe_name, pero recorta solo el nombre y conserva la extensión."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not 1 <= len(ext) <= 5:
        return safe_name(name)
    return f"{safe_name(stem)}.{safe_name(ext)}"


class _Folder:
    """Como el .zip, pero una carpeta: cada archivo se mueve a su lugar (o se copia, si es el original
    de la biblioteca)."""

    def __init__(self, root: Path, work: Path):
        self.root, self.work = root, work
        root.mkdir(parents=True, exist_ok=True)

    def write(self, f: Path, arc: str):
        dst = self.root / arc
        dst.parent.mkdir(parents=True, exist_ok=True)
        if f.is_relative_to(self.work):
            os.replace(f, dst)
        else:
            shutil.copy2(f, dst)

    def close(self):
        pass


def video_args(height: int) -> list[str]:
    """H.264 recodificado; con height, a lo sumo esa altura (un video más bajo queda como está)."""
    scale = ["-vf", f"scale=-2:'min({height},ih)'"] if height else []
    return [*scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23" if height else "21", "-pix_fmt", "yuv420p"]


def unique_path(p: Path) -> Path:
    """p, o «nombre (2).ext», «nombre (3).ext»… si ya hay un archivo con ese nombre."""
    n = 2
    out = p
    while out.exists():
        out, n = p.with_name(f"{p.stem} ({n}){p.suffix}"), n + 1
    return out


def dir_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def srt(segments: list[dict], key: str) -> str:
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

    out, n = [], 0
    for s in segments:
        text = (s.get(key) or "").strip()
        if text:
            n += 1
            out.append(f"{n}\n{ts(s['start'])} --> {ts(max(s['end'], s['start'] + 0.5))}\n{text}\n")
    return "\n".join(out)


def plain_text(title: str, segments: list[dict], key: str, gap: float = 2.0) -> str:
    """Solo el texto, en párrafos: uno nuevo tras una pausa larga o al cambiar de persona."""
    paras, cur, last = [], [], None
    for s in segments:
        text = (s.get(key) or "").strip()
        if not text:
            continue
        if cur and last and (s["start"] - last["end"] > gap or s.get("speaker") != last.get("speaker")):
            paras.append(" ".join(cur))
            cur = []
        cur.append(text)
        last = s
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join([title, *paras]) + "\n"


class Exporter:
    def __init__(self, root: Path, store, library, processor, youtube, prefs, notify, vaults=None, summaries=None):
        self.root = root
        self.summaries = summaries  # la cola del resumen (vt/summaries.py): el resumen se hace si falta
        self.vaults = vaults
        self.dir = root / "exports"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store, self.library, self.processor = store, library, processor
        self.youtube, self.prefs, self.notify = youtube, prefs, notify
        self.jobs: list[dict] = []
        self._history = root / "exports.json"
        try:  # lo guardado en una carpeta antes de reiniciar, si sigue ahí
            old = json.loads(self._history.read_text(encoding="utf-8"))
            self.jobs = [j for j in old if j.get("path") and Path(j["path"]).exists()]
        except (OSError, ValueError):
            pass
        self._cond = threading.Condition()
        self._last = 0.0
        self.sweep()
        threading.Thread(target=self._loop, daemon=True).start()

    def sweep(self, everything: bool = False) -> int:
        """Borra lo exportado para descargar que ya tiene más de 24 h (o todo lo que no está en
        curso, con everything). Devuelve los bytes liberados."""
        busy = {j["id"] for j in self.jobs if j["state"] not in ("listo", "error")}
        freed, gone = 0, set()
        for old in list(self.dir.iterdir()):
            try:  # otro hilo puede estar borrando lo mismo (quitar de la lista, Almacenamiento)
                if old.name in busy or not (everything or time.time() - old.stat().st_mtime > SWEEP_AGE):
                    continue
                freed += dir_size(old)
                shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
                gone.add(old.name)
            except OSError:
                continue
        if gone:  # ya no se pueden descargar: salen del panel
            self.jobs = [j for j in self.jobs if j["id"] not in gone or j.get("dest")]
            self._broadcast(force=True)
        return freed

    def busy_videos(self) -> set[str]:
        """Videos de exportaciones que aún no terminan (Almacenamiento no borra su original)."""
        return {v for j in self.jobs if j["state"] not in ("listo", "error") for v in j["videos"]}

    # ------------------------------------------------------------------ API
    def add(self, videos: list[str], kinds: list[str], name: str = "", audio: str = "m4a",
            layout: str = "flat", folder: str = "", quality: str = "alta", video: str = "original",
            dest: str = "", filename: str = "") -> dict:
        videos = [v for v in dict.fromkeys(videos) if v in self.library.data["videos"]]
        kinds = [ALIASES.get(k, k) for k in kinds]
        kinds = [k for k in KINDS if k in kinds]
        if not videos or not kinds:
            raise ValueError("nada que exportar")
        if audio not in AUDIO_FORMATS:
            raise ValueError("audio: " + ", ".join(AUDIO_FORMATS))
        if quality not in QUALITIES:
            raise ValueError("quality: " + ", ".join(QUALITIES))
        if video not in VIDEO_HEIGHT:
            raise ValueError("video: " + ", ".join(VIDEO_HEIGHT))
        if layout not in LAYOUTS:
            raise ValueError("layout: " + ", ".join(LAYOUTS))
        if dest:
            d = Path(dest)
            # una carpeta de este equipo: nunca de red (abrir \\servidor\… conecta a otra máquina)
            if not d.is_absolute() or str(d).startswith(("\\\\", "//")):
                raise ValueError(f"no se puede guardar en «{dest}»")
            # ni dentro de los datos: Almacenamiento tomaría lo exportado por archivos sueltos
            roots = [self.root] + ([v.root for v in self.vaults.all()] if self.vaults else [])
            if any(d.resolve().is_relative_to(r.resolve()) for r in roots):
                raise ValueError("elige una carpeta fuera de la de tus bibliotecas")
            try:
                d.mkdir(parents=True, exist_ok=True)  # el cuadro deja escribir una carpeta nueva
            except OSError:
                raise ValueError(f"no se puede guardar en «{dest}»") from None
            dest = str(d.resolve())
        if not name:
            name = self.library.data["videos"][videos[0]].get("title", "video") if len(videos) == 1 else "videos"
        job = {"id": uuid.uuid4().hex[:10], "name": name, "videos": videos, "kinds": kinds, "audio": audio,
               "quality": quality, "video": video, "dest": dest, "path": "", "filename": safe_file(filename) if filename else "",
               "layout": layout, "folder": folder, "state": "en espera", "pct": 0, "detail": "", "url": "", "error": "", "skipped": [],
               "added": time.time()}
        with self._cond:
            self.jobs.append(job)
            self._cond.notify_all()
        self._broadcast(force=True)
        return job

    def plan(self, videos: list[str], kinds: list[str], name: str = "", audio: str = "m4a") -> tuple[bool, str]:
        """(un solo archivo, su nombre): para proponerlo en «Guardar como» antes de exportar.
        Varios videos o tipos van en una carpeta con el nombre de lo exportado."""
        videos = [v for v in dict.fromkeys(videos) if v in self.library.data["videos"]]
        kinds = [k for k in KINDS if k in [ALIASES.get(k, k) for k in kinds]]
        if len(videos) == 1 and len(kinds) == 1:
            v = self.library.data["videos"][videos[0]]
            title, (label, ext) = safe_name(v.get("title") or videos[0])[:90], KINDS[kinds[0]]
            if kinds[0] in ("es_audio", "orig_audio"):
                ext = audio if audio in AUDIO_FORMATS else "m4a"
            if kinds[0] == "orig_video":
                return True, f"{title}{Path(v.get('media') or 'x.mp4').suffix or '.mp4'}"
            return True, f"{title} ({label}).{ext}"
        if not name:
            name = self.library.data["videos"][videos[0]].get("title", "video") if len(videos) == 1 else "videos"
        return False, safe_name(name)

    def _save_history(self):
        keep = [{k: j[k] for k in ("id", "name", "videos", "kinds", "state", "pct", "detail", "url", "error",
                                    "path", "skipped", "added")}
                for j in self.jobs if j["state"] == "listo" and j.get("path")][-HISTORY:]
        tmp = self._history.with_suffix(".tmp")
        tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._history)

    def remove(self, jid: str):
        with self._cond:
            gone = [j for j in self.jobs if j["id"] == jid]
            self.jobs = [j for j in self.jobs if j["id"] != jid]
        for j in gone:  # lo que quedaba para descargar ya no sirve (en curso: lo borra _run al ver que no está)
            if j["state"] in ("listo", "error"):
                shutil.rmtree(self.dir / j["id"], ignore_errors=True)  # lo guardado en una carpeta no se toca
        if any(j.get("path") for j in gone):
            self._save_history()
        self._broadcast(force=True)

    def public(self) -> dict:
        return {"type": "exports", "jobs": [{k: j[k] for k in ("id", "name", "state", "pct", "detail", "url", "error", "path")}
                                            | {"count": len(j["videos"]), "videos": j["videos"][:50],
                                               "skipped": len(j["skipped"])} for j in self.jobs]}

    def _broadcast(self, force=False):
        if force or time.time() - self._last > 0.7:
            self._last = time.time()
            self.notify(self.public())

    def _set(self, job, **kw):
        job.update(kw)
        self._broadcast(force="state" in kw)

    # ---------------------------------------------------------------- bucle
    def _loop(self):
        while True:
            with self._cond:
                while (job := next((j for j in self.jobs if j["state"] == "en espera"), None)) is None:
                    if not self._cond.wait(timeout=3600):  # sin trabajo: cada hora, lo vencido
                        try:
                            self.sweep()
                        except Exception:  # noqa: BLE001 — nunca detiene las exportaciones
                            pass
            try:
                self._run(job)
            except Exception as e:
                import traceback

                traceback.print_exc()
                shutil.rmtree(self._work_dir(job), ignore_errors=True)  # lo a medias no sirve
                self._set(job, state="error", error=reason(e))
                events.emit("exportacion.error", self._job_vault(job), job=job["id"], name=job["name"], error=job["error"])

    def _run(self, job):
        """Lo que pesa (convertir, mezclar) corre en varios hilos, un video por hilo; descargar y esperar
        el doblaje siguen de a uno. Cada archivo entra al .zip apenas está y se borra su copia suelta."""
        out_dir = self._work_dir(job)
        out_dir.mkdir(exist_ok=True)
        many = len(job["videos"]) > 1
        zpath = out_dir / "export.zip"
        # varios: un .zip sin comprimir (ya vienen comprimidos); a una carpeta elegida, una carpeta con
        # los archivos sueltos (un pendrive FAT32 no admite archivos de más de 4 GB)
        z = None
        if many or len(job["kinds"]) > 1:
            z = (_Folder(out_dir / "carpeta", out_dir) if job.get("dest")
                 else zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED, allowZip64=True))
        files: list[tuple[Path, str]] = []  # (archivo, nombre al descargar) cuando es uno solo
        used: set[str] = set()
        frac: dict[str, float] = {}  # avance de cada video: 0 a 1
        lock = threading.Lock()

        def progress():
            with lock:
                pct = round(sum(frac.values()) / len(job["videos"]) * 100, 1)
            self._set(job, pct=pct)

        def skip(vid, v, e):
            if not many:
                raise e
            import traceback

            traceback.print_exc()
            job["skipped"].append((v.get("title") or vid, reason(e)))  # el resto del lote sigue
            with lock:
                frac[vid] = 1.0

        def one(vid, v, title):  # en un hilo del grupo: todos los tipos de un video, en orden
            out = []
            tr = self.store.open(vid) if any(k in TRANSLATED for k in job["kinds"]) else None
            only_text = bool(tr and tr.transcribe_only)  # sin traducción ni voz
            # ya en español: sus subtítulos en español son el mismo texto
            skip = {k for k in TRANSLATED if not (k in SAME_IN_TARGET and tr and tr.lang == langs.TARGET)}
            if only_text and all(k in skip for k in job["kinds"]):
                raise ValueError("solo se transcribe: no tiene traducción ni voz en español")
            for i, kind in enumerate(job["kinds"]):
                if job not in self.jobs:
                    return out
                if only_text and kind in skip:
                    continue
                label, ext = KINDS[kind]
                if kind in ("es_audio", "orig_audio"):
                    ext = job.get("audio", "m4a")

                def prog(f, i=i):
                    with lock:
                        frac[vid] = (i + f) / len(job["kinds"])
                    progress()

                self._set(job, state="exportando", detail=f"{title} · {label}")
                path = self._make(kind, vid, v, out_dir, prog, job.get("audio", "m4a"),
                                  job.get("quality", "alta"), job.get("video", "original"))
                if kind == "orig_video":
                    ext = path.suffix.lstrip(".")
                out.append((path, f"{title} ({label}).{ext}" if kind != "orig_video" else f"{title}.{ext}"))
            return out

        def collect(fut, vid, v):
            try:
                got = fut.result()
            except Exception as e:
                return skip(vid, v, e)
            folder = self._folder(job, vid, v)
            for f, arc in got:
                if z is None:
                    files.append((f, arc))
                    continue
                arc = f"{folder}/{arc}" if folder else arc
                stem, ext, n = arc.rsplit(".", 1)[0], arc.rsplit(".", 1)[1], 2
                while arc in used:
                    arc, n = f"{stem} ({n}).{ext}", n + 1
                used.add(arc)
                z.write(f, arc)
                if f.is_relative_to(out_dir):
                    f.unlink(missing_ok=True)  # ya está en el .zip: no ocupa el disco dos veces
            with lock:
                frac[vid] = 1.0
            progress()

        pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="exportar")
        pending: dict = {}
        try:
            for vid in job["videos"]:
                if job not in self.jobs:
                    return
                v = self.library.data["videos"][vid]
                title = safe_name(v.get("title") or vid)
                try:
                    if any(k not in TEXT_KINDS for k in job["kinds"]):  # solo texto: no hace falta el archivo
                        self._ensure_media(job, vid, video=any(k in ("es_video", "orig_video") for k in job["kinds"]))
                    v = self.library.data["videos"][vid]
                    if any(k.startswith("es_") for k in job["kinds"]):
                        self._wait_dub(job, vid, title)
                    elif any(k in TEXT_KINDS for k in job["kinds"]):
                        self._wait_dub(job, vid, title, key="asr")  # el texto necesita la transcripción completa
                    if "summary" in job["kinds"]:
                        self._wait_summary(job, vid, title)
                except Exception as e:
                    skip(vid, v, e)
                    continue
                pending[pool.submit(one, vid, v, title)] = (vid, v)
                for f in [f for f in pending if f.done()]:
                    collect(f, *pending.pop(f))
            while pending:
                if job not in self.jobs:
                    return
                finished, _ = wait(list(pending), timeout=1, return_when=FIRST_COMPLETED)
                for f in finished:
                    collect(f, *pending.pop(f))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            if z is not None:
                z.close()
            if job not in self.jobs:  # cancelada: lo hecho no se va a descargar
                shutil.rmtree(out_dir, ignore_errors=True)
        if not files and not used:
            raise RuntimeError(f"ningún video se pudo exportar ({job['skipped'][0][1]})" if job["skipped"]
                               else "nada que exportar")
        if z is None:
            path, name = files[0]
        else:
            skipped = ("No se pudieron exportar:\n\n" + "\n".join(f"- {t}: {r}" for t, r in job["skipped"]) + "\n"
                       if job["skipped"] else "")
            if isinstance(z, _Folder):
                if skipped:
                    (z.root / "omitidos.txt").write_text(skipped, encoding="utf-8")
                path, name = z.root, safe_name(job["name"])
            else:
                if skipped:
                    with zipfile.ZipFile(zpath, "a", zipfile.ZIP_STORED, allowZip64=True) as za:
                        za.writestr("omitidos.txt", skipped)
                path, name = zpath, safe_name(job["name"]) + ".zip"
        if job.get("dest"):  # a la carpeta elegida: se mueve (mismo disco) o, si es el original de la biblioteca, se copia
            # el nombre elegido en «Guardar como» (ya confirmó reemplazarlo); si no, uno libre
            target = Path(job["dest"]) / job["filename"] if job.get("filename") and z is None \
                else unique_path(Path(job["dest"]) / name)
            if path.is_relative_to(out_dir):
                os.replace(path, target)
            else:
                shutil.copy2(path, target)
            shutil.rmtree(out_dir, ignore_errors=True)
            self._set(job, state="listo", pct=100, detail="", path=str(target))
            self._save_history()
            events.emit("exportacion.lista", self._job_vault(job), job=job["id"], name=job["name"], url="",
                        path=str(target), videos=job["videos"], kinds=job["kinds"])
            return
        url = None
        for vault in (self.vaults.all() if self.vaults else []):  # el original, directo de su biblioteca
            for sub, pre in (("youtube", "/media/yt/"), ("library", "/media/lib/")):
                if url is None and path.is_relative_to(vault.root / sub):
                    url = vault.url(pre + path.relative_to(vault.root / sub).as_posix())
        if url is None:
            rel = path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else ""
            if rel.startswith("youtube/"):
                url = "/media/yt/" + rel[8:]
            elif rel.startswith("library/"):
                url = "/media/lib/" + rel[8:]
            else:
                url = "/exports/" + path.relative_to(self.dir).as_posix()
        from urllib.parse import quote

        self._set(job, state="listo", pct=100, detail="", url=f"{url}?dl={quote(name)}")
        events.emit("exportacion.lista", self._job_vault(job), job=job["id"], name=job["name"], url=job["url"],
                    videos=job["videos"], kinds=job["kinds"])

    def _folder(self, job, vid, v) -> str:
        """La carpeta del video dentro del .zip ("" = en la raíz)."""
        layout = job.get("layout", "flat")
        if layout == "channel":
            return safe_name(v.get("channel") or "") if v.get("channel") else "Sin canal"
        if layout in ("collection", "playlist"):
            kind = "propia" if layout == "collection" else "playlist"
            c = next((c for c in self.library.data.get("collections", [])
                      if c.get("kind", "propia") == kind and vid in c.get("items", []) and c.get("name")), None)
            return safe_name(c["name"]) if c else ("Sin colección" if kind == "propia" else "Sin playlist")
        if layout == "folder":
            return safe_name(job.get("folder") or job["name"])
        return ""

    def _work_dir(self, job) -> Path:
        """Donde se arma: junto al destino elegido (mismo disco: mover es instantáneo) o en data/exports."""
        return Path(job["dest"]) / f".translay-exportando-{job['id']}" if job.get("dest") else self.dir / job["id"]

    def _job_vault(self, job):
        v = self.vaults.of(job["videos"][0]) if self.vaults and job["videos"] else None
        return v.id if v else None

    # ------------------------------------------------------------ insumos
    def _root(self, vid: str) -> Path:
        v = self.vaults.of(vid) if self.vaults else None
        return v.root if v else self.root

    def _media_path(self, src: str, vid: str = "") -> Path:
        src = (src or "").split("?")[0]
        v = self.vaults.of(vid) if self.vaults and vid else None
        if v and v.file(src):
            return v.file(src)
        if src.startswith("/media/yt/"):
            return self.root / "youtube" / Path(src[10:]).name  # solo el nombre: nunca fuera de la carpeta
        if src.startswith("/media/lib/"):
            return self.root / "library" / Path(src[11:]).name
        raise FileNotFoundError("el video no tiene copia en el equipo")

    def _ensure_media(self, job, vid, video: bool = False):
        """Copia en el equipo; si solo se bajó el audio y se pide un video, se baja el video completo."""
        v = self.library.data["videos"][vid]
        if v.get("media") and not (video and v.get("audio_only")):
            return
        vault = self.vaults.of(vid) if self.vaults else None
        if v.get("source") not in ("youtube", "link") or not self.youtube or (v.get("source") == "link" and not vault):
            raise FileNotFoundError(f"«{v.get('title', vid)}» no tiene copia en el equipo")
        self._set(job, state="exportando", detail=f"descargando {v.get('title', vid)}")
        session = self.prefs.values.get("yt_session", "ninguna")
        info = (vault.download(vid, None, session, audio_only=False) if vault
                else self.youtube.fetch(vid[3:], None, session, audio_only=False))
        self.library.set_field(vid, media=info["video"], audio=info["audio"], audio_only=False,
                               **{k: info[k] for k in ("title", "duration", "thumb", "channel", "categories")
                                  if info.get(k)})

    def _wait_dub(self, job, vid, title, key: str = "dub"):
        """Lo traducido necesita el doblaje completo (key="dub") o al menos la transcripción
        (key="asr", para subtítulos y texto): si falta, el video entra a la cola."""
        queued = False
        what = "doblaje" if key == "dub" else "transcripción"
        while job in self.jobs:
            p = self.processor.progress(vid)
            pj = self.processor._job(vid)
            if p[key] >= 0.99 or (queued and pj and pj["state"] in ("listo", "error")):
                return
            if pj is None or pj["state"] in ("listo", "error", "descargado"):
                self.processor.add(vid)
            queued = True
            self._set(job, state=f"esperando {what}", detail=f"{title} · {what} {round(p[key] * 100)} %")
            time.sleep(3)

    # ------------------------------------------------------------ salida
    def _make(self, kind, vid, v, out_dir: Path, prog, fmt: str = "m4a", quality: str = "alta",
              video: str = "original") -> Path:
        if kind in TEXT_KINDS:
            return self._make_text(kind, vid, v, out_dir)
        media = self._media_path(v["media"], vid)
        audio = self._media_path(v["audio"], vid) if v.get("audio") else media
        dur = float(v.get("duration") or 0)
        height = VIDEO_HEIGHT[video]
        if kind == "orig_video":
            if not height:
                return media
            out = out_dir / f"{vid}.orig.{video}.mp4"
            self._ffmpeg(["-i", str(media), "-map", "0:v:0", "-map", "0:a?", *video_args(height),
                          "-c:a", "aac", "-b:a", f"{ORIG_TRACK_KBPS[quality]}k", "-movflags", "+faststart", str(out)],
                         prog, dur)
            return out
        if kind == "orig_audio":
            if audio.suffix == f".{fmt}" and quality == "alta":
                return audio
            out = out_dir / f"{vid}.orig.{quality}.{fmt}"
            self._ffmpeg(["-i", str(audio), "-vn", *audio_args(fmt, quality), str(out)], prog, dur)
            return out
        # el MP4 lleva la mezcla en AAC (se copia tal cual); el audio suelto, en el formato elegido
        es = out_dir / f"{vid}.es.{quality}.{fmt if kind == 'es_audio' else 'm4a'}"
        mixed = 0.3 if height else 0.9  # parte del avance: la mezcla, y luego armar (o recodificar) el MP4
        if not es.exists():
            self._mix(vid, audio, es, prog if kind == "es_audio" else (lambda f: prog(f * mixed)), quality)
        if kind == "es_audio":
            return es
        tr = self.store.open(vid)
        orig = langs.get(tr.lang).iso3 if langs.is_source(tr.lang) else "und"
        subs = []
        for key, lang in (("translation", langs.get(langs.TARGET).iso3), ("text", orig)):
            f = out_dir / f"{vid}.{lang}.srt"
            f.write_text(srt(tr.segments, key), encoding="utf-8")
            subs.append((f, lang))
        out = out_dir / f"{vid}.es.{quality}.{video}.mp4"
        cmd = ["-i", str(media), "-i", str(es)]
        for f, _ in subs:
            cmd += ["-i", str(f)]
        cmd += ["-map", "0:v:0", "-map", "1:a", "-map", "0:a?", "-map", "2", "-map", "3",
                *(video_args(height) if height else ["-c:v", "copy"]), "-c:a:0", "copy",
                "-c:a:1", "aac", "-b:a:1", f"{ORIG_TRACK_KBPS[quality]}k", "-c:s", "mov_text",
                "-metadata:s:a:0", "language=spa", "-metadata:s:a:0", "title=Español",
                "-metadata:s:a:1", f"language={orig}", "-metadata:s:a:1", "title=Original",
                "-metadata:s:s:0", "language=spa", "-metadata:s:s:1", f"language={orig}",
                "-disposition:a:0", "default", "-disposition:a:1", "0", "-disposition:s:0", "0",
                "-disposition:s:1", "0", "-movflags", "+faststart", str(out)]
        step = lambda f: prog(mixed + (1 - mixed) * f)  # noqa: E731
        try:
            self._ffmpeg(cmd, step, dur)
        except subprocess.CalledProcessError:  # códec de video que MP4 no admite sin recodificar
            if height:
                raise
            i = cmd.index("-c:v")
            cmd[i:i + 2] = video_args(0)
            self._ffmpeg(cmd, step, dur)
        prog(1.0)
        return out

    @staticmethod
    def _ffmpeg(args: list[str], prog, dur: float):
        """ffmpeg con estos argumentos, informando el avance (convertir horas de audio o video tarda minutos)."""
        p = subprocess.Popen(["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        for line in p.stdout:
            if dur > 0 and line.startswith("out_time_us=") and line[12:].strip().isdigit():
                prog(min(1.0, int(line[12:]) / 1e6 / dur))
        err = p.stderr.read()
        if p.wait() != 0:
            raise subprocess.CalledProcessError(p.returncode, "ffmpeg", stderr=err)

    def _wait_summary(self, job, vid, title):
        """El resumen se hace antes de exportarlo, si aún no tiene (en la cola del resumen)."""
        if self.summaries is None or self.store.open(vid).data.get("summary"):
            return
        self._set(job, state="esperando", detail=f"{title} · resumiendo")
        if not self.summaries.request(vid) and not self.store.open(vid).data.get("summary"):
            raise ValueError("no tiene transcripción para resumir")
        while job in self.jobs:
            if self.store.open(vid).data.get("summary"):
                return
            err = self.summaries.error(vid)
            if err:
                raise RuntimeError(err)
            if self.summaries.state(vid) is None and not self.store.open(vid).data.get("summary"):
                raise RuntimeError("se canceló el resumen")  # sin trabajo ni resumen: no hay qué esperar
            time.sleep(1)

    def _make_text(self, kind, vid, v, out_dir: Path) -> Path:
        tr = self.store.open(vid)
        if kind == "summary":
            from .summarize import as_text
            out = out_dir / f"{vid}.resumen.txt"
            out.write_text(as_text(v.get("title") or vid, tr.data.get("summary") or {}), encoding="utf-8")
            return out
        if kind in ("txt_es", "txt_orig"):
            translated = kind == "txt_es" and tr.lang != langs.TARGET
            code = langs.TARGET if kind == "txt_es" else tr.lang or "orig"
            out = out_dir / f"{vid}.{code}.txt"
            out.write_text(plain_text(v.get("title") or vid, tr.segments, "translation" if translated else "text"),
                           encoding="utf-8")
            return out
        if kind in ("srt_es", "srt_orig"):
            out = out_dir / f"{vid}.{langs.TARGET if kind == 'srt_es' else tr.lang or 'orig'}.srt"
            translated = kind == "srt_es" and tr.lang != langs.TARGET
            out.write_text(srt(tr.segments, "translation" if translated else "text"), encoding="utf-8")
            return out
        # transcripción: hora · persona · lo que se dice / su traducción, y los comentarios de cada frase
        names = tr.data.get("speaker_names") or {}
        order: dict = {}
        for s in tr.segments:
            if s.get("speaker") is not None and s["speaker"] not in order:
                order[s["speaker"]] = len(order) + 1
        lines = [v.get("title") or vid, ""]
        for s in tr.segments:
            t = int(s["start"])
            stamp = f"{t // 3600}:{t // 60 % 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"
            who = ""
            if len(order) > 1 and s.get("speaker") is not None:
                who = " " + (names.get(str(s["speaker"])) or f"P{order[s['speaker']]}") + ":"
            lines.append(f"[{stamp}]{who} {s.get('text', '').strip()}")
            if s.get("translation") and tr.translates:
                lines.append(f"    {s['translation'].strip()}")
            for c in (tr.data.get("comments") or {}).get(str(s["id"]), []):
                lines.append(f"    » Comentario: {c['text']}")
            lines.append("")
        out = out_dir / f"{vid}.txt"
        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    def _mix(self, vid, src: Path, out: Path, prog, quality: str = "alta"):
        """Original (bajo la voz) + cada frase doblada en su momento → AAC, MP3 u Opus (según `out`)."""
        tr = self.store.open(vid)
        duck = DUCK_LEVELS.get(self.prefs.values.get("duck", "bajo"), 0.14)
        dub_dir = self._root(vid) / "audio"
        clips, prev_end = [], 0
        for s in sorted(tr.segments, key=lambda x: x["start"]):
            d = s.get("dub")
            f = dub_dir / d["file"] if d else None
            if not f or not f.exists():
                continue
            x, sr = read_wav(f)
            if x.ndim > 1:
                x = x.mean(axis=1)
            if sr != SR:
                x = resample(x.astype(np.float32), sr, SR)
            a = max(int(s["start"] * SR), prev_end)  # sin pisar la frase anterior
            clips.append((a, x.astype(np.float32)))
            prev_end = a + len(x)
        dur = float(json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(src)],
            capture_output=True, text=True, check=True).stdout)["format"]["duration"])
        total = int(dur * SR)
        # ganancia del original: baja bajo cada frase, con rampas de 120 ms
        ramp = int(0.12 * SR)
        regions = [(max(0, a - ramp), a + len(x) + ramp) for a, x in clips]
        dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(src), "-vn", "-f", "f32le", "-ac", "2",
                                "-ar", str(SR), "-"], stdout=subprocess.PIPE)
        enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR),
                                "-i", "-", *audio_args(out.suffix.lstrip("."), quality), str(out)], stdin=subprocess.PIPE)
        pos, ci, ri = 0, 0, 0
        try:
            while True:
                raw = dec.stdout.read(BLOCK * 8)
                if not raw:
                    break
                y = np.frombuffer(raw[: len(raw) // 8 * 8], np.float32).reshape(-1, 2).copy()
                n = len(y)
                g = np.ones(n, np.float32)
                while ri < len(regions) and regions[ri][1] < pos:
                    ri += 1
                k = ri
                while k < len(regions) and regions[k][0] < pos + n:
                    a, b = regions[k]
                    t = np.arange(pos, pos + n)
                    # 1 lejos de la frase, `duck` dentro, rampa lineal en los bordes
                    w = np.clip(np.minimum(t - a, b - t) / ramp, 0, 1)
                    g = np.minimum(g, 1 - (1 - duck) * w.astype(np.float32))
                    k += 1
                y *= g[:, None]
                while ci < len(clips) and clips[ci][0] + len(clips[ci][1]) < pos:
                    ci += 1
                k = ci
                while k < len(clips) and clips[k][0] < pos + n:
                    a, x = clips[k]
                    lo, hi = max(a, pos), min(a + len(x), pos + n)
                    if hi > lo:
                        y[lo - pos:hi - pos] += x[lo - a:hi - a, None]
                    k += 1
                np.clip(y, -1, 1, out=y)
                enc.stdin.write(y.tobytes())
                pos += n
                prog(min(1.0, pos / max(1, total)))
        finally:
            enc.stdin.close()
            enc.wait()
            dec.wait()
        if enc.returncode != 0:
            raise RuntimeError("no se pudo codificar el audio en español")
