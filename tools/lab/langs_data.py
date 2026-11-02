"""Data for the language labs: FLEURS (Google, CC-BY-4.0) into data/labs/languages/fleurs/.

The same sentences read in each language, with their text. Downloads each language's text (test and dev)
and the dev audio (for the recognition lab); what is already there is skipped. About 250 MB per language
with audio.

    python tools/lab/langs_data.py                    # en_us, pt_br, es_419
    python tools/lab/langs_data.py --no-audio         # text only (translation lab)
"""

import argparse
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "labs" / "languages" / "fleurs"
BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"


def fetch(url: str, dest: Path):
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--langs", nargs="+", default=["en_us", "pt_br", "es_419"])
    ap.add_argument("--no-audio", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in a.langs:
        for split in ("test", "dev"):
            tsv = OUT / f"{lang}.{split}.tsv"
            if not tsv.exists():
                print(f"{lang} {split}: text", flush=True)
                fetch(f"{BASE}/{lang}/{split}.tsv", tsv)
        if a.no_audio or (OUT / lang / "dev").is_dir():
            continue
        print(f"{lang}: dev audio", flush=True)
        tgz = OUT / f"{lang}.dev.tar.gz"
        fetch(f"{BASE}/{lang}/audio/dev.tar.gz", tgz)
        with tarfile.open(tgz) as t:
            t.extractall(OUT / lang, filter="data")  # no paths outside the folder
        tgz.unlink()
    print(f"done: {OUT}")


if __name__ == "__main__":
    main()
