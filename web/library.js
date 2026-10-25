"use strict";
// Biblioteca: videos traducidos y colecciones. Usa lo global de app.js
// ($, state, send, loadVideo, vEn).

const lib = { videos: {}, collections: [], sel: "recent", promptSave: false,
  queue: { paused: false, current: null, jobs: [] } };

/* ------------------------------------------------------------ vista */
function setView(view) {
  document.body.classList.toggle("view-library", view === "library");
  $("#view").textContent = view === "library" ? "Volver al video" : "Biblioteca";
  $("#view").hidden = view === "library" && !state.videoId;
  if (view === "library") {
    if (!vEn.paused) vEn.pause();
    send({ type: "unwatch" });
    send({ type: "library" });
    renderLibrary();
  }
  closeSave();
}
$("#view").addEventListener("click", () =>
  setView(document.body.classList.contains("view-library") ? "player" : "library"));

function libraryUpdate(m) {
  lib.videos = m.videos;
  lib.collections = m.collections;
  if (!lib.collections.some((c) => c.id === lib.sel)) lib.sel = "recent";
  renderLibrary();
  renderSaveList();
  if (lib.promptSave && state.videoId && lib.videos[state.videoId]) {
    lib.promptSave = false;
    openSave();  // al traducir un video nuevo: elegir si guardarlo en una colección
  }
}

function fmtDur(s) {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, ss = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(ss).padStart(2, "0");
}

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

function renderLibrary() {
  if (!document.body.classList.contains("view-library")) return;
  // columna de colecciones, agrupadas por tipo
  const nav = $("#collections");
  nav.replaceChildren();
  const groups = [["auto", null], ["propia", "Colecciones"], ["canal", "Canales"], ["categoría", "Categorías"]];
  for (const [kind, label] of groups) {
    const items = lib.collections.filter((c) => c.kind === kind);
    if (label && (items.length || kind === "propia")) nav.append(el("h4", { text: label }));
    for (const c of items) {
      nav.append(el("button", {
        class: "item" + (c.id === lib.sel ? " active" : ""), type: "button",
        on: { click: () => { lib.sel = c.id; renderLibrary(); } },
      }, el("span", { text: c.name }), el("span", { text: String(c.items.length) })));
    }
    if (kind === "propia") {
      const input = el("input", { type: "text", placeholder: "Nueva colección", maxlength: 80 });
      nav.append(el("form", { on: { submit: (e) => {
        e.preventDefault();
        if (input.value.trim()) send({ type: "coll_create", name: input.value.trim() });
        input.value = "";
      } } }, input, el("button", { class: "btn", type: "submit", text: "Crear" })));
    }
  }

  // estante: encabezado + tarjetas
  const c = lib.collections.find((x) => x.id === lib.sel) || { name: "Recientes", items: [], kind: "auto" };
  const head = $("#shelf-head");
  head.replaceChildren(...[el("h2", { text: c.name }),
    c.kind !== "auto" ? el("small", { text: c.kind }) : null,
    c.kind === "propia" ? el("button", { class: "btn", type: "button", text: "Eliminar colección", on: { click: () => {
      if (confirm(`¿Eliminar la colección "${c.name}"? Los videos no se borran.`)) send({ type: "coll_delete", coll: c.id });
    } } }) : null].filter(Boolean));

  const grid = $("#grid");
  grid.replaceChildren();
  if (!c.items.length) {
    grid.append(el("div", { class: "empty", text: c.kind === "propia" ? "colección vacía" : "sin videos" }));
    return;
  }
  for (const id of c.items) {
    const v = lib.videos[id];
    if (v) grid.append(card(v, c));
  }
}

function card(v, coll) {
  const pct = v.duration ? Math.min(100, (v.position || 0) / v.duration * 100) : 0;
  const thumb = el("div", { class: "thumb" },
    v.thumb ? el("img", { src: v.thumb, alt: "", loading: "lazy" }) : null,
    v.duration ? el("span", { class: "dur", text: fmtDur(v.duration) }) : null,
    pct > 1 ? el("div", { class: "prog" }, Object.assign(el("i"), { style: `width:${pct}%` })) : null);
  const sub = [v.channel, v.source === "youtube" ? "YouTube" : "archivo"].filter(Boolean).join(" · ");
  return el("article", { class: "card" }, thumb,
    el("div", { class: "meta" }, el("h3", { text: v.title || v.id }), el("p", { text: sub })),
    el("div", { class: "actions" },
      el("button", { class: "btn", type: "button", text: "Ver", disabled: !v.media,
        title: v.media ? null : "La copia del archivo aún no está en la biblioteca",
        on: { click: () => playFromLibrary(v) } }),
      canProcess(v) ? el("button", { class: "btn ghost", type: "button", text: "Procesar",
        title: "Traducir y doblar en segundo plano",
        on: { click: () => send({ type: "queue_add", video: v.id }) } }) : null,
      coll.kind === "propia" ? el("button", { class: "btn ghost", type: "button", text: "Quitar",
        on: { click: () => send({ type: "coll_toggle", coll: coll.id, video: v.id, on: false }) } }) : null));
}

function playFromLibrary(v) {
  const resume = v.position > 5 && v.position < (v.duration || 0) - 10 ? v.position : 0;
  loadVideo(v.media, v.id, v.title, v.audio, { fromLibrary: true, position: resume });
  setView("player");
}

function canProcess(v) {
  const job = lib.queue.jobs.find((j) => j.id === v.id);
  const inQueue = job && (job.state === "en cola" || job.state === "procesando");
  return !!v.media && !inQueue && (!v.progress || v.progress.dub < 0.97);
}

/* ------------------------------------------------------------ cola en segundo plano */
function queueUpdate(m) {
  const before = lib.queue.jobs.map((j) => j.id + j.state).join();
  lib.queue = m;
  // al terminar o cambiar un trabajo, refrescar el avance de las tarjetas
  if (before !== m.jobs.map((j) => j.id + j.state).join()) send({ type: "library" });
  renderQueuePanel();
}

// Panel de la cola (como las descargas del navegador): lo que se procesa ahora,
// lo que espera y lo terminado.
function renderQueuePanel() {
  const q = lib.queue;
  const active = q.jobs.filter((j) => j.state === "en cola" || j.state === "procesando");
  const nDown = Object.keys(state.downloads).length;
  const badge = $("#queue-badge");
  badge.textContent = String(active.length + nDown);
  badge.hidden = !(active.length + nDown);
  $("#queue-btn").classList.toggle("busy", nDown > 0 || q.jobs.some((j) => j.state === "procesando"));
  const running = q.jobs.find((j) => j.state === "procesando");
  $("#queue-state").textContent = q.paused
    ? (running && running.watching ? "en pausa · sigue el video que ves" : "en pausa · reposo")
    : running ? "procesando" : active.length ? "en espera" : "sin trabajos · reposo";
  $("#queue-toggle").textContent = q.paused ? "Reanudar" : "Pausar";
  $("#queue-clear").hidden = !q.jobs.some((j) => j.state === "listo" || j.state === "error");
  const ul = $("#queue-list");
  ul.replaceChildren();
  // descargas de YouTube en curso: cada etapa visible
  const downloads = Object.values(state.downloads);
  for (const d of downloads) {
    const idx = DOWNLOAD_STEPS.findIndex(([k]) => k === d.stage);
    const steps = el("div", { class: "steps" }, ...DOWNLOAD_STEPS.map(([k, text], i) =>
      el("span", { class: i < idx ? "done" : i === idx ? "now" : "", text })));
    const pct = d.stage === "video" || d.stage === "audio" ? d.pct : idx >= 3 ? 100 : 0;
    ul.append(el("li", { class: "qitem run" },
      el("div", { class: "qthumb" }),
      el("div", { class: "qbody" },
        el("strong", { text: d.title || "Video de YouTube" }),
        steps,
        el("div", { class: "qbar" }, Object.assign(el("i"), { style: `width:${pct}%` })),
        el("small", { text: downloadText(d) })),
      el("div", { class: "qactions" })));
  }
  if (!q.jobs.length && !downloads.length) ul.append(el("li", { class: "empty-row", text: "nada en la cola" }));
  for (const j of q.jobs) {
    const v = lib.videos[j.id] || { id: j.id, title: j.id };
    const pct = Math.round(j.dub * 100);
    const label = j.state === "listo" ? "listo"
      : j.state === "error" ? "error"
      : j.state === "procesando" ? (j.watching ? `viendo · ${pct} %` : `${pct} %`)
      : q.paused && !j.watching ? "en pausa" : "en espera";
    ul.append(el("li", { class: "qitem" + (j.state === "procesando" ? " run" : "") },
      el("div", { class: "qthumb" }, v.thumb ? el("img", { src: v.thumb, alt: "" }) : null),
      el("div", { class: "qbody" },
        el("strong", { text: v.title || j.id }),
        el("div", { class: "qbar" }, Object.assign(el("i"), { style: `width:${pct}%` })),
        el("small", { text: j.error || label })),
      el("div", { class: "qactions" },
        el("button", { class: "btn", type: "button", text: "Ver", disabled: !v.media,
          on: { click: () => { closeQueue(); playFromLibrary(v); } } }),
        el("button", { class: "btn ghost", type: "button", text: "Quitar",
          on: { click: () => send({ type: "queue_remove", video: j.id }) } }))));
  }
}
function openQueue() { renderQueuePanel(); $("#queue-pop").hidden = false; }
function closeQueue() { $("#queue-pop").hidden = true; }
$("#queue-btn").addEventListener("click", (e) => { e.stopPropagation(); $("#queue-pop").hidden ? openQueue() : closeQueue(); });
$("#queue-pop").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", closeQueue);
$("#queue-toggle").addEventListener("click", () => send({ type: lib.queue.paused ? "queue_resume" : "queue_pause" }));
$("#queue-clear").addEventListener("click", () => send({ type: "queue_clear" }));

/* ------------------------------------------------------------ guardar en colección */
function renderSaveList() {
  const ul = $("#save-list");
  ul.replaceChildren();
  const own = lib.collections.filter((c) => c.kind === "propia");
  for (const c of own) {
    const box = el("input", { type: "checkbox", checked: c.items.includes(state.videoId),
      on: { change: (e) => send({ type: "coll_toggle", coll: c.id, video: state.videoId, on: e.target.checked }) } });
    ul.append(el("li", {}, el("label", {}, box, el("span", { text: c.name }))));
  }
}
function openSave() { renderSaveList(); $("#save-pop").hidden = false; }
function closeSave() { $("#save-pop").hidden = true; }
$("#save").addEventListener("click", (e) => { e.stopPropagation(); $("#save-pop").hidden ? openSave() : closeSave(); });
$("#save-pop").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", closeSave);
$("#save-new").addEventListener("submit", (e) => {
  e.preventDefault();
  const name = $("#save-name").value.trim();
  if (name && state.videoId) send({ type: "coll_create", name, video: state.videoId });
  $("#save-name").value = "";
});

/* ------------------------------------------------------------ registro al abrir */
// Lo llama loadVideo: registra el video y, si es un archivo local, sube una copia
// y su miniatura para poder volver a verlo desde la biblioteca.
function libOnOpen({ id, name, file, fromLibrary, position }) {
  const known = !!lib.videos[id];
  if (!fromLibrary && !known) lib.promptSave = true;
  vEn.addEventListener("loadedmetadata", function once() {
    vEn.removeEventListener("loadedmetadata", once);
    if (position) vEn.currentTime = position;
    send({ type: "lib_register", id, title: name, duration: vEn.duration,
      source: file ? "file" : (id.startsWith("yt_") ? "youtube" : "file") });
    if (file) {
      if (!lib.videos[id]?.media) {
        fetch(`/api/upload/${id}?name=${encodeURIComponent(file.name)}`, { method: "PUT", body: file })
          .then(() => send({ type: "library" })).catch(() => {});
      }
      if (!lib.videos[id]?.thumb) makeThumb(URL.createObjectURL(file), id);
    }
  });
}

function makeThumb(src, id) {
  // fotograma al 10 % del video (máx. 30 s), en un <video> aparte
  const v = document.createElement("video");
  v.muted = true;
  v.preload = "auto";
  v.src = src;
  v.addEventListener("loadedmetadata", () => { v.currentTime = Math.min(30, (v.duration || 10) * 0.1); });
  v.addEventListener("seeked", () => {
    const c = document.createElement("canvas");
    c.width = 480;
    c.height = Math.round(480 * (v.videoHeight / v.videoWidth || 9 / 16));
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    c.toBlob((b) => b && fetch(`/api/thumb/${id}`, { method: "PUT", body: b }).then(() => send({ type: "library" })),
      "image/jpeg", 0.82);
  }, { once: true });
}

setView("library");
