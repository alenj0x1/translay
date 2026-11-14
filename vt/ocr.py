"""Leer el texto de una imagen: PP-OCRv5 (PaddleOCR, Apache 2.0) en ONNX, en la CPU.

Dos modelos oficiales de PaddlePaddle en Hugging Face, con la revisión fija:

* detección (`PP-OCRv5_mobile_det`, 4.8 MB): un mapa de «aquí hay texto» del cuadro reducido
  a 960 px por el lado largo. Lo que sigue es propio: binarizar, separar regiones con un
  etiquetado por tramos de fila (sin OpenCV), puntuar cada región y agrandarla como el
  post-proceso DB de PaddleOCR (`unclip_ratio` 1.5). El texto de un video va casi siempre
  derecho, así que cada región es un rectángulo.
* lectura (`latin_PP-OCRv5_mobile_rec`, 8 MB): cada renglón, a 48 px de alto, pasa a letras con
  CTC voraz. El diccionario sale del `inference.yml` del mismo modelo. El alfabeto latino cubre
  los idiomas que Translay reconoce (inglés, portugués y español), con sus tildes.

Los cuadros llegan de PyAV en BGR (el orden con el que se entrenaron los modelos).
"""

from __future__ import annotations

import numpy as np

from . import modelusage

DET = ("PaddlePaddle/PP-OCRv5_mobile_det_onnx", "e6f4fa85f00e168c862bc462aebca69eef9b3d3d")
REC = ("PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx", "89d3a50e2c27e2e7cceeab0e944c25c807d5db4f")
REPOS = (DET[0], REC[0])

DET_LONG = 960          # lado largo del cuadro para la detección (DetResizeForTest de PaddleOCR)
DET_THRESH = 0.3        # píxel con texto
BOX_THRESH = 0.6        # región que se acepta (promedio del mapa dentro de ella)
UNCLIP = 1.5
REC_H = 48
REC_MAX_W = 1600        # un renglón más ancho se reduce (el modelo admite hasta 3200)
REC_BATCH = 8


def files(repo_rev: tuple[str, str], name: str, download: bool = True):
    from huggingface_hub import hf_hub_download

    repo, rev = repo_rev
    try:
        return hf_hub_download(repo, name, revision=rev, local_files_only=not download)
    except Exception:
        if download:
            raise
        return None


def have() -> bool:
    return all(files(m, f, download=False) for m in (DET, REC) for f in ("inference.onnx", "inference.yml"))


def download(tqdm_class=None):
    from huggingface_hub import hf_hub_download

    for repo, rev in (DET, REC):
        for f in ("inference.yml", "inference.onnx"):
            hf_hub_download(repo, f, revision=rev, tqdm_class=tqdm_class)


def _dictionary(yml_path: str) -> list[str]:
    import yaml  # viene con huggingface_hub

    with open(yml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    chars = [str(c) for c in cfg["PostProcess"]["character_dict"]]
    return ["<blank>"] + chars + [" "]  # CTCLabelDecode: blanco al inicio y espacio al final


def resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Bilineal, en numpy (para los renglones: pocos y chicos)."""
    H, W = img.shape[:2]
    if (H, W) == (h, w):
        return img.astype(np.float32)
    ys = (np.arange(h) + 0.5) * H / h - 0.5
    xs = (np.arange(w) + 0.5) * W / w - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, H - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, W - 1)
    y1, x1 = np.minimum(y0 + 1, H - 1), np.minimum(x0 + 1, W - 1)
    wy = np.clip(ys - y0, 0, 1)[:, None, None]
    wx = np.clip(xs - x0, 0, 1)[None, :, None]
    a = img.astype(np.float32)
    top = a[y0][:, x0] * (1 - wx) + a[y0][:, x1] * wx
    bot = a[y1][:, x0] * (1 - wx) + a[y1][:, x1] * wx
    return top * (1 - wy) + bot * wy


def regions(mask: np.ndarray) -> list[tuple[int, int, int, int, np.ndarray, np.ndarray]]:
    """Regiones conectadas (8 vecinos) de una máscara: [(x0, y0, x1, y1, filas, tramos)], x1/y1
    exclusivos. Por tramos de fila con unión-búsqueda: el texto ocupa poco del cuadro, así que hay
    pocos tramos aunque la imagen sea grande."""
    m = np.pad(mask.astype(np.int8), ((0, 0), (1, 1)))
    d = np.diff(m, axis=1)
    rs, xs = np.nonzero(d == 1)
    _, xe = np.nonzero(d == -1)
    n = len(rs)
    if not n:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # índice del primer tramo de cada fila
    bounds = np.searchsorted(rs, np.arange(mask.shape[0] + 1))
    for r in range(1, mask.shape[0]):
        a0, a1 = bounds[r - 1], bounds[r]
        b0, b1 = bounds[r], bounds[r + 1]
        i, j = a0, b0
        while i < a1 and j < b1:
            # se tocan (también en diagonal): [xs, xe) contra [xs-1, xe+1)
            if xs[i] <= xe[j] and xs[j] <= xe[i]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
            if xe[i] < xe[j]:
                i += 1
            else:
                j += 1
    roots = np.array([find(i) for i in range(n)])
    out = []
    for root in np.unique(roots):
        k = roots == root
        out.append((int(xs[k].min()), int(rs[k].min()), int(xe[k].max()), int(rs[k].max()) + 1,
                    rs[k], np.stack([xs[k], xe[k]], 1)))
    return out


def join_rows(boxes: list[tuple], gap: float = 1.0) -> list[tuple]:
    """Une las cajas de un mismo renglón separadas por espacios (el detector corta las palabras de
    una letra monoespaciada): mismo alto, casi la misma altura y a menos de `gap` altos de distancia.
    Leer el renglón entero también es más rápido que leer cada palabra."""
    out: list[list[float]] = []
    for b in sorted(boxes, key=lambda b: b[0]):
        x0, y0, x1, y1, sc = b
        h = y1 - y0
        for o in out:
            oh = o[3] - o[1]
            ov = min(y1, o[3]) - max(y0, o[1])
            if ov > 0.6 * min(h, oh) and max(h, oh) < 1.4 * min(h, oh) and x0 - o[2] < gap * max(h, oh)                     and x1 > o[2]:
                o[1], o[2], o[3] = min(o[1], y0), max(o[2], x1), max(o[3], y1)
                o[4] = min(o[4], sc)
                break
        else:
            out.append([x0, y0, x1, y1, sc])
    return [tuple(o) for o in out]


class OCR:
    def __init__(self, threads: int = 2):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.log_severity_level = 3  # sin los avisos de inicializadores sin usar
        cpu = ["CPUExecutionProvider"]
        self.det = ort.InferenceSession(files(DET, "inference.onnx"), opts, providers=cpu)
        self.rec = ort.InferenceSession(files(REC, "inference.onnx"), opts, providers=cpu)
        self.chars = _dictionary(files(REC, "inference.yml"))

    # ------------------------------------------------------------ detección
    def detect(self, small: np.ndarray, scale: float) -> list[tuple[float, float, float, float, float]]:
        """small: el cuadro BGR ya reducido (lados múltiplos de 32). Cajas en píxeles del cuadro
        original (dividiendo por scale): [(x0, y0, x1, y1, puntaje)]."""
        modelusage.mark(DET[0])
        x = (small.astype(np.float32) / 255.0 - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
        prob = self.det.run(None, {"x": x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
        H, W = prob.shape
        out = []
        for x0, y0, x1, y1, rows, spans in regions(prob > DET_THRESH):
            w, h = x1 - x0, y1 - y0
            if min(w, h) < 3:
                continue
            score = float(np.mean(np.concatenate([prob[r, a:b] for r, (a, b) in zip(rows, spans)])))
            if score < BOX_THRESH:
                continue
            pad = w * h * UNCLIP / (2 * (w + h))  # lo que agranda el unclip de DB en un rectángulo
            bx0, by0 = max(0.0, x0 - pad), max(0.0, y0 - pad)
            bx1, by1 = min(float(W), x1 + pad), min(float(H), y1 + pad)
            if min(bx1 - bx0, by1 - by0) < 5:
                continue
            out.append((bx0 / scale, by0 / scale, bx1 / scale, by1 / scale, score))
        return join_rows(out)

    # ------------------------------------------------------------- lectura
    def recognize(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        """Renglones BGR → [(texto, confianza 0–1)]. Por tandas de anchos parecidos."""
        modelusage.mark(REC[0])
        res: list[tuple[str, float]] = [("", 0.0)] * len(crops)
        order = sorted(range(len(crops)), key=lambda i: crops[i].shape[1] / max(1, crops[i].shape[0]))
        for k in range(0, len(order), REC_BATCH):
            idx = order[k:k + REC_BATCH]
            widths = [min(REC_MAX_W, max(16, int(round(REC_H * c.shape[1] / max(1, c.shape[0])))))
                      for c in (crops[i] for i in idx)]
            W = max(widths)
            batch = np.zeros((len(idx), 3, REC_H, W), np.float32)
            for n, (i, w) in enumerate(zip(idx, widths)):
                img = resize(crops[i], w, REC_H) / 255.0
                batch[n, :, :, :w] = ((img - 0.5) / 0.5).transpose(2, 0, 1)
            probs = self.rec.run(None, {"x": batch})[0]
            for n, i in enumerate(idx):
                res[i] = self._ctc(probs[n])
        return res

    def _ctc(self, p: np.ndarray) -> tuple[str, float]:
        best = p.argmax(1)
        conf = p.max(1)
        keep = best != 0
        keep[1:] &= best[1:] != best[:-1]
        chars = [self.chars[c] for c in best[keep] if c < len(self.chars)]
        return "".join(chars).strip(), float(conf[keep].mean()) if keep.any() else 0.0

    def read(self, frame: np.ndarray, small: np.ndarray, scale: float) -> list[dict]:
        """Renglones de un cuadro: [{box: (x0, y0, x1, y1) en píxeles, text, conf}]."""
        boxes = self.detect(small, scale)
        if not boxes:
            return []
        crops = [frame[int(y0):max(int(y0) + 1, int(np.ceil(y1))), int(x0):max(int(x0) + 1, int(np.ceil(x1)))]
                 for x0, y0, x1, y1, _ in boxes]
        texts = self.recognize(crops)
        return [{"box": b[:4], "text": t, "conf": c} for b, (t, c) in zip(boxes, texts) if t]
