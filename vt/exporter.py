"""Exportar: video o audio traducido (y el original) de uno o varios videos.

Tipos
  es_video    MP4 con la voz en español (pista principal), el inglés como segunda
              pista y subtítulos ES/EN (se activan en el reproductor)
  es_audio    M4A con la voz en español
  orig_video  el video original
  orig_audio  el audio original

La mezcla en español es la misma que se escucha en la vista: cada frase doblada
en su momento y el original bajo la voz (nivel de Preferencias). Donde no hay
voz, el original queda a volumen normal. Se arma por bloques (un video largo no
pasa entero por memoria) con ffmpeg en la CPU: no usa la GPU.

Lo traducido espera a que el doblaje termine (el video entra a la cola si
hace falta). Un solo archivo se entrega tal cual; varios, en un .zip.
"""

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path

import numpy as np

from . import events
from .audiofx import read_wav, resample

SR = 48000
BLOCK = SR * 10
DUCK_LEVELS = {"silencio": 0.0, "bajo": 0.14, "medio": 0.3}
# texto: subtítulos (SRT) y transcripción bilingüe con comentarios (TXT); no necesitan el doblaje
TEXT_KINDS = ("srt_es", "srt_en", "txt")
KINDS = {"es_video": ("español", "mp4"), "es_audio": ("español", "m4a"),
         "srt_es": ("subtítulos español", "srt"), "srt_en": ("subtítulos inglés", "srt"),
         "txt": ("transcripción", "txt"),
         "orig_video": ("original", "mp4"), "orig_audio": ("audio original", "m4a")}


def safe_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "video")
    return re.sub(r"\s+", " ", text).strip(" .")[:110] or "video"


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


class Exporter:
    def __init__(self, root: Path, store, library, processor, youtube, prefs, notify, vaults=None):
        self.root = root
        self.vaults = vaults
        self.dir = root / "exports"
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.iterdir():  # lo de sesiones anteriores ya se descargó
            if time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
        self.store, self.library, self.processor = store, library, processor
        self.youtube, self.prefs, self.notify = youtube, prefs, notify
        self.jobs: list[dict] = []
        self._cond = threading.Condition()
        self._last = 0.0
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------------ API
    def add(self, videos: list[str], kinds: list[str], name: str = "") -> dict:
        videos = [v for v in dict.fromkeys(videos) if v in self.library.data["videos"]]
        kinds = [k for k in KINDS if k in kinds]
        if not videos or not kinds:
            raise ValueError("nada que exportar")
        if not name:
            name = self.library.data["videos"][videos[0]].get("title", "video") if len(videos) == 1 else "videos"
        job = {"id": uuid.uuid4().hex[:10], "name": name, "videos": videos, "kinds": kinds,
               "state": "en espera", "pct": 0, "detail": "", "url": "", "error": "", "added": time.time()}
        with self._cond:
            self.jobs.append(job)
            self._cond.notify_all()
        self._broadcast(force=True)
        return job

    def remove(self, jid: str):
        with self._cond:
            self.jobs = [j for j in self.jobs if j["id"] != jid]
        self._broadcast(force=True)

    def public(self) -> dict:
        return {"type": "exports", "jobs": [{k: j[k] for k in ("id", "name", "state", "pct", "detail", "url", "error")}
                                            | {"count": len(j["videos"])} for j in self.jobs]}

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
                    self._cond.wait()
            try:
                self._run(job)
            except Exception as e:
                import traceback

                traceback.print_exc()
                self._set(job, state="error", error=str(e)[:200])
                events.emit("exportacion.error", self._job_vault(job), job=job["id"], name=job["name"], error=job["error"])

    def _run(self, job):
        out_dir = self.dir / job["id"]
        out_dir.mkdir(exist_ok=True)
        files: list[tuple[Path, str]] = []  # (archivo, nombre al descargar)
        total = len(job["videos"]) * len(job["kinds"])
        done = 0
        for vid in job["videos"]:
            if job not in self.jobs:
                return
            v = self.library.data["videos"][vid]
            title = safe_name(v.get("title") or vid)
            if any(k not in TEXT_KINDS for k in job["kinds"]):  # solo texto: no hace falta el archivo
                self._ensure_media(job, vid, video=any(k in ("es_video", "orig_video") for k in job["kinds"]))
            v = self.library.data["videos"][vid]
            if any(k.startswith("es_") for k in job["kinds"]):
                self._wait_dub(job, vid, title)
            elif any(k in TEXT_KINDS for k in job["kinds"]):
                self._wait_dub(job, vid, title, key="asr")  # el texto necesita la transcripción completa
            for kind in job["kinds"]:
                label, ext = KINDS[kind]

                def prog(f, done=done):
                    self._set(job, pct=round((done + f) / total * 100))

                self._set(job, state="exportando", detail=f"{title} · {label}")
                path = self._make(kind, vid, v, out_dir, prog)
                if kind == "orig_video":
                    ext = path.suffix.lstrip(".")
                files.append((path, f"{title} ({label}).{ext}" if kind != "orig_video" else f"{title}.{ext}"))
                done += 1
                self._set(job, pct=round(done / total * 100))
        if len(files) == 1:
            path, name = files[0]
        else:  # varios: un .zip sin comprimir (video y audio ya vienen comprimidos)
            self._set(job, detail="armando el .zip")
            name = safe_name(job["name"]) + ".zip"
            path = out_dir / "export.zip"
            used = set()
            with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
                for f, arc in files:
                    stem, ext, n = arc.rsplit(".", 1)[0], arc.rsplit(".", 1)[1], 2
                    while arc in used:
                        arc, n = f"{stem} ({n}).{ext}", n + 1
                    used.add(arc)
                    z.write(f, arc)
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
            return self.root / "youtube" / src[10:]
        if src.startswith("/media/lib/"):
            return self.root / "library" / src[11:]
        raise FileNotFoundError("el video no tiene copia en el equipo")

    def _ensure_media(self, job, vid, video: bool = False):
        """Copia en el equipo; si solo se bajó el audio y se pide un video, se baja el video completo."""
        v = self.library.data["videos"][vid]
        if v.get("media") and not (video and v.get("audio_only")):
            return
        if v.get("source") != "youtube" or not self.youtube:
            raise FileNotFoundError(f"«{v.get('title', vid)}» no tiene copia en el equipo")
        self._set(job, state="exportando", detail=f"descargando {v.get('title', vid)}")
        vault = self.vaults.of(vid) if self.vaults else None
        info = (vault or self).youtube.fetch(vid[3:], None, self.prefs.values.get("yt_session", "ninguna"),
                                             audio_only=False)
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
    def _make(self, kind, vid, v, out_dir: Path, prog) -> Path:
        if kind in TEXT_KINDS:
            return self._make_text(kind, vid, v, out_dir)
        media = self._media_path(v["media"], vid)
        audio = self._media_path(v["audio"], vid) if v.get("audio") else media
        if kind == "orig_video":
            return media
        if kind == "orig_audio":
            if audio.suffix == ".m4a":
                return audio
            out = out_dir / f"{vid}.orig.m4a"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-vn", "-c:a", "aac",
                            "-b:a", "160k", str(out)], check=True)
            return out
        es = out_dir / f"{vid}.es.m4a"
        if not es.exists():
            self._mix(vid, audio, es, prog if kind == "es_audio" else (lambda f: prog(f * 0.9)))
        if kind == "es_audio":
            return es
        tr = self.store.open(vid)
        subs = []
        for key, lang in (("translation", "spa"), ("text", "eng")):
            f = out_dir / f"{vid}.{lang}.srt"
            f.write_text(srt(tr.segments, key), encoding="utf-8")
            subs.append((f, lang))
        out = out_dir / f"{vid}.es.mp4"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-i", str(es)]
        for f, _ in subs:
            cmd += ["-i", str(f)]
        cmd += ["-map", "0:v:0", "-map", "1:a", "-map", "0:a?", "-map", "2", "-map", "3",
                "-c:v", "copy", "-c:a:0", "copy", "-c:a:1", "aac", "-b:a:1", "128k", "-c:s", "mov_text",
                "-metadata:s:a:0", "language=spa", "-metadata:s:a:0", "title=Español",
                "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=Original",
                "-metadata:s:s:0", "language=spa", "-metadata:s:s:1", "language=eng",
                "-disposition:a:0", "default", "-disposition:a:1", "0", "-disposition:s:0", "0",
                "-disposition:s:1", "0", "-movflags", "+faststart", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:  # códec de video que MP4 no admite sin recodificar
            i = cmd.index("-c:v")
            cmd[i + 1] = "libx264"
            cmd[i + 2:i + 2] = ["-preset", "veryfast", "-crf", "21"]
            subprocess.run(cmd, check=True, capture_output=True)
        prog(1.0)
        return out

    def _make_text(self, kind, vid, v, out_dir: Path) -> Path:
        tr = self.store.open(vid)
        if kind in ("srt_es", "srt_en"):
            out = out_dir / f"{vid}.{kind}.srt"
            out.write_text(srt(tr.segments, "translation" if kind == "srt_es" else "text"), encoding="utf-8")
            return out
        # transcripción bilingüe: hora · persona · inglés / español, y los comentarios de cada frase
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
            if s.get("translation"):
                lines.append(f"    {s['translation'].strip()}")
            for c in (tr.data.get("comments") or {}).get(str(s["id"]), []):
                lines.append(f"    » Comentario: {c['text']}")
            lines.append("")
        out = out_dir / f"{vid}.txt"
        out.write_text("\n".join(lines), encoding="utf-8")
        return out

    def _mix(self, vid, src: Path, out: Path, prog):
        """Original (bajo la voz) + cada frase doblada en su momento → AAC."""
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
                                "-i", "-", "-c:a", "aac", "-b:a", "160k", str(out)], stdin=subprocess.PIPE)
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
