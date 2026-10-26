"use strict";
// Menú contextual (clic derecho): cambia según dónde se haga clic. Usa openMenu() de
// web/js/menu.js y lo global de app.js, library.js, vaults.js, home.js y patterns.js.
//   tarjeta de video · colección (barra lateral, fila del inicio, banner) · trabajo de la cola
//   frase de la transcripción · video · Siguientes · espacio libre
// En campos de texto, o con texto seleccionado, queda el menú del navegador.

const isOwner = () => !document.body.classList.contains("guest");
const canImport = () => document.body.classList.contains("can-import");
const ytUrl = (v) => (v?.source === "youtube" ? `https://www.youtube.com/watch?v=${v.id.slice(3)}` : "");
// copiar: el portapapeles moderno solo existe en conexiones seguras (no desde otro equipo por http)
function copyText(text, what) {
  const ok = () => toast(`${what} copiado.`, "ok");
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(ok, () => legacyCopy(text) ? ok() : toast("No se pudo copiar."));
  } else if (legacyCopy(text)) ok();
  else toast("No se pudo copiar.");
}
function legacyCopy(text) {
  const t = el("textarea", { style: "position:fixed;opacity:0;pointer-events:none" });
  t.value = text;
  (document.querySelector("dialog[open]") || document.body).append(t);
  t.select();
  let done = false;
  try { done = document.execCommand("copy"); } catch (e) { done = false; }
  t.remove();
  return done;
}

/* ------------------------------------------------------------ video */
function videoMenu(v, coll) {
  const job = jobOf(v.id);
  const canOpen = !!v.media || v.source === "youtube";
  const own = lib.collections.filter((c) => c.kind === "propia");
  const others = typeof vaults !== "undefined" ? vaults.list.filter((x) => x.id !== vaults.current) : [];
  const picked = lib.picked.has(v.id);
  const open = () => { if (coll) setContext({ name: coll.name, coll: coll.id, auto: coll.kind === "playlist" }); playItem(v.id); };
  return [
    { head: v.title || v.id },
    canOpen && { label: v.position > 5 ? "Continuar" : "Ver", icon: "play", onClick: open },
    canOpen && v.position > 5 && { label: "Ver desde el inicio", icon: "reload", onClick: () => { v.position = 0; open(); } },
    canDownload(v) && { label: "Descargar sin abrir", icon: "download", onClick: () => downloadOnly(v) },
    "sep",
    canImport() && job?.state === "en cola" && !job.prio && { label: "Priorizar", icon: "up", onClick: () => send({ type: "queue_add", video: v.id, front: true }) },
    canImport() && canProcess(v) && { label: "Traducir y doblar", icon: "spark", onClick: () => send({ type: "queue_add", video: v.id }) },
    canImport() && v.audio_only && v.source === "youtube" && !job?.fetch_video && { label: "Bajar el video completo", icon: "film", onClick: () => fetchVideo(v.id) },
    isOwner() && job && !["listo", "error"].includes(job.state) && { label: "Quitar de la cola", icon: "x", onClick: () => send({ type: "queue_remove", video: v.id }) },
    "sep",
    isOwner() && { label: "Guardar en", icon: "bookmark", sub: [
      ...own.map((c) => ({ label: c.name, badge: collBadge(c), check: c.items.includes(v.id),
        onClick: () => send({ type: "coll_toggle", coll: c.id, video: v.id, on: !c.items.includes(v.id) }) })),
      own.length ? "sep" : null,
      { label: "Nueva colección…", icon: "plus", onClick: async () => {
        const name = await promptDlg("Nueva colección", "", "Crear");
        if (name) send({ type: "coll_create", name, video: v.id });
      } },
    ] },
    isOwner() && others.length && { label: "Mover a", icon: "folder", sub: others.map((x) => ({ label: x.name, badge: vaultBadge(x),
      onClick: () => send({ type: "vault_move", videos: [v.id], to: x.id }) })) },
    { label: "Exportar…", icon: "download", onClick: () => openExport([v.id]) },
    "sep",
    ytUrl(v) && { label: "Abrir en YouTube", icon: "external", onClick: () => window.open(ytUrl(v), "_blank", "noopener") },
    ytUrl(v) && { label: "Copiar enlace", icon: "link", onClick: () => copyText(ytUrl(v), "Enlace") },
    { label: picked ? "Quitar de la selección" : "Seleccionar", icon: "check", onClick: () => {
      if (picked) lib.picked.delete(v.id); else lib.picked.add(v.id);
      if (currentView() === "library") renderLibrary();
    } },
    "sep",
    isOwner() && coll?.kind === "propia" && { label: "Quitar de la colección", icon: "x", onClick: () => send({ type: "coll_toggle", coll: coll.id, video: v.id, on: false }) },
    isOwner() && { label: "Eliminar video", icon: "trash", danger: true, onClick: async () => {
      if (await confirmDlg("¿Eliminar este video?", "Va a la papelera con su traducción, sus voces y lo descargado. Puedes devolverlo durante 30 días.", "Eliminar")) {
        send({ type: "lib_delete", videos: [v.id] });
      }
    } },
  ];
}

/* ------------------------------------------------------------ colección */
function collMenu(c) {
  const auto = c.kind === "auto" || ["home", "recent", "all"].includes(c.id);
  const go = () => { lib.sel = c.id; lib.picked.clear(); if (typeof closeSearch === "function") closeSearch(); currentView() === "library" ? renderLibrary() : setView("library"); };
  const first = c.items?.find((id) => lib.videos[id]?.media) || c.items?.[0];
  return [
    { head: c.name },
    { label: "Abrir", icon: "arrow", onClick: go },
    first && { label: c.kind === "playlist" ? "Reproducir la playlist" : "Reproducir", icon: "play", onClick: () => {
      setContext({ name: c.name, coll: c.id, auto: true });
      playItem(first);
    } },
    canImport() && ["propia", "categoría", "playlist"].includes(c.kind) && { label: "Importar aquí…", icon: "import", onClick: () => openMulti("", c.id) },
    c.items?.length && { label: "Exportar todo…", icon: "download", onClick: () => openExport(c.items, c.name) },
    "sep",
    !auto && c.kind !== "canal" && { label: "Otro patrón", icon: "shuffle", onClick: () => { reshufflePattern(c.id); renderLibrary(); } },
    c.kind === "playlist" && c.url && { label: "Abrir en YouTube", icon: "external", onClick: () => window.open(c.url, "_blank", "noopener") },
    isOwner() && c.kind === "propia" && { label: "Renombrar…", icon: "pencil", onClick: async () => {
      const name = await promptDlg("Renombrar colección", c.name, "Guardar");
      if (name && name !== c.name) send({ type: "coll_rename", coll: c.id, name });
    } },
    "sep",
    isOwner() && (c.kind === "propia" || c.kind === "playlist") && { label: c.kind === "playlist" ? "Eliminar playlist" : "Eliminar colección", icon: "trash", danger: true,
      onClick: async () => {
        const extra = c.kind === "playlist" ? "Los videos descargados se quedan; los pendientes salen de la cola." : "Los videos no se borran.";
        if (await confirmDlg(`¿Eliminar «${c.name}»?`, extra, "Eliminar")) send({ type: "coll_delete", coll: c.id });
      } },
  ];
}

/* ------------------------------------------------------------ cola */
function jobMenu(j) {
  const v = videoInfo(j.id) || { id: j.id, title: j.id };
  return [
    { head: v.title || j.id },
    { label: "Ver", icon: "play", disabled: !v.media && v.source !== "youtube", onClick: () => {
      closeQueue();
      if (j.lib && j.lib !== vaults.current) return playAcross(v.id, j.lib);  // de otra biblioteca
      playItem(v.id);
    } },
    canImport() && j.state === "en cola" && !j.prio && { label: "Priorizar", icon: "up", onClick: () => send({ type: "queue_add", video: j.id, front: true }) },
    canImport() && j.state === "descargado" && { label: "Traducir y doblar", icon: "spark", onClick: () => send({ type: "queue_add", video: j.id }) },
    ytUrl(v) && { label: "Copiar enlace", icon: "link", onClick: () => copyText(ytUrl(v), "Enlace") },
    "sep",
    isOwner() && { label: "Quitar de la cola", icon: "x", danger: true, onClick: () => send({ type: "queue_remove", video: j.id }) },
  ];
}

/* ------------------------------------------------------------ transcripción y video */
function lineMenu(li) {
  const s = state.segments.find((x) => String(x.id) === li.dataset.id);
  if (!s) return null;
  return [
    { label: "Ir a este momento", icon: "play", kbd: fmt(s.start), onClick: () => { vEn.currentTime = s.start; } },
    "sep",
    s.translation && { label: "Copiar en español", icon: "copy", onClick: () => copyText(s.translation, "Texto") },
    { label: "Copiar en inglés", icon: "copy", onClick: () => copyText(s.text, "Texto") },
    ytUrl(lib.videos[state.videoId]) && { label: "Copiar enlace a este momento", icon: "link",
      onClick: () => copyText(`${ytUrl(lib.videos[state.videoId])}&t=${Math.floor(s.start)}s`, "Enlace") },
    "sep",
    isOwner() && { label: "Comentar", icon: "comment", onClick: () => {
      state.editing = { seg: s.id, id: null, draft: "" };
      renderTranscript();
      focusEditor();
    } },
  ];
}

function playerMenu() {
  const dub = !!$("#c-lang button.on[data-v='es']");
  return [
    { label: vEn.paused ? "Reproducir" : "Pausar", icon: vEn.paused ? "play" : "pause", kbd: "Espacio", onClick: togglePlay },
    { label: dub ? "Escuchar el original" : "Escuchar en español", icon: "speaker", onClick: () => $(`#c-lang button[data-v='${dub ? "en" : "es"}']`)?.click() },
    { label: "Pantalla completa", icon: "fullscreen", onClick: toggleFull },
    "sep",
    { label: document.body.classList.contains("side-off") ? "Mostrar la transcripción" : "Ocultar la transcripción", icon: "comment", onClick: () => $("#side-toggle").click() },
    isOwner() && { label: "Guardar en…", icon: "bookmark", onClick: () => $("#save").click() },
    canImport() && needsVideo(lib.videos[state.videoId]) && !jobOf(state.videoId)?.fetch_video
      && { label: "Bajar el video completo", icon: "film", onClick: () => fetchVideo(state.videoId) },
    { label: "Exportar…", icon: "download", onClick: () => $("#export-btn").click() },
    ytUrl(lib.videos[state.videoId]) && { label: "Copiar enlace a este momento", icon: "link",
      onClick: () => copyText(`${ytUrl(lib.videos[state.videoId])}&t=${Math.floor(vEn.currentTime)}s`, "Enlace") },
  ];
}

/* ------------------------------------------------------------ general */
function generalMenu() {
  const mini = document.body.classList.contains("side-mini");
  return [
    canImport() && { label: "Importar enlaces…", icon: "import", onClick: () => openMulti("", lib.collections.some((c) => c.id === lib.sel && ["propia", "categoría", "playlist"].includes(c.kind)) ? lib.sel : "") },
    canImport() && { label: "Importar archivos…", icon: "upload", onClick: () => $("#file").click() },
    isOwner() && { label: "Nueva colección…", icon: "plus", onClick: async () => {
      const name = await promptDlg("Nueva colección", "", "Crear");
      if (name) send({ type: "coll_create", name });
    } },
    "sep",
    { label: "Inicio", icon: "home", onClick: goHome },
    { label: "Cola", icon: "queue", onClick: () => setView("queue") },
    isOwner() && { label: "Preferencias", icon: "sliders", onClick: () => setView("prefs") },
    "sep",
    currentView() !== "player" && innerWidth > 760 && { label: mini ? "Expandir la barra lateral" : "Contraer la barra lateral", icon: "sidebar", onClick: () => setSideMini(!mini) },
    { label: "Recargar", icon: "reload", kbd: "F5", onClick: () => location.reload() },
  ];
}

/* ------------------------------------------------------------ dónde se hizo clic */
function menuFor(t) {
  const collOf = (id) => lib.collections.find((c) => c.id === id) || (id === "home" ? { id, name: "Inicio", kind: "auto", items: [] } : null);
  const card = t.closest(".card[data-id]");
  if (card && lib.videos[card.dataset.id]) return videoMenu(lib.videos[card.dataset.id], collOf(card.dataset.coll));
  const up = t.closest("#upnext li[data-id]");
  if (up && lib.videos[up.dataset.id]) return videoMenu(lib.videos[up.dataset.id], null);
  const q = t.closest(".qitem[data-id]");
  if (q) { const j = lib.queue.jobs.find((x) => x.id === q.dataset.id); if (j) return jobMenu(j); }
  const nav = t.closest("[data-coll]") || (t.closest(".shelf-head.has-banner, .cbanner") && { dataset: { coll: lib.sel } });
  if (nav) { const c = collOf(nav.dataset.coll); if (c) return collMenu(c); }
  const line = t.closest("#transcript li[data-id]");
  if (line && !t.closest(".notes")) return lineMenu(line);
  if (t.closest("#pane-en .screen")) return playerMenu();
  return generalMenu();
}

document.addEventListener("contextmenu", (e) => {
  const t = e.target;
  // campos de texto, texto seleccionado y enlaces: el menú del navegador
  if (t.closest("input, textarea, [contenteditable], a[href]") || String(getSelection()).trim()) return;
  if (t.closest(".login, dialog")) return;
  const items = menuFor(t);
  if (!items) return;
  e.preventDefault();
  openMenu(items, { x: e.clientX, y: e.clientY });
});
