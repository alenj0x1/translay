"""Repara referencias de voz recortadas (versiones anteriores las cortaban a 8 s
adivinando el texto: la voz generada "arrastraba" las palabras sobrantes).

Para cada persona con referencia sospechosa (su texto no termina en un signo de
cierre), arma una nueva con frases completas de su propio video y marca la voz del
video para rehacerse: la cola vuelve a doblar sus frases en segundo plano.

    python -m vt.repair_refs            (con el servidor detenido)
    python -m vt.repair_refs --check    (solo lista, sin cambiar nada)
"""

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

from .audiofx import snr_estimate, trim_silence, write_wav
from .processor import decode_audio
from .speakers import MAX_CLIP_S, MAX_FALLBACK_S, SR

ROOT = Path(__file__).resolve().parent.parent / "data"
MAX_REF_S = 9.0
_CLOSED = re.compile(r"[.?!…»\"')]$")


def looks_cut(text: str) -> bool:
    return not _CLOSED.search((text or "").strip())


def media_path(v: dict) -> Path | None:
    src = (v.get("audio") or v.get("media") or "").split("?")[0]
    if src.startswith("/media/yt/"):
        return ROOT / "youtube" / src[10:]
    if src.startswith("/media/lib/"):
        return ROOT / "library" / src[11:]
    return None


def build_reference(audio: np.ndarray, segs: list[dict]) -> tuple[np.ndarray, str, float] | None:
    """Mejores frases completas de la persona (hasta ~9 s en total), sin recortar ninguna."""
    cands = []
    for s in segs:
        x = trim_silence(audio[int(s["start"] * SR):int(s["end"] * SR)], SR)
        dur = len(x) / SR
        if not 1.5 <= dur <= MAX_CLIP_S or not s.get("text", "").strip():
            continue
        score = min(dur, 6.0) * float(np.clip(snr_estimate(x, SR) / 30.0, 0.2, 1.0))
        score *= 1.0 if not looks_cut(s["text"]) else 0.6  # preferir frases que cierran
        cands.append((score, x, s["text"].strip()))
    if not cands:  # último recurso: una frase larga, entera
        for s in segs:
            x = trim_silence(audio[int(s["start"] * SR):int(s["end"] * SR)], SR)
            if MAX_CLIP_S < len(x) / SR <= MAX_FALLBACK_S and s.get("text", "").strip():
                cands.append((1.0, x, s["text"].strip()))
                break
    if not cands:
        return None
    cands.sort(key=lambda c: -c[0])
    chosen, total = [], 0.0
    for c in cands:
        if chosen and total + len(c[1]) / SR > MAX_REF_S:
            continue
        chosen.append(c)
        total += len(c[1]) / SR
        if total >= MAX_REF_S * 0.75:
            break
    gap = np.zeros(int(SR * 0.15), np.float32)
    parts = []
    for c in chosen:
        parts += [c[1], gap]
    return np.concatenate(parts[:-1]), " ".join(c[2] for c in chosen), max(c[0] for c in chosen)


def main(check: bool = False):
    lib = json.loads((ROOT / "library.json").read_text(encoding="utf-8"))["videos"]
    queue_path = ROOT / "queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else {"jobs": [], "paused": False}
    repaired = []
    for meta_path in sorted((ROOT / "voices").glob("*/voices.json")):
        vid = meta_path.parent.name
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        bad = [spk for spk, m in meta.items() if looks_cut(m.get("text", ""))]
        if not bad:
            continue
        title = (lib.get(vid) or {}).get("title", vid)
        print(f"{vid}  {title[:60]}  · voces a rehacer: {', '.join(bad)}")
        if check:
            continue
        src = media_path(lib.get(vid) or {})
        tr_path = ROOT / "transcripts" / f"{vid}.json"
        if not src or not src.exists() or not tr_path.exists():
            print("   sin audio o transcripción en el equipo: se omite")
            continue
        audio = decode_audio(src)
        tr = json.loads(tr_path.read_text(encoding="utf-8"))
        for spk in bad:
            ref = build_reference(audio, [s for s in tr["segments"] if str(s.get("speaker")) == spk])
            folder = meta_path.parent
            for old in folder.glob(f"spk{spk}_v*.wav"):
                old.unlink(missing_ok=True)
            if ref is None:  # sin frases utilizables: la persona usa la voz más parecida
                meta.pop(spk, None)
                print(f"   voz {spk}: sin frases completas; usará la voz más parecida")
                continue
            x, text, score = ref
            version = int(meta[spk].get("version", 0)) + 1
            name = f"spk{spk}_v{version}.wav"
            write_wav(folder / name, x, SR)
            meta[spk] = {"file": name, "version": version, "text": text, "score": float(score)}
            print(f"   voz {spk}: {len(x) / SR:.1f} s · …{text[-60:]!r}")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        # toda la voz del video se rehace (quien no tiene referencia usa la de otra persona)
        n = 0
        for s in tr["segments"]:
            if s.pop("dub", None) is not None:
                n += 1
        tr["updated"] = time.time()
        tr_path.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
        job = next((j for j in queue["jobs"] if j["id"] == vid), None)
        if job is None:
            queue["jobs"].append({"id": vid, "state": "en cola", "added": time.time(), "error": ""})
        else:
            job.update(state="en cola", error="")
        repaired.append((vid, n))
        print(f"   {n} frases a doblar de nuevo (en la cola)")
    if repaired and not check:
        queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"listo: {len(repaired)} videos")


if __name__ == "__main__":
    main(check="--check" in sys.argv)
