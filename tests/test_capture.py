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
    assert o == {"quality": "media", "fps": 15, "crop": None, "sizes": []}
    cmd = capture.convert_cmd(Path("a"), Path("b"), "ligera", 15, (0, 0, 640, 360))
    vf = cmd[cmd.index("-vf") + 1]
    assert "crop=" in vf and "min(480" in vf and "fps=15" in vf
    assert cmd[cmd.index("-maxrate") + 1] == "600k"
    assert "-vn" in capture.convert_cmd(Path("a"), Path("b"), "audio", 30, None)


def test_source_that_changes_shape():
    """De un celular (vertical) a una pantalla: un lienzo que entra a los dos, sin deformar."""
    assert capture.parse_sizes("1080x2340,1920x1080,1920x1080,x,9x9") == [(1080, 2340), (1920, 1080)]
    assert capture.canvas([(1080, 2340), (1920, 1080)], 720) == (1280, 720)
    assert capture.canvas([(1920, 1080), (1916, 1080)], 720) is None  # una ventana que se acomodó
    assert capture.canvas([(1280, 720)], 720) is None
    cmd = capture.convert_cmd(Path("a"), Path("b"), "media", 30, None, [(1080, 2340), (1920, 1080)])
    vf = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf and "pad=1280:720" in vf


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


def _webm(root: Path, secs: int) -> bytes:
    src = root / f"src{secs}.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:d={secs}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={secs}", "-c:v", "libvpx", "-b:v", "300k", "-c:a", "libopus",
                    "-shortest", str(src)], check=True)
    return src.read_bytes()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sin ffmpeg")
def test_abandoned_capture_is_finished_by_the_server():
    """La página no vuelve (navegador cerrado, otra dirección): el servidor la arma solo con las opciones de
    las partes; si después la página vuelve con lo que faltaba, se suma y se rearma completa."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = _webm(root, 4)
        pieces = [data[i:i + 4096] for i in range(0, len(data), 4096)]
        half = len(pieces) // 2
        caps = make_caps(root)
        q = {"q": "ligera", "fps": "15", "title": "Mi grabación", "lib": "principal", "crop": "", "sizes": "320x240"}
        for i in range(half):
            assert run(caps.part(CID, i, chunks(pieces[i]), None, q))[0] == 200
        got = []

        def register_for(cid, lib, title, quality):
            assert (cid, lib, title, quality) == (CID, "principal", "Mi grabación", "ligera")
            return lambda *a: got.append(a)

        meta = root / "captures" / f"{CID}.json"
        at = json.loads(meta.read_text())["at"]
        assert run(caps.sweep([root], register_for, now=at + 5)) == []  # todavía puede llegar más
        assert run(caps.sweep([root], register_for, now=at + capture.IDLE_S + 1)) == [CID]
        out, _, dur = got[0]
        assert out.exists() and dur > 0
        st = json.loads(meta.read_text())
        assert st["done"] == out.name and st["auto"]
        assert (root / "captures" / f"{CID}.webm.part").exists()  # se guarda por si la página vuelve
        assert run(caps.sweep([root], register_for, now=at + capture.IDLE_S + 100)) == []  # no se rearma

        # la página vuelve con el resto y la termina: se rearma con todo
        for i in range(half, len(pieces)):
            assert run(caps.part(CID, i, chunks(pieces[i]), None, q))[0] == 200
        assert run(caps.finish(CID, len(pieces), parse_opts(q), None, lambda *a: got.append(a))) == (200, out.name)
        assert len(got) == 2 and 3.5 < got[1][2] < 4.5
        assert not (root / "captures" / f"{CID}.webm.part").exists()
        assert "auto" not in json.loads(meta.read_text())


def test_sweep_leaves_alone_what_is_still_arriving_or_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        caps = make_caps(root)
        run(caps.part(CID, 0, chunks(b"a"), None, {"q": "media"}))
        at = json.loads((root / "captures" / f"{CID}.json").read_text())["at"]
        assert run(caps.sweep([root], lambda *a: None, now=at + 10)) == []
        assert run(caps.sweep([root / "no-existe"], lambda *a: None, now=at + 1e6)) == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sin ffmpeg")
def test_page_confirms_what_the_server_already_built():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = _webm(root, 2)
        caps = make_caps(root)
        q = {"q": "audio"}
        run(caps.part(CID, 0, chunks(data), None, q))
        at = json.loads((root / "captures" / f"{CID}.json").read_text())["at"]
        got = []
        assert run(caps.sweep([root], lambda *a: (lambda *b: got.append(b)), now=at + capture.IDLE_S + 1)) == [CID]
        # la página vuelve sin nada nuevo: el video ya está y lo recibido sobra
        assert run(caps.finish(CID, 1, parse_opts(q), None, lambda *a: got.append(a))) == (200, f"{CID}.m4a")
        assert len(got) == 1
        assert not (root / "captures" / f"{CID}.webm.part").exists()
