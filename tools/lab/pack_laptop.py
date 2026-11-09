"""Arma el lab para otro equipo como UN solo archivo: tools/lab/laptop.ps1 con tools/lab/cpu.py, la muestra
(en Opus a 32 kbit/s, ~290 KB) y su transcripción adentro, para enviarlo por chat o correo sin publicar nada.

    python tools/lab/pack_laptop.py                    → data/labs/translay-lab.ps1
"""

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "labs" / "translay-lab.ps1"
    with tempfile.TemporaryDirectory() as tmp:
        ogg = Path(tmp) / "podcast.ogg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ROOT / "samples" / "podcast.mp4"), "-vn", "-ac", "1",
                        "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", str(ogg)], check=True)
        files = {"cpu.py": (ROOT / "tools" / "lab" / "cpu.py").read_bytes(), "podcast.ogg": ogg.read_bytes(),
                 "podcast.truth.json": (ROOT / "samples" / "podcast.truth.json").read_bytes()}
    blob = "\n".join(f'    "{k}" = "{base64.b64encode(v).decode()}"' for k, v in files.items())
    src = (ROOT / "tools" / "lab" / "laptop.ps1").read_text(encoding="utf-8-sig")
    marker = '$ErrorActionPreference = "Stop"'
    assert marker in src
    src = src.replace(marker, "$Embedded = @{\n" + blob + "\n}\n" + marker, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(src, encoding="utf-8-sig")  # con BOM: PowerShell 5 lee los acentos bien
    print(f"{out} · {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
