"""Lab de CPU (y gráfica integrada): qué tan rápido reconoce y traduce Translay sin GPU NVIDIA.

Corre igual en esta máquina y en otro equipo: ahí lo lanza tools/lab/laptop.ps1 con el Python
y el código que instaló la app de escritorio, y el resultado vuelve como un solo JSON.

Variantes (cada una en su propio proceso, con tiempo límite; se intercalan por rondas):
  stream-*    lo que hace hoy la cola (vt/processor.py): reconocimiento en streaming por trozos de 3 s
  whole-*     el archivo entero de una vez (ventanas de 30 s, saltando silencios)
  batch-*     igual, con varias ventanas a la vez (BatchedInferencePipeline)
  wcpp-*      whisper.cpp (--whispercpp): en la CPU o en la gráfica por Vulkan (cualquier GPU, también AMD)
  mt-*        traducción de las frases de referencia (opus-base)
  *-def       hilos por defecto de CTranslate2 (4) · *-cores: un hilo por núcleo físico

Mide la velocidad (segundos de audio por segundo de reloj), la memoria pico del proceso y el error
de palabras (WER) contra <media>.truth.json.

    python tools/lab/cpu.py --media samples/podcast.mp4 --out data/labs/cpu-1
    python tools/lab/cpu.py --media a.mp4 --out x --whispercpp C:/wcpp --variants whole-small-cores wcpp-small-vk
"""

import argparse
import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve()
SR = 16000

# modelo, compute_type y beam de cada perfil (vt/profiles.py)
ASR = {"small": ("Systran/faster-whisper-small", "int8", 3),
       "turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "int8", 5)}
GGML = {"small": "ggml-small.bin", "turbo": "ggml-large-v3-turbo-q5_0.bin"}
VARIANTS = ["stream-small-def", "stream-small-cores", "whole-small-def", "whole-small-cores", "batch-small-cores",
            "whole-turbo-cores", "batch-turbo-cores", "wcpp-small-cpu", "wcpp-small-vk", "wcpp-turbo-vk",
            "mt-base-def", "mt-base-cores"]


def peak_mb(handle: int | None = None) -> float:
    """Memoria pico de este proceso (o del proceso de ese handle, aunque ya haya terminado)."""
    if os.name != "nt":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + \
                   [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                   "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                   "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    k32.GetCurrentProcess.restype = ctypes.c_void_p  # un HANDLE de 64 bits: como int se truncaba y medía 0
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo(handle or k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.PeakWorkingSetSize / 2**20


def decode(media: Path):
    """Audio mono 16 kHz con ffmpeg (el de la app de escritorio está en su carpeta tools, en el PATH)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(media), "-f", "s16le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0


def words(t: str) -> list[str]:  # como tools/eval_pipeline.py
    return re.sub(r"[^\w' ]+", " ", t.lower().replace("$", " dollars ")).split()


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    return d[len(hyp)] / max(1, len(ref))


def truth_of(media: Path) -> list[dict]:
    f = media.with_suffix(".truth.json")
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


# ------------------------------------------------------------------ una variante (proceso propio)
def run_variant(v: str, media: Path, cores: int, wcpp: Path | None) -> dict:
    kind, rest = v.split("-", 1)
    threads = 0 if v.endswith("-def") else cores
    audio = decode(media)
    dur = len(audio) / SR
    out = {"variant": v, "threads": threads or "def", "audio_s": round(dur, 2)}
    t0 = time.perf_counter()
    text = ""
    if kind in ("stream", "whole", "batch"):
        from faster_whisper import WhisperModel
        repo, ct, beam = ASR[rest.split("-")[0]]
        model = WhisperModel(repo, device="cpu", compute_type=ct, cpu_threads=threads)
        out["load_s"] = round(time.perf_counter() - t0, 2)
        t0 = time.perf_counter()
        if kind == "stream":  # la cola de hoy: vt.streaming con el motor de Translay
            sys.path.insert(0, str(Path(os.environ.get("TRANSLAY_CODE") or HERE.parents[2])))
            from vt.asr import WhisperASR
            from vt.streaming import Segment, StreamingTranscriber
            asr = WhisperASR.__new__(WhisperASR)
            asr.name, asr.device, asr.language, asr.beam_size, asr.model = rest.split("-")[0], "cpu", "en", beam, model
            st, segs, step = StreamingTranscriber(asr), [], int(3.0 * SR)  # CHUNK_S de vt/processor.py
            for a in range(0, len(audio), step):
                st.feed(a / SR, audio[a:a + step])
                if st.ready():
                    segs += [e for e in st.step() if isinstance(e, Segment)]
            segs += [e for e in st.flush() if isinstance(e, Segment)]
            text = " ".join(s.text for s in segs)
        else:
            kw = dict(language="en", beam_size=beam, word_timestamps=True, condition_on_previous_text=False,
                      temperature=0.0, vad_filter=True)
            if kind == "batch":
                from faster_whisper import BatchedInferencePipeline
                segs, _ = BatchedInferencePipeline(model).transcribe(audio, batch_size=8, **kw)
            else:
                segs, _ = model.transcribe(audio, **kw)
            text = " ".join(s.text for s in segs)
    elif kind == "wcpp":
        size, dev = rest.split("-")
        exe = next((p for p in (wcpp / "whisper-cli.exe", wcpp / "main.exe") if p.exists()), None)
        model = wcpp / GGML[size]
        if not exe or not model.exists():
            return {**out, "skipped": f"falta {'whisper-cli.exe' if not exe else model.name} en {wcpp}"}
        vad = wcpp / "ggml-silero-v5.1.2.bin"
        if not vad.exists():
            return {**out, "skipped": f"falta {vad.name} en {wcpp}"}
        wav = Path(tempfile.gettempdir()) / f"translay-lab-{os.getpid()}.wav"
        import wave
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
            w.writeframes((audio * 32768).clip(-32768, 32767).astype("<i2").tobytes())  # las muestras exactas de ffmpeg
        # con su detector de voz: sin él, whisper.cpp se saltaba tramos enteros (50 de 171 palabras) con un audio
        # que difería en 1 de amplitud; con él, las mismas 170 palabras siempre (como vad_filter en faster-whisper)
        args = [str(exe), "-m", str(model), "-f", str(wav), "-l", "en", "-t", str(cores), "-bs", "5" if size == "turbo" else "3",
                "-nt", "--vad", "-vm", str(vad)] + (["-ng"] if dev == "cpu" else [])
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        stdout, stderr = proc.communicate()
        out["child_peak_mb"] = round(peak_mb(int(proc._handle))) if os.name == "nt" else None
        wav.unlink(missing_ok=True)
        text = " ".join(l.strip() for l in stdout.splitlines() if l.strip())
        gpu = re.findall(r"ggml_vulkan: \d+ = ([^|\n]+)", stderr)
        out.update(rc=proc.returncode, device=gpu[0].strip() if gpu and dev != "cpu" else "CPU",
                   stderr_tail=[l for l in stderr.strip().splitlines() if "total time" in l or "vulkan" in l.lower()][-6:])
        if proc.returncode:
            return {**out, "error": "whisper.cpp terminó con error", "stderr_tail": stderr.strip().splitlines()[-8:]}
    elif kind == "mt":
        sys.path.insert(0, str(Path(os.environ.get("TRANSLAY_CODE") or HERE.parents[2])))
        import ctranslate2
        orig = ctranslate2.Translator
        ctranslate2.Translator = lambda *a, **k: orig(*a, **{**k, **({"intra_threads": threads} if threads else {})})
        from vt.translate import load_translator
        tr = load_translator("opus-base", device="cpu")
        out["load_s"] = round(time.perf_counter() - t0, 2)
        lines = [t["text"] for t in truth_of(media)]
        t0 = time.perf_counter()
        es = [tr.translate(s) for s in lines]  # de a una frase, como la cola
        wall = time.perf_counter() - t0
        return {**out, "wall_s": round(wall, 2), "sentences": len(lines), "ms_per_sentence": round(wall * 1000 / max(1, len(lines))),
                "peak_mb": round(peak_mb()), "sample": es[:3]}
    wall = time.perf_counter() - t0
    out.update(wall_s=round(wall, 2), speed=round(dur / wall, 2) if wall else None, text=text,
               peak_mb=out.pop("child_peak_mb", None) or round(peak_mb()))
    ref = truth_of(media)
    if ref:
        out["wer"] = round(wer(words(" ".join(t["text"] for t in ref if t["start"] < dur)), words(text)), 3)
    return out


# ------------------------------------------------------------------ todas (rondas intercaladas)
def machine() -> dict:
    info = {"os": platform.platform(), "python": sys.version.split()[0], "logical": os.cpu_count()}
    try:
        import ctranslate2
        import faster_whisper
        info.update(ctranslate2=ctranslate2.__version__, faster_whisper=faster_whisper.__version__,
                    ct2_cpu_types=sorted(ctranslate2.get_supported_compute_types("cpu")))
    except Exception as e:  # noqa: BLE001
        info["import_error"] = str(e)
    return info


def main():
    p = argparse.ArgumentParser(description="Lab de CPU y gráfica integrada (reconocimiento y traducción)")
    p.add_argument("--media", required=True, help="audio o video (con <nombre>.truth.json al lado para el WER)")
    p.add_argument("--out", required=True, help="carpeta de resultados (o el JSON de una variante con --one)")
    p.add_argument("--variants", nargs="*", default=VARIANTS)
    p.add_argument("--cores", type=int, default=0, help="núcleos físicos (por defecto, la mitad de los hilos)")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--timeout", type=float, default=900, help="segundos máximos por variante")
    p.add_argument("--whispercpp", help="carpeta con whisper-cli.exe y los modelos ggml")
    p.add_argument("--one", help=argparse.SUPPRESS)
    a = p.parse_args()
    cores = a.cores or max(1, (os.cpu_count() or 2) // 2)
    wcpp = Path(a.whispercpp) if a.whispercpp else None
    media = Path(a.media)
    if a.one:
        res = run_variant(a.one, media, cores, wcpp)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    variants = [v for v in a.variants if not v.startswith("wcpp") or wcpp]
    results = {"machine": machine(), "cores": cores, "media": media.name, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
               "runs": []}
    print(f"{len(variants)} variantes × {a.rounds} rondas · {cores} núcleos · {media.name}", flush=True)
    for rnd in range(a.rounds):
        for v in variants:
            f = out / f"{v}.r{rnd + 1}.json"
            t = time.time()
            try:
                r = subprocess.run([sys.executable, str(HERE), "--one", v, "--media", str(media), "--out", str(f),
                                    "--cores", str(cores)] + (["--whispercpp", str(wcpp)] if wcpp else []),
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=a.timeout)
                res = json.loads(f.read_text(encoding="utf-8")) if f.exists() else \
                    {"variant": v, "error": (r.stderr.strip().splitlines() or ["sin salida"])[-1]}
            except subprocess.TimeoutExpired:
                res = {"variant": v, "error": f"pasó el tiempo límite ({a.timeout:.0f} s)"}
            res["round"] = rnd + 1
            results["runs"].append(res)
            note = res.get("error") or res.get("skipped") or (
                f"{res['speed']}× · WER {res.get('wer', '-')} · {res['peak_mb']} MB" if "speed" in res
                else f"{res.get('ms_per_sentence')} ms/frase · {res.get('peak_mb')} MB")
            print(f"[{rnd + 1}] {v:20} {time.time() - t:6.1f} s  {note}", flush=True)
            (out / "resultados.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"listo: {out / 'resultados.json'}", flush=True)


if __name__ == "__main__":
    main()
