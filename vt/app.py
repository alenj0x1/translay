"""Punto de entrada del servidor: carga el modelo y sirve la vista."""

import argparse
import asyncio
import os
import re
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .asr import WhisperASR
from .httpws import AppServer
from .session import Session
from .translate import MODELS as MT_MODELS, load_translator
from .prefs import Prefs
from .processor import Processor
from .exporter import Exporter
from .resources import Resources
from .vaults import Vaults

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description="Translay: traduce y dobla videos del inglés al español")
    p.add_argument("--version", action="version", version=f"Translay {__version__}")
    p.add_argument("--host", default="127.0.0.1",
                   help="Dirección donde escucha el servidor (0.0.0.0 para todas, p. ej. en Docker)")
    p.add_argument("--port", type=int, default=8765, help="Puerto HTTP y WebSocket")
    # sin estos argumentos, los modelos salen del perfil de rendimiento (Preferencias → Rendimiento,
    # vt/profiles.py), elegido según el equipo; si se pasan, ganan sobre el perfil
    p.add_argument("--model", default=None, help="Modelo de Whisper (por defecto, el del perfil de rendimiento)")
    p.add_argument("--device", default=None, help="cuda (GPU NVIDIA) o cpu (por defecto, cuda si hay GPU)")
    p.add_argument("--compute-type", default=None, help="Precisión de Whisper en CTranslate2: float16, int8_float16, int8…")
    p.add_argument("--beam", type=int, default=None, help="Ancho de búsqueda de Whisper (5 segmenta mejor que 1)")
    p.add_argument("--translator", default=None,
                   help="none | " + " | ".join(MT_MODELS) + " | repo de HF (Marian CT2) (por defecto, el del perfil)")
    p.add_argument("--voice", default=None, help="none | omnivoice | chatterbox (por defecto, según el perfil)")
    p.add_argument("--owner-password", default=os.environ.get("TRANSLAY_OWNER_PASSWORD", ""),
                   help="Contraseña del dueño al arrancar (o TRANSLAY_OWNER_PASSWORD); hace falta cuando "
                        "nadie entra desde 127.0.0.1, como en Docker")
    p.add_argument("--allow-origin", action="append",
                   default=[o for o in os.environ.get("TRANSLAY_ORIGINS", "").split(",") if o.strip()],
                   help="Otro origen desde el que se puede usar la app (p. ej. https://translay.midominio.com "
                        "detrás de un proxy que cambia el Host); se repite, o TRANSLAY_ORIGINS separados por comas")
    p.add_argument("--no-browser", action="store_true", help="No abrir el navegador al arrancar")
    p.add_argument("--data-dir", default=os.environ.get("TRANSLAY_DATA", ""),
                   help="Carpeta de datos de la biblioteca Principal (o TRANSLAY_DATA; por defecto, data/ junto "
                        "al código). La app de escritorio usa la que elegiste al instalar")
    a = p.parse_args()
    DATA = Path(a.data_dir).expanduser().resolve() if a.data_dir else ROOT / "data"
    DATA.mkdir(parents=True, exist_ok=True)

    # equipo, límites y perfil de rendimiento (vt/hardware.py, vt/limits.py, vt/profiles.py)
    from . import hardware, profiles
    from .limits import apply_self

    prefs = Prefs(DATA / "prefs.json")
    hw = hardware.detect()
    lim = {"vram_mb": int(prefs.values.get("limit_vram_mb") or 0) or None,
           "ram_mb": int(prefs.values.get("limit_ram_mb") or 0) or None,
           "threads": int(prefs.values.get("limit_threads") or 0) or None}
    err = apply_self(lim["ram_mb"], lim["threads"])
    if err:
        print(f"[rendimiento] {err}", flush=True)
    cli = {k: v for k, v in vars(a).items() if k in ("model", "device", "compute_type", "beam", "translator", "voice")
           and v is not None}
    # el dispositivo real decide el perfil: con --device cpu (o sin CUDA usable) es como no tener GPU
    a.device = a.device or ("cuda" if hw.get("gpu") and hardware.cuda_usable() else "cpu")
    if a.device != "cuda":
        hw = dict(hw, gpu=None)
    active = profiles.resolve(prefs.values.get("perf_profile", "auto"), hw, lim)
    prof = profiles.PROFILES[active]
    a.model = a.model or prof["asr"]
    a.compute_type = a.compute_type or (prof["asr_ct"] if a.device == "cuda" else "int8")
    a.beam = a.beam or prof["beam"]
    mt_ct = None if a.translator else prof["mt_ct"]
    a.translator = a.translator or prof["mt"]
    a.voice = a.voice or ("omnivoice" if prof["voice"] else "none")
    g = hw.get("gpu")
    unified = bool(g and g.get("unified"))  # memoria unificada, como DGX Spark (vt/hardware.py)
    mem = " de memoria unificada" if unified else ""
    print(f"Equipo: {g['name'] + ' ' + str(round((g.get('vram_total_mb') or 0) / 1024)) + ' GB' + mem if g else 'sin GPU'} · "
          f"{round((hw['ram']['total_mb'] or 0) / 1024)} GB de RAM · {hw['cpu']['usable_threads']} hilos · "
          f"perfil «{prof['name']}»" + (f" (con {', '.join(cli)} por línea de comandos)" if cli else ""), flush=True)

    print(f"Preparando {a.model} en {a.device} ({a.compute_type})…", flush=True)
    asr = WhisperASR(a.model, a.device, a.compute_type, a.beam)
    asr.warmup()
    print(f"Preparando traductor {a.translator}…", flush=True)
    translator = load_translator(a.translator, a.device, mt_ct)
    translator.translate("Warm up.")
    gpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")  # un solo hilo usa la GPU
    # bibliotecas (vt/vaults.py): Principal es data/; las demás, cada una en su carpeta
    vaults = Vaults(DATA)
    for vault in vaults.all():
        vault.library.import_youtube(vault.root / "youtube")
    store, library, youtube = vaults.store, vaults.library, vaults.main.youtube

    def backfill_youtube():
        """Miniatura, canal y categorías de videos YA descargados que no los tengan.

        Solo lo que está en el equipo (lo pendiente lo completa la cola al descargarlo),
        nunca descarga, y con pausas: miles de consultas seguidas al arrancar hacían que
        YouTube bloqueara la sesión ("confirma que no eres un bot")."""
        import time as _time

        for vid, v in list(library.data["videos"].items()):
            if v.get("source") == "youtube" and v.get("media") and (not v.get("thumb") or "categories" not in v):
                try:
                    vault = vaults.of(vid) or vaults.main  # ya descargado: no baja nada
                    info = vault.youtube.fetch(vid[3:], audio_only=bool(v.get("audio_only")))
                    library.set_field(vid, **{k: info[k] for k in ("thumb", "channel", "categories", "title")
                                              if info.get(k) is not None})
                except Exception as e:
                    print(f"[biblioteca] {vid}: {e}", flush=True)
                _time.sleep(3)

    threading.Thread(target=backfill_youtube, daemon=True).start()
    lib_dir = DATA / "library"
    lib_dir.mkdir(parents=True, exist_ok=True)

    def vault_dir(vid: str, query: dict) -> Path:
        """Carpeta de archivos importados de la biblioteca del video (o de la indicada)."""
        v = vaults.of(vid) or vaults.get(query.get("lib")) or vaults.main
        d = v.root / "library"
        d.mkdir(parents=True, exist_ok=True)
        return d

    MEDIA_EXTS = {"mp4", "m4v", "webm", "mkv", "mov", "avi", "ts", "flv", "wmv", "3gp", "mpg", "mpeg", "mp3", "m4a", "wav", "ogg", "opus", "flac", "aac"}

    async def put_media(rest, query, headers, body):
        """Copia de un archivo local, para volver a verlo desde la biblioteca."""
        vid = rest.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", vid):
            return 400, "id invalido"
        ext = re.sub(r"[^a-z0-9]", "", Path(query.get("name", "video.mp4")).suffix.lower())[:5] or "mp4"
        if ext not in MEDIA_EXTS:  # solo video o audio: nada que el navegador abra como página
            return 400, "formato no admitido"
        out = vault_dir(vid, query) / f"{vid}.{ext}"
        tmp = out.with_suffix(".part")
        try:
            with tmp.open("wb") as f:
                async for chunk in body:
                    f.write(chunk)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)  # subida cortada: no queda el archivo a medias
        library.set_field(vid, media=f"/media/lib/{out.name}")
        return 200, "OK"

    async def put_thumb(rest, query, headers, body):
        vid = rest.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", vid):
            return 400, "id invalido"
        out = vault_dir(vid, query) / f"{vid}.jpg"
        data = b""
        async for c in body:  # como mucho 2 MB: lo demás no se guarda en memoria
            data += c[: (2 << 20) - len(data)]
        if not data.startswith(b"\xff\xd8"):
            return 400, "no es una imagen JPEG"
        out.write_bytes(data)
        library.set_field(vid, thumb=f"/media/lib/{out.name}")
        return 200, "OK"
    thumbs_dir = DATA / "youtube" / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    thumb_locks: dict = {}

    async def get_thumb(rest):
        """Miniatura de un video de YouTube: se baja una sola vez y queda en el equipo
        (con miles importados, pedirlas a YouTube cada vez que se muestran sobra)."""
        hd = rest.endswith("_hd.jpg")  # grande (la portada de la biblioteca)
        vid = rest.removesuffix(".jpg").removesuffix("_hd")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            return None
        for f in [v.root / "youtube" / f"{vid}.jpg" for v in vaults.all()] + [thumbs_dir / f"{vid}{'_hd' if hd else ''}.jpg"]:
            if f.exists():  # la del video descargado (en su biblioteca) vale
                return f
        lock = thumb_locks.setdefault(vid, asyncio.Lock())
        async with lock:
            out = thumbs_dir / f"{vid}{'_hd' if hd else ''}.jpg"
            if not out.exists():
                def fetch():
                    import urllib.request

                    for size in (("maxresdefault", "hqdefault") if hd else ("mqdefault",)):
                        try:
                            with urllib.request.urlopen(f"https://i.ytimg.com/vi/{vid}/{size}.jpg", timeout=8) as r:
                                data = r.read(4 << 20)
                            break
                        except Exception:
                            data = None
                    if not data:
                        raise OSError("sin miniatura")
                    tmp = out.with_suffix(".part")
                    tmp.write_bytes(data)
                    tmp.replace(out)
                try:
                    await asyncio.get_running_loop().run_in_executor(None, fetch)
                except Exception:
                    return None
        thumb_locks.pop(vid, None)
        return out if out.exists() else None

    chan_dir = DATA / "youtube" / "channels"
    chan_dir.mkdir(parents=True, exist_ok=True)
    chan_locks: dict = {}  # canales ya pedidos en esta sesión
    chan_sem = asyncio.Semaphore(1)  # de a uno con YouTube

    async def get_channel_art(rest):
        """/chan/<avatar|banner>/<canal>: avatar o banner del canal de YouTube, bajado una
        sola vez (si el canal no tiene, se recuerda y la vista usa su patrón)."""
        from urllib.parse import unquote

        kind, _, name = rest.partition("/")
        name = unquote(name).strip()
        if kind not in ("avatar", "banner") or not name:
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "x"
        out = chan_dir / slug
        f = chan_dir / f"{slug}_{kind}.jpg"
        miss = chan_dir / f"{slug}.none"
        if f.exists() or miss.exists():
            return f if f.exists() else None
        vid = next((i for vault in vaults.all() for i, v in vault.library.data["videos"].items()
                    if v.get("source") == "youtube" and v.get("channel") == name), None)
        if not vid:
            return None
        # se baja aparte, de a uno: esperar aquí a yt-dlp dejaría ocupadas las conexiones del
        # navegador (con muchos canales, el video no llega a cargar) y YouTube frena las ráfagas.
        # Mientras tanto la vista usa el patrón; la próxima vez ya está.
        if slug not in chan_locks:
            chan_locks[slug] = True

            async def fetch():
                async with chan_sem:
                    if f.exists() or miss.exists():
                        return
                    try:
                        got = await asyncio.get_running_loop().run_in_executor(
                            None, youtube.channel_art, vid[3:], out, prefs.values.get("yt_session", "ninguna"))
                        if not got:
                            miss.write_text("", encoding="utf-8")
                    except Exception as e:
                        print(f"[canal] {name}: {e}", flush=True)
                        if "rate-limited" not in str(e):  # frenado por YouTube: se reintenta otro día
                            miss.write_text(str(e)[:300], encoding="utf-8")
                        await asyncio.sleep(60)

            asyncio.ensure_future(fetch())
        return None

    async def get_vault_file(rest):
        """Archivos de las demás bibliotecas: /v/<biblioteca>/media/yt/…, /audio/…, /voices/…, /people/…"""
        vid, _, sub = rest.partition("/")
        v = vaults.get(vid)
        f = v.file("/" + sub) if v else None
        return f if f and f.is_file() else None

    async def get_main_people(rest):
        f = vaults.main.file("/people/" + rest)
        return f if f and f.is_file() else None

    async def put_cookies(rest, query, headers, body):
        """cookies.txt exportado desde el navegador: se valida y se guarda solo lo de YouTube."""
        from . import cookies

        data = b"".join([c async for c in body])[: 5 << 20]
        try:
            info = cookies.import_file(data, DATA / "cookies.txt")
        except ValueError as e:
            return 400, str(e)
        if prefs.set("yt_session", "archivo"):
            notify(prefs.public())
        processor.unblock()  # cookies nuevas: las descargas en pausa siguen
        notify({"type": "cookies", "browsers": cookies.detect(),
                "status": cookies.status(DATA / "cookies.txt"), "imported": info})
        return 200, "OK"

    dubber, tts = None, None
    if a.voice != "none":
        from .dub import Dubber
        from .tts import TTSClient

        tts = TTSClient(a.voice, a.device, lazy=True)  # el proceso de voz arranca al primer uso
        dubber = Dubber(tts, DATA)
        dubber.tts_params = {"num_step": prof["steps"] or 16}
    tts_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
    info = {"model": a.model, "device": "GPU" if a.device == "cuda" else a.device.upper(),
            "translator": translator.name, "voice": a.voice, "profile": active}

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

    # con memoria unificada «pasar a la RAM» no libera nada: se duerme directo al cerrar la voz (2 min)
    res = Resources(asr, translator, tts, on_change=lambda st: notify({"type": "power", "state": st}),
                    idle_s=120 if unified else 45)
    # arranca en reposo: la preparación cargó los modelos para verificarlos; vuelven a la RAM
    asr.unload()
    translator.unload()
    from .perf import Perf

    perf = Perf(prefs, res, active, cli, device=a.device)
    processor = Processor(DATA, store, library, asr, translator, dubber, res, gpu, tts_exec, notify,
                          youtube=youtube, session=lambda: prefs.values.get("yt_session", "ninguna"), vaults=vaults,
                          order=lambda: prefs.values.get("download_order", "orden"))
    exporter = Exporter(DATA, store, library, processor, youtube, prefs, notify, vaults=vaults)

    # acceso (vt/auth.py), webhooks (vt/webhooks.py) y API (vt/api.py)
    from .api import Admin, Api, CollectorWS, make_guard
    from .auth import Auth, check_pw, same_origin
    from .webhooks import Webhooks

    auth = Auth(DATA / "auth.json", vaults)
    if a.owner_password and not check_pw(a.owner_password, auth.data.get("owner")):
        auth.set_owner_password(a.owner_password)  # Docker: desde el contenedor nadie llega por 127.0.0.1
    origins = tuple(o.strip().rstrip("/").lower() for o in a.allow_origin)
    hooks = Webhooks(DATA / "webhooks.json", notify)
    admin = Admin(auth, hooks, a.port)

    def make_session(vault, access):
        s = Session(CollectorWS(), asr, gpu, store, translator, info, dubber, tts_exec, youtube, library, res,
                    processor, prefs, notify, exporter, vaults=vaults, access=access, admin=admin, perf=perf)
        s.vault = vault
        return s

    api = Api(vaults, auth, processor, exporter, make_session)

    async def get_app_page(rest):
        return ROOT / "web" / "index.html"  # /b/<biblioteca>: la misma página, con esa biblioteca

    async def ws_handler(ws):
        loop_ref["loop"] = asyncio.get_running_loop()
        session = Session(ws, asr, gpu, store, translator, info, dubber, tts_exec, youtube, library, res,
                          processor, prefs, notify, exporter, vaults=vaults, access=auth.access(ws.request),
                          admin=admin, perf=perf)
        sessions.add(session)
        try:
            await session.run()
        finally:
            sessions.discard(session)

    (DATA / "audio").mkdir(parents=True, exist_ok=True)
    server = AppServer({"/samples/": ROOT / "samples", "/audio/": DATA / "audio",
                        "/media/yt/": DATA / "youtube", "/media/lib/": lib_dir,
                        "/exports/": DATA / "exports", "/voices/": DATA / "voices",
                        "/": ROOT / "web"},
                       {"/ws": ws_handler}, {"/api/upload/": put_media, "/api/thumb/": put_thumb,
                                             "/api/cookies": put_cookies},
                       {"/thumb/yt/": get_thumb, "/chan/": get_channel_art,"/v/": get_vault_file, "/people/": get_main_people, "/b/": get_app_page},
                       {"/api/v1": api.route, "/api/auth/": api.auth_route}, make_guard(auth, vaults),
                       origin_ok=lambda h: same_origin(h, origins))
    admin.server = server
    url = f"http://{a.host}:{a.port}"
    print(f"Listo: {url}", flush=True)
    if not a.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        async def run_all():
            loop_ref["loop"] = asyncio.get_running_loop()
            if admin.network:  # «Acceso desde otros equipos» (Preferencias → Acceso y API)
                await admin.set_network(True)
                print("En la red: " + ", ".join(f"http://{ip}:{a.port}" for ip in admin.lan_ips()), flush=True)
            await server.serve(a.host, a.port)

        asyncio.run(run_all())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
