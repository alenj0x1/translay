"use strict";
// Menú contextual (clic derecho): cambia según dónde se haga clic. Usa openMenu() de
// web/js/menu.js y lo global de app.js, library.js, vaults.js, home.js y patterns.js.
//   tarjeta de video · colección (barra lateral, fila del inicio, banner) · trabajo de la cola
//   frase de la transcripción · video · Siguientes · espacio libre
// En campos de texto, o con texto seleccionado, queda el menú del navegador.

const isOwner = () => !document.body.classList.contains("guest");
const canImport = () => document.body.classList.contains("can-import");
const ytUrl = (v) => (v?.source === "youtube" ? `https://www.youtube.com/watch?v=${v.id.slice(3)}` : "");
const shareUrl = (v) => ytUrl(v) || (v?.source === "link" ? v.url || "" : "");
// idioma en que se habla (lo ya reconocido en otro idioma se rehace)
async function setVideoLang(v, lang) {
  if (v.lang === lang) return;
  if (v.progress?.asr > 0 && !(await confirmDlg(t("¿Cambiar el idioma del video?"),
    t("Se borrará la transcripción actual y el video se procesará de nuevo."), t("Cambiar")))) return;
  v.lang = lang;
  if (v.id === state.videoId) applyLang(lang, translatesV(v));
  send({ type: "video_lang", video: v.id, lang });
}
// traducir y doblar, o solo transcribir: no borra nada (lo reconocido sirve en los dos)
function setVideoMode(v, mode) {
  v.mode = mode;
  if (v.id === state.videoId) { applyLang(v.lang, translatesV(v)); renderTranscript(); }
  send({ type: "video_lang", video: v.id, mode });
}
async function renameVideo(v) {
  const title = (await promptDlg(t("Renombrar video"), v.title || v.id, t("Guardar")))?.trim();
  if (title && title !== v.title) send({ type: "lib_rename", video: v.id, title });
}
const langMenu = (v) => ({ label: transcribeMode() ? t("Idioma") : t("Idioma y traducción"), icon: "globe", sub: [
  { head: t("Idioma del video") },
  ...Object.keys(LANGS).map((c) => ({ label: cap(langName(c)), check: (v.lang || "en") === c, onClick: () => setVideoLang(v, c) })),
  ...(transcribeMode() ? [] : langModes(v)),
] });
const langModes = (v) => [
  "sep",
  (v.lang || "en") !== targetLang() && (v.lang || "en") in LANGS && { label: t("Traducir y doblar"), icon: "spark", check: translatesV(v),
    onClick: () => setVideoMode(v, "translate") },
  { label: t("Solo transcribir"), icon: "comment", check: !translatesV(v), onClick: () => setVideoMode(v, "transcribe") },
];
// copiar: el portapapeles moderno solo existe en conexiones seguras (no desde otro equipo por http)
function copyText(text, what) {
  // `what` es un sustantivo («Enlace») o el aviso entero («Ruta copiada», ya traducido o no)
  const ok = () => toast(/\b(copiad[oa]s?|copied)\b/i.test(what) ? t(what) : t("{what} copiado", { what: t(what) }), "ok");
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(ok, () => legacyCopy(text) ? ok() : toast(t("No se pudo copiar")));
  } else if (legacyCopy(text)) ok();
  else toast(t("No se pudo copiar"));
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
  const canOpen = !!v.media || isRemote(v);
  const own = lib.collections.filter((c) => c.kind === "propia");
  const others = typeof vaults !== "undefined" ? vaults.list.filter((x) => x.id !== vaults.current) : [];
  const picked = lib.picked.has(v.id);
  const open = () => { if (coll) setContext({ name: coll.name, coll: coll.id, auto: coll.kind === "playlist" }); playItem(v.id); };
  return [
    { head: v.title || v.id },
    canOpen && { label: v.position > 5 ? t("Continuar") : t("Ver"), icon: "play", onClick: open },
    canOpen && v.position > 5 && { label: t("Ver desde el inicio"), icon: "reload", onClick: () => { v.position = 0; open(); } },
    canDownload(v) && { label: t("Descargar sin abrir"), icon: "download", onClick: () => downloadOnly(v) },
    "sep",
    canImport() && canProcess(v) && { label: translatesV(v) ? t("Traducir y doblar") : t("Transcribir"), icon: "spark", onClick: () => send({ type: "queue_add", video: v.id }) },
    canImport() && langMenu(v),
    isOwner() && { label: t("Renombrar…"), icon: "pencil", onClick: () => renameVideo(v) },
    canImport() && v.audio_only && isRemote(v) && !job?.fetch_video && { label: t("Descargar el video completo"), icon: "film", onClick: () => fetchVideo(v.id) },
    isOwner() && job && !["listo", "error"].includes(job.state) && { label: t("Quitar de la cola"), icon: "x", onClick: () => send({ type: "queue_remove", video: v.id }) },
    "sep",
    isOwner() && { label: t("Guardar en"), icon: "bookmark", sub: [
      ...own.map((c) => ({ label: c.name, badge: collBadge(c), check: c.items.includes(v.id),
        onClick: () => send({ type: "coll_toggle", coll: c.id, video: v.id, on: !c.items.includes(v.id) }) })),
      own.length ? "sep" : null,
      { label: t("Nueva colección…"), icon: "plus", onClick: async () => {
        const name = await promptDlg(t("Nueva colección"), "", t("Crear"));
        if (name) send({ type: "coll_create", name, video: v.id });
      } },
    ] },
    isOwner() && others.length && { label: t("Mover a"), icon: "folder", sub: others.map((x) => ({ label: x.name, badge: vaultBadge(x),
      onClick: () => send({ type: "vault_move", videos: [v.id], to: x.id }) })) },
    { label: t("Exportar…"), icon: "download", onClick: () => openExport([v.id]) },
    "sep",
    ytUrl(v) && { label: t("Abrir en YouTube"), icon: "external", onClick: () => window.open(ytUrl(v), "_blank", "noopener") },
    ytUrl(v) && { label: t("Copiar enlace"), icon: "link", onClick: () => copyText(ytUrl(v), "Enlace") },
    { label: picked ? t("Quitar de la selección") : t("Seleccionar"), icon: "check", onClick: () => {
      if (picked) lib.picked.delete(v.id); else lib.picked.add(v.id);
      if (currentView() === "library") renderLibrary();
    } },
    "sep",
    v.progress?.asr > 0 && { label: t("Copiar para un agente"), icon: "agent", onClick: () => copyForAgent(v.id, false) },
    isOwner() && coll?.kind === "propia" && { label: t("Quitar de la colección"), icon: "x", onClick: () => send({ type: "coll_toggle", coll: coll.id, video: v.id, on: false }) },
    isOwner() && { label: t("Eliminar video"), icon: "trash", danger: true, onClick: async () => {
      if (await confirmDlg(t("¿Eliminar este video?"), t("Se moverá a la papelera con su traducción, voces y archivos descargados. Puedes restaurarlo durante 30 días."), t("Eliminar"))) {
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
    { label: t("Abrir"), icon: "arrow", onClick: go },
    first && { label: c.kind === "playlist" ? t("Reproducir la playlist") : t("Reproducir"), icon: "play", onClick: () => {
      setContext({ name: c.name, coll: c.id, auto: true });
      playItem(first);
    } },
    canImport() && ["propia", "categoría", "playlist"].includes(c.kind) && { label: t("Agregar aquí…"), icon: "plus", onClick: () => openMulti("", c.id) },
    c.items?.length && { label: t("Exportar todo…"), icon: "download", onClick: () => openExport(c.items, c.name, c) },
    "sep",
    !auto && c.kind !== "canal" && { label: t("Otro color"), icon: "shuffle", onClick: () => { reshufflePattern(c.id); renderLibrary(); } },
    c.kind === "playlist" && c.url && { label: t("Abrir en YouTube"), icon: "external", onClick: () => window.open(c.url, "_blank", "noopener") },
    isOwner() && c.kind === "propia" && { label: t("Renombrar…"), icon: "pencil", onClick: async () => {
      const name = await promptDlg(t("Renombrar colección"), c.name, t("Guardar"));
      if (name && name !== c.name) send({ type: "coll_rename", coll: c.id, name });
    } },
    "sep",
    isOwner() && (c.kind === "propia" || c.kind === "playlist") && { label: c.kind === "playlist" ? t("Eliminar playlist") : t("Eliminar colección"), icon: "trash", danger: true,
      onClick: async () => {
        const extra = c.kind === "playlist" ? t("Los videos descargados se conservan. Los pendientes se quitan de la cola.") : t("Los videos no se borran.");
        if (await confirmDlg(t("¿Eliminar «{name}»?", { name: c.name }), extra, t("Eliminar"))) send({ type: "coll_delete", coll: c.id });
      } },
  ];
}

/* ------------------------------------------------------------ cola */
function jobMenu(j) {
  const v = videoInfo(j.id) || { id: j.id, title: j.id };
  const active = jobActive(j) && !j.watching;
  return [
    { head: v.title || j.id },
    { label: t("Abrir el video"), icon: "arrow", disabled: !v.media && !isRemote(v), onClick: () => openJob(j, v) },
    "sep",
    isOwner() && active && { label: j.held ? t("Continuar") : t("Detener"), icon: j.held ? "resume" : "stop",
      onClick: () => send({ type: "queue_hold", video: j.id, held: !j.held }) },
    canImport() && j.state === "en cola" && !j.prio && !j.watching && { label: t("Priorizar"), icon: "first",
      onClick: () => send({ type: "queue_add", video: j.id, front: true }) },
    canImport() && j.state === "descargado" && { label: translatesV(v) ? t("Traducir y doblar") : t("Transcribir"), icon: "spark",
      onClick: () => send({ type: "queue_add", video: j.id }) },
    isOwner() && { label: lib.queue.paused ? t("Continuar toda la cola") : t("Detener toda la cola"), icon: lib.queue.paused ? "resume" : "stop",
      onClick: () => send({ type: lib.queue.paused ? "queue_resume" : "queue_pause" }) },
    shareUrl(v) && { label: t("Copiar enlace"), icon: "link", onClick: () => copyText(shareUrl(v), "Enlace") },
    "sep",
    isOwner() && { label: t("Quitar de la cola"), icon: "x", danger: true, onClick: () => send({ type: "queue_remove", video: j.id }) },
  ];
}

/* ------------------------------------------------------------ transcripción y video */
function lineMenu(li) {
  const s = state.segments.find((x) => String(x.id) === li.dataset.id);
  if (!s) return null;
  return [
    { label: t("Ir a este momento"), icon: "play", kbd: fmt(s.start), onClick: () => { vEn.currentTime = s.start; } },
    "sep",
    state.translates && s.translation && { label: t("Copiar en {lang}", { lang: langName(targetLang()) }), icon: "copy", onClick: () => copyText(s.translation, "Texto") },
    { label: state.translates ? t("Copiar en {lang}", { lang: langName(state.lang) }) : t("Copiar"), icon: "copy", onClick: () => copyText(s.text, "Texto") },
    ytUrl(lib.videos[state.videoId]) && { label: t("Copiar enlace a este momento"), icon: "link",
      onClick: () => copyText(`${ytUrl(lib.videos[state.videoId])}&t=${Math.floor(s.start)}s`, "Enlace") },
    { label: t("Copiar todo para un agente"), icon: "agent", onClick: () => copyForAgent(state.videoId, true) },
    "sep",
    isOwner() && { label: t("Comentar"), icon: "comment", onClick: () => {
      state.editing = { seg: s.id, id: null, draft: "" };
      renderTranscript();
      focusEditor();
    } },
  ];
}

// un elemento del video en la transcripción (código, comando, enlace…)
function elementMenu(li) {
  const e = (state.elements || []).find((x) => String(x.id) === li.dataset.el);
  if (!e) return null;
  return [
    { label: t("Ir a este momento"), icon: "play", kbd: fmt(e.start), onClick: () => { vEn.currentTime = e.start; } },
    "sep",
    { label: t("Copiar {what}", { what: (ELEMENT_LABEL[e.kind] || t("Texto")).toLowerCase() }), icon: "copy", onClick: () => copyText(e.text, ELEMENT_LABEL[e.kind] || "Texto") },
    { label: t("Preguntar a Lumi"), icon: "agent", onClick: () => askAgentAbout(e) },
    e.kind === "link" && { label: t("Abrir el enlace"), icon: "external", onClick: () => window.open(/^https?:/i.test(e.text) ? e.text : `https://${e.text}`, "_blank", "noopener") },
    { label: t("Copiar todos los elementos"), icon: "copy", onClick: () => copyText(elementsText(), t("Elementos copiados")) },
    { label: t("Copiar todo para un agente"), icon: "agent", onClick: () => copyForAgent(state.videoId, true) },
  ];
}

// clic derecho sobre algo escrito en el video: copiarlo o preguntarle al agente, y lo del video debajo
function screenHitMenu(it) {
  const label = HIT_LABEL[it.kind] || t("Texto");
  return [
    { label: t("Copiar {what}", { what: label.toLowerCase() }), icon: "copy", onClick: () => copyText(hitText(it), label) },
    it.kind === "link" && { label: t("Abrir el enlace"), icon: "external", onClick: () => window.open(/^https?:/i.test(it.text) ? it.text : `https://${it.text}`, "_blank", "noopener") },
    { label: t("Preguntar a Lumi"), icon: "agent", onClick: () => askAgentAbout(it) },
    "sep",
    ...playerMenu(),
  ];
}

function playerMenu() {
  const dub = !!$("#c-lang button.on[data-v='es']");
  return [
    { label: vEn.paused ? t("Reproducir") : t("Pausar"), icon: vEn.paused ? "play" : "pause", kbd: t("Espacio"), onClick: togglePlay },
    state.translates && { label: dub ? t("Escuchar el original") : t("Escuchar en {lang}", { lang: langName(targetLang()) }), icon: "speaker", onClick: () => $(`#c-lang button[data-v='${dub ? "en" : "es"}']`)?.click() },
    { label: t("Pantalla completa"), icon: "fullscreen", onClick: toggleFull },
    { label: t("Subtítulos"), icon: "captions", kbd: "C", sub: subsMenu() },
    "sep",
    { label: t("Copiar para un agente"), icon: "agent", onClick: () => copyForAgent(state.videoId, true) },
    { label: document.body.classList.contains("side-off") ? t("Mostrar el panel") : t("Ocultar el panel"), icon: "sidebar", onClick: () => setSide(document.body.classList.contains("side-off")) },
    isOwner() && lib.videos[state.videoId] && { label: t("Renombrar…"), icon: "pencil", onClick: () => renameVideo(lib.videos[state.videoId]) },
    isOwner() && { label: t("Guardar en…"), icon: "bookmark", onClick: () => $("#save").click() },
    canImport() && needsVideo(lib.videos[state.videoId]) && !jobOf(state.videoId)?.fetch_video
      && { label: t("Descargar el video completo"), icon: "film", onClick: () => fetchVideo(state.videoId) },
    { label: t("Exportar…"), icon: "download", onClick: () => $("#export-btn").click() },
    ytUrl(lib.videos[state.videoId]) && { label: t("Copiar enlace a este momento"), icon: "link",
      onClick: () => copyText(`${ytUrl(lib.videos[state.videoId])}&t=${Math.floor(vEn.currentTime)}s`, "Enlace") },
  ];
}

/* ------------------------------------------------------------ general */
function generalMenu() {
  const mini = document.body.classList.contains("side-mini");
  return [
    canImport() && { label: t("Agregar enlaces…"), icon: "plus", onClick: () => openMulti("", lib.collections.some((c) => c.id === lib.sel && ["propia", "categoría", "playlist"].includes(c.kind)) ? lib.sel : "") },
    canImport() && { label: t("Agregar archivos…"), icon: "upload", onClick: () => $("#file").click() },
    isOwner() && { label: t("Nueva colección…"), icon: "plus", onClick: async () => {
      const name = await promptDlg(t("Nueva colección"), "", t("Crear"));
      if (name) send({ type: "coll_create", name });
    } },
    "sep",
    { label: t("Inicio"), icon: "home", onClick: goHome },
    { label: t("Cola"), icon: "queue", onClick: () => setView("queue") },
    isOwner() && { label: t("Ajustes"), icon: "gear", onClick: () => setView("prefs") },
    "sep",
    currentView() !== "player" && innerWidth > 760 && { label: mini ? t("Expandir la barra lateral") : t("Contraer la barra lateral"), icon: "sidebar", onClick: () => setSideMini(!mini) },
    { label: t("Recargar"), icon: "reload", kbd: "F5", onClick: () => location.reload() },
  ];
}

/* ------------------------------------------------------------ una exportación (Cola) */
function exportMenu(x) {
  const done = x.state === "listo" || x.state === "error";
  return [
    x.state === "listo" && x.path && state.access?.local && { label: t("Mostrar en el Explorador"), icon: "folder", onClick: () => revealExport(x) },
    x.state === "listo" && x.path && { label: t("Copiar la ruta"), icon: "copy", onClick: () => copyText(x.path, t("Ruta copiada")) },
    x.state === "listo" && !x.path && { label: t("Descargar"), icon: "download", onClick: () => download(x) },
    { label: done ? t("Quitar de la lista") : t("Cancelar"), icon: "x", onClick: () => send({ type: "export_remove", job: x.id }) },
  ].filter(Boolean);
}

/* ------------------------------------------------------------ resumen (panel lateral) */
function summaryMenu() {
  const s = state.summary;
  const job = state.summaryJob && state.summaryJob.state !== "error";
  return [
    s && { label: t("Copiar el resumen"), icon: "copy", onClick: () => copyText(summaryText(), t("Resumen copiado")) },
    s && { label: t("Exportar el resumen"), icon: "download", onClick: () => { openExport([state.videoId]); checkOnlyKind("summary"); } },
    canImport() && s && !job && { label: t("Regenerar el resumen"), icon: "reload", onClick: () => requestSummary(true) },
    canImport() && job && { label: t("Cancelar el resumen"), icon: "x", onClick: () => send({ type: "summary_cancel", video: state.videoId }) },
  ].filter(Boolean);
}

/* ------------------------------------------------------------ dónde se hizo clic */
// clic derecho en la barra de avance: ese momento (preguntarle al agente, ir ahí, copiarlo)
function trackMenu(x) {
  const r = $("#track").getBoundingClientRect();
  const d = vEn.duration || 0;
  if (!d || !r.width) return null;
  const at = Math.max(0, Math.min(d, ((x - r.left) / r.width) * d));
  return [
    { label: t("Preguntar a {agent} sobre {time}", { agent: agentName(), time: fmt(at) }), icon: "agent", onClick: () => agentMention(at) },
    { label: t("Ir a {time}", { time: fmt(at) }), icon: "play", onClick: () => { vEn.currentTime = at; } },
    { label: t("Copiar el momento"), icon: "copy", onClick: () => copyText(fmt(at), "Momento") },
  ];
}

function menuFor(target) {
  const collOf = (id) => lib.collections.find((c) => c.id === id) || (id === "home" ? { id, name: t("Inicio"), kind: "auto", items: [] } : null);
  const card = target.closest(".card[data-id]");
  if (card && lib.videos[card.dataset.id]) return videoMenu(lib.videos[card.dataset.id], collOf(card.dataset.coll));
  const up = target.closest("#upnext li[data-id]");
  if (up && lib.videos[up.dataset.id]) return videoMenu(lib.videos[up.dataset.id], null);
  const ex = target.closest(".qitem[data-export]");
  if (ex) { const x = lib.exports.find((j) => j.id === ex.dataset.export); if (x) return exportMenu(x); }
  const q = target.closest(".qitem[data-id]");
  if (q) { const j = lib.queue.jobs.find((x) => x.id === q.dataset.id); if (j) return jobMenu(j); }
  const nav = target.closest("[data-coll]") || (target.closest(".shelf-head.has-banner, .cbanner") && { dataset: { coll: lib.sel } });
  if (nav) { const c = collOf(nav.dataset.coll); if (c) return collMenu(c); }
  if (target.closest("#ag-summary")) { const items = summaryMenu(); if (items.length) return items; }
  const msg = target.closest("#ag-msgs li[data-i]");
  if (msg) return agentMsgMenu(msg);
  const line = target.closest("#transcript li[data-id]");
  if (line && !target.closest(".notes")) return lineMenu(line);
  const elRow = target.closest("#transcript li.el-row");
  if (elRow) return elementMenu(elRow);
  const hit = target.closest(".st-hit, .st-item");
  if (hit?._item) return screenHitMenu(hit._item);
  if (target.closest(".stage .screen")) return playerMenu();  // también el video en español (vista dividida)
  return generalMenu();
}

document.addEventListener("contextmenu", (e) => {
  const t = e.target;
  // campos de texto, texto seleccionado y enlaces: el menú del navegador
  // (el check de una miniatura no: ahí va el menú del video)
  if (t.closest("input:not([type=checkbox]), textarea, [contenteditable], a[href]") || String(getSelection()).trim()) return;
  if (t.closest(".login, dialog")) return;
  const items = t.closest("#track") ? trackMenu(e.clientX) : menuFor(t);
  if (!items) return;
  e.preventDefault();
  openMenu(items, { x: e.clientX, y: e.clientY });
});
