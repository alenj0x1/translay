"""Dobla un video completo sin navegador y exporta <nombre>.es.mp4.

Usa exactamente el pipeline del servidor (streaming ASR → traducción →
diarización → voz clonada → ajuste de duración) y arma la pista doblada:
voz en español en el momento de cada frase + original de fondo atenuado.

Reporta por frase: persona, compresión aplicada y, con la cadencia en vivo,
cuánto después del final de la frase original estaría lista la voz.

    python tools/dub_file.py samples/podcast.mp4 --voice omnivoice
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.eval_pipeline import score_diarization, stream  # noqa: E402
from tools.eval_tts import decode  # noqa: E402
from vt.asr import WhisperASR  # noqa: E402
from vt.audiofx import read_wav, resample, write_wav  # noqa: E402
from vt.dub import Dubber  # noqa: E402
from vt.store import Store  # noqa: E402
from vt.translate import load_translator  # noqa: E402
from vt.tts import TTSClient  # noqa: E402

OUT_SR = 24000
DUCK = 0.14


def produce(media: Path, voice: str, data: Path, translator: str = "opus-big", log=print, asr=None, mt=None, tts=None,
            ref: str = "persona", ref_min_s: float = 2.5):
    """El pipeline del servidor sobre un archivo: reconoce, traduce, identifica a cada persona y dobla cada
    frase. Devuelve (filas [(segmento, frase guardada, info de la voz)], transcripción, audio a 16 kHz, redobladas).
    ref="frase": cada frase de al menos ref_min_s segundos se clona con su propio audio original como referencia (lleva su
    entonación); las más cortas, con la referencia de la persona.
    tools/lab/dub_quality.py lo usa para medir el doblaje."""
    asr = asr or WhisperASR()
    asr.warmup()
    mt = mt or load_translator(translator, tgt="es")
    dub = Dubber(tts or TTSClient(voice), data)
    store = Store(data / "transcripts")
    vid = ("off_" + media.stem.replace(".", "_"))[:60].ljust(8, "_")
    for f in (data / "transcripts").glob(f"{vid}.json"):
        f.unlink()  # cada corrida empieza limpia
    tr = store.open(vid, media.name)
    tr.set_lang("en")  # en inglés (sin detectar el idioma)
    audio16 = decode(media, 16000)
    refs = data / "refs"

    def own_ref(s, seg):
        if ref != "frase" or s.audio is None or len(s.audio) < ref_min_s * 16000:
            return None
        refs.mkdir(parents=True, exist_ok=True)
        f = refs / f"{seg['id']}.wav"
        write_wav(f, s.audio, 16000)
        return str(f), s.text

    segs = stream(asr, audio16)
    texts = mt.translate_many([s.text for s in segs])
    rows, redo = [], set()
    for s, es in zip(segs, texts):
        seg, _ = tr.add_segment(s.start, s.end, s.text, es, mt.name)
        seg["speaker"] = dub.identify(tr, seg, s.audio)
        for fixed in dub.relabel(tr):  # persona corregida: se vuelve a doblar al final
            redo.add(fixed["id"])
        info = dub.synthesize(tr, seg, dub.loudness(s.audio), ref_override=own_ref(s, seg))
        seg["dub"] = info
        rows.append((s, seg, info))
        log(f"[{s.start:6.1f}] P{seg['speaker']} ×{info['rate']:.2f} gpu {info['gpu']:4.1f}s  {es}")
    for i, (s, seg, info) in enumerate(rows):
        if seg["id"] in redo:
            info = dub.synthesize(tr, seg, dub.loudness(s.audio), ref_override=own_ref(s, seg))
            seg["dub"] = info
            rows[i] = (s, seg, info)
    tr.save()
    return rows, tr, audio16, redo


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("media")
    p.add_argument("--voice", default="omnivoice")
    p.add_argument("--data", default=str(ROOT / "data" / "offline"))
    a = p.parse_args()
    media = Path(a.media)
    data = Path(a.data)

    t0 = time.perf_counter()
    rows, tr, audio16, redo = produce(media, a.voice, data)
    segs = [s for s, _, _ in rows]
    labels = [seg["speaker"] for _, seg, _ in rows]
    print(f"frases con persona corregida y redobladas: {len(redo)} ({time.perf_counter() - t0:.0f}s)")
    # pista doblada: cada frase en su momento; si se pisan, la siguiente espera
    orig = decode(media, OUT_SR)
    track = orig * DUCK
    cursor, drift = 0.0, []
    for s, seg, info in rows:
        y, sr = read_wav(data / "audio" / info["file"])
        y = resample(y, sr, OUT_SR)
        start = max(s.start, cursor)
        drift.append(start - s.start)
        i = int(start * OUT_SR)
        end = min(len(track), i + len(y))
        track[i:end] += y[: end - i]
        cursor = start + len(y) / OUT_SR + 0.08
    track = np.clip(track, -1, 1)
    wav = media.with_suffix(".es.wav")
    out = media.with_suffix(".es.mp4")
    write_wav(wav, track, OUT_SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-i", str(wav), "-map", "0:v",
                    "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)], check=True)
    wav.unlink()

    # simulación en vivo: la voz de una frase queda lista cuando termina su
    # reconocimiento (+1.5 s típico) y la síntesis de las frases anteriores
    ready, busy = [], 0.0
    for s, seg, info in rows:
        start = max(s.end + 1.5, busy)
        busy = start + info["gpu"]
        ready.append(busy - s.end)
    rates = [info["rate"] for _, _, info in rows]
    gpu = sum(info["gpu"] for _, _, info in rows)
    dur = len(audio16) / 16000
    msg = (f"\n{out.name}: {len(rows)} frases · personas {len(set(labels))} · GPU voz {gpu:.0f}s "
           f"para {dur:.0f}s de video (RTF {gpu / dur:.2f}) · comprimidas {sum(r > 1.01 for r in rates)} "
           f"(máx ×{max(rates):.2f}) · desfase máx {max(drift):.1f}s · voz lista tras la frase: "
           f"mediana {np.median(ready):.1f}s, máx {max(ready):.1f}s")
    truth_p = media.parent / (media.stem.split("_")[0] + ".truth.json")
    if truth_p.exists():
        truth = json.loads(truth_p.read_text(encoding="utf-8"))
        acc, nf, nr, _ = score_diarization(segs, labels, truth)
        msg += f" · diarización {acc:.0%} ({nf}/{nr})"
    print(msg)


if __name__ == "__main__":
    main()
