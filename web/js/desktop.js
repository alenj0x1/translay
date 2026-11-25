"use strict";
// App de escritorio (desktop/, Tauri): la misma página, dentro de una ventana propia.
// - El encabezado hace de barra de título: se arrastra, y a la derecha van Ajustes y claro/oscuro
//   como íconos, más minimizar, maximizar y cerrar (la barra de Windows toma el color de acento del
//   sistema, no el del tema).
// - Ajustes suma la página «App de escritorio»: qué hace la ventana al cerrarla, dónde está la
//   biblioteca Principal, los registros y las actualizaciones.
// - Versiones nuevas (vt/updates.py): busca sola al abrir y cada 6 h (salvo que se apague), o con «Buscar
//   actualizaciones». Con una versión nueva aparece un botón en la barra de título y «Descargar» abre el
//   instalador en el navegador; la app no descarga ni ejecuta nada por su cuenta.
// - En la bandeja (ventana cerrada con «Seguir en la bandeja»), cuando no queda trabajo en la cola (o está
//   detenida), Translay se cierra del todo: no deja modelos ni procesos ocupando la GPU o la RAM.
// - Subtítulos en vivo sobre cualquier ventana: un botón en la barra de título y una fila en «App de escritorio»
//   abren o cierran la franja (setLiveSubs).
// En el navegador nada de esto existe (DESKTOP es false).

const DESKTOP = !!(window.__TAURI__ && window.__TAURI__.core);
const DESKTOP_SECTION = ["escritorio", t("App de escritorio"), t("La ventana de Translay en este equipo."), "monitor"];
i18nTrack(DESKTOP_SECTION);  // al cambiar de idioma, sus textos también cambian (i18n.js)

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
  // Ajustes: solo el ícono (la página ya tiene su título)
  const prefsBtn = $("#prefs-btn");
  prefsBtn.classList.add("ghost", "icon");
  prefsBtn.title = t("Ajustes");
  prefsBtn.setAttribute("aria-label", t("Ajustes"));
  const themeBtn = el("button", { class: "btn ghost icon", id: "theme-btn", type: "button",
    on: { click: () => {
      const dark = document.documentElement.dataset.theme === "dark";
      setPref("theme_mode", dark ? "claro" : "oscuro");
      applyTheme();
      renderPrefs();
    } } });
  const winBtn = (id, label, ic, fn) => el("button", { class: "btn ghost icon win-btn", id, type: "button", title: label,
    "aria-label": label, on: { click: fn } }, icon(ic));
  const maxBtn = winBtn("win-max", t("Maximizar"), "maximize", () => desktopWindow().toggleMaximize());
  const updateBtn = el("button", { class: "btn ghost icon", id: "update-btn", type: "button", hidden: true,
    on: { click: () => openPrefs("escritorio") } }, icon("update"));
  // subtítulos en vivo sobre cualquier ventana (live.js): encendidos, el botón queda marcado
  const liveBtn = el("button", { class: "btn ghost icon", id: "live-btn", type: "button",
    on: { click: () => setLiveSubs(!desktop.live) } }, icon("captions"));
  bar.append(updateBtn, liveBtn, themeBtn, el("div", { class: "win-controls" },
    winBtn("win-min", t("Minimizar"), "minimize", () => desktopWindow().minimize()),
    maxBtn,
    // una grabación en curso se detiene y se guarda antes (capture.js)
    winBtn("win-close", t("Cerrar"), "x", async () => {
      if (typeof capSettle === "function") await capSettle();
      desktopCall("close_window");
    })));
  // actualización, subtítulos en vivo, prefs-btn y theme-btn van juntos, justo antes de los controles de la ventana
  bar.insertBefore(prefsBtn, themeBtn);
  bar.insertBefore(liveBtn, prefsBtn);
  bar.insertBefore(updateBtn, liveBtn);
  renderLive();
  desktopCall("live_state").then((on) => { desktop.live = !!on; renderLive(); }).catch(() => {});
  // la franja también se cierra sola (el servidor se detuvo): el botón lo refleja
  window.__TAURI__.event.listen("live", (e) => { desktop.live = !!e.payload?.on; renderLive(); });

  const syncTheme = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    desktopCall("set_theme", { theme: dark ? "dark" : "light" });  // la próxima vez la ventana abre con este tema
    const label = dark ? t("Cambiar a claro") : t("Cambiar a oscuro");
    themeBtn.replaceChildren(icon(dark ? "sun" : "moon"));
    themeBtn.title = label;
    themeBtn.setAttribute("aria-label", label);
  };
  syncTheme();
  new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // el color de énfasis, el fondo y el idioma: la pantalla de arranque de la próxima vez se pinta con ellos
  let lookSent = "", lookTimer = 0;
  const syncLook = () => {
    clearTimeout(lookTimer);
    lookTimer = setTimeout(() => {
      let accent = "none";
      try { accent = localStorage.getItem("vt-accent") || "#7d5ba6"; } catch (e) { /* sin almacenamiento */ }
      const look = { accent: /^#[0-9a-f]{6}$/i.test(accent) ? accent.toLowerCase() : "none",
        scene: typeof homeBgMode === "function" ? homeBgMode() : "translay", lang: I18N.lang || "es" };
      const key = JSON.stringify(look);
      if (key !== lookSent) { lookSent = key; desktopCall("set_look", look); }
    }, 400);
  };
  syncLook();
  new MutationObserver(syncLook).observe(document.documentElement, { attributes: true, attributeFilter: ["style", "lang"] });
  new MutationObserver(syncLook).observe(document.body, { childList: true });

  const syncMax = async () => {
    desktop.maximized = await desktopWindow().isMaximized();
    document.documentElement.classList.toggle("maximized", desktop.maximized);
    const label = desktop.maximized ? t("Restaurar") : t("Maximizar");
    maxBtn.replaceChildren(icon(desktop.maximized ? "unmaximize" : "maximize"));
    maxBtn.title = label;
    maxBtn.setAttribute("aria-label", label);
  };
  syncMax();
  window.addEventListener("resize", syncMax);
  snapLayouts(maxBtn);
  // doble clic en el encabezado: maximizar o restaurar, como en cualquier ventana
  bar.addEventListener("dblclick", (e) => { if (e.target === bar) desktopWindow().toggleMaximize(); });

  desktopCall("desktop_info").then((info) => {
    desktop.info = info;
    setTimeout(() => checkUpdate(false), 20000);  // al abrir, sin competir con el arranque
  });
  setInterval(() => checkUpdate(false), 6 * 3600 * 1000);
}

// Diseños de ajuste de Windows 11 (elegir dónde va la ventana): Windows los muestra solo sobre su propio
// botón de maximizar; con la barra propia se piden a la app al dejar el mouse encima o mantenerlo presionado.
// En Windows 10 no existen: la app responde false y no se vuelve a pedir.
function snapLayouts(maxBtn) {
  let timer = 0, held = false, supported = true;
  const show = () => {
    if (!supported) return;
    desktopCall("snap_layouts").then((ok) => { supported = !!ok; }).catch(() => { supported = false; });
  };
  const cancel = () => { clearTimeout(timer); timer = 0; };
  maxBtn.addEventListener("pointerenter", () => { cancel(); timer = setTimeout(show, 700); });
  maxBtn.addEventListener("pointerleave", cancel);
  maxBtn.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    cancel();
    held = false;
    timer = setTimeout(() => { held = true; show(); }, 450);
  });
  maxBtn.addEventListener("pointerup", cancel);
  // mantenerlo presionado abrió los diseños: ese clic no maximiza
  maxBtn.addEventListener("click", (e) => { if (held) { held = false; e.stopImmediatePropagation(); e.preventDefault(); } }, true);
}

/* ------------------------------------------------------------ subtítulos en vivo */
// Una franja abajo de la pantalla, encima de cualquier ventana (llamadas, juegos, transmisiones), con la traducción
// de lo que suena en el equipo (desktop/src-tauri/src/live.rs y web/live.html). Deja pasar los clics; se mueve con
// la manija que aparece al pasar el mouse y recuerda dónde quedó. Se cierra con Translay.
function setLiveSubs(on) {
  desktopCall("live_set", { on })
    .then((now) => { desktop.live = !!now; renderLive(); })
    .catch((e) => { toast(t("No se pudieron abrir los subtítulos en vivo. {error}", { error: String(e) })); clientError("vivo", String(e)); });
}

function renderLive() {
  const b = $("#live-btn");
  if (b) {
    b.classList.toggle("on", !!desktop.live);
    const label = desktop.live ? t("Ocultar los subtítulos en vivo") : t("Subtítulos en vivo sobre cualquier ventana");
    b.title = label;
    b.setAttribute("aria-label", label);
    b.setAttribute("aria-pressed", desktop.live ? "true" : "false");
  }
  desktop.renderLiveRow?.();
}

/* ------------------------------------------------------------ versiones nuevas */
// state: idle · checking · latest · available · opened · error
const upd = { state: "idle", info: null, error: "", notified: false, manual: false };

// el servidor consulta GitHub (vt/updates.py) y responde con un mensaje «update» (onUpdateInfo)
function checkUpdate(manual) {
  if (!manual && (!desktop.info?.auto_update || upd.state === "available" || upd.state === "opened")) return;
  if (upd.state === "checking") return;
  upd.state = "checking";
  upd.manual = manual;
  upd.error = "";
  renderUpdate();
  send({ type: "update_check", force: manual });
}

function onUpdateInfo(m) {
  if (m.error) {
    // sin conexión, la búsqueda automática no molesta (ni olvida una versión ya encontrada)
    upd.state = upd.manual ? "error" : upd.info?.available ? "available" : "idle";
    upd.error = m.error;
  } else {
    upd.info = m;
    upd.state = m.available ? "available" : "latest";
  }
  renderUpdate();
  if (upd.state === "available" && !upd.manual && !upd.notified) {
    upd.notified = true;
    toast(t("Translay {version} está disponible", { version: m.version }), "ok", { label: t("Ver"), onClick: () => openPrefs("escritorio") });
  }
}

// el instalador se baja y se ejecuta desde el navegador, como cualquier descarga
function openDownload() {
  desktopCall("open_download", { url: upd.info.download })
    .then(() => { upd.state = "opened"; renderUpdate(); })
    .catch((e) => { upd.state = "error"; upd.error = String(e); renderUpdate(); });
}

function renderUpdate() {
  const b = $("#update-btn");
  if (b) {
    b.hidden = !(upd.state === "available" || upd.state === "opened");
    const label = upd.info?.version ? t("Translay {version} disponible", { version: upd.info.version }) : t("Versión nueva disponible");
    b.title = label;
    b.setAttribute("aria-label", label);
  }
  desktop.renderPrefs?.();
}

// notas de la versión (Markdown de CHANGELOG.es.md, en la versión de GitHub): títulos y viñetas, en texto
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
  const status = {
    idle: t("Translay busca las versiones nuevas en GitHub."),
    checking: t("Buscando…"),
    latest: t("Tienes la última versión."),
    available: t("Translay {version} está disponible.", { version: v }),
    opened: t("La descarga de Translay {version} se abrió en el navegador. Ejecuta el instalador. Tu biblioteca y tus ajustes se conservarán.", { version: v }),
    error: upd.error,
  }[upd.state] || "";
  const actions = upd.state === "available" || upd.state === "opened"
    ? [btn(t("Descargar {version}", { version: v }), { icon: "download", onClick: openDownload })]
    : [btn(upd.state === "checking" ? t("Buscando…") : t("Buscar actualizaciones"), { icon: "reload", disabled: upd.state === "checking",
      onClick: () => checkUpdate(true) })];
  const auto = (value, ic, text) => el("button", { type: "button", class: "seg" + (!!info.auto_update === value ? " on" : ""),
    on: { click: () => desktopCall("set_auto_update", { enabled: value }).then(() => { info.auto_update = value; renderUpdate(); }) } },
    icon(ic), text);
  return [
    row(t("Buscar actualizaciones"), info.auto_update ? t("Al abrir Translay y cada 6 horas.") : t("Solo de forma manual."),
      el("div", { class: "segs" }, auto(true, "reload", t("Automáticamente")), auto(false, "x", t("Manualmente")))),
    row(`Translay ${info.version || ""}`, status, ...actions),
    upd.state === "available" || upd.state === "opened" ? updateNotes(upd.info?.notes) : null,
  ];
}

// ¿Queda algo por hacer? Trabajos en cola o procesándose (de todas las bibliotecas, sin pausa),
// descargas abiertas, exportaciones en curso o una grabación de pantalla (en curso o subiéndose).
function desktopBusy() {
  if (typeof capBusy === "function" && capBusy()) return true;
  if (desktop.live) return true;  // los subtítulos en vivo siguen a la vista
  const q = lib.queue || { jobs: [] };
  // con la cola detenida igual se procesa el video que se está viendo; lo detenido a mano no cuenta
  const pending = q.jobs.some((j) => j.state === "procesando" || j.dl)
    || (!q.paused && q.jobs.some((j) => j.state === "en cola" && !j.held));
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

// Página «App de escritorio» de Ajustes (web/js/app.js, PREF_BLOCKS)
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
    const liveSeg = (value, ic, text) => el("button", { type: "button", class: "seg" + (!!desktop.live === value ? " on" : ""),
      on: { click: () => setLiveSubs(value) } }, icon(ic), text);
    box.replaceChildren(
      row(t("Subtítulos en vivo"), t("La traducción de lo que suena en el equipo, abajo de la pantalla y encima de cualquier ventana. Los clics pasan a la ventana de atrás. Para moverla, arrastra la manija que aparece al pasar el mouse."),
        el("div", { class: "segs" }, liveSeg(false, "x", t("Ocultos")), liveSeg(true, "captions", t("Visibles")))),
      row(t("Al cerrar la ventana"), info.close_to_tray
        ? t("Translay permanece en la bandeja mientras haya trabajos en la cola y se cierra al terminar. Si la cola está detenida o vacía, se cierra de inmediato.")
        : t("Translay se cierra por completo."),
        el("div", { class: "segs" }, seg(false, "x", t("Salir")), seg(true, "tray", t("Minimizar a la bandeja")))),
      row(t("Biblioteca Principal"), info.data_dir || "",
        btn(t("Abrir carpeta"), { icon: "folder", onClick: () => desktopCall("open_folder", { which: "data" }) }),
        btn(t("Cambiar…"), { icon: "pencil", onClick: () => desktopCall("change_data_dir") })),
      row(t("Bienvenida"), t("Los pasos del primer uso, para cambiar todo de una vez."),
        btn(t("Ver la bienvenida"), { icon: "spark", onClick: () => desktopCall("show_welcome").catch(() => {}) })),
      row(t("Registros"), t("Registro del servidor, útil para reportar problemas."),
        btn(t("Abrir carpeta"), { icon: "folder", onClick: () => desktopCall("open_folder", { which: "logs" }) })),
    );
  };
  const updBox = el("div", { class: "set-rows desk-rows" });
  const updRow = (title, desc, ...ctl) => el("div", { class: "set-row" },
    el("div", { class: "set-text" }, el("strong", { text: title }), desc ? el("p", { text: desc }) : null),
    el("div", { class: "set-ctl" }, ...ctl.filter(Boolean)));
  const renderUpd = () => updBox.replaceChildren(...updateRows(updRow).filter(Boolean));
  // lo que cambia (búsqueda, descarga) se ve al instante mientras la página está abierta
  desktop.renderPrefs = () => { if (updBox.isConnected) renderUpd(); };
  desktop.renderLiveRow = () => { if (box.isConnected) render(); };
  render();
  renderUpd();
  if (!desktop.info) desktopCall("desktop_info").then((info) => { desktop.info = info; render(); renderUpd(); });
  return [[box, t("Ventana y datos"), desktopVersion()], [updBox, t("Actualizaciones"), ""]];
}

function desktopVersion() {
  return desktop.info ? t("Translay {version} para Windows.", { version: desktop.info.version }) : "";
}

// después de los demás scripts: usa $ y setPref de app.js
/* ------------------------------------------------------------ primer uso */
// El asistente de primer uso de la ventana (desktop/ui/wizard.js) ya preguntó todo mientras se instalaba Translay:
// lo elegido llega una sola vez (take_welcome) y se guarda con las mismas preferencias de Ajustes; la biblioteca
// principal toma su nombre, color, avatar y patrón. YouTube y el acceso desde otros equipos necesitan el servidor:
// se hacen aquí. La bienvenida de la página (web/js/welcome.js) queda para el navegador (sin instalador).
// welcome.js › maybeWelcome llama a esto con los ajustes y la biblioteca cargados.
const WELCOME_PREFS = ["app_mode", "target_lang", "transcribe_lang", "theme_mode", "accent_color", "home_bg",
  "agent_name", "agent_color", "agent_avatar", "language"];  // el idioma al final: cambia toda la página
let desktopWelcomed = false;
async function desktopWelcome() {
  if (desktopWelcomed) return;
  desktopWelcomed = true;
  let w = null;
  try { w = await desktopCall("take_welcome"); } catch (e) { /* de antes del asistente */ }
  if (w && typeof w === "object") applyDesktopWelcome(w);
  if (!prefs.welcomed) setPref("welcomed", true);
}

function applyDesktopWelcome(w) {
  const chosen = w.prefs && typeof w.prefs === "object" ? w.prefs : {};
  for (const key of WELCOME_PREFS) {
    const spec = prefsSchema.find((p) => p.key === key);
    const value = chosen[key];
    if (!spec || value === undefined || value === prefs[key]) continue;
    if (spec.options ? !spec.options.some(([o]) => o === value) : typeof value !== "string") continue;  // el servidor lo vuelve a validar
    setPref(key, value);
  }
  applyTheme();
  const d = w.library;
  const main = vaults.list.find((v) => v.main) || vaults.list[0];
  if (d && main) {
    const name = String(d.name || "").trim().slice(0, 60) || main.name;
    const color = VAULT_COLORS.includes(d.color) ? d.color : main.color;
    const ic = VAULT_ICONS.some(([k]) => k === d.icon) ? d.icon : main.icon;
    const pattern = /^[a-z0-9]{0,12}$/.test(d.pattern || "") ? d.pattern || "" : main.pattern || "";
    if (name !== main.name || color !== main.color || ic !== main.icon || pattern !== (main.pattern || "")) {
      send({ type: "vault_update", id: main.id, name, color, icon: ic, pattern });
    }
  }
  if (w.network === true) send({ type: "admin_network", on: true });
  // YouTube: Ajustes en su cuenta y la ventana del navegador para iniciar sesión (cuando llega cuál hay)
  if (w.youtube === true) {
    openPrefs("biblioteca");
    let tries = 0;
    const go = () => {
      if (canConnectYouTube(ytAcc.status)) {
        if (!ytAcc.status.connected) connectYouTube();
        $("#yt-account")?.scrollIntoView({ block: "center" });
      } else if (++tries < 30) setTimeout(go, 500);
    };
    setTimeout(go, 600);
  }
}

if (DESKTOP) document.addEventListener("DOMContentLoaded", initDesktop);
