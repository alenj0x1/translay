// El agente como personaje: una estrella de puntas redondeadas que cada persona arma a su gusto (Ajustes › Agente
// › Avatar): color, ojos, boca, mejillas y un accesorio. Se guarda como JSON en la preferencia agent_avatar.
//   starSvg(look)        el personaje (SVG); clase "think" mientras piensa y "talk" mientras responde
//   agentLook()          lo elegido, completo con los valores por defecto
//   STAR_PARTS           las opciones de cada parte (agregar una = una entrada aquí y su dibujo abajo)
// Elegido 2026-11-14 («Lumi»): las puntas siempre redondeadas.

const STAR_DEFAULT = { shape: "cinco", eyes: "brillo", mouth: "sonrisa", cheeks: "rosadas", acc: "ninguno" };
// formas del cuerpo: puntas, radio de las puntas, radio interior y cuánto se redondean (siempre redondeadas)
const STAR_SHAPES = {
  cinco: [5, 35, 17.5, .55], cuatro: [4, 35, 19, .85], seis: [6, 34, 21, .6], siete: [7, 33, 23, .62],
  suave: [5, 33, 22, .9], nube: [8, 32, 26, .95],
};
const STAR_COLOR = "#f3c25a";  // si el agente usa el color del tema
const STAR_PARTS = {
  shape: [["cinco", t("Cinco puntas")], ["cuatro", t("Cuatro puntas")], ["seis", t("Seis puntas")], ["siete", t("Siete puntas")],
    ["suave", t("Suave")], ["nube", t("Nube")]],
  eyes: [["brillo", t("Con brillo")], ["felices", t("Felices")], ["grandes", t("Grandes")], ["guiño", t("Guiño")], ["tranquilos", t("Tranquilos")]],
  mouth: [["sonrisa", t("Sonrisa")], ["risa", t("Risa")], ["gatito", t("Gatito")], ["asombro", t("Asombro")], ["serena", t("Serena")]],
  cheeks: [["ninguna", t("Sin mejillas")], ["rosadas", t("Rosadas")], ["pecas", t("Pecas")], ["corazones", t("Corazones")]],
  acc: [["ninguno", t("Ninguno")], ["corona", t("Corona")], ["gorra", t("Gorra")], ["moño", t("Moño")], ["lentes", t("Lentes")],
    ["audífonos", t("Audífonos")], ["flor", t("Flor")], ["mago", t("Sombrero de mago")]],
};
i18nTrack(STAR_PARTS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

function agentLook() {
  let look = {};
  try { look = JSON.parse(prefs.agent_avatar || "{}") || {}; } catch { look = {}; }
  if (typeof look !== "object") look = {};
  if (typeof look.cheeks === "boolean") look.cheeks = look.cheeks ? "rosadas" : "ninguna";  // antes era sí o no
  return { ...STAR_DEFAULT, ...look };
}

const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}
function mixHex(hex, other, w) {  // mezcla dos colores #rrggbb (w: cuánto del segundo)
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const a = p(hex), b = p(other);
  return "#" + a.map((x, i) => Math.round(x + (b[i] - x) * w).toString(16).padStart(2, "0")).join("");
}

// cuerpo: «cinco» es el de Lumi (dibujado a mano); las demás formas se calculan con las puntas redondeadas
const STAR_BODY = "M40 6c3 0 5 2 6.5 5.5l5 11 12 1.6c7 1 8.5 6 3.6 10.6l-8.7 8.3 2.2 11.8c1.3 7-2.8 10-9 6.7L40 56l-11.6 5.5c-6.2 3.3-10.3.3-9-6.7l2.2-11.8-8.7-8.3c-4.9-4.6-3.4-9.6 3.6-10.6l12-1.6 5-11C35 8 37 6 40 6z";
function starBody(shape) {
  if (!STAR_SHAPES[shape] || shape === "cinco") return STAR_BODY;
  const [n, ro, ri, round] = STAR_SHAPES[shape];
  const cx = 40, cy = 38;
  const pts = [];
  for (let i = 0; i < n * 2; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / n;
    const r = i % 2 ? ri : ro;
    pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
  }
  // cada vértice se reemplaza por una curva entre los puntos medios de sus lados (más «round», más redonda)
  const mid = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
  let d = "";
  pts.forEach((p, i) => {
    const prev = pts[(i - 1 + pts.length) % pts.length], next = pts[(i + 1) % pts.length];
    const k = (i % 2 ? .5 : 1) * round * .5;
    const a = mid(p, prev, k), b = mid(p, next, k);
    d += (i ? "L" : "M") + a.map((x) => x.toFixed(1)).join(" ") + "Q" + p.map((x) => x.toFixed(1)).join(" ") + " " + b.map((x) => x.toFixed(1)).join(" ");
  });
  return d + "Z";
}

function starEyes(g, kind, ink) {
  const shine = (x, y, r = 1.1) => g.append(svgEl("circle", { class: "st-pupil", cx: x, cy: y, r, fill: "#fff" }));
  if (kind === "felices" || kind === "tranquilos") {
    const d = kind === "felices" ? ["M30 36q3-4 6 0", "M44 36q3-4 6 0"] : ["M30 35q3 3 6 0", "M44 35q3 3 6 0"];
    for (const p of d) g.append(svgEl("path", { class: "st-eye", d: p, stroke: ink, "stroke-width": 2.4, fill: "none", "stroke-linecap": "round" }));
    return;
  }
  const big = kind === "grandes";
  const rx = big ? 4 : 3, ry = big ? 5.2 : 4;
  g.append(svgEl("ellipse", { class: "st-eye", cx: 33, cy: 35, rx, ry, fill: ink }));
  if (kind === "guiño") g.append(svgEl("path", { class: "st-eye", d: "M44 35.5q3-3 6 0", stroke: ink, "stroke-width": 2.4, fill: "none", "stroke-linecap": "round" }));
  else g.append(svgEl("ellipse", { class: "st-eye", cx: 47, cy: 35, rx, ry, fill: ink }));
  shine(33.9, 33.4, big ? 1.5 : 1.1);
  if (kind !== "guiño") shine(47.9, 33.4, big ? 1.5 : 1.1);
  if (big) { shine(32, 37, .6); shine(46, 37, .6); }
}

function starMouth(g, kind, ink) {
  const stroke = { stroke: ink, "stroke-width": 2.2, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" };
  if (kind === "risa") g.append(svgEl("path", { class: "st-mouth", d: "M35 42.5h10q-1 6-5 6t-5-6z", fill: ink }));
  else if (kind === "gatito") g.append(svgEl("path", { class: "st-mouth", d: "M35.5 43q2.2 2.6 4.5 0 2.3 2.6 4.5 0", ...stroke }));
  else if (kind === "asombro") g.append(svgEl("ellipse", { class: "st-mouth", cx: 40, cy: 45, rx: 2.6, ry: 3, fill: ink }));
  else if (kind === "serena") g.append(svgEl("path", { class: "st-mouth", d: "M37 44.5q3 1.4 6 0", ...stroke }));
  else g.append(svgEl("path", { class: "st-mouth", d: "M35 43q5 4 10 0", ...stroke }));
}

function starAccessory(g, kind, color) {
  const ink = "#2b2b2b";
  if (kind === "corona") {
    g.append(svgEl("path", { d: "M31 9l3 5 6-7 6 7 3-5 1 9H30z", fill: "#f6c945", stroke: "#b8860b", "stroke-width": 1.2, "stroke-linejoin": "round" }));
    g.append(svgEl("circle", { cx: 40, cy: 13, r: 1.3, fill: "#e4572e" }));
  } else if (kind === "gorra") {
    g.append(svgEl("path", { d: "M29 15q1-10 11-10t11 10z", fill: "#4c7bd9" }));
    g.append(svgEl("path", { d: "M44 14.5h13q1 2.5-2 3H44z", fill: "#3a62b5" }));
    g.append(svgEl("circle", { cx: 40, cy: 5.2, r: 1.4, fill: "#3a62b5" }));
  } else if (kind === "moño") {
    g.append(svgEl("path", { d: "M47 14l7-5q2 4 0 8zM47 14l-1 8q-4-1-4-5z", fill: "#e84f9b" }));
    g.append(svgEl("circle", { cx: 47, cy: 14, r: 2, fill: "#c23d80" }));
  } else if (kind === "lentes") {
    const s = { fill: "none", stroke: ink, "stroke-width": 1.8 };
    g.append(svgEl("circle", { cx: 33, cy: 35, r: 6, ...s }), svgEl("circle", { cx: 47, cy: 35, r: 6, ...s }),
      svgEl("path", { d: "M39 35h2M27 34l-4-2M53 34l4-2", ...s, "stroke-linecap": "round" }));
  } else if (kind === "audífonos") {
    g.append(svgEl("path", { d: "M20 34q0-24 20-24t20 24", fill: "none", stroke: ink, "stroke-width": 3, "stroke-linecap": "round" }));
    g.append(svgEl("rect", { x: 15, y: 30, width: 8, height: 12, rx: 4, fill: ink }), svgEl("rect", { x: 57, y: 30, width: 8, height: 12, rx: 4, fill: ink }));
  } else if (kind === "flor") {
    for (let i = 0; i < 5; i++) {
      const a = (i / 5) * Math.PI * 2;
      g.append(svgEl("circle", { cx: 52 + Math.cos(a) * 3.2, cy: 13 + Math.sin(a) * 3.2, r: 2.6, fill: "#f7f2fa" }));
    }
    g.append(svgEl("circle", { cx: 52, cy: 13, r: 2, fill: "#f3a712" }));
  } else if (kind === "mago") {
    g.append(svgEl("path", { d: "M27 17q13-4 26 0l-9-16q-2-2-4 0z", fill: "#5b4a9e" }));
    g.append(svgEl("path", { d: "M25 17.5q15-5 30 0", fill: "none", stroke: "#3f3378", "stroke-width": 3, "stroke-linecap": "round" }));
    g.append(svgEl("path", { d: "M41 7l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z", fill: color }));
  }
}

// «Del tema»: el color de énfasis de la app (o el de la biblioteca, si está elegido así); si el tema no tiene uno
// (gris), el amarillo de la estrella
function themeStarColor() {
  const v = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  let rgb = null;
  if (/^#[0-9a-f]{6}$/i.test(v)) rgb = [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16));
  else if (/^rgba?\(/i.test(v)) rgb = v.match(/[\d.]+/g).slice(0, 3).map(Number);
  if (!rgb || Math.max(...rgb) - Math.min(...rgb) < 24) return STAR_COLOR;
  return "#" + rgb.map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");
}

function starSvg(look = agentLook(), color = null, cls = "") {
  const c = /^#[0-9a-f]{6}$/i.test(color || "") ? color : (/^#[0-9a-f]{6}$/i.test(prefs.agent_color || "") ? prefs.agent_color : themeStarColor());
  const ink = mixHex(c, "#000000", .78);
  const svg = svgEl("svg", { viewBox: "0 0 80 80", class: ("agent-star " + cls).trim(), "aria-hidden": "true" });
  const body = svgEl("g", { class: "st-body" });
  // con su borde blanco (el mismo en todos los tamaños y lugares)
  body.append(svgEl("path", { d: starBody(look.shape), fill: c, stroke: "#fff", "stroke-width": 2.6, "stroke-linejoin": "round" }));
  starEyes(body, look.eyes, ink);
  starMouth(body, look.mouth, ink);
  const blush = mixHex(c, "#f0607a", .55);
  if (look.cheeks === "rosadas") {
    body.append(svgEl("circle", { cx: 28, cy: 41, r: 2.6, fill: blush, opacity: .6 }), svgEl("circle", { cx: 52, cy: 41, r: 2.6, fill: blush, opacity: .6 }));
  } else if (look.cheeks === "pecas") {
    for (const [x, y] of [[26.5, 40], [29, 42], [27, 43.5], [53.5, 40], [51, 42], [53, 43.5]]) {
      body.append(svgEl("circle", { cx: x, cy: y, r: .8, fill: ink, opacity: .55 }));
    }
  } else if (look.cheeks === "corazones") {
    const heart = (x, y) => `M${x} ${y + 1.6}l-2.4-2.3a1.4 1.4 0 0 1 2.4-1.5 1.4 1.4 0 0 1 2.4 1.5z`;
    body.append(svgEl("path", { d: heart(28, 40.5), fill: blush }), svgEl("path", { d: heart(52, 40.5), fill: blush }));
  }
  // dormido (modelo apagado): ojos cerrados y «z» que flotan; se muestran con la clase "sleep" (star.css)
  for (const d of ["M30 36q3 2.6 6 0", "M44 36q3 2.6 6 0"]) {
    body.append(svgEl("path", { class: "st-closed", d, stroke: ink, "stroke-width": 2.4, fill: "none", "stroke-linecap": "round" }));
  }
  starAccessory(body, look.acc, c);
  svg.append(body);
  const heart = (x, y, s) => `M${x} ${y + s * .9}l-${s}-${s * .95}a${s * .55} ${s * .55} 0 0 1 ${s}-${s * .6} ${s * .55} ${s * .55} 0 0 1 ${s} ${s * .6}z`;
  for (const [x, y, s] of [[64, 16, 4], [15, 22, 3.2]]) svg.append(svgEl("path", { class: "st-heart", d: heart(x, y, s), fill: mixHex(c, "#f0607a", .7) }));
  for (const [x, y, s] of [[58, 22, 7], [64, 14, 9], [71, 5, 11]]) {
    const z = svgEl("text", { class: "st-z", x, y, "font-size": s, "font-weight": 800, fill: mixHex(c, "#ffffff", .35) });
    z.textContent = "z";
    svg.append(z);
  }
  // destellos (al pensar)
  for (const d of ["M68 10l1.4 3.6 3.6 1.4-3.6 1.4L68 20l-1.4-3.6-3.6-1.4 3.6-1.4z", "M10 18l1 2.6 2.6 1-2.6 1L10 25l-1-2.4-2.6-1 2.6-1z",
    "M72 52l1 2.6 2.6 1-2.6 1L72 59l-1-2.4-2.6-1 2.6-1z"]) svg.append(svgEl("path", { class: "st-spark", d, fill: c }));
  return svg;
}
