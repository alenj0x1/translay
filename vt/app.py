"""Punto de entrada del servidor: carga el modelo y sirve la vista."""

import argparse
import asyncio
import re
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .asr import WhisperASR
from .httpws import AppServer
from .session import Session
from .store import Store
from .translate import MODELS as MT_MODELS, load_translator
from .library import Library
from .prefs import Prefs
from .processor import Processor
from .exporter import Exporter
from .resources import Resources
from .youtube import YouTube

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="Traductor de video EN→ES en tiempo real")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--model", default="large-v3-turbo")
    p.add_argument("--device", default="cuda")
    p.add_argument("--compute-type", default="float16")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--translator", default="opus-big",
                   help="none | " + " | ".join(MT_MODELS) + " | repo de HF (Marian CT2)")
    p.add_argument("--voice", default="omnivoice", help="none | omnivoice | chatterbox")
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()

    print(f"Preparando {a.model} en {a.device} ({a.compute_type})…", flush=True)
    asr = WhisperASR(a.model, a.device, a.compute_type, a.beam)
    asr.warmup()
    print(f"Preparando traductor {a.translator}…", flush=True)
    translator = load_translator(a.translator, a.device)
    translator.translate("Warm up.")
    gpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")  # un solo hilo usa la GPU
    store = Store(ROOT / "data" / "transcripts")
    youtube = YouTube(ROOT / "data" / "youtube")
    library = Library(ROOT / "data" / "library.json")
    library.import_youtube(ROOT / "data" / "youtube")

    def backfill_youtube():
        """Miniatura, canal y categorías de videos descargados antes de la biblioteca."""
        for vid, v in list(library.data["videos"].items()):
            if v.get("source") == "youtube" and (not v.get("thumb") or "categories" not in v):
                try:
                    info = youtube.fetch(vid[3:])
                    library.set_field(vid, **{k: info[k] for k in ("thumb", "channel", "categories", "title")
                                              if info.get(k) is not None})
                except Exception as e:
                    print(f"[biblioteca] {vid}: {e}", flush=True)

    threading.Thread(target=backfill_youtube, daemon=True).start()
    lib_dir = ROOT / "data" / "library"
    lib_dir.mkdir(parents=True, exist_ok=True)

    async def put_media(rest, query, headers, body):
        """Copia de un archivo local, para volver a verlo desde la biblioteca."""
        vid = rest.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", vid):
            return 400, "id invalido"
        ext = re.sub(r"[^a-z0-9]", "", Path(query.get("name", "video.mp4")).suffix.lower())[:5] or "mp4"
        out = lib_dir / f"{vid}.{ext}"
        tmp = out.with_suffix(".part")
        with tmp.open("wb") as f:
            async for chunk in body:
                f.write(chunk)
        tmp.replace(out)
        library.set_field(vid, media=f"/media/lib/{out.name}")
        return 200, "OK"

    async def put_thumb(rest, query, headers, body):
        vid = rest.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", vid):
            return 400, "id invalido"
        out = lib_dir / f"{vid}.jpg"
        data = b"".join([c async for c in body])
        out.write_bytes(data[: 2 << 20])
        library.set_field(vid, thumb=f"/media/lib/{out.name}")
        return 200, "OK"
    async def put_cookies(rest, query, headers, body):
        """cookies.txt exportado desde el navegador: se valida y se guarda solo lo de YouTube."""
        from . import cookies

        data = b"".join([c async for c in body])[: 5 << 20]
        try:
            info = cookies.import_file(data, ROOT / "data" / "cookies.txt")
        except ValueError as e:
            return 400, str(e)
        if prefs.set("yt_session", "archivo"):
            notify(prefs.public())
        notify({"type": "cookies", "browsers": cookies.detect(),
                "status": cookies.status(ROOT / "data" / "cookies.txt"), "imported": info})
        return 200, "OK"

    dubber, tts = None, None
    if a.voice != "none":
        from .dub import Dubber
        from .tts import TTSClient

        tts = TTSClient(a.voice, a.device, lazy=True)  # el proceso de voz arranca al primer uso
        dubber = Dubber(tts, ROOT / "data")
    tts_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
    info = {"model": a.model, "device": "GPU" if a.device == "cuda" else a.device.upper(),
            "translator": translator.name, "voice": a.voice}

    # avisos para todas las pestañas abiertas (cola, reposo, avance en segundo plano)
    sessions: set = set()
    loop_ref: dict = {}

    def notify(msg: dict):
        loop = loop_ref.get("loop")
        if not loop:
            return

        def send_all():
            for sess in list(sessions):
                out = sess.forward_bg(msg)
                if out is not None:
                    asyncio.ensure_future(sess.ws.send_json(out))

        loop.call_soon_threadsafe(send_all)

    res = Resources(asr, translator, tts, on_change=lambda st: notify({"type": "power", "state": st}))
    # arranca en reposo: la preparación cargó los modelos para verificarlos; vuelven a la RAM
    asr.unload()
    translator.unload()
    prefs = Prefs(ROOT / "data" / "prefs.json")
    processor = Processor(ROOT / "data", store, library, asr, translator, dubber, res, gpu, tts_exec, notify,
                          youtube=youtube, session=lambda: prefs.values.get("yt_session", "ninguna"))
    exporter = Exporter(ROOT / "data", store, library, processor, youtube, prefs, notify)

    async def ws_handler(ws):
        loop_ref["loop"] = asyncio.get_running_loop()
        session = Session(ws, asr, gpu, store, translator, info, dubber, tts_exec, youtube, library, res,
                          processor, prefs, notify, exporter)
        sessions.add(session)
        try:
            await session.run()
        finally:
            sessions.discard(session)

    (ROOT / "data" / "audio").mkdir(parents=True, exist_ok=True)
    server = AppServer({"/samples/": ROOT / "samples", "/audio/": ROOT / "data" / "audio",
                        "/media/yt/": ROOT / "data" / "youtube", "/media/lib/": lib_dir,
                        "/exports/": ROOT / "data" / "exports", "/": ROOT / "web"},
                       {"/ws": ws_handler}, {"/api/upload/": put_media, "/api/thumb/": put_thumb,
                                             "/api/cookies": put_cookies})
    url = f"http://{a.host}:{a.port}"
    print(f"Listo: {url}", flush=True)
    if not a.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        asyncio.run(server.serve(a.host, a.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
