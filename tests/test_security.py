"""Arreglos de la revisión de seguridad: lo que un pedido malicioso o un corte no debe lograr.

    python -m pytest tests/test_security.py
"""

import asyncio
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt.auth import Auth, hash_pw  # noqa: E402
from vt.httpws import WebSocket  # noqa: E402
from vt.jsonio import read_json, write_json  # noqa: E402
from vt.store import Store  # noqa: E402
from vt.trash import _rel_files  # noqa: E402
from vt.vaults import Vaults  # noqa: E402


def test_json_keeps_a_backup_and_survives_a_broken_file():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "library.json"
        write_json(f, {"v": 1})
        write_json(f, {"v": 2})
        assert read_json(f) == {"v": 2}
        f.write_text("{roto", encoding="utf-8")  # un corte a mitad de algo que no pasó por write_json
        assert read_json(f) == {"v": 1}  # la copia anterior
        assert not list(Path(d).glob("*.tmp"))


def test_login_always_issues_a_new_token():
    """Un token plantado antes de entrar (fijación de sesión) no queda con permisos."""
    with tempfile.TemporaryDirectory() as d:
        vs = Vaults(Path(d) / "data")
        auth = Auth(Path(d) / "auth.json", vs)
        auth.data["owner"] = hash_pw("clave-larga")
        planted = "token-plantado"
        assert auth.login("mala", "", planted) is None
        tok = auth.login("clave-larga", "", planted)
        assert tok and tok != planted
        from vt.auth import _sha
        assert _sha(planted) not in auth.data["sessions"]


def test_odd_ids_never_reach_outside_the_library():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "library").mkdir()
        assert _rel_files(root, "../../etc") == []
        try:
            Store(root / "tr").open("../x")
            raise AssertionError("debió rechazarlo")
        except ValueError:
            pass


def _ws(frames: bytes) -> WebSocket:
    reader = asyncio.StreamReader()
    reader.feed_data(frames)
    reader.feed_eof()

    class W:
        def write(self, b): pass
        async def drain(self): pass
        def close(self): pass
        def is_closing(self): return True

    return WebSocket(reader, W())


def _frame(op, payload, fin=True, masked=True):
    head = bytes([(0x80 if fin else 0) | op])
    n = len(payload)
    head += bytes([(0x80 if masked else 0) | n]) if n < 126 else bytes([(0x80 if masked else 0) | 126]) + struct.pack("!H", n)
    if not masked:
        return head + payload
    mask = b"\x01\x02\x03\x04"
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def test_websocket_rejects_bad_frames():
    async def recv(data):
        return await _ws(data).recv()

    run = lambda data: asyncio.run(recv(data))  # noqa: E731
    assert run(_frame(0x1, b"hola")) == "hola"
    assert run(_frame(0x1, b"ho", fin=False) + _frame(0x0, b"la")) == "hola"
    assert run(_frame(0x1, b"hola", masked=False)) is None  # sin máscara
    assert run(_frame(0x0, b"suelta")) is None  # continuación sin mensaje
    assert run(_frame(0x9, b"x" * 200)) is None  # control demasiado largo
    assert run(_frame(0x3, b"?")) is None  # código desconocido
