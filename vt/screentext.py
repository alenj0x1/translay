"""Texto en pantalla: lo que está escrito en el video (títulos, letreros, diapositivas), traducido y
puesto encima en el mismo lugar.

Por video, en la CPU y en paralelo con el reconocimiento de voz (la GPU solo traduce):

1. Muestreo: un cuadro cada STEP_S. Si el cuadro casi no cambió (miniatura en gris, por bloques)
   no se vuelve a leer: lo que estaba sigue en pantalla.
2. Lectura (vt/ocr.py): renglones con su caja. Un renglón en el mismo lugar y con la misma imagen
   que en el cuadro anterior no se vuelve a leer (en una grabación de pantalla casi todo queda quieto).
3. Bloques (`blocks`): renglones vecinos se juntan en párrafos; cada renglón tiene su tipo
   (vt/textkind.py) y en un bloque de código lo dudoso también es código. Solo el texto común y
   los comentarios se traducen; el código, los comandos y los enlaces quedan como están.
4. Seguimiento (`Tracker`): el mismo bloque en cuadros seguidos es un solo elemento con su inicio
   y su fin. Lo que aparece en un solo cuadro y con poca confianza se descarta (un parpadeo).
5. Color: el del fondo (el borde alrededor del bloque) y el del texto, para que la caja que tapa
   el original se vea como parte del video.

Se guarda en `transcripts/<video>.screen.json` (aparte de la transcripción: se escribe desde otro
hilo) y se manda a las pestañas por tandas, mientras avanza.
"""

from __future__ import annotations

import json
import re
import threading
import time
from difflib import SequenceMatcher
from functools import partial
from pathlib import Path

import numpy as np

from . import events, textkind

STEP_S = 0.5            # un cuadro cada medio segundo
MIN_CONF = 0.75         # renglón que se acepta
KEEP_CONF = 0.9         # visto una sola vez: se guarda solo con esta confianza
MIN_H = 0.02            # alto mínimo de un renglón (fracción del alto del video): lo menor no se lee
FLUSH_S = 15.0          # cada cuánto tiempo de video se traducen y mandan los elementos cerrados
THUMB = (192, 108)
CHANGE = 6.0            # diferencia media (0–255) en algún bloque de 8×8 de la miniatura
VERSION = 1
GROW = 1.6              # una caja de un renglón crece hasta esto (el español suele ser más largo)


# ------------------------------------------------------------------ bloques
def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _xyxy(b):
    return (b[0], b[1], b[0] + b[2], b[1] + b[3])


def _row_merge(lines: list[dict]) -> list[dict]:
    """Pedazos del mismo renglón (el detector a veces corta en un espacio grande) y del mismo tipo."""
    lines = sorted(lines, key=lambda x: (x["box"][1], x["box"][0]))
    out: list[dict] = []
    for ln in sorted(lines, key=lambda x: x["box"][0]):
        x0, y0, x1, y1 = ln["box"]
        h = y1 - y0
        for o in out:
            a0, b0, a1, b1 = o["box"]
            ov = min(y1, b1) - max(y0, b0)
            # mismo tipo, misma fila, cerca y del mismo alto (la barra lateral chica no se pega al título)
            if o["kind"] == ln["kind"] and ov > 0.6 * min(h, b1 - b0) and 0 <= x0 - a1 < 0.8 * h \
                    and max(h, b1 - b0) < 1.4 * min(h, b1 - b0):
                o["text"] += " " + ln["text"]
                o["box"] = (a0, min(y0, b0), x1, max(y1, b1))
                o["conf"] = min(o["conf"], ln["conf"])
                break
        else:
            out.append(dict(ln))
    return out


_INLINE = re.compile(r"\s(?://|#|--|/\*)\s")


def _split_comment(ln: dict) -> list[dict]:
    """`return data  # parsed settings`: el código y su comentario, cada uno con su parte de la caja
    (por la posición de las letras: en el código casi siempre la letra es monoespaciada)."""
    m = _INLINE.search(ln["text"])
    if not m or ln["kind"] not in ("code", "command"):
        return [ln]
    code, comment = ln["text"][:m.start()].rstrip(), ln["text"][m.start():].strip()
    if not code or textkind.kind(comment) != "comment":
        return [ln]
    x0, y0, x1, y1 = ln["box"]
    # el OCR junta los espacios dobles: medio carácter más allá para no tapar la última letra del código
    ch = (x1 - x0) / len(ln["text"])
    cut = min(x1 - ch, x0 + ch * (m.start() + 1.5))
    return [dict(ln, text=code, box=(x0, y0, cut, y1)),
            dict(ln, text=comment, kind="comment", box=(cut, y0, x1, y1))]


def _terminal(lines: list[dict]):
    """Contexto del cuadro: si hay una terminal (un prompt, salida de `ls -l`…), lo corto que está en su
    zona y con su misma letra también es terminal: en un listado, `is`, `for` o `stuff` son archivos, no
    palabras. Una frase (con su punto) o un texto de otro tamaño, no."""
    term = [ln for ln in lines if ln["kind"] in ("code", "command") and textkind.shell(ln["text"])]
    if not term:
        return
    hs = sorted(t["box"][3] - t["box"][1] for t in term)
    h = hs[len(hs) // 2]
    left = min(t["box"][0] for t in term) - 2 * h
    right = max(t["box"][2] for t in term) + 2 * h
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        words = ln["text"].split()
        if ln["kind"] == "text" and len(words) <= 6 and not ln["text"].rstrip().endswith((".", "!", "?")) \
                and abs((y1 - y0) - h) < 0.25 * h and x0 >= left and x1 <= right:
            ln["kind"] = "code"


def blocks(lines: list[dict], W: int, H: int) -> list[dict]:
    """Renglones leídos (px) → bloques: {box (x, y, w, h en fracción), px, text, kind, conf, lines}."""
    good = []
    # cuántos textos chicos hay en el cuadro: muchos es una pantalla (su letra chica es interfaz); pocos,
    # una animación o una diapositiva (su letra chica es contenido)
    small = sum(1 for ln in lines if (ln["box"][3] - ln["box"][1]) / H < textkind.UI_H)
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        if ln["conf"] < MIN_CONF or (y1 - y0) < MIN_H * H:
            continue
        k = textkind.kind(ln["text"], {"h": (y1 - y0) / H, "y": y0 / H, "conf": ln["conf"], "small": small})
        if k != "noise":
            good.append(dict(ln, kind=k))
    _terminal(good)
    good = _row_merge(good)
    good.sort(key=lambda x: (x["box"][1], x["box"][0]))
    # grupos por cercanía (sin mirar el tipo), para decidir el tipo con su contexto
    groups: list[list[dict]] = []
    for ln in good:
        x0, y0, x1, y1 = ln["box"]
        h = y1 - y0
        best = None
        for g in groups:
            last = g[-1]
            a0, b0, a1, b1 = last["box"]
            lh = b1 - b0
            gap = y0 - b1
            if gap > 0.8 * max(h, lh) or gap < -0.5 * min(h, lh) or max(h, lh) > 1.5 * min(h, lh):
                continue
            left = abs(x0 - a0) < 1.2 * max(h, lh)
            center = abs((x0 + x1) - (a0 + a1)) / 2 < 1.5 * max(h, lh)
            overlap = min(x1, a1) - max(x0, a0) > 0.5 * min(x1 - x0, a1 - a0)
            if left or center or overlap:
                best = g
                break
        if best is None:
            groups.append([ln])
        else:
            best.append(ln)
    out = []
    for g in groups:
        kinds = textkind.settle([ln["kind"] for ln in g])
        run: list[dict] = []
        for ln, k in zip(g, kinds):
            ln["kind"] = k
            parts = _split_comment(ln)
            ln = parts[0]  # un comentario al final de una línea de código es su propio bloque
            out.extend(_block([p], W, H) for p in parts[1:])
            k = ln["kind"]
            if run and (run[-1]["kind"] != k or k == "link"):
                out.append(_block(run, W, H))
                run = []
            run.append(ln)
        if run:
            out.append(_block(run, W, H))
    return out


def _block(run: list[dict], W: int, H: int) -> dict:
    x0 = min(r["box"][0] for r in run)
    y0 = min(r["box"][1] for r in run)
    x1 = max(r["box"][2] for r in run)
    y1 = max(r["box"][3] for r in run)
    k = run[0]["kind"]
    text = textkind.joiner(k).join(r["text"] for r in run)
    # alineado como el original: varios renglones que empiezan en el mismo x (y terminan en distinto)
    # van a la izquierda; un comentario de código, siempre
    h = float(np.mean([r["box"][3] - r["box"][1] for r in run]))
    lefts, rights = [r["box"][0] for r in run], [r["box"][2] for r in run]
    left = k == "comment" or (len(run) > 1 and max(lefts) - min(lefts) < 0.5 * h
                              and max(rights) - min(rights) > 0.5 * h)
    return {"box": (x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H), "px": (x0, y0, x1, y1), "text": text,
            "kind": k, "conf": float(np.mean([r["conf"] for r in run])), "lines": len(run),
            "align": "left" if left else "center"}


def colors(frame: np.ndarray, px) -> tuple[str, str]:
    """(fondo, texto) en #rrggbb: el fondo es el borde alrededor del bloque; el texto, lo de adentro
    que más se aleja del fondo. frame en BGR."""
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in px)
    m = 3
    a0, b0, a1, b1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
    outer = frame[b0:b1, a0:a1].reshape(-1, 3).astype(np.float32)
    ring = np.ones((b1 - b0, a1 - a0), bool)
    ring[max(0, y0 - b0):max(0, y1 - b0), max(0, x0 - a0):max(0, x1 - a0)] = False
    edge = outer[ring.reshape(-1)] if ring.any() else outer
    bg = np.median(edge, axis=0) if len(edge) else np.array([0, 0, 0], np.float32)
    inner = frame[max(0, y0):min(H, y1), max(0, x0):min(W, x1)].reshape(-1, 3).astype(np.float32)
    if len(inner):
        d = np.abs(inner - bg).sum(1)
        far = inner[d >= np.quantile(d, 0.85)]
        fg = np.median(far, axis=0) if len(far) else 255 - bg
    else:
        fg = 255 - bg
    if np.abs(fg - bg).sum() < 120:  # sin contraste claro: texto blanco o negro según el fondo
        fg = np.array([20, 20, 20]) if bg.mean() > 140 else np.array([245, 245, 245])

    def hexc(c):
        b, g, r = (int(np.clip(v, 0, 255)) for v in c)
        return f"#{r:02x}{g:02x}{b:02x}"
    return hexc(bg), hexc(fg)


# --------------------------------------------------------------- seguimiento
def _same_text(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _grows(a: dict, b: dict) -> bool:
    """¿Es el mismo texto apareciendo letra por letra? (tipografía cinética, máquina de escribir): uno es el
    comienzo del otro, en el mismo renglón, del mismo alto y alineados por la izquierda, el centro o la derecha."""
    ta, tb = _norm(a["text"]), _norm(b["text"])
    if not ta or not tb or ta == tb:
        return False
    short, long_ = sorted((ta, tb), key=len)
    if not long_.startswith(short) and not long_.endswith(short):
        return False
    ax, ay, aw, ah = a["box"]
    bx, by, bw, bh = b["box"]
    h = max(ah / max(1, a.get("lines") or 1), bh / max(1, b.get("lines") or 1))
    if abs((ay + ah / 2) - (by + bh / 2)) > 0.6 * h or max(ah, bh) > 1.6 * min(ah, bh):
        return False
    tol = 0.8 * h
    return abs(ax - bx) < tol or abs((ax + aw / 2) - (bx + bw / 2)) < tol or abs((ax + aw) - (bx + bw)) < tol


class Tracker:
    def __init__(self, step: float = STEP_S):
        self.step = step
        self.active: list[dict] = []
        self.done: list[dict] = []

    def _close(self, it: dict):
        letters = sum(ch.isalpha() for ch in it["text"])
        # un parpadeo: visto una vez y con poca confianza, o un trozo de 1–3 letras visto una sola vez
        if it["hits"] >= 2 or (it["conf"] >= KEEP_CONF and letters > 3):
            it["end"] = round(it["last"] + self.step / 2, 2)
            self.done.append(it)

    def extend(self, t: float):
        """El cuadro no cambió: todo lo que estaba sigue en pantalla."""
        for it in self.active:
            it["last"] = t
            it["hits"] += 1

    def update(self, t: float, found: list[dict]):
        free = list(self.active)
        nxt = []
        for b in found:
            match, grow = None, False
            for it in free:
                if it["kind"] == b["kind"] and _iou(_xyxy(it["box"]), _xyxy(b["box"])) > 0.4 and _same_text(it["text"], b["text"]) >= 0.6:
                    match = it
                    break
            if match is None:
                match = next((it for it in free if _grows(it, b)), None)
                grow = match is not None
            elif _grows(match, b):
                grow = True  # se parece y además es el comienzo del otro: también va creciendo
            if match:
                free.remove(match)
                match["last"] = t
                match["hits"] += 1
                if grow:
                    # texto que aparece (o se borra) letra por letra: un solo elemento con el texto completo
                    if len(_norm(b["text"])) > len(_norm(match["text"])):
                        match.update({k: b[k] for k in ("text", "conf", "box", "lines", "align", "kind", "bg", "fg")
                                      if k in b})
                elif b["conf"] > match["conf"]:  # la mejor lectura se queda (texto, caja y colores)
                    match.update({k: b[k] for k in ("text", "conf", "box", "lines", "align") if k in b})
                    if "bg" in b:
                        match.update(bg=b["bg"], fg=b["fg"])
                nxt.append(match)
            else:
                nxt.append({**{k: v for k, v in b.items() if k != "px"}, "start": round(max(0.0, t - self.step / 2), 2),
                            "last": t, "hits": 1})
        for it in free:
            self._close(it)
        self.active = nxt

    def close_all(self, t: float) -> list[dict]:
        for it in self.active:
            self._close(it)
        self.active = []
        return self.take()

    def take(self) -> list[dict]:
        out, self.done = self.done, []
        for it in out:
            it.pop("hits", None)
            it.pop("last", None)
        return out


# ------------------------------------------------------------------ video
def _changed(a: np.ndarray, b: np.ndarray) -> bool:
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.float32)
    h, w = (d.shape[0] // 8) * 8, (d.shape[1] // 8) * 8
    blk = d[:h, :w].reshape(h // 8, 8, w // 8, 8).mean((1, 3))
    return bool(blk.max() > CHANGE)


def _sig(frame: np.ndarray, box) -> np.ndarray:
    from .ocr import resize

    x0, y0, x1, y1 = (int(v) for v in box[:4])
    crop = frame[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)].mean(2, keepdims=True)
    return resize(crop, 48, 12)[:, :, 0]


def scan(path: Path, ocr, start: float = 0.0, step: float = STEP_S, stop=lambda: False, emit=lambda items, t: None):
    """Lee el texto de todo el video desde `start`. emit(elementos cerrados, hasta dónde se leyó) cada
    FLUSH_S de video y al final. Devuelve False si se pidió parar."""
    import av

    tracker = Tracker(step)
    prev_thumb = None
    prev_lines: list[tuple] = []  # (caja px, firma, texto, confianza) del último cuadro leído
    flushed = start
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        if start > 0:
            c.seek(int(start / s.time_base), stream=s)
        nxt = start
        t = start
        for frame in c.decode(s):
            if frame.time is None or frame.time < nxt - 1e-3:
                continue
            t = float(frame.time)
            nxt = t + step
            if stop():
                return False
            thumb = frame.reformat(*THUMB, format="gray").to_ndarray()
            if prev_thumb is not None and not _changed(thumb, prev_thumb):
                tracker.extend(t)
            else:
                prev_thumb = thumb
                W, H = frame.width, frame.height
                sc = 960 / max(W, H)
                w, h = max(32, int(round(W * sc / 32)) * 32), max(32, int(round(H * sc / 32)) * 32)
                big = frame.to_ndarray(format="bgr24")
                small = frame.reformat(w, h, format="bgr24").to_ndarray()
                boxes = ocr.detect(small, w / W)
                lines, todo, sigs = [], [], []
                for bx in boxes:
                    if bx[3] - bx[1] < MIN_H * H:
                        continue
                    sg = _sig(big, bx)
                    sigs.append(sg)
                    hit = next((p for p in prev_lines if _iou(p[0], bx) > 0.8 and np.abs(p[1] - sg).mean() < 6), None)
                    if hit:
                        lines.append({"box": bx[:4], "text": hit[2], "conf": hit[3], "_sig": sg})
                    else:
                        todo.append((bx, sg))
                if todo:
                    crops = [big[int(b[1]):max(int(b[1]) + 1, int(np.ceil(b[3]))),
                                 int(b[0]):max(int(b[0]) + 1, int(np.ceil(b[2])))] for b, _ in todo]
                    for (bx, sg), (text, conf) in zip(todo, ocr.recognize(crops)):
                        if text:
                            lines.append({"box": bx[:4], "text": text, "conf": conf, "_sig": sg})
                prev_lines = [(ln["box"], ln.pop("_sig"), ln["text"], ln["conf"]) for ln in lines]
                found = blocks(lines, W, H)
                for b in found:
                    b["bg"], b["fg"] = colors(big, b["px"])
                tracker.update(t, found)
            if t - flushed >= FLUSH_S:
                items = tracker.take()
                flushed = t
                emit(items, t)
    emit(tracker.close_all(t + step), None)
    return True


# ------------------------------------------------------------- en la app
def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


class ScreenText:
    """Cola propia: un video a la vez, el que se está viendo primero."""

    def __init__(self, store, library, res, gpu, translator, prefs, notify, media, vaults=None, threads: int = 2):
        self.store, self.library, self.res, self.gpu = store, library, res, gpu
        self.translator, self.prefs, self.notify, self.media = translator, prefs, notify, media
        self.vaults, self.threads = vaults, threads
        self.jobs: dict[str, dict] = {}   # video → {state, pct}
        self._order: list[str] = []
        self.focus: str | None = None
        self._ocr = None
        self._cond = threading.Condition()
        threading.Thread(target=self._loop, daemon=True, name="texto-en-pantalla").start()

    # ------------------------------------------------------------- API
    def enabled(self) -> bool:
        return bool(self.prefs.values.get("screen_text", True)) and self.prefs.translating

    def path(self, vid: str) -> Path:
        return self.store.open(vid).path.with_name(f"{vid}.screen.json")

    def load(self, vid: str) -> dict | None:
        try:
            p = self.path(vid)
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except (OSError, ValueError):
            return None

    def public(self, vid: str) -> dict | None:
        """Para la vista: los elementos y si falta leer."""
        d = self.load(vid)
        j = self.jobs.get(vid)
        if d is None and j is None:
            return None
        from .videocontext import elements

        return {"items": (d or {}).get("items", []), "elements": elements(d), "done": bool(d and d.get("done")),
                "state": j["state"] if j else None}

    def request(self, vid: str, front: bool = False):
        """Un video con imagen que se procesa o se mira: se lee su texto si aún no se hizo."""
        if not self.enabled():
            return
        v = self.library.data["videos"].get(vid) or {}
        if v.get("audio_only") or not v.get("media"):
            return
        d = self.load(vid)
        if d and d.get("done") and d.get("v") == VERSION:
            return
        with self._cond:
            if front:
                self.focus = vid
            if vid in self.jobs and vid in self._order:
                if front:
                    self._order.remove(vid)
                    self._order.insert(0, vid)
                return
            if vid in self.jobs:
                return
            self.jobs[vid] = {"state": "en cola", "pct": 0}
            self._order.insert(0, vid) if front else self._order.append(vid)
            self._cond.notify_all()

    def forget(self, vid: str):
        with self._cond:
            if vid in self._order:
                self._order.remove(vid)
                self.jobs.pop(vid, None)
            elif vid in self.jobs:
                self.jobs[vid]["cancel"] = True

    # ------------------------------------------------------------ bucle
    def _loop(self):
        while True:
            with self._cond:
                while not self._order:
                    if not self._cond.wait(timeout=60 if self._ocr else None) and self._ocr and not self._order:
                        self._ocr = None  # sin trabajo: los modelos dejan la memoria
                vid = self._order.pop(0)
                job = self.jobs.get(vid)
            if job is None:
                continue
            try:
                self._run(vid, job)
            except Exception:  # noqa: BLE001 — un video que falla no frena a los demás
                import traceback

                traceback.print_exc()
            finally:
                with self._cond:
                    self.jobs.pop(vid, None)

    def _engine(self):
        if self._ocr is None:
            from . import ocr

            if not ocr.have():
                ocr.download()
            self._ocr = ocr.OCR(self.threads)
        return self._ocr

    def _translate(self, vid: str, items: list[dict]):
        tr = self.store.open(vid)
        todo = [it for it in items if textkind.translatable(it["kind"])]
        if not todo or not tr.translates:
            return
        vault = self.vaults.of(vid) if self.vaults else None
        # un comentario se traduce sin su marca (`#`, `//`…): el traductor no la conoce y la vuelve «⁇»
        parts = {it["id"]: textkind.comment_parts(it["text"]) if it["kind"] == "comment" else ("", it["text"], "")
                 for it in todo}
        texts = sorted({p[1] for p in parts.values() if p[1]})
        fn = partial(self.translator.translate_many, texts, glossary=vault.glossary if vault else None, src=tr.lang)
        got = dict(zip(texts, self.gpu.submit(self.res.run, ("mt",), fn).result()))
        for it in todo:
            pre, body, post = parts[it["id"]]
            es = (got.get(body) or "").strip()
            # ya estaba en español (o el traductor lo dejó igual): no se tapa nada
            if es and _norm(es) != _norm(body):
                it["translation"] = f"{pre}{es}{post}"

    def _save(self, vid: str, data: dict):
        p = self.path(vid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)

    def _run(self, vid: str, job: dict):
        tr = self.store.open(vid)
        if tr.detecting or not tr.translates:
            return  # sin idioma todavía (se pide de nuevo al detectarlo) o solo se transcribe
        src = self.media(vid)
        if src is None:
            return
        data = self.load(vid) or {}
        if data.get("v") != VERSION:
            data = {"v": VERSION, "items": [], "upto": 0.0, "done": False}
        job["state"] = "leyendo"
        eng = self._engine()
        dur = float((self.library.data["videos"].get(vid) or {}).get("duration") or 0)
        next_id = [max((it["id"] for it in data["items"]), default=-1) + 1]
        began = time.perf_counter()

        def emit(items, upto):
            for it in items:
                it["id"] = next_id[0]
                next_id[0] += 1
                it["conf"] = round(it["conf"], 3)
                it["box"] = [round(v, 4) for v in it["box"]]
            self._translate(vid, items)
            data["items"].extend(items)
            if upto is None:
                data["done"] = True
            else:
                data["upto"] = round(upto, 2)
                job["pct"] = int(100 * upto / dur) if dur else 0
            self._save(vid, data)
            from .videocontext import elements

            self.notify({"type": "bg", "video": vid, "msg": {"type": "screen_text", "items": items,
                                                             "elements": elements(data), "done": data["done"]}})

        ok = scan(src, eng, start=data["upto"], stop=lambda: job.get("cancel") or not self.enabled(), emit=emit)
        if ok:
            n = sum(1 for it in data["items"] if it.get("translation"))
            print(f"[texto] {vid}: {len(data['items'])} elementos, {n} traducidos "
                  f"en {time.perf_counter() - began:.0f} s", flush=True)
            v = self.vaults.of(vid) if self.vaults else None
            events.emit("texto.listo", v.id if v else None, video=vid, items=len(data["items"]), translated=n)


# ------------------------------------------------------------ al exportar
def _ass_color(hexc: str) -> str:
    h = (hexc or "#000000").lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}&".upper()


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _wrap(text: str, width: float, size: float, char: float) -> list[str]:
    """Renglones que caben en `width` con letra de alto `size` (ancho medio por letra: char × size)."""
    out, cur = [], ""
    for w in text.split():
        nxt = f"{cur} {w}".strip()
        if cur and len(nxt) * char * size > width:
            out.append(cur)
            cur = w
        else:
            cur = nxt
    return out + ([cur] if cur else [])


def ass(items: list[dict], W: int, H: int) -> str:
    """Subtítulos ASS que dibujan cada traducción como en la vista: una caja del color del fondo y el
    texto con el color original, del tamaño que entra en la caja. Para grabarlos en el video."""
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {W}\nPlayResY: {H}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Box,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n"
            "Style: Text,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
            "Style: Code,Consolas,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,4,0,0,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev = []
    for it in items:
        es = it.get("translation")
        if not es:
            continue
        x, y, w, h = it["box"]
        pad = max(2.0, H * 0.004)
        bx, by, bw, bh = x * W - pad, y * H - pad, w * W + 2 * pad, h * H + 2 * pad
        a, b = _ass_time(it["start"]), _ass_time(it["end"])
        code = it["kind"] == "comment"
        char = 0.6 if code else 0.55
        size = h * H / max(1, it.get("lines") or 1) * 0.74
        left = it.get("align") == "left"
        if (it.get("lines") or 1) == 1:  # en español suele ser más largo: la caja crece antes que achicar la letra
            need = len(es) * char * size + 0.4 * size
            if need > bw:
                nw = min(need, bw * GROW)
                if left:
                    nw = min(nw, W - bx - 2)
                else:
                    cx = bx + bw / 2
                    nw = min(nw, 2 * (cx - 2), 2 * (W - 2 - cx))
                    bx = cx - nw / 2
                bw = max(bw, nw)
        rect = f"m 0 0 l {bw:.0f} 0 {bw:.0f} {bh:.0f} 0 {bh:.0f}"
        ev.append(rf"Dialogue: 0,{a},{b},Box,,0,0,0,,{{\pos({bx:.0f},{by:.0f})\p1\1c{_ass_color(it.get('bg'))}"
                  rf"\bord0\shad0}}{rect}{{\p0}}")
        inner = bw - 0.4 * size
        for _ in range(14):  # se achica hasta que entra, como en la vista
            lines = _wrap(es, inner, size, char)
            if len(lines) * size * 1.15 <= bh and all(len(ln) * char * size <= inner for ln in lines):
                break
            size *= 0.9
        body = r"\N".join(ln.replace("\\", "/").replace("{", "(").replace("}", ")") for ln in lines)
        style, an = ("Code", 4) if code else ("Text", 4 if left else 5)
        px = bx + 0.2 * size if an == 4 else bx + bw / 2
        ev.append(rf"Dialogue: 1,{a},{b},{style},,0,0,0,,{{\an{an}\pos({px:.0f},{by + bh / 2:.0f})\fs{size:.1f}"
                  rf"\1c{_ass_color(it.get('fg'))}\bord0\shad0\q2}}{body}")
    return head + "\n".join(ev) + "\n"
