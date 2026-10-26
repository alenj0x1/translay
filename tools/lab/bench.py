"""Banco de pruebas: el pipeline de la cola con una configuración, midiendo todo.

Hace lo mismo que vt/processor.py con un video: reconocimiento en streaming por
trozos de 3 s, traducción de cada frase, persona de cada frase y voz en otro hilo
(con los turnos en la GPU de vt/resources.py). Mide:

  tiempos      total y por etapa; velocidad = segundos de video por segundo de reloj
  en vivo      cuánto antes hay que empezar a preparar para que, reproduciendo desde
               el inicio, cada voz esté lista antes de su frase («espera»)
  memoria      pico de VRAM (nvidia-smi) y de RAM (lo informa el lab que lo lanza)
  calidad      error de palabras (WER) y personas acertadas, si hay verdad de referencia
  carga        cuánto tardó en cargar cada modelo

    python tools/lab/bench.py samples/podcast.mp4 --asr large-v3-turbo --mt opus-big \\
        --voice omnivoice --steps 16 --device cuda --out data/labs/x.json
"""

import argparse
import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def wait_for_job(timeout=3.0):
    """El lab mete este proceso en su Job Object justo después de lanzarlo: se espera a
    estar adentro antes de cargar nada (así los límites rigen desde el principio)."""
    if sys.platform != "win32" or not os.environ.get("TRANSLAY_LAB"):
        return
    k32 = ctypes.windll.kernel32
    t = time.time()
    while time.time() - t < timeout:
        inside = ctypes.c_int()
        k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(inside))
        if inside.value:
            return
        time.sleep(0.02)


class VramWatch:
    """Muestrea la VRAM usada de la GPU cada 0.25 s (pico durante el banco)."""

    def __init__(self):
        from vt.hardware import gpus

        self._g = gpus
        self.base = (gpus(0)[0]["vram_used_mb"] if gpus(0) else 0)
        self.peak = self.base
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.wait(0.25):
            g = self._g(0)
            if g:
                self.peak = max(self.peak, g[0]["vram_used_mb"] or 0)

    def stop(self) -> int:
        self._stop.set()
        return max(0, self.peak - self.base)


def main():
    wait_for_job()
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--asr", default="large-v3-turbo")
    p.add_argument("--asr-ct", default="float16", help="compute_type de Whisper (float16, int8_float16, int8)")
    p.add_argument("--beam", type=int, default=5)
    p.add_argument("--mt", default="opus-big")
    p.add_argument("--mt-ct", default=None, help="compute_type del traductor (por defecto, el del modelo)")
    p.add_argument("--voice", default="omnivoice", help="omnivoice | chatterbox | none")
    p.add_argument("--steps", type=int, default=16, help="pasos de la voz (OmniVoice)")
    p.add_argument("--device", default="cuda")
    p.add_argument("--limit-s", type=float, default=0, help="procesar solo los primeros N segundos")
    p.add_argument("--out")
    a = p.parse_args()

    from vt import gpu as _gpu

    _gpu.enable_cuda_dlls()
    from tools.eval_pipeline import score_diarization, wer, words
    from vt.asr import WhisperASR
    from vt.dub import Dubber
    from vt.processor import CHUNK_S, MAX_PENDING_DUBS, SR, decode_audio
    from vt.resources import Resources
    from vt.store import Store
    from vt.streaming import Segment, StreamingTranscriber
    from vt.translate import load_translator

    res = {"config": vars(a), "lab": json.loads(os.environ.get("TRANSLAY_LAB") or "null"), "ok": False}
    vram = VramWatch() if a.device == "cuda" else None
    t_all = time.perf_counter()
    try:
        audio = decode_audio(Path(a.media))
        if a.limit_s:
            audio = audio[: int(a.limit_s * SR)]
        dur = len(audio) / SR
        res["audio_s"] = round(dur, 1)

        t = time.perf_counter()
        ct = a.asr_ct if a.device == "cuda" else "int8"
        asr = WhisperASR(a.asr, a.device, ct, a.beam)
        asr.warmup()
        res["load_asr_s"] = round(time.perf_counter() - t, 1)
        t = time.perf_counter()
        mt = load_translator(a.mt, a.device, a.mt_ct)
        mt.translate("Warm up.")
        res["load_mt_s"] = round(time.perf_counter() - t, 1)

        tts = dubber = None
        data = Path(tempfile.mkdtemp(prefix="translay-lab-"))
        if a.voice != "none":
            from vt.tts import TTSClient

            t = time.perf_counter()
            tts = TTSClient(a.voice, a.device)
            res["load_tts_s"] = round(time.perf_counter() - t, 1)
            dubber = Dubber(tts, data)
            dubber.tts_params = {"num_step": a.steps}
        resources = Resources(asr, mt, tts)
        gpu = ThreadPoolExecutor(1, thread_name_prefix="gpu")
        tts_exec = ThreadPoolExecutor(1, thread_name_prefix="voz")
        store = Store(data / "transcripts")
        tr = store.open("lab_bench", "lab")

        times = {"asr": 0.0, "mt": 0.0, "tts": 0.0}
        waits = {"asr": 0.0, "mt": 0.0, "tts": 0.0}
        tts_each, segs, labels, ready = [], [], [], {}
        t0 = time.perf_counter()

        def timed(stage, fn, *args):
            """Corre con los turnos de la GPU; separa el cálculo de la espera del turno."""
            inner = [0.0]

            def work(*a2):
                t = time.perf_counter()
                try:
                    return fn(*a2)
                finally:
                    inner[0] = time.perf_counter() - t

            t = time.perf_counter()
            out = resources.run((stage,), work, *args)
            times[stage] += inner[0]
            waits[stage] += max(0.0, time.perf_counter() - t - inner[0])
            return out, inner[0]

        def dub_job(seg, orig_db):
            info, el = timed("tts", dubber.synthesize, tr, seg, orig_db)
            tts_each.append(el)
            ready[seg["id"]] = time.perf_counter() - t0
            return info

        dubs = []
        st = StreamingTranscriber(asr)

        def handle(events):
            for ev in events:
                if not isinstance(ev, Segment):
                    continue
                es = gpu.submit(timed, "mt", mt.translate, ev.text).result()[0]
                seg, _ = tr.add_segment(ev.start, ev.end, ev.text, es, mt.name)
                segs.append(ev)
                if dubber:
                    seg["speaker"] = dubber.identify(tr, seg, ev.audio)
                    labels.append(seg["speaker"])
                    dubs.append(tts_exec.submit(dub_job, seg, dubber.loudness(ev.audio)))
                else:
                    ready[seg["id"]] = time.perf_counter() - t0

        step = int(CHUNK_S * SR)
        pos = 0
        while pos < len(audio):
            while sum(not f.done() for f in dubs) > MAX_PENDING_DUBS:
                time.sleep(0.05)
            st.feed(pos / SR, audio[pos:pos + step])
            pos += step
            if st.ready():
                handle(gpu.submit(timed, "asr", st.step).result()[0])
        handle(gpu.submit(timed, "asr", st.flush).result()[0])
        for f in dubs:
            f.result()
        wall = time.perf_counter() - t0

        # en vivo: reproduciendo desde el inicio, cada voz debe estar lista antes de su frase
        lead = [ready[s["id"]] - s["start"] for s in tr.segments if s["id"] in ready]
        res.update({
            "ok": True,
            "wall_s": round(wall, 1),
            "speed": round(dur / wall, 2) if wall else None,
            "stage_s": {k: round(v, 1) for k, v in times.items()},
            "wait_turn_s": {k: round(v, 1) for k, v in waits.items()},
            "segments": len(tr.segments),
            "tts_p50_s": round(sorted(tts_each)[len(tts_each) // 2], 2) if tts_each else None,
            "tts_p95_s": round(sorted(tts_each)[int(len(tts_each) * 0.95) - 1], 2) if tts_each else None,
            "wait_s": round(max(lead), 1) if lead else None,  # espera antes de reproducir para no alcanzar a la voz
        })
        truth_f = Path(a.media).with_suffix(".truth.json")
        if not truth_f.exists():
            truth_f = Path(a.media).parent / (Path(a.media).stem.split("_")[0] + ".truth.json")
        if truth_f.exists():
            truth = json.loads(truth_f.read_text(encoding="utf-8"))
            ref = [t for t in truth if t["start"] < dur]
            res["wer"] = round(wer(words(" ".join(t["text"] for t in ref)), words(" ".join(s.text for s in segs))), 3)
            if dubber:
                res["speakers_ok"] = round(score_diarization(segs, labels, ref)[0], 3)
        if tts:
            tts.close()
    except Exception as e:  # sin memoria, CUDA, etc.: también es un resultado del lab
        res["error"] = f"{type(e).__name__}: {e}"[:400]
    res["total_s"] = round(time.perf_counter() - t_all, 1)
    if vram:
        res["vram_peak_mb"] = vram.stop()
    out = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
