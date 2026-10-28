"use strict";
// Setup and loading screens of the desktop app (src-tauri/src/lib.rs):
//   first launch  → "Preparar Translay": hardware, library folder, install with progress on the button
//   every launch  → "Abriendo Translay" while the server loads its models; then the window opens Translay
//   server stopped → its last lines, "Reintentar" and the logs folder
// el(), icon() and btn() come from Translay's web/js/ui.js (shared/).

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const win = window.__TAURI__.window.getCurrentWindow();
const $ = (s) => document.querySelector(s);

const STEP_TEXT = { server: "Instalando el servidor", voice: "Instalando el motor de voz" };
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
  $("#size").textContent = status.voice
    ? "El servidor y el motor de voz: unos 7,5 GB en disco. Los modelos (unos 6 GB) se bajan al abrir Translay."
    : "El servidor: unos 2 GB en disco. Los modelos (unos 2 GB) se bajan al abrir Translay.";
  setBtn($("#install"), status.server_ok ? "Actualizar e instalar" : "Instalar", "download");
  show("setup");
}

$("#pick").addEventListener("click", async () => {
  const dir = await invoke("pick_folder");
  if (dir) { dataDir = dir; $("#data-dir").textContent = dir; }
});

let installing = false;

async function install() {
  if (installing) return;
  installing = true;
  const b = $("#install");
  b.classList.add("dl", "busy");
  b.style.setProperty("--p", "0%");
  setBtn(b, "Instalando 0 %", "download");
  $("#pick").disabled = true;
  $("#install-note").textContent = "";
  try {
    await invoke("install");
    await start();
  } catch (e) {
    installing = false;
    b.classList.remove("dl", "busy");
    $("#pick").disabled = false;
    setBtn(b, "Reintentar", "reload");
    $("#install-note").textContent = String(e);
  }
}
$("#install").addEventListener("click", install);

listen("setup", ({ payload: p }) => {
  if (p.percent == null || p.state === "error") return;
  const b = $("#install");
  b.style.setProperty("--p", `${p.percent}%`);
  setBtn(b, `Instalando ${p.percent} %`, "download");
  if (p.step && p.total_bytes) {
    $("#install-note").textContent = `${STEP_TEXT[p.step]} · ${gb(p.done_bytes)} de ${gb(p.total_bytes)} GB`;
  }
});

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
