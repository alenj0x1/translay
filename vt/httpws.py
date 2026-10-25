"""Servidor HTTP estático + WebSocket (RFC 6455) sobre asyncio, sin dependencias.

Alcance intencionalmente pequeño: GET/HEAD de archivos (con Range para que el
video permita saltar), y rutas WebSocket con mensajes de texto/binarios.
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


class AppServer:
    def __init__(self, routes: dict[str, Path], ws_routes: dict):
        """routes: prefijo URL → carpeta. ws_routes: ruta → async fn(ws)."""
        self.routes = sorted(routes.items(), key=lambda kv: -len(kv[0]))
        self.ws_routes = ws_routes

    async def serve(self, host: str, port: int):
        server = await asyncio.start_server(self._handle, host, port)
        async with server:
            await server.serve_forever()

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
            path = unquote(urlsplit(target).path)

            if path in self.ws_routes and headers.get("upgrade", "").lower() == "websocket":
                key = headers.get("sec-websocket-key", "").encode()
                accept = base64.b64encode(hashlib.sha1(key + _GUID).digest()).decode()
                writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                              f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
                await writer.drain()
                await self.ws_routes[path](WebSocket(reader, writer))
                return
            if method not in ("GET", "HEAD"):
                return await self._simple(writer, 405, "Method Not Allowed")
            await self._static(writer, method, path, headers.get("range"))
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

    async def _static(self, writer, method, path, rng):
        f = self._resolve(path)
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
                f"Content-Length: {length}", "Accept-Ranges: bytes", "Cache-Control: no-store",
                "Connection: close"]
        if status.startswith("206"):
            head.append(f"Content-Range: bytes {start}-{end}/{size}")
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

    async def _simple(self, writer, code, msg):
        body = msg.encode()
        writer.write(f"HTTP/1.1 {code} {msg}\r\nContent-Length: {len(body)}\r\n"
                     f"Connection: close\r\n\r\n".encode() + body)
        await writer.drain()
