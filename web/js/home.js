"use strict";
// Translay: la portada de la biblioteca (escenario + filas), el color de acento de cada
// biblioteca y el reproductor tipo cine (controles que se esconden, transcripción plegable).
// Usa lo global de app.js, library.js y vaults.js.

/* ------------------------------------------------------------ acento: el color de la biblioteca */
function applyAccent(color) {
  const root = document.documentElement.style;
  if (!/^#[0-9a-f]{6}$/i.test(color || "")) {
    for (const k of ["--accent", "--on-accent", "--accent-soft"]) root.removeProperty(k);
    return;
  }
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16) / 255);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  root.setProperty("--accent", color);
  root.setProperty("--on-accent", lum > 0.55 ? "#111111" : "#ffffff");
  root.setProperty("--accent-soft", `color-mix(in srgb, ${color} 35%, transparent)`);
}

/* ------------------------------------------------------------ portada */
const fmtLong = (s) => {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")}` : `${m} min`;
};
const ROW_MAX = 24;

function homeRows() {
  const vs = lib.videos;
  const rows = [];
  const watching = Object.values(vs).filter((v) => v.media && v.duration && (v.position || 0) > 5 && v.position < v.duration - 10)
    .sort((a, b) => (b.opened || 0) - (a.opened || 0)).map((v) => v.id);
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
  if (h) return { v: h, en: lib.hero.en, es: lib.hero.es, label: "Seguir viendo" };
  const recent = lib.collections.find((c) => c.id === "recent")?.items || [];
  const v = recent.map((id) => lib.videos[id]).find((x) => x && x.media) || lib.videos[recent[0]];
  return v ? { v, label: "Recién agregado" } : null;
}

function renderHome() {
  const head = $("#shelf-head");
  head.hidden = true;
  const grid = $("#grid");
  grid.className = "grid home";
  grid.replaceChildren();
  const h = heroVideo();
  if (h) grid.append(hero(h));
  for (const r of homeRows()) grid.append(row(r));
}

function hero({ v, en, es, label }) {
  const pct = v.duration ? Math.min(100, (v.position || 0) / v.duration * 100) : 0;
  const play = () => { setContext({ name: label, items: [v.id], auto: false }); playItem(v.id); };
  const canOpen = !!v.media || isRemote(v);
  return el("section", { class: "hero", style: v.thumb ? `--img: url("${v.thumb}")` : null },
    el("div", { class: "hero-media" + (canOpen ? " open" : ""), on: { click: () => canOpen && play() } },
      v.thumb ? el("img", { src: v.thumb.startsWith("/thumb/yt/") ? v.thumb.replace(/\.jpg$/, "_hd.jpg") : v.thumb, alt: "" }) : null,
      canOpen ? el("span", { class: "hero-play", "aria-hidden": "true" }, icon("play")) : null),
    el("div", { class: "hero-copy" },
      el("span", { class: "label", text: [label, v.channel].filter(Boolean).join(" · ") }),
      el("h2", { text: v.title || v.id }),
      // la firma de Translay: la frase en los dos idiomas
      en || es ? el("blockquote", { class: "hero-line" },
        es ? el("p", { class: "es", text: es }) : null,
        en ? el("p", { class: "en", text: en }) : null) : null,
      el("div", { class: "hero-acts" },
        btn(pct > 1 ? "Continuar" : "Ver", { icon: "play", variant: "dark", disabled: !canOpen, onClick: play }),
        pct > 1 ? btn("Desde el inicio", { variant: "ghost", onClick: () => { v.position = 0; play(); } }) : null,
        btn("Exportar", { icon: "download", variant: "ghost", onClick: () => openExport([v.id]) })),
      pct > 1 ? el("div", { class: "hero-prog" }, meter(pct), el("small", { text: v.duration >= 3600 ? `${fmtLong(v.position)} de ${fmtLong(v.duration)}` : `${fmtDur(v.position)} de ${fmtDur(v.duration)}` })) : null));
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
  return el("span", { class: "ring", title: `Traducido ${Math.round(p.asr * 100)} % · doblado ${Math.round(p.dub * 100)} %` }, s);
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

// transcripción plegable (se recuerda)
function setSide(open) {
  document.body.classList.toggle("side-off", !open);
  const b = $("#side-toggle");
  if (b) { b.classList.toggle("on", open); b.title = open ? "Ocultar la transcripción" : "Mostrar la transcripción"; }
  try { localStorage.setItem("vt-side", open ? "1" : "0"); } catch (e) {}
}
$("#side-toggle")?.addEventListener("click", () => setSide(document.body.classList.contains("side-off")));
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
// El botón junto al logo solo pliega la barra lateral (biblioteca, reproductor, Cola y Preferencias).
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
$("#import-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  importPop.hidden = !importPop.hidden;
  if (!importPop.hidden) $("#yt-url").focus();
});
importPop.addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", () => { importPop.hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") importPop.hidden = true; });
// al importar, el panel se cierra solo
$("#yt").addEventListener("submit", () => setTimeout(() => { importPop.hidden = true; }, 0));
$("#file").addEventListener("change", () => { importPop.hidden = true; });
// buscar desde cualquier vista lleva a la biblioteca
$("#lib-q").addEventListener("focus", () => { if (currentView() !== "library") setView("library"); });
