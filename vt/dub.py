"""Doblaje: voz en español con la voz de cada persona del video.

Por frase:
  1. huella de voz → persona (SpeakerTracker); su audio mejora su referencia
  2. TTS clonando la referencia de esa persona (o la más parecida)
  3. ajuste de duración al espacio de la frase original (WSOLA, hasta ×1.3)
  4. sonoridad igualada a la voz original
  5. WAV en data/audio/<video>/<frase>.wav — al repetir, suena sincronizado

Las referencias se guardan en data/voices/<video>/ para reabrir el video y
seguir con las mismas voces.
"""

import json
import threading
from pathlib import Path

import numpy as np

from .audiofx import active_rms_db, fade, match_loudness, read_wav, time_stretch, trim_silence, write_wav
from .speakers import SR, SpeakerEmbedder, SpeakerTracker


class VideoVoices:
    """Personas y referencias de un video, persistidas en disco."""

    def __init__(self, root: Path, vid: str, state: dict | None):
        self.dir = root / vid
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tracker = SpeakerTracker(state=state)
        self.short: list[tuple[int, np.ndarray]] = []
        self.meta_path = self.dir / "voices.json"
        self.meta: dict[str, dict] = {}
        if self.meta_path.exists():
            self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            for k, v in self.meta.items():
                wav = self.dir / v["file"]
                if wav.exists():  # la referencia guardada vuelve como un solo fragmento
                    x, _ = read_wav(wav)
                    self.tracker.refs[int(k)] = [(v.get("score", 3.0), x, v.get("text", ""))]

    def add(self, spk: int, audio: np.ndarray, text: str) -> bool:
        if not self.tracker.add_reference(spk, audio, text):
            return False
        x, ref_text = self.tracker.reference(spk)
        version = self.meta.get(str(spk), {}).get("version", 0) + 1
        name = f"spk{spk}_v{version}.wav"  # nombre nuevo: el motor no reutiliza la voz vieja
        write_wav(self.dir / name, x, SR)
        for old in self.dir.glob(f"spk{spk}_v*.wav"):
            if old.name != name:
                old.unlink(missing_ok=True)
        self.meta[str(spk)] = {"file": name, "version": version, "text": ref_text,
                               "score": float(max(r[0] for r in self.tracker.refs[spk]))}
        self.meta_path.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return True

    def ref_for(self, spk: int | None) -> tuple[str | None, str | None]:
        v = self.tracker.voice_for(spk)
        m = self.meta.get(str(v)) if v is not None else None
        if not m:
            return None, None
        return str(self.dir / m["file"]), m["text"]


class Dubber:
    def __init__(self, tts, data_root: Path, max_rate: float = 1.25):
        self.tts = tts
        self.embedder = SpeakerEmbedder()
        self.audio_root = data_root / "audio"
        self.voice_root = data_root / "voices"
        self.max_rate = max_rate
        self._videos: dict[str, VideoVoices] = {}
        self._lock = threading.Lock()

    def voices(self, tr) -> VideoVoices:
        vid = tr.data["id"]
        if vid not in self._videos:
            self._videos[vid] = VideoVoices(self.voice_root, vid, tr.data.get("speakers"))
        return self._videos[vid]

    def identify(self, tr, seg: dict, audio: np.ndarray | None) -> int | None:
        """Asigna persona a la frase (CPU, ~10 ms) y mejora su referencia."""
        with self._lock:
            vv = self.voices(tr)
            if audio is None:
                return seg.get("speaker")
            dur = seg["end"] - seg["start"]
            emb = self.embedder.embed(audio)
            spk, _ = vv.tracker.assign(emb, dur)
            if emb is not None and dur < vv.tracker.min_new_s:
                vv.short.append((seg["id"], emb))  # se revisa cuando las huellas maduren
                vv.short = vv.short[-40:]
            if spk is None:  # demasiado corta para una huella: misma persona que antes
                prev = [x for x in tr.segments if x["start"] < seg["start"] and x.get("speaker") is not None]
                return prev[-1]["speaker"] if prev else None
            if spk is not None and dur >= vv.tracker.min_new_s:
                vv.add(spk, audio, seg["text"])
            tr.data["speakers"] = vv.tracker.state()
            return vv.tracker.resolve(spk)

    def relabel(self, tr) -> list[dict]:
        """Revisa las frases cortas recientes contra las huellas actuales.

        Una persona que empieza con frases cortas ("Good evening.") queda asignada
        a otra hasta que dice algo largo; entonces sus frases cortas se corrigen.
        Devuelve las frases que cambiaron de persona (hay que volver a doblarlas)."""
        with self._lock:
            vv = self.voices(tr)
            tk = vv.tracker
            cents = tk.confirmed()  # las personas solo con frases cortas son provisionales
            if not cents or not vv.short:
                return []
            by_id = {x["id"]: x for x in tr.segments}
            changed = []
            for sid, e in vv.short:
                seg = by_id.get(sid)
                if seg is None:
                    continue
                sims = sorted(((float(c @ e), i) for i, c in cents), reverse=True)
                best, cur = sims[0][1], tk.resolve(seg.get("speaker"))
                cur_sim = next((v for v, i in sims if i == cur), -1.0)
                if best != cur and sims[0][0] - cur_sim > 0.08:
                    seg["speaker"] = best
                    changed.append(seg)
            return changed

    def slot(self, tr, seg: dict) -> float:
        """Espacio disponible: hasta el inicio de la frase siguiente (si ya existe)."""
        nxt = min((x["start"] for x in tr.segments if x["start"] > seg["start"] + 0.05), default=None)
        if nxt is not None:
            return max(0.4, nxt - seg["start"] - 0.08)
        return (seg["end"] - seg["start"]) + 0.3

    def target_duration(self, seg: dict, slot: float) -> float:
        """Duración pedida al motor: la de la frase original (+5 %), sin pasar de un
        ritmo de ~20 caracteres/s en español y sin salirse del espacio disponible."""
        text = seg.get("translation") or ""
        base = (seg["end"] - seg["start"]) * 1.05
        need = len(text) / 20.0
        return round(float(np.clip(max(base, need), 0.5, max(slot, 0.5))), 2)

    def synthesize(self, tr, seg: dict, orig_db: float | None = None, slot: float | None = None) -> dict | None:
        """Genera el audio en español de la frase. Devuelve la info para guardar."""
        text = seg.get("translation")
        if not text:
            return None
        vv = self.voices(tr)
        ref, ref_text = vv.ref_for(seg.get("speaker"))
        slot = slot or self.slot(tr, seg)
        target = self.target_duration(seg, slot)
        y, sr, gpu = self.tts.synth(text, ref=ref, ref_text=ref_text, duration=target,
                                    num_step=16, clean_ref="auto")
        y = trim_silence(y, sr, pad_s=0.03)
        room = slot
        dur = len(y) / sr
        rate = 1.0
        if dur > room * 1.02:  # el español no cupo: se comprime sin cambiar el tono
            rate = min(dur / room, self.max_rate)
            y = time_stretch(y, sr, rate)
        level = float(np.clip(orig_db if orig_db is not None else -20.0, -26.0, -14.0))
        y = fade(match_loudness(y, sr, level), sr)
        out = self.audio_root / tr.data["id"]
        out.mkdir(parents=True, exist_ok=True)
        name = f"{seg['id']}.wav"
        write_wav(out / name, y, sr)
        return {"file": f"{tr.data['id']}/{name}", "dur": round(len(y) / sr, 3), "rate": round(rate, 3),
                "gpu": round(gpu, 2), "engine": self.tts.engine, "voice": seg.get("speaker")}

    @staticmethod
    def loudness(audio: np.ndarray | None) -> float | None:
        return active_rms_db(audio, SR) if audio is not None and len(audio) > SR * 0.3 else None
