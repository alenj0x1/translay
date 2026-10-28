"use strict";
// App de escritorio (desktop/, Tauri): la misma página, dentro de una ventana propia.
// - El encabezado hace de barra de título: se arrastra, y a la derecha van Preferencias y claro/oscuro
//   como íconos, más minimizar, maximizar y cerrar (la barra de Windows toma el color de acento del
//   sistema, no el del tema).
// - Preferencias suma la página «App de escritorio»: qué hace la ventana al cerrarla, dónde está la
//   biblioteca Principal y los registros.
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
  bar.append(themeBtn, el("div", { class: "win-controls" },
    winBtn("win-min", "Minimizar", "minimize", () => desktopWindow().minimize()),
    maxBtn,
    winBtn("win-close", "Cerrar", "x", () => desktopCall("close_window"))));
  // prefs-btn y theme-btn van juntos, justo antes de los controles de la ventana
  bar.insertBefore(prefsBtn, themeBtn);

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

  desktopCall("desktop_info").then((info) => { desktop.info = info; });
}

// ¿Queda algo por hacer? Trabajos en cola o procesándose (de todas las bibliotecas, sin pausa),
// descargas abiertas o exportaciones en curso.
function desktopBusy() {
  const q = lib.queue || { jobs: [] };
  const pending = !q.paused && q.jobs.some((j) => j.state === "en cola" || j.state === "procesando" || j.dl);
  const exporting = (lib.exports || []).some((x) => x.state !== "listo" && x.state !== "error");
  return pending || exporting || Object.keys(state.downloads || {}).length > 0;
}

// Cada 15 s: dos revisiones seguidas sin trabajo (30 s) le avisan a la app, que cierra Translay solo
// si la ventana está en la bandeja (minimizada o a la vista no cuenta; la página no lo puede saber).
let desktopIdle = 0;
setInterval(() => {
  if (!DESKTOP || typeof lib === "undefined") return;
  desktopIdle = desktopBusy() ? 0 : desktopIdle + 1;
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
  render();
  if (!desktop.info) desktopCall("desktop_info").then((info) => { desktop.info = info; render(); });
  return [[box, "Ventana y datos", desktopVersion()]];
}

function desktopVersion() {
  return desktop.info ? `Translay ${desktop.info.version} para Windows.` : "";
}

// después de los demás scripts: usa $ y setPref de app.js
if (DESKTOP) document.addEventListener("DOMContentLoaded", initDesktop);
