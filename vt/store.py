"""Persistencia de transcripciones por video.

Cada video se identifica con una huella de su contenido (calculada en el
navegador). Se guarda un JSON por video con:

* `segments`: frases con tiempo de inicio/fin, texto y traducción.
* `covered`: rangos del video ya procesados (incluye silencios), para no
  volver a transcribirlos al retroceder o reabrir el video.
* `lang`: idioma en que se habla (código de `vt/langs.py`; "en" si no está, como
  antes de los idiomas). Vacío con `detect`: se detecta al empezar a reconocerlo.
* `summary`: el resumen (vt/summarize.py): de qué se trató y sus puntos con su minuto.
* `mode`: "translate" (traducir y doblar) o "transcribe" (solo transcribir, en su
  idioma y sin voz). Lo elige la persona; si falta, un video en el idioma de destino
  solo se transcribe. Cambiar de modo no borra nada: las traducciones quedan guardadas.
* `target`: idioma de la traducción y el doblaje de cada frase (`translation`,
  `tr_model`, `dub`). Las de otros idiomas se guardan en `seg["alt"][idioma]` y vuelven
  al elegir ese idioma en Ajustes (`use_target`): lo que falte se traduce y dobla, lo
  que ya estaba no se rehace. Sin `target` (antes de los idiomas) es español.
"""

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import langs

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_LANG_CODE = re.compile(r"^[a-z]{2,3}$")  # código de Whisper (un idioma detectado puede no estar en el registro)
MODES = ("translate", "transcribe")
_PER_TARGET = ("translation", "tr_model", "dub")  # campos de cada frase que dependen del idioma de destino


def merge_ranges(ranges: list[list[float]], tol: float = 0.25) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 3), round(b, 3)] for a, b in out]


class Transcript:
    ephemeral = False  # LiveTranscript: solo en memoria

    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data
        self._lock = threading.Lock()  # la vista y la cola en segundo plano pueden escribir a la vez
        self.deleted = False  # video eliminado: lo que siga procesándose ya no se guarda

    @property
    def lang(self) -> str:
        return self.data.get("lang") or ("" if self.detecting else langs.DEFAULT_SOURCE)

    @property
    def detecting(self) -> bool:
        """¿Falta detectar el idioma? (se detecta con lo primero que se reconoce)"""
        return bool(self.data.get("detect")) and not self.data.get("lang")

    @property
    def target(self) -> str:
        """Idioma de la traducción y el doblaje guardados en cada frase."""
        return self.data.get("target") or langs.DEFAULT_TARGET

    def use_target(self, code: str) -> bool:
        """Pasa las frases al idioma de destino `code`: lo del idioma anterior se guarda en
        `alt` y lo que ya había en `code` vuelve. True si cambió."""
        if code == self.target or not langs.is_target(code):
            return False
        with self._lock:
            old = self.target
            for s in self.data["segments"]:
                alt = s.setdefault("alt", {})
                kept = {k: s.pop(k) for k in _PER_TARGET if s.get(k) is not None}
                if kept:
                    alt[old] = kept
                back = alt.pop(code, {})
                s.update(translation=back.get("translation"), tr_model=back.get("tr_model"))
                if back.get("dub"):
                    s["dub"] = back["dub"]
                if not alt:
                    s.pop("alt", None)
            self.data["target"] = code
            if self.data.pop("mode_auto", None):
                self.data.pop("mode", None)  # lo decidió el idioma de destino anterior
        return True

    @property
    def mode(self) -> str:
        m = self.data.get("mode")
        if m in MODES:
            return m
        return "transcribe" if self.lang == self.target else "translate"

    @property
    def translates(self) -> bool:
        """¿Se traduce y dobla? No si la persona eligió solo transcribir, si ya está en el
        idioma de destino o si es un idioma que todavía no se traduce."""
        return (self.mode == "translate" and self.lang != self.target and langs.is_source(self.lang)
                and TRANSLATION())

    @property
    def transcribe_only(self) -> bool:
        return not self.translates

    def set_lang(self, lang: str, mode: str | None = None, detected: bool = False) -> bool:
        """Cambia el idioma del video. Lo reconocido en otro idioma no sirve: se borra
        (frases, tramos cubiertos y comentarios) para volver a procesarlo. True si cambió.

        detected: lo detectó Whisper en lo primero que se reconoció; no se borra nada
        (ya se reconoció en ese idioma) y puede ser uno fuera del registro."""
        ok = _LANG_CODE.fullmatch(lang or "") if detected else langs.is_source(lang)
        changed = False
        with self._lock:
            if ok and lang != self.lang:  # detectando, lang es ""
                if not detected:
                    self.data.update(segments=[], covered=[], comments={})
                    self.data.pop("detected", None)  # lo eligió la persona: no se vuelve a revisar
                self.data.update(lang=lang)
                self.data.pop("detect", None)
                changed = True
            if mode in MODES and mode != self.data.get("mode"):
                self.data["mode"] = mode
                changed = True
        return changed

    def set_detected(self, code: str, own: str | None = None, live: bool = False, prob: float | None = None) -> bool:
        """Idioma que detectó Whisper. Si la persona no eligió el modo, lo que está en su
        idioma (`own`, de Ajustes) solo se transcribe. True si cambió algo.
        Solo vale mientras se detecta: la cola y una pestaña pueden detectar a la vez y la
        segunda no debe cambiar un idioma ya decidido."""
        if not self.detecting:
            return False
        changed = self.set_lang(code, detected=True)
        if not TRANSLATION() and "mode" not in self.data:
            self.data["mode"] = "transcribe"  # agregado al solo transcribir: no se pone a traducir al volver
            changed = True
        if changed and live:
            # en vivo se decide con pocos segundos: la cola lo confirma con todo el archivo (Processor._verify_lang)
            self.data["detected"] = {"by": "vivo", "prob": round(float(prob or 0), 3)}
        if code == own and "mode" not in self.data:
            self.data["mode"] = "transcribe"
            self.data["mode_auto"] = True  # por el idioma, no elegido: si el idioma cambia, se vuelve a decidir
            changed = True
        return changed

    @property
    def lang_unconfirmed(self) -> bool:
        """¿El idioma salió de unos segundos en vivo y aún no se confirmó con el archivo completo?"""
        return (self.data.get("detected") or {}).get("by") == "vivo"

    def redetect(self, code: str) -> bool:
        """La cola, con el archivo completo, encontró otro idioma que el detectado en vivo: lo
        reconocido no sirve (se borra) y se rehace en el correcto. True si cambió."""
        with self._lock:
            self.data.pop("detected", None)
            if code == self.lang or not _LANG_CODE.fullmatch(code or ""):
                return False
            self.data.update(lang=code, segments=[], covered=[], comments={})
            if self.data.pop("mode_auto", None):
                self.data.pop("mode", None)  # el modo lo había decidido el idioma equivocado
            return True

    def set_mode(self, mode: str) -> bool:
        """Traducir o solo transcribir. No borra nada: lo reconocido sirve en los dos modos."""
        if mode not in MODES or mode == self.data.get("mode"):
            return False
        with self._lock:
            self.data["mode"] = mode
            self.data.pop("mode_auto", None)
        return True

    @property
    def segments(self) -> list[dict]:
        return self.data["segments"]

    @property
    def covered(self) -> list[list[float]]:
        return self.data["covered"]

    def add_segment(self, start: float, end: float, text: str,
                    translation: str | None, tr_model: str | None = None) -> tuple[dict, list[int]]:
        """Inserta una frase; reemplaza las que se solapan. Devuelve (nueva, ids borrados)."""
        if self.transcribe_only:
            translation, tr_model = None, None
        removed = []
        keep = []
        for s in self.segments:
            overlap = min(end, s["end"]) - max(start, s["start"])
            shorter = max(1e-3, min(end - start, s["end"] - s["start"]))
            if overlap / shorter > 0.5:
                removed.append(s["id"])
            else:
                keep.append(s)
        self.data["next_id"] += 1
        seg = {"id": self.data["next_id"], "start": start, "end": end,
               "text": text, "translation": translation, "tr_model": tr_model}
        keep.append(seg)
        keep.sort(key=lambda s: s["start"])
        self.data["segments"] = keep
        return seg, removed

    def stale(self, tr_model: str) -> list[dict]:
        """Frases sin traducir o traducidas con otro modelo (ninguna si solo se transcribe)."""
        if self.transcribe_only:
            return []
        return [s for s in self.segments if s.get("tr_model") != tr_model]

    def set_translation(self, seg_id: int, translation: str | None, tr_model: str) -> bool:
        for s in self.segments:
            if s["id"] == seg_id:
                s["translation"], s["tr_model"] = translation, tr_model
                return True
        return False

    def add_covered(self, a: float, b: float):
        if b - a > 0.05:
            self.data["covered"] = merge_ranges(self.covered + [[a, b]])

    def save(self):
        if self.deleted:
            return
        with self._lock:
            self.data["updated"] = time.time()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def public(self) -> dict:
        segs = [{k: v for k, v in x.items() if k != "alt"} for x in self.segments]  # otros idiomas: no viajan
        return {"id": self.data["id"], "segments": segs, "covered": self.covered, "target": self.target,
                "comments": self.comments, "lang": self.lang, "mode": self.mode, "translates": self.translates,
                "detecting": self.detecting, "speaker_names": self.data.get("speaker_names") or {},
                "voice_map": self.data.get("voice_map") or {}, "summary": self.data.get("summary")}

    # ------------------------------------------------- comentarios por frase
    @property
    def comments(self) -> dict:
        """id de frase (texto) → [{id, text, created, updated}]"""
        return self.data.setdefault("comments", {})

    def add_comment(self, seg_id: int, text: str) -> dict:
        c = {"id": uuid.uuid4().hex[:8], "text": text.strip()[:4000], "created": time.time(), "updated": None}
        self.comments.setdefault(str(seg_id), []).append(c)
        return c

    def edit_comment(self, seg_id: int, cid: str, text: str):
        for c in self.comments.get(str(seg_id), []):
            if c["id"] == cid:
                c.update(text=text.strip()[:4000], updated=time.time())

    def delete_comment(self, seg_id: int, cid: str):
        key = str(seg_id)
        items = [c for c in self.comments.get(key, []) if c["id"] != cid]
        if items:
            self.comments[key] = items
        else:
            self.comments.pop(key, None)


class LiveTranscript(Transcript):
    """Subtítulos en vivo sobre cualquier ventana (app de escritorio): lo que suena en el equipo se reconoce y
    traduce, pero nada se guarda. No tiene archivo, no entra a ninguna biblioteca ni a la caché del Store, y solo
    conserva las últimas frases (una sesión puede durar horas)."""

    ephemeral = True
    KEEP = 40

    def __init__(self, vid: str):
        super().__init__(None, {"id": vid, "name": "", "segments": [], "covered": [], "next_id": 0,
                                "created": time.time(), "detect": True, "target": langs.target()})

    def add_segment(self, start, end, text, translation, tr_model=None):
        seg, removed = super().add_segment(start, end, text, translation, tr_model)
        self.data["segments"] = self.data["segments"][-self.KEEP:]
        return seg, removed

    def add_covered(self, a: float, b: float):
        super().add_covered(a, b)
        self.data["covered"] = self.data["covered"][-self.KEEP:]

    def save(self):
        pass  # nunca se escribe en disco


# ¿La app traduce? (Ajustes › Uso; vt/app.py lo conecta a la preferencia). Con «Transcribir y resumir»,
# ningún video se traduce ni dobla, aunque lo tuviera elegido: lo hecho se conserva y sigue al volver.
TRANSLATION = lambda: True  # noqa: E731


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Transcript] = {}
        # la cola, las descargas y las pestañas abren a la vez: un solo objeto por video
        self._open_lock = threading.Lock()

    def open(self, vid: str, name: str = "") -> Transcript:
        if not _SAFE_ID.match(vid):
            raise ValueError("id de video inválido")
        t = self._cache.get(vid)
        if t is not None:
            return t
        with self._open_lock:
            if vid in self._cache:
                return self._cache[vid]
            path = self.root / f"{vid}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                # el idioma se detecta con lo primero que se reconoce (o lo elige quien importa)
                data = {"id": vid, "name": name, "segments": [], "covered": [],
                        "next_id": 0, "created": time.time(), "detect": True, "target": langs.target()}
            t = Transcript(path, data)
            t.use_target(langs.target())
            self._cache[vid] = t
            return t

    def retarget(self, code: str) -> list[str]:
        """Cambió el idioma de destino: las transcripciones abiertas pasan a él en memoria (se guardan con el
        próximo cambio; abrir una del disco también la pasa). Las que no están abiertas pasan al abrirlas.
        Devuelve los ids que cambiaron. Sin guardar aquí: con miles de videos abiertos (las tarjetas leen su
        avance) serían miles de archivos escritos de una vez."""
        return [vid for vid, t in list(self._cache.items()) if t.use_target(code)]

    def forget(self, vid: str):
        """Suelta la transcripción abierta (su archivo se movió, p. ej. a la papelera)."""
        with self._open_lock:
            t = self._cache.pop(vid, None)
        if t:
            t.deleted = True

    def delete(self, vid: str):
        if not _SAFE_ID.match(vid):
            return
        with self._open_lock:
            t = self._cache.pop(vid, None)
        if t:
            t.deleted = True
        (self.root / f"{vid}.json").unlink(missing_ok=True)
        (self.root / f"{vid}.screen.json").unlink(missing_ok=True)  # texto en pantalla (vt/screentext.py)
        (self.root / f"{vid}.agent.json").unlink(missing_ok=True)   # conversación con el agente (vt/agentsvc.py)
