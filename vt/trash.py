"""Papelera: lo que se borra (videos, una biblioteca vaciada o eliminada) se guarda 30 días.

Nada se destruye al momento: los archivos se RENOMBRAN a la papelera, siempre dentro del
mismo disco (es instantáneo y no puede quedar a medias: si un archivo está en uso, ese
queda donde estaba y se anota), junto con lo necesario para devolverlos tal cual: datos
de cada video, colecciones en que estaba y, si se eliminó una biblioteca, su configuración.

  <biblioteca>/papelera/<id>/entry.json     qué es, cuándo, qué había
  <biblioteca>/papelera/<id>/files/…        los archivos, con su ruta relativa

Una biblioteca eliminada deja sus archivos en su propio disco
(<carpeta>/.translay-eliminada-<id>/) y su entrada en la papelera de Principal
(data/papelera), que es la que se lista. Al arrancar se vacía lo que tenga más de 30 días.
Nunca se borra una entrada que no se pudo devolver entera.
"""

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

KEEP_DAYS = 30
DIR = "papelera"
_TID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
_SAFE_VID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _rel_files(root: Path, vid: str) -> list[Path]:
    """Archivos de un video dentro de su biblioteca (rutas relativas a la biblioteca)."""
    out = []
    if not _SAFE_VID.match(vid):  # un id raro nunca apunta fuera de la biblioteca
        return out
    for rel in (Path("transcripts") / f"{vid}.json", Path("audio") / vid, Path("voices") / vid):
        if (root / rel).exists():
            out.append(rel)
    folder, stem = (Path("youtube"), vid[3:]) if vid.startswith("yt_") else (Path("library"), vid)
    if (root / folder).is_dir():
        out += [folder / f.name for f in (root / folder).glob(f"{stem}.*") if f.stem == stem]
    return out


def _rename(src: Path, dst: Path) -> bool:
    """Renombra (mismo disco: atómico). Si algo está en uso, no mueve nada y devuelve False."""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            os.replace(src, dst)
        else:
            os.rename(src, dst)
        return True
    except OSError:
        return False


def _write_json(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class Trash:
    def __init__(self, root: Path):
        self.root = root  # carpeta de la biblioteca
        self.dir = root / DIR

    # ------------------------------------------------------------- guardar
    def _new(self) -> tuple[str, Path]:
        tid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        d = self.dir / tid
        (d / "files").mkdir(parents=True, exist_ok=True)
        return tid, d

    def videos(self, vault, vids: list[str], cleared: bool = False) -> dict | None:
        """Mueve a la papelera los videos (datos + archivos). cleared: se vació toda la biblioteca."""
        lib = vault.library
        vids = [v for v in vids if v in lib.data["videos"]]
        if not vids:
            return None
        tid, d = self._new()
        moved, kept = [], []
        for vid in vids:
            vault.store.forget(vid)
            for rel in _rel_files(self.root, vid):
                name = str(rel).replace("\\", "/")
                (moved if _rename(self.root / rel, d / "files" / rel) else kept).append(name)
        entry = {
            "id": tid, "kind": "biblioteca-vaciada" if cleared else "videos", "created": time.time(),
            "vault": vault.id, "vault_name": vault.name, "count": len(vids),
            "title": (f"«{vault.name}» vaciada" if cleared else
                      (lib.data["videos"][vids[0]].get("title") or vids[0]) if len(vids) == 1 else f"{len(vids)} videos"),
            "videos": {v: lib.data["videos"][v] for v in vids},
            "memberships": {c["id"]: [i for i in c["items"] if i in vids] for c in lib.data["collections"]},
            "collections": [dict(c) for c in lib.data["collections"]] if cleared else [],
            "files": moved,
            "kept": kept,  # en uso al borrar: quedaron en su lugar
        }
        _write_json(d / "entry.json", entry)
        return entry

    def vault(self, v, own: tuple[str, ...]) -> dict:
        """Una biblioteca eliminada: sus archivos se renombran dentro de su propia carpeta (mismo
        disco, aunque sea externo) y la entrada va a esta papelera (la de Principal)."""
        tid, d = self._new()
        store = v.root / f".translay-eliminada-{tid}"
        store.mkdir(parents=True, exist_ok=True)
        moved, kept = [], []
        for name in (*own, DIR):  # también su propia papelera: vuelve con ella
            p = v.root / name
            if p.exists():
                (moved if _rename(p, store / name) else kept).append(name)
        entry = {"id": tid, "kind": "biblioteca", "created": time.time(), "vault": v.id, "vault_name": v.name,
                 "title": f"Biblioteca «{v.name}»", "root": str(v.root), "store": str(store),
                 "count": len(v.library.data["videos"]), "meta": v.meta, "files": moved, "kept": kept}
        _write_json(d / "entry.json", entry)
        return entry

    # ------------------------------------------------------------- consultar
    def entries(self) -> list[dict]:
        out = []
        if not self.dir.is_dir():
            return out
        for f in sorted(self.dir.glob("*/entry.json"), reverse=True):
            try:
                e = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for k in ("videos", "collections", "memberships", "meta"):
                e.pop(k, None)
            e["expires"] = e["created"] + KEEP_DAYS * 86400
            out.append(e)
        return out

    def _entry(self, tid: str) -> tuple[dict, Path]:
        d = self.dir / str(tid)
        if not _TID.match(str(tid)) or not (d / "entry.json").exists():
            raise ValueError("eso ya no está en la papelera")
        return json.loads((d / "entry.json").read_text(encoding="utf-8")), d

    # ------------------------------------------------------------- devolver
    def restore_videos(self, vault, tid: str, vaults=None) -> list[str]:
        """Devuelve los videos a su biblioteca, con sus archivos y colecciones. Si alguno ya volvió
        a estar en una biblioteca (lo importaste de nuevo), no se pisa: se avisa y la entrada queda."""
        e, d = self._entry(tid)
        lib = vault.library
        vids = list(e.get("videos", {}))
        clash = [vid for vid in vids
                 if vid in lib.data["videos"] or (vaults is not None and vaults.of(vid) not in (None, vault))]
        if clash:
            raise ValueError("Ya hay una copia nueva de " + ("ese video" if len(clash) == 1 else f"{len(clash)} de esos videos")
                             + " en tus bibliotecas: elimínala primero si quieres recuperar la de la papelera.")
        left = []
        for rel in e.get("files", []):
            src, dst = d / "files" / rel, self.root / rel
            if not src.exists():
                continue
            if dst.exists():  # algo lo recreó después de borrar (p. ej. una voz en camino): vale lo guardado
                shutil.rmtree(dst, ignore_errors=True) if dst.is_dir() else dst.unlink(missing_ok=True)
            if not _rename(src, dst):
                left.append(rel)
        for vid, meta in e.get("videos", {}).items():
            lib.data["videos"][vid] = meta
        have = {c["id"] for c in lib.data["collections"]}
        for c in e.get("collections", []):  # biblioteca vaciada: vuelven sus colecciones
            if c["id"] not in have:
                lib.data["collections"].append(c)
                have.add(c["id"])
        for c in lib.data["collections"]:
            for vid in e.get("memberships", {}).get(c["id"], []):
                if vid not in c["items"]:
                    c["items"].append(vid)
        lib.save()
        if left:  # en uso ahora: la entrada queda con lo que falta, para no perderlo
            e.update(files=left, videos={}, collections=[], memberships={}, title=e["title"] + " (archivos pendientes)")
            _write_json(d / "entry.json", e)
        else:
            shutil.rmtree(d, ignore_errors=True)
        return vids

    def restore_vault_files(self, tid: str) -> dict:
        """Devuelve los archivos de una biblioteca eliminada a su carpeta. Si en esa carpeta ya hay
        otra biblioteca (creaste una con el mismo nombre), se devuelve a <carpeta>-restaurada."""
        e, d = self._entry(tid)
        root = Path(e["root"])
        src_dir = Path(e["store"]) if e.get("store") else d / "files"
        if any((root / n).exists() for n in e.get("files", [])):
            base, n = Path(str(root) + "-restaurada"), 2
            alt = base
            while alt.exists() and any(alt.iterdir()):
                alt, n = Path(f"{base}-{n}"), n + 1
            root = alt
        root.mkdir(parents=True, exist_ok=True)
        left = [n for n in e.get("files", []) if (src_dir / n).exists() and not _rename(src_dir / n, root / n)]
        if left:
            raise ValueError("Algunos archivos de la biblioteca están en uso; cierra lo que los use y vuelve a intentar.")
        if e.get("store"):
            shutil.rmtree(src_dir, ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)
        e["root"] = str(root)
        return e

    # ------------------------------------------------------------- borrar del todo
    def purge(self, tid: str | None = None, everything: bool = False, older_than_days: float | None = None) -> int:
        """Borra para siempre: una entrada (tid), todas (everything) o las más viejas que N días.
        Sin ninguna de las tres, no borra nada."""
        if not self.dir.is_dir() or not (tid or everything or older_than_days is not None):
            return 0
        n = 0
        now = time.time()
        for d in [x for x in self.dir.iterdir() if x.is_dir() and _TID.match(x.name)]:
            try:
                e = json.loads((d / "entry.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # ilegible (p. ej. un corte de luz al escribirla): se mira la fecha de la carpeta
                e = {"id": d.name, "created": d.stat().st_mtime}
            if tid and e.get("id") != tid:
                continue
            if older_than_days is not None and now - e.get("created", now) < older_than_days * 86400:
                continue
            if e.get("store"):
                shutil.rmtree(e["store"], ignore_errors=True)
                try:
                    Path(e["root"]).rmdir()  # la carpeta de la biblioteca, si quedó vacía
                except OSError:
                    pass
            shutil.rmtree(d, ignore_errors=True)
            n += 1
        return n
