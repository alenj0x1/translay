"use strict";
// Translay: el logo y las escenas del inicio toman el color del tema.
//   themeTone()        tono (0–360) del color de énfasis y si el tema es oscuro
//   tonePalette(tone)  los colores de las escenas: pastel en claro, pastel intenso en oscuro
//   wordmark(box, px)  el logo: una onda de voz y «translay»
// Lo que se anima se detiene con la pestaña oculta y con «reducir movimiento» queda quieto.

const BRAND_HUE = 265;  // violeta: el tono propio de Translay cuando el énfasis es el del tema (neutro)
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function hexHue(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec((hex || "").trim());
  if (!m) return null;
  const [r, g, b] = m.slice(1).map((x) => parseInt(x, 16) / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  if (d < 0.08) return null;  // casi gris: sin tono propio
  const h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

let toneCache = { at: 0 };
function themeTone() {
  const now = performance.now();
  if (toneCache.h !== undefined && now - toneCache.at < 400) return toneCache;
  const root = document.documentElement;
  const accent = root.style.getPropertyValue("--accent-base") || "";
  toneCache = { at: now, h: hexHue(accent) ?? BRAND_HUE, dark: root.dataset.theme === "dark" };
  return toneCache;
}

function tonePalette({ h, dark }) {
  return dark
    ? { ink: [226, 223, 215], hot: `hsl(${h},85%,68%)`, warm: `hsl(${h + 25},85%,74%)`,
        cool: `hsl(${h - 40},70%,74%)` }
    : { ink: [60, 62, 72], hot: `hsl(${h},62%,62%)`, warm: `hsl(${h + 25},70%,66%)`,
        cool: `hsl(${h - 40},50%,64%)` };
}

// un bucle de animación para todo lo de la marca: ~30 cuadros por segundo, quieto si no se ve
const brandLoops = new Set();
let brandLast = 0;
let brandRaf = 0;
function brandTick(ms) {
  brandRaf = brandLoops.size ? requestAnimationFrame(brandTick) : 0;  // sin nada animado, el bucle se detiene
  if (document.hidden || ms - brandLast < 33) return;
  brandLast = ms;
  for (const f of brandLoops) {
    if (!f.alive()) { brandLoops.delete(f); continue; }
    try { f(ms / 1000); } catch (e) { brandLoops.delete(f); console.error(e); }  // una que falla no frena a las demás
  }
}
function brandLoop(draw, alive) {
  draw.alive = alive;
  if (reduceMotion.matches) { draw(4); return; }  // quieto: un cuadro
  brandLoops.add(draw);
  if (!brandRaf) brandRaf = requestAnimationFrame(brandTick);
}

/* ------------------------------------------------------------ el logo
   Una onda de voz (las barras de una voz hablando, centradas en el alto del texto) y «translay» en la letra de la app.
   Las barras van en el color del tema (.wordmark .wave en layout.css); el texto, en el color del texto. */
const WAVE = [0.44, 0.84, 0.6, 1, 0.44];  // alto de cada barra, en alto de las letras altas (t, l)

function wordmark(box, px = 26) {
  const NS = "http://www.w3.org/2000/svg";
  const build = () => {
    const asc = px * 0.72;              // alto de las letras altas (t, l) en Plus Jakarta Sans
    const base = px * 0.98, mid = base - asc / 2;  // la onda, centrada con el texto en Y
    const bw = px * 0.13, gap = px * 0.08;
    const waveW = WAVE.length * bw + (WAVE.length - 1) * gap;
    const svg = document.createElementNS(NS, "svg");
    const text = document.createElementNS(NS, "text");
    text.textContent = "translay";
    text.setAttribute("x", waveW + px * 0.32);
    text.setAttribute("y", base);
    text.setAttribute("class", "word");
    text.setAttribute("style", `font: 800 ${px}px var(--font); letter-spacing: ${-px * 0.04}px`);
    svg.append(...WAVE.map((k, i) => {
      const r = document.createElementNS(NS, "rect");
      const h = asc * k;
      for (const [a, v] of [["x", i * (bw + gap)], ["y", mid - h / 2], ["width", bw], ["height", h], ["rx", bw / 2], ["class", "wave"]]) r.setAttribute(a, v);
      return r;
    }), text);
    box.replaceChildren(svg);
    const w = Math.ceil(waveW + px * 0.32 + text.getComputedTextLength() + 2);
    svg.setAttribute("width", w);
    svg.setAttribute("height", Math.ceil(px * 1.25));
    svg.setAttribute("viewBox", `0 0 ${w} ${Math.ceil(px * 1.25)}`);
  };
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", "translay");
  document.fonts.load(`800 ${px}px "Plus Jakarta Sans"`).then(build);
}

document.querySelectorAll(".brand").forEach((b) => {
  const w = b.querySelector(".wordmark");
  if (w) wordmark(w, +(w.dataset.size || 26));
});
