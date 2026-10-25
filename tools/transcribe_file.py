"""Simula la reproducción de un video y corre el streaming sin navegador.

Sirve para medir y ajustar la política de streaming de forma reproducible:
imprime cada frase con su tiempo, el retraso con que se habría mostrado y el
factor de tiempo real. Opcionalmente escribe un .srt.

    python tools/transcribe_file.py samples/demo.mp4 --srt out.srt
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt.asr import WhisperASR  # noqa: E402
from vt.streaming import Segment, StreamingTranscriber  # noqa: E402
from vt.translate import load_translator  # noqa: E402

SR = 16000


def decode(path: str) -> np.ndarray:
    import av

    out = []
    with av.open(path) as c:
        res = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for frame in c.decode(audio=0):
            for f in res.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) / 32768.0


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--model", default="large-v3-turbo")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--chunk", type=float, default=0.1)
    p.add_argument("--translator", default="opus-big")
    p.add_argument("--srt")
    a = p.parse_args()

    audio = decode(a.media)
    asr = WhisperASR(a.model, beam_size=a.beam)
    asr.warmup()
    mt = load_translator(a.translator)
    mt.translate("Warm up.")
    st = StreamingTranscriber(asr)
    step = int(a.chunk * SR)
    segs: list[Segment] = []
    lags, gpu, mt_ms = [], 0.0, []
    t_wall = time.perf_counter()

    def collect(events, now):
        for e in events:
            if isinstance(e, Segment):
                segs.append(e)
                lags.append(now - e.end)
                t = time.perf_counter()
                e.es = mt.translate(e.text)
                mt_ms.append((time.perf_counter() - t) * 1000)
                print(f"[{e.start:7.2f} → {e.end:7.2f}] (+{now - e.end:4.2f}s) {e.text}")
                if e.es:
                    print(f"{'':28}{e.es}")

    # reproduce la cadencia en vivo: mientras la GPU trabaja, el video sigue
    # avanzando y ese audio se acumula para la siguiente inferencia
    clock, i = 0.0, 0
    while i < len(audio):
        while i < len(audio) and (i + step) / SR <= clock:
            st.feed(i / SR, audio[i:i + step])
            i += step
        if st.ready():
            t = time.perf_counter()
            events = st.step()
            dt = time.perf_counter() - t
            gpu += dt
            clock += dt
            collect(events, clock)
        else:
            st.feed(i / SR, audio[i:i + step])
            i += step
            clock = max(clock, i / SR)
    collect(st.flush(), len(audio) / SR)

    dur = len(audio) / SR
    print(f"\naudio {dur:.1f}s · GPU {gpu:.1f}s · RTF {gpu / dur:.2f} · "
          f"retraso medio {np.mean(lags) if lags else 0:.2f}s · máx {max(lags, default=0):.2f}s · "
          f"pared {time.perf_counter() - t_wall:.1f}s · traducción {np.median(mt_ms) if mt_ms else 0:.0f} ms/frase")
    if a.srt:
        with open(a.srt, "w", encoding="utf-8") as f:
            for n, s in enumerate(segs, 1):
                f.write(f"{n}\n{srt_time(s.start)} --> {srt_time(s.end)}\n{getattr(s, 'es', None) or s.text}\n\n")


if __name__ == "__main__":
    main()
