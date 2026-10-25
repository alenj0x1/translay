"use strict";
// Biblioteca: videos traducidos, colecciones y playlists; selección de varios
// videos; "Siguientes" del video que se ve; cola y exportaciones. Usa lo global
// de app.js ($, state, send, loadVideo, vEn, toast, setStatus…).

const lib = { videos: {}, collections: [], sel: "recent", promptSave: false,
  queue: { paused: false, current: null, jobs: [] },
  picked: new Set(),     // videos seleccionados en el estante
  ctx: null,             // colección del video que se ve: {name, coll?, items?, auto}
  keepCtxFor: null,      // video que se abre desde "Siguientes" (conserva el contexto)
  exports: [], mine: new Set(), delivered: new Set(),
  lastView: "library" };

/* ------------------------------------------------------------ vistas */
function currentView() {
  const b = document.body.classList;
  return b.contains("view-prefs") ? "prefs" : b.contains("view-library") ? "library" : "player";
}
function setView(view) {
  const before = currentView();
  if (before !== "prefs" && view === "prefs") lib.lastView = before;
  document.body.classList.toggle("view-library", view === "library");
  document.body.classList.toggle("view-prefs", view === "prefs");
  $("#prefs-btn").classList.toggle("on", view === "prefs");
  $("#view").textContent = view === "library" ? "Volver al video" : "Biblioteca";
  $("#view").hidden = view === "library" && !state.videoId;
  // fuera del reproductor, el video sigue en miniatura (abajo a la derecha) mientras
  // se esté reproduciendo; en pausa se guarda hasta volver
  if (view !== "player" && before === "player" && state.videoId) {
    lib.mini = !vEn.paused;
    if (!lib.mini) send({ type: "unwatch" });
  }
  if (view === "player") lib.mini = false;
  document.body.classList.toggle("mini", !!lib.mini && view !== "player");
  // de vuelta al video: la cola vuelve a darle prioridad desde donde quedó
  if (view === "player" && before !== "player" && state.videoId && state.serverSide) {
    send({ type: "watch", video: state.videoId, t: vEn.currentTime || 0 });
  }
  if (view === "library") {
    send({ type: "library" });
    renderLibrary();
  }
  if (view === "prefs") markPrefsNav();
  closeSave();
}
function togglePrefs() {
  setView(currentView() === "prefs" ? (lib.lastView === "player" && state.videoId ? "player" : "library") : "prefs");
}
$("#view").addEventListener("click", () => setView(currentView() === "library" ? "player" : "library"));

function libraryUpdate(m) {
  lib.videos = m.videos;
  lib.collections = m.collections;
  if (!lib.collections.some((c) => c.id === lib.sel)) lib.sel = "recent";
  for (const id of [...lib.picked]) if (!lib.videos[id]) lib.picked.delete(id);
  softRenderLibrary();
  renderSaveList();
  renderUpNext();
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

const jobOf = (id) => lib.queue.jobs.find((j) => j.id === id);
const playlistOf = (id) => lib.collections.find((c) => c.kind === "playlist" && c.items.includes(id));

// estado de un video aún sin descargar (playlist)
function pendingText(v) {
  if (v.media) return "";
  const j = jobOf(v.id);
  if (j?.dl) return j.dl.stage === "video" || j.dl.stage === "audio" ? `descargando ${j.dl.pct} %` : `${j.dl.stage}…`;
  if (j?.state === "error") return "error al descargar";
  return j ? "en cola · sin descargar" : "sin descargar";
}

/* ------------------------------------------------------------ biblioteca */
// Lo que llega solo (avance de la cola, descargas) NO redibuja la biblioteca: si el
// estante se reemplaza entre que se presiona y se suelta un botón, el clic se pierde
// (por eso "Ver" pedía dos clics). Se redibuja solo si cambió qué se muestra; si no,
// las tarjetas se actualizan en su lugar.
function shelfSignature() {
  const c = lib.collections.find((x) => x.id === lib.sel);
  return JSON.stringify([lib.sel, c?.items, [...lib.picked], prefs.lib_channels,
    lib.collections.map((x) => [x.id, x.name, x.items.length]),
    c?.items.map((id) => [lib.videos[id]?.title, lib.videos[id]?.thumb, !!lib.videos[id]?.media])]);
}
function softRenderLibrary() {
  if (currentView() !== "library") return;
  if (shelfSignature() !== lib.shelfSig) renderLibrary();
  else refreshCards();
}
function refreshCards() {
  if (currentView() !== "library") return;
  for (const art of document.querySelectorAll("#grid .card[data-id]")) {
    const v = lib.videos[art.dataset.id];
    if (!v) continue;
    const old = art.querySelector(".stage-bar");
    const bar = progressBar(v);
    if (old && bar) { if (old.outerHTML !== bar.outerHTML) old.replaceWith(bar); }
    else if (old) old.remove();
    else if (bar) art.querySelector(".actions").before(bar);
    const pend = art.querySelector(".pending-dl");
    const text = pendingText(v);
    if (pend && text) { if (pend.textContent !== text) pend.textContent = text; }
    else if (pend) pend.remove();
    const btn = art.querySelector(".actions .btn");
    const dl = downloadPct(v);
    btn.classList.toggle("dl", dl !== null);
    const label = dl !== null ? `Descargando ${dl} %` : "Ver";
    if (btn.textContent !== label) btn.textContent = label;  // sin tocar lo que no cambió
    if (dl !== null) btn.style.setProperty("--p", `${dl}%`);
    else btn.style.removeProperty("--p");
  }
}

function renderLibrary() {
  if (currentView() !== "library") return;
  lib.shelfSig = shelfSignature();
  // columna de colecciones, agrupadas por tipo
  const nav = $("#collections");
  nav.replaceChildren();
  const groups = [["auto", null], ["propia", "Colecciones"], ["playlist", "Playlists"], ["canal", "Canales"],
    ["categoría", "Categorías"]];
  for (const [kind, label] of groups) {
    if (kind === "canal" && prefs.lib_channels === false) continue;  // Preferencias → Biblioteca
    const items = lib.collections.filter((c) => c.kind === kind);
    if (label && (items.length || kind === "propia")) nav.append(el("h4", { text: label }));
    for (const c of items) {
      nav.append(el("button", {
        class: "item" + (c.id === lib.sel ? " active" : ""), type: "button", title: c.name,
        on: { click: () => { lib.sel = c.id; lib.picked.clear(); renderLibrary(); } },
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

  const c = lib.collections.find((x) => x.id === lib.sel) || { name: "Recientes", items: [], kind: "auto" };
  renderShelfHead(c);
  const grid = $("#grid");
  grid.replaceChildren();
  if (!Object.keys(lib.videos).length) {  // biblioteca vacía: empezar aquí mismo
    grid.append(welcome());
    return;
  }
  grid.classList.toggle("picking", lib.picked.size > 0);
  if (!c.items.length) {
    grid.append(el("div", { class: "empty", text: c.kind === "propia" ? "colección vacía" : "sin videos" }));
    return;
  }
  c.items.forEach((id, i) => {
    const v = lib.videos[id];
    if (v) grid.append(card(v, c, i));
  });
}

function renderShelfHead(c) {
  const head = $("#shelf-head");
  const n = lib.picked.size;
  if (n) {  // con selección: acciones sobre lo elegido
    head.replaceChildren(
      el("h2", { text: c.name }),
      el("span", { class: "sel-count", text: n === 1 ? "1 seleccionado" : `${n} seleccionados` }),
      el("div", { class: "acts" },
        el("button", { class: "btn dark", type: "button", text: "Abrir", on: { click: () => openPicked(c) } }),
        el("button", { class: "btn", type: "button", text: "Procesar", on: { click: () => {
          for (const id of pickedIn(c)) send({ type: "queue_add", video: id });
          lib.picked.clear();
          renderLibrary();
        } } }),
        el("button", { class: "btn", type: "button", text: "Exportar",
          on: { click: () => openExport(pickedIn(c), n === 1 ? "" : `${c.name} (${n})`) } }),
        el("button", { class: "btn danger", type: "button", text: "Eliminar", on: { click: async () => {
          const ids = pickedIn(c);
          const what = ids.length === 1 ? "este video" : `estos ${ids.length} videos`;
          if (await confirmDlg(`¿Eliminar ${what}?`,
            "Se borran de la biblioteca junto con su traducción, sus voces y los archivos descargados.", "Eliminar")) {
            send({ type: "lib_delete", videos: ids });
            lib.picked.clear();
          }
        } } }),
        el("button", { class: "btn ghost", type: "button", text: "Quitar selección",
          on: { click: () => { lib.picked.clear(); renderLibrary(); } } })));
    return;
  }
  const acts = el("div", { class: "acts" });
  if (c.kind === "playlist") {
    acts.append(
      el("button", { class: "btn dark", type: "button", text: "Reproducir", disabled: !c.items.length,
        on: { click: () => { setContext({ name: c.name, coll: c.id, auto: true }); playItem(c.items[0]); } } }),
      el("a", { class: "btn", href: c.url, target: "_blank", rel: "noopener", text: "Abrir en YouTube" }));
  }
  if (c.items.length) {
    acts.append(el("button", { class: "btn", type: "button", text: "Exportar",
      on: { click: () => openExport(c.items, c.name) } }));
  }
  if (c.kind === "propia" || c.kind === "playlist") {
    const what = c.kind === "playlist" ? "la playlist" : "la colección";
    acts.append(el("button", { class: "btn ghost", type: "button", text: c.kind === "playlist" ? "Eliminar playlist" : "Eliminar colección",
      on: { click: async () => {
        const extra = c.kind === "playlist" ? "Los videos descargados se quedan; los pendientes salen de la cola." : "Los videos no se borran.";
        if (await confirmDlg(`¿Eliminar ${what} «${c.name}»?`, extra, "Eliminar")) send({ type: "coll_delete", coll: c.id });
      } } }));
  }
  if (c.id === "all" && c.items.length) {
    acts.append(el("button", { class: "btn ghost", type: "button", text: "Vaciar biblioteca", on: { click: async () => {
      if (await confirmDlg("¿Vaciar la biblioteca?",
        "Se borran todos los videos, colecciones y playlists, con sus traducciones, voces y archivos descargados. No se puede deshacer.",
        "Vaciar biblioteca")) {
        send({ type: "lib_clear" });
        lib.picked.clear();
        lib.sel = "recent";
      }
    } } }));
  }
  head.replaceChildren(...[
    el("h2", { text: c.name, title: c.name }),
    c.kind === "playlist" ? el("span", { class: "pl-tag", text: "Playlist" }) : null,
    c.kind === "playlist" && c.channel ? el("small", { text: c.channel }) : null,
    c.kind !== "auto" && c.kind !== "playlist" ? el("small", { text: c.kind }) : null,
    acts].filter(Boolean));
}

const pickedIn = (c) => c.items.filter((id) => lib.picked.has(id));

function openPicked(c) {
  const ids = pickedIn(c);
  lib.picked.clear();
  if (!ids.length) return;
  setContext({ name: c.name, items: ids, auto: true });
  playItem(ids[0]);
}

function welcome() {
  const input = el("input", { type: "text", placeholder: "Enlace de YouTube: video o playlist", spellcheck: "false" });
  const file = el("input", { type: "file", accept: "video/*,audio/*", multiple: true, hidden: true,
    on: { change: (e) => { openFiles([...e.target.files]); e.target.value = ""; } } });
  return el("div", { class: "welcome" },
    el("h2", { text: "Traduce tu primer video" }),
    el("form", { on: { submit: (e) => { e.preventDefault(); openYouTube(input.value.trim()); } } },
      input, el("button", { class: "btn dark", type: "submit", text: "Traducir" })),
    el("label", { class: "btn" }, document.createTextNode("Abrir archivos"), file),
    el("small", { text: "o arrastra un video aquí" }));
}

// avance de traducción y doblaje de un video ya en el equipo
function progressBar(v) {
  if (!v.media) return null;
  const j = jobOf(v.id);
  const p = j && j.state !== "listo" ? { dub: j.dub } : v.progress || { dub: 0 };
  const pct = Math.round(p.dub * 100);
  if (p.dub >= 0.97) return el("div", { class: "stage-bar done" }, el("span", { text: "traducido" }));
  const label = j?.state === "procesando" ? `procesando · ${pct} %`
    : j?.state === "en cola" ? `en cola · ${pct} %` : pct ? `doblado ${pct} %` : "";
  if (!label) return null;
  return el("div", { class: "stage-bar" + (j?.state === "procesando" ? " run" : "") },
    el("b", {}, Object.assign(el("i"), { style: `width:${pct}%` })), el("span", { text: label }));
}

function card(v, coll, i) {
  const pct = v.duration ? Math.min(100, (v.position || 0) / v.duration * 100) : 0;
  const pending = pendingText(v);
  const pick = el("input", { type: "checkbox", class: "pick", "aria-label": "Seleccionar", checked: lib.picked.has(v.id),
    on: { change: (e) => {
      if (e.target.checked) lib.picked.add(v.id); else lib.picked.delete(v.id);
      renderLibrary();
    } } });
  const thumb = el("div", { class: "thumb" }, pick,
    v.thumb ? el("img", { src: v.thumb, alt: "", loading: "lazy" }) : null,
    coll.kind === "playlist" ? el("span", { class: "num", text: String(i + 1) }) : null,
    pending ? el("span", { class: "pending-dl", text: pending }) : null,
    v.duration ? el("span", { class: "dur", text: fmtDur(v.duration) }) : null,
    pct > 1 ? el("div", { class: "prog" }, Object.assign(el("i"), { style: `width:${pct}%` })) : null);
  const sub = [v.channel, v.source === "youtube" ? "YouTube" : "archivo"].filter(Boolean).join(" · ");
  const canOpen = !!v.media || v.source === "youtube";
  const dl = downloadPct(v);  // descargando: el botón lo dice y se llena con el avance
  return el("article", { class: "card" + (lib.picked.has(v.id) ? " picked" : ""), "data-id": v.id }, thumb,
    el("div", { class: "meta" }, el("h3", { text: v.title || v.id }), el("p", { text: sub })),
    progressBar(v),
    el("div", { class: "actions" },
      el("button", { class: "btn" + (dl !== null ? " dl" : ""), type: "button", disabled: !canOpen,
        text: dl !== null ? `Descargando ${dl} %` : "Ver", style: dl !== null ? `--p:${dl}%` : null,
        title: canOpen ? null : "La copia del archivo aún no está en la biblioteca",
        on: { click: () => {
          setContext({ name: coll.name, coll: coll.id, auto: coll.kind === "playlist" });
          playItem(v.id);
        } } }),
      canProcess(v) ? el("button", { class: "btn ghost", type: "button", text: "Procesar",
        title: "Traducir y doblar en segundo plano",
        on: { click: () => send({ type: "queue_add", video: v.id }) } }) : null,
      coll.kind === "propia" ? el("button", { class: "btn ghost", type: "button", text: "Quitar",
        on: { click: () => send({ type: "coll_toggle", coll: coll.id, video: v.id, on: false }) } }) : null));
}

// avance de descarga de un video sin copia (la cola o al abrirlo); null si no se descarga
function downloadPct(v) {
  if (v.media) return null;
  const d = state.downloads[v.id.slice(3)] || jobOf(v.id)?.dl;
  if (!d) return null;
  // video y audio se bajan por separado: se reparten la barra; unir y preparar es el final
  return d.stage === "video" ? Math.round(d.pct * 0.85) : d.stage === "audio" ? 85 + Math.round(d.pct * 0.1)
    : d.stage === "buscando" ? 0 : 97;
}

function playFromLibrary(v) {
  const resume = v.position > 5 && v.position < (v.duration || 0) - 10 ? v.position : 0;
  loadVideo(v.media, v.id, v.title, v.audio, { fromLibrary: true, position: resume, keepContext: true });
  setView("player");
}

// abre un video de la colección actual (si es de una playlist y no está
// descargado, se descarga primero y se abre al terminar)
function playItem(id) {
  const v = lib.videos[id];
  if (!v) return;
  if (v.media) return playFromLibrary(v);
  if (v.source === "youtube") {
    lib.keepCtxFor = id;
    openVideoLink("https://www.youtube.com/watch?v=" + id.slice(3));
  }
}

function canProcess(v) {
  const job = jobOf(v.id);
  const inQueue = job && (job.state === "en cola" || job.state === "procesando");
  return (!!v.media || v.source === "youtube") && !inQueue && (!v.progress || v.progress.dub < 0.97);
}

/* ------------------------------------------------------------ siguientes */
function setContext(ctx) { lib.ctx = ctx; }

function contextItems() {
  const c = lib.ctx;
  if (!c) return [];
  if (c.coll) return (lib.collections.find((x) => x.id === c.coll) || { items: c.items || [] }).items;
  return c.items || [];
}

function renderUpNext(scroll) {
  const items = contextItems().filter((id) => lib.videos[id]);
  const has = items.length > 1;
  $("#side-tabs").hidden = !has;
  if (!has) {
    if (!$("#upnext").hidden) setSideTab("transcript");
    return;
  }
  const ol = $("#upnext");
  const pl = lib.ctx.coll && lib.collections.find((x) => x.id === lib.ctx.coll)?.kind === "playlist";
  const frag = document.createDocumentFragment();
  frag.append(el("li", { class: "head", text: (pl ? "Playlist · " : "") + lib.ctx.name }));
  items.forEach((id, i) => {
    const v = lib.videos[id];
    const now = id === state.videoId;
    const info = [fmtDur(v.duration), pendingText(v) || (v.progress && v.progress.dub >= 0.97 ? "traducido" : "")]
      .filter(Boolean).join(" · ");
    frag.append(el("li", { class: now ? "now" : "", "data-id": id, on: { click: () => { if (!now) playItem(id); } } },
      el("span", { class: "n", text: String(i + 1) }),
      el("div", { class: "qthumb" }, v.thumb ? el("img", { src: v.thumb, alt: "", loading: "lazy" }) : null),
      el("div", {}, el("strong", { text: v.title || id }), el("small", { text: info }))));
  });
  const top = ol.scrollTop;
  ol.replaceChildren(frag);
  ol.scrollTop = top;
  if (scroll) ol.querySelector("li.now")?.scrollIntoView({ block: "center" });
}

function playNextInContext() {
  if (!lib.ctx || prefs.autoplay_next === false) return;  // Preferencias → Video
  const items = contextItems();
  const i = items.indexOf(state.videoId);
  if (i >= 0 && i + 1 < items.length) playItem(items[i + 1]);
}

/* ------------------------------------------------------------ playlists */
function playlistAdded(m) {
  toast(`Playlist «${m.name}» agregada: ${m.count} videos a la cola.`, "ok");
  lib.sel = m.coll;
  lib.picked.clear();
  setView("library");
}

/* ------------------------------------------------------------ archivos locales extra */
// Copia un archivo a la biblioteca (con duración y miniatura) y lo manda a la cola.
function importLocal(file, id) {
  if (lib.videos[id]?.media) return;
  const url = URL.createObjectURL(file);
  const probe = document.createElement("video");
  probe.preload = "metadata";
  probe.muted = true;
  probe.src = url;
  probe.addEventListener("loadedmetadata", () => {
    send({ type: "lib_register", id, title: file.name, duration: probe.duration, source: "file" });
    fetch(`/api/upload/${id}?name=${encodeURIComponent(file.name)}`, { method: "PUT", body: file })
      .then(() => { send({ type: "queue_add", video: id }); send({ type: "library" }); })
      .catch(() => {});
    makeThumb(url, id);
  }, { once: true });
}

/* ------------------------------------------------------------ cola en segundo plano */
function queueUpdate(m) {
  const before = lib.queue.jobs.map((j) => j.id + j.state + j.downloaded).join();
  lib.queue = m;
  // al terminar o cambiar un trabajo, refrescar el avance de las tarjetas
  if (before !== m.jobs.map((j) => j.id + j.state + j.downloaded).join()) send({ type: "library" });
  renderQueuePanel();
  renderPower();
  if (m.jobs.some((j) => j.dl || j.state === "procesando")) { refreshCards(); renderUpNext(); }
}

// Panel de la cola (como las descargas del navegador): exportaciones, descargas,
// lo que se procesa ahora, lo que espera y lo terminado.
function renderQueuePanel() {
  const q = lib.queue;
  const active = q.jobs.filter((j) => j.state === "en cola" || j.state === "procesando");
  const nDown = Object.keys(state.downloads).length;
  const nExp = lib.exports.filter((x) => x.state !== "listo" && x.state !== "error").length;
  const badge = $("#queue-badge");
  badge.textContent = String(active.length + nDown + nExp);
  badge.hidden = !(active.length + nDown + nExp);
  $("#queue-btn").classList.toggle("busy", nDown > 0 || nExp > 0 || q.jobs.some((j) => j.state === "procesando" || j.dl));
  const running = q.jobs.find((j) => j.state === "procesando");
  $("#queue-state").textContent = q.paused
    ? (running && running.watching ? "en pausa · sigue el video que ves" : "en pausa · reposo")
    : running ? "procesando" : active.length ? "en espera" : "sin trabajos · reposo";
  $("#queue-toggle").textContent = q.paused ? "Reanudar" : "Pausar";
  $("#queue-clear").hidden = !q.jobs.some((j) => j.state === "listo" || j.state === "error")
    && !lib.exports.some((x) => x.state === "listo" || x.state === "error");
  const ul = $("#queue-list");
  ul.replaceChildren();
  // exportaciones
  if (lib.exports.length) ul.append(el("li", { class: "qsec", text: "Exportar" }));
  for (const x of lib.exports) {
    const label = x.state === "listo" ? "listo"
      : x.state === "error" ? (x.error || "error")
      : x.detail ? `${x.detail}${x.state === "exportando" ? ` · ${x.pct} %` : ""}` : x.state;
    ul.append(el("li", { class: "qitem" + (x.state === "exportando" ? " run" : "") },
      el("div", { class: "qthumb exp", text: x.count > 1 ? "zip" : "mp4" }),
      el("div", { class: "qbody" },
        el("strong", { text: x.name }),
        el("div", { class: "qbar" }, Object.assign(el("i"), { style: `width:${x.pct}%` })),
        el("small", { text: label })),
      el("div", { class: "qactions" },
        x.state === "listo" ? el("button", { class: "btn", type: "button", text: "Descargar", on: { click: () => download(x) } }) : null,
        el("button", { class: "btn ghost", type: "button", text: x.state === "listo" || x.state === "error" ? "Quitar" : "Cancelar",
          on: { click: () => send({ type: "export_remove", job: x.id }) } }))));
  }
  // descargas de YouTube en curso (al abrir un enlace): cada etapa visible
  const downloads = Object.values(state.downloads);
  if (lib.exports.length && (downloads.length || q.jobs.length)) ul.append(el("li", { class: "qsec", text: "Traducir" }));
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
  if (!q.jobs.length && !downloads.length && !lib.exports.length) ul.append(el("li", { class: "empty-row", text: "nada en la cola" }));
  for (const j of q.jobs) {
    const v = lib.videos[j.id] || { id: j.id, title: j.id };
    const dl = !j.downloaded && j.state !== "listo" && j.state !== "error";
    const pct = dl ? (j.dl?.pct || 0) : Math.round(j.dub * 100);
    const label = j.state === "listo" ? "listo"
      : j.state === "error" ? "error"
      : dl ? pendingText(v) || "sin descargar"
      : j.state === "procesando" ? (j.watching ? `viendo · ${pct} %` : `${pct} %`)
      : q.paused && !j.watching ? "en pausa" : "en espera";
    const pl = playlistOf(j.id);
    ul.append(el("li", { class: "qitem" + (j.state === "procesando" || j.dl ? " run" : "") },
      el("div", { class: "qthumb" }, v.thumb ? el("img", { src: v.thumb, alt: "" }) : null),
      el("div", { class: "qbody" },
        el("strong", { text: v.title || j.id }),
        el("div", { class: "qbar" }, Object.assign(el("i"), { style: `width:${pct}%` })),
        el("small", { text: j.error || (pl ? `${label} · ${pl.name}` : label) })),
      el("div", { class: "qactions" },
        el("button", { class: "btn", type: "button", text: "Ver", disabled: !v.media && v.source !== "youtube",
          on: { click: () => {
            closeQueue();
            if (pl) setContext({ name: pl.name, coll: pl.id, auto: true });
            playItem(v.id);
          } } }),
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
$("#queue-clear").addEventListener("click", () => {
  send({ type: "queue_clear" });
  for (const x of lib.exports) if (x.state === "listo" || x.state === "error") send({ type: "export_remove", job: x.id });
});

/* ------------------------------------------------------------ exportar */
let exportVideos = [];
function openExport(ids, name = "") {
  exportVideos = ids.filter((id) => lib.videos[id]);
  if (!exportVideos.length) return;
  const one = exportVideos.length === 1;
  const first = lib.videos[exportVideos[0]];
  $("#export-title").textContent = one ? first.title || first.id : name || `${exportVideos.length} videos`;
  $("#export-sub").textContent = one ? "" : `${exportVideos.length} videos · un archivo .zip`;
  $("#export-form").dataset.name = one ? "" : name || "videos";
  updateExportNote();
  $("#export-dlg").showModal();
}
function updateExportNote() {
  const kinds = [...$("#export-form").querySelectorAll("input[name=kind]:checked")].map((x) => x.value);
  $("#export-go").disabled = !kinds.length;
  const vs = exportVideos.map((id) => lib.videos[id]);
  const needDub = kinds.some((k) => k.startsWith("es_"))
    ? vs.filter((v) => !(v.progress && v.progress.dub >= 0.99)).length : 0;
  const needDl = vs.filter((v) => !v.media).length;
  const parts = [];
  if (needDl) parts.push(exportVideos.length === 1 ? "se descarga primero" : `${needDl} se descargan primero`);
  if (needDub) parts.push(exportVideos.length === 1 ? "el doblaje aún no termina: se exporta al terminar"
    : `${needDub} aún sin doblaje completo: se exportan al terminar`);
  $("#export-note").textContent = parts.join(" · ");
}
$("#export-form").addEventListener("change", updateExportNote);
$("#export-dlg").addEventListener("close", () => {
  if ($("#export-dlg").returnValue !== "ok") return;
  const kinds = [...$("#export-form").querySelectorAll("input[name=kind]:checked")].map((x) => x.value);
  if (kinds.length) send({ type: "export", videos: exportVideos, kinds, name: $("#export-form").dataset.name });
});
$("#export-btn").addEventListener("click", () => { if (state.videoId) openExport([state.videoId]); });

function exportStarted(id) {
  lib.mine.add(id);
  openQueue();
}
function exportsUpdate(m) {
  lib.exports = m.jobs;
  for (const x of m.jobs) {
    // lo que pidió esta pestaña se descarga solo al terminar
    if (x.state === "listo" && lib.mine.has(x.id) && !lib.delivered.has(x.id)) {
      lib.delivered.add(x.id);
      download(x);
      toast(`Exportación lista: ${x.name}`, "ok");
    }
    if (x.state === "error" && lib.mine.has(x.id) && !lib.delivered.has(x.id)) {
      lib.delivered.add(x.id);
      toast(`No se pudo exportar «${x.name}»: ${x.error}`);
    }
  }
  renderQueuePanel();
}
function download(x) {
  const a = el("a", { href: x.url, download: "" });
  document.body.append(a);
  a.click();
  a.remove();
}

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
function libOnOpen({ id, name, file, fromLibrary, position, keepContext }) {
  const known = !!lib.videos[id];
  const pl = playlistOf(id);
  if (!fromLibrary && !known && !pl) lib.promptSave = true;
  // "Siguientes": la colección desde donde se abrió; si no, su playlist
  if (!keepContext && lib.keepCtxFor !== id) {
    lib.ctx = pl ? { name: pl.name, coll: pl.id, auto: true } : null;
  }
  lib.keepCtxFor = null;
  renderUpNext(true);
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
renderUpNext();

/* ------------------------------------------------------------ miniatura */
$("#mini-back").addEventListener("click", (e) => { e.stopPropagation(); setView("player"); });
$("#mini-close").addEventListener("click", (e) => {
  e.stopPropagation();
  vEn.pause();
  send({ type: "unwatch" });
  lib.mini = false;
  document.body.classList.remove("mini");
});
