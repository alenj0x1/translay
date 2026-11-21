"""Lo que solo hace el dueño: rendimiento, almacenamiento, papelera, acceso y API, bibliotecas,
la sesión de YouTube (cookies y cuenta) y buscar actualizaciones.

Parte de Session (vt/session.py): sus métodos usan el estado de la sesión (self)."""

import asyncio
from . import events, i18n
from .vaults import VAULT_PREFS
from .dialogs import pick_folder


class AdminMixin:
    # ------------------------------------------------------------- rendimiento
    async def _perf(self, m: dict):
        """perf_get · perf_set {profile?, vram_mb?, ram_mb?, threads?} · perf_plan {profile} (qué falta bajar)
        · server_restart {prune?} (prune: al volver, borra los modelos que el perfil nuevo no usa)"""
        loop = asyncio.get_running_loop()
        if m["type"] == "perf_plan":
            from . import modelset, profiles

            pid = profiles.resolve(str(m.get("profile") or "auto"), self.perf.hw(), self.perf.limits())
            plan = await loop.run_in_executor(None, modelset.plan, pid)
            return await self.ws.send_json({"type": "perf_plan", "choice": m.get("profile"), **plan})
        if m["type"] == "perf_prune":  # la app de escritorio reinicia por su cuenta (al instalar la voz)
            if self.prefs:
                self.prefs.set("models_prune", m.get("on") is True)
            return
        if m["type"] == "server_restart":
            if m.get("prune") is True and self.prefs:
                self.prefs.set("models_prune", True)
            await self.ws.send_json({"type": "restarting"})
            self.notify({"type": "restarting"})
            tts = getattr(self.dubber, "tts", None)
            self.perf.restart(before=tts.close if tts else None)
            return
        if m["type"] == "perf_set":
            err = await loop.run_in_executor(None, self.perf.set, m)
            if err:
                await self.ws.send_json({"type": "vault_error", "error": err})
        msg = await loop.run_in_executor(None, self.perf.public)
        if m["type"] == "perf_set":
            self.notify(msg)  # todas las pestañas del dueño
        else:
            await self.ws.send_json(msg)

    # ------------------------------------------------------------- almacenamiento
    async def _storage(self, m: dict):
        """storage_scan · storage_free {what, vault?, videos?, repo?}: responde "storage" (y "storage_freed")."""
        if not self.storage:
            return
        loop = asyncio.get_running_loop()
        if m["type"] == "storage_free":
            try:
                freed = await loop.run_in_executor(None, lambda: self.storage.free(
                    str(m.get("what", "")), str(m.get("vault") or ""), [str(v) for v in m.get("videos") or []],
                    str(m.get("repo") or "")))
                await self.ws.send_json({"type": "storage_freed", "what": m.get("what"), "bytes": freed})
                if m.get("what") in ("untranslated", "videos"):
                    self.notify({"type": "library_changed"})
                if m.get("what") == "trash":
                    await self._trash({"type": "trash_list"})
            except (ValueError, OSError) as e:
                await self.ws.send_json({"type": "vault_error", "error": str(e) or i18n.t("no se pudo")})
        try:
            out = await loop.run_in_executor(None, self.storage.scan)
        except OSError as e:
            return await self.ws.send_json({"type": "vault_error", "error": i18n.t("No se pudo medir el espacio. {e}", e=e)})
        await self.ws.send_json(out)
        if out["has_install"] and out["install"] is None:  # lo lento, aparte
            install = await loop.run_in_executor(None, self.storage.measure_install)
            await self.ws.send_json({**out, "install": install})

    # ------------------------------------------------------------- papelera
    async def _trash(self, m: dict):
        """trash_list · trash_restore {id, vault} · trash_purge {id | all, vault}"""
        from .trash import Trash

        loop = asyncio.get_running_loop()
        t = m["type"]
        try:
            if t == "trash_restore":
                vault = self.vaults.get(str(m.get("vault", ""))) or self.vault
                tid = str(m.get("id", ""))
                e = next((x for x in Trash(vault.root).entries() if x["id"] == tid), None)
                if e and e["kind"] == "biblioteca":
                    e = await loop.run_in_executor(None, Trash(vault.root).restore_vault_files, tid)
                    v = await loop.run_in_executor(None, self.vaults.open_folder, e["root"])
                    events.emit("biblioteca.creada", v.id, name=v.name)
                    self.notify({"type": "vaults_changed"})
                    await self._send_vault_state()
                else:
                    vids = await loop.run_in_executor(None, Trash(vault.root).restore_videos, vault, tid, self.vaults)
                    self.notify({"type": "library_changed"})
                    events.emit("video.agregado", vault.id, videos=vids, count=len(vids))
                await self.ws.send_json({"type": "trash_restored", "id": tid})
            elif t == "trash_purge":
                tid, everything = str(m.get("id") or ""), m.get("all") is True
                if not tid and not everything:
                    raise ValueError(i18n.t("No se indicó qué borrar de la papelera"))
                for v in ([self.vaults.get(str(m["vault"]))] if m.get("vault") else self.vaults.all()):
                    if v:
                        await loop.run_in_executor(None, lambda v=v: Trash(v.root).purge(tid=tid or None, everything=everything))
        except (ValueError, OSError) as e:
            await self.ws.send_json({"type": "vault_error", "error": str(e) or i18n.t("no se pudo")})
        items = []
        for v in self.vaults.all():
            if self.access.can_view(v.id):
                items += [dict(x, vault=v.id) for x in Trash(v.root).entries()]
        await self.ws.send_json({"type": "trash", "items": sorted(items, key=lambda x: -x["created"])})

    async def _admin(self, m: dict):
        """Acceso, claves de API, webhooks y red: Ajustes → Acceso y API (solo el dueño)."""
        a, t = self.admin, m["type"]
        if a is None:
            return
        try:
            if t == "admin_owner_pw":
                pw = str(m.get("password", ""))
                if pw and len(pw) < 6:
                    raise ValueError(i18n.t("La contraseña debe tener al menos 6 caracteres"))
                a.auth.set_owner_password(pw)
            elif t == "admin_vault_access":
                a.auth.set_vault_access(str(m.get("id", "")), str(m.get("mode", "")), str(m.get("perm", "ver")),
                                        str(m.get("password", "")))
                events.emit("biblioteca.cambio", str(m.get("id", "")), access=m.get("mode"))
                self.notify({"type": "vaults_changed"})
            elif t == "admin_key_create":
                key, token = a.auth.create_key(str(m.get("name", "")), str(m.get("scope", "all")),
                                               str(m.get("perm", "lectura")))
                await self.ws.send_json({"type": "admin_key", "key": key, "token": token})
            elif t == "admin_key_revoke":
                a.auth.revoke_key(str(m.get("id", "")))
            elif t == "admin_hook_save":
                a.hooks.upsert(m.get("hook") or {})
            elif t == "admin_hook_remove":
                a.hooks.remove(str(m.get("id", "")))
            elif t == "admin_hook_test":
                a.hooks.test(str(m.get("id", "")))
                return
            elif t == "admin_network":
                await a.set_network(bool(m.get("on")))
        except (ValueError, OSError) as e:
            return await self.ws.send_json({"type": "vault_error", "error": str(e) or i18n.t("no se pudo")})
        if t == "admin_get":
            return await self.ws.send_json(a.public())
        self.notify(a.public())  # todas las pestañas del dueño

    # ------------------------------------------------------------ bibliotecas
    async def _vault(self, m: dict):
        t, loop = m["type"], asyncio.get_running_loop()
        try:
            if t == "vault_open":
                v = self.vaults.get(str(m.get("id", "")))
                if v is not None:
                    self.vault = v
                    self.vaults.set_last(v.id)
                return await self._send_vault_state()
            if t == "vault_pick_folder":  # el cuadro nativo de Windows, en este equipo
                path = await loop.run_in_executor(None, pick_folder)
                return await self.ws.send_json({"type": "vault_folder", "path": path, "for": m.get("for", "")})
            if t == "vault_create":
                # empieza con las preferencias propias de la biblioteca abierta (tema, modo de importar)
                prefs = {k: self._pref(k) for k in VAULT_PREFS}
                v = await loop.run_in_executor(None, lambda: self.vaults.create(
                    str(m.get("name", "")), str(m.get("folder", "")).strip(), str(m.get("color", "")),
                    str(m.get("icon", "")), prefs, str(m.get("pattern", ""))))
                self.vault = v
                self.vaults.set_last(v.id)
                events.emit("biblioteca.creada", v.id, name=v.name)
            elif t == "vault_open_folder":
                v = await loop.run_in_executor(None, self.vaults.open_folder, str(m.get("folder", "")).strip())
                self.vault = v
                self.vaults.set_last(v.id)
            elif t == "vault_update":
                v = self.vaults.update(str(m.get("id", "")), **{k: str(m.get(k, "")) for k in ("name", "color", "icon")},
                                       **({"pattern": str(m["pattern"])} if "pattern" in m else {}))
                events.emit("biblioteca.cambio", v.id, name=v.name)
            elif t == "vault_remove":
                vid = str(m.get("id", ""))
                vids = await loop.run_in_executor(None, self.vaults.remove, vid, bool(m.get("delete_files")))
                if self.processor:
                    self.processor.remove_many(vids)
                if self.vault.id == vid:
                    self.vault = self.vaults.main
                events.emit("biblioteca.eliminada", vid, deleted_files=bool(m.get("delete_files")))
            elif t == "vault_move":
                to = str(m.get("to", ""))
                busy = self.processor.busy if self.processor else (lambda v: False)
                moved, skipped = await loop.run_in_executor(
                    None, lambda: self.vaults.move([str(v) for v in m.get("videos", [])], to, busy))
                if self.dubber:
                    for v in m.get("videos", []):
                        self.dubber.forget(str(v))
                await self.ws.send_json({"type": "vault_moved", "moved": moved, "skipped": skipped,
                                         "to": self.vaults.get(to).name})
                if moved:
                    events.emit("video.movido", to, videos=[str(v) for v in m.get("videos", [])
                                                            if self.vaults.of(str(v)) is self.vaults.get(to)], to=to)
                self.notify({"type": "library_changed"})
                if self.processor:
                    self.processor._broadcast()
            else:
                return
        except (ValueError, OSError, KeyError) as e:
            return await self.ws.send_json({"type": "vault_error", "error": str(e) or i18n.t("no se pudo")})
        self.notify({"type": "vaults_changed"})
        await self._send_vault_state()

    # ------------------------------------------------------- sesión de YouTube
    def _cookies_path(self):
        return self.vaults.cookies

    async def _cookies_status(self, extra: dict | None = None):
        from . import cookies

        await self.ws.send_json({**cookies.message(self._cookies_path()), **(extra or {})})

    async def _cookies(self, m: dict):
        from . import cookies

        if m["type"] == "cookies_browsers":
            return await self._cookies_status()
        if m["type"] in ("yt_connect", "yt_disconnect"):
            return await self._account(m)
        key = str(m.get("browser", ""))
        try:
            info = await asyncio.get_running_loop().run_in_executor(
                None, cookies.import_browser, key, self._cookies_path())
        except Exception as e:
            return await self._cookies_status({"error": cookies.friendly(e, key)})
        self.cookies_imported(info)
        await self._cookies_status({"imported": info})

    async def _account(self, m: dict):
        """Conectar o desconectar la cuenta de YouTube. La ventana para iniciar sesión se
        abre en el equipo donde corre Translay: solo desde ese equipo."""
        from . import cookies, ytsession

        if not self.access.local:
            return await self._cookies_status({"error": i18n.t("La cuenta de YouTube se conecta desde el equipo donde corre Translay.")})
        acc = ytsession.get(self._cookies_path().parent)
        loop = asyncio.get_running_loop()
        changed = lambda: self.notify(cookies.message(self._cookies_path()))  # noqa: E731 (desde el hilo)
        try:
            if m["type"] == "yt_disconnect":
                await loop.run_in_executor(None, acc.disconnect, changed)
                if self.prefs and self.prefs.values.get("yt_session") == "cuenta" and self.prefs.set("yt_session", "ninguna"):
                    self.notify(self.prefs.public())
                return await self._cookies_status({"disconnected": True})
            key = str(m.get("browser") or next((b["key"] for b in ytsession.detect()), ""))
            await loop.run_in_executor(None, acc.connect, key, changed)
        except ytsession.Cancelled:
            return await self._cookies_status({"cancelled": True})
        except (ValueError, TimeoutError, OSError, RuntimeError) as e:
            return await self._cookies_status({"error": str(e)})
        if self.prefs and self.prefs.set("yt_session", "cuenta"):
            self.notify(self.prefs.public())
        if self.processor:
            self.processor.unblock()
        self.notify({**cookies.message(self._cookies_path()), "connected_now": True})

    def cookies_imported(self, info: dict):
        """Tras importar una sesión, las descargas pasan a usarla (y siguen si estaban en pausa)."""
        if self.prefs and self.prefs.set("yt_session", "archivo"):
            self.notify(self.prefs.public())
        if self.processor:
            self.processor.unblock()

    async def _update_check(self, force: bool):
        """¿Hay una versión nueva? (vt/updates.py; solo avisa, no descarga nada)"""
        from . import updates
        try:
            info = await asyncio.get_running_loop().run_in_executor(None, updates.check, force)
            await self.ws.send_json({"type": "update", **info})
        except Exception as e:  # sin conexión o GitHub no respondió
            print(f"[actualizaciones] {e}", flush=True)
            await self.ws.send_json({"type": "update", "error": i18n.t("No se pudo consultar GitHub. Revisa la conexión a internet.")})
