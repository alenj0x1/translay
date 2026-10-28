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
  // controles de la ventana (app de escritorio, web/js/desktop.js)
  minimize: '<path d="M3.5 8h9"/>',
  maximize: '<rect x="3.5" y="3.5" width="9" height="9" rx="1"/>',
  tray: '<path d="M2.5 9.5h3l1 1.5h3l1-1.5h3M2.5 9.5v3.5h11V9.5M4 9.5l1.2-6h5.6l1.2 6"/>',
  unmaximize: '<rect x="3.5" y="5.5" width="7" height="7" rx="1"/><path d="M5.5 3.5h6a1 1 0 0 1 1 1v6"/>',
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
  library: '<path d="M2.5 2.5v11M5.5 2.5v11M8.5 3.5l3 10M2 13.5h12"/>',
  flask: '<path d="M6 2.5h4M6.7 2.5v4L3 12.6a.6.6 0 0 0 .5.9h9a.6.6 0 0 0 .5-.9L9.3 6.5v-4M4.8 9.5h6.4"/>',
  smile: '<circle cx="8" cy="8" r="5.5"/><path d="M5.6 9.4a3 3 0 0 0 4.8 0"/><path class="solid" d="M5.5 6.2h1.2v1.2H5.5zM9.3 6.2h1.2v1.2H9.3z"/>',
  book: '<path d="M8 4.2C6.6 3 4.6 2.7 2.5 3v9.6c2.1-.3 4.1 0 5.5 1.2 1.4-1.2 3.4-1.5 5.5-1.2V3C11.4 2.7 9.4 3 8 4.2zM8 4.2v9.6"/>',
  globe: '<circle cx="8" cy="8" r="5.5"/><path d="M2.5 8h11M8 2.5c1.6 1.6 2.3 3.4 2.3 5.5S9.6 11.9 8 13.5C6.4 11.9 5.7 10.1 5.7 8S6.4 4.1 8 2.5z"/>',
  star: '<path d="M8 2.3l1.7 3.6 3.9.5-2.9 2.7.8 3.9L8 11.1 4.5 13l.8-3.9-2.9-2.7 3.9-.5z"/>',
  folder: '<path d="M2 4.5V12.5h12V5.5H7.5L6 3.5H2z"/>',
  home: '<path d="M2.5 7.2L8 2.8l5.5 4.4V13.5h-3.7V9.6H6.2v3.9H2.5z"/>',
  clock: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2.2 1.4"/>',
  tag: '<path d="M2.5 2.5h5l6 6-5 5-6-6z"/><circle class="solid" cx="5.4" cy="5.4" r="1"/>',
  search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5l3 3"/>',
  chevron: '<path d="M4.5 6.2L8 9.7l3.5-3.5"/>',
  copy: '<rect x="5.5" y="5.5" width="8" height="8"/><path d="M10.5 3.5V2.5h-8v8h1"/>',
  user: '<circle cx="8" cy="5.5" r="2.8"/><path d="M2.8 13.8c.6-2.6 2.7-4.1 5.2-4.1s4.6 1.5 5.2 4.1"/>',
  lock: '<rect x="3" y="7" width="10" height="7"/><path d="M5.2 7V5a2.8 2.8 0 0 1 5.6 0v2"/>',
  arrow: '<path d="M3 8h10M9 4l4 4-4 4"/>',
  undo: '<path d="M5.5 3.5L2.5 6.5l3 3M2.5 6.5h7a4 4 0 0 1 0 8h-2"/>',
  dice: '<rect x="2.5" y="2.5" width="11" height="11" rx="2.5"/><circle class="solid" cx="5.6" cy="5.6" r="1"/><circle class="solid" cx="10.4" cy="10.4" r="1"/><circle class="solid" cx="8" cy="8" r="1"/>',
  sidebar: '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M6 3v10"/>',
  dots: '<circle class="solid" cx="3.5" cy="8" r="1.2"/><circle class="solid" cx="8" cy="8" r="1.2"/><circle class="solid" cx="12.5" cy="8" r="1.2"/>',
  eye: '<path d="M1.8 8S4 3.8 8 3.8 14.2 8 14.2 8 12 12.2 8 12.2 1.8 8 1.8 8z"/><circle cx="8" cy="8" r="2"/>',
  reload: '<path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"/>',
  // categorías (web/js/patterns.js)
  car: '<path d="M2.5 10.5V8.2l1.4-3.4h8.2l1.4 3.4v2.3zM2.5 8.2h11"/><circle cx="5" cy="11.5" r="1.3"/><circle cx="11" cy="11.5" r="1.3"/>',
  paw: '<ellipse cx="8" cy="10.6" rx="2.6" ry="2.2"/><circle cx="4.2" cy="7.4" r="1.2"/><circle cx="6.6" cy="4.6" r="1.2"/><circle cx="9.4" cy="4.6" r="1.2"/><circle cx="11.8" cy="7.4" r="1.2"/>',
  ball: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5.3l2.4 1.8-.9 2.8h-3l-.9-2.8zM8 2.5v2.8M10.4 7.1l2.8-1M9.5 9.9l1.6 2.4M6.5 9.9l-1.6 2.4M5.6 7.1l-2.8-1"/>',
  plane: '<path d="M2.5 9.2l11-5.7-3 10-2.6-3.4zM7.9 10.1L13.5 3.5"/>',
  gamepad: '<path d="M5 4.5h6a3.5 3.5 0 0 1 3.3 4.7l-.6 1.8a1.8 1.8 0 0 1-3 .6L9.6 10H6.4l-1.1 1.6a1.8 1.8 0 0 1-3-.6l-.6-1.8A3.5 3.5 0 0 1 5 4.5z"/><path d="M5.2 6.5v2.2M4.1 7.6h2.2"/><circle class="solid" cx="10.8" cy="7.2" r=".7"/>',
  chat: '<path d="M2.5 3.5h8v5.5H6.5l-2.5 2v-2H2.5z"/><path d="M10.5 6h3v5h-1.2v1.8L10 11H7.5"/>',
  news: '<rect x="2.5" y="3" width="9" height="10"/><path d="M11.5 6h2v6.2a.8.8 0 0 1-1.6 0M4.5 5.5h5M4.5 8h5M4.5 10.5h3"/>',
  brush: '<path d="M13.5 2.5L7.6 8.4M8.8 9.6L6.4 7.2c-1.6 0-2.7 1-2.7 2.6 0 1.3-.6 2.4-1.2 3.2 2.6.3 6.3-.4 6.3-3.4z"/>',
  cap: '<path d="M1.5 6.5L8 3.5l6.5 3L8 9.5zM4.5 8v3c1 1 2.2 1.5 3.5 1.5s2.5-.5 3.5-1.5V8M14.5 6.5v3.5"/>',
  atom: '<circle class="solid" cx="8" cy="8" r="1.1"/><ellipse cx="8" cy="8" rx="6" ry="2.4"/><ellipse cx="8" cy="8" rx="6" ry="2.4" transform="rotate(60 8 8)"/><ellipse cx="8" cy="8" rx="6" ry="2.4" transform="rotate(-60 8 8)"/>',
  heart: '<path d="M8 13.2S2.3 9.8 2.3 6A2.9 2.9 0 0 1 8 4.8 2.9 2.9 0 0 1 13.7 6c0 3.8-5.7 7.2-5.7 7.2z"/>',
  shuffle: '<path d="M2.5 4.5h2.2c3.6 0 3.4 7 7 7h1.8M2.5 11.5h2.2c1.2 0 2-.8 2.6-1.8M9.5 6.3c.6-1 1.4-1.8 2.6-1.8h1.4M12 2.5l2 2-2 2M12 9.5l2 2-2 2"/>',
};

function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 16 16");
  s.setAttribute("aria-hidden", "true");
  if (cls) s.setAttribute("class", cls);
  s.innerHTML = ICONS[name] || "";
  return s;
}

// primera letra en mayúscula (los estados se arman en minúscula para poder unirlos)
const cap = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : s);

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
    // el texto va en .btn-text (así el botón puede quedar solo con su ícono cuando falta espacio)
    for (const t of [...n.childNodes]) {
      if (t.nodeType === 3 && t.textContent.trim()) t.replaceWith(el("span", { class: "btn-text", text: t.textContent.trim() }));
    }
    n.prepend(icon(n.dataset.icon));
  }
}

function meter(pct, cls = "") {
  return el("div", { class: ("meter " + cls).trim() }, Object.assign(el("i"), { style: `width:${pct}%` }));
}
