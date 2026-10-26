"""API HTTP (JSON) para integrar el traductor con otras apps, inicio de sesión y red local.

Autenticación: Authorization: Bearer vt_…  (Preferencias → Acceso y API → Claves).
Una clave sirve para todas las bibliotecas o para una; "lectura" o "escritura".
Desde este mismo equipo, sin clave, la API responde como al dueño.

  GET    /api/v1                                  esta lista
  GET    /api/v1/events                           eventos de los webhooks
  GET    /api/v1/libraries                        bibliotecas
  GET    /api/v1/libraries/{lib}                  una biblioteca
  GET    /api/v1/libraries/{lib}/videos           ?collection=&limit=&offset=
  GET    /api/v1/libraries/{lib}/collections
  GET    /api/v1/libraries/{lib}/search?q=        en las transcripciones
  POST   /api/v1/libraries/{lib}/import           {"urls": [...], "mode": "traducir|descargar", "priority": false}
  GET    /api/v1/libraries/{lib}/glossary         ·  PUT {"entries": [{"src", "dst"}]}
  GET    /api/v1/videos/{id}                      datos, avance y estado en la cola
  GET    /api/v1/videos/{id}/transcript           frases con inglés y español
  GET    /api/v1/videos/{id}/subtitles?lang=es    SRT (es | en)
  DELETE /api/v1/videos/{id}                      lo borra con sus archivos
  GET    /api/v1/queue?library=                   cola
  POST   /api/v1/queue                            {"video": id, "priority": false}
  DELETE /api/v1/queue/{id}
  POST   /api/v1/queue/pause  ·  /queue/resume    (clave para todas las bibliotecas)
  POST   /api/v1/exports                          {"videos": [...], "kinds": ["es_video", "srt_es", …]}
  GET    /api/v1/exports/{id}                     estado y enlace de descarga

Inicio de sesión (la vista): POST /api/auth/login {password, vault?} · POST /api/auth/logout · GET /api/auth/me
"""

import asyncio
import json
import socket
import time

from . import events
from .auth import is_local
from .exporter import KINDS, srt

COOKIE = "vt_s"


class CollectorWS:
    """WebSocket de mentira: la API reutiliza la lógica de la sesión y junta sus respuestas."""

    def __init__(self):
        self.msgs: list[dict] = []
        self.request = None

    async def send_json(self, obj):
        self.msgs.append(obj)

    def last(self, kind: str) -> dict | None:
        return next((m for m in reversed(self.msgs) if m.get("type") == kind), None)


class Admin:
    """Acceso, claves, webhooks y red local (lo que el dueño maneja en Preferencias)."""

    def __init__(self, auth, hooks, port: int):
        self.auth, self.hooks, self.port = auth, hooks, port
        self.server = None
        self._lan: list = []

    @staticmethod
    def lan_ips() -> list[str]:
        ips = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(info[4][0])
        except OSError:
            pass
        try:  # la que sale a la red (sin enviar nada)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))

    @property
    def network(self) -> bool:
        return bool(self.auth.data.get("network"))

    async def set_network(self, on: bool):
        """Escuchar también en la red local (otros equipos y celulares de la misma red)."""
        for srv in self._lan:
            srv.close()
        self._lan = []
        if on and self.server:
            for ip in self.lan_ips():
                try:
                    self._lan.append(await self.server.listen(ip, self.port))
                except OSError as e:
                    print(f"[red] {ip}:{self.port}: {e}", flush=True)
        if self.auth.data.get("network") != on:
            self.auth.data["network"] = on
            self.auth._save()

    def public(self) -> dict:
        urls = [f"http://{ip}:{self.port}" for ip in self.lan_ips()] if self.network else []
        return {**self.hooks.public(), "type": "admin", "owner_set": self.auth.owner_set,
                "keys": self.auth.keys_public(), "network": self.network, "urls": urls, "port": self.port}


class Api:
    def __init__(self, vaults, auth, processor, exporter, make_session):
        self.vaults, self.auth, self.processor, self.exporter = vaults, auth, processor, exporter
        self._fails: dict[str, list[float]] = {}  # intentos fallidos por equipo (últimos 10 min)
        self._login_sem = asyncio.Semaphore(2)  # scrypt pesa: como mucho dos a la vez
        self.make_session = make_session  # (biblioteca, acceso) → Session con CollectorWS

    # ------------------------------------------------------------ sesión de la vista
    async def auth_route(self, req):
        sub = req.path[len("/api/auth/"):]
        if sub == "login" and req.method == "POST":
            body = req.json() or {}
            ip = req.peer or ""
            now = time.time()
            fails = self._fails[ip] = [t for t in self._fails.get(ip, []) if now - t < 600]
            if len(fails) >= 10:  # diez fallos en diez minutos: ese equipo espera
                return 429, {"error": "demasiados intentos; espera unos minutos"}, {}
            await asyncio.sleep(0.4)  # frena los intentos en ráfaga
            async with self._login_sem:  # el hash corre aparte: el servidor sigue respondiendo
                vault = str(body.get("vault", "") or "")
                grant = await asyncio.get_running_loop().run_in_executor(
                    None, self.auth.verify, str(body.get("password", "")), vault)
            token = None if grant is False else self.auth.login("", vault, req.cookies.get(COOKIE, ""), grant)
            if not token:
                fails.append(now)
                return 401, {"error": "contraseña incorrecta"}, {}
            self._fails.pop(ip, None)
            return 200, {"ok": True}, {"Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
                                                     f"Max-Age={30 * 86400}"}
        if sub == "logout" and req.method == "POST":
            self.auth.logout(req.cookies.get(COOKIE, ""))
            return 200, {"ok": True}, {"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"}
        if sub == "me":
            return 200, self.auth.access(req).public(), {}
        return 404, {"error": "no existe"}, {}

    # ------------------------------------------------------------------- API v1
    async def route(self, req):
        acc = self.auth.access(req)
        if not acc.any:
            return 401, {"error": "falta una clave de API válida (Authorization: Bearer vt_…)"}, {}
        parts = [p for p in req.path[len("/api/v1"):].split("/") if p]
        m = req.method
        try:
            return await self._dispatch(req, acc, parts, m)
        except PermissionError as e:
            return 403, {"error": str(e) or "sin permiso"}, {}
        except (KeyError, LookupError) as e:
            return 404, {"error": str(e).strip("'") or "no existe"}, {}
        except ValueError as e:
            return 400, {"error": str(e)}, {}

    def _vault(self, acc, lib: str, write: bool = False):
        v = self.vaults.get(lib)
        if v is None or not acc.can_view(lib):
            raise LookupError("biblioteca no encontrada")
        if write and not self._can_write(acc, lib):
            raise PermissionError("esta clave es de solo lectura")
        return v

    @staticmethod
    def _can_write(acc, lib) -> bool:
        return acc.owner or acc.perm(lib) == "escritura"

    def _video(self, acc, vid: str, write: bool = False):
        v = self.vaults.of(vid)
        if v is None or not acc.can_view(v.id):
            raise LookupError("video no encontrado")
        if write and not self._can_write(acc, v.id):
            raise PermissionError("esta clave es de solo lectura")
        return v

    def _video_public(self, v, vid: str) -> dict:
        e = v.library.data["videos"][vid]
        out = {"id": vid, "library": v.id, **{k: e.get(k) for k in ("title", "duration", "source", "channel",
                                                                     "categories", "added")}}
        out.update({k: v.url(e[k]) for k in ("media", "audio", "thumb") if e.get(k)})
        try:
            out["progress"] = self.processor.progress(vid)
        except Exception:
            out["progress"] = {"asr": 0, "dub": 0}
        j = self.processor._job(vid)
        out["queue"] = {k: j.get(k) for k in ("state", "prio", "error", "dl")} if j else None
        return out

    async def _session(self, vault, acc):
        sess = self.make_session(vault, acc)
        sess.vault = vault
        return sess

    async def _dispatch(self, req, acc, p, m):
        if not p:
            return 200, {"version": 1, "doc": __doc__.split("Inicio de sesión")[0].strip()}, {}
        head = p[0]
        if head == "events":
            return 200, events.CATALOG, {}
        # ---------------------------------------------------------- bibliotecas
        if head == "libraries":
            if len(p) == 1:
                items = [i for i in self.vaults.public() if acc.can_view(i["id"])]
                if not acc.owner:
                    items = [{k: v for k, v in i.items() if k not in ("path", "access")} for i in items]
                return 200, items, {}
            v = self._vault(acc, p[1])
            if len(p) == 2:
                info = v.info()
                if not acc.owner:
                    info = {k: x for k, x in info.items() if k not in ("path", "access")}
                return 200, info, {}
            what = p[2]
            if what == "videos":
                data = v.library.public()
                coll = req.query.get("collection", "all")
                c = next((x for x in data["collections"] if x["id"] == coll), None)
                if c is None:
                    raise LookupError("colección no encontrada")
                off, lim = int(req.query.get("offset", 0)), min(500, int(req.query.get("limit", 100)))
                ids = c["items"][off:off + lim]
                return 200, {"total": len(c["items"]), "offset": off,
                             "videos": [self._video_public(v, i) for i in ids if i in v.library.data["videos"]]}, {}
            if what == "collections":
                return 200, [{k: c.get(k) for k in ("id", "name", "kind", "url", "channel")} | {"count": len(c["items"])}
                             for c in v.library.public()["collections"]], {}
            if what == "search":
                sess = await self._session(v, acc)
                await sess._search(req.query.get("q", ""))
                r = sess.ws.last("search_results") or {}
                return 200, {"q": r.get("q"), "total": r.get("total", 0), "results": r.get("results", [])}, {}
            if what == "import" and m == "POST":
                v = self._vault(acc, p[1], write=True)
                body = req.json() or {}
                urls = [str(u) for u in body.get("urls") or ([body["url"]] if body.get("url") else [])]
                if not urls:
                    raise ValueError("faltan los enlaces (urls)")
                mode = str(body.get("mode", ""))
                if mode not in ("", "traducir", "descargar"):
                    raise ValueError("mode: traducir o descargar")
                sess = await self._session(v, acc)
                await sess._batch(urls, "", True, bool(body.get("priority")), mode)
                r = sess.ws.last("batch_added") or {}
                return 202, {"videos": r.get("videos", 0), "playlists": r.get("playlists", 0),
                             "elsewhere": r.get("elsewhere", {})}, {}
            if what == "glossary":
                if m == "PUT":
                    v = self._vault(acc, p[1], write=True)
                    body = req.json() or {}
                    sess = await self._session(v, acc)
                    await sess._glossary({"type": "glossary_set", "entries": body.get("entries") or []})
                return 200, {"entries": v.glossary.entries}, {}
            raise LookupError("no existe")
        # ---------------------------------------------------------------- videos
        if head == "videos" and len(p) >= 2:
            vid = p[1]
            if len(p) == 2 and m == "DELETE":
                v = self._video(acc, vid, write=True)
                sess = await self._session(v, acc)
                await sess._delete({"type": "lib_delete", "videos": [vid]})
                return 200, {"deleted": vid}, {}
            v = self._video(acc, vid)
            if len(p) == 2:
                return 200, self._video_public(v, vid), {}
            tr = v.store.open(vid)
            if p[2] == "transcript":
                return 200, {"id": vid, "segments": [{k: s.get(k) for k in ("id", "start", "end", "text", "translation",
                                                                             "speaker")} for s in tr.segments],
                             "speaker_names": tr.data.get("speaker_names") or {}, "comments": tr.comments}, {}
            if p[2] == "subtitles":
                lang = req.query.get("lang", "es")
                return 200, srt(tr.segments, "translation" if lang == "es" else "text"), {
                    "Content-Type": "application/x-subrip; charset=utf-8"}
            raise LookupError("no existe")
        # ------------------------------------------------------------------ cola
        if head == "queue":
            if len(p) == 1 and m == "GET":
                lib = req.query.get("library")
                jobs = [j for j in self.processor.public()["jobs"] if acc.can_view(j.get("lib") or "principal")
                        and (not lib or (j.get("lib") or "principal") == lib)]
                q = self.processor.public()
                return 200, {"paused": q["paused"], "current": q["current"] if acc.owner else None,
                             "blocked_until": q["blocked_until"], "jobs": jobs}, {}
            if len(p) == 1 and m == "POST":
                body = req.json() or {}
                vid = str(body.get("video", ""))
                self._video(acc, vid, write=True)
                self.processor.add(vid, front=bool(body.get("priority")))
                return 202, {"queued": vid}, {}
            if len(p) == 2 and p[1] in ("pause", "resume") and m == "POST":
                if not (acc.owner or all(self._can_write(acc, v.id) for v in self.vaults.all())):
                    raise PermissionError("pausar la cola requiere una clave de escritura para todas las bibliotecas")
                self.processor.set_paused(p[1] == "pause")
                return 200, {"paused": p[1] == "pause"}, {}
            if len(p) == 2 and m == "DELETE":
                self._video(acc, p[1], write=True)
                self.processor.remove(p[1])
                return 200, {"removed": p[1]}, {}
        # ------------------------------------------------------------ exportar
        if head == "exports":
            if len(p) == 1 and m == "POST":
                body = req.json() or {}
                vids = [str(x) for x in body.get("videos", [])]
                for vid in vids:
                    self._video(acc, vid)
                kinds = [k for k in body.get("kinds", []) if k in KINDS]
                if not kinds:
                    raise ValueError("kinds: " + ", ".join(KINDS))
                job = self.exporter.add(vids, kinds, str(body.get("name", ""))[:120])
                return 202, {"id": job["id"], "state": job["state"]}, {}
            if len(p) == 2 and m == "GET":
                j = next((x for x in self.exporter.public()["jobs"] if x["id"] == p[1]), None)
                if j is not None and not acc.owner:  # solo exportaciones de videos que se pueden ver
                    vs = [self.vaults.of(v) for v in j.get("videos") or []]
                    if not vs or not all(v is not None and acc.can_view(v.id) for v in vs):
                        j = None
                if j is None:
                    raise LookupError("exportación no encontrada")
                return 200, j, {}
        raise LookupError("no existe")


def make_guard(auth, vaults):
    """Quién puede pedir cada archivo: los de una biblioteca, quien puede verla."""

    def guard(req):
        p = req.path
        if p.startswith("/v/"):
            vid = p[3:].split("/", 1)[0]
            ok = auth.access(req).can_view(vid)
        elif p.startswith(("/media/", "/audio/", "/voices/", "/people/")):
            ok = auth.access(req).can_view("principal")
        elif p.startswith(("/thumb/", "/exports/", "/chan/")):
            ok = auth.access(req).any
        elif p.startswith(("/api/upload/", "/api/thumb/")):
            vid = p.rsplit("/", 1)[-1]
            v = vaults.of(vid) or vaults.get(req.query.get("lib")) or vaults.main
            ok = auth.access(req).can_import(v.id)
        elif p.startswith("/api/"):
            ok = auth.access(req).owner
        else:
            return None  # la página (html, css, js) es pública: muestra el inicio de sesión si hace falta
        return None if ok else (403, "Sin acceso")

    return guard
