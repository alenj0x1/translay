"use strict";
// Componentes de la interfaz: un solo lugar para crear elementos, íconos y botones.
// El aspecto de cada componente vive en web/css/components/*.css; aquí solo se arma.
//
//   el(tag, attrs, ...hijos)        elemento (attrs: class, text, on: {evento: fn}, …)
//   icon(nombre)                    ícono SVG de línea (ver ICONS)
//   btn(texto, opciones)            botón .btn con ícono opcional
//   setBtn(boton, texto, icono)     cambia texto/ícono de un botón existente
//   hydrateIcons(raiz)              pone el ícono a todo [data-icon] del HTML
//   meter(pct, clase)               barra de avance

/* ------------------------------------------------------------ íconos */
// 16×16, trazo de 1.5 (el color sale de currentColor). Las partes rellenas llevan class="solid".
const ICONS = {
  link: '<path d="M6.6 9.4a2.6 2.6 0 0 0 3.7 0l2.4-2.4a2.6 2.6 0 0 0-3.7-3.7l-.9.9M9.4 6.6a2.6 2.6 0 0 0-3.7 0L3.3 9a2.6 2.6 0 0 0 3.7 3.7l.9-.9"/>',
  upload: '<path d="M8 10.5V2.5M4.8 5.6L8 2.5l3.2 3.1M2.5 10v3.5h11V10"/>',
  download: '<path d="M8 2.5v8M4.8 7.4L8 10.5l3.2-3.1M2.5 10v3.5h11V10"/>',
  import: '<path d="M8 2.5v7M5 6.7L8 9.6l3-2.9M2.5 12.5h11"/>',
  queue: '<path d="M2.5 4h8M2.5 8h8M2.5 12h5M12.5 10v4M10.5 12h4"/>',
  sliders: '<path d="M2.5 4.5h4M9.5 4.5h4M2.5 11.5h7M12.5 11.5h1"/><circle cx="8" cy="4.5" r="1.5"/><circle cx="11" cy="11.5" r="1.5"/>',
  grid: '<rect x="2.5" y="2.5" width="4.5" height="4.5"/><rect x="9" y="2.5" width="4.5" height="4.5"/><rect x="2.5" y="9" width="4.5" height="4.5"/><rect x="9" y="9" width="4.5" height="4.5"/>',
  video: '<rect x="2" y="3.5" width="12" height="9"/><path class="solid" d="M6.8 6v4l3.4-2z"/>',
  play: '<path class="solid" d="M4.5 2.8v10.4l8.6-5.2z"/>',
  pause: '<rect class="solid" x="3.8" y="2.8" width="2.8" height="10.4"/><rect class="solid" x="9.4" y="2.8" width="2.8" height="10.4"/>',
  bookmark: '<path d="M4 2.5h8v11l-4-3-4 3z"/>',
  columns: '<rect x="2" y="3" width="12" height="10"/><path d="M8 3v10"/>',
  expand: '<rect x="2" y="3" width="12" height="10"/>',
  trash: '<path d="M2.5 4.5h11M6 4.5V2.5h4v2M4 4.5l.7 9h6.6l.7-9M6.7 7v4M9.3 7v4"/>',
  x: '<path d="M4 4l8 8M12 4l-8 8"/>',
  check: '<path d="M3 8.5l3.2 3L13 4.5"/>',
  plus: '<path d="M8 3v10M3 8h10"/>',
  up: '<path d="M8 13V3M4 7l4-4 4 4"/>',
  pencil: '<path d="M10.5 2.8l2.7 2.7-7.7 7.7H2.8v-2.7z"/>',
  comment: '<path d="M2.5 3h11v7.5h-6l-3 2.5v-2.5h-2z"/>',
  spark: '<path d="M8 2v3M8 11v3M2 8h3M11 8h3M4 4l2 2M10 10l2 2M12 4l-2 2M6 10l-2 2"/>',
  external: '<path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M11.5 9.5v4h-9v-9h4"/>',
  speaker: '<path class="solid i-spk" d="M2.5 6h2.6l3.6-3v10l-3.6-3H2.5z"/><path class="i-wave" d="M10.8 5.4a3.6 3.6 0 0 1 0 5.2M12.6 3.6a6.2 6.2 0 0 1 0 8.8"/><path class="i-x" d="M10.6 6l3.6 4M14.2 6l-3.6 4"/>',
  fullscreen: '<path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10"/>',
  restore: '<path d="M9.5 2.5h4v4M13.5 2.5L8.5 7.5M6.5 13.5h-4v-4M2.5 13.5l5-5"/>',
  sun: '<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M12.6 3.4l-1 1M4.4 11.6l-1 1"/>',
  moon: '<path d="M12.8 10.2A5.5 5.5 0 0 1 5.8 3.2a5.5 5.5 0 1 0 7 7z"/>',
  monitor: '<rect x="2" y="2.5" width="12" height="8.5"/><path d="M5.5 13.5h5M8 11v2.5"/>',
  zip: '<rect x="3" y="2" width="10" height="12"/><path d="M8 2v2M8 5v1M8 7v1M7 9h2v2.5H7z"/>',
  film: '<rect x="2" y="3" width="12" height="10"/><path d="M5 3v10M11 3v10M2 6h3M2 10h3M11 6h3M11 10h3"/>',
  music: '<path d="M6 12V3.5l7-1.5V10"/><circle cx="4.5" cy="12" r="1.5"/><circle cx="11.5" cy="10" r="1.5"/>',
};

function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 16 16");
  s.setAttribute("aria-hidden", "true");
  if (cls) s.setAttribute("class", cls);
  s.innerHTML = ICONS[name] || "";
  return s;
}

/* ------------------------------------------------------------ elementos */
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === "text") e.textContent = v;
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  e.append(...kids.filter(Boolean));
  return e;
}

// Botón del sistema. variant: "" | "dark" | "ghost" | "danger"; size: "" | "sm" | "xs".
function btn(text, { icon: ic, variant = "", size = "sm", title, onClick, disabled, type = "button", href, cls = "", style } = {}) {
  const b = href
    ? el("a", { class: ["btn", size, variant, cls].filter(Boolean).join(" "), href, target: "_blank", rel: "noopener", title })
    : el("button", { class: ["btn", size, variant, cls].filter(Boolean).join(" "), type, title, disabled: !!disabled, style });
  setBtn(b, text, ic);
  if (onClick) b.addEventListener("click", onClick);
  return b;
}

function setBtn(b, text, ic) {
  const label = b.querySelector(":scope > .btn-text");
  if (label && (ic === undefined || b.dataset.icon === ic)) {
    if (label.textContent !== text) label.textContent = text;
    return b;
  }
  b.replaceChildren();
  if (ic) { b.append(icon(ic)); b.dataset.icon = ic; }
  b.append(el("span", { class: "btn-text", text }));
  return b;
}

// HTML estático: <button data-icon="queue">Cola</button> → ícono + texto
function hydrateIcons(root = document) {
  for (const n of root.querySelectorAll("[data-icon]")) {
    if (n.querySelector(":scope > svg")) continue;
    n.prepend(icon(n.dataset.icon));
  }
}

function meter(pct, cls = "") {
  return el("div", { class: ("meter " + cls).trim() }, Object.assign(el("i"), { style: `width:${pct}%` }));
}
