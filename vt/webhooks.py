"""Webhooks: avisos HTTP (POST JSON) a otras apps cuando pasa algo (vt/events.py).

data/webhooks.json:  [{id, name, url, events: [...] (vacío = todos), vault: "all"|id,
                       secret, active, created}]

Cada envío:
  POST <url>
  Content-Type: application/json
  X-VT-Event: video.procesado
  X-VT-Delivery: <id del envío>
  X-VT-Signature: sha256=<HMAC-SHA256 del cuerpo con el secreto del webhook>
  {"event": "...", "time": 1730000000.0, "vault": "ciencia", "data": {...}}

Si falla (sin respuesta 2xx) se reintenta a los 10 s, 1 min y 5 min. Los últimos
envíos quedan en memoria para verlos en Preferencias → Webhooks.
"""

import hashlib
import hmac
import json
import queue
import secrets
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

from . import events

RETRIES = (10, 60, 300)
TIMEOUT_S = 8


class Webhooks:
    def __init__(self, path: Path, notify=lambda m: None):
        self.path, self.notify = path, notify
        self._lock = threading.Lock()
        self.hooks: list[dict] = []
        if path.exists():
            try:
                self.hooks = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                self.hooks = []
        self.log: deque = deque(maxlen=60)
        self._q: queue.Queue = queue.Queue()
        self._pending: dict = {}  # (webhook, evento) agrupado → datos más recientes
        threading.Thread(target=self._sender, daemon=True).start()
        threading.Thread(target=self._flusher, daemon=True).start()
        events.subscribe(self.on_event)

    def _save(self):
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.hooks, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    # ------------------------------------------------------------ administrar
    def public(self) -> dict:
        return {"type": "webhooks", "hooks": self.hooks, "log": list(self.log)[::-1],
                "catalog": events.CATALOG}

    def upsert(self, h: dict) -> dict:
        url = str(h.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("la URL debe empezar con http:// o https://")
        evs = [e for e in h.get("events", []) if e in events.CATALOG]
        cur = next((x for x in self.hooks if x["id"] == h.get("id")), None)
        if cur is None:
            cur = {"id": secrets.token_hex(4), "secret": "whsec_" + secrets.token_urlsafe(24), "created": time.time()}
            self.hooks.append(cur)
        cur.update(name=str(h.get("name", "")).strip()[:60] or url[:60], url=url, events=evs,
                   vault=str(h.get("vault") or "all"), active=bool(h.get("active", True)))
        self._save()
        return cur

    def remove(self, hid: str):
        self.hooks = [x for x in self.hooks if x["id"] != hid]
        self._save()

    def test(self, hid: str):
        h = next((x for x in self.hooks if x["id"] == hid), None)
        if h:
            self._q.put((h, "prueba", None, {"mensaje": "Webhook de prueba desde el traductor"}, 0))

    # ---------------------------------------------------------------- envío
    def _wants(self, h, name, vault) -> bool:
        if not h.get("active", True):
            return False
        if h.get("events") and name not in h["events"]:
            return False
        return h.get("vault", "all") == "all" or vault in (None, h["vault"])

    def on_event(self, name: str, vault, data: dict):
        for h in self.hooks:
            if not self._wants(h, name, vault):
                continue
            if name in events.COALESCE:
                self._pending[(h["id"], name)] = (h, vault, data)
            else:
                self._q.put((h, name, vault, data, 0))

    def _flusher(self):
        while True:
            time.sleep(events.COALESCE_S)
            items, self._pending = self._pending, {}
            for (_, name), (h, vault, data) in items.items():
                self._q.put((h, name, vault, data, 0))

    def _sender(self):
        while True:
            h, name, vault, data, attempt = self._q.get()
            if attempt and not any(x["id"] == h["id"] for x in self.hooks):
                continue  # se borró mientras esperaba el reintento
            body = json.dumps({"event": name, "time": time.time(), "vault": vault, "data": data},
                              ensure_ascii=False).encode()
            did = secrets.token_hex(6)
            sig = hmac.new(h["secret"].encode(), body, hashlib.sha256).hexdigest()
            req = urllib.request.Request(h["url"], data=body, method="POST", headers={
                "Content-Type": "application/json", "User-Agent": "video-translator-webhooks/1",
                "X-VT-Event": name, "X-VT-Delivery": did, "X-VT-Signature": f"sha256={sig}"})
            status, err = 0, ""
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                    status = r.status
            except urllib.error.HTTPError as e:
                status, err = e.code, str(e.reason)
            except Exception as e:
                err = str(e)[:160]
            ok = 200 <= status < 300
            self.log.append({"id": did, "hook": h["id"], "event": name, "time": time.time(), "status": status,
                             "ok": ok, "error": err, "attempt": attempt + 1})
            if not ok and attempt < len(RETRIES):
                delay = RETRIES[attempt]
                threading.Timer(delay, self._q.put, ((h, name, vault, data, attempt + 1),)).start()
            self.notify({"type": "webhooks_log", "log": list(self.log)[::-1]})
