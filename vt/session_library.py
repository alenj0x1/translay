"""La biblioteca desde la pestaña: lista y portada, búsqueda, glosario, personas y voces,
comentarios, borrar y exportar.

Parte de Session (vt/session.py): sus métodos usan el estado de la sesión (self)."""

import asyncio
import json
from functools import partial
from pathlib import Path
from . import events, i18n
from .store import _SAFE_ID as _SAFE_VID
from .dialogs import _dialog_available, pick_folder, pick_save, reveal


class LibraryMixin:
    # ------------------------------------------------------------ búsqueda
    async def _search(self, q: str):
        """Busca en todas las transcripciones (inglés, español y comentarios), sin tildes ni mayúsculas."""
        import unicodedata

        def norm(t: str) -> str:
            return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")

        needle = norm(q.strip())
        if len(needle) < 2:
            return await self.ws.send_json({"type": "search_results", "q": q, "results": [], "total": 0})

        def run():
            results, total = [], 0
            for f in sorted(self.store.root.glob("*.json")):
                vid = f.stem
                if vid not in self.library.data["videos"]:
                    continue
                tr = self.store._cache.get(vid)
                data = tr.data if tr else json.loads(f.read_text(encoding="utf-8"))
                comments = data.get("comments") or {}
                hits = []
                for s in data.get("segments", []):
                    notes = " ".join(c["text"] for c in comments.get(str(s["id"]), []))
                    field = ("en" if needle in norm(s.get("text")) else "es" if needle in norm(s.get("translation"))
                             else "nota" if notes and needle in norm(notes) else None)
                    if field:
                        total += 1
                        if len(hits) < 20:
                            hits.append({"seg": s["id"], "t": s["start"], "field": field, "text": s.get("text", ""),
                                         "translation": s.get("translation") or "", "note": notes if field == "nota" else ""})
                if hits:
                    results.append({"video": vid, "hits": hits})
            results.sort(key=lambda r: -len(r["hits"]))
            return results[:100], total

        results, total = await asyncio.get_running_loop().run_in_executor(None, run)
        await self.ws.send_json({"type": "search_results", "q": q, "results": results, "total": total})

    # ------------------------------------------------------------- glosario
    async def _glossary(self, m: dict):
        gl = getattr(self, "glossary", None)
        if gl is None:
            return
        if m["type"] == "glossary_set":
            old, new = gl.set(m.get("entries") or [])
            self.notify({"type": "glossary", "entries": gl.entries, "vault": self.vault.id})
            events.emit("glosario.cambio", self.vault.id, entries=gl.entries)
            # frases afectadas por lo que cambió: se vuelven a traducir (y su voz se rehace en la cola)
            changed = [e for e in new if e not in old] + [e for e in old if e not in new]
            if changed:
                asyncio.create_task(self._retranslate(changed))
        else:
            await self.ws.send_json({"type": "glossary", "entries": gl.entries, "vault": self.vault.id})

    async def _retranslate(self, changed: list[dict]):
        loop = asyncio.get_running_loop()
        vault = self.vault
        gl = vault.glossary
        n_segs = n_vids = 0
        for f in sorted(vault.store.root.glob("*.json")):
            vid = f.stem
            if vid not in vault.library.data["videos"]:
                continue
            tr = vault.store.open(vid)
            if tr.transcribe_only:  # no pasa por el traductor
                continue
            await loop.run_in_executor(None, self.translator.prepare, tr.lang)  # fuera del hilo de la GPU
            # lo corregido a mano en el editor de frases no se pisa
            todo = [s for s in tr.segments if gl.matches(s.get("text", ""), changed) and not s.get("manual")]
            if not todo:
                continue
            tx = partial(self.translator.translate_many, glossary=gl, src=tr.lang)
            outs = await loop.run_in_executor(self.gpu, self.res.run, ("mt",), tx, [s["text"] for s in todo])
            for s, es in zip(todo, outs):
                tr.set_translation(s["id"], es, self.translator.name_for(tr.lang))
            tr.save()
            n_segs += len(todo)
            n_vids += 1
            if self.dubber and self.tr is tr:
                # el video abierto en esta pestaña: su voz nueva enseguida, como en el editor (la cola, si lo está
                # procesando más adelante, recién vuelve a esas frases al terminarlo)
                self._queue_stale_dubs(tr)
            elif self.processor and any(s.get("dub") for s in tr.segments):
                self.processor.add(vid)  # la voz de esas frases se rehace
            self.notify({"type": "bg", "video": vid, "msg": {"type": "translations",
                         "items": [{"id": s["id"], "translation": s.get("translation")} for s in todo]}})
        self.notify({"type": "glossary_applied", "segments": n_segs, "videos": n_vids})

    # ------------------------------------------------------------- personas
    async def _people(self, m: dict):
        """Nombre de una persona del video y la voz que usa (la suya o la de otra persona)."""
        vid, spk = str(m.get("video", "")), str(m.get("spk", ""))
        tr = self.store.open(vid)
        names = tr.data.setdefault("speaker_names", {})
        vmap = tr.data.setdefault("voice_map", {})
        if "name" in m:
            name = str(m["name"]).strip()[:60]
            if name:
                names[spk] = name
            else:
                names.pop(spk, None)
        redub = 0
        if "voice" in m:
            voice = str(m["voice"] or "")
            if voice in ("", spk):
                changed = vmap.pop(spk, None) is not None
            else:
                changed = vmap.get(spk) != voice
                vmap[spk] = voice
            if changed:  # su voz se rehace en la cola
                for s in tr.segments:
                    if str(s.get("speaker")) == spk and s.pop("dub", None) is not None:
                        redub += 1
                if redub and self.processor:
                    self.processor.add(vid)
        tr.save()
        self.notify({"type": "bg", "video": vid, "msg": {"type": "people", "speaker_names": names,
                                                           "voice_map": vmap, "redub": redub}})

    def _voice_meta(self, vid: str) -> dict:
        meta = self._vault_of(vid).root / "voices" / vid / "voices.json"
        try:
            return json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        except ValueError:
            return {}

    def _voice_refs(self, vid: str) -> dict:
        vault = self._vault_of(vid)
        return {spk: vault.url(f"/voices/{vid}/{m['file']}") for spk, m in self._voice_meta(vid).items() if m.get("file")}

    def _people_saved(self, vault=None) -> list[dict]:
        vault = vault or self.vault
        return [{**p, "url": vault.url(f"/people/{p['file']}")} for p in vault.people()]

    async def _people_saved_op(self, m: dict):
        """Guardar a una persona de un video (nombre y voz) en su biblioteca, u olvidarla."""
        if m["type"] == "people_save":
            vid, spk = str(m.get("video", "")), str(m.get("spk", ""))
            vault = self._vault_of(vid)
            ref = self._voice_meta(vid).get(spk)
            if not ref:
                return await self.ws.send_json({"type": "yt_error", "error": i18n.t("Esta persona aún no tiene una voz de referencia")})
            vault.save_person(str(m.get("name", "")), vault.root / "voices" / vid / ref["file"], ref.get("text", ""),
                              str(m.get("id") or "") or None)
        else:
            vault = self.vaults.get(str(m.get("vault", ""))) or self.vault
            vault.forget_person(str(m.get("id", "")))
        self.notify({"type": "people_saved", "vault": vault.id, "items": self._people_saved(vault)})

    # ------------------------------------------------------------ comentarios
    def _comment(self, m: dict):
        vid, seg, text = str(m.get("video", "")), int(m.get("seg", -1)), str(m.get("text", ""))
        tr = self.store.open(vid)
        if m["type"] == "comment_add" and text.strip():
            tr.add_comment(seg, text)
        elif m["type"] == "comment_edit" and text.strip():
            tr.edit_comment(seg, str(m.get("id")), text)
        elif m["type"] == "comment_delete":
            tr.delete_comment(seg, str(m.get("id")))
        tr.save()
        self.notify({"type": "comments", "video": vid, "comments": tr.comments})  # todas las pestañas
        events.emit("comentario.cambio", self._vault_of(vid).id, video=vid, segment=seg, action=m["type"][8:])

    # ------------------------------------------------------- borrar videos
    async def _delete(self, m: dict):
        """Borrar videos o vaciar la biblioteca: van a la papelera (30 días, se pueden devolver)."""
        from .trash import Trash

        vault = self.vaults.get(str(m.get("vault", ""))) or self.vault  # vaciar otra biblioteca (desde su tarjeta)
        cleared = m["type"] == "lib_clear"
        vids = (list(vault.library.data["videos"]) if cleared else
                [str(v) for v in m.get("videos", []) if str(v) in vault.library.data["videos"]])
        if self.processor:
            self.processor.remove_many(vids)
        entry = await asyncio.get_running_loop().run_in_executor(None, lambda: Trash(vault.root).videos(vault, vids, cleared))
        # solo lo que fue a la papelera: si mientras tanto llegó un video nuevo (la cola), se queda
        vault.library.remove_many(vids)
        if cleared and entry:
            gone = {c["id"] for c in entry.get("collections", [])}
            vault.library.data["collections"] = [c for c in vault.library.data["collections"] if c["id"] not in gone]
            vault.library.save()
        self.notify({"type": "deleted", "videos": vids})
        self.notify({"type": "library_changed"})
        if entry:
            await self.ws.send_json({"type": "trashed", "id": entry["id"], "vault": vault.id, "title": entry["title"],
                                     "count": entry["count"], "kind": entry["kind"]})
        if vids:
            events.emit("video.eliminado", vault.id, videos=vids, count=len(vids))

    # ------------------------------------------------------------- biblioteca
    async def _library(self, m: dict):
        lib, kind = self.library, m.get("type")
        vid = str(m.get("video", ""))
        if kind == "lib_meta":  # título y miniatura de videos de otras bibliotecas (para la cola)
            out = {}
            for i in [str(x) for x in m.get("ids", [])][:300]:
                v = self.vaults.of(i)
                e = v.library.data["videos"].get(i) if v and self.access.can_view(v.id) else None
                if e:
                    out[i] = {"id": i, "lib": v.id, "title": e.get("title", i), "source": e.get("source"),
                              **{f: v.url(e[f]) for f in ("thumb", "media") if e.get(f)}}
            return await self.ws.send_json({"type": "lib_meta", "videos": out})
        if kind == "lib_register":  # en su biblioteca (un archivo ya importado en otra queda allá)
            rid = str(m.get("id", ""))
            if not _SAFE_VID.fullmatch(rid):
                return
            target = self._vault_of(rid)
            if rid not in target.library.data["videos"]:
                events.emit("video.agregado", target.id, videos=[rid], count=1)
            # solo datos descriptivos: las rutas de archivos (media, audio, miniatura) las pone el servidor
            dur = m.get("duration")
            known = (target.library.data["videos"].get(rid) or {}).get("source")  # el origen no cambia al abrirlo
            target.library.register(
                rid, title=str(m.get("title") or "")[:300] or None,
                duration=float(dur) if isinstance(dur, (int, float)) and 0 < dur < 1e6 else None,
                source=None if known else m.get("source") if m.get("source") in ("file", "youtube") else None)
        elif kind == "lib_remove":
            self._vault_of(vid).library.remove(vid)
        elif kind == "lib_rename":
            if not self._vault_of(vid).library.rename_video(vid, str(m.get("title") or "")):
                return
            self.notify({"type": "library_changed"})  # las demás pestañas
        elif kind == "coll_create":
            c = lib.create(m.get("name", ""))
            if vid:
                lib.toggle(c["id"], vid, True)
            events.emit("coleccion.creada", self.vault.id, collection=c["id"], name=c["name"], kind="propia")
        elif kind == "coll_toggle":
            lib.toggle(m["coll"], vid, bool(m.get("on")))
            events.emit("coleccion.cambio", self.vault.id, collection=m["coll"], video=vid, added=bool(m.get("on")))
        elif kind == "coll_rename":
            lib.rename(m["coll"], m.get("name", ""))
            events.emit("coleccion.cambio", self.vault.id, collection=m["coll"], name=m.get("name", ""))
        elif kind == "coll_delete":
            events.emit("coleccion.eliminada", self.vault.id, collection=m["coll"])
            orphans = lib.delete(m["coll"])  # lo pendiente de una playlist borrada sale de la cola
            if orphans and self.processor:
                self.processor.remove_many(orphans)
        data = self.vault.public_library()
        data["vault"] = self.vault.id
        data["hero"] = self._hero(data["videos"])
        if self.processor:  # avance de cada video (para "Procesar" y las barras)
            for vid, v in data["videos"].items():
                try:
                    v["progress"] = self.processor.progress(vid)
                except Exception:
                    v["progress"] = {"asr": 0, "dub": 0}
        await self.ws.send_json({"type": "library", **data})

    def _hero(self, videos: dict) -> dict | None:
        """Portada: el último video que se estaba viendo y la frase (inglés y español) donde quedó."""
        best = None
        for vid, v in videos.items():
            pos, dur = v.get("position") or 0, v.get("duration") or 0
            if v.get("media") and pos > 5 and dur and pos < dur - 10 and (best is None or (v.get("opened") or 0) > best[0]):
                best = ((v.get("opened") or 0), vid, pos)
        if best is None:  # nada empezado: el último que se abrió o se agregó (con su resumen, si tiene)
            ready = [(v.get("opened") or v.get("added") or 0, vid) for vid, v in videos.items() if v.get("media")]
            if not ready:
                return None
            best = (0, max(ready)[1], 0)
        _, vid, pos = best
        try:
            tr = self.vault.store.open(vid)
        except (ValueError, OSError):
            return {"video": vid}
        seg = next((s for s in reversed(tr.segments) if s["start"] <= pos + 0.5 and s.get("translation")), None) if pos else None
        out = {"video": vid, "en": seg.get("text", "") if seg else "", "es": seg.get("translation", "") if seg else ""}
        # lo del resumen que ayuda a retomar (inicio en pantalla grande): ideas clave y los primeros capítulos
        s = tr.data.get("summary") or {}
        if s.get("version") == 2:
            out["ideas"] = [x for x in s.get("takeaways") or []][:3]
            out["chapters"] = [{"t": c["t"], "title": c["title"]} for c in (s.get("chapters") or [])[:4] if c.get("title")]
        elif s.get("points"):
            out["ideas"] = [p["text"] for p in s["points"][:3]]
        return out

    async def _export(self, m: dict):
        if m["type"] == "export_remove":
            if self.access.owner or str(m.get("job", "")) in self._my_exports:
                self.exporter.remove(str(m.get("job", "")))
            return
        if m["type"] == "export_pick_folder":  # el cuadro nativo de Windows, en este equipo
            if not self.access.local:
                return
            # la carpeta fija de Ajustes › Exportar (desde ahí o el diálogo de exportar)
            p = self.prefs.values
            path = await asyncio.get_running_loop().run_in_executor(
                None, pick_folder, i18n.t("Dónde guardar lo exportado"), p.get("export_dir") or p.get("export_last_dir") or "")
            if path:
                self.prefs.set("export_dir", str(Path(path)))
                self.prefs.set("export_ask", "carpeta")
                self.notify({"type": "prefs"})
            return await self.ws.send_json({"type": "export_folder", "path": path})
        if m["type"] == "export_reveal":  # el archivo exportado, marcado en el Explorador
            if not self.access.local:
                return
            j = next((j for j in self.exporter.jobs if j["id"] == str(m.get("job", "")) and j.get("path")), None)
            if j and Path(j["path"]).exists():
                reveal(Path(j["path"]))
            return
        if m["type"] != "export":
            return
        try:
            vids = [str(v) for v in m.get("videos", [])
                    if (o := self.vaults.of(str(v))) is not None and self.access.can_view(o.id)]
            # desde este mismo equipo (el dueño) se guarda en una carpeta: la que elige en «Guardar como»
            # (empieza en la última que usó) o la fija de Ajustes › Exportar; desde otro equipo, el
            # resultado se descarga con el navegador
            loop = asyncio.get_running_loop()
            kinds, name, audio = list(m.get("kinds", [])), str(m.get("name", ""))[:120], str(m.get("audio") or "m4a")
            dest, filename = "", ""
            if self.access.owner and self.access.local and self.prefs:
                p = self.prefs.values
                if p.get("export_ask") == "carpeta" and p.get("export_dir"):
                    dest = p["export_dir"]
                else:
                    single, planned = await loop.run_in_executor(None, self.exporter.plan, vids, kinds, name, audio)
                    last = p.get("export_last_dir") or ""
                    if single:
                        chosen = await loop.run_in_executor(None, pick_save, planned, last)
                        dest, filename = (str(Path(chosen).parent), Path(chosen).name) if chosen else ("", "")
                    else:
                        dest = await loop.run_in_executor(None, pick_folder, i18n.t("Dónde guardar «{name}»", name=planned), last)
                    if not dest:
                        if _dialog_available():  # lo canceló; sin pantalla (Docker), se descarga
                            return await self.ws.send_json({"type": "export_cancelled"})
                    else:
                        self.prefs.set("export_last_dir", str(Path(dest)))
            job = await loop.run_in_executor(None, lambda: self.exporter.add(
                vids, kinds, name, audio,
                str(m.get("layout") or "flat"), str(m.get("folder", ""))[:120], str(m.get("quality") or "alta"),
                str(m.get("video") or "original"), dest, filename))
            self._my_exports.add(job["id"])
            await self.ws.send_json({"type": "export_started", "job": job["id"]})
        except ValueError as e:
            await self.ws.send_json({"type": "yt_error", "error": str(e)})
