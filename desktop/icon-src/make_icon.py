"""Draws Translay's app icon (desktop/src-tauri/icons/source.png): the logo's voice wave in the accent color
on the dark background, as a rounded square. `npx tauri icon` turns it into every size Windows needs."""
from pathlib import Path
from PIL import Image, ImageDraw

S = 1024 * 4                    # drawn 4x larger, then reduced: smooth edges
u = S / 64                      # the design is on a 64-unit grid
BG, WAVE = "#161616", "#9677b8"  # the app's dark background; the violet accent as the logo shows it in dark
HEIGHTS = [0.44, 0.84, 0.6, 1, 0.44]  # the same bars as the logo (web/js/brand.js › WAVE)
BW, GAP, TALL = 6.4, 2.8, 34

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=15 * u, fill=BG)
x = (64 - (len(HEIGHTS) * BW + (len(HEIGHTS) - 1) * GAP)) / 2
for k in HEIGHTS:
    h = TALL * k
    d.rounded_rectangle([x * u, (32 - h / 2) * u, (x + BW) * u, (32 + h / 2) * u], radius=BW / 2 * u, fill=WAVE)
    x += BW + GAP
out = Path(__file__).resolve().parent.parent / "src-tauri" / "icons" / "source.png"
img.resize((1024, 1024), Image.LANCZOS).save(out)
print(out)
