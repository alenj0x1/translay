"""Material para el laboratorio del agente (tools/lab/agent.py): videos públicos completos, transcritos y
traducidos con los mismos modelos de Translay, guardados como transcripciones de verdad.

  python tools/lab/agent_fixtures.py            baja el audio de los que falten y los procesa

Salida en data/labs/agent/videos/<nombre>.json (con el formato de vt/store.py: segments con start, end,
text y translation) y <nombre>.screen.json si el laboratorio del texto en pantalla ya leyó ese video.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "labs" / "agent" / "videos"
# nombre → (id de YouTube, título, escenario)
VIDEOS = {
    "funnel": ("jQjOD579jhI", "The Digital Marketing Funnel Explained", "marketing, corto (2,5 min)"),
    "python-vscode": ("6i3e-j3wSf0", "Python Tutorial for Beginners with VS Code", "curso de programación (14 min)"),
    "talk-agents": ("pz74r-4dGfQ", "Your AI Agent Is Hiding Its Mistakes From You", "charla técnica (19 min)"),
    "econ-schools": ("o6UXRZ2XwgU", "The Most Important Economic Schools of Thought", "explicativo largo (26 min)"),
    "mit-supply": ("_OkTw766oCs", "1. Introduction and Supply & Demand", "clase universitaria (35 min)"),
}


def audio(vid: str, dest: Path) -> Path:
    out = dest / f"{vid}.m4a"
    if not out.exists():
        subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-warnings", "-f", "ba[ext=m4a]/ba", "-o", str(out),
                        f"https://www.youtube.com/watch?v={vid}"], check=True, timeout=1800)
    return out


def main():
    from faster_whisper import WhisperModel

    from vt.processor import decode_audio
    from vt.translate import load_translator

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_audio"
    tmp.mkdir(exist_ok=True)
    asr = WhisperModel("mobiuslabsgmbh/faster-whisper-large-v3-turbo", device="cuda", compute_type="float16")
    mt = load_translator("opus-big", device="cuda")
    for name, (vid, title, _) in VIDEOS.items():
        dst = OUT / f"{name}.json"
        if dst.exists():
            continue
        t0 = time.perf_counter()
        pcm = decode_audio(audio(vid, tmp))
        segs, _ = asr.transcribe(pcm, language="en", vad_filter=True, beam_size=5)
        segs = [{"id": i, "start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for i, s in enumerate(segs) if s.text.strip()]
        es = mt.translate_many([s["text"] for s in segs])
        for s, t in zip(segs, es):
            s["translation"] = t
        data = {"id": name, "name": title, "lang": "en", "mode": "translate", "segments": segs,
                "covered": [[0, segs[-1]["end"]]] if segs else [], "youtube": vid}
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        screen = ROOT / "data" / "labs" / "screentext" / "out" / name / "items.json"
        if screen.exists():
            items = json.loads(screen.read_text(encoding="utf-8"))
            (OUT / f"{name}.screen.json").write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(segs)} frases, {segs[-1]['end'] / 60:.1f} min en {time.perf_counter() - t0:.0f} s", flush=True)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
