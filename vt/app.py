"""Punto de entrada del servidor: carga el modelo y sirve la vista."""

import argparse
import asyncio
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .asr import WhisperASR
from .httpws import AppServer
from .session import Session
from .store import Store
from .translate import MODELS as MT_MODELS, load_translator

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

    print(f"Cargando {a.model} en {a.device} ({a.compute_type})…", flush=True)
    asr = WhisperASR(a.model, a.device, a.compute_type, a.beam)
    asr.warmup()
    print(f"Cargando traductor {a.translator}…", flush=True)
    translator = load_translator(a.translator, a.device)
    translator.translate("Warm up.")
    gpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")  # un solo hilo usa la GPU
    store = Store(ROOT / "data" / "transcripts")
    dubber, tts_exec = None, None
    if a.voice != "none":
        from .dub import Dubber
        from .tts import TTSClient

        print(f"Cargando voz {a.voice}…", flush=True)
        dubber = Dubber(TTSClient(a.voice, a.device), ROOT / "data")
        tts_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
    info = {"model": a.model, "device": "GPU" if a.device == "cuda" else a.device.upper(),
            "translator": translator.name, "voice": a.voice}

    async def ws_handler(ws):
        await Session(ws, asr, gpu, store, translator, info, dubber, tts_exec).run()

    (ROOT / "data" / "audio").mkdir(parents=True, exist_ok=True)
    server = AppServer({"/samples/": ROOT / "samples", "/audio/": ROOT / "data" / "audio",
                        "/": ROOT / "web"}, {"/ws": ws_handler})
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
