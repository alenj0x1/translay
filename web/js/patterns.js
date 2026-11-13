"use strict";
// Campo de puntos: un fondo sólido y apagado con una cuadrícula pareja de puntos de su mismo tono.
// Cada colección tiene el suyo, sacado de su nombre (siempre el mismo); «Otro patrón» cambia la semilla
// (se guarda en el navegador). Los puntos miden lo mismo en cualquier caja (no se estiran con ella).
// Íconos por categoría de YouTube; los canales usan su avatar y banner reales (/chan/…).

// [principal (distintivo), fondo, puntos]: oscuros y apagados
const DOT_PALETTES = [
  ["#5b7db1", "#1f2a3a", "#3f5a80"],
  ["#3f9a8c", "#17302d", "#2f6e65"],
  ["#c0714f", "#33221c", "#7c4a35"],
  ["#9aa04f", "#262a18", "#5e6232"],
  ["#9a6aa8", "#2a1f2e", "#5f4469"],
  ["#c06a85", "#301e25", "#7a4455"],
  ["#b89a5e", "#2c2619", "#73603b"],
  ["#7f8a99", "#22262c", "#4f5763"],
];

// generador con semilla (FNV-1a + mezcla): el mismo texto da siempre la misma secuencia
function seeded(text) {
  let h = 2166136261;
  for (const ch of String(text)) h = Math.imul(h ^ ch.codePointAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

const patternSeed = (key) => {
  try { return key + (localStorage.getItem("vt-pattern:" + key) || ""); } catch (e) { return key; }
};
function reshufflePattern(key) {
  try { localStorage.setItem("vt-pattern:" + key, String(Math.random()).slice(2, 8)); } catch (e) { /* sin almacenamiento */ }
}

// mezcla de dos colores #rrggbb (t: cuánto de b)
function mixHex(a, b, t) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("");
}

// colores fijos por clave (las bibliotecas usan su propio color como principal)
const PALETTE_OVERRIDE = {};
function patternPalette(key) {
  const main = PALETTE_OVERRIDE[key];
  if (main) return [main, mixHex(main, "#141518", 0.7), mixHex(main, "#141518", 0.32)];
  const r = seeded(patternSeed(key));
  return DOT_PALETTES[Math.floor(r() * DOT_PALETTES.length)];
}

// el campo de puntos como estilo de fondo: color sólido + puntos de tamaño fijo en px
function patternStyle(key) {
  const r = seeded(patternSeed(key) + "·dots");
  const [, bg, dot] = patternPalette(key);
  const gap = [12, 14, 16][Math.floor(r() * 3)];
  const rad = gap >= 16 ? 1.6 : 1.3;
  return `background-color: ${bg}; background-image: radial-gradient(circle, ${dot} ${rad}px, transparent ${rad + 0.4}px);`
    + ` background-size: ${gap}px ${gap}px; background-position: ${gap / 2}px ${gap / 2}px`;
}

// un elemento con el patrón de fondo (cols y rows quedan por compatibilidad: los puntos no se estiran)
function patternEl(key, cls) {
  return el("span", { class: "bau " + (cls || ""), "aria-hidden": "true", style: patternStyle(key) });
}

/* ------------------------------------------------------------ bibliotecas */
// banner de una biblioteca: su patrón, con su color como el principal
function vaultBanner(v, cls = "", cols = 16, rows = 3) {
  const key = `vault:${v.id}:${v.pattern || ""}`;
  if (/^#[0-9a-f]{6}$/i.test(v.color || "")) PALETTE_OVERRIDE[key] = v.color;
  return patternEl(key, "vbanner " + cls, cols, rows);
}

/* ------------------------------------------------------------ íconos */
const CATEGORY_ICON = {
  "Cine y animación": "film", "Autos y vehículos": "car", "Música": "music", "Mascotas y animales": "paw",
  "Deportes": "ball", "Viajes y eventos": "plane", "Videojuegos": "gamepad", "Personas y blogs": "chat",
  "Comedia": "smile", "Entretenimiento": "star", "Noticias y política": "news", "Tutoriales y estilo": "brush",
  "Educación": "cap", "Ciencia y tecnología": "atom", "ONG y activismo": "heart",
};
const COLL_ICONS = ["bookmark", "star", "folder", "book", "globe", "music", "film", "flask", "heart", "atom", "cap", "plane"];
const AUTO_ICON = { home: "home", recent: "clock", all: "grid" };

function collIcon(c) {
  if (AUTO_ICON[c.id]) return AUTO_ICON[c.id];
  if (c.kind === "categoría") return CATEGORY_ICON[c.name] || "tag";
  if (c.kind === "canal") return "user";
  if (c.kind === "playlist") return "queue";
  const r = seeded(c.id + "·icon");
  return COLL_ICONS[Math.floor(r() * COLL_ICONS.length)];
}

const chanArt = (kind, name) => `/chan/${kind}/${encodeURIComponent(name)}`;

// distintivo de la colección: avatar del canal o ícono sobre su color
function collBadge(c, cls = "") {
  const color = patternPalette(c.id)[0];
  const b = el("span", { class: "cbadge " + cls, style: `--c: ${color}`, "aria-hidden": "true" }, icon(collIcon(c)));
  if (c.kind === "canal") {
    const img = el("img", { src: chanArt("avatar", c.name), alt: "", loading: "lazy" });
    img.addEventListener("load", () => b.classList.add("has-img"));
    img.addEventListener("error", () => img.remove());
    b.append(img);
  }
  return b;
}

// banner de la colección: el del canal o su patrón
function collBanner(c, onShuffle) {
  const b = el("div", { class: "cbanner" }, patternEl(c.id, "fill", 16, 3));
  if (c.kind === "canal") {
    const img = el("img", { src: chanArt("banner", c.name), alt: "", loading: "lazy" });
    img.addEventListener("load", () => b.classList.add("has-img"));
    img.addEventListener("error", () => img.remove());
    b.append(img);
  }
  if (onShuffle && c.kind !== "canal") {
    b.append(btn("Otro patrón", { icon: "shuffle", size: "xs", cls: "cb-shuffle", onClick: () => { reshufflePattern(c.id); onShuffle(); } }));
  }
  return b;
}
