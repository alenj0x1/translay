"use strict";
// Translay: dibuja la escena de fondo fuera del hilo de la interfaz (OffscreenCanvas), así navegar no se siente.
// Recibe de web/js/scenes.js › mountScene: init {canvas, name, W, H, d, colors, fade, still} · resize {W, H, d} ·
// palette {colors, fade} · pause {paused}. Las escenas y el dibujo son los mismos de scenes.js.
importScripts("scenes.js");

let r = null, paused = false, still = false, t0 = 0, timer = 0;
// lo que llega mientras se carga la letra (el tamaño final, colores nuevos) se aplica al terminar, no se pierde
let size = null, colors = null;

const loop = () => {
  clearTimeout(timer);
  if (!r || paused) return;
  const a = performance.now();
  r.frame(still ? 4 : (a - t0) / 1000);
  const took = performance.now() - a;
  // el siguiente cuadro espera lo que haga falta para no pasar del 15 % de un núcleo (SCENE_SHARE)
  if (!still) timer = setTimeout(loop, Math.max(1000 / SCENE_FPS, took / SCENE_SHARE - took));
};

async function loadFont() {
  try {  // la misma letra de la app, si se puede cargar aquí; si no, la monoespaciada del sistema
    const f = new FontFace("JetBrains Mono", "url(../fonts/jetbrains-mono-latin-400-normal.woff2)");
    self.fonts.add(await f.load());
    return '"JetBrains Mono"';
  } catch {
    return "monospace";
  }
}

self.onmessage = async ({ data: m }) => {
  if (m.type === "init") {
    size = m.W ? { W: m.W, H: m.H, d: m.d } : size;
    colors = colors || { colors: m.colors, fade: m.fade };
    still = !!m.still;
    const font = await loadFont();
    r = sceneRenderer(m.canvas.getContext("2d"), (w, h) => new OffscreenCanvas(w, h));
    r.scene(m.name);
    r.palette(colors.colors, colors.fade, font);
    if (size) r.resize(size.W, size.H, size.d);
    t0 = performance.now() - 3000;
    loop();
  } else if (m.type === "resize") {
    size = { W: m.W, H: m.H, d: m.d };
    if (r) { r.resize(m.W, m.H, m.d); if (still) loop(); }
  } else if (m.type === "palette") {
    colors = { colors: m.colors, fade: m.fade };
    if (r) { r.palette(m.colors, m.fade); if (still) loop(); }
  } else if (m.type === "pause") {
    paused = m.paused;
    if (!paused) loop();
  }
};
