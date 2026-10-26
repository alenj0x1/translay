"""Biblioteca: videos traducidos y colecciones.

data/library.json guarda:
  videos       id → {title, duration, source (file|youtube), media, audio, thumb,
                     channel, categories, added, opened, position}
  collections  [{id, name, items: [ids], created}]   (las que crea la persona)
               + {kind: "playlist", playlist, url, channel}  (playlists importadas de YouTube)

Los videos de una playlist se registran antes de descargarlos (sin `media`): la
cola los descarga en orden. Hasta tenerlos, solo aparecen en su playlist.

Las colecciones automáticas no se guardan: se calculan al pedir la biblioteca.
  recientes    los videos ya en el equipo, del último abierto al primero
  todos        todos los videos de la biblioteca, del último agregado al primero
  canal        una por canal de YouTube
  categoría    una por categoría de YouTube (nombres en español)
"""

import json
import re
import time
import uuid
from pathlib import Path

CATEGORIES_ES = {
    "Film & Animation": "Cine y animación", "Autos & Vehicles": "Autos y vehículos",
    "Music": "Música", "Pets & Animals": "Mascotas y animales", "Sports": "Deportes",
    "Travel & Events": "Viajes y eventos", "Gaming": "Videojuegos", "People & Blogs": "Personas y blogs",
    "Comedy": "Comedia", "Entertainment": "Entretenimiento", "News & Politics": "Noticias y política",
    "Howto & Style": "Tutoriales y estilo", "Education": "Educación",
    "Science & Technology": "Ciencia y tecnología", "Nonprofits & Activism": "ONG y activismo",
}

_FIELDS = ("title", "duration", "source", "media", "audio", "thumb", "channel", "categories")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


class Library:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"videos": {}, "collections": []}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            # miniaturas remotas de versiones anteriores → la copia local (se baja una sola vez)
            for vid, v in self.data["videos"].items():
                t = v.get("thumb") or ""
                if t.startswith("https://i.ytimg.com/vi/"):
                    v["thumb"] = f"/thumb/yt/{vid[3:]}.jpg"
        self._dirty_at = 0.0

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---------------------------------------------------------------- videos
    def register(self, vid: str, **info) -> dict:
        """Alta o actualización de un video (al abrirlo)."""
        v = self.data["videos"].setdefault(vid, {"id": vid, "added": time.time(), "position": 0})
        for k in _FIELDS:
            if info.get(k) not in (None, "", []):
                v[k] = info[k]
        v["opened"] = time.time()
        self.save()
        return v

    def set_field(self, vid: str, **kw):
        v = self.data["videos"].get(vid)
        if v:
            v.update(kw)
            self.save()

    def set_fields(self, changes: dict[str, dict]):
        """Varios videos de una vez (un solo guardado)."""
        for vid, kw in changes.items():
            if vid in self.data["videos"]:
                self.data["videos"][vid].update(kw)
        if changes:
            self.save()

    def position(self, vid: str, t: float):
        """Punto de reproducción (para continuar); se guarda como máximo cada 5 s."""
        v = self.data["videos"].get(vid)
        if not v:
            return
        v["position"] = round(t, 1)
        if time.time() - self._dirty_at > 5:
            self._dirty_at = time.time()
            self.save()

    def remove(self, vid: str):
        self.remove_many([vid])

    def remove_many(self, vids):
        vids = set(vids)
        for vid in vids:
            self.data["videos"].pop(vid, None)
        for c in self.data["collections"]:
            c["items"] = [i for i in c["items"] if i not in vids]
        self.save()

    def clear(self) -> list[str]:
        """Vacía la biblioteca: todos los videos y colecciones. Devuelve los ids borrados."""
        vids = list(self.data["videos"])
        self.data = {"videos": {}, "collections": []}
        self.save()
        return vids

    # ----------------------------------------------------------- colecciones
    def create(self, name: str) -> dict:
        c = {"id": uuid.uuid4().hex[:10], "name": name.strip()[:80] or "Sin nombre", "items": [],
             "created": time.time()}
        self.data["collections"].append(c)
        self.save()
        return c

    def rename(self, cid: str, name: str):
        for c in self.data["collections"]:
            if c["id"] == cid and name.strip():
                c["name"] = name.strip()[:80]
        self.save()

    def delete(self, cid: str) -> list[str]:
        """Borra la colección. Devuelve los videos que quedan huérfanos sin descargar
        (de una playlist): se quitan también de la biblioteca."""
        self.data["collections"] = [c for c in self.data["collections"] if c["id"] != cid]
        used = {i for c in self.data["collections"] for i in c["items"]}
        orphans = [vid for vid, v in self.data["videos"].items()
                   if v.get("source") == "youtube" and not v.get("media") and vid not in used]
        for vid in orphans:
            self.data["videos"].pop(vid, None)
        self.save()
        return orphans

    def add_pending(self, entries: list[dict]) -> list[str]:
        """Videos de YouTube aún sin descargar (enlaces sueltos): la cola los baja en orden."""
        now, out = time.time(), []
        for n, e in enumerate(entries):
            vid = "yt_" + e["id"]
            if vid not in self.data["videos"]:
                self.data["videos"][vid] = {"id": vid, "source": "youtube", "title": e.get("title") or e["id"],
                                            "duration": e.get("duration") or 0, "channel": e.get("channel", ""),
                                            "thumb": f"/thumb/yt/{e['id']}.jpg",  # se guarda al mostrarla
                                            "added": now - n * 1e-3, "position": 0}
            out.append(vid)
        self.save()
        return out

    def import_playlist(self, info: dict) -> dict:
        """Playlist de YouTube como colección (si ya existe, se actualiza con su orden actual)."""
        c = next((x for x in self.data["collections"] if x.get("playlist") == info["id"]), None)
        if c is None:
            c = {"id": uuid.uuid4().hex[:10], "kind": "playlist", "playlist": info["id"], "items": [],
                 "created": time.time()}
            self.data["collections"].append(c)
        c.update(name=info["title"][:120], url=info["url"], channel=info.get("channel", ""))
        now = time.time()
        for n, e in enumerate(info["entries"]):
            vid = "yt_" + e["id"]
            if vid not in self.data["videos"]:
                self.data["videos"][vid] = {"id": vid, "source": "youtube", "title": e["title"],
                                            "duration": e["duration"], "channel": e["channel"],
                                            "thumb": e["thumb"], "added": now - n * 1e-3, "position": 0}
        c["items"] = ["yt_" + e["id"] for e in info["entries"]]
        self.save()
        return c

    def toggle(self, cid: str, vid: str, on: bool):
        for c in self.data["collections"]:
            if c["id"] == cid:
                if on and vid not in c["items"]:
                    c["items"].insert(0, vid)
                elif not on:
                    c["items"] = [i for i in c["items"] if i != vid]
        self.save()

    # ----------------------------------------------------------------- vista
    def public(self) -> dict:
        videos = self.data["videos"]
        # recientes: lo que está en el equipo y lo recién importado (aún descargándose);
        # lo pendiente de una playlist queda solo en ella
        in_lists = {i for c in self.data["collections"] if c.get("kind") == "playlist" for i in c["items"]}
        recent = sorted((i for i in videos if videos[i].get("media") or i not in in_lists),
                        key=lambda i: -(videos[i].get("opened") or videos[i].get("added", 0)))
        # todos: cada video de la biblioteca (también lo pendiente de descargar), del último agregado al primero
        every = sorted(videos, key=lambda i: -videos[i].get("added", 0))
        auto = [{"id": "recent", "name": "Recientes", "kind": "auto", "items": recent},
                {"id": "all", "name": "Todos", "kind": "auto", "items": every}]
        channels, cats = {}, {}
        for vid in recent:
            v = videos[vid]
            if v.get("channel"):
                channels.setdefault(v["channel"], []).append(vid)
            for cat in v.get("categories") or []:
                cats.setdefault(CATEGORIES_ES.get(cat, cat), []).append(vid)
        auto += [{"id": "ch-" + _slug(n), "name": n, "kind": "canal", "items": i} for n, i in sorted(channels.items())]
        auto += [{"id": "cat-" + _slug(n), "name": n, "kind": "categoría", "items": i} for n, i in sorted(cats.items())]
        own = [{**c, "kind": c.get("kind", "propia"), "items": [i for i in c["items"] if i in videos]}
               for c in self.data["collections"]]
        return {"videos": videos, "collections": auto[:2] + own + auto[2:]}

    def import_youtube(self, root: Path):
        """Registra los videos de YouTube ya descargados (de antes de la biblioteca)."""
        changed = False
        for meta in root.glob("*.json"):
            info = json.loads(meta.read_text(encoding="utf-8"))
            vid = "yt_" + info["id"]
            if vid not in self.data["videos"]:
                self.data["videos"][vid] = {"id": vid, "source": "youtube", "added": meta.stat().st_mtime,
                                            "opened": meta.stat().st_mtime, "position": 0,
                                            **{k: info.get(k) for k in _FIELDS if info.get(k) is not None},
                                            "media": info.get("video")}
                changed = True
        if changed:
            self.save()
