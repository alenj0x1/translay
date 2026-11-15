"use strict";
// Setup and loading screens of the desktop app (src-tauri/src/lib.rs):
//   first launch  → "Preparar Translay": hardware, library folder, install the server with progress on the button;
//                   then "Elige cómo usar Translay": the profile (recommended one first), which installs the voice
//                   engine only if it has voice and downloads its models (vt/modelset.py), so Translay opens ready;
//                   meanwhile the first-run wizard (wizard.js) sets up Translay, with that progress in its strip.
//                   The server starts when the models are in, but the window opens Translay only once the wizard
//                   ends (start with hold, then open_app); if it ends first, the startup strip shows until then
//   every launch  → the startup screen while the server loads its models: what it is loading, its progress and tips;
//                   then the window opens Translay
//   server stopped → its last lines, "Reintentar" and the logs folder
// Behind every screen, Translay's background scene (the one chosen in Ajustes › Apariencia; «Translay» the first
// time) in its accent color and language, as the app reported them last time (index.html, i18n.js).
// el(), icon() and btn() come from Translay's web/js/ui.js; wordmark() from brand.js and mountScene() from
// scenes.js (all in shared/).

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const win = window.__TAURI__.window.getCurrentWindow();
const $ = (s) => document.querySelector(s);

const STEP_TEXT = () => ({ server: t("Instalando el servidor"), voice: t("Instalando el motor de voz"), models: t("Descargando modelos") });
const gb = (bytes) => (bytes / 1e9).toLocaleString(I18N.lang, { maximumFractionDigits: 1, minimumFractionDigits: 1 });

let status = null;
let dataDir = "";

// ------------------------------------------------------------ title bar
// the title bar's icons and labels, in the current theme and language (also after the wizard changes them)
let titleMax = false;
function syncTitleBar() {
  const theme = $("#theme-btn");
  const dark = document.documentElement.dataset.theme === "dark";
  const label = dark ? t("Cambiar a claro") : t("Cambiar a oscuro");
  theme.replaceChildren(icon(dark ? "sun" : "moon"));
  theme.title = label;
  theme.setAttribute("aria-label", label);
  const max = $("#win-max");
  max.replaceChildren(icon(titleMax ? "unmaximize" : "maximize"));
  for (const [b, text] of [[$("#win-min"), t("Minimizar")], [$("#win-close"), t("Cerrar")], [max, titleMax ? t("Restaurar") : t("Maximizar")]]) {
    b.title = text;
    b.setAttribute("aria-label", text);
  }
}

function initTitleBar() {
  $("#theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.classList.add("theme-switch");  // no button fades between themes
    document.documentElement.dataset.theme = next;
    requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.remove("theme-switch")));
    try { localStorage.setItem("vt-theme-block", next); } catch (e) { /* no storage */ }
    invoke("set_theme", { theme: next });
    if (wizardOpen()) wizardTheme(next);  // the mode chosen in the wizard follows it
    syncTitleBar();
  });
  $("#win-min").append(icon("minimize"));
  $("#win-close").append(icon("x"));
  $("#win-min").addEventListener("click", () => win.minimize());
  $("#win-close").addEventListener("click", () => invoke("close_window"));
  const syncMax = async () => {
    titleMax = await win.isMaximized();
    document.documentElement.classList.toggle("maximized", titleMax);
    syncTitleBar();
  };
  $("#win-max").addEventListener("click", () => win.toggleMaximize());
  window.addEventListener("resize", syncMax);
  syncTitleBar();
  syncMax();
  $(".bar").addEventListener("dblclick", (e) => { if (e.target.hasAttribute("data-tauri-drag-region")) win.toggleMaximize(); });
  for (const n of document.querySelectorAll("[data-ic]")) n.append(icon(n.dataset.ic));
}

// ------------------------------------------------------------ Translay's look: its scene and its logo
function initLook() {
  const scene = (window.__TRANSLAY_LOOK__ || {}).scene;
  mountScene($("#scene"), SCENES[scene] ? scene : "translay");  // a photo background or none: the default scene
}

function show(id) {
  for (const s of document.querySelectorAll(".panel")) s.hidden = s.id !== id;
  document.body.classList.toggle("starting", id === "loading");  // the startup strip carries the logo itself
  // the strip's logo is measured once it is on screen (hidden, its text has no width)
  const mark = $("#loading .wordmark");
  if (id === "loading" && !mark.firstChild?.tagName) wordmark(mark, 26);
}

// ------------------------------------------------------------ first launch
function renderSetup() {
  const g = status.gpu;
  $("#gpu").textContent = g ? `${g.name}${g.vram_mb ? ` · ${Math.round(g.vram_mb / 1024)} GB` : ""}` : t("Sin GPU NVIDIA");
  const mode = $("#mode");
  mode.textContent = status.voice ? t("Con voz") : t("Solo subtítulos");
  mode.className = "tag" + (status.voice ? " ok" : "");
  $("#data-dir").textContent = dataDir;
  setBtn($("#pick"), t("Cambiar…"), "pencil");
  // first time: only the server; the profile chosen next decides the voice engine and the models
  $("#size").textContent = status.data_chosen
    ? (status.voice_chosen && !status.voice_installed ? t("El motor de voz, unos 4,8 GB, para el perfil que elegiste.")
      : t("Lo que cambió en esta versión."))
    : t("El servidor, unos 2 GB. Después eliges el perfil: según él se instala el motor de voz y se bajan sus modelos.");
  setBtn($("#install"), status.server_ok ? t("Actualizar e instalar") : t("Instalar"), "download");
  show("setup");
}

$("#pick").addEventListener("click", async () => {
  const dir = await invoke("pick_folder");
  if (dir) { dataDir = dir; $("#data-dir").textContent = dir; }
});

let installing = false;
// where progress shows; verb is the Spanish text, translated when shown
let working = { btn: "#install", note: "#install-note", verb: "Instalando" };

function busy(b, verb) {
  b.classList.add("dl", "busy");
  b.style.setProperty("--p", "0%");
  setBtn(b, `${t(verb)} 0 %`, "download");
}
function idle(b, label, ic) {
  b.classList.remove("dl", "busy");
  setBtn(b, label, ic);
}

async function install() {
  if (installing) return;
  installing = true;
  const b = $("#install");
  working = { btn: "#install", note: "#install-note", verb: "Instalando" };
  busy(b, "Instalando");
  $("#pick").disabled = true;
  $("#install-note").textContent = "";
  try {
    if (status.data_chosen) {  // update or a voice engine asked for inside Translay: as chosen before
      await invoke("install", {});
      await start();
    } else {  // first time: the server, then the profile
      await invoke("install", { voice: false });
      installing = false;
      await chooseProfile();
    }
  } catch (e) {
    installing = false;
    idle(b, t("Reintentar"), "reload");
    $("#pick").disabled = false;
    $("#install-note").textContent = String(e);
  }
}
$("#install").addEventListener("click", install);

listen("setup", ({ payload: p }) => {
  if (p.percent == null || p.state === "error") return;
  const b = $(working.btn);
  b.style.setProperty("--p", `${p.percent}%`);
  // downloaded, now unpacking: say so instead of a percent that stands still
  const finishing = p.state === "finishing";
  setBtn(b, finishing ? t("Terminando de instalar") : `${t(working.verb)} ${p.percent} %`, "download");
  if (p.step && p.total_bytes) {
    const label = p.step === "models" && p.label ? ` · ${p.label}` : "";
    $(working.note).textContent = `${STEP_TEXT()[p.step]}${label} · ${t("{a} de {b} GB", { a: gb(p.done_bytes), b: gb(p.total_bytes) })}`;
  }
  // the first-run wizard shows the same in its bottom strip (and the startup strip, if the wizard already ended)
  if (wizardOpen() || wizardEnded) {
    const what = STEP_TEXT()[p.step] || t("Preparando");
    const size = p.total_bytes ? ` · ${t("{a} de {b} GB", { a: gb(p.done_bytes), b: gb(p.total_bytes) })}` : "";
    progressSay(finishing ? `${what} · ${t("Terminando de instalar")}` : `${what}${size}`, finishing ? null : p.percent);
  }
});

// where the first launch is, for the wizard's strip or the startup strip, whichever is on screen
const lastProgress = { text: "", pct: null };
function progressSay(text, pct) {
  lastProgress.text = text;
  lastProgress.pct = pct;
  if (wizardOpen()) wzProgress(text, pct);
  else stripSay(text, pct);
}

// ------------------------------------------------------------ profile
let plans = null;
let chosen = "";

async function chooseProfile() {
  show("profile");
  $("#profiles").replaceChildren(el("div", { class: "row" }, el("p", { class: "note", text: t("Midiendo tu equipo…") })));
  setBtn($("#prepare"), t("Instalar y abrir"), "download");
  $("#prepare").disabled = true;
  try {
    plans = await invoke("profiles", { dataDir });
  } catch (e) {
    $("#profiles").replaceChildren();
    setBtn($("#prepare"), t("Reintentar"), "reload");
    $("#prepare").disabled = false;
    $("#prepare").onclick = () => { $("#prepare").onclick = null; chooseProfile(); };
    $("#prepare-note").textContent = String(e);
    return;
  }
  $("#prepare-note").textContent = "";
  // el recomendado, salvo que tenga voz y esta GPU no pueda con ella: entonces el primero que sí
  const can = (p) => !(p.voice && !status.voice);
  chosen = can(plans.profiles.find((p) => p.id === plans.recommended) || {}) ? plans.recommended
    : (plans.profiles.find(can) || plans.profiles[plans.profiles.length - 1]).id;
  renderProfiles();
}

function renderProfiles() {
  const voiceOk = status.voice;  // a GPU that can run the voice engine
  $("#profiles").replaceChildren(...plans.profiles.map((p) => {
    const blocked = p.voice && !voiceOk;
    const bytes = p.download_bytes + (p.voice && p.voice_env ? plans.voice_env_bytes : 0);
    const facts = [p.voice ? t("Con voz") : t("Solo subtítulos"), p.state_label,
      bytes ? t("Descarga {n} GB", { n: gb(bytes) }) : t("Ya está descargado")];
    const b = el("button", { type: "button", class: "row pick" + (p.id === chosen ? " on" : ""), disabled: blocked,
      on: { click: () => { chosen = p.id; renderProfiles(); } } },
      el("span", { class: "radio" }),
      el("div", { class: "row-text" },
        el("strong", {}, p.name, p.id === plans.recommended ? el("span", { class: "tag ok", text: t("Recomendado") }) : null),
        el("p", { text: blocked ? t("Necesita una GPU NVIDIA con al menos 4 GB para la voz.") : p.desc }),
        el("p", { class: "facts", text: facts.join(" · ") })));
    return b;
  }));
  $("#prepare").disabled = false;
}

async function prepare() {
  if (installing || !plans) return;
  installing = true;
  const p = plans.profiles.find((x) => x.id === chosen);
  const b = $("#prepare");
  working = { btn: "#prepare", note: "#prepare-note", verb: "Preparando" };
  busy(b, "Preparando");
  for (const r of document.querySelectorAll("#profiles .pick")) r.disabled = true;
  $("#prepare-note").textContent = "";
  // first launch: the wizard opens while all of this downloads (wizard.js); its strip shows the progress
  if (!status.data_chosen && !wizardOpen() && !wizardEnded) {
    openWizard({ dataDir, voice: p.voice, onDone: wizardDone });
    wzProgress(p.voice ? STEP_TEXT().voice : STEP_TEXT().models, null);
  }
  try {
    await invoke("install", { voice: p.voice });  // the voice engine, only if this profile uses it
    // the recommended one stays automatic: it follows the machine if it changes
    await invoke("prepare", { dataDir, profile: chosen === plans.recommended ? "auto" : chosen });  // «auto»: solo el recomendado
    await start();
  } catch (e) {
    installing = false;
    idle(b, t("Reintentar"), "reload");
    renderProfiles();
    $("#prepare-note").textContent = String(e);
    if (wizardOpen()) wzProgress(String(e), null, "error", prepare);
    else if (wizardEnded) show("profile");  // the wizard already ended: the profile screen with the error and «Reintentar»
  }
}

// the wizard ended: Translay opens now if the server is ready; if not, the startup strip shows until it is
let wizardEnded = false;
function wizardDone(ready) {
  wizardEnded = true;
  if (!ready) {
    show("loading");
    rotateTips();
    stripSay(lastProgress.text || t("Abriendo Translay"), lastProgress.pct);  // where the download or the loading is
  }
  invoke("open_app").catch(() => {});
}
$("#prepare").addEventListener("click", prepare);

// ------------------------------------------------------------ startup: what is loading and tips
// What the server prints while it starts (vt/app.py, vt/modelset.py), in words. Lines it does not describe keep the
// last step on screen.
function stripSay(text, pct) {
  $("#load-line").textContent = text;
  $("#load-pct").textContent = pct == null ? "" : `${pct} %`;
  $("#load-bar").parentElement.classList.toggle("wait", pct == null);
  if (pct != null) $("#load-bar").style.setProperty("--p", `${pct}%`);
}
function loadingLine(line) {
  const say = progressSay;  // the startup strip, or the wizard's while it is open
  const dl = /^Descargando (.+?): (\d{1,3})%\|/.exec(line);
  if (dl) return say(t("Descargando {x}", { x: dl[1] }), +dl[2]);
  const pct = /(\d{1,3})%\|/.exec(line);
  // «Fetching N files» is Hugging Face checking what is already on disk, not a download
  if (pct) return say(/^Fetching/.test(line) ? t("Revisando los modelos") : t("Descargando modelos"), +pct[1]);
  if (/^Equipo/.test(line)) return say(t("Revisando el equipo"));
  if (/^Preparando traductor/.test(line)) return say(t("Cargando el traductor"));
  if (/^Preparando/.test(line)) return say(t("Cargando el reconocimiento de voz"));
}

// in the language loaded at boot (a function: the catalogue arrives after this file runs)
const TIPS = () => [
  t("Pasa el mouse por el texto escrito en un video para copiarlo o preguntarle a Lumi."),
  t("Ver dividido muestra el original y el traducido lado a lado."),
  t("Mientras un video se procesa, la línea de avance marca lo que ya tiene voz."),
  t("La velocidad del video cambia sin alterar el tono de la voz."),
  t("Doble clic en el borde de un panel lo devuelve a su ancho habitual."),
  t("El fondo y el color de énfasis se cambian en Ajustes › Apariencia."),
  t("Cada biblioteca tiene su propio color y su patrón."),
];
let tipTimer = 0;
function rotateTips() {
  clearInterval(tipTimer);
  const box = $("#tip");
  let i = Math.floor(Math.random() * TIPS().length);
  const next = () => {
    box.classList.add("out");
    setTimeout(() => {
      const tips = TIPS();  // in the language of now (the wizard may have changed it)
      box.textContent = tips[i % tips.length];
      i = (i + 1) % tips.length;
      box.classList.remove("out");
    }, box.textContent ? 260 : 0);
  };
  next();
  tipTimer = setInterval(next, 8000);
}

async function start() {
  progressSay(t("Abriendo Translay"), null);
  // while the first-run wizard is open the window stays on it when the server is ready (open_app releases it)
  const hold = wizardOpen();
  if (!hold) {
    show("loading");
    rotateTips();
  }
  await invoke("start", { dataDir: status.data_chosen ? null : dataDir, hold });
}

listen("server", ({ payload: p }) => {
  if (p.state === "starting") loadingLine(p.line);
  if (p.state === "ready" && wizardOpen()) wzProgress(t("Translay está listo"), 100, "ready");
  if (p.state === "error") failed(p.tail || []);
});

// ------------------------------------------------------------ stopped
function failed(tail) {
  clearInterval(tipTimer);
  if (wizardOpen()) {  // the server stopped during the wizard: what was chosen is kept, «Reintentar» opens Translay
    finishWizard(false);
    wizardEnded = true;
    invoke("open_app").catch(() => {});
  }
  const lines = tail.filter((l) => l.trim());
  $("#fail-msg").textContent = t("El servidor se cerró. Estas son sus últimas líneas");
  $("#fail-log").textContent = lines.slice(-20).join("\n") || t("Sin salida");
  setBtn($("#retry"), t("Reintentar"), "reload");
  setBtn($("#open-logs"), t("Abrir registros"), "folder");
  show("failed");
}
$("#retry").addEventListener("click", () => start().catch((e) => failed([String(e)])));
$("#open-logs").addEventListener("click", () => invoke("open_folder", { which: "logs" }));

// ------------------------------------------------------------ boot
(async () => {
  await loadI18n();
  initTitleBar();
  initLook();
  initWizardButtons();
  status = await invoke("status");
  dataDir = status.data_dir;
  const query = new URLSearchParams(location.search);
  if (query.has("error")) {
    failed(await invoke("server_tail"));
  } else if (query.has("welcome") && status.ready) {
    // «Ver la bienvenida» (Ajustes › App de escritorio): the wizard again over what is installed; Translay keeps
    // running behind it and opens again when it ends
    openWizard({ dataDir, voice: status.voice !== false, replay: true, onDone: () => invoke("open_app").catch(() => {}) });
    wzProgress(t("Todo listo"), 100, "ready");
  } else if (status.ready) {
    start().catch((e) => failed([String(e)]));
  } else {
    renderSetup();
    // a new version with different packages: update without asking (the folder was already chosen)
    if (status.data_chosen) install();
  }
})();
