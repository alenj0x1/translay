"""Servidor HTTP estático + WebSocket (RFC 6455) sobre asyncio, sin dependencias.

Alcance intencionalmente pequeño: GET/HEAD de archivos (con Range para que el
video permita saltar), rutas WebSocket con mensajes de texto/binarios, rutas HTTP
de una API (JSON) y un guardián que decide quién puede pedir cada ruta (vt/auth.py).
"""

import asyncio
import base64
import hashlib
import json
import struct
from pathlib import Path
from urllib.parse import unquote, urlsplit

import numpy as np

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_REASONS = {200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 429: "Too Many Requests"}
_MAX_MSG = 16 * 1024 * 1024
_MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".mov": "video/quicktime", ".mp3": "audio/mpeg", ".wav": "audio/wav",
}


class WebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.closed = False
        self._lock = asyncio.Lock()

    async def recv(self) -> str | bytes | None:
        """Siguiente mensaje completo, o None si la conexión se cerró."""
        op_msg, parts = 0, []
        try:
            while True:
                b0, b1 = await self.reader.readexactly(2)
                fin, op, masked, n = b0 & 0x80, b0 & 0x0F, b1 & 0x80, b1 & 0x7F
                if n == 126:
                    n = struct.unpack("!H", await self.reader.readexactly(2))[0]
                elif n == 127:
                    n = struct.unpack("!Q", await self.reader.readexactly(8))[0]
                if n > _MAX_MSG:
                    await self.close(1009)
                    return None
                mask = await self.reader.readexactly(4) if masked else None
                data = await self.reader.readexactly(n)
                if mask and n:
                    m = np.resize(np.frombuffer(mask, np.uint8), n)
                    data = (np.frombuffer(data, np.uint8) ^ m).tobytes()
                if op == 0x8:
                    await self.close()
                    return None
                if op == 0x9:
                    await self._frame(0xA, data)
                    continue
                if op == 0xA:
                    continue
                if op in (0x1, 0x2):
                    op_msg, parts = op, [data]
                else:
                    parts.append(data)
                if fin:
                    payload = b"".join(parts)
                    return payload.decode("utf-8") if op_msg == 0x1 else payload
        except (asyncio.IncompleteReadError, ConnectionError):
            self.closed = True
            return None

    async def send_json(self, obj):
        await self._frame(0x1, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    async def close(self, code: int = 1000):
        if not self.closed:
            try:
                await self._frame(0x8, struct.pack("!H", code))
            except ConnectionError:
                pass
            self.closed = True

    async def _frame(self, op: int, data: bytes):
        if self.closed:
            return
        n = len(data)
        if n < 126:
            hdr = struct.pack("!BB", 0x80 | op, n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x80 | op, 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x80 | op, 127, n)
        async with self._lock:
            try:
                self.writer.write(hdr + data)
                await self.writer.drain()
            except ConnectionError:
                self.closed = True


class Request:
    """Pedido HTTP para las rutas de la API y el guardián."""

    def __init__(self, method, path, query, headers, peer, body=b""):
        self.method, self.path, self.query, self.headers, self.peer, self.body = method, path, query, headers, peer, body

    def json(self):
        try:
            return json.loads(self.body or b"{}")
        except ValueError:
            return None

    @property
    def cookies(self) -> dict:
        out = {}
        for part in self.headers.get("cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k:
                out[k] = v
        return out


class AppServer:
    def __init__(self, routes: dict[str, Path], ws_routes: dict, put_routes: dict | None = None,
                 get_routes: dict | None = None, http_routes: dict | None = None, guard=None,
                 origin_ok=None):
        """routes: prefijo URL → carpeta. ws_routes: ruta → async fn(ws).
        get_routes: prefijo → async fn(resto_de_ruta) → archivo a servir (o None: 404).
        put_routes: prefijo → async fn(resto_de_ruta, query, headers, cuerpo) → (código, texto);
        `cuerpo` es un iterador asíncrono de bloques (el archivo no pasa entero por memoria).
        http_routes: prefijo → async fn(Request) → (código, cuerpo: dict|str|bytes, cabeceras) (cualquier método).
        guard: fn(Request) → None (pasa) o (código, texto): se consulta antes de archivos y subidas.
        origin_ok: fn(cabeceras) → bool: si el pedido viene de la propia app (vt/auth.py same_origin).
        Se exige al WebSocket y a todo lo que no sea GET/HEAD, salvo con clave de API."""
        self.routes = sorted(routes.items(), key=lambda kv: -len(kv[0]))
        self.ws_routes = ws_routes
        self.put_routes = put_routes or {}
        self.get_routes = get_routes or {}
        self.http_routes = http_routes or {}
        self.guard = guard
        self.origin_ok = origin_ok or (lambda h: True)

    async def serve(self, host: str, port: int):
        server = await asyncio.start_server(self._handle, host, port)
        async with server:
            await server.serve_forever()

    async def listen(self, host: str, port: int):
        """Otra dirección más (p. ej. la de la red local); devuelve el servidor para cerrarlo."""
        return await asyncio.start_server(self._handle, host, port)

    async def _handle(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            method, target, _ = line.decode("latin-1").split(" ", 2)
            headers = {}
            while True:
                h = await reader.readline()
                if h in (b"\r\n", b"\n", b""):
                    break
                k, _, v = h.decode("latin-1").partition(":")
                headers[k.strip().lower()] = v.strip()
            parts = urlsplit(target)
            path = unquote(parts.path)
            from urllib.parse import parse_qs
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            peer = (writer.get_extra_info("peername") or ("",))[0]
            req = Request(method, path, query, headers, peer)

            # otro sitio abierto en el navegador no puede usar la app (CSRF / WebSocket entre orígenes)
            writes = method not in ("GET", "HEAD") and not headers.get("authorization")
            is_ws = path in self.ws_routes and headers.get("upgrade", "").lower() == "websocket"
            if (is_ws or writes) and not self.origin_ok(headers):
                return await self._simple(writer, 403, "Origen no permitido")
            if is_ws:
                key = headers.get("sec-websocket-key", "").encode()
                accept = base64.b64encode(hashlib.sha1(key + _GUID).digest()).decode()
                writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                              f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
                await writer.drain()
                ws = WebSocket(reader, writer)
                ws.request = req  # quién se conecta (para los permisos)
                await self.ws_routes[path](ws)
                return
            api = next((p for p in self.http_routes if path.startswith(p)), None)
            if api:
                length = int(headers.get("content-length", "0") or 0)
                if length > 2 << 20:
                    return await self._simple(writer, 413, "Payload Too Large")
                req.body = await reader.readexactly(length) if length else b""
                code, body, extra = await self.http_routes[api](req)
                return await self._respond(writer, code, body, extra)
            if self.guard:
                denied = self.guard(req)
                if denied:
                    return await self._simple(writer, *denied)
            if method == "PUT":
                for prefix, fn in self.put_routes.items():
                    if path.startswith(prefix):
                        length = int(headers.get("content-length", "0"))

                        async def body(left=length):
                            while left > 0:
                                chunk = await reader.read(min(1 << 20, left))
                                if not chunk:
                                    raise ConnectionError("subida interrumpida")
                                left -= len(chunk)
                                yield chunk

                        code, text = await fn(path[len(prefix):], query, headers, body())
                        return await self._simple(writer, code, text)
                return await self._simple(writer, 404, "Not Found")
            if method not in ("GET", "HEAD"):
                return await self._simple(writer, 405, "Method Not Allowed")
            await self._static(writer, method, path, headers.get("range"), parts.query)
        except (ConnectionError, ValueError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def _resolve(self, path: str) -> Path | None:
        for prefix, root in self.routes:
            if path == prefix.rstrip("/") or path.startswith(prefix):
                rel = path[len(prefix):].lstrip("/") or "index.html"
                f = (root / rel).resolve()
                if f.is_relative_to(root.resolve()) and f.is_file():
                    return f
                return None
        return None

    async def _static(self, writer, method, path, rng, query=""):
        prefix = next((p for p in self.get_routes if path.startswith(p)), None)
        f = await self.get_routes[prefix](path[len(prefix):]) if prefix else self._resolve(path)
        if f is None:
            return await self._simple(writer, 404, "Not Found")
        size = f.stat().st_size
        start, end, status = 0, size - 1, "200 OK"
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start, end = int(a), int(b) if b else size - 1
            else:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            if start > end:
                return await self._simple(writer, 416, "Range Not Satisfiable")
            status = "206 Partial Content"
        length = end - start + 1
        head = [f"HTTP/1.1 {status}", f"Content-Type: {_MIME.get(f.suffix.lower(), 'application/octet-stream')}",
                f"Content-Length: {length}", "Accept-Ranges: bytes",
                # miniaturas: en caché (al redibujar listas no se vuelven a pedir); lo demás cambia
                "Cache-Control: max-age=3600" if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                else "Cache-Control: no-store",
                "Connection: close"]
        if status.startswith("206"):
            head.append(f"Content-Range: bytes {start}-{end}/{size}")
        # ?dl=<nombre>: se descarga con ese nombre en vez de abrirse
        from urllib.parse import parse_qs, quote

        dl = parse_qs(query).get("dl", [""])[0]
        if dl:
            ascii_name = dl.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
            head.append(f'Content-Disposition: attachment; filename="{ascii_name}"; '
                        f"filename*=UTF-8''{quote(dl)}")
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode())
        if method == "GET":
            with f.open("rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    chunk = fh.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
                    left -= len(chunk)
        await writer.drain()

    async def _respond(self, writer, code, body, extra=None):
        ctype = "text/plain; charset=utf-8"
        if isinstance(body, (dict, list)):
            body, ctype = json.dumps(body, ensure_ascii=False).encode(), "application/json; charset=utf-8"
        elif isinstance(body, str):
            body = body.encode()
        extra = dict(extra or {})
        ctype = extra.pop("Content-Type", ctype)
        head = [f"HTTP/1.1 {code} {_REASONS.get(code, 'OK')}", f"Content-Type: {ctype}",
                f"Content-Length: {len(body)}", "Cache-Control: no-store", "Connection: close"]
        for k, v in (extra or {}).items():
            for one in (v if isinstance(v, list) else [v]):
                head.append(f"{k}: {one}")
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
        await writer.drain()

    async def _simple(self, writer, code, msg):
        body = msg.encode()
        writer.write(f"HTTP/1.1 {code} {_REASONS.get(code, 'OK')}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                     f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()
