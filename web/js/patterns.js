"use strict";
// Patrones Bauhaus: círculos, cuartos de círculo, triángulos y cuadrados en cuadrícula.
// Cada colección tiene el suyo, sacado de su nombre (siempre el mismo, nunca dos iguales);
// «Otro patrón» cambia la semilla (se guarda en el navegador).
// Íconos por categoría de YouTube; los canales usan su avatar y banner reales (/chan/…).

const BAU_PALETTES = [
  ["#e8a13a", "#d9534f", "#3a7ca5", "#f1e3c8"],
  ["#5b8def", "#9b6bd6", "#2bb3a3", "#1f2a44"],
  ["#f06c9b", "#ffb86b", "#7bd389", "#2b2340"],
  ["#3fbf74", "#e3c14f", "#3a7bd5", "#16302b"],
  ["#ff7a59", "#ffd166", "#118ab2", "#073b4c"],
  ["#c084fc", "#60a5fa", "#f472b6", "#1e1b3a"],
  ["#ef6f6c", "#f7b267", "#4d9de0", "#fdf0d5"],
  ["#2ec4b6", "#ff9f1c", "#e71d36", "#011627"],
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

// colores fijos por clave (las bibliotecas usan su propio color como principal)
const PALETTE_OVERRIDE = {};
function patternPalette(key) {
  const r = seeded(patternSeed(key));
  const p = BAU_PALETTES[Math.floor(r() * BAU_PALETTES.length)];
  const main = PALETTE_OVERRIDE[key];
  return main ? [main, p[1] === main ? p[0] : p[1], p[2], p[3]] : p;
}

// SVG de cols × rows celdas; `slice` lo recorta para llenar cualquier caja
function bauhausSVG(key, cols = 12, rows = 3) {
  const r = seeded(patternSeed(key) + "·shapes");
  const c = patternPalette(key);
  const z = 10;
  let s = `<rect width="${cols * z}" height="${rows * z}" fill="${c[3]}"/>`;
  for (let x = 0; x < cols; x++) {
    for (let y = 0; y < rows; y++) {
      const X = x * z, Y = y * z, cx = X + z / 2, cy = Y + z / 2;
      const k = Math.floor(r() * 5), f = c[Math.floor(r() * 3)], rot = Math.floor(r() * 4) * 90;
      const t = `transform="rotate(${rot} ${cx} ${cy})"`;
      if (k === 0) s += `<circle cx="${cx}" cy="${cy}" r="${z / 2 - 0.8}" fill="${f}"/>`;
      else if (k === 1) s += `<path d="M${X} ${Y + z}A${z} ${z} 0 0 1 ${X + z} ${Y}V${Y + z}Z" fill="${f}" ${t}/>`;
      else if (k === 2) s += `<path d="M${X} ${Y}L${X + z} ${Y + z}H${X}Z" fill="${f}" ${t}/>`;
      else if (k === 3) s += `<path d="M${X} ${Y + z}A${z / 2} ${z / 2} 0 0 1 ${X + z} ${Y + z}Z" fill="${f}" ${t}/>`;
      else s += `<rect x="${X + 2}" y="${Y + 2}" width="${z - 4}" height="${z - 4}" rx="1" fill="${f}"/>`;
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${cols * z} ${rows * z}" preserveAspectRatio="xMidYMid slice">${s}</svg>`;
}

const patternURL = (key, cols, rows) => `url("data:image/svg+xml,${encodeURIComponent(bauhausSVG(key, cols, rows))}")`;

// un elemento con el patrón de fondo
function patternEl(key, cls, cols, rows) {
  return el("span", { class: "bau " + (cls || ""), "aria-hidden": "true", style: `background-image: ${patternURL(key, cols, rows)}` });
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
