"use strict";
// Translay: la portada de la biblioteca (escenario + filas), el color de acento de cada
// biblioteca y el reproductor tipo cine (controles que se esconden, transcripción plegable).
// Usa lo global de app.js, library.js y vaults.js.

/* ------------------------------------------------------------ acento: el color de la biblioteca */
// el color elegido va en --accent-base; tokens.css lo vuelve pastel en claro (y su texto, un tono profundo del mismo
// color) y lo deja tal cual en oscuro (texto blanco o casi negro según su luz)
function applyAccent(color) {
  const root = document.documentElement.style;
  // data-lib-accent: con el color de la biblioteca, los interruptores también lo usan (controls.css)
  if (!/^#[0-9a-f]{6}$/i.test(color || "")) {
    for (const k of ["--accent-base", "--on-accent-dark"]) root.removeProperty(k);
    delete document.documentElement.dataset.libAccent;
    return;
  }
  document.documentElement.dataset.libAccent = "";
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  root.setProperty("--accent-base", color);
  root.setProperty("--on-accent-dark", lum > 0.55 ? "#111111" : "#ffffff");
}

// Ajustes › Apariencia: el color de énfasis elegido; con «Color de cada biblioteca», el de la abierta
function syncAccent() {
  applyAccent(prefs.accent_lib && typeof vaults !== "undefined" ? currentVault().color : prefs.accent_color || null);
}

/* ------------------------------------------------------------ portada */
const fmtLong = (s) => {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
};
const ROW_MAX = 24;

function homeRows(skip) {
  const vs = lib.videos;
  const rows = [];
  const watching = Object.values(vs).filter((v) => v.media && v.duration && (v.position || 0) > 5 && v.position < v.duration - 10)
    .sort((a, b) => (b.opened || 0) - (a.opened || 0)).map((v) => v.id).filter((id) => id !== skip);  // el destacado no se repite
  if (watching.length) rows.push({ id: "recent", title: "Seguir viendo", items: watching, more: false });
  const byId = Object.fromEntries(lib.collections.map((c) => [c.id, c]));
  if (byId.recent?.items.length) rows.push({ id: "recent", title: "Recientes", items: byId.recent.items });
  for (const c of lib.collections.filter((c) => (c.kind === "propia" || c.kind === "playlist") && c.items.length).slice(0, 8)) {
    rows.push({ id: c.id, title: c.name, items: c.items, kind: c.kind === "playlist" ? "Playlist" : "" });
  }
  const chans = lib.collections.filter((c) => c.kind === "canal" && c.items.length > 1).sort((a, b) => b.items.length - a.items.length);
  for (const c of chans.slice(0, 4)) rows.push({ id: c.id, title: c.name, items: c.items, kind: "Canal" });
  const cats = lib.collections.filter((c) => c.kind === "categoría" && c.items.length > 1).sort((a, b) => b.items.length - a.items.length);
  for (const c of cats.slice(0, 2)) rows.push({ id: c.id, title: c.name, items: c.items, kind: "Categoría" });
  return rows;
}

function heroVideo() {
  const h = lib.hero && lib.videos[lib.hero.video];
  if (h) return { v: h, en: lib.hero.en, es: lib.hero.es, ideas: lib.hero.ideas, chapters: lib.hero.chapters,
    label: (h.position || 0) > 5 ? "Seguir viendo" : "Recién agregado" };
  const recent = lib.collections.find((c) => c.id === "recent")?.items || [];
  const v = recent.map((id) => lib.videos[id]).find((x) => x && x.media) || lib.videos[recent[0]];
  return v ? { v, label: (v.position || 0) > 5 ? "Seguir viendo" : "Recién agregado" } : null;
}

function renderHome() {
  const head = $("#shelf-head");
  // con videos elegidos en las filas: las acciones arriba, fuera del desplazamiento (antes no aparecían)
  head.hidden = !lib.picked.size;
  if (lib.picked.size) renderShelfHead({ id: "home", name: "Inicio", kind: "auto", items: [...lib.picked] });
  const grid = $("#grid");
  grid.className = "grid home";
  grid.replaceChildren();
  if (!Object.keys(lib.videos).length) { grid.append(emptyLibrary()); return; }
  // lo que sigues viendo, grande y con su luz detrás; agregar y grabar están en la barra de arriba
  const lead = heroVideo();
  const light = homeLight(lead?.v);
  if (light) grid.append(light);
  if (lead) grid.append(hero(lead));
  for (const r of homeRows(lead?.v.id)) grid.append(row(r));
}

// la biblioteca vacía: lo que se puede hacer y el botón de Agregar (el mismo de la barra)
function emptyLibrary() {
  return emptyState("film", "Tu biblioteca está vacía",
    "Agrega un enlace de YouTube o Dropbox, sube un archivo o graba la pantalla. Los videos aparecen aquí mientras se traducen.",
    "div", btn("Agregar video", { icon: "plus", variant: "dark", onClick: () => $("#import-btn").click() }));
}

/* ------------------------------------------------------------ fondo del inicio (Ajustes › Apariencia)
   una escena ASCII con los colores del tema (web/js/scenes.js) o una imagen propia, oscurecida
   (se sube a data/ui/home-bg.jpg). */
function homeBgMode() {
  const m = prefs.home_bg;
  return m === "imagen" ? (prefs.home_bg_rev ? m : "translay") : SCENES[m] ? m : "translay";  // los fondos de antes: la escena por defecto
}

function homeLight(v, mode = homeBgMode(), preview = false) {
  const box = el("div", { class: "home-light " + (mode === "imagen" ? "imagen" : "scene-bg"), "aria-hidden": "true" });
  if (mode === "imagen") {
    const img = el("img", { src: `/ui/home-bg.jpg?v=${prefs.home_bg_rev}`, alt: "" });
    img.addEventListener("load", () => lightTone(box, img), { once: true });
    box.append(img);
    return box;
  }
  // la escena va en la capa de toda la app (web/js/scenes.js › syncSceneBg); aquí solo en la vista previa de Ajustes
  if (preview) mountScene(box, mode);
  requestAnimationFrame(() => lightTone(box, null));
  return box;
}

/* el texto sobre la luz siempre legible: se mide el color que queda detrás del texto (la mitad derecha de la
   imagen, ya mezclada con el fondo según su opacidad) y el texto del destacado va claro u oscuro (--hl-fg) */
function lightTone(box, img) {
  const host = box.parentElement;
  if (!host) return;
  const rgb = (c) => (c.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
  const bg = rgb(getComputedStyle(document.documentElement).backgroundColor);
  let src = [0, 0, 0];
  let alpha = 0.3;
  if (img) {
    try {
      const c = document.createElement("canvas");
      c.width = 16; c.height = 9;
      const g = c.getContext("2d", { willReadFrequently: true });
      g.drawImage(img, 0, 0, 16, 9);
      const d = g.getImageData(8, 0, 8, 9).data;  // la mitad derecha: donde va el texto
      const sum = [0, 0, 0];
      for (let i = 0; i < d.length; i += 4) { sum[0] += d[i]; sum[1] += d[i + 1]; sum[2] += d[i + 2]; }
      src = sum.map((x) => x / (d.length / 4));
      alpha = parseFloat(getComputedStyle(img).opacity) || 0.5;
    } catch { return; }  // imagen de otro origen: queda el color del tema
  } else {
    const probe = el("i", { style: "color: var(--accent)" });
    box.append(probe);
    src = rgb(getComputedStyle(probe).color);
    probe.remove();
  }
  const mix = src.map((x, i) => x * alpha + bg[i] * (1 - alpha));
  const lin = mix.map((x) => { x /= 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
  const lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  host.classList.toggle("on-bright", lum > 0.36);
  host.classList.toggle("on-dark", lum <= 0.36);
}

function hero({ v, en, es, label, ideas, chapters }) {
  const pct = v.duration ? Math.min(100, (v.position || 0) / v.duration * 100) : 0;
  const play = () => { setContext({ name: label, items: [v.id], auto: false }); playItem(v.id); };
  const canOpen = !!v.media || isRemote(v);
  return el("section", { class: "hero lite", style: v.thumb ? `--img: url("${v.thumb}")` : null },
    el("div", { class: "hero-media" + (canOpen ? " open" : ""), on: { click: () => canOpen && play() } },
      v.thumb ? el("img", { src: v.thumb.startsWith("/thumb/yt/") ? v.thumb.replace(/\.jpg$/, "_hd.jpg") : v.thumb, alt: "" }) : null,
      canOpen ? el("span", { class: "hero-play", "aria-hidden": "true" }, icon("play")) : null),
    el("div", { class: "hero-copy" },
      el("span", { class: "label", text: [label, v.channel].filter(Boolean).join(" · ") }),
      el("h2", { text: v.title || v.id }),
      // la firma de Translay: la frase en los dos idiomas
      en || es ? el("blockquote", { class: "hero-line" },
        es && !(transcribeMode() && en) ? el("p", { class: "es", text: es }) : null,
        en && !(es && sameText(en, es) && !transcribeMode()) ? el("p", { class: "en", text: en }) : null) : null,
      el("div", { class: "hero-acts" },
        btn(pct > 1 ? "Continuar" : "Ver", { icon: "play", variant: "dark", disabled: !canOpen, onClick: play }),
        pct > 1 ? btn("Desde el inicio", { variant: "ghost", onClick: () => { v.position = 0; play(); } }) : null,
        btn("Exportar", { icon: "download", variant: "ghost", onClick: () => openExport([v.id]) })),
      pct > 1 ? el("div", { class: "hero-prog" }, meter(pct), el("small", { text: v.duration >= 3600 ? `${fmtLong(v.position)} de ${fmtLong(v.duration)}` : `${fmtDur(v.position)} de ${fmtDur(v.duration)}` })) : null,
      heroSummary(ideas, chapters, (t) => { v.position = t; play(); })));
}

// lo del resumen que ayuda a retomar: ideas clave y los primeros capítulos (cada uno lleva a su momento);
// en una pantalla angosta se oculta (CSS)
function heroSummary(ideas, chapters, seek) {
  if (!ideas?.length && !chapters?.length) return null;
  return el("div", { class: "hero-sum" },
    ideas?.length ? el("h4", { text: "Ideas clave" }) : null,
    ideas?.length ? el("ul", {}, ...ideas.map((t) => el("li", { text: t }))) : null,
    chapters?.length ? el("div", { class: "hero-chs" }, ...chapters.map((c) => el("button", { type: "button", class: "hero-ch",
      title: "Ver desde aquí", on: { click: () => seek(c.t) } }, el("b", { text: fmtDur(c.t) }), c.title))) : null);
}

function row(r) {
  const coll = lib.collections.find((c) => c.id === r.id) || { id: r.id, name: r.title, kind: "auto", items: r.items };
  const strip = el("div", { class: "strip" });
  r.items.slice(0, ROW_MAX).forEach((id, i) => {
    const v = lib.videos[id];
    if (v) strip.append(card(v, coll, i));
  });
  const scrollBy = (dir) => strip.scrollBy({ left: dir * strip.clientWidth * 0.9, behavior: "smooth" });
  const prev = el("button", { type: "button", class: "strip-nav prev", "aria-label": "Anteriores", hidden: true, on: { click: () => scrollBy(-1) } }, icon("chevron"));
  const next = el("button", { type: "button", class: "strip-nav next", "aria-label": "Siguientes", hidden: true, on: { click: () => scrollBy(1) } }, icon("chevron"));
  // cada flecha solo si hay más videos hacia ese lado; centradas en la miniatura
  const sync = () => {
    const max = strip.scrollWidth - strip.clientWidth;
    prev.hidden = strip.scrollLeft <= 2;
    next.hidden = strip.scrollLeft >= max - 2;
    const th = strip.querySelector(".thumb")?.offsetHeight;
    if (th) wrap.style.setProperty("--nav-y", `${th / 2}px`);
  };
  strip.addEventListener("scroll", sync, { passive: true });
  new ResizeObserver(sync).observe(strip);
  const wrap = el("div", { class: "strip-wrap" }, prev, strip, next);
  return el("section", { class: "row", "data-coll": r.id },
    el("header", {},
      coll.kind !== "auto" ? collBadge(coll, "md") : null,
      el("h3", {}, el("button", { type: "button", on: { click: () => openColl(r.id) } }, r.title)),
      r.more !== false && r.items.length > 4 ? btn("Ver todo", { size: "xs", variant: "ghost", onClick: () => openColl(r.id) }) : null),
    wrap);
}
function openColl(id) {
  lib.sel = id;
  lib.picked.clear();
  renderLibrary();
}

// anillo de avance: traducido (suave) y doblado (lleno), en el color de la biblioteca
function progressRing(p) {
  if (!p || (!p.asr && !p.dub)) return null;
  if (p.dub >= 0.995) return null;  // listo: lo dice la tarjeta («Listo en español»)
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 36 36");
  s.innerHTML = `<circle cx="18" cy="18" r="14" class="r0"/><circle cx="18" cy="18" r="14" class="r1" pathLength="100" stroke-dasharray="${Math.round(p.asr * 100)} 100"/>`
    + `<circle cx="18" cy="18" r="14" class="r2" pathLength="100" stroke-dasharray="${Math.round(p.dub * 100)} 100"/>`;
  return el("span", { class: "ring", title: transcribeMode() ? `Transcrito ${Math.round(p.asr * 100)} %`
    : `Traducido ${Math.round(p.asr * 100)} % · doblado ${Math.round(p.dub * 100)} %` }, s);
}

/* ------------------------------------------------------------ reproductor: controles que se esconden */
let idleTimer = null;
function wake() {
  document.body.classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    const overCtl = document.querySelector("#ctrl:hover, .vbar:hover, .popover:not([hidden])");
    if (!vEn.paused && !overCtl && currentView() === "player") document.body.classList.add("idle");
  }, 2600);
}
for (const ev of ["mousemove", "pointerdown", "keydown", "touchstart"]) document.addEventListener(ev, wake, { passive: true });
vEn.addEventListener("pause", wake);
vEn.addEventListener("play", wake);

// el panel del video (transcripción, agente, personas): se oculta arrastrando su borde (web/js/panels.js)
// o desde el clic derecho; se recuerda
function setSide(open) {
  document.body.classList.toggle("side-off", !open);
  try { localStorage.setItem("vt-side", open ? "1" : "0"); } catch (e) {}
}
try { setSide(localStorage.getItem("vt-side") !== "0"); } catch (e) { setSide(true); }

/* ------------------------------------------------------------ scroll sin barras: bordes que se desvanecen */
const FADE_Y = "#grid, #collections, #transcript, #upnext, #people, #prefs-body, #prefs-nav, #qlist, #qnav, .popover ul, .acc-evs";
const FADE_X = ".strip, .libside .collections";
const FADE = 36;
function updateFade(box) {
  const x = box.classList.contains("fades-x");
  const pos = x ? box.scrollLeft : box.scrollTop;
  const max = x ? box.scrollWidth - box.clientWidth : box.scrollHeight - box.clientHeight;
  const a = Math.min(FADE, Math.max(0, pos)), b = Math.min(FADE, Math.max(0, max - pos - 1));
  box.style.setProperty(x ? "--fl" : "--ft", `${a}px`);
  box.style.setProperty(x ? "--fr" : "--fb", `${b}px`);
}
function scanFades() {
  const horiz = new Set(document.querySelectorAll(FADE_X));
  for (const box of document.querySelectorAll(`${FADE_Y}, ${FADE_X}`)) {
    const x = horiz.has(box) && getComputedStyle(box).overflowX !== "visible" && box.scrollWidth > box.clientWidth + 1;
    box.classList.toggle("fades-x", x);
    box.classList.toggle("fades-y", !x);
    updateFade(box);
  }
}
document.addEventListener("scroll", (e) => {
  const t = e.target;
  if (t.classList && (t.classList.contains("fades-x") || t.classList.contains("fades-y"))) updateFade(t);
}, { capture: true, passive: true });
let fadeRaf = 0;
const queueFades = () => { if (!fadeRaf) fadeRaf = requestAnimationFrame(() => { fadeRaf = 0; scanFades(); }); };
new MutationObserver(queueFades).observe(document.body, { childList: true, subtree: true });
addEventListener("resize", queueFades);
queueFades();


/* ------------------------------------------------------------ barra lateral colapsable (se recuerda) */
// El botón junto al logo solo pliega la barra lateral (biblioteca, reproductor, Cola y Ajustes).
function syncSideBtn() {
  const b = $("#side-btn");
  const t = document.body.classList.contains("side-mini") ? "Expandir la barra lateral" : "Contraer la barra lateral";
  b.title = t;
  b.setAttribute("aria-label", t);
}
function setSideMini(on) {
  document.body.classList.toggle("side-mini", on);
  try { localStorage.setItem("vt-side-mini", on ? "1" : ""); } catch (e) { /* sin almacenamiento */ }
  syncSideBtn();
}
try { setSideMini(localStorage.getItem("vt-side-mini") === "1"); } catch (e) { /* sin almacenamiento */ }
$("#side-btn").addEventListener("click", () => setSideMini(!document.body.classList.contains("side-mini")));

/* ------------------------------------------------------------ marca e importar */
function goHome() {
  lib.sel = "home";
  lib.picked.clear();
  if (typeof closeSearch === "function") closeSearch();
  if (currentView() !== "library") setView("library");
  else renderLibrary();
  $("#grid")?.scrollTo({ top: 0, behavior: "smooth" });
}
for (const b of document.querySelectorAll(".bar .brand")) {
  b.setAttribute("role", "link");
  b.tabIndex = 0;
  b.title = "Ir al inicio";
  b.addEventListener("click", goHome);
  b.addEventListener("keydown", (e) => { if (e.key === "Enter") goHome(); });
}
const importPop = $("#import-pop");
function toggleImportPop(open = importPop.hidden) {
  importPop.hidden = !open;
  if (open) $("#yt-url").focus();
}
// «Agregar» abre el panel (enlace, archivos, grabar, varios enlaces); «Grabar» va directo a grabar
$("#import-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleImportPop(); });
$("#rec-btn").addEventListener("click", () => { importPop.hidden = true; openCapture(); });
importPop.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("pointerdown", (e) => {
  if (!e.target.closest(".import-wrap, .menu, dialog")) importPop.hidden = true;
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") importPop.hidden = true; });
// al importar, el panel se cierra solo
$("#file").addEventListener("change", () => { importPop.hidden = true; });
$("#multi-btn").addEventListener("click", () => { importPop.hidden = true; openMulti(""); });
// buscar desde cualquier vista lleva a la biblioteca
$("#lib-q").addEventListener("focus", () => { if (currentView() !== "library") setView("library"); });
// alto del encabezado (en el celular es fijo arriba y cambia de alto): las acciones de una selección
// quedan justo debajo (layout.css)
const topBar = document.querySelector(".bar");
const syncBarH = () => document.documentElement.style.setProperty("--bar-h", `${Math.ceil(topBar.getBoundingClientRect().height)}px`);
new ResizeObserver(syncBarH).observe(topBar);
addEventListener("resize", syncBarH);
syncBarH();
