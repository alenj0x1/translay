"""Grabación de pantalla por partes (vt/capture.py): orden, reintentos, cortes y armado final."""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import capture  # noqa: E402
from vt.capture import Captures, parse_crop, parse_opts  # noqa: E402

CID = "cap_abcdef123456"


async def chunks(data: bytes):
    yield data


def run(coro):
    return asyncio.run(coro)


def make_caps(root: Path) -> Captures:
    return Captures(lambda vid, lib: root)


def test_parts_in_order_retries_and_gaps():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        caps = make_caps(root)
        assert run(caps.part(CID, 0, chunks(b"aaa"), None)) == (200, "next=1")
        assert run(caps.part(CID, 0, chunks(b"aaa"), None)) == (200, "next=1")  # reintento: no se duplica
        assert run(caps.part(CID, 2, chunks(b"ccc"), None)) == (409, "next=1")  # falta la 1
        assert run(caps.part(CID, 1, chunks(b"bbb"), None)) == (200, "next=2")
        assert (root / "captures" / f"{CID}.webm.part").read_bytes() == b"aaabbb"


def test_resume_discards_unconfirmed_bytes():
    # el servidor se cayó después de escribir y antes de anotar: lo de más se descarta
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        caps = make_caps(root)
        run(caps.part(CID, 0, chunks(b"aaa"), None))
        part = root / "captures" / f"{CID}.webm.part"
        part.write_bytes(b"aaaXXXX")
        assert run(caps.part(CID, 1, chunks(b"bbb"), None)) == (200, "next=2")
        assert part.read_bytes() == b"aaabbb"
        # otra instancia (servidor reiniciado) sigue desde lo anotado
        assert run(make_caps(root).part(CID, 2, chunks(b"c"), None)) == (200, "next=3")


def test_parse_options():
    assert parse_crop("11,21,641,361") == (10, 20, 640, 360)
    assert parse_crop("0,0,8,8") is None and parse_crop("x") is None
    o = parse_opts({"q": "nada", "fps": "15", "crop": ""})
    assert o == {"quality": "media", "fps": 15, "crop": None}
    cmd = capture.convert_cmd(Path("a"), Path("b"), "ligera", 15, (0, 0, 640, 360))
    vf = cmd[cmd.index("-vf") + 1]
    assert "crop=" in vf and "min(480" in vf and "fps=15" in vf
    assert cmd[cmd.index("-maxrate") + 1] == "600k"
    assert "-vn" in capture.convert_cmd(Path("a"), Path("b"), "audio", 30, None)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sin ffmpeg")
@pytest.mark.parametrize("quality,crop,ext", [("media", None, "mp4"), ("ligera", "100,50,320,240", "mp4"),
                                              ("audio", None, "m4a")])
def test_finish_builds_file_once(quality, crop, ext):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src.webm"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x480:rate=30:d=3",
                        "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:v", "libvpx", "-b:v", "500k", "-c:a", "libopus",
                        "-shortest", str(src)], check=True)
        data = src.read_bytes()
        caps = make_caps(root)
        size = 4096  # partes arbitrarias, como las de MediaRecorder
        pieces = [data[i:i + size] for i in range(0, len(data), size)]
        for i, b in enumerate(pieces):
            assert run(caps.part(CID, i, chunks(b), None))[0] == 200
        got = []
        opts = parse_opts({"q": quality, "crop": crop or ""})

        async def both():
            # dos «Terminar» a la vez (reintento tras un corte): una sola conversión
            return await asyncio.gather(caps.finish(CID, len(pieces), opts, None, lambda *a: got.append(a)),
                                        caps.finish(CID, len(pieces), opts, None, lambda *a: got.append(a)))

        r1, r2 = run(both())
        assert r1 == r2 == (200, f"{CID}.{ext}")
        assert len(got) == 1
        out, thumb, dur = got[0]
        assert out.exists() and 2.5 < dur < 3.5
        assert (thumb is None) == (quality == "audio")
        assert not (root / "captures" / f"{CID}.webm.part").exists()
        assert json.loads((root / "captures" / f"{CID}.json").read_text())["done"] == out.name
        # ya armado: responde al instante, aunque se repita
        assert run(caps.finish(CID, len(pieces), opts, None, lambda *a: got.append(a))) == (200, out.name)
        assert len(got) == 1
        if crop:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True)
            assert r.stdout.strip() == "320,240"


def test_finish_waits_for_missing_parts():
    with tempfile.TemporaryDirectory() as tmp:
        caps = make_caps(Path(tmp))
        run(caps.part(CID, 0, chunks(b"a"), None))
        assert run(caps.finish(CID, 3, parse_opts({}), None, lambda *a: None)) == (409, "next=1")
