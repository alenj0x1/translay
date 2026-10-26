"""Bibliotecas: varias bibliotecas independientes, cada una en su propia carpeta.

Como las bóvedas de Obsidian: una biblioteca es una carpeta con todo lo suyo, y
puede estar en cualquier lugar (otro disco, por ejemplo):

  <carpeta>/vault.json      nombre, color, ícono y sus preferencias propias
  <carpeta>/library.json    videos y colecciones (vt/library.py)
  <carpeta>/glossary.json   su glosario (vt/glossary.py)
  <carpeta>/transcripts/    transcripciones        <carpeta>/youtube/   descargas
  <carpeta>/library/        archivos importados    <carpeta>/audio/     voz en español
  <carpeta>/voices/         voces de cada video    <carpeta>/people/    personas guardadas

La biblioteca «Principal» es data/ (lo de antes de haber bibliotecas sigue ahí,
sin mover nada). Lo global queda en data/: cola, cookies, preferencias generales
y la lista de bibliotecas (data/libraries.json).

Un video vive en una sola biblioteca (se puede mover a otra): así la cola, las
transcripciones y los archivos se ubican solo con su id.

Rutas en el navegador: lo de Principal se sirve como siempre (/media/yt/…,
/audio/…); lo de las demás, con el prefijo /v/<id>/ (ver Vault.url).
"""

import json
import re
import shutil
import threading
import time
import unicodedata
import uuid
from collections import ChainMap
from pathlib import Path

from .glossary import Glossary
from .library import Library
from .store import Store
from .youtube import YouTube

MAIN = "principal"
# preferencias propias de cada biblioteca (las demás son generales)
VAULT_PREFS = ("theme_mode", "import_mode", "download_what")
COLORS = ["#e4572e", "#f3a712", "#29bf12", "#00a5cf", "#7d5ba6", "#e84f9b", "#2b2d42", "#8d6e63"]
ICONS = ["library", "flask", "smile", "music", "book", "globe", "star", "film", "heart", "atom", "cap", "gamepad",
         "ball", "plane", "chat", "brush", "news", "paw"]
_PATTERN = re.compile(r"[a-z0-9]{0,12}")  # semilla del banner (web/js/patterns.js)
# subcarpetas que son de la biblioteca (al eliminarla se borra solo esto, nunca la carpeta entera)
OWN = ("vault.json", "library.json", "glossary.json", "transcripts", "youtube", "library", "audio", "voices",
       "people", "library.tmp", "glossary.tmp", "vault.tmp")
_ID = re.compile(r"^[a-z0-9-]{1,40}$")


class Vault:
    def __init__(self, vid: str, root: Path, cookies: Path, main: bool = False):
        self.id, self.root, self.main = vid, root, main
        root.mkdir(parents=True, exist_ok=True)
        self.meta_path = root / "vault.json"
        self.meta = {"name": "Principal" if main else root.name, "color": COLORS[0], "icon": "library", "prefs": {}}
        if self.meta_path.exists():
            try:
                self.meta.update(json.loads(self.meta_path.read_text(encoding="utf-8")))
            except ValueError:
                pass
        self.library = Library(root / "library.json")
        self.store = Store(root / "transcripts")
        self.youtube = YouTube(root / "youtube", cookies)
        self.glossary = Glossary(root / "glossary.json")
        self.prefix = "" if main else f"/v/{vid}"
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.meta["name"]

    def save_meta(self):
        with self._lock:
            tmp = self.root / "vault.tmp"
            tmp.write_text(json.dumps({**self.meta, "id": self.id}, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.meta_path)

    # ------------------------------------------------------------------ rutas
    def url(self, u: str) -> str:
        """Ruta de un archivo de la biblioteca para el navegador."""
        if u and self.prefix and u.startswith(("/media/", "/audio/", "/voices/", "/people/")):
            return self.prefix + u
        return u

    def file(self, u: str) -> Path | None:
        """Archivo en disco de una ruta /media/yt/…, /media/lib/…, /audio/…, /voices/…, /people/…"""
        u = (u or "").split("?")[0]
        for pre, sub in (("/media/yt/", "youtube"), ("/media/lib/", "library"), ("/audio/", "audio"),
                         ("/voices/", "voices"), ("/people/", "people")):
            if u.startswith(pre):
                base = (self.root / sub).resolve()
                f = (base / u[len(pre):]).resolve()
                return f if f.is_relative_to(base) else None
        return None

    def public_library(self) -> dict:
        data = self.library.public()
        if self.prefix:  # las rutas de los archivos, con el prefijo de la biblioteca
            data["videos"] = {k: {**v, **{f: self.url(v[f]) for f in ("media", "audio", "thumb") if v.get(f)}}
                              for k, v in data["videos"].items()}
        return data

    def info(self) -> dict:
        vids = self.library.data["videos"]
        return {"id": self.id, "name": self.name, "color": self.meta.get("color"), "icon": self.meta.get("icon"),
                "pattern": self.meta.get("pattern", ""),
                "path": str(self.root), "main": self.main, "count": len(vids),
                "access": {"mode": (self.meta.get("access") or {}).get("mode", "privada"),
                           "perm": (self.meta.get("access") or {}).get("perm", "ver"),
                           "has_pw": bool((self.meta.get("access") or {}).get("pw"))},
                "downloaded": sum(1 for v in vids.values() if v.get("media"))}

    # ------------------------------------------------------- personas guardadas
    def people(self) -> list[dict]:
        f = self.root / "people" / "people.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except ValueError:
            return []

    def save_person(self, name: str, wav: Path, text: str, pid: str | None = None) -> dict:
        """Guarda a una persona (nombre y su voz) para usarla en cualquier video de la biblioteca."""
        d = self.root / "people"
        d.mkdir(parents=True, exist_ok=True)
        items = self.people()
        p = next((x for x in items if x["id"] == pid), None) if pid else None
        if p is None:
            p = {"id": uuid.uuid4().hex[:8]}
            items.append(p)
        file = f"{p['id']}_{int(time.time())}.wav"
        shutil.copyfile(wav, d / file)
        if p.get("file"):
            (d / p["file"]).unlink(missing_ok=True)
        p.update(name=name.strip()[:60] or "Sin nombre", file=file, text=text)
        (d / "people.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def forget_person(self, pid: str):
        d = self.root / "people"
        items = self.people()
        for p in items:
            if p["id"] == pid and p.get("file"):
                (d / p["file"]).unlink(missing_ok=True)
        items = [p for p in items if p["id"] != pid]
        if d.exists():
            (d / "people.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def person_ref(self, pid: str) -> tuple[str | None, str | None]:
        p = next((x for x in self.people() if x["id"] == pid), None)
        if not p:
            return None, None
        f = self.root / "people" / p["file"]
        return (str(f), p.get("text", "")) if f.exists() else (None, None)


class Vaults:
    def __init__(self, data: Path):
        self.data = data
        self.cookies = data / "cookies.txt"
        self.path = data / "libraries.json"
        self._lock = threading.RLock()
        saved = {"list": [], "last": MAIN}
        if self.path.exists():
            try:
                saved.update(json.loads(self.path.read_text(encoding="utf-8")))
            except ValueError:
                pass
        self.last = saved.get("last") or MAIN
        self._vaults: dict[str, Vault] = {MAIN: Vault(MAIN, data, self.cookies, main=True)}
        for e in saved["list"]:
            if e.get("id") != MAIN and _ID.match(e.get("id", "")):
                try:
                    self._vaults[e["id"]] = Vault(e["id"], Path(e["path"]), self.cookies)
                except OSError as ex:  # p. ej. un disco externo desconectado
                    print(f"[bibliotecas] {e.get('path')}: {ex}", flush=True)
        if self.last not in self._vaults:
            self.last = MAIN
        self.store = RoutedStore(self, lambda: self.main)
        self.library = RoutedLibrary(self)

    def _save(self):
        with self._lock:
            out = {"list": [{"id": v.id, "path": str(v.root)} for v in self._vaults.values() if not v.main],
                   "last": self.last}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    @property
    def main(self) -> Vault:
        return self._vaults[MAIN]

    def all(self) -> list[Vault]:
        return list(self._vaults.values())

    def get(self, vid: str | None) -> Vault | None:
        return self._vaults.get(vid or "")

    def of(self, video: str) -> Vault | None:
        """La biblioteca donde está un video."""
        for v in self._vaults.values():
            if video in v.library.data["videos"]:
                return v
        return None

    def public(self) -> list[dict]:
        return [v.info() for v in self._vaults.values()]

    def set_last(self, vid: str):
        if vid in self._vaults and vid != self.last:
            self.last = vid
            self._save()

    # ---------------------------------------------------------- administrar
    def create(self, name: str, folder: str = "", color: str = "", icon: str = "", prefs: dict | None = None,
               pattern: str = "") -> Vault:
        name = (name or "").strip()[:60] or "Biblioteca"
        with self._lock:
            plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()  # Océanos → oceanos
            vid = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:24] or "biblioteca"
            base, n = vid, 2
            while vid in self._vaults:
                vid, n = f"{base}-{n}", n + 1
            root = Path(folder).expanduser() if folder else self.data / "libraries" / vid
            if not root.is_absolute():
                raise ValueError("la carpeta debe ser una ruta completa (p. ej. D:\\Videos\\Ciencia)")
            root = root.resolve()
            if any(v.root.resolve() == root for v in self._vaults.values()):
                raise ValueError("esa carpeta ya es una biblioteca")
            if root.exists() and (root / "library.json").exists():
                raise ValueError("esa carpeta ya tiene una biblioteca: usa «Abrir carpeta»")
            v = Vault(vid, root, self.cookies)
            v.meta.update(name=name, color=color if color in COLORS else COLORS[len(self._vaults) % len(COLORS)],
                          icon=icon if icon in ICONS else "library", prefs=dict(prefs or {}),
                          pattern=pattern if _PATTERN.fullmatch(pattern or "") else "")
            v.save_meta()
            v.library.save()
            self._vaults[vid] = v
            self._save()
            return v

    def open_folder(self, folder: str) -> Vault:
        """Una carpeta que ya es biblioteca (p. ej. de otro equipo o de un disco externo)."""
        root = Path(folder).expanduser()
        if not root.is_absolute() or not (root / "library.json").exists():
            raise ValueError("esa carpeta no tiene una biblioteca (falta library.json)")
        root = root.resolve()
        with self._lock:
            hit = next((v for v in self._vaults.values() if v.root.resolve() == root), None)
            if hit:
                return hit
            meta = {}
            try:
                meta = json.loads((root / "vault.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            vid = meta.get("id") if _ID.match(str(meta.get("id", ""))) and meta.get("id") != MAIN else ""
            base = vid or re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-")[:24] or "biblioteca"
            vid, n = base, 2
            while vid in self._vaults:
                vid, n = f"{base}-{n}", n + 1
            v = Vault(vid, root, self.cookies)
            # un video ya presente en otra biblioteca queda donde estaba
            dup = [k for k in v.library.data["videos"] if self.of(k)]
            if dup:
                v.library.remove_many(dup)
            v.save_meta()
            self._vaults[vid] = v
            self._save()
            return v

    def update(self, vid: str, **kw) -> Vault:
        v = self._vaults[vid]
        if kw.get("name", "").strip():
            v.meta["name"] = kw["name"].strip()[:60]
        if kw.get("color") in COLORS:
            v.meta["color"] = kw["color"]
        if kw.get("icon") in ICONS:
            v.meta["icon"] = kw["icon"]
        if kw.get("pattern") is not None and _PATTERN.fullmatch(kw["pattern"]):
            v.meta["pattern"] = kw["pattern"]
        v.save_meta()
        return v

    def set_pref(self, vid: str, key: str, value):
        v = self._vaults[vid]
        v.meta.setdefault("prefs", {})[key] = value
        v.save_meta()

    def remove(self, vid: str, delete_files: bool = False) -> list[str]:
        """Quita la biblioteca de la lista (sus archivos quedan) o la elimina con sus archivos.
        Devuelve sus videos (para quitarlos de la cola)."""
        if vid == MAIN or vid not in self._vaults:
            raise ValueError("la biblioteca Principal no se puede quitar")
        with self._lock:
            v = self._vaults.pop(vid)
            if self.last == vid:
                self.last = MAIN
            self._save()
        vids = list(v.library.data["videos"])
        for t in v.store._cache.values():
            t.deleted = True
        if delete_files:
            for name in OWN:  # solo lo de la biblioteca: la carpeta puede tener otras cosas
                p = v.root / name
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            try:
                v.root.rmdir()  # vacía: también se quita
            except OSError:
                pass
        return vids

    def move(self, videos: list[str], dest_id: str, busy=lambda vid: False) -> tuple[int, int]:
        """Mueve videos (con sus archivos) a otra biblioteca. Devuelve (movidos, saltados)."""
        dest = self._vaults[dest_id]
        moved = skipped = 0
        for video in videos:
            src = self.of(video)
            if src is None or src is dest:
                continue
            if busy(video):  # descargándose o procesándose: se deja para no cortar el trabajo
                skipped += 1
                continue
            t = src.store._cache.pop(video, None)
            if t:
                t.save()
                t.deleted = True  # otra pestaña que lo tenga abierto ya no escribe en la carpeta vieja
            files = [(src.root / "transcripts" / f"{video}.json", dest.root / "transcripts"),
                     (src.root / "audio" / video, dest.root / "audio"),
                     (src.root / "voices" / video, dest.root / "voices")]
            folder, stem = (("youtube", video[3:]) if video.startswith("yt_") else ("library", video))
            files += [(f, dest.root / folder) for f in (src.root / folder).glob(f"{glob_escape(stem)}.*")
                      if f.stem == stem]
            for f, to in files:
                if f.exists():
                    to.mkdir(parents=True, exist_ok=True)
                    target = to / f.name
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink()
                    shutil.move(str(f), str(target))
            entry = src.library.data["videos"].get(video)
            if entry:
                dest.library.data["videos"][video] = entry
            src.library.remove_many([video])
            moved += 1
        if moved:
            dest.library.save()
        return moved, skipped


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


class RoutedStore:
    """Transcripciones de cualquier biblioteca: cada video se abre en la suya.
    Lo que no es de un video (root, _cache) es de la biblioteca por defecto."""

    def __init__(self, vaults: Vaults, default):
        self.vaults, self.default = vaults, default

    def _for(self, vid: str) -> Vault:
        return self.vaults.of(vid) or self.default()

    def open(self, vid: str, name: str = ""):
        return self._for(vid).store.open(vid, name)

    def delete(self, vid: str):
        self._for(vid).store.delete(vid)

    @property
    def root(self) -> Path:
        return self.default().store.root

    @property
    def _cache(self) -> dict:
        return self.default().store._cache


class RoutedLibrary:
    """Los videos de todas las bibliotecas, para la cola y la exportación (que solo usan ids)."""

    def __init__(self, vaults: Vaults):
        self.vaults = vaults

    @property
    def data(self) -> dict:
        return {"videos": ChainMap(*[v.library.data["videos"] for v in self.vaults.all()])}

    def set_field(self, vid: str, **kw):
        v = self.vaults.of(vid)
        if v:
            v.library.set_field(vid, **kw)

    def set_fields(self, changes: dict):
        by: dict = {}
        for vid, kw in changes.items():
            v = self.vaults.of(vid)
            if v:
                by.setdefault(v.id, {})[vid] = kw
        for k, ch in by.items():
            self.vaults.get(k).library.set_fields(ch)

    def position(self, vid: str, t: float):
        v = self.vaults.of(vid)
        if v:
            v.library.position(vid, t)
