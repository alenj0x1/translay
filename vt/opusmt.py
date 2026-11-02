"""Traductores Opus-MT preparados aquí, desde la publicación oficial de Helsinki-NLP.

Algunos pares (portugués → español, con el modelo multilingüe itc-itc) no tienen una
versión CTranslate2 publicada. En vez de depender de una conversión de terceros,
Translay baja el archivo oficial de OPUS-MT (versión fija, SHA-256 verificado), lo
convierte con el conversor de CTranslate2 (solo numpy, sin torch: ~3 s) y deja el
modelo en float16 junto a los demás modelos descargados. Lo intermedio se borra.

  PUBLISHED  nombre → (URL, SHA-256, bytes) de cada modelo
  ensure(name) → carpeta del modelo listo (lo prepara la primera vez)

Licencia de los modelos: CC-BY-4.0 (Helsinki-NLP / Tatoeba Challenge); el LICENSE y
el README originales quedan en la carpeta del modelo.
"""

import hashlib
import os
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

PUBLISHED = {
    "itc-itc": (
        "https://object.pouta.csc.fi/Tatoeba-MT-models/itc-itc/opusTCv20210807_transformer-big_2022-08-10.zip",
        "c2546351ab204a161f6a8dc5afe16438c654870c5b0b1bd96c9cf02999d537eb",
        789084111,
    ),
}
_KEEP = ("decoder.yml", "source.spm", "target.spm", "LICENSE", "README.md")
_lock = threading.Lock()


def models_dir() -> Path:
    """Junto a la caché de Hugging Face (allí están los demás modelos)."""
    from huggingface_hub import constants
    return Path(os.environ.get("TRANSLAY_MODELS") or Path(constants.HF_HUB_CACHE) / "translay")


def _download(url: str, sha: str, size: int, dest: Path, log):
    h = hashlib.sha256()
    done, step = 0, size // 10
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if done // step != (done - len(chunk)) // step:
                log(f"descargando traductor: {min(100, round(100 * done / size))} %")
    if h.hexdigest() != sha:
        raise RuntimeError("el traductor descargado no coincide con la versión publicada; se descartó")


def ensure(name: str, log=print) -> Path:
    """Carpeta CTranslate2 del modelo `name` (de PUBLISHED); la prepara si falta."""
    out = models_dir() / f"opus-{name}"
    if (out / "model.bin").exists():
        return out
    url, sha, size = PUBLISHED[name]
    with _lock:
        if (out / "model.bin").exists():
            return out
        import ctranslate2.converters as conv
        import yaml

        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
            tmp = Path(tmp)
            log(f"preparando traductor Opus-MT {name} (una sola vez)")
            _download(url, sha, size, tmp / "model.zip", log)
            raw = tmp / "raw"
            with zipfile.ZipFile(tmp / "model.zip") as z:
                z.extract("decoder.yml", raw)
                cfg = yaml.safe_load((raw / "decoder.yml").read_text(encoding="utf-8"))
                for member in {*cfg["models"], *cfg["vocabs"], *_KEEP}:
                    if "/" in member or "\\" in member or member.startswith("."):
                        raise RuntimeError(f"archivo inesperado en el modelo: {member}")
                    z.extract(member, raw)
            (tmp / "model.zip").unlink()
            built = tmp / "ct2"
            conv.OpusMTConverter(str(raw)).convert(str(built), quantization="float16")
            for f in ("source.spm", "target.spm", "LICENSE", "README.md"):
                shutil.copy(raw / f, built / f)
            shutil.rmtree(raw)
            if out.exists():
                shutil.rmtree(out)
            built.replace(out)  # atómico: o queda completo o no queda
        log(f"traductor Opus-MT {name} listo")
    return out
