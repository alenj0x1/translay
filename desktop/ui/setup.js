"use strict";
// Setup and loading screens of the desktop app (src-tauri/src/lib.rs):
//   first launch  → "Preparar Translay": hardware, library folder, install the server with progress on the button;
//                   then "Elige cómo usar Translay": the profile (recommended one first), which installs the voice
//                   engine only if it has voice and downloads its models (vt/modelset.py), so Translay opens ready
//   every launch  → "Abriendo Translay" while the server loads its models; then the window opens Translay
//   server stopped → its last lines, "Reintentar" and the logs folder
// el(), icon() and btn() come from Translay's web/js/ui.js (shared/).

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const win = window.__TAURI__.window.getCurrentWindow();
const $ = (s) => document.querySelector(s);

const STEP_TEXT = { server: "Instalando el servidor", voice: "Instalando el motor de voz", models: "Descargando modelos" };
const gb = (bytes) => (bytes / 1e9).toLocaleString("es", { maximumFractionDigits: 1, minimumFractionDigits: 1 });

let status = null;
let dataDir = "";

function show(id) {
  for (const s of document.querySelectorAll(".panel")) s.hidden = s.id !== id;
}

// ------------------------------------------------------------ title bar
function initTitleBar() {
  const theme = $("#theme-btn");
  const syncTheme = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    const label = dark ? "Cambiar a claro" : "Cambiar a oscuro";
    theme.replaceChildren(icon(dark ? "sun" : "moon"));
    theme.title = label;
    theme.setAttribute("aria-label", label);
  };
  theme.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.classList.add("theme-switch");  // no button fades between themes
    document.documentElement.dataset.theme = next;
    requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.remove("theme-switch")));
    try { localStorage.setItem("vt-theme-block", next); } catch (e) { /* no storage */ }
    invoke("set_theme", { theme: next });
    syncTheme();
  });
  syncTheme();
  $("#win-min").append(icon("minimize"));
  $("#win-close").append(icon("x"));
  $("#win-min").addEventListener("click", () => win.minimize());
  $("#win-close").addEventListener("click", () => invoke("close_window"));
  const max = $("#win-max");
  const syncMax = async () => {
    const on = await win.isMaximized();
    document.documentElement.classList.toggle("maximized", on);
    max.replaceChildren(icon(on ? "unmaximize" : "maximize"));
    max.title = on ? "Restaurar" : "Maximizar";
    max.setAttribute("aria-label", max.title);
  };
  max.addEventListener("click", () => win.toggleMaximize());
  window.addEventListener("resize", syncMax);
  syncMax();
  $(".bar").addEventListener("dblclick", (e) => { if (e.target.hasAttribute("data-tauri-drag-region")) win.toggleMaximize(); });
  for (const n of document.querySelectorAll("[data-ic]")) n.append(icon(n.dataset.ic));
}

// ------------------------------------------------------------ first launch
function renderSetup() {
  const g = status.gpu;
  $("#gpu").textContent = g ? `${g.name}${g.vram_mb ? ` · ${Math.round(g.vram_mb / 1024)} GB` : ""}` : "Sin GPU NVIDIA";
  const mode = $("#mode");
  mode.textContent = status.voice ? "Voz en español" : "Solo subtítulos";
  mode.className = "tag" + (status.voice ? " ok" : "");
  $("#data-dir").textContent = dataDir;
  setBtn($("#pick"), "Cambiar…", "pencil");
  // first time: only the server; the profile chosen next decides the voice engine and the models
  $("#size").textContent = status.data_chosen
    ? (status.voice_chosen && !status.voice_installed ? "El motor de voz, unos 4,8 GB, para el perfil que elegiste."
      : "Lo que cambió en esta versión.")
    : "El servidor, unos 2 GB. Después eliges el perfil: según él se instala el motor de voz y se bajan sus modelos.";
  setBtn($("#install"), status.server_ok ? "Actualizar e instalar" : "Instalar", "download");
  show("setup");
}

$("#pick").addEventListener("click", async () => {
  const dir = await invoke("pick_folder");
  if (dir) { dataDir = dir; $("#data-dir").textContent = dir; }
});

let installing = false;
let working = { btn: "#install", note: "#install-note", verb: "Instalando" };  // where progress shows

function busy(b, verb) {
  b.classList.add("dl", "busy");
  b.style.setProperty("--p", "0%");
  setBtn(b, `${verb} 0 %`, "download");
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
    idle(b, "Reintentar", "reload");
    $("#pick").disabled = false;
    $("#install-note").textContent = String(e);
  }
}
$("#install").addEventListener("click", install);

listen("setup", ({ payload: p }) => {
  if (p.percent == null || p.state === "error") return;
  const b = $(working.btn);
  b.style.setProperty("--p", `${p.percent}%`);
  setBtn(b, `${working.verb} ${p.percent} %`, "download");
  if (p.step && p.total_bytes) {
    $(working.note).textContent = `${STEP_TEXT[p.step]}${p.step === "models" && p.label ? ` · ${p.label}` : ""} · ${gb(p.done_bytes)} de ${gb(p.total_bytes)} GB`;
  }
});

// ------------------------------------------------------------ profile
let plans = null;
let chosen = "";

async function chooseProfile() {
  show("profile");
  $("#profiles").replaceChildren(el("div", { class: "row" }, el("p", { class: "note", text: "Midiendo tu equipo…" })));
  setBtn($("#prepare"), "Instalar y abrir", "download");
  $("#prepare").disabled = true;
  try {
    plans = await invoke("profiles", { dataDir });
  } catch (e) {
    $("#profiles").replaceChildren();
    setBtn($("#prepare"), "Reintentar", "reload");
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
    const facts = [p.voice ? "Con voz en español" : "Solo subtítulos", p.state_label,
      bytes ? `Descarga ${gb(bytes)} GB` : "Ya está descargado"];
    const b = el("button", { type: "button", class: "row pick" + (p.id === chosen ? " on" : ""), disabled: blocked,
      on: { click: () => { chosen = p.id; renderProfiles(); } } },
      el("span", { class: "radio" }),
      el("div", { class: "row-text" },
        el("strong", {}, p.name, p.id === plans.recommended ? el("span", { class: "tag ok", text: "Recomendado" }) : null),
        el("p", { text: blocked ? "Necesita una GPU NVIDIA con al menos 4 GB para la voz." : p.desc }),
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
  try {
    await invoke("install", { voice: p.voice });  // the voice engine, only if this profile uses it
    // the recommended one stays automatic: it follows the machine if it changes
    await invoke("prepare", { dataDir, profile: chosen === plans.recommended ? "auto" : chosen });  // «auto»: solo el recomendado
    await start();
  } catch (e) {
    installing = false;
    idle(b, "Reintentar", "reload");
    renderProfiles();
    $("#prepare-note").textContent = String(e);
  }
}
$("#prepare").addEventListener("click", prepare);

// ------------------------------------------------------------ loading
function loadingLine(line) {
  const bar = $("#load-bar").parentElement;
  const pct = /(\d{1,3})%\|/.exec(line);
  if (pct) {  // model download (Hugging Face progress bar)
    bar.classList.remove("wait");
    $("#load-bar").style.setProperty("--p", `${pct[1]}%`);
    $("#load-line").textContent = `Descargando modelos ${pct[1]} %`;
    return;
  }
  if (/^(Equipo|Preparando)/.test(line)) {
    bar.classList.add("wait");
    $("#load-line").textContent = line.replace(/…$/, "") + "…";
  }
}

async function start() {
  $("#load-line").textContent = "";
  $("#load-bar").parentElement.classList.add("wait");
  show("loading");
  await invoke("start", { dataDir: status.data_chosen ? null : dataDir });
}

listen("server", ({ payload: p }) => {
  if (p.state === "starting") loadingLine(p.line);
  if (p.state === "error") failed(p.tail || []);
});

// ------------------------------------------------------------ stopped
function failed(tail) {
  const lines = tail.filter((l) => l.trim());
  $("#fail-msg").textContent = "El servidor se cerró. Estas son sus últimas líneas:";
  $("#fail-log").textContent = lines.slice(-20).join("\n") || "Sin salida.";
  setBtn($("#retry"), "Reintentar", "reload");
  setBtn($("#open-logs"), "Abrir registros", "folder");
  show("failed");
}
$("#retry").addEventListener("click", () => start().catch((e) => failed([String(e)])));
$("#open-logs").addEventListener("click", () => invoke("open_folder", { which: "logs" }));

// ------------------------------------------------------------ boot
(async () => {
  initTitleBar();
  status = await invoke("status");
  dataDir = status.data_dir;
  if (new URLSearchParams(location.search).has("error")) {
    failed(await invoke("server_tail"));
  } else if (status.ready) {
    start().catch((e) => failed([String(e)]));
  } else {
    renderSetup();
    // a new version with different packages: update without asking (the folder was already chosen)
    if (status.data_chosen) install();
  }
})();
