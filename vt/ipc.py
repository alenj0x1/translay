"""Mensajes binarios por tuberías (stdin/stdout) entre procesos.

Trama: [u32 largo JSON][JSON utf-8][u32 largo binario][binario]. Lo usan el
servidor (py 3.14) y el proceso de voz (entorno propio con torch), así cada
motor TTS vive aislado con sus dependencias.
"""

import json
import struct


def write_msg(stream, header: dict, payload: bytes = b""):
    h = json.dumps(header, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(h)) + h + struct.pack("<I", len(payload)) + payload)
    stream.flush()


def _read_exact(stream, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def read_msg(stream) -> tuple[dict, bytes]:
    n = struct.unpack("<I", _read_exact(stream, 4))[0]
    header = json.loads(_read_exact(stream, n).decode("utf-8"))
    m = struct.unpack("<I", _read_exact(stream, 4))[0]
    return header, _read_exact(stream, m) if m else b""
