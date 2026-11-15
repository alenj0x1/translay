"use strict";
// Bienvenida de primer uso: un diálogo por pasos que aparece la primera vez que se abre Translay (sin videos y sin
// haberla visto, preferencia «welcomed»), con «Omitir» siempre a mano. Solo en el navegador (Docker, run.py): la app
// de escritorio pregunta lo mismo y más en su propio asistente mientras se instala (desktop/ui/wizard.js).
//   1 Idioma       el de la interfaz, el agente y los resúmenes (Ajustes › Uso › Idioma); arranca en el del sistema
//   2 Biblioteca   nombre, color y avatar de la biblioteca principal, con su banner de vista previa
//   3 Apariencia   modo, fondo y color de énfasis; el fondo real de la app cambia detrás del diálogo
//   4 Agente       nombre, forma y color de la estrella (el mismo creador de Ajustes › Agente)
// Cada opción se guarda al elegirla, como en Ajustes: cerrar a mitad de camino no pierde lo elegido.

const WELCOME_STEPS = [
  ["idioma", "Idioma", "globe"],
  ["biblioteca", "Biblioteca", "library"],
  ["apariencia", "Apariencia", "sun"],
  ["agente", "Agente", "agent"],
];
const welcome = { step: 0, shown: false, lib: null, scene: "" };

// se abre sola una vez: con los ajustes y la biblioteca cargados, en el equipo de quien instaló Translay
function maybeWelcome() {
  if (welcome.shown || !prefsSchema.length || !lib.loaded) return;
  if (!(state.access?.local && state.access?.owner)) return;
  // en la app de escritorio, su asistente de primer uso ya lo preguntó: se aplica lo elegido (web/js/desktop.js)
  if (DESKTOP) { if (vaults.list.length) desktopWelcome(); return; }
  if (prefs.welcomed || Object.keys(lib.videos || {}).length) return;
  if (document.querySelector("dialog[open]")) return;  // otro diálogo abierto: a la próxima
  openWelcome();
}

function openWelcome() {
  welcome.shown = true;
  welcome.step = 0;
  const main = vaults.list.find((v) => v.main) || vaults.list[0] || {};
  welcome.lib = { id: main.id, name: main.name || "", color: main.color || VAULT_COLORS[0], icon: main.icon || "library",
    pattern: main.pattern || "" };
  // el idioma del sistema la primera vez: Ajustes lo guarda vacío («Del sistema») y el servidor ya lo usa
  renderWelcome();
  const dlg = $("#welcome-dlg");
  dlg.showModal();
  dlg.addEventListener("close", finishWelcome, { once: true });
}

function finishWelcome() {
  document.activeElement?.blur?.();  // guarda el texto que se estaba escribiendo
  saveWelcomeLib();
  setPref("welcomed", true);
}

function welcomeGo(step) {
  if (welcome.step === 1) saveWelcomeLib();
  welcome.step = Math.max(0, Math.min(WELCOME_STEPS.length - 1, step));
  renderWelcome();
}

function saveWelcomeLib() {
  const d = welcome.lib;
  if (!d?.id) return;
  const name = d.name.trim();
  const v = vaultById(d.id);
  if (v && (v.name !== name || v.color !== d.color || v.icon !== d.icon || (v.pattern || "") !== d.pattern) && name) {
    send({ type: "vault_update", id: d.id, name, color: d.color, icon: d.icon, pattern: d.pattern });
  }
}

const prefSpec = (key) => prefsSchema.find((p) => p.key === key);
function welcomeRow(key, label) {
  const p = prefSpec(key);
  if (!p) return null;
  return el("div", { class: "wl-row" }, el("span", { class: "label", text: label || p.label }), prefControl(p));
}

// ------------------------------------------------------------ pasos
function welcomeLang() {
  const p = prefSpec("language");
  const cur = I18N.lang;
  const list = el("div", { class: "opt-list wl-langs" }, ...p.options.filter(([v]) => v).map(([value, name]) =>
    el("button", { type: "button", class: "code-theme" + (cur === value ? " on" : ""), "aria-pressed": String(cur === value),
      on: { click: () => { if (value !== cur) setPref("language", value); } } }, icon("globe"), name)));
  const stage = el("div", { class: "wl-stage wl-hello" }, el("span", { class: "wordmark", "data-size": "44" }));
  wordmark(stage.firstChild, 44);
  return [el("div", { class: "wl-opts" }, list), stage];
}

function welcomeLibrary() {
  const d = welcome.lib;
  const banner = el("div", { class: "vpreview wl-banner" });
  const paint = () => {
    const pv = { id: d.id || "new", color: d.color, icon: d.icon, pattern: d.pattern };
    banner.replaceChildren(vaultAscii(pv, 90, 14, "fill"), vaultBadge(pv, "xl"), el("strong", { text: d.name.trim() || t("Biblioteca") }));
  };
  const name = el("input", { class: "input", type: "text", maxlength: 60, autocomplete: "off", placeholder: t("Ciencia, Comedia…"),
    "aria-label": t("Nombre") });
  name.value = d.name;
  name.addEventListener("input", () => { d.name = name.value; paint(); });
  const colors = el("div", { class: "vcolors wl-colors" }, ...VAULT_COLORS.map((c) => {
    const b = el("button", { type: "button", class: "vcolor" + (d.color === c ? " on" : ""), "aria-label": t("Color {color}", { color: c }),
      on: { click: () => { d.color = c; renderWelcome(); } } });
    b.style.setProperty("--vc", c);
    return b;
  }));
  const icons = el("div", { class: "vicons wl-icons" }, ...VAULT_ICONS.map(([ic, lbl]) =>
    el("button", { type: "button", class: "btn vicon" + (d.icon === ic ? " on" : ""), title: lbl, "aria-label": lbl,
      on: { click: () => { d.icon = ic; renderWelcome(); } } }, icon(ic))));
  const reshuffle = btn(t("Otro patrón"), { icon: "shuffle", size: "sm", variant: "ghost",
    onClick: () => { d.pattern = newPattern(); renderWelcome(); } });
  paint();
  return [el("div", { class: "wl-opts" },
    el("label", { class: "wl-row" }, el("span", { class: "label", text: t("Nombre") }), name),
    el("div", { class: "wl-row" }, el("span", { class: "label", text: t("Color") }), colors),
    el("div", { class: "wl-row" }, el("span", { class: "label", text: t("Avatar") }), icons)),
  el("div", { class: "wl-stage" }, banner, el("div", { class: "vpreview-acts" }, reshuffle))];
}

function welcomeLook() {
  const p = prefSpec("home_bg");
  const cur = homeBgMode();
  const ICON = { translay: "mic", recorrido: "arrow", luna: "moon", tierra: "globe", nubes: "sun", mar: "globe", arrecife: "flask", ballena: "music", atardecer: "theme", medusas: "spark", abismo: "eye", naufragio: "drive", "arañas": "atom", "arañas y perro": "paw" };
  // la imagen propia se elige en Ajustes: aquí, solo las escenas
  const scenes = el("div", { class: "opt-list wl-scenes" }, ...p.options.filter(([v]) => SCENES[v]).map(([value, text]) =>
    el("button", { type: "button", class: "code-theme" + (cur === value ? " on" : ""), "aria-pressed": String(cur === value),
      on: { click: () => { setPref("home_bg", value); renderWelcome(); } } }, icon(ICON[value] || "film"), text)));
  // la vista previa es la escena de verdad, con el color de énfasis y el modo elegidos
  let stage = $("#welcome-dlg .wl-scene");
  if (!stage || welcome.scene !== cur) {
    stage = el("div", { class: "wl-stage wl-scene", "aria-hidden": "true" });
    welcome.scene = cur;
    requestAnimationFrame(() => mountScene(stage, cur));
  }
  return [el("div", { class: "wl-opts" },
    welcomeRow("theme_mode", t("Modo")),
    el("div", { class: "wl-row" }, el("span", { class: "label", text: t("Fondo") }), scenes),
    welcomeRow("accent_color")), stage];
}

// el creador ya trae su estrella grande pasando por sus gestos: ocupa todo el ancho, sin otra vista previa al lado
function welcomeAgent() {
  return [el("div", { class: "wl-opts" }, welcomeRow("agent_name"), welcomeRow("agent_color"), welcomeRow("agent_avatar"))];
}

const WELCOME_BODY = [welcomeLang, welcomeLibrary, welcomeLook, welcomeAgent];

function renderWelcome() {
  const dlg = $("#welcome-dlg");
  const last = welcome.step === WELCOME_STEPS.length - 1;
  $("#wl-tabs").replaceChildren(...WELCOME_STEPS.map(([, label, ic], i) =>
    el("button", { type: "button", class: "seg" + (i === welcome.step ? " on" : ""), "aria-current": i === welcome.step ? "step" : null,
      on: { click: () => welcomeGo(i) } }, icon(ic), t(label))));
  const [opts, stage = null] = WELCOME_BODY[welcome.step]();
  const body = $("#wl-body");
  const focused = document.activeElement;
  // el panel del agente y la escena se mueven, no se rearman: así no parpadean al elegir algo
  body.dataset.step = WELCOME_STEPS[welcome.step][0];
  body.replaceChildren(...[opts, stage].filter(Boolean));
  if (focused?.isConnected) focused.focus();
  $("#wl-back").hidden = welcome.step === 0;
  $("#wl-back").textContent = t("Atrás");  // al cambiar de idioma, el suyo (no el de otro texto con la misma traducción)
  $("#wl-skip").textContent = t("Omitir");
  setBtn($("#wl-next"), last ? t("Empezar") : t("Siguiente"), last ? "check" : "arrow");
  dlg.querySelector(".dlg-actions").classList.toggle("first", welcome.step === 0);
}

$("#wl-back").addEventListener("click", () => welcomeGo(welcome.step - 1));
$("#wl-next").addEventListener("click", () => {
  if (welcome.step < WELCOME_STEPS.length - 1) welcomeGo(welcome.step + 1);
  else $("#welcome-dlg").close();
});
$("#wl-skip").addEventListener("click", () => $("#welcome-dlg").close());
// lo que se elige con los controles de Ajustes (modo, color, avatar, nombre) redibuja el paso
$("#wl-body").addEventListener("click", (e) => {
  if (e.target.closest(".wl-row button")) setTimeout(renderWelcome);
});
