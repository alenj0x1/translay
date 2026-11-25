"""Lab: ¿qué tan bien queda el doblaje? Seis números sobre los mismos diálogos, para comparar cambios.

Dos pasos, para medir cada cambio rápido:

  producir   el pipeline del servidor sobre cada muestra (tools/dub_file.py › produce: reconoce, traduce,
             identifica a cada persona y dobla) y la pista que se exporta, mezclada como vt/exporter.py
             (original bajo cada frase con rampas de 120 ms, cada frase sin pisar la anterior). Lento: queda
             guardado en data/labs/dub_quality/<variante>/<muestra>/ y no se repite si ya está.
  medir      sobre lo guardado, segundos.

Lo que se mide (por frase, y su mediana por muestra):

  cer        errores de la voz: Whisper (español) vuelve a transcribir cada frase doblada y se compara con el
             texto pedido, letra por letra (sin mayúsculas, puntuación ni espacios). Lo que más se nota: una
             palabra mal dicha o inventada.
  wer        lo mismo, palabra por palabra.
  sim        parecido de la voz: coseno de huellas WeSpeaker entre la frase doblada y la misma frase original
             de esa persona (la medida interna de Translay; los papers usan WavLM-ECAPA, otra escala).
  id         % de frases dobladas que se parecen más a su persona que a las demás del video.
  mos        naturalidad (UTMOS22, 1–5), si su modelo está en data/labs/models/ (--utmos lo explica). Es un
             modelo entrenado con voces en inglés: sirve para comparar variantes, no como nota absoluta.
  tono       entonación: correlación del contorno de tono (semitonos sobre la mediana de la frase) entre el
             original y el doblaje, ambos llevados a 40 puntos a lo largo de la frase.
  energia    lo mismo con el volumen (dB por trama de 20 ms).
  desfase    cuánto después de su momento empieza la frase doblada en la pista (porque la anterior aún suena).
  desborde   % de frases que siguen sonando más de 0,5 s después de terminada la original.
  compresion cuánto se aceleró la voz para entrar en su lugar (1,00 = nada).
  voz_orig   cuánto de la voz original se oye bajo el doblaje, en dB respecto de la voz doblada, dentro de los tramos
             doblados (más bajo = mejor). Se mide proyectando lo que suena aparte del doblaje sobre el habla limpia de
             la muestra (samples/<diálogo>.mp4: las muestras con ruido son ese habla más el ruido, en la misma línea).
  fondo      a qué nivel queda el fondo (música, ambiente) en esos tramos, en dB respecto del original (0 = intacto).
             Solo en muestras con ruido o música (<diálogo>_music10…).

    python tools/lab/dub_quality.py                         # variante «base», tres diálogos
    python tools/lab/dub_quality.py --samples podcast_music10 --variant base
    python tools/lab/dub_quality.py --only-measure --label base

Variantes: VARIANTS (datos); cada una cambia algo del doblaje y se compara contra «base» en el mismo
material. Las pistas quedan para escucharlas (<muestra>.es.wav).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.eval_tts import decode  # noqa: E402
from vt.audiofx import f0_track, read_wav, resample, write_wav  # noqa: E402

OUT = ROOT / "data" / "labs" / "dub_quality"
MODELS = ROOT / "data" / "labs" / "models"
UTMOS_FILE = MODELS / "utmos22_strong_step7459_v1.pt"
UTMOS_URL = "https://huggingface.co/k2-fsa/TTS_eval_models/resolve/main/mos/utmos22_strong_step7459_v1.pt"
OMNI_PY = ROOT / ".venvs" / "omnivoice" / "Scripts" / "python.exe"
SR = 16000
MIX_SR = 48000
SAMPLES = ["podcast", "panel", "friends"]
# cada variante: lo que cambia en el doblaje (las claves las entiende produce_variant)
MIX_ONLY = {"separate", "duck"}  # opciones que solo cambian la mezcla (reusan las frases de «base»)
VARIANTS = {
    "base": {},  # como hoy: el original bajo cada frase
    "sep-cdx23": {"separate": "cdx23"},
    "ref-frase": {"ref": "frase"},  # cada frase (2,5 s o más) se clona con su propio audio original: lleva su entonación  # el fondo separado (sin voz) entero, sin bajarlo (tools/lab/separate.py)
}


# ------------------------------------------------------------------ producir

def mix_like_export(orig: np.ndarray, clips: list[tuple[float, np.ndarray]], duck: float, sr: int):
    """La pista doblada como la arma vt/exporter.py › _mix: cada frase en su momento sin pisar la anterior y
    el original bajo cada una (rampas de 120 ms). Devuelve (pista, [(inicio, fin) colocados en segundos])."""
    placed, prev_end, out = [], 0, orig.astype(np.float32).copy()
    starts = []
    for start, x in clips:
        a = max(int(start * sr), prev_end)
        starts.append((a, x))
        prev_end = a + len(x)
    ramp = int(0.12 * sr)
    t = np.arange(len(out))
    g = np.ones(len(out), np.float32)
    for a, x in starts:
        lo, hi = max(0, a - ramp), min(len(out), a + len(x) + ramp)
        w = np.clip(np.minimum(t[lo:hi] - (a - ramp), (a + len(x) + ramp) - t[lo:hi]) / ramp, 0, 1)
        g[lo:hi] = np.minimum(g[lo:hi], 1 - (1 - duck) * w)
    out *= g
    for a, x in starts:
        hi = min(len(out), a + len(x))
        if hi > a:
            out[a:hi] += x[: hi - a]
        placed.append((a / sr, (a + len(x)) / sr))
    return np.clip(out, -1, 1), placed


def produce_variant(sample: str, variant: str, opts: dict, models: dict) -> Path:
    """Dobla la muestra (variante «base») o, en una variante que solo cambia la mezcla (MIX_ONLY), toma exactamente
    las mismas frases dobladas de «base» y vuelve a mezclar: así la comparación cambia una sola cosa."""
    from tools.dub_file import produce
    from vt.exporter import DUCK_LEVELS

    media = ROOT / "samples" / f"{sample}.mp4"
    out = OUT / variant / sample
    done = out / "frases.json"
    if done.exists():
        return out
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if set(opts) <= MIX_ONLY and opts:
        base = produce_variant(sample, "base", VARIANTS["base"], models)
        meta = json.loads((base / "frases.json").read_text(encoding="utf-8"))
        for f in meta["frases"]:
            shutil.copyfile(base / f["en"], out / f["en"])
            shutil.copyfile(base / f["dub"], out / f["dub"])
        frases, secs, redone, duration = meta["frases"], meta["seconds"], meta["redone"], meta["duration"]
    else:
        work = out / "datos"
        work.mkdir()
        t0 = time.perf_counter()
        rows, tr, audio16, redo = produce(media, opts.get("voice", "omnivoice"), work, log=lambda *_: None,
                                          ref=opts.get("ref", "persona"), **models)
        secs, redone, duration = time.perf_counter() - t0, len(redo), len(audio16) / SR
        frases = []
        for i, (seg_audio, seg, info) in enumerate(rows):
            orig_wav = out / f"{i:03d}.en.wav"
            write_wav(orig_wav, seg_audio.audio, SR)
            y, ysr = read_wav(work / "audio" / info["file"])
            write_wav(out / f"{i:03d}.es.wav", y, ysr)
            frases.append({"i": i, "start": seg_audio.start, "end": seg_audio.end, "text": seg_audio.text,
                           "es": seg["translation"], "speaker": seg["speaker"], "rate": info["rate"], "gpu": info["gpu"],
                           "en": orig_wav.name, "dub": f"{i:03d}.es.wav"})
        shutil.rmtree(work, ignore_errors=True)  # lo pesado del pipeline ya está copiado
    clips = []
    for f in frases:
        y, ysr = read_wav(out / f["dub"])
        clips.append((f["start"], resample(y.astype(np.float32), ysr, MIX_SR)))
    orig = decode(media, MIX_SR)
    duck, sep = DUCK_LEVELS["bajo"], None
    if opts.get("separate"):
        bg_dir = out / "separado"
        r = subprocess.run([str(OMNI_PY), str(Path(__file__).with_name("separate.py")), "--model", opts["separate"], str(media),
                            str(bg_dir)], capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"la separación falló: {r.stderr.strip()[-400:]}")
        sep = json.loads(r.stdout.strip().splitlines()[-1])
        bg = decode(bg_dir / "fondo.wav", MIX_SR)[: len(orig)]
        orig = np.pad(bg, (0, len(orig) - len(bg)))
        duck = opts.get("duck", 1.0)  # el fondo ya no trae voz: queda entero salvo que la variante diga otra cosa
    bed, _ = mix_like_export(orig, [(st, np.zeros_like(x)) for st, x in clips], duck, MIX_SR)  # lo que suena aparte
    write_wav(out / "fondo_en_mezcla.wav", bed, MIX_SR)
    track, placed = mix_like_export(orig, clips, duck, MIX_SR)
    for f, (a, b) in zip(frases, placed):
        f["placed_start"], f["placed_end"] = round(a, 3), round(b, 3)
    write_wav(out / f"{sample}.es.wav", track, MIX_SR)
    done.write_text(json.dumps({"sample": sample, "variant": variant, "opts": opts, "seconds": round(secs, 1), "separation": sep,
                                "duration": round(duration, 1), "redone": redone, "frases": frases},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ------------------------------------------------------------------ medir

def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def edits(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def contour(x: np.ndarray, sr: int, kind: str, n: int = 40) -> np.ndarray | None:
    """Contorno de la frase llevado a n puntos: tono en semitonos sobre su mediana, o energía en dB."""
    if kind == "tono":
        f = f0_track(x, sr)
        voiced = f > 0
        if voiced.sum() < 8:
            return None
        idx = np.arange(len(f))
        st = 12 * np.log2(f[voiced] / np.median(f[voiced]))
        c = np.interp(idx, idx[voiced], st)[idx[voiced][0]: idx[voiced][-1] + 1]
    else:
        hop = int(sr * 0.02)
        frames = len(x) // hop
        if frames < 8:
            return None
        e = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2) + 1e-10) for i in range(frames)])
        c = 20 * np.log10(e)
        keep = c > c.max() - 40  # sin el silencio del principio y el final
        c = c[np.argmax(keep): len(keep) - np.argmax(keep[::-1])]
    if len(c) < 8:
        return None
    return np.interp(np.linspace(0, len(c) - 1, n), np.arange(len(c)), c)


def corr(a, b) -> float | None:
    if a is None or b is None or a.std() < 1e-6 or b.std() < 1e-6:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def utmos(paths: list[Path]) -> dict[str, float]:
    if not UTMOS_FILE.exists() or not OMNI_PY.exists():
        return {}
    script = Path(__file__).with_name("utmos_score.py")
    r = subprocess.run([str(OMNI_PY), str(script), str(UTMOS_FILE), *map(str, paths)], capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        print(f"  UTMOS falló: {r.stderr.strip()[-300:]}", flush=True)
        return {}
    return json.loads(r.stdout)


def measure(out: Path, asr, emb) -> dict:
    meta = json.loads((out / "frases.json").read_text(encoding="utf-8"))
    frases = meta["frases"]
    # huellas de voz: cada frase original y cada doblada
    en_emb, es_emb = {}, {}
    for f in frases:
        x, sr = read_wav(out / f["en"])
        y, ysr = read_wav(out / f["dub"])
        en_emb[f["i"]] = emb.embed(resample(x.astype(np.float32), sr, SR))
        es_emb[f["i"]] = emb.embed(resample(y.astype(np.float32), ysr, SR))
    by_spk = {}
    for f in frases:
        if en_emb[f["i"]] is not None:
            by_spk.setdefault(f["speaker"], []).append(en_emb[f["i"]])
    centers = {k: np.mean(v, axis=0) for k, v in by_spk.items()}
    mos = utmos([out / f["dub"] for f in frases])
    for f in frases:
        y, ysr = read_wav(out / f["dub"])
        y16 = resample(y.astype(np.float32), ysr, SR)
        x, sr = read_wav(out / f["en"])
        x16 = resample(x.astype(np.float32), sr, SR)
        heard = asr_text(asr, y16)
        want, got = norm_text(f["es"]), norm_text(heard)
        f["heard"] = heard
        f["cer"] = edits(want.replace(" ", ""), got.replace(" ", "")) / max(1, len(want.replace(" ", "")))
        f["wer"] = edits(want.split(), got.split()) / max(1, len(want.split()))
        a, b = en_emb[f["i"]], es_emb[f["i"]]
        f["sim"] = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))) if a is not None and b is not None else None
        if b is not None and len(centers) > 1:
            sims = {k: float(np.dot(b, c) / (np.linalg.norm(b) * np.linalg.norm(c))) for k, c in centers.items()}
            f["id"] = max(sims, key=sims.get) == f["speaker"]
        f["tono"] = corr(contour(x16, SR, "tono"), contour(y16, SR, "tono"))
        f["energia"] = corr(contour(x16, SR, "energia"), contour(y16, SR, "energia"))
        f["desfase"] = round(f["placed_start"] - f["start"], 3)
        f["desborde"] = (f["placed_end"] - f["end"]) > 0.5
        f["mos"] = mos.get(str(out / f["dub"]))
    (out / "medidas.json").write_text(json.dumps(frases, ensure_ascii=False, indent=1), encoding="utf-8")

    def med(k):
        v = [f[k] for f in frases if f.get(k) is not None]
        return round(float(np.median(v)), 3) if v else None

    ids = [f["id"] for f in frases if "id" in f]
    leak, bed = leak_and_bed(out, meta)
    return {"muestra": meta["sample"], "variante": meta["variant"], "frases": len(frases), "cer": med("cer"),
            "cer_media": round(float(np.mean([f["cer"] for f in frases])), 3), "wer": med("wer"), "sim": med("sim"),
            "id": round(sum(ids) / len(ids), 3) if ids else None, "mos": med("mos"), "tono": med("tono"),
            "energia": med("energia"), "desfase": med("desfase"),
            "desborde": round(sum(f["desborde"] for f in frases) / len(frases), 3), "compresion": med("rate"),
            "rtf_voz": round(sum(f["gpu"] for f in frases) / meta["duration"], 3), "voz_orig": leak, "fondo": bed,
            "sep_rtf": (meta.get("separation") or {}).get("rtf")}


def leak_and_bed(out: Path, meta: dict) -> tuple[float | None, float | None]:
    """voz_orig y fondo (ver arriba), dentro de los tramos doblados. None si la muestra no tiene habla limpia."""
    sample = meta["sample"]
    clean_name = sample.split("_")[0]
    clean_p = ROOT / "samples" / f"{clean_name}.mp4"
    bed_p = out / "fondo_en_mezcla.wav"
    if not clean_p.exists() or not bed_p.exists():
        return None, None
    speech = decode(clean_p, MIX_SR)
    orig = decode(ROOT / "samples" / f"{sample}.mp4", MIX_SR)
    bed, _ = read_wav(bed_p)
    n = min(len(speech), len(orig), len(bed))
    speech, orig, bed = speech[:n], orig[:n], bed[:n]
    mask = np.zeros(n, bool)
    dub_energy = []
    for f in meta["frases"]:
        a, b = int(f["placed_start"] * MIX_SR), min(n, int(f["placed_end"] * MIX_SR))
        mask[a:b] = True
        y, ysr = read_wav(out / f["dub"])
        dub_energy.append(np.mean(resample(y.astype(np.float32), ysr, MIX_SR) ** 2))
    if not mask.any():
        return None, None
    s, r = speech[mask], bed[mask]
    alpha = float(np.dot(r, s) / (np.dot(s, s) + 1e-12))  # cuánto del habla original sigue en lo que suena aparte
    leak = 20 * np.log10(abs(alpha) * np.sqrt(np.mean(s ** 2)) / np.sqrt(np.mean(dub_energy)) + 1e-9)
    noise = (orig - speech)[mask]  # el fondo de la muestra (ruido o música)
    fondo = None
    if np.mean(noise ** 2) > 1e-6 * np.mean(s ** 2) and clean_name != sample:
        beta = float(np.dot(r, noise) / (np.dot(noise, noise) + 1e-12))
        fondo = round(20 * np.log10(abs(beta) + 1e-9), 1)
    return round(float(leak), 1), fondo


def asr_text(asr, audio: np.ndarray) -> str:
    """Whisper en español sobre una frase completa (sin streaming)."""
    segs, _ = asr.model.transcribe(audio, language="es", beam_size=5, vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs)


def gpu_busy() -> int | None:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", nargs="+", default=SAMPLES + [f"{x}_music10" for x in SAMPLES])
    ap.add_argument("--variant", nargs="+", default=["base"], choices=list(VARIANTS))
    ap.add_argument("--only-measure", action="store_true", help="no producir: medir lo ya guardado")
    ap.add_argument("--label", default="", help="nombre del resumen (data/labs/dub_quality/resumen-<label>.json)")
    ap.add_argument("--utmos", action="store_true", help="dice cómo tener el modelo de naturalidad y sale")
    a = ap.parse_args()
    if a.utmos:
        print(f"UTMOS22 (Apache-2.0, 411 MB): {UTMOS_URL}\n  guardarlo en {UTMOS_FILE}")
        return
    busy = gpu_busy()
    if busy is not None and busy > 20:
        sys.exit(f"la gráfica está ocupada ({busy} %): espera a que se libere para medir")
    missing = [s for s in a.samples if not (ROOT / "samples" / f"{s}.mp4").exists()]
    if missing:
        sys.exit(f"faltan muestras: {missing} (tools/make_dialogue.py las genera)")

    from vt.asr import WhisperASR
    from vt.speakers import SpeakerEmbedder

    asr = WhisperASR()
    models = {"asr": asr}
    if not a.only_measure:
        from vt.translate import load_translator
        from vt.tts import TTSClient

        models["mt"] = load_translator("opus-big", tgt="es")
        models["tts"] = TTSClient("omnivoice")
        try:
            for v in a.variant:
                for s in a.samples:
                    print(f"producir {v}/{s}", flush=True)
                    produce_variant(s, v, VARIANTS[v], models)
        finally:
            models.pop("tts").close()  # la voz deja la gráfica libre para medir
            models.pop("mt").unload()
    asr.warmup()
    emb = SpeakerEmbedder()
    rows = []
    for v in a.variant:
        for s in a.samples:
            out = OUT / v / s
            if not (out / "frases.json").exists():
                print(f"  sin producir: {v}/{s}")
                continue
            r = measure(out, asr, emb)
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    if not UTMOS_FILE.exists():
        print("(sin naturalidad: falta el modelo UTMOS; --utmos dice cómo tenerlo)")
    summary = OUT / f"resumen-{a.label or time.strftime('%Y%m%d-%H%M%S')}.json"
    summary.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["frases", "cer", "wer", "sim", "id", "mos", "tono", "energia", "desfase", "desborde", "compresion", "rtf_voz",
            "voz_orig", "fondo", "sep_rtf"]
    print("\n" + "variante/muestra".ljust(24) + "".join(c.rjust(11) for c in cols))
    for r in rows:
        print(f"{r['variante']}/{r['muestra']}".ljust(24) + "".join(str(r.get(c, "")).rjust(11) for c in cols))
    print(f"resumen: {summary}")


if __name__ == "__main__":
    main()
