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
  {"type":"playlist", "url":<enlace>}                la importa como colección y la manda a la cola
  {"type":"yt_batch", "urls":[…], "lang"}            enlaces de YouTube o Dropbox (vt/links.py) a la cola; batch_added
  {"type":"video_lang", "video", "lang":"en"|"es"}   idioma en que se habla (en español solo se transcribe)
  {"type":"export", "videos":[ids], "kinds":[…], "name"}  exportar (vt/exporter.py) · export_remove
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

Doblaje: cada frase final pasa por una cola de voz que atiende primero lo que
se va a escuchar (las frases desde el punto de reproducción en adelante, en
orden). La voz corre en su propio hilo y proceso, así el reconocimiento no
espera a la síntesis.
"""

import asyncio
import json
import struct
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from functools import partial

from .store import _SAFE_ID as _SAFE_VID, Store, Transcript
from . import events
from .auth import Access
from .vaults import VAULT_PREFS, RoutedStore

# lo que solo hace el dueño; lo que además de ver puede hacer quien tiene "importar"
OWNER_ONLY = {"prefs_set", "cookies_browsers", "cookies_import", "queue_pause", "queue_resume", "queue_clear",
              "queue_unblock", "queue_remove", "lib_delete", "lib_clear", "lib_remove", "glossary_set", "people_set",
              "people_save", "people_forget", "power_info", "coll_create", "coll_toggle", "coll_rename", "coll_delete", "lib_rename",
              "comment_add", "comment_edit", "comment_delete"}
IMPORT_ONLY = {"youtube", "playlist", "video_lang", "yt_batch", "lib_register", "queue_add", "queue_video", "watch"}
from .streaming import Partial, Segment, StreamingTranscriber
from .translate import Translator


class Session:
    def __init__(self, ws, asr, gpu: ThreadPoolExecutor, store: Store,
                 translator: Translator, info: dict, dubber=None, tts_exec: ThreadPoolExecutor | None = None,
                 youtube=None, library=None, res=None, processor=None, prefs=None, notify=None, exporter=None,
                 vaults=None, access: Access | None = None, admin=None, perf=None):
        self.ws = ws
        self.perf = perf  # equipo, perfil y límites (vt/perf.py)
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

    def _prefs_msg(self) -> dict:
        m = self.prefs.public()
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
                "public": [{"id": v.id, "name": v.name, "color": v.meta.get("color"), "icon": v.meta.get("icon")}
                           for v in self.vaults.all() if (v.meta.get("access") or {}).get("mode") == "publica"]}

    def _allowed(self, t: str, m: dict) -> bool:
        """¿Esta conexión puede pedir esto?"""
        a = self.access
        if a.owner:
            return True
        if t in OWNER_ONLY or t.startswith(("admin_", "trash_", "perf_")) or t == "server_restart" or \
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
            if t in ("lib_register", "watch", "video_lang"):  # la del video, si ya está en alguna biblioteca
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
                    elif m.get("type") in ("perf_get", "perf_set", "server_restart") and self.perf:
                        asyncio.create_task(self._perf(m))
                    elif self.library and m.get("type") in ("lib_delete", "lib_clear"):
                        asyncio.create_task(self._delete(m))
                    elif self.library and m.get("type", "").startswith(("lib", "coll")):
                        await self._library(m)
                    elif m.get("type") in ("cookies_browsers", "cookies_import"):
                        asyncio.create_task(self._cookies(m))
                    elif m.get("type") == "prefs_set" and self.prefs:
                        key, value = str(m.get("key")), m.get("value")
                        if key in VAULT_PREFS:  # propia de la biblioteca abierta
                            if self.prefs._valid(key, value):
                                self.vaults.set_pref(self.vault.id, key, value)
                                self.notify({"type": "prefs"})  # cada pestaña, con los de su biblioteca
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
                        asyncio.create_task(self._playlist(m.get("url", ""), str(m.get("lang") or "en")))
                    elif m.get("type") == "video_lang":
                        await self._video_lang(str(m.get("video", "")), str(m.get("lang", "")))
                    elif m.get("type") == "yt_batch":
                        asyncio.create_task(self._batch(list(m.get("urls", [])), str(m.get("coll") or ""),
                                                        bool(m.get("quiet")), bool(m.get("front")),
                                                        lang=str(m.get("lang") or "en")))
                    elif m.get("type") in ("export", "export_remove") and self.exporter:
                        await self._export(m)
                    elif m.get("type", "").startswith("queue_") and self.processor:
                        await self._queue(m)
                    else:
                        self.q.put_nowait((m.get("type"), m))
        finally:
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
                    self.st.language = self.tr.lang
                    vault = self._vault_of(self.tr.data["id"])
                    await self.ws.send_json({"type": "transcript", **self.tr.public(),
                                             "voice_refs": self._voice_refs(self.tr.data["id"]),
                                             "prefix": vault.prefix, "vault": vault.id})
                    if self._backfill:
                        self._backfill.cancel()
                    self._backfill = asyncio.create_task(self._translate_stale(self.tr))
                    # la voz que falte la completa la cola (vt/processor.py) al ver o
                    # procesar el video: hacerlo también aquí duplicaba el trabajo
            if self.tr is not None and self.st.ready():
                try:
                    await self._run(self.st.step)
                except Exception:  # una falla no debe detener la sesión
                    traceback.print_exc()
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
            if isinstance(ev, Segment):
                translation = None if tr.native else await loop.run_in_executor(
                    self.gpu, self.res.run, ("mt",), partial(self.translator.translate, glossary=self._gl(tr)), ev.text)
                seg, removed = tr.add_segment(ev.start, ev.end, ev.text, translation,
                                              self.translator.name)
                if self.dubber and not tr.native:  # ya en español: solo se transcribe
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

    async def _live_translation(self, src: str) -> str:
        """Traduce la frase abierta para el subtítulo en vivo (solo si cambió)."""
        if not src:
            self._live_src = self._live_es = ""
        elif self.tr is not None and self.tr.native:
            self._live_src = self._live_es = src
        elif src != self._live_src:
            loop = asyncio.get_running_loop()
            self._live_es = await loop.run_in_executor(
                self.gpu, self.res.run, ("mt",), partial(self.translator.translate, glossary=self._gl(self.tr)),
                src) or ""
            self._live_src = src
        return self._live_es

    async def _translate_stale(self, tr: Transcript):
        """Traduce frases guardadas sin traducción (o con otro modelo), por lotes."""
        name = self.translator.name
        if name == "none":
            return
        loop = asyncio.get_running_loop()
        tx = partial(self.translator.translate_many, glossary=self._gl(tr))
        while self.tr is tr and (todo := tr.stale(name)[:16]):
            outs = await loop.run_in_executor(self.gpu, self.res.run, ("mt",), tx, [s["text"] for s in todo])
            for seg, es in zip(todo, outs):
                tr.set_translation(seg["id"], es, name)
            tr.save()
            await self.ws.send_json({"type": "translations",
                                     "items": [{"id": s["id"], "translation": es}
                                               for s, es in zip(todo, outs)]})

    # ---------------------------------------------------------------- doblaje
    def _queue_dub(self, prio: int, tr: Transcript, seg: dict, orig_db: float | None):
        """prio 0: frase en vivo (modo intérprete, va primero); 1: por delante / guardada."""
        if not self.dubber or not seg.get("translation") or tr.native:
            return
        old = self.dub_pending.get(seg["id"])
        self.dub_pending[seg["id"]] = (min(prio, old[0]) if old else prio, tr, orig_db)
        self.dub_event.set()

    def _next_dub(self):
        """La frase pendiente que antes se va a escuchar."""
        best, best_key = None, None
        for sid, (prio, tr, _) in self.dub_pending.items():
            seg = next((x for x in tr.segments if x["id"] == sid), None)
            if seg is None:
                continue
            ahead = seg["end"] >= self.playhead - 0.5
            key = (prio, not ahead, seg["start"] if ahead else -seg["start"])
            if best_key is None or key < best_key:
                best, best_key = sid, key
        if best is None:
            self.dub_pending.clear()
            return None
        prio, tr, orig_db = self.dub_pending.pop(best)
        return prio, tr, best, orig_db

    def _next_dub(self):
        """La frase pendiente que antes se va a escuchar."""
        best, best_key = None, None
        for sid, (prio, tr, _) in self.dub_pending.items():
            seg = next((x for x in tr.segments if x["id"] == sid), None)
            if seg is None:
                continue
            ahead = seg["end"] >= self.playhead - 0.5
            key = (prio, not ahead, seg["start"] if ahead else -seg["start"])
            if best_key is None or key < best_key:
                best, best_key = sid, key
        if best is None:
            self.dub_pending.clear()
            return None
        prio, tr, orig_db = self.dub_pending.pop(best)
        return prio, tr, best, orig_db

    def _queue_stale_dubs(self, tr: Transcript):
        for seg in tr.segments:
            d = seg.get("dub")
            if seg.get("translation") and (not d or d.get("text") != seg["translation"]
                                           or d.get("engine") != self.dubber.tts.engine):
                self._queue_dub(1, tr, seg, seg.get("orig_db"))

    async def _dub_worker(self):
        loop = asyncio.get_running_loop()
        while True:
            if not self.dub_pending:
                self.dub_event.clear()
                await self.dub_event.wait()
                continue
            item = self._next_dub()
            if item is None:
                continue
            prio, tr, seg_id, orig_db = item
            seg = next((s for s in tr.segments if s["id"] == seg_id), None)
            if seg is None or tr is not self.tr:
                continue
            d = seg.get("dub")
            if (d and d.get("text") == seg.get("translation") and d.get("engine") == self.dubber.tts.engine
                    and d.get("voice") == seg.get("speaker")):
                continue
            if orig_db is not None:
                seg["orig_db"] = round(orig_db, 1)
            try:
                info = await loop.run_in_executor(self.tts_exec, self.res.run, ("tts",), self.dubber.synthesize, tr, seg,
                                                  seg.get("orig_db"))
            except Exception:  # una frase fallida no detiene el doblaje
                traceback.print_exc()
                continue
            if not info:
                continue
            info["text"] = seg["translation"]
            seg["dub"] = info
            tr.save()
            await self.ws.send_json({"type": "dub", "id": seg_id, "speaker": seg.get("speaker"),
                                     "url": self._vault_of(tr.data["id"]).url("/audio/" + info["file"])
                                     + f"?v={self._dub_seq}",
                                     "dur": info["dur"], "live": prio == 0})

    # ---------------------------------------------------------------- YouTube
    async def _youtube(self, url: str, queue: bool = False):
        loop = asyncio.get_running_loop()
        if not self.youtube:
            await self.ws.send_json({"type": "yt_error", "error": "YouTube no está habilitado"})
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
                     lang: str = "en"):
        """Varios enlaces a la vez: los videos entran a la cola sin descargar (se bajan en
        orden) y cada playlist se importa como colección. lang: el idioma en que se hablan."""
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
        self._import_lang(ids, known, lang)
        asyncio.create_task(self._fill_titles([i for i in ids if i.startswith("yt_")
                                               and (lib.data["videos"].get(i) or {}).get("title") == i[3:]], lib))
        if coll:
            for vid in ids:
                lib.toggle(coll, vid, True)
        if self.processor and ids:
            # "abrirlo": se descarga primero; «Solo descargar» (Preferencias): sin traducir
            dl_only = (mode == "descargar") if mode else self._download_only()  # mode: desde la API
            self.processor.add_many(ids, front=front, download_only=dl_only and not front,
                                    audio_only=self._audio_only())
        if ids:
            events.emit("video.agregado", self.vault.id, videos=ids, count=len(ids))
        await self.ws.send_json({"type": "batch_added", "videos": len(ids), "playlists": len(lists), "ids": ids,
                                 "quiet": bool(quiet), "elsewhere": elsewhere, "errors": errors})
        self.notify({"type": "library_changed"})
        for u in lists:
            await self._playlist(u, lang)

    def _import_lang(self, ids: list[str], known: set, lang: str):
        """Idioma elegido al importar: para lo nuevo, y para lo que ya estaba solo si se pidió
        «en español» (volver a importar en inglés no deshace lo que se cambió a mano)."""
        for vid in ids:
            if vid not in known or lang != "en":
                self._set_lang(vid, lang)

    def _set_lang(self, vid: str, lang: str) -> bool:
        """Idioma del video, en su transcripción (lo usa el procesamiento) y en la biblioteca."""
        from .store import LANGS

        if lang not in LANGS or not _SAFE_VID.fullmatch(vid):
            return False
        vault = self._vault_of(vid)
        tr = vault.store.open(vid)
        had = bool(tr.covered)
        changed = tr.set_lang(lang)
        if changed:
            tr.save()
        if vid in vault.library.data["videos"]:
            vault.library.set_field(vid, lang=lang)
        if changed and had and self.processor:
            self.processor.add(vid)  # lo reconocido en el otro idioma se rehace
        return changed

    async def _video_lang(self, vid: str, lang: str):
        if not self._set_lang(vid, lang):
            return
        if self.tr is not None and self.tr.data["id"] == vid:  # esta pestaña lo procesaba en vivo
            self.q.put_nowait(("seek", {}))
        vault = self._vault_of(vid)
        tr = vault.store.open(vid)
        # cada pestaña que lo tenga abierto vuelve a cargar su transcripción (ahora vacía)
        self.notify({"type": "bg", "video": vid, "msg": {"type": "transcript", **tr.public(), "voice_refs": {},
                                                         "prefix": vault.prefix, "vault": vault.id}})
        self.notify({"type": "library_changed"})

    async def _fill_titles(self, ids: list[str], lib=None):
        """Título y canal de los videos recién importados, 3 consultas a la vez y con pausas."""
        loop = asyncio.get_running_loop()
        lib = lib or self.library
        sem = asyncio.Semaphore(3)
        done: dict[str, dict] = {}

        async def one(vid):
            async with sem:
                info = await loop.run_in_executor(None, self.youtube.quick_info, vid[3:])
                await asyncio.sleep(0.3)
            if info.get("title") and info["title"] != vid[3:]:
                done[vid] = {"title": info["title"], "channel": info.get("channel", "")}

        for k in range(0, len(ids), 30):  # se guarda y se avisa cada 30
            await asyncio.gather(*(one(v) for v in ids[k:k + 30]))
            if done:
                lib.set_fields({v: f for v, f in done.items()
                                if (lib.data["videos"].get(v) or {}).get("title") == v[3:]})
                done.clear()
                self.notify({"type": "library_changed"})

    async def _playlist(self, url: str, lang: str = "en"):
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
        self._import_lang([i for i in c["items"] if i in lib.data["videos"]], known, lang)
        if self.processor:  # en orden: la cola descarga y procesa uno tras otro
            self.processor.add_many([i for i in c["items"] if i in lib.data["videos"]],
                                    download_only=self._download_only(), audio_only=self._audio_only())
        events.emit("coleccion.creada", self.vault.id, collection=c["id"], name=c["name"], kind="playlist",
                    count=len(c["items"]))
        await self.ws.send_json({"type": "playlist_added", "coll": c["id"], "name": c["name"],
                                 "count": len(c["items"])})
        self.notify({"type": "library_changed"})

    async def _export(self, m: dict):
        if m["type"] == "export_remove":
            if self.access.owner or str(m.get("job", "")) in self._my_exports:
                self.exporter.remove(str(m.get("job", "")))
            return
        try:
            vids = [str(v) for v in m.get("videos", [])
                    if (o := self.vaults.of(str(v))) is not None and self.access.can_view(o.id)]
            job = self.exporter.add(vids, list(m.get("kinds", [])), str(m.get("name", ""))[:120])
            self._my_exports.add(job["id"])
            await self.ws.send_json({"type": "export_started", "job": job["id"]})
        except ValueError as e:
            await self.ws.send_json({"type": "yt_error", "error": str(e)})

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
        tx = partial(self.translator.translate_many, glossary=gl)
        n_segs = n_vids = 0
        for f in sorted(vault.store.root.glob("*.json")):
            vid = f.stem
            if vid not in vault.library.data["videos"]:
                continue
            tr = vault.store.open(vid)
            if tr.native:  # en español: no pasa por el traductor
                continue
            todo = [s for s in tr.segments if gl.matches(s.get("text", ""), changed)]
            if not todo:
                continue
            outs = await loop.run_in_executor(self.gpu, self.res.run, ("mt",), tx, [s["text"] for s in todo])
            for s, es in zip(todo, outs):
                tr.set_translation(s["id"], es, self.translator.name)
            tr.save()
            n_segs += len(todo)
            n_vids += 1
            if self.processor and any(s.get("dub") for s in tr.segments):
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
                return await self.ws.send_json({"type": "yt_error", "error": "esa persona aún no tiene una voz de referencia"})
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

    # ------------------------------------------------------------- rendimiento
    async def _perf(self, m: dict):
        """perf_get · perf_set {profile?, vram_mb?, ram_mb?, threads?} · server_restart"""
        loop = asyncio.get_running_loop()
        if m["type"] == "server_restart":
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
                    raise ValueError("falta qué borrar de la papelera")
                for v in ([self.vaults.get(str(m["vault"]))] if m.get("vault") else self.vaults.all()):
                    if v:
                        await loop.run_in_executor(None, lambda v=v: Trash(v.root).purge(tid=tid or None, everything=everything))
        except (ValueError, OSError) as e:
            await self.ws.send_json({"type": "vault_error", "error": str(e) or "no se pudo"})
        items = []
        for v in self.vaults.all():
            if self.access.can_view(v.id):
                items += [dict(x, vault=v.id) for x in Trash(v.root).entries()]
        await self.ws.send_json({"type": "trash", "items": sorted(items, key=lambda x: -x["created"])})

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
        if best is None:
            return None
        _, vid, pos = best
        try:
            segs = self.vault.store.open(vid).segments
        except (ValueError, OSError):
            return {"video": vid}
        seg = next((s for s in reversed(segs) if s["start"] <= pos + 0.5 and s.get("translation")), None)
        return {"video": vid, "en": seg.get("text", "") if seg else "", "es": seg.get("translation", "") if seg else ""}

    # --------------------------------------------------------- cola de fondo
    async def _queue(self, m: dict):
        kind, vid = m["type"], str(m.get("video", ""))
        if kind == "queue_add":
            # download_only: «Descargar» desde «Ver» (bajarlo sin abrirlo ni traducirlo)
            self.processor.add_many([vid], front=bool(m.get("front")), download_only=bool(m.get("download_only")))
        elif kind == "queue_remove":
            self.processor.remove(vid)
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
            if t in ("cookies", "webhooks", "webhooks_log", "glossary_applied", "admin", "yt_blocked", "perf", "restarting"):
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
    async def _admin(self, m: dict):
        """Acceso, claves de API, webhooks y red: Preferencias → Acceso y API (solo el dueño)."""
        a, t = self.admin, m["type"]
        if a is None:
            return
        try:
            if t == "admin_owner_pw":
                pw = str(m.get("password", ""))
                if pw and len(pw) < 6:
                    raise ValueError("la contraseña debe tener al menos 6 caracteres")
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
            return await self.ws.send_json({"type": "vault_error", "error": str(e) or "no se pudo"})
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
            return await self.ws.send_json({"type": "vault_error", "error": str(e) or "no se pudo"})
        self.notify({"type": "vaults_changed"})
        await self._send_vault_state()

    # ------------------------------------------------------- sesión de YouTube
    def _cookies_path(self):
        return self.vaults.cookies

    async def _cookies_status(self, extra: dict | None = None):
        from . import cookies

        await self.ws.send_json({"type": "cookies", "browsers": cookies.detect(),
                                 "status": cookies.status(self._cookies_path()), **(extra or {})})

    async def _cookies(self, m: dict):
        from . import cookies

        if m["type"] == "cookies_browsers":
            return await self._cookies_status()
        key = str(m.get("browser", ""))
        try:
            info = await asyncio.get_running_loop().run_in_executor(
                None, cookies.import_browser, key, self._cookies_path())
        except Exception as e:
            return await self._cookies_status({"error": cookies.friendly(e, key)})
        self.cookies_imported(info)
        await self._cookies_status({"imported": info})

    def cookies_imported(self, info: dict):
        """Tras importar una sesión, las descargas pasan a usarla (y siguen si estaban en pausa)."""
        if self.prefs and self.prefs.set("yt_session", "archivo"):
            self.notify(self.prefs.public())
        if self.processor:
            self.processor.unblock()


def pick_folder() -> str:
    """Cuadro nativo para elegir una carpeta (el servidor corre en este mismo equipo)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return ""
    try:
        root = tk.Tk()
    except Exception:  # sin pantalla (Docker, servidor remoto): la carpeta se escribe a mano
        return ""
    root.withdraw()
    root.attributes("-topmost", True)  # delante del navegador
    try:
        return filedialog.askdirectory(parent=root, title="Carpeta de la biblioteca", mustexist=False) or ""
    finally:
        root.destroy()
