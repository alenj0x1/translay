"""Almacenamiento: cuánto ocupa cada cosa de Translay y qué se puede liberar (Ajustes → Almacenamiento).

Por biblioteca
  originales     youtube/ y library/: lo descargado (o subido) de cada video. Se puede liberar lo de
                 YouTube o de un enlace (se vuelve a bajar al abrirlo o exportarlo): los que nunca se
                 tradujeron, o uno por uno desde «Lo que más ocupa». Lo subido desde el equipo no.
  doblajes       audio/: la voz en español, frase por frase
  textos         transcripciones, voces de cada video, personas, miniaturas y datos de YouTube
  papelera       papelera/ (se vacía sola a los 30 días; aquí, al momento)
  sueltos        archivos que ya no son de ningún video (un video borrado a mano, una descarga
                 cortada) y .tmp que quedaron de una escritura interrumpida. Las transcripciones
                 nunca: también las tiene lo que se abrió sin guardarlo en la biblioteca
De todo Translay
  exportaciones  data/exports: lo exportado para descargar (se borra solo a las 24 h)
  modelos        los de Translay en la caché de Hugging Face; el del perfil activo no se puede borrar
                 (los demás se vuelven a bajar si cambias de perfil o de idioma)
  instalación    la caché de paquetes de la app de escritorio (solo para reinstalar más rápido).
                 Comparte archivos con los entornos (enlaces duros): cuenta solo lo que se libera
  labs           data/labs: mediciones de desarrollo (tools/lab)

Al arrancar se borran solos los .tmp que quedaron (sweep_tmp); lo exportado para descargar
lo limpia vt/exporter.py. scan() es rápido (recorre carpetas); la caché de instalación se mide aparte, en segundo plano,
porque son cientos de miles de archivos. Nada se borra sin pasar por free().
"""

import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import modelset, modelusage
from .exporter import dir_size
from .modelusage import VOICE_REPOS  # noqa: F401 (vt/app.py lo usa desde aquí)

MEDIA_EXT = {".m4a", ".mp4", ".webm", ".mkv", ".mp3", ".opus", ".ogg", ".wav", ".mov", ".flac", ".aac", ".m4v"}
_TMP = re.compile(r"\.(tmp|part)$|\.[0-9a-f]{8}\.tmp$")
TMP_AGE = 3600  # un .tmp de hace más de una hora ya no lo está escribiendo nadie
LARGEST = 40


def known_models() -> dict[str, str]:
    """repo → nombre para mostrar, de todo lo que Translay puede bajar."""
    return {repo: m["label"] for repo, m in modelset.info().items()}


def hub_dir() -> Path:
    from huggingface_hub import constants
    return Path(constants.HF_HUB_CACHE)


model_path = modelset.path


def install_cache() -> Path | None:
    """La caché de uv de la app de escritorio (junto a sus entornos, TRANSLAY_VENVS)."""
    venvs = os.environ.get("TRANSLAY_VENVS")
    return Path(venvs).parent / "cache" if venvs else None


def unique_size(p: Path) -> int:
    """Bytes que se liberan al borrar p: sin los archivos que también están enlazados en otro lado."""
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                st = os.stat(os.path.join(root, f))
            except OSError:
                continue
            if st.st_nlink <= 1:
                total += st.st_size
    return total


def _files(d: Path):
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.is_file(follow_symlinks=False):
                    yield e
    except OSError:
        return


class Storage:
    def __init__(self, data: Path, vaults, processor=None, exporter=None, in_use=lambda: set()):
        self.data, self.vaults, self.processor, self.exporter = data, vaults, processor, exporter
        self.in_use = in_use  # repos que usa el perfil activo
        self._install: dict = {"bytes": None, "at": 0.0}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- medir
    def _busy(self, vid: str) -> bool:
        """En la cola o en una exportación que aún no termina: su original no se toca."""
        if self.exporter and vid in self.exporter.busy_videos():
            return True
        j = self.processor._job(vid) if self.processor else None
        return bool(j and j.get("state") not in ("listo", "error", "descargado"))

    def _vault(self, v) -> dict:
        videos = v.library.data["videos"]
        transcripts = {p.stem for p in (v.root / "transcripts").glob("*.json")}
        used: dict[str, str] = {}  # nombre de archivo en youtube/ o library/ → video
        for vid, x in videos.items():
            for f in ("media", "audio", "thumb"):
                if x.get(f):
                    used[Path(x[f].split("?")[0]).name] = vid
        media = {"bytes": 0, "count": 0}
        text = {"bytes": 0}
        free = {"bytes": 0, "count": 0}
        loose = {"bytes": 0, "count": 0}
        per_video: dict[str, int] = {}
        now = time.time()
        for sub in ("youtube", "library"):
            for e in _files(v.root / sub):
                size = e.stat().st_size
                ext = os.path.splitext(e.name)[1].lower()
                if _TMP.search(e.name):
                    if now - e.stat().st_mtime > TMP_AGE:
                        loose["bytes"] += size
                        loose["count"] += 1
                    continue
                if ext not in MEDIA_EXT:
                    text["bytes"] += size  # miniaturas y datos de YouTube
                    continue
                vid = used.get(e.name)
                if vid is None:  # de ningún video (no se cuenta lo que se está bajando)
                    stem = e.name.split(".")[0]
                    if not self._busy("yt_" + stem) and not self._busy(stem) and now - e.stat().st_mtime > TMP_AGE:
                        loose["bytes"] += size
                        loose["count"] += 1
                    continue
                media["bytes"] += size
                media["count"] += 1
                per_video[vid] = per_video.get(vid, 0) + size
        # los que se pueden liberar: de YouTube o de un enlace, sin traducir ni transcribir, fuera de la cola
        largest = []
        for vid, size in per_video.items():
            x = videos[vid]
            if x.get("source") not in ("youtube", "link"):
                continue
            done = vid in transcripts
            if not done and not self._busy(vid):
                free["bytes"] += size
                free["count"] += 1
            largest.append({"video": vid, "vault": v.id, "title": x.get("title") or vid, "bytes": size,
                            "duration": x.get("duration") or 0, "translated": done})
        dubs = dir_size(v.root / "audio") if (v.root / "audio").exists() else 0
        # doblajes de videos que ya no están (ni en la biblioteca ni con su transcripción)
        for d in self._orphan_dubs(v, videos, transcripts):
            n = dir_size(d)
            dubs -= n
            loose["bytes"] += n
            loose["count"] += 1
        for sub in ("transcripts", "voices", "people"):
            if (v.root / sub).exists():
                text["bytes"] += dir_size(v.root / sub)
        for e in _files(v.root):  # library.json.<x>.tmp y parecidos
            if _TMP.search(e.name) and now - e.stat().st_mtime > TMP_AGE:
                loose["bytes"] += e.stat().st_size
                loose["count"] += 1
        trash = dir_size(v.root / "papelera") if (v.root / "papelera").exists() else 0
        return {"id": v.id, "name": v.name, "path": str(v.root),
                "media": media, "free": free, "dubs": {"bytes": dubs}, "text": text,
                "trash": {"bytes": trash}, "loose": loose, "largest": largest}

    def scan(self) -> dict:
        libs = [self._vault(v) for v in self.vaults.all()]
        largest = sorted((x for lib in libs for x in lib.pop("largest")), key=lambda x: -x["bytes"])[:LARGEST]
        in_use = self.in_use()
        usage = modelusage.snapshot()
        models = []
        for repo, info in modelset.info().items():
            p = model_path(repo)
            if p.exists():
                models.append({"repo": repo, **info, "bytes": dir_size(p), "in_use": repo in in_use,
                               "used": usage["used"].get(repo), "downloaded": p.stat().st_mtime})
        # en uso; después lo usado alguna vez (lo más reciente primero); al final lo nunca usado, por tamaño
        models.sort(key=lambda m: (not m["in_use"], m["used"] is None, -(m["used"] or 0), -m["bytes"]))
        extra = {}
        if (self.data / "exports").exists():
            extra["exports"] = dir_size(self.data / "exports")
        if (self.data / "labs").exists():
            extra["labs"] = dir_size(self.data / "labs")
        if (self.data / "yt-session").exists():
            extra["session"] = dir_size(self.data / "yt-session")
        cache = install_cache()
        install = None
        if cache and cache.exists():
            install = self._install["bytes"]
            if install is None or time.time() - self._install["at"] > 600:
                install = None  # se mide en segundo plano (measure_install)
        disks = {}
        for p in [self.data, *[Path(lib["path"]) for lib in libs], hub_dir()] + ([cache] if cache else []):
            try:
                drive = Path(p).resolve().anchor or "/"
                if drive not in disks:
                    u = shutil.disk_usage(drive)
                    disks[drive] = {"path": drive, "total": u.total, "free": u.free}
            except OSError:
                pass
        return {"type": "storage", "usage_since": usage["since"], "libraries": libs, "largest": largest, "models": models, "extra": extra,
                "install": install, "has_install": bool(cache and cache.exists()), "disks": list(disks.values()),
                "at": time.time()}

    def measure_install(self) -> int | None:
        cache = install_cache()
        if not cache or not cache.exists():
            return None
        with self._lock:
            if self._install["bytes"] is None or time.time() - self._install["at"] > 600:
                self._install = {"bytes": unique_size(cache), "at": time.time()}
        return self._install["bytes"]

    def sweep_tmp(self) -> int:
        """Al arrancar: los .tmp de escrituras que se cortaron (library.json.<x>.tmp…), de más de una hora."""
        n = 0
        for v in self.vaults.all():
            for e in _files(v.root):
                if _TMP.search(e.name) and time.time() - e.stat().st_mtime > TMP_AGE:
                    try:
                        os.unlink(e.path)
                        n += 1
                    except OSError:
                        pass
        return n

    # ------------------------------------------------------------- liberar
    def free(self, what: str, vault: str = "", videos: list[str] | None = None, repo: str = "") -> int:
        """Borra una cosa y devuelve los bytes liberados. what: untranslated · videos · loose · trash ·
        exports · labs · model · unused_models · install."""
        if what in ("untranslated", "videos"):
            return self._free_media(what, vault, videos or [])
        if what == "loose":
            return sum(self._free_loose(v) for v in self.vaults.all() if not vault or v.id == vault)
        if what == "trash":
            from .trash import Trash
            freed = 0
            for v in self.vaults.all():
                if not vault or v.id == vault:
                    before = dir_size(v.root / "papelera") if (v.root / "papelera").exists() else 0
                    Trash(v.root).purge(everything=True)
                    freed += before - (dir_size(v.root / "papelera") if (v.root / "papelera").exists() else 0)
            return freed
        if what == "exports":
            return self.exporter.sweep(everything=True) if self.exporter else 0
        if what == "labs":
            return self._rmtree(self.data / "labs")
        if what == "unused_models":  # todos los que el perfil que corre no usa
            in_use = self.in_use()
            return sum(modelset.remove(r) for r in known_models() if r not in in_use)
        if what == "model":
            if repo not in known_models() or repo in self.in_use():
                raise ValueError("ese modelo está en uso")
            return self._rmtree(model_path(repo))
        if what == "install":
            cache = install_cache()
            if not cache:
                raise ValueError("solo en la app de escritorio")
            freed = unique_size(cache) if cache.exists() else 0
            shutil.rmtree(cache, ignore_errors=True)
            cache.mkdir(parents=True, exist_ok=True)
            self._install = {"bytes": 0, "at": time.time()}
            return freed
        raise ValueError("no sé qué liberar")

    def _orphan_dubs(self, v, videos, transcripts) -> list[Path]:
        d = v.root / "audio"
        return [x for x in (d.iterdir() if d.is_dir() else [])
                if x.is_dir() and x.name not in videos and x.name not in transcripts and not self._busy(x.name)]

    @staticmethod
    def _rmtree(p: Path) -> int:
        if not p.exists():
            return 0
        n = dir_size(p)
        shutil.rmtree(p, ignore_errors=True)
        return n - (dir_size(p) if p.exists() else 0)

    def _free_media(self, what: str, vault: str, only: list[str]) -> int:
        """Borra la copia en el equipo (el video queda en la biblioteca y se vuelve a bajar al abrirlo)."""
        freed = 0
        for v in self.vaults.all():
            if vault and v.id != vault:
                continue
            videos = v.library.data["videos"]
            transcripts = {p.stem for p in (v.root / "transcripts").glob("*.json")}
            changes = {}
            for vid, x in list(videos.items()):
                if not x.get("media") or x.get("source") not in ("youtube", "link") or self._busy(vid):
                    continue
                if what == "videos" and vid not in only:
                    continue
                if what == "untranslated" and vid in transcripts:
                    continue
                kept = False
                for f in {x.get("media"), x.get("audio")} - {None, ""}:
                    p = v.file(f)
                    if p and p.is_file() and p.suffix.lower() in MEDIA_EXT:
                        try:
                            size = p.stat().st_size
                            p.unlink()
                            freed += size
                        except OSError:  # en uso (se está reproduciendo): queda, y el video la sigue usando
                            kept = True
                if not kept:
                    changes[vid] = {"media": "", "audio": "", "audio_only": False}
            if changes:
                v.library.set_fields(changes)
        return freed

    def _free_loose(self, v) -> int:
        freed = 0
        now = time.time()
        videos = v.library.data["videos"]
        used = {Path(x[f].split("?")[0]).name for x in videos.values() for f in ("media", "audio", "thumb") if x.get(f)}

        def rm(p: Path):
            nonlocal freed
            try:
                n = dir_size(p)
                shutil.rmtree(p) if p.is_dir() else p.unlink()
                freed += n
            except OSError:
                pass

        for sub in ("youtube", "library"):
            for e in _files(v.root / sub):
                old = now - e.stat().st_mtime > TMP_AGE
                ext = os.path.splitext(e.name)[1].lower()
                stem = e.name.split(".")[0]
                if _TMP.search(e.name) and old:
                    rm(Path(e.path))
                elif ext in MEDIA_EXT and e.name not in used and old \
                        and not self._busy("yt_" + stem) and not self._busy(stem):
                    rm(Path(e.path))
        for d in self._orphan_dubs(v, videos, {p.stem for p in (v.root / "transcripts").glob("*.json")}):
            rm(d)
        for e in _files(v.root):
            if _TMP.search(e.name) and now - e.stat().st_mtime > TMP_AGE:
                rm(Path(e.path))
        return freed
