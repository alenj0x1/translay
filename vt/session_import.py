"""Agregar videos: un enlace de YouTube, una lista de enlaces, una playlist, y el idioma y el
modo (traducir o solo transcribir) de cada uno.

Parte de Session (vt/session.py): sus métodos usan el estado de la sesión (self)."""

import asyncio
from . import events, i18n, langs
from .store import _SAFE_ID as _SAFE_VID


class ImportMixin:
    # ---------------------------------------------------------------- YouTube
    async def _youtube(self, url: str, queue: bool = False):
        loop = asyncio.get_running_loop()
        if not self.youtube:
            await self.ws.send_json({"type": "yt_error", "error": i18n.t("YouTube no está habilitado")})
            return
        from .youtube import video_id

        vid = video_id(url) or ""
        last = {"stage": None, "frac": 0.0, "title": ""}

        def progress(stage, frac, title=None, stats=None):
            last["title"] = title or last["title"]
            # sin inundar el WebSocket: cada cambio de etapa y cada 2 %
            if stage == last["stage"] and frac - last["frac"] < 0.02 and frac < 1.0:
                return
            last.update(stage=stage, frac=frac)
            loop.call_soon_threadsafe(asyncio.ensure_future, self.ws.send_json(
                {"type": "yt_progress", "id": vid, "title": last["title"], "stage": stage,
                 "pct": round(frac * 100)}))

        try:
            session = self.prefs.values.get("yt_session", "ninguna") if self.prefs else "ninguna"
            vault = self._vault_of("yt_" + vid)  # si ya está en otra biblioteca, queda en esa
            info = await loop.run_in_executor(None, vault.youtube.fetch, url, progress, session)
            vault.library.register("yt_" + info["id"], source="youtube", media=info["video"],
                                   **{k: info.get(k) for k in ("title", "duration", "audio", "thumb",
                                                                 "channel", "categories")})
            info = {**info, **{k: vault.url(info[k]) for k in ("video", "audio", "thumb") if info.get(k)}}
            if queue and self.processor:  # solo a la cola: no se abre para ver
                self.processor.add("yt_" + info["id"])
                await self.ws.send_json({"type": "yt_queued", **info})
                await self._library({"type": "library"})
                return
            await self.ws.send_json({"type": "yt_ready", **info})
        except Exception as e:
            from .youtube import friendly_error

            print(f"[youtube] {e}", flush=True)
            sess = self.prefs.values.get("yt_session", "ninguna") if self.prefs else "ninguna"
            await self.ws.send_json({"type": "yt_error", "id": vid, "error": friendly_error(e, sess)})

    def _audio_only(self) -> bool:
        return bool(self.prefs) and self._pref("download_what") == "audio"

    def _download_only(self) -> bool:
        return bool(self.prefs) and self._pref("import_mode") == "descargar"

    async def _batch(self, urls: list[str], coll: str, quiet: bool = False, front: bool = False, mode: str = "",
                     lang: str = "auto", tmode: str = ""):
        """Varios enlaces a la vez: los videos entran a la cola sin descargar (se bajan en
        orden) y cada playlist se importa como colección. lang: el idioma en que se hablan
        ("auto": se detecta); tmode: "translate", "transcribe" o "" (según el idioma)."""
        from . import links
        from .youtube import playlist_id, video_id

        vids, lists, shared, errors = [], [], {}, []
        for u in urls:
            u = str(u)
            try:
                lk = links.parse(u)
            except ValueError as e:
                errors.append(str(e))
                continue
            v = video_id(u) if not lk else None
            if lk:
                shared[lk["id"]] = lk
            elif v:
                vids.append(v)
            elif playlist_id(u):
                lists.append(u)
        vids = list(dict.fromkeys(vids))
        lib = self.library  # la biblioteca abierta al importar (aunque luego se cambie)
        # un video vive en una sola biblioteca: los que ya están en otra se quedan allá
        elsewhere: dict[str, int] = {}
        for v in list(vids):
            o = self.vaults.of("yt_" + v)
            if o is not None and o is not self.vault:
                elsewhere[o.name] = elsewhere.get(o.name, 0) + 1
                vids.remove(v)
        for v in list(shared):
            o = self.vaults.of(v)
            if o is not None and o is not self.vault:
                elsewhere[o.name] = elsewhere.get(o.name, 0) + 1
                shared.pop(v)
        # aparecen al instante; los títulos llegan de a poco (miles de consultas juntas
        # son justo la ráfaga que YouTube marca)
        known = set(lib.data["videos"])
        ids = lib.add_pending([{"id": v} for v in vids])
        for vid, lk in shared.items():  # Dropbox: el título sale del nombre del archivo
            if vid not in known:
                lib.register(vid, source="link", url=lk["url"], title=lk["name"])
            ids.append(vid)
        self._import_lang(ids, known, lang, tmode)
        if self.processor:  # los títulos se completan de a poco (Processor._titles_loop)
            self.processor.kick_titles()
        if coll:
            for vid in ids:
                lib.toggle(coll, vid, True)
        if self.processor and ids:
            # "abrirlo": se descarga primero; «Solo descargar» (Ajustes): sin traducir
            dl_only = (mode == "descargar") if mode else self._download_only()  # mode: desde la API
            self.processor.add_many(ids, front=front, download_only=dl_only and not front,
                                    audio_only=self._audio_only())
        if ids:
            events.emit("video.agregado", self.vault.id, videos=ids, count=len(ids))
        await self.ws.send_json({"type": "batch_added", "videos": len(ids), "playlists": len(lists), "ids": ids,
                                 "quiet": bool(quiet), "elsewhere": elsewhere, "errors": errors})
        self.notify({"type": "library_changed"})
        for u in lists:
            await self._playlist(u, lang, tmode)

    def _import_lang(self, ids: list[str], known: set, lang: str, tmode: str = ""):
        """Idioma y modo elegidos al importar: para lo nuevo; lo que ya estaba conserva lo que
        se cambió a mano, salvo que se pida un idioma o un modo concreto."""
        if not tmode and self.prefs and not self.prefs.translating:
            tmode = "transcribe"  # solo transcribir (Ajustes › Uso): lo nuevo no se pone a traducir al volver
        for vid in ids:
            if vid not in known or langs.is_source(lang) or tmode:
                self._set_lang(vid, lang, tmode)

    def _set_lang(self, vid: str, lang: str, mode: str = "") -> bool:
        """Idioma y modo del video, en su transcripción (lo usa el procesamiento) y en la
        biblioteca. lang "auto" o vacío: se detecta, si aún no se conoce. True si cambió."""
        from .store import MODES

        if not _SAFE_VID.fullmatch(vid) or (lang not in ("auto", "") and not langs.is_source(lang)):
            return False
        vault = self._vault_of(vid)
        tr = vault.store.open(vid)
        had = bool(tr.covered)
        lang_changed = langs.is_source(lang) and tr.set_lang(lang)
        if mode not in MODES and lang_changed and lang == self._own_lang() and "mode" not in tr.data:
            mode = "transcribe"  # en el idioma propio: solo se transcribe
        mode_changed = tr.set_mode(mode)
        if lang_changed or mode_changed:
            tr.save()
        if vid in vault.library.data["videos"]:
            vault.library.set_field(vid, lang=tr.lang, mode=tr.mode)
        if (lang_changed or mode_changed) and had and self.processor:
            self.processor.add(vid)  # lo reconocido en otro idioma se rehace; con otro modo, se completa
        return lang_changed or mode_changed

    async def _video_lang(self, vid: str, lang: str, mode: str = ""):
        if not self._set_lang(vid, lang, mode):
            return
        vault = self._vault_of(vid)
        tr = vault.store.open(vid)
        if self.tr is not None and self.tr.data["id"] == vid:  # esta pestaña lo procesaba en vivo
            self.q.put_nowait(("seek", {}))
            self.st.language = tr.lang
            if tr.translates:  # pasó a traducir: lo ya reconocido se traduce
                if self._backfill:
                    self._backfill.cancel()
                self._backfill = asyncio.create_task(self._translate_stale(tr))
        # cada pestaña que lo tenga abierto vuelve a cargar su transcripción (vacía si cambió el idioma)
        self.notify({"type": "bg", "video": vid, "msg": {"type": "transcript", **tr.public(),
                                                         "voice_refs": self._voice_refs(vid),
                                                         "prefix": vault.prefix, "vault": vault.id}})
        self.notify({"type": "library_changed"})

    async def _playlist(self, url: str, lang: str = "auto", tmode: str = ""):
        loop = asyncio.get_running_loop()
        sess = self.prefs.values.get("yt_session", "ninguna") if self.prefs else "ninguna"
        try:
            info = await loop.run_in_executor(None, self.youtube.playlist, url, sess)
        except Exception as e:
            from .youtube import friendly_error

            print(f"[playlist] {e}", flush=True)
            await self.ws.send_json({"type": "yt_error", "error": friendly_error(e, sess)})
            return
        lib = self.library
        other = {"yt_" + e["id"] for e in info["entries"]
                 if (o := self.vaults.of("yt_" + e["id"])) is not None and o is not self.vault}
        known = set(lib.data["videos"])
        c = lib.import_playlist(info, exclude=other)  # los que ya están en otra biblioteca se quedan allá
        self._import_lang([i for i in c["items"] if i in lib.data["videos"]], known, lang, tmode)
        if self.processor:  # en orden: la cola descarga y procesa uno tras otro
            self.processor.add_many([i for i in c["items"] if i in lib.data["videos"]],
                                    download_only=self._download_only(), audio_only=self._audio_only())
        events.emit("coleccion.creada", self.vault.id, collection=c["id"], name=c["name"], kind="playlist",
                    count=len(c["items"]))
        await self.ws.send_json({"type": "playlist_added", "coll": c["id"], "name": c["name"],
                                 "count": len(c["items"])})
        self.notify({"type": "library_changed"})
