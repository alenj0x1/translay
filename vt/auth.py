"""Acceso: quién puede ver y hacer qué.

  · Dueño: desde este mismo equipo entra sin iniciar sesión; desde otro equipo, con
    la contraseña del dueño (Preferencias → Acceso).
  · Cada biblioteca tiene su visibilidad (vault.json → "access"):
        privada      solo el dueño
        clave        cualquiera con el enlace y la contraseña de la biblioteca
        publica      cualquiera con el enlace
    y lo que puede hacer quien entra: "ver" (ver, buscar, exportar) o "importar"
    (además, agregar videos y mandarlos a la cola).
  · Claves de API (Authorization: Bearer vt_…): para todas las bibliotecas o una,
    de "lectura" o "escritura".

Las contraseñas y claves se guardan con hash (scrypt / sha256), nunca en claro.
Las sesiones son una cookie con un token al azar (30 días).

"Este equipo" = la conexión viene de 127.0.0.1 sin cabeceras de proxy: un túnel
(Cloudflare, ngrok) corre en el equipo pero agrega X-Forwarded-For y similares,
así que lo que llega por él cuenta como remoto.

Otros sitios: el navegador del dueño manda sus cookies (y, desde este equipo, ni
hacen falta) a cualquier página que le pida algo a localhost:8765. Por eso el
WebSocket y todo pedido que cambia algo exigen que la cabecera Origin sea la
propia app (same_origin); los scripts con clave de API no la necesitan.
"""

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

SESSION_DAYS = 30
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "cf-connecting-ip", "x-forwarded-host")
MODES = ("privada", "clave", "publica")
PERMS = ("ver", "importar")


def hash_pw(pw: str, salt: str | None = None) -> dict:
    salt = salt or secrets.token_hex(16)
    h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()
    return {"salt": salt, "hash": h}


def check_pw(pw: str, rec: dict | None) -> bool:
    if not rec or not pw:
        return False
    return hmac.compare_digest(hash_pw(pw, rec["salt"])["hash"], rec["hash"])


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def same_origin(headers: dict, allowed: tuple = ()) -> bool:
    """¿El pedido viene de la propia app? Sin Origin = no es un navegador (curl, scripts).
    Vale si el Origin coincide con el Host (o el X-Forwarded-Host de un proxy) o está en
    `allowed` (--allow-origin). "null" (iframes aislados, archivos locales) nunca vale."""
    origin = headers.get("origin")
    if origin is None:
        return True
    origin = origin.strip().rstrip("/").lower()
    if origin in allowed:
        return True
    netloc = urlsplit(origin).netloc
    hosts = {headers.get("host", "").lower(), headers.get("x-forwarded-host", "").split(",")[0].strip().lower()}
    return bool(netloc) and netloc in hosts


def is_local(req) -> bool:
    return req.peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1") and not any(h in req.headers for h in _PROXY_HEADERS)


class Access:
    """Lo que puede hacer una conexión: dueño (todo) o permisos por biblioteca."""

    def __init__(self, owner: bool = False, perms: dict | None = None, key: dict | None = None, local: bool = False):
        self.owner = owner
        self.perms = perms or {}  # biblioteca → "ver" | "importar" (| "escritura" para claves)
        self.key = key
        self.local = local

    def perm(self, vault_id: str) -> str | None:
        if self.owner:
            return "dueño"
        return self.perms.get(vault_id)

    def can_view(self, vault_id: str) -> bool:
        return self.perm(vault_id) is not None

    def can_import(self, vault_id: str) -> bool:
        return self.perm(vault_id) in ("dueño", "importar", "escritura")

    @property
    def any(self) -> bool:
        return self.owner or bool(self.perms)

    def public(self) -> dict:
        return {"owner": self.owner, "perms": self.perms, "local": self.local}


class Auth:
    def __init__(self, path: Path, vaults):
        self.path, self.vaults = path, vaults
        self._lock = threading.Lock()
        self.data = {"owner": None, "sessions": {}, "keys": []}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                pass
        now = time.time()
        self.data["sessions"] = {k: s for k, s in self.data["sessions"].items() if s.get("exp", 0) > now}

    def _save(self):
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    # ------------------------------------------------------------ dueño
    @property
    def owner_set(self) -> bool:
        return bool(self.data.get("owner"))

    def set_owner_password(self, pw: str):
        """Cambiar la contraseña cierra las sesiones de dueño abiertas en otros equipos."""
        self.data["owner"] = hash_pw(pw) if pw else None
        self.data["sessions"] = {k: s for k, s in self.data["sessions"].items() if not s.get("owner")}
        self._save()

    # ----------------------------------------------------------- sesiones
    def login(self, password: str, vault_id: str = "", token: str = "") -> str | None:
        """Contraseña del dueño (sin biblioteca) o de una biblioteca. Devuelve el token de sesión."""
        if vault_id:
            v = self.vaults.get(vault_id)
            acc = (v.meta.get("access") or {}) if v else {}
            if not v or acc.get("mode") != "clave" or not check_pw(password, acc.get("pw")):
                return None
            grant = {"vault": vault_id, "pv": acc.get("pv", 0)}
        else:
            if not check_pw(password, self.data.get("owner")):
                return None
            grant = None
        s = self.data["sessions"].get(_sha(token)) if token else None
        if s is None:
            token = secrets.token_urlsafe(32)
            s = {"owner": False, "grants": [], "exp": 0}
            self.data["sessions"][_sha(token)] = s
        if grant:
            s["grants"] = [g for g in s["grants"] if g["vault"] != vault_id] + [grant]
        else:
            s["owner"] = True
        s["exp"] = time.time() + SESSION_DAYS * 86400
        self._save()
        return token

    def logout(self, token: str):
        if self.data["sessions"].pop(_sha(token or ""), None) is not None:
            self._save()

    # ---------------------------------------------------------- claves de API
    def create_key(self, name: str, scope: str, perm: str) -> tuple[dict, str]:
        token = "vt_" + secrets.token_urlsafe(30)
        k = {"id": secrets.token_hex(4), "name": name.strip()[:60] or "Clave", "hash": _sha(token),
             "hint": token[:7] + "…" + token[-4:], "scope": scope if scope == "all" or self.vaults.get(scope) else "all",
             "perm": perm if perm in ("lectura", "escritura") else "lectura", "created": time.time(), "used": 0}
        self.data["keys"].append(k)
        self._save()
        return k, token

    def revoke_key(self, kid: str):
        self.data["keys"] = [k for k in self.data["keys"] if k["id"] != kid]
        self._save()

    def keys_public(self) -> list[dict]:
        return [{k: v for k, v in key.items() if k != "hash"} for key in self.data["keys"]]

    # ------------------------------------------------------------- permisos
    def access(self, req) -> Access:
        local = is_local(req)
        bearer = req.headers.get("authorization", "")
        if bearer.lower().startswith("bearer "):
            h = _sha(bearer[7:].strip())
            key = next((k for k in self.data["keys"] if hmac.compare_digest(k["hash"], h)), None)
            if not key:
                return Access(local=local)
            if time.time() - key.get("used", 0) > 60:
                key["used"] = time.time()
                self._save()
            ids = [v.id for v in self.vaults.all()] if key["scope"] == "all" else [key["scope"]]
            perm = "escritura" if key["perm"] == "escritura" else "ver"
            return Access(perms={i: perm for i in ids if self.vaults.get(i)}, key=key, local=local)
        if local:
            return Access(owner=True, local=True)
        s = self.data["sessions"].get(_sha(req.cookies.get("vt_s", "")))
        if s and s.get("exp", 0) < time.time():
            s = None
        if s and s.get("owner") and self.owner_set:
            return Access(owner=True)
        perms = {}
        for v in self.vaults.all():
            acc = v.meta.get("access") or {}
            mode, perm = acc.get("mode", "privada"), acc.get("perm", "ver")
            if mode == "publica":
                perms[v.id] = perm
            elif mode == "clave" and s and any(g["vault"] == v.id and g.get("pv", 0) == acc.get("pv", 0)
                                                for g in s.get("grants", [])):
                perms[v.id] = perm
        return Access(perms=perms)

    def set_vault_access(self, vault_id: str, mode: str, perm: str, password: str = ""):
        v = self.vaults.get(vault_id)
        if v is None or mode not in MODES or perm not in PERMS:
            raise ValueError("acceso no válido")
        acc = dict(v.meta.get("access") or {})
        if mode == "clave":
            if password:
                acc["pw"] = hash_pw(password)
                acc["pv"] = acc.get("pv", 0) + 1  # contraseña nueva: quien entró con la vieja ya no entra
            elif not acc.get("pw"):
                raise ValueError("falta la contraseña de la biblioteca")
            elif acc.get("mode") != "clave":
                acc["pv"] = acc.get("pv", 0) + 1  # vuelve a pedir contraseña: las sesiones de antes no reviven
        acc.update(mode=mode, perm=perm)
        v.meta["access"] = acc
        v.save_meta()

    @staticmethod
    def vault_access_public(v) -> dict:
        acc = v.meta.get("access") or {}
        return {"mode": acc.get("mode", "privada"), "perm": acc.get("perm", "ver"), "has_pw": bool(acc.get("pw"))}
