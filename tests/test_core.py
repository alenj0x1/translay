"""Pruebas sin GPU del núcleo: streaming (con un ASR falso) y almacenamiento.

    python -m pytest tests   ó   python tests/test_core.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt.asr import Word  # noqa: E402
from vt.store import Store, merge_ranges  # noqa: E402
from vt.streaming import Segment, StreamingTranscriber  # noqa: E402
from vt.textproc import match_shape, polish, preedit, split_sentences  # noqa: E402

SR = 16000
SCRIPT = [(0.2, 0.6, " Hello"), (0.7, 1.1, " world."), (1.5, 1.9, " This"),
          (2.0, 2.3, " is"), (2.4, 2.9, " a"), (3.0, 3.5, " test.")]


class FakeASR:
    """Devuelve las palabras del guion cuyo audio ya está en el búfer."""

    def __init__(self, st_ref):
        self.st_ref = st_ref

    def transcribe(self, audio, prompt=None, language=None):
        t0 = self.st_ref[0].t0
        end = t0 + len(audio) / SR
        return [Word(a - t0, b - t0, w, 0.99) for a, b, w in SCRIPT if b <= end and a >= t0 - 0.01]


def tone(seconds):
    t = np.arange(int(seconds * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_streaming_commits_sentences():
    ref = []
    st = StreamingTranscriber(FakeASR(ref))
    ref.append(st)
    audio = np.concatenate([tone(3.6), np.zeros(SR, np.float32)])
    segs = []
    for i in range(0, len(audio), 1600):
        st.feed(i / SR, audio[i:i + 1600])
        if st.ready():
            segs += [e for e in st.step() if isinstance(e, Segment)]
    segs += [e for e in st.flush() if isinstance(e, Segment)]
    assert [s.text for s in segs] == ["Hello world.", "This is a test."]
    assert st.final_t >= 3.5


def test_store_overlap_and_ranges():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d))
        tr = store.open("abcdef0123456789", "demo.mp4")
        tr.add_segment(0.0, 2.0, "Then, a neural network converges.", None)
        seg, removed = tr.add_segment(0.1, 3.0, "Then, a neural network converts the sound.", None)
        assert removed == [1] and len(tr.segments) == 1
        tr.add_covered(0, 10)
        tr.add_covered(10.1, 20)
        assert tr.covered == [[0, 20]]
        tr.save()
        assert Store(Path(d)).open("abcdef0123456789").segments[0]["id"] == seg["id"]
    assert merge_ranges([[5, 6], [0, 1], [0.9, 2]]) == [[0, 2], [5, 6]]


def test_textproc():
    assert split_sentences("Mr. Smith went to the U.S. Army. He left.") == [
        "Mr. Smith went to the U.S. Army.", "He left."]
    assert split_sentences("Are you ready? Because yes.") == ["Are you ready?", "Because yes."]
    assert split_sentences("I paid $5. It was 3.5 percent.") == ["I paid $5.", "It was 3.5 percent."]
    assert preedit("Let's call it a day.") == "Let's stop for today."
    assert preedit("Would you go back?") == "Would you return?"
    assert preedit("that's pretty much it, let us know") == "that's all, tell us"
    assert match_shape("the text will be", "El texto será.") == "el texto será"
    assert match_shape("Finally, in a version,", "Finalmente, en una versión.") == "Finalmente, en una versión,"
    assert match_shape("which is fine", "que está bien") == "lo que está bien"
    assert polish("Cuesta $ 799 , mira el vídeo") == "Cuesta $799, mira el video"
    assert polish("Hoy quiero hablaros de esto y os voy a mostrar") == "Hoy quiero hablarles de esto y les voy a mostrar"
    assert preedit("Opus has been out for a bit") == "Opus has been available for a bit"


def test_audiofx():
    from vt.audiofx import median_f0, resample, time_stretch

    sr = 16000
    t = np.arange(sr * 2) / sr
    x = (0.4 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    y = time_stretch(x, sr, 1.3)
    assert abs(len(y) - len(x) / 1.3) < sr * 0.02
    assert abs(median_f0(y, sr) - 150) < 3          # el tono no cambia
    z = resample(x, sr, 24000)
    assert len(z) == 48000 and abs(median_f0(resample(z, 24000, sr), sr) - 150) < 3


def test_speaker_tracker():
    from vt.speakers import SpeakerTracker

    rng = np.random.default_rng(0)
    a, b = rng.standard_normal(256), rng.standard_normal(256)
    unit = lambda v: v / np.linalg.norm(v)  # noqa: E731
    tr = SpeakerTracker()
    ids = [tr.assign(unit(v + 0.3 * rng.standard_normal(256)), 3.0)[0] for v in (a, b, a, b, a)]
    assert ids == [0, 1, 0, 1, 0]
    # una frase corta parecida a alguien no crea persona nueva
    assert tr.assign(unit(a + 0.8 * rng.standard_normal(256)), 0.9)[0] == 0
    tr.assign(unit(b), np.float64(2.5))  # duraciones numpy (vienen de los tiempos de Whisper)
    import json
    json.dumps(tr.state())  # el estado se guarda en el JSON de la transcripción
    # una referencia nunca se recorta (el texto dejaría de coincidir con el audio)
    tone = lambda sec: (0.3 * np.sin(2 * np.pi * 180 * np.arange(int(16000 * sec)) / 16000)).astype(np.float32)  # noqa: E731
    assert not tr.add_reference(0, tone(15), "demasiado larga")          # más de 12 s: nunca
    assert tr.add_reference(0, tone(10), "larga, a falta de otra")       # último recurso, entera
    assert len(tr.refs[0][0][1]) == 10 * 16000 and tr.refs[0][0][2] == "larga, a falta de otra"
    assert not tr.add_reference(0, tone(11), "otra larga")               # ya tiene una
    assert tr.add_reference(0, tone(5), "frase completa.")               # una normal la reemplaza
    assert [r[2] for r in tr.refs[0]] == ["frase completa."]
    restored = SpeakerTracker(state=tr.state())
    assert restored.assign(unit(b + 0.3 * rng.standard_normal(256)), 3.0)[0] == 1


def test_cookies_import():
    from vt import cookies

    rows = [  # cookies inventadas: solo para la prueba
        (".youtube.com", "LOGIN_INFO", "falso123"),
        (".youtube.com", "PREF", "f6=40000000"),
        (".google.com", "SID", "falso456"),
        (".banco-ejemplo.com", "SESSION", "no-se-guarda"),
    ]
    lines = ["# Netscape HTTP Cookie File"]
    lines += ["\t".join([dom, "TRUE", "/", "TRUE", "2000000000", name, val]) for dom, name, val in rows]
    fake = "\n".join(lines).encode()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "cookies.txt"
        info = cookies.import_file(fake, out)
        assert info["count"] == 3 and info["logged_in"]
        assert "banco-ejemplo" not in out.read_text(encoding="utf-8")  # solo YouTube/Google
        assert cookies.status(out)["present"]
        try:
            cookies.import_file(b"esto no es un cookies.txt", out)
            raise AssertionError("debió rechazarse")
        except ValueError:
            pass


def test_playlist_library_and_srt():
    from vt.exporter import safe_name, srt
    from vt.library import Library
    from vt.youtube import playlist_id

    assert playlist_id("https://www.youtube.com/watch?v=ejjBbaq9RmY&list=PLKfy8g4yBtRY") == "PLKfy8g4yBtRY"
    assert playlist_id("https://www.youtube.com/watch?v=ejjBbaq9RmY&list=RDejjBbaq9RmY") is None  # mix
    with tempfile.TemporaryDirectory() as d:
        lib = Library(Path(d) / "library.json")
        info = {"id": "PLprueba123", "title": "Mi lista", "url": "u", "channel": "c",
                "entries": [{"id": f"vid{i:08d}", "title": f"T{i}", "duration": 60, "channel": "c", "thumb": ""}
                            for i in range(3)]}
        c = lib.import_playlist(info)
        assert c["items"] == ["yt_vid00000000", "yt_vid00000001", "yt_vid00000002"]
        pub = lib.public()
        by = {x["id"]: x for x in pub["collections"]}
        assert by["recent"]["items"] == [] and len(by["all"]["items"]) == 3  # sin descargar: solo en Todos
        assert lib.import_playlist(info)["id"] == c["id"]  # reimportar no duplica
        lib.set_field("yt_vid00000000", media="/media/yt/x.mp4")
        assert sorted(lib.delete(c["id"])) == ["yt_vid00000001", "yt_vid00000002"]  # lo descargado se queda
    segs = [{"start": 1.0, "end": 2.5, "text": "Hi.", "translation": "Hola."}, {"start": 3, "end": 3.1, "text": "x"}]
    out = srt(segs, "translation")
    assert out.startswith("1\n00:00:01,000 --> 00:00:02,500\nHola.") and "x" not in out
    assert safe_name('a/b:c?"d') == "a b c d"


def test_download_only_queue():
    """«Solo descargar»: se descarga pero no se procesa hasta pedirlo."""
    from vt.library import Library
    from vt.processor import Processor

    loop, Processor._loop = Processor._loop, lambda self: None  # sin hilo de procesamiento en la prueba
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            lib = Library(root / "library.json")
            lib.add_pending([{"id": "abcdefghij1"}])
            p = Processor(root, Store(root / "tr"), lib, None, None, None, None, None, None, lambda m: None)
            p.add_many(["yt_abcdefghij1"], download_only=True)
            job = p._job("yt_abcdefghij1")
            assert job["download_only"] and p._next() is None
            lib.set_field("yt_abcdefghij1", media="/media/yt/x.mp4")
            job["state"] = "descargado"
            assert p._next() is None                      # descargado: no se procesa solo
            p.add_many(["yt_abcdefghij1"], download_only=True)
            assert p._job("yt_abcdefghij1")["state"] == "descargado"  # reimportar no lo cambia
            p.add("yt_abcdefghij1")                       # «Procesar»
            job = p._job("yt_abcdefghij1")
            assert job["state"] == "en cola" and "download_only" not in job and p._next() is job
            job["state"] = "descargado"
            p.clear_done()
            assert p._job("yt_abcdefghij1") is None       # «Limpiar terminados» también lo quita
            # «Bajar video»: lo que solo tiene audio entra a descargarse sin volver a procesarse
            lib.set_field("yt_abcdefghij1", media="/media/yt/x.m4a", audio_only=True)
            assert p.fetch_videos(["yt_abcdefghij1"]) == 1
            job = p._job("yt_abcdefghij1")
            assert job["fetch_video"] and job["state"] in ("listo", "descargado") and p._next() is None
            assert p._next_download() is job
            p.clear_done()
            assert p._job("yt_abcdefghij1") is job        # pendiente: «Limpiar terminados» no lo quita
    finally:
        Processor._loop = loop


def test_vaults():
    """Bibliotecas: cada una en su carpeta; un video vive en una sola y se puede mover con sus archivos."""
    from vt.vaults import Vaults

    with tempfile.TemporaryDirectory() as d:
        data = Path(d) / "data"
        vs = Vaults(data)
        vs.main.library.add_pending([{"id": "abcdefghij1"}])
        (data / "youtube").mkdir(exist_ok=True)
        (data / "youtube" / "abcdefghij1.m4a").write_bytes(b"x")
        vs.main.library.set_field("yt_abcdefghij1", media="/media/yt/abcdefghij1.m4a")
        tr = vs.store.open("yt_abcdefghij1")
        tr.save()
        sci = vs.create("Ciencia", str(Path(d) / "otro disco" / "ciencia"), prefs={"theme_style": "pastel"})
        assert vs.get("ciencia") is sci and sci.prefix == "/v/ciencia"
        assert vs.of("yt_abcdefghij1") is vs.main
        moved, skipped = vs.move(["yt_abcdefghij1"], "ciencia")
        assert (moved, skipped) == (1, 0) and vs.of("yt_abcdefghij1") is sci
        assert (sci.root / "youtube" / "abcdefghij1.m4a").exists() and not (data / "youtube" / "abcdefghij1.m4a").exists()
        assert (sci.root / "transcripts" / "yt_abcdefghij1.json").exists()
        assert sci.public_library()["videos"]["yt_abcdefghij1"]["media"] == "/v/ciencia/media/yt/abcdefghij1.m4a"
        assert sci.file("/media/yt/../../x") is None                       # sin salirse de la carpeta
        assert vs.library.data["videos"]["yt_abcdefghij1"]["id"] == "yt_abcdefghij1"  # la cola los ve a todos
        again = Vaults(data)                                               # al reiniciar sigue ahí
        assert again.get("ciencia").name == "Ciencia" and again.get("ciencia").meta["prefs"]["theme_style"] == "pastel"
        (sci.root / "mio.txt").write_text("no es de la biblioteca")
        vids = vs.remove("ciencia", delete_files=True)
        assert vids == ["yt_abcdefghij1"] and (sci.root / "mio.txt").exists()  # solo se borra lo suyo
        assert not (sci.root / "youtube").exists() and vs.get("ciencia") is None


def test_access_and_webhooks():
    """Acceso: dueño local, invitados por biblioteca, claves de API; webhooks firmados."""
    import hashlib
    import hmac
    import http.server
    import threading
    import time as _t

    from vt import events
    from vt.auth import Auth
    from vt.httpws import Request
    from vt.vaults import Vaults
    from vt.webhooks import Webhooks

    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        vs = Vaults(data)
        sci = vs.create("Ciencia")
        assert vs.create("Océanos").id == "oceanos"                         # el enlace /b/<id> sin tildes rotas
        auth = Auth(data / "auth.json", vs)
        req = lambda peer="127.0.0.1", **h: Request("GET", "/", {}, {"host": "127.0.0.1:8765", **{k.replace("_", "-"): v for k, v in h.items()}}, peer)
        assert auth.access(req()).owner                                    # este equipo: dueño
        assert not auth.access(req(x_forwarded_for="1.2.3.4")).any         # por un túnel: remoto
        assert not auth.access(req("192.168.1.5")).any                     # todo es privado
        auth.set_vault_access("ciencia", "publica", "ver")
        a = auth.access(req("192.168.1.5"))
        assert a.can_view("ciencia") and not a.can_import("ciencia") and not a.can_view("principal")
        auth.set_vault_access("ciencia", "clave", "importar", "secreta1")
        assert not auth.access(req("192.168.1.5")).any
        assert auth.login("mala", "ciencia") is None
        tok = auth.login("secreta1", "ciencia")
        a = auth.access(req("192.168.1.5", cookie=f"vt_s={tok}"))
        assert a.can_import("ciencia") and not a.owner
        auth.set_vault_access("ciencia", "clave", "importar", "otra1234")  # contraseña nueva: la sesión vieja no entra
        assert not auth.access(req("192.168.1.5", cookie=f"vt_s={tok}")).any
        auth.set_vault_access("ciencia", "clave", "importar", "otra1234")
        tok2 = auth.login("otra1234", "ciencia")
        auth.set_vault_access("ciencia", "publica", "ver")
        auth.set_vault_access("ciencia", "clave", "importar")              # vuelve a pedir la misma contraseña
        assert not auth.access(req("192.168.1.5", cookie=f"vt_s={tok2}")).any  # la sesión de antes no revive
        auth.set_owner_password("dueño123")
        tok = auth.login("dueño123")
        assert auth.access(req("192.168.1.5", cookie=f"vt_s={tok}")).owner
        key, token = auth.create_key("script", "ciencia", "lectura")
        a = auth.access(req("192.168.1.5", authorization=f"Bearer {token}"))
        assert a.perm("ciencia") == "ver" and not a.can_view("principal") and "hash" not in auth.keys_public()[0]
        assert not auth.access(req("192.168.1.5", authorization="Bearer vt_falsa")).any

        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                got.append((self.headers["X-VT-Event"], self.headers["X-VT-Signature"], body))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        hooks = Webhooks(data / "webhooks.json")
        h = hooks.upsert({"url": f"http://127.0.0.1:{srv.server_port}/x", "events": ["video.procesado"], "vault": "ciencia"})
        events.emit("video.procesado", "principal", video="a")             # otra biblioteca: no
        events.emit("video.descargado", "ciencia", video="b")              # otro evento: no
        events.emit("video.procesado", "ciencia", video="c")
        events.emit("biblioteca.creada", "ciencia", name="Ciencia")         # «name» en los datos no choca
        for _ in range(50):
            if got:
                break
            _t.sleep(0.05)
        srv.shutdown()
        assert len(got) == 1 and got[0][0] == "video.procesado"
        sig = "sha256=" + hmac.new(h["secret"].encode(), got[0][2], hashlib.sha256).hexdigest()
        assert got[0][1] == sig and b'"video": "c"' in got[0][2]
        events._sinks.remove(hooks.on_event)


def test_same_origin():
    """Otro sitio abierto en el navegador no puede usar la app (CSRF / WebSocket entre orígenes)."""
    import asyncio

    from vt.auth import same_origin
    from vt.httpws import AppServer

    h = {"host": "127.0.0.1:8765"}
    assert same_origin(h)                                                  # sin Origin: curl, scripts
    assert same_origin({**h, "origin": "http://127.0.0.1:8765"})
    assert not same_origin({**h, "origin": "https://malo.example"})
    assert not same_origin({**h, "origin": "null"})
    assert same_origin({**h, "origin": "https://t.example.com", "x-forwarded-host": "t.example.com"})
    assert same_origin({**h, "origin": "https://t.example.com/"}, ("https://t.example.com",))

    async def run():
        hits = []

        async def api(req):
            hits.append(req.method)
            return 200, {"ok": True}, {}

        async def ws(sock):
            hits.append("ws")

        srv = AppServer({}, {"/ws": ws}, http_routes={"/api/v1": api}, origin_ok=same_origin)
        server = await asyncio.start_server(srv._handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def ask(lines):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(("\r\n".join(lines + [f"Host: 127.0.0.1:{port}", "Content-Length: 0", "", ""])).encode())
            await w.drain()
            status = (await r.readline()).decode()
            w.close()
            return int(status.split()[1])

        evil = "Origin: https://malo.example"
        assert await ask(["POST /api/v1/queue HTTP/1.1", evil]) == 403
        assert await ask(["GET /ws HTTP/1.1", "Upgrade: websocket", "Connection: Upgrade",
                          "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==", evil]) == 403
        assert await ask(["GET /api/v1 HTTP/1.1", evil]) == 200                # leer no cambia nada
        assert await ask(["POST /api/v1/queue HTTP/1.1", evil, "Authorization: Bearer vt_x"]) == 200
        assert await ask(["POST /api/v1/queue HTTP/1.1", f"Origin: http://127.0.0.1:{port}"]) == 200
        assert await ask(["POST /api/v1/queue HTTP/1.1"]) == 200
        assert hits == ["GET", "POST", "POST", "POST"]
        server.close()

    asyncio.run(run())


if __name__ == "__main__":
    test_same_origin()
    test_access_and_webhooks()
    test_vaults()
    test_download_only_queue()
    test_playlist_library_and_srt()
    test_cookies_import()
    test_audiofx()
    test_speaker_tracker()
    test_streaming_commits_sentences()
    test_store_overlap_and_ranges()
    test_textproc()
    print("ok")


def test_renamed_video_keeps_its_name(tmp_path):
    from vt.library import Library

    lib = Library(tmp_path / "library.json")
    lib.register("lk_0123456789abcdef", source="link", title="21_10")
    assert lib.rename_video("lk_0123456789abcdef", "  Clase   de estadística ")
    # lo que llega después (descarga, abrirlo en el navegador) no pisa el nombre
    lib.set_field("lk_0123456789abcdef", title="21_10", duration=60)
    lib.set_fields({"lk_0123456789abcdef": {"title": "21_10"}})
    lib.register("lk_0123456789abcdef", title="21_10")
    v = Library(tmp_path / "library.json").data["videos"]["lk_0123456789abcdef"]
    assert v["title"] == "Clase de estadística" and v["duration"] == 60
    assert not lib.rename_video("lk_0123456789abcdef", "   ") and not lib.rename_video("no_existe_123", "x")
