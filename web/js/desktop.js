"use strict";
// App de escritorio (desktop/, Tauri): la misma página, dentro de una ventana propia.
// - El encabezado hace de barra de título: se arrastra, y a la derecha van Preferencias y claro/oscuro
//   como íconos, más minimizar, maximizar y cerrar (la barra de Windows toma el color de acento del
//   sistema, no el del tema).
// - Preferencias suma la página «App de escritorio»: qué hace la ventana al cerrarla, dónde está la
//   biblioteca Principal, los registros y las actualizaciones.
// - Actualizaciones (desktop/src-tauri/src/updates.rs, firmadas con la clave de Translay): busca sola al
//   abrir y cada 6 h (salvo que se apague), o con «Buscar actualizaciones». Con una versión nueva aparece
//   un botón en la barra de título; nunca se instala mientras hay trabajo (espera a que termine).
// - En la bandeja (ventana cerrada con «Seguir en la bandeja»), cuando no queda trabajo en la cola,
//   Translay se cierra del todo: no deja modelos ni procesos ocupando la GPU o la RAM.
// En el navegador nada de esto existe (DESKTOP es false).

const DESKTOP = !!(window.__TAURI__ && window.__TAURI__.core);
const DESKTOP_SECTION = ["escritorio", "App de escritorio", "La ventana de Translay en este equipo.", "monitor"];

function desktopCall(cmd, args) {
  return window.__TAURI__.core.invoke(cmd, args);
}

const desktop = { info: null, maximized: false };

function desktopWindow() {
  return window.__TAURI__.window.getCurrentWindow();
}

function initDesktop() {
  document.documentElement.classList.add("desktop");
  const bar = $(".bar");
  bar.setAttribute("data-tauri-drag-region", "");
  // Preferencias: solo el ícono (la página ya tiene su título)
  const prefsBtn = $("#prefs-btn");
  prefsBtn.classList.add("ghost", "icon");
  prefsBtn.title = "Preferencias";
  prefsBtn.setAttribute("aria-label", "Preferencias");
  const themeBtn = el("button", { class: "btn ghost icon", id: "theme-btn", type: "button",
    on: { click: () => {
      const dark = document.documentElement.dataset.theme === "dark";
      setPref("theme_mode", dark ? "claro" : "oscuro");
      applyTheme();
      renderPrefs();
    } } });
  const winBtn = (id, label, ic, fn) => el("button", { class: "btn ghost icon win-btn", id, type: "button", title: label,
    "aria-label": label, on: { click: fn } }, icon(ic));
  const maxBtn = winBtn("win-max", "Maximizar", "maximize", () => desktopWindow().toggleMaximize());
  const updateBtn = el("button", { class: "btn ghost icon", id: "update-btn", type: "button", hidden: true,
    on: { click: () => openPrefs("escritorio") } }, icon("update"));
  bar.append(updateBtn, themeBtn, el("div", { class: "win-controls" },
    winBtn("win-min", "Minimizar", "minimize", () => desktopWindow().minimize()),
    maxBtn,
    winBtn("win-close", "Cerrar", "x", () => desktopCall("close_window"))));
  // actualización, prefs-btn y theme-btn van juntos, justo antes de los controles de la ventana
  bar.insertBefore(prefsBtn, themeBtn);
  bar.insertBefore(updateBtn, prefsBtn);

  const syncTheme = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    desktopCall("set_theme", { theme: dark ? "dark" : "light" });  // la próxima vez la ventana abre con este tema
    const label = dark ? "Cambiar a claro" : "Cambiar a oscuro";
    themeBtn.replaceChildren(icon(dark ? "sun" : "moon"));
    themeBtn.title = label;
    themeBtn.setAttribute("aria-label", label);
  };
  syncTheme();
  new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  const syncMax = async () => {
    desktop.maximized = await desktopWindow().isMaximized();
    document.documentElement.classList.toggle("maximized", desktop.maximized);
    const label = desktop.maximized ? "Restaurar" : "Maximizar";
    maxBtn.replaceChildren(icon(desktop.maximized ? "unmaximize" : "maximize"));
    maxBtn.title = label;
    maxBtn.setAttribute("aria-label", label);
  };
  syncMax();
  window.addEventListener("resize", syncMax);
  // doble clic en el encabezado: maximizar o restaurar, como en cualquier ventana
  bar.addEventListener("dblclick", (e) => { if (e.target === bar) desktopWindow().toggleMaximize(); });

  window.__TAURI__.event.listen("update", (e) => {
    const p = e.payload || {};
    upd.state = p.state;
    upd.pct = p.pct ?? null;
    upd.mb = p.mb ?? null;
    renderUpdate();
  });
  desktopCall("desktop_info").then((info) => {
    desktop.info = info;
    setTimeout(() => checkUpdate(false), 20000);  // al abrir, sin competir con el arranque
  });
  setInterval(() => checkUpdate(false), 6 * 3600 * 1000);
}

/* ------------------------------------------------------------ actualizaciones */
// state: idle · checking · latest · available · downloading · installing · error
const upd = { state: "idle", info: null, error: "", pct: null, whenIdle: false, notified: false };

async function checkUpdate(manual) {
  if (!manual && (!desktop.info?.auto_update || upd.state === "available")) return;
  if (["checking", "downloading", "installing"].includes(upd.state)) return;
  upd.state = "checking";
  upd.error = "";
  renderUpdate();
  try {
    const info = await desktopCall("check_update");
    if (upd.state !== "checking") return;  // mientras tanto empezó una descarga: no se pisa
    upd.info = info;
    upd.state = info.available ? "available" : "latest";
  } catch (e) {
    if (upd.state !== "checking") return;
    // sin conexión, la búsqueda automática no molesta (ni olvida una versión ya encontrada)
    upd.state = manual ? "error" : upd.info?.available ? "available" : "idle";
    upd.error = String(e);
  }
  renderUpdate();
  if (upd.state === "available" && !manual && !upd.notified) {
    upd.notified = true;
    toast(`Hay una versión nueva de Translay: ${upd.info.version}.`, "ok", { label: "Ver", onClick: () => openPrefs("escritorio") });
  }
}

// con trabajo en curso (cola, descargas, exportaciones) espera a que termine, salvo «Actualizar ahora»:
// la cola sigue sola al volver a abrir (cada video retoma desde donde quedó)
async function installUpdate(now = false) {
  if (desktopBusy() && !now) {
    upd.whenIdle = true;
    renderUpdate();
    return;
  }
  if (now && desktopBusy() && !(await confirmDlg("¿Actualizar ahora?",
    "La cola se detiene y sigue sola al volver a abrir Translay, desde donde quedó. Una exportación en curso se cancela.",
    "Actualizar ahora"))) return;
  upd.whenIdle = false;
  upd.state = "downloading";
  upd.pct = 0;
  renderUpdate();
  try {
    await desktopCall("install_update");  // instala, cierra Translay y lo vuelve a abrir
  } catch (e) {
    upd.state = "error";
    upd.error = String(e);
    renderUpdate();
  }
}

function renderUpdate() {
  const b = $("#update-btn");
  if (b) {
    b.hidden = !(upd.state === "available" || upd.state === "downloading" || upd.state === "installing");
    const label = upd.info?.version ? `Translay ${upd.info.version} disponible` : "Actualización disponible";
    b.title = label;
    b.setAttribute("aria-label", label);
  }
  desktop.renderPrefs?.();
}

// notas de la versión (Markdown de CHANGELOG.es.md, en latest.json): títulos y viñetas, en texto
function updateNotes(md) {
  const box = el("div", { class: "upd-notes" });
  for (const raw of String(md || "").split("\n")) {
    const line = raw.trim();
    if (!line || line === "---") continue;
    const clean = line.replace(/^#+\s*/, "").replace(/^[-*]\s+/, "").replace(/\*\*|`/g, "");
    box.append(el(/^#/.test(line) ? "strong" : "p", { text: clean }));
  }
  return box.childElementCount ? box : null;
}

function updateRows(row) {
  const info = desktop.info || {};
  const v = upd.info?.version;
  const busy = upd.state === "checking" || upd.state === "downloading" || upd.state === "installing";
  const working = upd.state === "available" && desktopBusy();  // la cola o una exportación trabajan
  const status = {
    idle: "Las versiones nuevas llegan firmadas desde GitHub.",
    checking: "Buscando…",
    latest: "Tienes la última versión.",
    available: upd.whenIdle ? `Translay ${v} se instala cuando termine lo que está procesando.`
      : working ? `Translay ${v} está disponible. Hay trabajo en curso: puedes esperar a que termine o actualizar ahora.`
        : `Translay ${v} está disponible.`,
    downloading: `Descargando Translay ${v}…`,
    installing: "Instalando: Translay se cierra y vuelve a abrirse.",
    error: upd.error,
  }[upd.state] || "";
  let actions;
  if (upd.state === "downloading" || upd.state === "installing") {
    actions = [btn(upd.state === "downloading" ? (upd.pct != null ? `Descargando ${upd.pct} %` : `Descargando ${upd.mb ?? 0} MB`) : "Instalando…", { icon: "update", disabled: true })];
  } else if (upd.state === "available" && (working || upd.whenIdle)) {
    actions = [
      upd.whenIdle ? null : btn("Actualizar al terminar", { icon: "clock", onClick: () => installUpdate() }),
      btn("Actualizar ahora", { icon: "update", onClick: () => installUpdate(true) }),
    ];
  } else if (upd.state === "available") {
    actions = [btn(`Actualizar a ${v}`, { icon: "update", onClick: () => installUpdate() })];
  } else {
    actions = [btn(upd.state === "checking" ? "Buscando…" : "Buscar actualizaciones", { icon: "reload", disabled: busy,
      onClick: () => checkUpdate(true) })];
  }
  const auto = (value, ic, text) => el("button", { type: "button", class: "seg" + (!!info.auto_update === value ? " on" : ""),
    on: { click: () => desktopCall("set_auto_update", { enabled: value }).then(() => { info.auto_update = value; renderUpdate(); }) } },
    icon(ic), text);
  return [
    row("Buscar actualizaciones", info.auto_update ? "Al abrir Translay y cada 6 horas." : "Solo cuando lo pidas.",
      el("div", { class: "segs" }, auto(true, "reload", "Automáticamente"), auto(false, "x", "Solo a mano"))),
    row(`Translay ${info.version || ""}`, status, ...actions),
    upd.state === "available" || upd.state === "downloading" ? updateNotes(upd.info?.notes) : null,
  ];
}

// ¿Queda algo por hacer? Trabajos en cola o procesándose (de todas las bibliotecas, sin pausa),
// descargas abiertas o exportaciones en curso.
function desktopBusy() {
  const q = lib.queue || { jobs: [] };
  // con la cola en pausa igual se procesa el video que se está viendo
  const pending = q.jobs.some((j) => j.state === "procesando" || j.dl) || (!q.paused && q.jobs.some((j) => j.state === "en cola"));
  const exporting = (lib.exports || []).some((x) => x.state !== "listo" && x.state !== "error");
  return pending || exporting || Object.keys(state.downloads || {}).length > 0;
}

// Cada 15 s: dos revisiones seguidas sin trabajo (30 s) le avisan a la app, que cierra Translay solo
// si la ventana está en la bandeja (minimizada o a la vista no cuenta; la página no lo puede saber).
let desktopIdle = 0;
setInterval(() => {
  if (!DESKTOP || typeof lib === "undefined") return;
  desktopIdle = desktopBusy() ? 0 : desktopIdle + 1;
  if (desktopIdle >= 2 && upd.whenIdle) return installUpdate();  // «Actualizar al terminar»
  if (desktopIdle >= 2) desktopCall("quit_if_in_tray");
}, 15000);

// Página «App de escritorio» de Preferencias (web/js/app.js, PREF_BLOCKS)
function desktopPrefsBlocks() {
  const box = el("div", { class: "set-rows desk-rows" });
  const render = () => {
    const info = desktop.info || {};
    const choose = (value) => {
      desktopCall("set_close_to_tray", { enabled: value }).then(() => { info.close_to_tray = value; render(); });
    };
    const seg = (value, ic, text) => el("button", { type: "button", class: "seg" + (!!info.close_to_tray === value ? " on" : ""),
      on: { click: () => choose(value) } }, icon(ic), text);
    const row = (title, desc, ...ctl) => el("div", { class: "set-row" },
      el("div", { class: "set-text" }, el("strong", { text: title }), desc ? el("p", { class: "desk-path", text: desc }) : null),
      el("div", { class: "set-ctl" }, ...ctl));
    box.replaceChildren(
      row("Al cerrar la ventana", info.close_to_tray ? "Translay sigue en la bandeja mientras la cola tenga trabajo; al terminar, se cierra y libera todo." : "Translay se cierra por completo.",
        el("div", { class: "segs" }, seg(false, "x", "Salir"), seg(true, "tray", "Seguir en la bandeja"))),
      row("Biblioteca Principal", info.data_dir || "",
        btn("Abrir carpeta", { icon: "folder", onClick: () => desktopCall("open_folder", { which: "data" }) }),
        btn("Cambiar…", { icon: "pencil", onClick: () => desktopCall("change_data_dir") })),
      row("Registros", "Lo que escribe el servidor; sirve para reportar un problema.",
        btn("Abrir carpeta", { icon: "folder", onClick: () => desktopCall("open_folder", { which: "logs" }) })),
    );
  };
  const updBox = el("div", { class: "set-rows desk-rows" });
  const updRow = (title, desc, ...ctl) => el("div", { class: "set-row" },
    el("div", { class: "set-text" }, el("strong", { text: title }), desc ? el("p", { text: desc }) : null),
    el("div", { class: "set-ctl" }, ...ctl.filter(Boolean)));
  const renderUpd = () => updBox.replaceChildren(...updateRows(updRow).filter(Boolean));
  // lo que cambia (búsqueda, descarga) se ve al instante mientras la página está abierta
  desktop.renderPrefs = () => { if (updBox.isConnected) renderUpd(); };
  render();
  renderUpd();
  if (!desktop.info) desktopCall("desktop_info").then((info) => { desktop.info = info; render(); renderUpd(); });
  return [[box, "Ventana y datos", desktopVersion()], [updBox, "Actualizaciones", ""]];
}

function desktopVersion() {
  return desktop.info ? `Translay ${desktop.info.version} para Windows.` : "";
}

// después de los demás scripts: usa $ y setPref de app.js
if (DESKTOP) document.addEventListener("DOMContentLoaded", initDesktop);
