"""Sesión WebSocket: una por pestaña del navegador.

Protocolo
---------
Cliente → servidor
  {"type":"open", "id":<huella>, "name":<archivo>}   abre/crea la transcripción
  binario: float64 LE (tiempo de medio) + PCM int16 LE mono 16 kHz
  {"type":"seek"|"stop"|"end", "t":<s>}             cierra o descarta lo pendiente
  {"type":"pos", "t":<s>}                            punto de reproducción (orden del doblaje)
  {"type":"watch", "video":<id>, "t":<s>} / unwatch  video guardado que se está viendo: lo procesa
                                                     la cola (vt/processor.py) desde ese punto
  {"type":"youtube", "url":<enlace>}                 descarga y responde yt_progress / yt_ready
  {"type":"playlist", "url":<enlace>, "lang", "mode"}  la importa como colección y la manda a la cola
  {"type":"yt_batch", "urls":[…], "lang", "mode"}    enlaces de YouTube o Dropbox (vt/links.py) a la cola; batch_added.
                                                     lang: "auto" (se detecta) o uno de vt/langs.py;
                                                     mode: "translate", "transcribe" o "" (según el idioma propio)
  {"type":"video_lang", "video", "lang"?, "mode"?}   idioma en que se habla (rehace lo reconocido) y/o
                                                     traducir o solo transcribir (no borra nada)
  {"type":"export", "videos":[ids], "kinds":[…], "name", "audio":"m4a"|"mp3"|"opus", "quality":"alta"|"media"|"liviana",
   "video":"original"|"480p"|"360p", "layout":"flat"|"channel"|"collection"|"playlist"|"folder", "folder"}
                                                     exportar (vt/exporter.py). Desde este equipo, el dueño elige dónde
                                                     guardar en el cuadro de Windows, o va a la carpeta fija de
                                                     Ajustes; si lo cancela, responde export_cancelled
                                                     export_remove {job} · export_pick_folder · export_reveal {job}
  summarize {video, force?} · summary_cancel {video}   resumen del video (vt/summaries.py); el avance llega
                                                     como summary_state y el resultado como summary
  storage_scan · storage_free {what, vault?, videos?, repo?}   Ajustes → Almacenamiento (vt/storage.py)
  perf_plan {profile}                                qué modelos faltan para ese perfil (vt/modelset.py) · server_restart {prune?}
  comment_add / comment_edit / comment_delete {video, seg, id?, text}   comentarios por frase
  lib_delete {videos:[ids]} · lib_clear              videos o toda la biblioteca a la papelera (30 días)
  trash_list · trash_restore {id, vault} · trash_purge {id | all, vault}   papelera
  lib_rename {video, title}                          nombre propio de un video
  {"type":"library"} · lib_register · lib_remove · coll_create · coll_toggle · coll_rename · coll_delete
                                                     biblioteca y colecciones (responde "library")
  vault_open {id} · vault_create {name, folder, color, icon} · vault_open_folder {folder}
  vault_update {id, name, color, icon, pattern} · vault_remove {id, delete_files} · vault_pick_folder
  vault_move {videos, to}                            bibliotecas (vt/vaults.py; responde "vaults")
  people_save {video, spk, name} · people_forget {id}  personas guardadas en la biblioteca

Servidor → cliente
  ready · transcript · partial (+ "es" en vivo) · segment · translations · dub · covered · stats
  lang {lang, mode, translates}                      idioma detectado (o cambiado) del video abierto

Doblaje: cada frase final pasa por una cola de voz que atiende primero lo que
se va a escuchar (las frases desde el punto de reproducción en adelante, en
orden). La voz corre en su propio hilo y proceso, así el reconocimiento no
espera a la síntesis.
"""

import asyncio
import json
import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from pathlib import Path
from functools import partial

from .store import _SAFE_ID as _SAFE_VID, Store, Transcript
from .auth import Access
from .vaults import VAULT_PREFS, RoutedStore

# lo que solo hace el dueño; lo que además de ver puede hacer quien tiene "importar"
OWNER_ONLY = {"prefs_set", "cookies_browsers", "cookies_import", "yt_connect", "yt_disconnect", "queue_pause", "queue_resume", "queue_clear",
              "queue_unblock", "queue_remove", "queue_hold", "lib_delete", "lib_clear", "lib_remove", "glossary_set", "people_set",
              "people_save", "people_forget", "power_info", "coll_create", "coll_toggle", "coll_rename", "coll_delete", "lib_rename",
              "comment_add", "comment_edit", "comment_delete", "rec_mute",
              "export_pick_folder", "export_reveal", "diag_report", "seg_edit", "seg_takes", "seg_take"}
OWNER_PREFIXES = ("admin_", "trash_", "perf_", "storage_")
IMPORT_ONLY = {"youtube", "playlist", "video_lang", "yt_batch", "lib_register", "queue_add", "queue_video", "watch",
               "summarize", "summary_cancel", "agent_ask", "agent_continue", "agent_stop", "agent_clear", "agent_power",
               "agent_dictate", "agent_model_download"}
from .streaming import Detected, Partial, Segment, StreamingTranscriber
from .translate import Translator
from .session_dub import DubMixin
from .session_import import ImportMixin
from .session_agent import AgentMixin
from .session_library import LibraryMixin
from .session_admin import AdminMixin
from .session_edit import EditMixin
from . import diag
from .dialogs import downloads, reveal


class Session(DubMixin, ImportMixin, AgentMixin, LibraryMixin, AdminMixin, EditMixin):
    def __init__(self, ws, asr, gpu: ThreadPoolExecutor, store: Store,
                 translator: Translator, info: dict, dubber=None, tts_exec: ThreadPoolExecutor | None = None,
                 youtube=None, library=None, res=None, processor=None, prefs=None, notify=None, exporter=None,
                 vaults=None, access: Access | None = None, admin=None, perf=None, storage=None, appmute=None):
        self.ws = ws
        self.appmute = appmute  # silenciar las otras apps mientras esta pestaña graba una ventana (vt/appmute.py)
        self.perf = perf  # equipo, perfil y límites (vt/perf.py)
        self.storage = storage  # cuánto ocupa cada cosa y qué se puede liberar (vt/storage.py)
        self.gpu = gpu
        # quién es (vt/auth.py): el dueño o un invitado con permisos por biblioteca
        self.access = access or Access(owner=True, local=True)
        self.admin = admin  # acceso, claves de API, webhooks y red (solo el dueño)
        self._my_exports: set[str] = set()
        # bibliotecas: la que esta pestaña tiene abierta; cada video se abre en la suya
        self.vaults = vaults
        req = getattr(ws, "request", None)
        asked = vaults.get((req.query.get("lib") if req else "") or "")  # /b/<biblioteca>
        if asked and self.access.can_view(asked.id):
            self.vault = asked
        elif self.access.owner:
            self.vault = vaults.get(vaults.last) or vaults.main
        else:
            self.vault = next((v for v in vaults.all() if self.access.can_view(v.id)), vaults.main)
        self._store = RoutedStore(vaults, lambda: self.vault)
        self.translator = translator
        self.info = info
        self.st = StreamingTranscriber(asr)
        self.tr: Transcript | None = None
        self.q: asyncio.Queue = asyncio.Queue()
        self._live_src = ""
        self._live_es = ""
        self._backfill: asyncio.Task | None = None
        self.dubber = dubber
        self.tts_exec = tts_exec
        self.dub_pending: dict[int, tuple[int, Transcript, float | None]] = {}
        self.dub_event = asyncio.Event()
        self.playhead = 0.0
        self.res = res
        self.processor = processor
        self.watching: str | None = None
        self.prefs = prefs
        self.notify = notify or (lambda msg: None)
        self.exporter = exporter
        self._dub_seq = 0
        self._dub_task: asyncio.Task | None = None

    # la biblioteca abierta en esta pestaña
    @property
    def store(self):
        return self._store

    @property
    def library(self):
        return self.vault.library

    @property
    def youtube(self):
        return self.vault.youtube

    @property
    def glossary(self):
        return self.vault.glossary

    def _vault_of(self, vid: str):
        """La biblioteca de un video (si aún no está en ninguna, la abierta)."""
        return self.vaults.of(vid) or self.vault

    def _gl(self, tr):
        return self._vault_of(tr.data["id"]).glossary if tr is not None else self.vault.glossary

    def _pref(self, key: str):
        own = self.vault.meta.get("prefs") or {}
        return own[key] if key in VAULT_PREFS and key in own else self.prefs.values.get(key)

    @property
    def _summaries(self):
        return self.exporter.summaries if self.exporter else None

    def _prefs_msg(self) -> dict:
        m = self.prefs.public()
        if not (self.access.owner and self.access.local):  # carpetas de este equipo: solo para quien está en él
            m["values"].update({p["key"]: "" for p in m["schema"] if p["type"] == "path"})
        own = self.vault.meta.get("prefs") or {}
        m["values"].update({k: v for k, v in own.items() if k in VAULT_PREFS})
        m["vault_keys"] = list(VAULT_PREFS)
        return m

    def _vaults_msg(self) -> dict:
        items = [i for i in self.vaults.public() if self.access.can_view(i["id"])]
        if not self.access.owner:  # el invitado no ve dónde están las carpetas
            items = [{**i, "path": "", "access": None, "perm": self.access.perm(i["id"])} for i in items]
        return {"type": "vaults", "current": self.vault.id, "items": items}

    async def _send_vault_state(self):
        """Todo lo que cambia con la biblioteca: lista, preferencias, glosario y videos."""
        await self.ws.send_json(self._vaults_msg())
        await self.ws.send_json(self._prefs_msg())
        await self.ws.send_json({"type": "glossary", "entries": self.glossary.entries, "vault": self.vault.id})
        await self.ws.send_json({"type": "people_saved", "vault": self.vault.id, "items": self._people_saved()})
        await self._library({"type": "library"})

    def _auth_msg(self) -> dict:
        req = getattr(self.ws, "request", None)
        asked = self.vaults.get((req.query.get("lib") if req else "") or "")
        acc = (asked.meta.get("access") or {}) if asked else {}
        return {"type": "auth", **self.access.public(), "vault": self.vault.id if self.access.any else None,
                "asked": asked.id if asked else None, "asked_name": asked.name if asked else "",
                "asked_mode": acc.get("mode", "privada") if asked else "",
                "owner_set": bool(self.admin and self.admin.auth.owner_set),
                # qué pide permiso: la página no manda lo que no puede (así un invitado no ve avisos de permiso)
                "owner_only": sorted(OWNER_ONLY), "import_only": sorted(IMPORT_ONLY),
                "owner_prefixes": list(OWNER_PREFIXES),
                "public": [{"id": v.id, "name": v.name, "color": v.meta.get("color"), "icon": v.meta.get("icon")}
                           for v in self.vaults.all() if (v.meta.get("access") or {}).get("mode") == "publica"]}

    def _allowed(self, t: str, m: dict) -> bool:
        """¿Esta conexión puede pedir esto?"""
        a = self.access
        if a.owner:
            return True
        if t in OWNER_ONLY or t.startswith(OWNER_PREFIXES) or t == "server_restart" or \
                (t.startswith("vault_") and t != "vault_open"):
            return False
        if t == "vault_open":
            return a.can_view(str(m.get("id", "")))
        if t in IMPORT_ONLY:
            if t == "queue_add":
                v = self.vaults.of(str(m.get("video", "")))
                return bool(v) and a.can_import(v.id)
            if t == "queue_video":
                vs = [self.vaults.of(str(x)) for x in m.get("videos", [])]
                return bool(vs) and all(v and a.can_import(v.id) for v in vs)
            if t in ("lib_register", "watch", "video_lang", "summarize", "summary_cancel", "agent_ask", "agent_continue", "agent_stop",
                     "agent_clear", "agent_power"):  # la del video, si ya está en alguna biblioteca
                return a.can_import(self._vault_of(str(m.get("id") or m.get("video") or "")).id)
            return a.can_import(self.vault.id)
        if t == "open":
            v = self.vaults.of(str(m.get("id", "")))
            return a.can_view(v.id) if v else a.can_import(self.vault.id)
        return True

    async def run(self):
        await self.ws.send_json(self._auth_msg())
        if not self.access.any:  # sin permiso: la vista muestra el inicio de sesión
            while await self.ws.recv() is not None:
                pass
            return
        worker = asyncio.create_task(self._worker())
        if self.dubber:
            self._dub_task = asyncio.create_task(self._dub_worker())
        await self.ws.send_json({"type": "ready", **self.info})
        await self.ws.send_json({"type": "power", "state": self.res.state})
        if self.prefs:
            await self.ws.send_json(self._vaults_msg())
            await self.ws.send_json(self._prefs_msg())
            if self.access.owner:
                await self._cookies_status()
        if self.processor:
            out = self.forward_bg(self.processor.public())
            if out:
                await self.ws.send_json(out)
        if self.exporter:
            out = self.forward_bg(self.exporter.public())
            if out:
                await self.ws.send_json(out)
        try:
            while (msg := await self.ws.recv()) is not None:
                if isinstance(msg, bytes):
                    if not self.access.can_import(self.vault.id):
                        continue  # procesar audio en vivo usa la GPU: no para quien solo ve
                    if len(msg) > 8:
                        self.res.touch()
                        t = struct.unpack("<d", msg[:8])[0]
                        pcm = np.frombuffer(msg[8:], "<i2").astype(np.float32) / 32768.0
                        self.q.put_nowait(("audio", t, pcm))
                else:
                    m = json.loads(msg)
                    if not self._allowed(str(m.get("type", "")), m):
                        # la interfaz no debería pedirlo (lo filtra con owner_only/import_only): es un error
                        who = "dueño" if self.access.owner else "invitado"
                        if self._page_note():
                            diag.error(f"permiso.{str(m.get('type'))[:40]}", f"rechazado ({who}, biblioteca {self.vault.id})")
                        await self.ws.send_json({"type": "denied", "what": m.get("type")})
                        continue
                    if m.get("type", "").startswith("admin_"):
                        asyncio.create_task(self._admin(m))
                    elif m.get("type") == "pos":
                        self.playhead = float(m.get("t", 0))
                        if self.tr is not None:  # en su biblioteca (puede no ser la abierta)
                            self.vaults.library.position(self.tr.data["id"], self.playhead)
                        if self.watching and self.processor:
                            self.processor.position(self.watching, self.playhead)
                    elif m.get("type") == "watch" and self.processor:
                        if self.watching and self.watching != m.get("video"):
                            self.processor.unwatch(self.watching)
                        self.watching = str(m.get("video"))
                        self.processor.watch(self.watching, float(m.get("t", 0)))
                    elif m.get("type") == "unwatch" and self.processor:
                        if self.watching:
                            self.processor.unwatch(self.watching)
                        self.watching = None
                    elif m.get("type", "").startswith("comment_"):
                        self._comment(m)
                    elif m.get("type") in ("summarize", "summary_cancel") and self._summaries:
                        vid = str(m.get("video", ""))
                        if m["type"] == "summary_cancel":
                            self._summaries.cancel(vid)
                        elif _SAFE_VID.match(vid) and self.vaults.of(vid):
                            ok = await asyncio.get_running_loop().run_in_executor(
                                None, self._summaries.request, vid, bool(m.get("force")))
                            if not ok:  # sin transcripción (o ya tiene): la vista no queda «en cola»
                                await self.ws.send_json({"type": "summary_state", "state": None})
                    elif m.get("type") == "agent_model_download" and self._agent:  # bajarlo de antemano
                        self._agent.download(str(m.get("key", "")))
                    elif m.get("type") == "agent_models" and self._agent:  # Ajustes › Agente › Modelo
                        out = await asyncio.get_running_loop().run_in_executor(None, self._agent.catalog)
                        await self.ws.send_json({"type": "agent_models", **out})
                    elif m.get("type") == "agent_context":
                        asyncio.create_task(self._agent_context(m))
                    elif m.get("type", "").startswith("agent_") and self._agent:
                        asyncio.create_task(self._agent_msg(m))
                    elif m.get("type") == "search":
                        asyncio.create_task(self._search(str(m.get("q", ""))))
                    elif m.get("type") in ("glossary_get", "glossary_set"):
                        asyncio.create_task(self._glossary(m))
                    elif m.get("type") == "people_set":
                        await self._people(m)
                    elif m.get("type") in ("people_save", "people_forget"):
                        await self._people_saved_op(m)
                    elif m.get("type") == "people_get":
                        v = self.vaults.get(str(m.get("vault", ""))) or self.vault
                        if self.access.can_view(v.id):  # un invitado solo ve las de sus bibliotecas
                            await self.ws.send_json({"type": "people_saved", "vault": v.id, "items": self._people_saved(v)})
                    elif m.get("type", "").startswith("vault_"):
                        asyncio.create_task(self._vault(m))
                    elif m.get("type", "").startswith("trash_"):
                        asyncio.create_task(self._trash(m))
                    elif m.get("type") in ("perf_get", "perf_set", "perf_plan", "perf_prune", "server_restart") and self.perf:
                        asyncio.create_task(self._perf(m))
                    elif self.library and m.get("type") in ("lib_delete", "lib_clear"):
                        asyncio.create_task(self._delete(m))
                    elif self.library and m.get("type", "").startswith(("lib", "coll")):
                        await self._library(m)
                    elif m.get("type") in ("cookies_browsers", "cookies_import", "yt_connect", "yt_disconnect"):
                        asyncio.create_task(self._cookies(m))
                    elif m.get("type") == "prefs_set" and self.prefs:
                        key, value = str(m.get("key")), m.get("value")
                        if key in VAULT_PREFS:  # propia de la biblioteca abierta
                            if self.prefs._valid(key, value):
                                self.vaults.set_pref(self.vault.id, key, value)
                                self.notify({"type": "prefs"})  # cada pestaña, con los de su biblioteca
                        elif self.prefs.kind(key) == "path":  # solo las elige el cuadro de Windows (servidor)
                            pass
                        elif self.prefs.set(key, value):
                            self.notify({"type": "prefs"})  # todas las pestañas
                    elif m.get("type") == "power_info":
                        import sys as _sys
                        import threading as _th
                        import traceback as _tb
                        names = {t.ident: t.name for t in _th.enumerate()}
                        stacks = {names.get(i, str(i)): "".join(_tb.format_stack(f)[-4:])
                                  for i, f in _sys._current_frames().items()}
                        await self.ws.send_json({"type": "power_info", **self.res.info(), "threads": stacks})
                    elif m.get("type") == "youtube":
                        asyncio.create_task(self._youtube(m.get("url", ""), bool(m.get("queue"))))
                    elif m.get("type") == "playlist":
                        asyncio.create_task(self._playlist(m.get("url", ""), str(m.get("lang") or "auto"),
                                                           str(m.get("mode") or "")))
                    elif m.get("type") == "video_lang":
                        await self._video_lang(str(m.get("video", "")), str(m.get("lang") or ""),
                                               str(m.get("mode") or ""))
                    elif m.get("type") == "update_check":
                        asyncio.create_task(self._update_check(bool(m.get("force"))))
                    elif m.get("type") == "yt_batch":
                        asyncio.create_task(self._batch(list(m.get("urls", [])), str(m.get("coll") or ""),
                                                        bool(m.get("quiet")), bool(m.get("front")),
                                                        lang=str(m.get("lang") or "auto"),
                                                        tmode=str(m.get("mode") or "")))
                    elif m.get("type", "").startswith("export") and self.exporter:
                        asyncio.create_task(self._export(m))  # el cuadro de carpetas espera a la persona
                    elif m.get("type", "").startswith("storage_"):
                        asyncio.create_task(self._storage(m))
                    elif m.get("type", "").startswith("queue_") and self.processor:
                        await self._queue(m)
                    elif m.get("type") in ("seg_edit", "seg_takes", "seg_take"):  # editor de frases (vt/session_edit.py)
                        asyncio.create_task(getattr(self, "_" + m["type"])(m))
                    elif m.get("type") == "client_error":
                        self._client_error(m)
                    elif m.get("type") == "diag_report":
                        asyncio.create_task(self._diag_report())
                    elif m.get("type") == "rec_mute" and self.appmute:
                        asyncio.create_task(self._rec_mute(m))
                    else:
                        self.q.put_nowait((m.get("type"), m))
        finally:
            if self.appmute:  # la pestaña que grababa se cerró o se cortó: las otras apps recuperan el sonido
                await asyncio.to_thread(self.appmute.restore, self)
            self.q.put_nowait(("close", None))
            await worker
            if self._backfill:
                self._backfill.cancel()
            if self._dub_task:
                self._dub_task.cancel()
            if self.watching and self.processor:
                self.processor.unwatch(self.watching)

    async def _worker(self):
        while True:
            ops = [await self.q.get()]
            while not self.q.empty():
                ops.append(self.q.get_nowait())
            for op in ops:
                kind = op[0]
                if kind == "close":
                    await self._finish()
                    return
                if kind == "audio":
                    if self.tr is None:
                        continue
                    _, t, pcm = op
                    if self.st.is_gap(t):
                        await self._finish(abort=True)
                    self.st.feed(t, pcm)
                elif kind == "seek":
                    await self._finish(abort=True)
                elif kind in ("stop", "end"):
                    await self._finish(keep_context=True)
                elif kind == "open":
                    await self._finish()
                    self.tr = self.store.open(str(op[1].get("id", "")), op[1].get("name", ""))
                    self.st.language = self.tr.lang  # "" = se detecta con la primera voz
                    vault = self._vault_of(self.tr.data["id"])
                    await self.ws.send_json({"type": "transcript", **self.tr.public(),
                                             "summary_state": self._summaries.state(self.tr.data["id"])
                                             if self._summaries else None,
                                             "voice_refs": self._voice_refs(self.tr.data["id"]),
                                             "screen_text": self.processor.screen.public(self.tr.data["id"])
                                             if self.processor and self.processor.screen else None,
                                             "prefix": vault.prefix, "vault": vault.id})
                    # la descripción bajo el título (vt/agentsvc.py), si falta y el video ya está reconocido
                    ag = self.processor.agent if self.processor else None
                    if ag and self.tr.data["id"] in vault.library.data["videos"] and \
                            self.processor.progress(self.tr.data["id"])["asr"] >= 0.98:
                        ag.describe(self.tr.data["id"])
                    if self._backfill:
                        self._backfill.cancel()
                    self._backfill = asyncio.create_task(self._translate_stale(self.tr))
                    # la voz que falte la completa la cola (vt/processor.py) al ver o
                    # procesar el video: hacerlo también aquí duplicaba el trabajo
            if self.tr is not None and self.st.ready():
                if self.tr.lang and self.st.language != self.tr.lang:
                    # lo detectó la cola (o lo corrigió con el archivo completo, o se eligió) mientras tanto
                    self.st.language = self.tr.lang
                try:
                    await self._run(self.st.step)
                except Exception:  # una falla no debe detener la sesión
                    diag.exception("sesion.trabajo")
                    await self.ws.send_json({"type": "stats", "infer_ms": 0, "buffer_s": 0})

    async def _finish(self, keep_context: bool = False, abort: bool = False):
        """Cierra el tramo actual y reinicia el streamer.

        stop/end: se confirma todo lo pendiente (el tramo terminó de verdad).
        seek: se descarta la frase abierta (quedaría cortada a la mitad).
        La pausa no llega aquí: al reanudar, el audio sigue siendo continuo.
        """
        if self.st._started:
            await self._run(self.st.abort if abort else self.st.flush)
        self.st.reset(0.0, keep_context=keep_context)

    async def _run(self, fn):
        loop = asyncio.get_running_loop()
        t = time.perf_counter()
        events = await loop.run_in_executor(self.gpu, self.res.run, ("asr",), fn)
        ms = (time.perf_counter() - t) * 1000
        tr = self.tr
        if tr is None:
            return
        dirty = False
        for ev in events:
            if isinstance(ev, Detected):
                await self._detected(tr, ev)
                dirty = True
            elif isinstance(ev, Segment):
                # traductor aún descargándose (primer video en ese idioma): la frase queda sin
                # traducir y _translate_stale la completa cuando esté
                ready = tr.translates and self.translator.ready(tr.lang)
                translation = await loop.run_in_executor(
                    self.gpu, self.res.run, ("mt",), partial(self.translator.translate, glossary=self._gl(tr),
                                                             src=tr.lang), ev.text) if ready else None
                seg, removed = tr.add_segment(ev.start, ev.end, ev.text, translation,
                                              self.translator.name_for(tr.lang) if ready else None)
                if self.dubber and tr.translates:  # solo transcribir: sin personas ni voz
                    seg["speaker"] = await loop.run_in_executor(None, self.dubber.identify, tr, seg, ev.audio)
                    self._queue_dub(0, tr, seg, self.dubber.loudness(ev.audio))
                    for fixed in self.dubber.relabel(tr):  # frases cortas con persona corregida
                        await self.ws.send_json({"type": "speaker", "id": fixed["id"], "speaker": fixed["speaker"]})
                        self._queue_dub(0, tr, fixed, fixed.get("orig_db"))
                await self.ws.send_json({"type": "segment", "segment": seg, "removed": removed})
                dirty = True
            elif isinstance(ev, Partial):
                es = await self._live_translation(f"{ev.committed} {ev.tentative}".strip())
                await self.ws.send_json({"type": "partial", "committed": ev.committed,
                                         "tentative": ev.tentative, "es": es})
        if self.st.final_t > self.st.start_t:
            before = list(map(list, tr.covered))
            tr.add_covered(self.st.start_t, self.st.final_t)
            if tr.covered != before:
                await self.ws.send_json({"type": "covered", "ranges": tr.covered})
                dirty = True
        if dirty:
            tr.save()
        await self.ws.send_json({"type": "stats", "infer_ms": round(ms),
                                 "buffer_s": round(self.st.duration, 2)})


    # --------------------------------------------------------- cola de fondo
    async def _queue(self, m: dict):
        kind, vid = m["type"], str(m.get("video", ""))
        if kind == "queue_add":
            # download_only: «Descargar» desde «Ver» (bajarlo sin abrirlo ni traducirlo)
            self.processor.add_many([vid], front=bool(m.get("front")), download_only=bool(m.get("download_only")))
        elif kind == "queue_remove":
            self.processor.remove(vid)
        elif kind == "queue_hold":  # detener o reanudar un solo video de la cola
            self.processor.set_held(vid, bool(m.get("held")))
        elif kind == "queue_pause":
            self.processor.set_paused(True)
            # pausada y sin ningún video viéndose: reposo profundo inmediato
            # (también se cierra el proceso de voz: la GPU queda libre)
            if not self.st._started and not self.processor.focus["vid"]:
                await asyncio.get_running_loop().run_in_executor(None, self._sleep_when_idle)
        elif kind == "queue_resume":
            self.processor.set_paused(False)
        elif kind == "queue_clear":
            self.processor.clear_done()
        elif kind == "queue_unblock":
            self.processor.unblock()
        elif kind == "queue_video":  # «Bajar video» de lo que solo tiene el audio
            n = self.processor.fetch_videos([str(v) for v in m.get("videos", [])])
            await self.ws.send_json({"type": "video_fetch", "count": n})

    def _sleep_when_idle(self):
        # lo que estaba en curso (una traducción o una voz) termina primero
        for _ in range(60):
            if self.res.info()["busy"] == 0:
                break
            time.sleep(0.5)
        self.res.sleep(deep=True)

    def forward_bg(self, msg: dict) -> dict | None:
        """Avance en segundo plano del video que esta pestaña tiene abierto."""
        t = msg.get("type")
        if t == "bg":
            return msg["msg"] if self.tr is not None and msg["video"] == self.tr.data["id"] else None
        if not self.access.owner:
            if t in ("cookies", "webhooks", "webhooks_log", "glossary_applied", "admin", "yt_blocked", "yt_need_account", "perf",
                     "restarting"):
                return None
            if t == "queue":  # solo lo de sus bibliotecas
                return {**msg, "jobs": [j for j in msg["jobs"] if self.access.can_view(j.get("lib") or "principal")]}
            if t == "exports":
                return {**msg, "jobs": [j for j in msg["jobs"] if j["id"] in self._my_exports]}
            if t == "comments":
                v = self.vaults.of(str(msg.get("video", "")))
                return msg if v and self.access.can_view(v.id) else None
            if t == "vaults_changed":  # cambió el acceso: se recalcula (quizá ya no puede entrar)
                req = getattr(self.ws, "request", None)
                if self.admin and req is not None:
                    self.access = self.admin.auth.access(req)
                if not self.access.can_view(self.vault.id):
                    asyncio.ensure_future(self.ws.close())
                    return None
                return self._vaults_msg()
        if t == "prefs":  # con los valores propios de la biblioteca de esta pestaña
            return self._prefs_msg()
        if t in ("glossary", "people_saved") and msg.get("vault") not in (None, self.vault.id):
            return None
        if t == "vaults_changed":
            if self.vaults.get(self.vault.id) is None:  # la quitaron desde otra pestaña
                self.vault = self.vaults.main
                asyncio.ensure_future(self._send_vault_state())
                return None
            return self._vaults_msg()
        return msg

    # ------------------------------------------------------- administración
    def _client_error(self, m: dict):
        """Un error de la interfaz (JavaScript o una acción que intentó sin permiso) va al registro. Acotado:
        hasta 50 por conexión, textos cortos (cualquiera puede mandarlo, también un invitado)."""
        if not self._page_note():
            return
        kind = "".join(ch for ch in str(m.get("kind", "js"))[:30] if ch.isalnum() or ch in "._-") or "js"
        diag.error(f"interfaz.{kind}", str(m.get("message", ""))[:400])

    def _page_note(self) -> bool:
        """¿Se anota lo que manda esta conexión (errores de la página, rechazos)? Hasta 20 por minuto; el registro
        además tiene un tope para todas juntas (vt/diag.py)."""
        now = time.time()
        win = getattr(self, "_notes", None)
        if not win or now - win[0] > 60:
            self._notes = win = [now, 0]
        win[1] += 1
        return win[1] <= 20

    async def _diag_report(self):
        """Ajustes › Rendimiento › «Guardar informe»: el informe de diagnóstico (vt/diag.py). En este equipo se
        guarda en Descargas y se muestra en el Explorador; desde otro equipo vuelve el texto para descargarlo."""
        info = {"Perfil": (self.info or {}).get("profile", ""), "Dispositivo": (self.info or {}).get("device", ""),
                "Voz": (self.info or {}).get("voice", ""), "Bibliotecas": len(self.vaults.all()),
                "Registro": str(diag.path() or "")}
        text = await asyncio.to_thread(diag.report, info)
        name = time.strftime("Translay-informe-%Y%m%d-%H%M%S.txt")
        if self.access.local:
            # TRANSLAY_REPORT_DIR: otra carpeta y sin abrir el Explorador (las pruebas e2e no tocan Descargas)
            folder = Path(os.environ.get("TRANSLAY_REPORT_DIR") or downloads())
            try:
                folder.mkdir(parents=True, exist_ok=True)
                out = folder / name
                await asyncio.to_thread(out.write_text, text, "utf-8")
                if not os.environ.get("TRANSLAY_REPORT_DIR"):
                    reveal(out)
                return await self.ws.send_json({"type": "diag_report", "path": str(out), "name": name})
            except OSError as e:  # Descargas protegida o sin espacio: se descarga desde la página
                diag.error("informe", f"no se pudo guardar en Descargas: {e}")
        await self.ws.send_json({"type": "diag_report", "name": name, "text": text})

    async def _rec_mute(self, m: dict):
        """{"type":"rec_mute","on":true,"label":<etiqueta de la pista>} al empezar a grabar una ventana con
        «Silenciar las otras apps al grabar una ventana»; on=false al terminar. Solo el dueño en este equipo:
        toca el sonido de sus aplicaciones."""
        if not self.access.local:
            return await self.ws.send_json({"type": "rec_mute", "error": "remote"})
        if m.get("on"):
            out = await asyncio.to_thread(self.appmute.mute_others, str(m.get("label", ""))[:200], self)
        else:
            out = {"restored": await asyncio.to_thread(self.appmute.restore, self)}
        await self.ws.send_json({"type": "rec_mute", **out})
