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
  return b.contains("view-prefs") ? "prefs" : b.contains("view-queue") ? "queue" : b.contains("view-library") ? "library" : "player";
}
function setView(view) {
  const before = currentView();
  if (before !== "prefs" && before !== "queue" && (view === "prefs" || view === "queue")) lib.lastView = before;
  document.body.classList.toggle("view-library", view === "library");
  document.body.classList.toggle("view-prefs", view === "prefs");
  document.body.classList.toggle("view-queue", view === "queue");
  $("#prefs-btn").classList.toggle("on", view === "prefs");
  setBtn($("#view"), view === "library" ? "Volver al video" : "Biblioteca", view === "library" ? "video" : "grid");
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
  if (view === "queue") { $("#qnav").dataset.sig = ""; $("#qhead").dataset.sig = ""; $("#qlist").dataset.sig = ""; renderQueueScreen(); }
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
  if (lib.openAfterSwitch && lib.videos[lib.openAfterSwitch]) {  // desde la cola: video de otra biblioteca
    const id = lib.openAfterSwitch;
    lib.openAfterSwitch = null;
    playItem(id);
  }
  const wait = lib.openWhenReady && lib.videos[lib.openWhenReady];
  if (wait?.media) {  // lo que se pidió abrir ya se descargó
    lib.openWhenReady = null;
    playFromLibrary(wait);
  }
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


const jobOf = (id) => lib.queue.jobs.find((j) => j.id === id);
const playlistOf = (id) => lib.collections.find((c) => c.kind === "playlist" && c.items.includes(id));

// estado de un video aún sin descargar (playlist)
// «descargando 40 % · 2,3 MB/s · quedan 0:12»
function fmtBytes(b) {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(b < 10 && i ? 1 : 0).replace(".", ",")} ${u[i]}`;
}
function dlText(d) {
  if (d.stage !== "video" && d.stage !== "audio") return `${d.stage}…`;
  const parts = [`descargando ${d.pct} %`];
  if (d.speed) parts.push(`${fmtBytes(d.speed)}/s`);
  if (d.eta != null && d.eta > 0) parts.push(`quedan ${fmtDur(d.eta)}`);
  return parts.join(" · ");
}

function pendingText(v) {
  const j = jobOf(v.id);
  if (v.media) {  // descargado: en cola o procesándose hasta tener la voz
    if (!j || ["listo", "error", "descargado"].includes(j.state) || (v.progress && v.progress.dub >= 0.97)) return "";
    return j.state === "procesando" ? "procesando" : "en cola";  // el % va en la barra de la tarjeta
  }
  if (j?.dl) return dlText(j.dl);
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
    else if (text) art.querySelector(".thumb").append(el("span", { class: "pending-dl", text }));
    art.classList.toggle("pending", !!text);
    const disc = art.querySelector(".thumb .play");
    if (disc) {  // solo cambia lo distinto (el anillo de descarga o el botón de reproducir)
      const dl = downloadPct(v);
      if ((dl !== null) !== disc.classList.contains("dl")) disc.replaceWith(playDisc(dl));
      else if (dl !== null) {
        disc.style.setProperty("--p", dl);
        if (disc.firstChild.textContent !== `${dl}%`) disc.firstChild.textContent = `${dl}%`;
      }
    }
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
        on: { click: () => { lib.sel = c.id; lib.picked.clear(); closeSearch(); renderLibrary(); } },
      }, el("span", { text: c.name }), el("span", { text: String(c.items.length) })));
    }
    if (kind === "propia") {
      const input = el("input", { class: "input", type: "text", placeholder: "Nueva colección", maxlength: 80 });
      nav.append(el("form", { class: "inline-form", on: { submit: (e) => {
        e.preventDefault();
        if (input.value.trim()) send({ type: "coll_create", name: input.value.trim() });
        input.value = "";
      } } }, input, btn("Crear", { type: "submit" })));
    }
  }

  if (lib.search) return renderSearch();
  const c = lib.collections.find((x) => x.id === lib.sel) || { name: "Recientes", items: [], kind: "auto" };
  renderShelfHead(c);
  const grid = $("#grid");
  grid.classList.remove("results");
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
  // de a 200 tarjetas (con miles de videos, dibujarlas todas trabaría la página)
  if (lib.limitFor !== c.id) { lib.limitFor = c.id; lib.limit = 200; }
  c.items.slice(0, lib.limit).forEach((id, i) => {
    const v = lib.videos[id];
    if (v) grid.append(card(v, c, i));
  });
  if (c.items.length > lib.limit) {
    grid.append(el("div", { class: "more" }, btn(`Mostrar más (${c.items.length - lib.limit})`, {
      icon: "plus", onClick: () => { lib.limit += 200; renderLibrary(); } })));
  }
}

function renderShelfHead(c) {
  const head = $("#shelf-head");
  const n = lib.picked.size;
  if (n) {  // con selección: acciones sobre lo elegido
    head.replaceChildren(
      el("h2", { text: c.name }),
      el("span", { class: "label", text: n === 1 ? "1 seleccionado" : `${n} seleccionados` }),
      el("div", { class: "acts" },
        btn("Abrir", { icon: "play", variant: "dark", onClick: () => openPicked(c) }),
        btn("Procesar", { icon: "spark", onClick: () => {
          for (const id of pickedIn(c)) send({ type: "queue_add", video: id });
          lib.picked.clear();
          renderLibrary();
        } }),
        btn("Exportar", { icon: "download", onClick: () => openExport(pickedIn(c), n === 1 ? "" : `${c.name} (${n})`) }),
        moveMenu(() => pickedIn(c), () => { lib.picked.clear(); renderLibrary(); }),
        btn("Eliminar", { icon: "trash", variant: "danger", onClick: async () => {
          const ids = pickedIn(c);
          const what = ids.length === 1 ? "este video" : `estos ${ids.length} videos`;
          if (await confirmDlg(`¿Eliminar ${what}?`,
            "Se borran de la biblioteca junto con su traducción, sus voces y los archivos descargados.", "Eliminar")) {
            send({ type: "lib_delete", videos: ids });
            lib.picked.clear();
          }
        } }),
        btn("Quitar selección", { icon: "x", variant: "ghost", onClick: () => { lib.picked.clear(); renderLibrary(); } })));
    return;
  }
  const acts = el("div", { class: "acts" });
  if (c.kind === "playlist") {
    acts.append(
      btn("Reproducir", { icon: "play", variant: "dark", disabled: !c.items.length,
        onClick: () => { setContext({ name: c.name, coll: c.id, auto: true }); playItem(c.items[0]); } }),
      btn("Abrir en YouTube", { icon: "external", href: c.url }));
  }
  if (c.items.length) {
    acts.append(btn("Exportar", { icon: "download", onClick: () => openExport(c.items, c.name) }));
  }
  if (c.kind === "propia" || c.kind === "playlist") {
    const what = c.kind === "playlist" ? "la playlist" : "la colección";
    acts.append(btn(c.kind === "playlist" ? "Eliminar playlist" : "Eliminar colección", { icon: "trash", variant: "ghost",
      onClick: async () => {
        const extra = c.kind === "playlist" ? "Los videos descargados se quedan; los pendientes salen de la cola." : "Los videos no se borran.";
        if (await confirmDlg(`¿Eliminar ${what} «${c.name}»?`, extra, "Eliminar")) send({ type: "coll_delete", coll: c.id });
      } }));
  }
  if (c.id === "all" && c.items.length) {
    acts.append(btn("Vaciar biblioteca", { icon: "trash", variant: "ghost", onClick: async () => {
      if (await confirmDlg("¿Vaciar la biblioteca?",
        "Se borran todos los videos, colecciones y playlists, con sus traducciones, voces y archivos descargados. No se puede deshacer.",
        "Vaciar biblioteca")) {
        send({ type: "lib_clear" });
        lib.picked.clear();
        lib.sel = "recent";
      }
    } }));
  }
  head.replaceChildren(...[
    el("h2", { text: c.name, title: c.name }),
    c.kind === "playlist" ? el("span", { class: "chip", text: "Playlist" }) : null,
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
    el("form", { class: "field", on: { submit: (e) => { e.preventDefault(); openYouTube(input.value.trim()); } } },
      icon("link"), input, btn("Importar", { icon: "import", variant: "dark", type: "submit" })),
    el("label", { class: "btn", "data-icon": "upload" }, icon("upload"), document.createTextNode("Importar archivos"), file),
    el("small", { text: "o arrastra un video aquí" }));
}

// avance de traducción y doblaje de un video ya en el equipo
function progressBar(v) {
  if (!v.media) return null;
  const j = jobOf(v.id);
  const p = j && j.state !== "listo" ? { dub: j.dub } : v.progress || { dub: 0 };
  const pct = Math.round(p.dub * 100);
  if (p.dub >= 0.97) return el("div", { class: "stage-bar done" }, el("span", { text: "traducido" }));
  if (j?.state === "descargado" && !pct) return el("div", { class: "stage-bar" }, el("span", { text: "descargado · sin traducir" }));
  const label = j?.state === "procesando" ? `procesando · ${pct} %`
    : j?.state === "en cola" ? `en cola · ${pct} %` : pct ? `doblado ${pct} %` : "";
  if (!label) return null;
  return el("div", { class: "stage-bar" + (j?.state === "procesando" ? " run" : "") }, meter(pct), el("span", { text: label }));
}

function card(v, coll, i) {
  const pct = v.duration ? Math.min(100, (v.position || 0) / v.duration * 100) : 0;
  const pending = pendingText(v);
  const pick = el("input", { type: "checkbox", class: "pick", "aria-label": "Seleccionar", checked: lib.picked.has(v.id),
    on: { change: (e) => {
      if (e.target.checked) lib.picked.add(v.id); else lib.picked.delete(v.id);
      renderLibrary();
    } } });
  const canOpen = !!v.media || v.source === "youtube";
  // abrir: toda la miniatura (y el título), como en YouTube; al pasar el mouse aparece el botón de reproducir
  const open = (e) => {
    if (!canOpen || e.target.closest(".pick")) return;
    setContext({ name: coll.name, coll: coll.id, auto: coll.kind === "playlist" });
    playItem(v.id);
  };
  const thumb = el("div", { class: "thumb" + (canOpen ? " open" : ""), title: canOpen ? "Ver" : "La copia del archivo aún no está en la biblioteca",
    on: { click: open } }, pick,
    v.thumb ? el("img", { src: v.thumb, alt: "", loading: "lazy" }) : null,
    coll.kind === "playlist" ? el("span", { class: "chip solid num", text: String(i + 1) }) : null,
    pending ? el("span", { class: "pending-dl", text: pending }) : null,
    v.duration ? el("span", { class: "chip dur", text: fmtDur(v.duration) }) : null,
    v.audio_only ? el("span", { class: "chip aud", title: "Solo se descargó el audio" }, icon("music"), " solo audio") : null,
    pct > 1 ? el("div", { class: "prog" }, Object.assign(el("i"), { style: `width:${pct}%` })) : null,
    canOpen ? playDisc(downloadPct(v)) : null);
  const sub = [v.channel, v.source === "youtube" ? "YouTube" : "archivo"].filter(Boolean).join(" · ");
  const job = jobOf(v.id);
  const acts = [
    job && job.state === "en cola" && !job.prio ? btn("Priorizar", { icon: "up", variant: "ghost", title: "Procesar esto antes que lo demás",
      onClick: () => send({ type: "queue_add", video: v.id, front: true }) }) : null,
    canProcess(v) ? btn("Procesar", { icon: "spark", variant: "ghost", title: "Traducir y doblar en segundo plano",
      onClick: () => send({ type: "queue_add", video: v.id }) }) : null,
    coll.kind === "propia" ? btn("Quitar", { icon: "x", variant: "ghost",
      onClick: () => send({ type: "coll_toggle", coll: coll.id, video: v.id, on: false }) }) : null,
  ].filter(Boolean);
  return el("article", { class: "card" + (lib.picked.has(v.id) ? " picked" : "") + (pending ? " pending" : ""),
    "data-id": v.id }, thumb,
    el("div", { class: "meta" }, el("h3", { class: canOpen ? "open" : "", text: v.title || v.id, on: { click: open } }), el("p", { text: sub })),
    progressBar(v),
    acts.length ? el("div", { class: "actions" }, ...acts) : null);
}

// centro de la miniatura: reproducir, o un anillo con el avance mientras se descarga
function playDisc(dl) {
  return dl === null
    ? el("span", { class: "play" }, icon("play"))
    : el("span", { class: "play dl", style: `--p:${dl}`, title: `Descargando ${dl} %` }, el("b", { text: `${dl}%` }));
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
    lib.openWhenReady = id;
    send({ type: "queue_add", video: id, front: true });
    toast("Se abrirá en cuanto termine de descargarse.", "ok");
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
  updateSideTabs();
  if (!has) return;
  if (lib.showUpNext) { lib.showUpNext = false; setSideTab("upnext"); return; }
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
  if (currentView() !== "player") setView("library");  // viendo un video: no se sale de él
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
    fetch(`/api/upload/${id}?name=${encodeURIComponent(file.name)}&lib=${vaults.current || ""}`, { method: "PUT", body: file })
      .then(() => {
        if (prefs.import_mode !== "descargar") send({ type: "queue_add", video: id });
        send({ type: "library" });
      })
      .catch(() => {});
    makeThumb(url, id);
  }, { once: true });
}

/* ------------------------------------------------------------ cola en segundo plano */
function queueUpdate(m) {
  const prev = new Map(lib.queue.jobs.map((j) => [j.id, j]));
  for (const j of m.jobs) {
    const p = prev.get(j.id);
    if (!p) continue;
    const title = lib.videos[j.id]?.title || j.id;
    if (p.state !== "listo" && j.state === "listo") notifyLater("traducidos", title);
    else if (!p.downloaded && j.downloaded) notifyLater("descargados", title);
  }
  const busy = (jobs) => jobs.some((j) => j.state === "en cola" || j.state === "procesando");
  if (busy(lib.queue.jobs) && !busy(m.jobs) && m.jobs.length) notifyUser("Cola terminada", "Todo lo pendiente se procesó.");
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
// La cola es una sola (una GPU, un orden), pero cada biblioteca ve lo suyo: el panel y el
// número muestran la biblioteca abierta; la pantalla de la Cola permite ver otra o todas.
lib.qlib = null;  // null: la abierta · "all": todas · id: una en particular
function jobsOf(which) {
  const jobs = lib.queue.jobs;
  if (which === "all" || typeof vaults === "undefined" || vaults.list.length < 2) return jobs;
  const id = which || vaults.current;
  return jobs.filter((j) => (j.lib || "principal") === id);
}
const queueJobs = () => jobsOf(lib.qlib);

function renderQueuePanel() {
  const q = lib.queue;
  const mine = jobsOf(null);
  const active = mine.filter((j) => j.state === "en cola" || j.state === "procesando");
  const nDown = Object.keys(state.downloads).length;
  const nExp = lib.exports.filter((x) => x.state !== "listo" && x.state !== "error").length;
  const badge = $("#queue-badge");
  badge.textContent = String(active.length + nDown + nExp);
  badge.hidden = !(active.length + nDown + nExp);
  $("#queue-btn").classList.toggle("busy", nDown > 0 || nExp > 0 || q.jobs.some((j) => j.state === "procesando" || j.dl));
  const running = q.jobs.find((j) => j.state === "procesando");
  const blocked = q.blocked_until ? Math.max(1, Math.ceil((q.blocked_until * 1000 - Date.now()) / 60000)) : 0;
  const downloading = q.jobs.find((j) => j.dl);
  $("#queue-state").textContent = blocked ? `descargas en pausa · YouTube pidió verificación · ${blocked} min`
    : q.paused
    ? (running && running.watching ? "procesamiento en pausa · sigue el video que ves"
      : downloading ? "procesamiento en pausa · descargando" : "procesamiento en pausa · reposo")
    : running ? "procesando" : downloading ? (q.careful ? "descargando · modo cuidadoso" : "descargando")
    : active.length ? "en espera" : "sin trabajos · reposo";
  setBtn($("#queue-toggle"), q.paused ? "Reanudar" : "Pausar", q.paused ? "play" : "pause");
  $("#queue-clear").hidden = !q.jobs.some((j) => j.state === "listo" || j.state === "error" || j.state === "descargado")
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
      el("div", { class: "qthumb exp" }, icon(x.count > 1 ? "zip" : "film")),
      el("div", { class: "qbody" },
        el("strong", { text: x.name }),
        meter(x.pct),
        el("small", { text: label })),
      el("div", { class: "qactions" },
        x.state === "listo" ? btn("Descargar", { icon: "download", size: "xs", onClick: () => download(x) }) : null,
        btn(x.state === "listo" || x.state === "error" ? "Quitar" : "Cancelar", { variant: "ghost", size: "xs",
          onClick: () => send({ type: "export_remove", job: x.id }) }))));
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
        meter(pct),
        el("small", { text: downloadText(d) })),
      el("div", { class: "qactions" })));
  }
  if (!mine.length && !downloads.length && !lib.exports.length) ul.append(el("li", { class: "empty-row", text: "nada en la cola de esta biblioteca" }));
  // los trabajos, en orden de estado (lo que se descarga, primero); el resto en la pantalla de la Cola
  const jobs = orderedJobs(null, mine);
  for (const j of jobs.slice(0, 50)) ul.append(jobItem(j));
  if (jobs.length > 50) ul.append(el("li", { class: "empty-row", text: `y ${jobs.length - 50} más · «Ver toda la cola» arriba` }));
  const others = q.jobs.length - mine.length;
  if (others > 0) ul.append(el("li", { class: "empty-row" }, btn(`${others} en otras bibliotecas`, { size: "xs", variant: "ghost",
    icon: "queue", onClick: () => { closeQueue(); lib.qlib = "all"; setView("queue"); } })));
  if (currentView() === "queue") renderQueueScreen();
}

/* ------------------------------------------------------------ cola: orden y elementos */
const JOB_ORDER = { descargando: 0, procesando: 1, "en cola": 2, descargado: 3, error: 4, listo: 5 };
const jobKind = (j) => (j.dl ? "descargando" : j.state);
function orderedJobs(kind = null, base = null) {
  const q = base || queueJobs();
  const list = kind ? q.filter((j) => jobKind(j) === kind) : q.slice();
  // estable: dentro de cada estado se respeta el orden de la cola (lo priorizado ya va primero)
  return list.map((j, i) => [j, i]).sort((a, b) => (JOB_ORDER[jobKind(a[0])] ?? 9) - (JOB_ORDER[jobKind(b[0])] ?? 9) || a[1] - b[1])
    .map(([j]) => j);
}

function jobLabel(j, v) {
  const q = lib.queue;
  const dl = !j.downloaded && j.state !== "listo" && j.state !== "error";
  const pct = dl ? (j.dl?.pct || 0) : Math.round(j.dub * 100);
  const label = j.state === "listo" ? "listo"
    : j.state === "error" ? "error"
    : j.state === "descargado" ? "descargado · sin traducir"
    : j.dl ? dlText(j.dl)
    : dl && j.retry_at ? "falló la descarga · se reintenta en unos minutos"
    : dl && q.blocked_until ? "esperando · descargas en pausa"
    : dl ? pendingText(v) || "sin descargar"
    : j.state === "procesando" ? (j.watching ? `viendo · ${pct} %` : `procesando · ${pct} %`)
    : q.paused && !j.watching ? "en pausa" : j.prio ? "siguiente · con prioridad" : "en espera";
  const pl = playlistOf(j.id);
  return { pct, text: j.error || (pl ? `${label} · ${pl.name}` : label) };
}

function jobItem(j) {
  const v = videoInfo(j.id) || { id: j.id, title: j.id };
  const { pct, text } = jobLabel(j, v);
  const pl = playlistOf(j.id);
  // de otra biblioteca: se nota con su insignia
  const away = j.lib && j.lib !== vaults.current ? vaultById(j.lib) : null;
  return el("li", { class: "qitem" + (j.state === "procesando" || j.dl ? " run" : ""), "data-id": j.id },
    el("div", { class: "qthumb" }, v.thumb ? el("img", { src: v.thumb, alt: "", loading: "lazy" }) : null),
    el("div", { class: "qbody" },
      el("strong", { text: v.title || j.id }),
      meter(pct),
      el("small", {}, away ? vaultBadge(away, "xs") : null, away ? `${away.name} · ${text}` : text)),
    el("div", { class: "qactions" },
      btn("Ver", { icon: "play", size: "xs", disabled: !v.media && v.source !== "youtube",
        onClick: () => {
          closeQueue();
          if (away) return playAcross(v.id, away.id);
          if (pl) setContext({ name: pl.name, coll: pl.id, auto: true });
          playItem(v.id);
        } }),
      j.state === "descargado" ? btn("Procesar", { icon: "spark", size: "xs", title: "Traducir y doblar",
        onClick: () => send({ type: "queue_add", video: j.id }) }) : null,
      j.state === "en cola" && !j.prio ? btn("Priorizar", { icon: "up", size: "xs", title: "Procesar esto antes que lo demás",
        onClick: () => send({ type: "queue_add", video: j.id, front: true }) }) : null,
      btn("Quitar", { variant: "ghost", size: "xs", onClick: () => send({ type: "queue_remove", video: j.id }) })));
}

/* ------------------------------------------------------------ pantalla de la Cola */
// Como la página de descargas del navegador: estados a la izquierda (con su cantidad)
// y la lista a la derecha, de a 100. El avance se actualiza en su lugar (sin perder clics).
const QSECTIONS = [["todo", "Todo"], ["descargando", "Descargando"], ["procesando", "Procesando"],
  ["en cola", "En cola"], ["descargado", "Descargados sin traducir"], ["error", "Con error"], ["listo", "Listos"]];
lib.qsec = "todo";
lib.qlimit = 100;

function renderQueueScreen() {
  if (currentView() !== "queue") return;
  const q = lib.queue;
  const all = queueJobs();
  const counts = Object.fromEntries(QSECTIONS.map(([k]) => [k, k === "todo" ? all.length : all.filter((j) => jobKind(j) === k).length]));
  const multi = typeof vaults !== "undefined" && vaults.list.length > 1;
  // índice
  const nav = $("#qnav");
  const libCounts = multi ? vaults.list.map((v) => jobsOf(v.id).length) : [];
  const navSig = JSON.stringify([lib.qsec, counts, lib.exports.length, lib.qlib, vaults.current, libCounts]);
  if (nav.dataset.sig !== navSig) {
    nav.dataset.sig = navSig;
    nav.replaceChildren(el("h4", { text: "Cola" }), ...QSECTIONS.filter(([k]) => k === "todo" || counts[k]).map(([k, t]) =>
      el("button", { type: "button", class: "item" + (lib.qsec === k ? " active" : ""),
        on: { click: () => { lib.qsec = k; lib.qlimit = 100; renderQueueScreen(); } } },
        el("span", { text: t }), el("span", { text: String(counts[k]) }))));
    if (multi) {  // de qué biblioteca: la abierta (por defecto), otra o todas
      const cur = lib.qlib || vaults.current;
      const pick = (id) => { lib.qlib = id === vaults.current ? null : id; lib.qlimit = 100; $("#qlist").dataset.sig = ""; renderQueueScreen(); };
      nav.append(el("h4", { text: "Bibliotecas" }),
        ...vaults.list.map((v, i) => el("button", { type: "button", class: "item" + (cur === v.id ? " active" : ""), on: { click: () => pick(v.id) } },
          el("span", {}, vaultBadge(v, "xs"), v.name), el("span", { text: String(libCounts[i]) }))),
        el("button", { type: "button", class: "item" + (cur === "all" ? " active" : ""), on: { click: () => pick("all") } },
          el("span", { text: "Todas" }), el("span", { text: String(q.jobs.length) })));
    }
    if (lib.exports.length) {
      nav.append(el("h4", { text: "Exportar" }), el("button", { type: "button", class: "item" + (lib.qsec === "exportar" ? " active" : ""),
        on: { click: () => { lib.qsec = "exportar"; renderQueueScreen(); } } },
        el("span", { text: "Exportaciones" }), el("span", { text: String(lib.exports.length) })));
    }
  }
  // encabezado: estado y acciones generales
  const blocked = q.blocked_until ? Math.max(1, Math.ceil((q.blocked_until * 1000 - Date.now()) / 60000)) : 0;
  const head = $("#qhead");
  const title = (QSECTIONS.find(([k]) => k === lib.qsec) || [, "Exportaciones"])[1];
  const headSig = JSON.stringify([title, q.paused, blocked, $("#queue-state").textContent, counts.listo + counts.error + counts.descargado]);
  if (head.dataset.sig !== headSig) {
    head.dataset.sig = headSig;
    head.replaceChildren(
      el("h2", { text: title }),
      el("span", { class: "label", text: $("#queue-state").textContent }),
      el("div", { class: "acts" },
        btn(q.paused ? "Reanudar procesamiento" : "Pausar procesamiento", { icon: q.paused ? "play" : "pause",
          onClick: () => send({ type: q.paused ? "queue_resume" : "queue_pause" }) }),
        blocked ? btn("Reintentar descargas", { icon: "download", onClick: () => send({ type: "queue_unblock" }) }) : null,
        counts.listo + counts.error + counts.descargado ? btn("Limpiar terminados", { icon: "check", variant: "ghost",
          onClick: () => $("#queue-clear").click() }) : null));
  }
  // lista
  const ul = $("#qlist");
  if (lib.qsec === "exportar") {
    ul.dataset.sig = "";
    ul.replaceChildren(...$("#queue-list").querySelectorAll(":scope > .qitem:not([data-id])").length
      ? [...$("#queue-list").querySelectorAll(":scope > .qitem:not([data-id])")].map((n) => n.cloneNode(true)) : []);
    return;
  }
  const jobs = orderedJobs(lib.qsec === "todo" ? null : lib.qsec);
  const shown = jobs.slice(0, lib.qlimit);
  const sig = shown.map((j) => j.id + jobKind(j) + (j.prio ? "p" : "")).join("|");
  if (ul.dataset.sig === sig) {  // misma lista: solo el avance y el texto, en su lugar
    for (const li of ul.querySelectorAll(".qitem[data-id]")) {
      const j = lib.queue.jobs.find((x) => x.id === li.dataset.id);
      if (!j) continue;
      const { pct, text } = jobLabel(j, lib.videos[j.id] || { id: j.id });
      li.querySelector(".meter > i").style.width = `${pct}%`;
      const small = li.querySelector("small");
      if (small.textContent !== text) small.textContent = text;
    }
    return;
  }
  ul.dataset.sig = sig;
  ul.replaceChildren(...shown.map(jobItem));
  if (!shown.length) ul.append(el("li", { class: "empty-row", text: "nada aquí" }));
  if (jobs.length > shown.length) {
    ul.append(el("li", { class: "empty-row" }, btn(`Mostrar más (${jobs.length - shown.length})`, {
      icon: "plus", onClick: () => { lib.qlimit += 100; renderQueueScreen(); } })));
  }
}

function openQueue() { renderQueuePanel(); $("#queue-pop").hidden = false; }
function closeQueue() { $("#queue-pop").hidden = true; }
$("#queue-btn").addEventListener("click", (e) => { e.stopPropagation(); $("#queue-pop").hidden ? openQueue() : closeQueue(); });
$("#queue-pop").addEventListener("click", (e) => e.stopPropagation());
document.addEventListener("click", closeQueue);
$("#queue-full").addEventListener("click", () => { closeQueue(); setView("queue"); });
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
  const onlyText = kinds.every((k) => ["srt_es", "srt_en", "txt"].includes(k));
  const needDl = onlyText ? 0 : vs.filter((v) => !v.media).length;
  const needText = !needDub && kinds.some((k) => ["srt_es", "srt_en", "txt"].includes(k))
    ? vs.filter((v) => !(v.progress && v.progress.asr >= 0.99)).length : 0;
  const parts = [];
  if (needDl) parts.push(exportVideos.length === 1 ? "se descarga primero" : `${needDl} se descargan primero`);
  const audioOnly = kinds.some((k) => k.endsWith("_video")) ? vs.filter((v) => v.audio_only).length : 0;
  if (audioOnly) parts.push(exportVideos.length === 1 ? "solo tiene el audio: el video se descarga primero"
    : `${audioOnly} solo tienen el audio: su video se descarga primero`);
  if (needText) parts.push(exportVideos.length === 1 ? "la transcripción aún no termina: se exporta al terminar"
    : `${needText} aún sin transcripción completa: se exportan al terminar`);
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
      notifyUser("Exportación lista", x.name);
    }
    if (x.state === "error" && lib.mine.has(x.id) && !lib.delivered.has(x.id)) {
      lib.delivered.add(x.id);
      toast(`No se pudo exportar «${x.name}»: ${x.error}`);
      notifyUser("No se pudo exportar", x.name);
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
        fetch(`/api/upload/${id}?name=${encodeURIComponent(file.name)}&lib=${vaults.current || ""}`, { method: "PUT", body: file })
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
    c.toBlob((b) => b && fetch(`/api/thumb/${id}?lib=${vaults.current || ""}`, { method: "PUT", body: b }).then(() => send({ type: "library" })),
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


/* ------------------------------------------------------------ búsqueda en las transcripciones */
let searchTimer = null;
$("#lib-q").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = $("#lib-q").value.trim();
  if (q.length < 2) { if (!q) closeSearch(true); return; }
  searchTimer = setTimeout(() => send({ type: "search", q }), 350);
});
$("#lib-search").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#lib-q").value.trim();
  if (q.length >= 2) send({ type: "search", q });
});
$("#lib-q").addEventListener("keydown", (e) => { if (e.key === "Escape") closeSearch(true); });
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && currentView() === "library" && !e.target.closest("input, textarea, dialog")) {
    e.preventDefault();
    $("#lib-q").focus();
  }
});

function searchResults(m) {
  if (m.q.trim() !== $("#lib-q").value.trim()) return;  // llegó tarde: ya se escribió otra cosa
  lib.search = m;
  lib.sel = lib.sel || "recent";
  renderLibrary();
}
function closeSearch(render = false) {
  if (!lib.search && !render) return;
  lib.search = null;
  if (render) { $("#lib-q").value = ""; lib.shelfSig = ""; renderLibrary(); }
}

// texto con la coincidencia marcada (subrayada, sin resaltado tipo marcador)
function highlight(text, q) {
  const norm = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const i = norm(text).indexOf(norm(q));
  if (i < 0) return document.createTextNode(text);
  return el("span", {}, text.slice(0, i), el("b", { class: "hl", text: text.slice(i, i + q.length) }), text.slice(i + q.length));
}

function openAt(v, t) {
  if (!v?.media) return playItem(v.id);
  setContext(null);
  loadVideo(v.media, v.id, v.title, v.audio, { fromLibrary: true, position: Math.max(0, t - 1), keepContext: true });
  setView("player");
}

function renderSearch() {
  const m = lib.search;
  const head = $("#shelf-head");
  head.replaceChildren(
    el("h2", { text: `Resultados para «${m.q}»` }),
    el("span", { class: "label", text: m.total ? `${m.total} ${m.total === 1 ? "coincidencia" : "coincidencias"} en ${m.results.length} ${m.results.length === 1 ? "video" : "videos"}` : "sin coincidencias" }),
    el("div", { class: "acts" }, btn("Cerrar búsqueda", { icon: "x", variant: "ghost", onClick: () => closeSearch(true) })));
  const grid = $("#grid");
  grid.classList.add("results");
  grid.replaceChildren();
  if (!m.results.length) {
    grid.append(el("div", { class: "empty", text: "nada encontrado en las transcripciones" }));
    return;
  }
  for (const r of m.results) {
    const v = lib.videos[r.video];
    if (!v) continue;
    grid.append(el("article", { class: "hitcard" },
      el("div", { class: "qthumb", on: { click: () => openAt(v, r.hits[0].t) } }, v.thumb ? el("img", { src: v.thumb, alt: "", loading: "lazy" }) : null),
      el("div", { class: "hitbody" },
        el("h3", { text: v.title || v.id }),
        el("ul", {}, ...r.hits.map((h) => el("li", { on: { click: () => openAt(v, h.t) }, title: "Ver desde aquí" },
          el("span", { class: "chip", text: fmtDur(h.t) }),
          el("div", {},
            el("p", {}, h.field === "en" ? highlight(h.text, m.q) : document.createTextNode(h.text)),
            h.translation ? el("p", { class: "es" }, h.field === "es" ? highlight(h.translation, m.q) : document.createTextNode(h.translation)) : null,
            h.note ? el("p", { class: "note" }, icon("comment"), " ", highlight(h.note, m.q)) : null)))))));
  }
}
