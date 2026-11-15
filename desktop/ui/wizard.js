"use strict";
// First-run wizard of the desktop app (index.html › #wizard). It opens on the first launch right after the profile is
// chosen, while the voice engine installs and the models download (their progress stays in the bottom strip), so
// Translay opens already set up:
//   1 Idioma           the app's language (Windows' preselected; the wizard itself switches at once), «Traducir a» and
//                      which other language is only transcribed; preview: videos in each language and what happens
//   2 Cómo lo usarás   Traducir y doblar or Transcribir y resumir (app_mode); preview: the player of each one
//   3 Tu biblioteca    name, color, avatar and pattern of the main library; preview: its banner
//   4 Apariencia       mode, background scene and accent color; the window itself changes, the real scene is the preview
//   5 Lumi             the agent's name, color and star (the same creator as Ajustes › Agente, web/js/star.js)
//   6 YouTube          connect the account when Translay opens (needs the server), or not now; optional
//   7 Desde el celular access from other devices on the network (Ajustes › Acceso y API); optional
//   8 Conoce Translay  short animated demos made of pieces that look like the app, with a cursor that clicks
// Everything chosen is saved as it changes (set_welcome, in the app's settings); Translay's page applies it on its
// first load with its own preferences (web/js/desktop.js › desktopWelcome). When the wizard ends and the server is
// ready, the window opens Translay (open_app); if the server is still loading, the startup strip shows meanwhile.
// el(), icon(), btn(), setBtn(), carousel() and splitSwatch() come from web/js/ui.js; wordmark() from brand.js,
// mountScene() from scenes.js, the library's look from vaultlook.js and the star from star.js (all in shared/).
// invoke() and $ come from setup.js, which calls openWizard().

// what is chosen, with the keys of Translay's preferences (vt/prefs.py); star.js and scenes.js read it as `prefs`
const prefs = {
  language: "", target_lang: "", transcribe_lang: "", app_mode: "traducir",
  theme_mode: "sistema", accent_color: "#7d5ba6", home_bg: "translay",
  agent_name: "Lumi", agent_color: "", agent_avatar: "",
  // the scenes keep moving while the wizard waits in the background (scenes.js › sceneShouldPause); not applied
  get bg_pause_blur() { return !wz.open; },
};
const wz = {
  open: false, step: 0, seen: 0, lang: "es", sys: "es", voice: true, dataDir: "", onDone: null,
  lib: { name: "", color: VAULT_COLORS[4], icon: "library", pattern: newPattern() },
  youtube: "", network: "", ip: null, ready: false, scene: "", built: {}, saveTimer: 0, starTimer: 0, starState: "",
};

// the background scenes that can be chosen here (the private one and a photo are only in Ajustes)
// (tables written with t() follow the language through i18nTrack, i18n.js)
const WZ_SCENES = [["translay", "Translay", "mic"], ["recorrido", t("Recorrido"), "arrow"], ["luna", t("Luna"), "moon"],
  ["tierra", t("Tierra"), "globe"], ["nubes", t("Nubes"), "theme"], ["atardecer", t("Atardecer"), "sun"], ["mar", t("Fondo marino"), "globe"],
  ["arrecife", t("Arrecife"), "flask"], ["ballena", t("Ballena"), "music"], ["medusas", t("Medusas"), "spark"], ["abismo", t("Abismo"), "eye"],
  ["naufragio", t("Naufragio"), "drive"], ["arañas", t("Arañas"), "atom"]];
const WZ_ACCENTS = [["", t("Del tema")], ["#e4572e", t("Coral")], ["#f3a712", t("Ámbar")], ["#29bf12", t("Verde")], ["#00a5cf", t("Celeste")],
  ["#7d5ba6", t("Violeta")], ["#e84f9b", t("Rosa")], ["#8d6e63", t("Café")]];
i18nTrack(WZ_SCENES);
i18nTrack(WZ_ACCENTS);
// each language's name in each interface language (web/js/i18n.js › LANG_NAMES)
const WZ_LANG_NAMES = {
  es: { en: "inglés", es: "español", pt: "portugués" },
  en: { en: "English", es: "Spanish", pt: "Portuguese" },
  pt: { en: "inglês", es: "espanhol", pt: "português" },
};
const langName = (code) => (WZ_LANG_NAMES[I18N.lang] || WZ_LANG_NAMES.es)[code] || code;
const targetLang = () => prefs.target_lang || wz.lang;

const WZ_STEPS = [
  { id: "idioma", icon: "globe", label: () => t("Idioma"), title: () => t("Idioma de Translay y de tus videos"),
    lead: () => t("La interfaz, el agente y los resúmenes usan el idioma de Translay. Los videos se doblan al idioma que elijas."), build: stepLang },
  { id: "uso", icon: "sliders", label: () => t("Cómo lo usarás"), title: () => t("Qué harás con tus videos"),
    lead: () => t("Translay muestra lo que necesitas según lo que hagas más. Se cambia en Ajustes › Uso."), build: stepUse },
  { id: "biblioteca", icon: "library", label: () => t("Tu biblioteca"), title: () => t("Tu biblioteca principal"),
    lead: () => t("Aquí se guardan tus videos, colecciones y transcripciones."), build: stepLibrary },
  { id: "apariencia", icon: "theme", label: () => t("Apariencia"), title: () => t("Cómo se ve Translay"),
    lead: () => t("El modo, el fondo y el color de énfasis. La ventana cambia mientras eliges."), build: stepLook },
  { id: "agente", icon: "star", label: () => prefs.agent_name.trim() || "Lumi", title: () => t("Tu agente"),
    lead: () => t("Responde lo que preguntes sobre cada video. Arma su estrella a tu gusto."), build: stepAgent },
  { id: "youtube", icon: "video", optional: true, label: () => "YouTube", title: () => t("Cuenta de YouTube"),
    lead: () => t("Algunos videos piden iniciar sesión. Translay usa tu cuenta solo para descargarlos."), build: stepYouTube },
  { id: "celular", icon: "phone", optional: true, label: () => t("Desde el celular"), title: () => t("Acceso desde otros equipos"),
    lead: () => t("Mira y agrega videos desde el celular o la tablet, en tu misma red."), build: stepPhone },
  { id: "conoce", icon: "spark", label: () => t("Conoce Translay"), title: () => t("Lo que harás todos los días"),
    lead: () => t("Cada demostración se repite sola. Elige una para verla de nuevo."), build: stepTour },
];

// ------------------------------------------------------------ open, steps and the strip
function wizardOpen() { return wz.open; }

// opts: { dataDir, voice (the chosen profile has voice), onDone }
function openWizard(opts) {
  wz.open = true;
  wz.dataDir = opts.dataDir || "";
  wz.voice = opts.voice !== false;
  wz.onDone = opts.onDone;
  wz.sys = systemLang();
  wz.lang = I18N.lang;
  wz.lib.name = t("Principal");
  const look = window.__TRANSLAY_LOOK__ || {};
  if (/^#[0-9a-f]{6}$/i.test(look.accent || "")) prefs.accent_color = look.accent.toLowerCase();
  else if (look.accent === "none") prefs.accent_color = "";
  if (WZ_SCENES.some(([k]) => k === look.scene)) prefs.home_bg = look.scene;
  wz.scene = SCENES[look.scene] ? look.scene : "translay";
  invoke("lan_ip").then((ip) => { wz.ip = ip || null; if (wz.built.celular) wz.built.celular.sync(); }).catch(() => {});
  // seen again from Ajustes: only what is changed here is applied (the rest of the settings and the library stay)
  wz.replay = !!opts.replay;
  wz.start = { prefs: { ...prefs }, lib: JSON.stringify(wz.lib), lang: wz.lang };
  document.body.classList.add("wizard-on");
  show("wizard");
  renderWizard(true);
  save();
}

function renderWizard(rebuild = false) {
  if (rebuild) {
    for (const b of Object.values(wz.built)) b.stop?.();
    wz.built = {};
  }
  const step = WZ_STEPS[wz.step];
  $("#wz-rail").replaceChildren(...WZ_STEPS.map((s, i) => {
    const done = i < wz.step || (i <= wz.seen && i !== wz.step);
    return el("button", { type: "button", class: "wz-step" + (i === wz.step ? " on" : "") + (done ? " done" : ""),
      "aria-current": i === wz.step ? "step" : null, on: { click: () => go(i) } },
      el("span", { class: "wz-dot" }, icon(done ? "check" : s.icon)), el("span", { class: "wz-step-text", text: s.label() }));
  }));
  $("#wz-title").textContent = step.title();
  $("#wz-lead").textContent = step.lead();
  if (!wz.built[step.id]) wz.built[step.id] = step.build();
  const b = wz.built[step.id];
  const body = $("#wz-body");
  body.dataset.step = step.id;
  if (body.firstChild !== b.opts) {
    for (const [id, other] of Object.entries(wz.built)) if (id !== step.id) other.pause?.();
    body.replaceChildren(b.opts, b.preview);
    b.opts.scrollTop = 0;
  }
  b.sync?.();
  b.resume?.();
  markOn(body);
  fadeEdges(b.opts);
  const last = wz.step === WZ_STEPS.length - 1;
  setBtn($("#wz-back"), t("Atrás"), null);
  $("#wz-back").hidden = wz.step === 0;
  setBtn($("#wz-skip"), t("Omitir"), null);
  $("#wz-skip").hidden = !step.optional;
  setBtn($("#wz-next"), last ? t("Empezar") : t("Siguiente"), last ? "check" : "arrow");
}

function go(i) {
  document.activeElement?.blur?.();
  wz.step = Math.max(0, Math.min(WZ_STEPS.length - 1, i));
  wz.seen = Math.max(wz.seen, wz.step);
  renderWizard();
  save();
}

function initWizardButtons() {
  $("#wz-back").addEventListener("click", () => go(wz.step - 1));
  $("#wz-skip").addEventListener("click", () => {
    const id = WZ_STEPS[wz.step].id;
    if (id === "youtube") wz.youtube = "no";
    if (id === "celular") wz.network = "no";
    go(wz.step + 1);
  });
  $("#wz-next").addEventListener("click", () => {
    if (wz.step < WZ_STEPS.length - 1) go(wz.step + 1);
    else finishWizard();
  });
}

// «Empezar» (or the server stopped: then without onDone, setup.js shows the error)
function finishWizard(done = true) {
  if (!wz.open) return;
  wz.open = false;
  for (const b of Object.values(wz.built)) b.stop?.();
  clearInterval(wz.starTimer);
  document.body.classList.remove("wizard-on");
  clearTimeout(wz.saveTimer);
  invoke("set_welcome", { choices: { ...choices(), done: true } }).catch(() => {}).finally(() => { if (done) wz.onDone?.(wz.ready); });
}

// what Translay's page applies (web/js/desktop.js › applyDesktopWelcome)
function choices() {
  const changed = (k) => !wz.replay || prefs[k] !== wz.start.prefs[k];
  const out = {
    prefs: Object.fromEntries(Object.entries(prefs).filter(([k]) => k !== "bg_pause_blur" && changed(k))),
    library: { ...wz.lib, name: wz.lib.name.trim() || t("Principal") },
    youtube: wz.youtube === "yes", network: wz.network === "yes",
  };
  if (!wz.replay || wz.lang !== wz.start.lang) out.prefs.language = wz.lang === wz.sys ? "" : wz.lang;
  if (wz.replay && JSON.stringify(wz.lib) === wz.start.lib) delete out.library;
  return out;
}
function save() {
  clearTimeout(wz.saveTimer);
  wz.saveTimer = setTimeout(() => invoke("set_welcome", { choices: choices() }).catch(() => {}), 400);
}

// the bottom strip: what is installing or loading, in words, with its percent (setup.js feeds it)
//   kind: "work" (pct null = no percent yet) · "ready" · "error" (retry: what «Reintentar» runs)
function wzProgress(text, pct, kind = "work", retry = null) {
  wz.ready = kind === "ready";
  const box = $("#wz-progress");
  box.dataset.kind = kind;
  const line = $("#wz-load");
  line.replaceChildren(...(kind === "ready" ? [icon("check")] : []), text);
  $("#wz-pct").replaceChildren();
  if (kind === "error" && retry) {
    $("#wz-pct").append(btn(t("Reintentar"), { icon: "reload", size: "xs", variant: "ghost", onClick: retry }));
  } else if (pct != null && kind === "work") $("#wz-pct").textContent = `${pct} %`;
  const track = $("#wz-bar").parentElement;
  track.classList.toggle("wait", kind === "work" && pct == null);
  $("#wz-bar").style.setProperty("--p", `${kind === "ready" ? 100 : pct ?? 0}%`);
}

// marks the chosen option of every group in the step: [data-k] with the value it stands for in data-v
function wzValue(k) {
  if (k === "lang") return wz.lang;
  if (k === "lib.color") return wz.lib.color;
  if (k === "lib.icon") return wz.lib.icon;
  if (k === "youtube") return wz.youtube;
  if (k === "network") return wz.network;
  if (k === "tour") return String(wz.tour ?? 0);
  if (k.startsWith("star.")) return agentLook()[k.slice(5)];
  return prefs[k];
}
function markOn(root) {
  for (const n of root.querySelectorAll("[data-k]")) {
    const on = String(wzValue(n.dataset.k) ?? "") === n.dataset.v;
    n.classList.toggle("on", on);
    n.setAttribute("aria-pressed", String(on));
    // a color swatch: the chosen one carries a check (no ring)
    if (n.classList.contains("vcolor")) {
      const mark = n.querySelector(":scope > .wz-check");
      if (on && !mark) n.append(el("span", { class: "wz-check" }, icon("check")));
      else if (!on && mark) mark.remove();
    }
  }
}

// a scrolling options column has no visible bar: the edge where more continues fades out
function fadeEdges(box) {
  const sync = () => {
    box.classList.toggle("more-up", box.scrollTop > 2);
    box.classList.toggle("more-down", box.scrollTop + box.clientHeight < box.scrollHeight - 2);
  };
  if (!box.dataset.fade) {
    box.dataset.fade = "1";
    box.addEventListener("scroll", sync, { passive: true });
    new ResizeObserver(sync).observe(box);
  }
  sync();
}
// a choice: saved, the groups marked and the step's preview updated
function pick(k, v) {
  if (k === "lang") return pickLang(v);
  if (k === "lib.color") wz.lib.color = v;
  else if (k === "lib.icon") wz.lib.icon = v;
  else if (k === "youtube") wz.youtube = v;
  else if (k === "network") wz.network = v;
  else if (k !== "_star") prefs[k] = v;  // («_star»: the agent's look, already saved in agent_avatar)
  if (["theme_mode", "accent_color", "home_bg"].includes(k)) applyLook();
  const b = wz.built[WZ_STEPS[wz.step].id];
  markOn($("#wz-body"));
  b?.sync?.();
  if (b) fadeEdges(b.opts);
  save();
}

// another language: the catalogue, then the whole wizard again in it (and the title bar)
async function pickLang(lang) {
  if (lang === wz.lang) return;
  wz.lang = lang;
  if (prefs.target_lang === lang) prefs.target_lang = "";
  const untouched = wz.lib.name === t("Principal");  // the library's name, if it is still the default, in the new language
  await setLang(lang);
  if (untouched) wz.lib.name = t("Principal");
  if (typeof syncTitleBar === "function") syncTitleBar();
  renderWizard(true);
  save();
}

// ------------------------------------------------------------ pieces
const wzField = (label, ...kids) => el("div", { class: "wz-field" }, el("span", { class: "wz-label", text: label }), ...kids);
// a list of options, one per row (icon, name, a line and an optional tag)
function wzList(k, items, cls = "") {
  return el("div", { class: ("wz-list " + cls).trim() }, ...items.map((it) =>
    el("button", { type: "button", class: "wz-opt", "data-k": k, "data-v": it.value, on: { click: () => pick(k, it.value) } },
      it.icon ? el("span", { class: "wz-ic" }, icon(it.icon)) : null,
      el("span", { class: "wz-opt-text" },
        el("strong", {}, el("span", { text: it.title }), it.tag ? el("span", { class: "wz-tag", text: it.tag }) : null),
        it.desc ? el("small", { text: it.desc }) : null))));
}
// short options side by side (the chosen one slides as a pill: web/js/ui.js)
function wzSegs(k, items) {
  return el("div", { class: "segs" }, ...items.map(([value, label]) =>
    el("button", { type: "button", class: "seg", "data-k": k, "data-v": value, on: { click: () => pick(k, value) } }, label)));
}
function wzSwatches(k, items, theme = false) {
  return el("div", { class: "vcolors wz-swatches" }, ...items.map(([value, name]) =>
    el("button", { type: "button", class: "vcolor" + (value ? " split" : " theme"), title: name, "aria-label": name, "data-k": k, "data-v": value,
      style: value ? `--vc: ${value}` : null, on: { click: () => pick(k, value) } }, value ? splitSwatch() : theme ? icon("theme") : null)));
}
function wzInput(value, placeholder, onInput, max = 60) {
  const f = el("input", { class: "wz-input", type: "text", maxlength: max, autocomplete: "off", spellcheck: "false", placeholder });
  f.value = value;
  f.addEventListener("input", () => onInput(f.value));
  return f;
}
const wzPreview = (cls, ...kids) => el("div", { class: ("wz-preview " + cls).trim() }, ...kids);

// ------------------------------------------------------------ 1 · Idioma
const SAMPLE_VIDEOS = [["en", t("Cómo funciona la memoria"), "12:40"], ["pt", t("Receta de pan casero"), "8:05"],
  ["es", t("Entrevista sobre música"), "21:16"]];
i18nTrack(SAMPLE_VIDEOS);
function stepLang() {
  const opts = el("div", { class: "wz-opts" },
    wzField(t("Idioma"), wzList("lang", LANGS.map((c) => ({ value: c, icon: "globe", title: LANG_NATIVE[c],
      tag: c === wz.sys ? t("El de Windows") : "" })), "compact")),
    wzField(t("Traducir a"), wzSegs("target_lang", [["", t("El idioma de la app")], ...LANGS.map((c) => [c, LANG_NATIVE[c]])])),
    el("div", { class: "wz-field", id: "wz-only" }));
  // the interface in its language, and what happens to a video in each language
  const side = el("div", { class: "mini-side" }, ...[["home", t("Inicio")], ["grid", t("Colecciones")], ["queue", t("Cola")], ["gear", t("Ajustes")]]
    .map(([ic, label], i) => el("span", { class: "mini-nav" + (i ? "" : " on") }, icon(ic), label)));
  const list = el("div", { class: "mini-videos" });
  const main = el("div", { class: "mini-main" }, el("div", { class: "mini-search" }, icon("search"), t("Busca en tu biblioteca")), list);
  const preview = wzPreview("wz-app", el("div", { class: "mini-app" }, side, main));
  const sync = () => {
    const target = targetLang();
    const others = ["en", "es", "pt"].filter((c) => c !== target);
    $("#wz-only")?.replaceChildren(el("span", { class: "wz-label", text: t("Solo transcribir videos en") }),
      wzSegs("transcribe_lang", [["", t("Ningún otro")], ...others.map((c) => [c, LANG_NATIVE[c]])]));
    if (prefs.transcribe_lang === target) prefs.transcribe_lang = "";
    markOn(opts);
    list.replaceChildren(...SAMPLE_VIDEOS.map(([lang, title, dur]) => {
      const only = lang === target || lang === prefs.transcribe_lang || prefs.app_mode === "transcribir";
      const result = prefs.app_mode === "transcribir" ? t("Se transcribe y resume")
        : lang === target ? t("Ya está en {lang}, se transcribe", { lang: langName(lang) })
        : only ? t("Solo se transcribe") : t("Se dobla al {lang}", { lang: langName(target) });
      return el("div", { class: "mini-video" },
        el("span", { class: "mini-thumb" }, el("span", { class: "mini-dur", text: dur })),
        el("span", { class: "mini-vtext" }, el("strong", { text: title }),
          el("span", { class: "mini-chips" }, el("span", { class: "mini-chip", text: lang.toUpperCase() }),
            el("span", { class: "mini-result" + (only ? "" : " dub") }, icon(only ? "lines" : "speaker"), result))));
    }));
  };
  // (the second group depends on the target: rebuilt by sync once the step is on screen)
  return { opts, preview, sync };
}

// ------------------------------------------------------------ 2 · Cómo lo usarás
function stepUse() {
  const facts = (...list) => el("ul", { class: "wz-facts" }, ...list.map((s) => el("li", {}, icon("check"), s)));
  const opts = el("div", { class: "wz-opts" }, wzList("app_mode", [
    { value: "traducir", icon: "speaker", title: t("Traducir y doblar"),
      desc: wz.voice ? t("Los videos en otro idioma, con una voz en el tuyo y el original de fondo.")
        : t("Los videos en otro idioma, con subtítulos traducidos junto al original.") },
    { value: "transcribir", icon: "lines", title: t("Transcribir y resumir"),
      desc: t("Para estudiar o repasar videos en tu idioma, sin traducción ni voz.") },
  ], "big"));
  // what each one brings, under its option
  const [dubOpt, textOpt] = opts.querySelectorAll(".wz-opt-text");
  dubOpt.append(facts(...[wz.voice ? t("Voz en tu idioma que sigue al original") : null, t("Subtítulos traducidos y del original"),
    t("El texto escrito en el video, traducido en su lugar"), t("Transcripción, resumen y agente")].filter(Boolean)));
  textOpt.append(facts(t("Transcripción con el minuto de cada frase"), t("Resumen con las ideas principales"), t("El agente responde sobre el video")));
  const preview = wzPreview("wz-player");
  const sync = () => {
    const dub = prefs.app_mode !== "transcribir";
    const target = targetLang();
    const source = target === "en" ? "pt" : "en";
    const frame = el("div", { class: "mini-frame" },
      el("span", { class: "mini-sub orig", text: SAY[source] }),
      el("span", { class: "mini-sub", text: SAY[target] }),
      el("div", { class: "mini-seek" }, icon("pause"), el("i", { style: "--p: 38%" }), el("span", { text: "04:51" })));
    const side = dub
      ? el("div", { class: "mini-panel" },
        el("div", { class: "segs mini-segs" }, el("span", { class: "seg on", text: t("Doblado") }), el("span", { class: "seg", text: t("Original") })),
        el("p", { class: "mini-note" }, icon("speaker"), t("Voz en {lang}", { lang: langName(target) })),
        el("p", { class: "mini-note" }, icon("captions"), t("Subtítulos en {lang} y en el original", { lang: langName(target) })))
      : el("div", { class: "mini-panel" },
        el("strong", { class: "mini-h", text: t("Resumen") }),
        ...[t("Dormir ayuda a fijar lo aprendido"), t("Repasar antes de dormir rinde más"), t("Dos técnicas para estudiar")]
          .map((s) => el("p", { class: "mini-point" }, el("i"), s)));
    const lines = el("div", { class: "mini-lines" }, ...TRANSCRIPT.map(([tm, text], i) =>
      el("p", { class: i === 1 ? "on" : "" }, el("b", { text: tm }), text)));
    preview.replaceChildren(el("div", { class: "mini-player" + (dub ? "" : " text") }, dub ? frame : lines, side));
  };
  return { opts, preview, sync };
}
// what the voice says in the dubbed preview (in the language it dubs to)
const SAY = { es: "El cerebro guarda los recuerdos mientras dormimos.", en: "The brain stores memories while we sleep.",
  pt: "O cérebro guarda as memórias enquanto dormimos." };
const TRANSCRIPT = [["04:12", t("Hoy vamos a ver cómo se forma un recuerdo.")], ["04:51", t("El cerebro guarda los recuerdos mientras dormimos.")],
  ["05:30", t("Por eso repasar antes de dormir funciona tan bien.")], ["06:08", t("Veamos dos técnicas que lo aprovechan.")]];
i18nTrack(TRANSCRIPT);

// ------------------------------------------------------------ 3 · Tu biblioteca
function stepLibrary() {
  const d = wz.lib;
  const name = wzInput(d.name, t("Principal"), (v) => { d.name = v; sync(); save(); });
  const icons = el("div", { class: "vicons wz-icons" }, ...VAULT_ICONS.map(([ic, label]) =>
    el("button", { type: "button", class: "btn vicon", title: label, "aria-label": label, "data-k": "lib.icon", "data-v": ic,
      on: { click: () => pick("lib.icon", ic) } }, icon(ic))));
  const opts = el("div", { class: "wz-opts" },
    wzField(t("Nombre"), name),
    wzField(t("Color"), wzSwatches("lib.color", VAULT_COLORS.map((c) => [c, t("Color {color}", { color: c })]))),
    wzField(t("Avatar"), icons),
    wzField(t("Carpeta"), el("p", { class: "wz-path" }, icon("folder"), el("span", { text: wz.dataDir }))));
  const banner = el("div", { class: "wz-banner" });
  const again = btn(t("Otro patrón"), { icon: "shuffle", size: "sm", variant: "ghost", onClick: () => { d.pattern = newPattern(); sync(); save(); } });
  const preview = wzPreview("wz-lib", banner, el("div", { class: "vpreview-acts" }, again));
  const sync = () => {
    const pv = { id: "principal", color: d.color, icon: d.icon, pattern: d.pattern };
    banner.replaceChildren(vaultAscii(pv, 120, 40, "fill"),
      el("div", { class: "wz-banner-info" }, vaultBadge(pv, "xl"),
        el("div", { class: "wz-banner-text" }, el("strong", { text: d.name.trim() || t("Principal") }), el("small", { text: t("{n} videos", { n: 0 }) }))));
  };
  return { opts, preview, sync };
}

// ------------------------------------------------------------ 4 · Apariencia
// an option shown as a picture with its name below (the mode's little window, a scene's still frame)
const wzThumb = (k, v, name, pic) => el("button", { type: "button", class: "wz-thumb", "data-k": k, "data-v": v, on: { click: () => pick(k, v) } },
  pic, el("span", { class: "wz-thumb-name", text: name }));
// a still frame of each scene for its thumbnail: at this size characters can't be read, so each cell is a little
// square in its color and intensity (the same density function as the background); «recorrido» is caught while
// the Moon rises over the logo. Painted again when the mode or the accent changes
function paintThumbs(root) {
  const pal = scenePalette(), boost = document.documentElement.dataset.theme === "light" ? 1.6 : 1;  // en claro, la tinta es pálida
  const W = 120, H = 68, k = 2, cols = W / k, rows = H / k, A = W / H, u0 = (ASPECT - A) / 2;
  for (const c of root.querySelectorAll("canvas[data-scene]")) {
    const field = SCENES[c.dataset.scene];
    if (!field) continue;
    c.width = W * 2; c.height = H * 2;  // sharp on high-density screens
    const g = c.getContext("2d");
    g.setTransform(2, 0, 0, 2, 0, 0);
    g.clearRect(0, 0, W, H);
    const t = c.dataset.scene === "recorrido" ? 37.6 : 14;
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const r = field(u0 + ((i + 0.5) / cols) * A, (j + 0.5) / rows, t, 1 / rows, A);
        if (r[0] < 0.06) continue;
        g.globalAlpha = Math.min(1, (0.15 + r[0] * 0.95) * boost);
        g.fillStyle = pal.colors[r[1] || 0];
        g.fillRect(i * k, j * k, k, k);
      }
    }
    g.globalAlpha = 1;
  }
}
function stepLook() {
  const modes = [["sistema", t("Sistema")], ["claro", t("Claro")], ["oscuro", t("Oscuro")]];
  const opts = el("div", { class: "wz-opts wz-cols" },
    wzField(t("Modo"), el("div", { class: "wz-thumbs modes" }, ...modes.map(([v, name]) =>
      wzThumb("theme_mode", v, name, el("span", { class: "wz-mode", "data-mode": v }, el("i"), el("i")))))),
    wzField(t("Color de énfasis"), wzSwatches("accent_color", WZ_ACCENTS, true), el("p", { class: "wz-note", id: "wz-accent-name" })),
    // los fondos a todo el ancho: una miniatura de cada escena, todas a la vista sin desplazarse
    wzField(t("Fondo"), el("div", { class: "wz-thumbs" }, ...WZ_SCENES.map(([k, name]) =>
      wzThumb("home_bg", k, name, el("span", { class: "wz-thumb-img" }, el("canvas", { "data-scene": k })))))));
  opts.lastElementChild.classList.add("wz-span");
  let thumbsKey = "";
  const scene = el("div", { class: "wz-scene", "aria-hidden": "true" });
  const mark = el("span", { class: "wordmark", "data-size": "26" });
  const card = el("div", { class: "wz-scene-card" }, mark,
    el("div", { class: "wz-scene-row" }, el("span", { class: "mini-field" }, icon("link"), t("Pega un enlace de YouTube")),
      el("span", { class: "btn sm dark" }, icon("plus"), el("span", { class: "btn-text", text: t("Agregar") }))),
    el("div", { class: "bar-track" }, el("i", { style: "--p: 64%" })));
  const preview = wzPreview("wz-look", scene, card);
  let mounted = "";
  const sync = () => {
    if (scene.isConnected && (mounted !== prefs.home_bg || !scene.firstChild)) {
      mounted = prefs.home_bg;
      scene.replaceChildren();
      mountScene(scene, prefs.home_bg);
    }
    if (mark.isConnected && !mark.firstChild?.tagName) wordmark(mark, 26);
    const key = JSON.stringify(scenePalette());
    if (opts.isConnected && key !== thumbsKey) { thumbsKey = key; paintThumbs(opts); }
    const n = $("#wz-accent-name");
    if (n) n.textContent = (WZ_ACCENTS.find(([c]) => c === prefs.accent_color) || WZ_ACCENTS[0])[1];
  };
  // the scene's worker ends when its canvas leaves the page; it starts again when the step is back
  return { opts, preview, sync, resume: () => requestAnimationFrame(sync), pause: () => { scene.replaceChildren(); mounted = ""; } };
}

// the window takes the chosen mode, accent and scene at once (the startup strip and Translay keep them)
function applyLook() {
  const root = document.documentElement;
  const m = prefs.theme_mode;
  const theme = m === "claro" ? "light" : m === "oscuro" ? "dark" : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  if (root.dataset.theme !== theme) {
    root.classList.add("theme-switch");
    root.dataset.theme = theme;
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switch")));
    try { localStorage.setItem("vt-theme-block", theme); } catch (e) { /* no storage */ }
    invoke("set_theme", { theme }).catch(() => {});
    if (typeof syncTitleBar === "function") syncTitleBar();
  }
  const a = prefs.accent_color;
  if (/^#[0-9a-f]{6}$/i.test(a)) {
    const c = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16) / 255);
    root.dataset.libAccent = "";
    root.style.setProperty("--accent-base", a);
    root.style.setProperty("--on-accent-dark", 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.55 ? "#111111" : "#ffffff");
  } else {
    delete root.dataset.libAccent;
    root.style.removeProperty("--accent-base");
    root.style.removeProperty("--on-accent-dark");
  }
  if (wz.scene !== prefs.home_bg) {
    wz.scene = prefs.home_bg;
    $("#scene").replaceChildren();
    mountScene($("#scene"), prefs.home_bg);
  }
  // the agent's star in «Del tema» follows the accent
  if (wz.built.agente) wz.built.agente.sync();
}

// the title bar's light/dark button while the wizard is open: the mode chosen here follows it
function wizardTheme(theme) {
  prefs.theme_mode = theme === "dark" ? "oscuro" : "claro";
  if (wz.open) { markOn($("#wz-body")); save(); }
}

// ------------------------------------------------------------ 5 · Lumi
function stepAgent() {
  const saveLook = (patch) => { prefs.agent_avatar = JSON.stringify({ ...agentLook(), ...patch }); };
  const name = wzInput(prefs.agent_name, "Lumi", (v) => {
    prefs.agent_name = v;
    const rail = $("#wz-rail .wz-step.on .wz-step-text");
    if (rail) rail.textContent = v.trim() || "Lumi";
    sync();
    save();
  }, 32);
  const colors = wzSwatches("agent_color", WZ_ACCENTS, true);
  const parts = {};
  const part = (k, label) => {
    parts[k] = STAR_PARTS[k].map(([value, title]) => el("button", { type: "button", class: "star-opt", title, "aria-label": title,
      "data-k": "star." + k, "data-v": value, on: { click: () => { if (agentLook()[k] !== value) { saveLook({ [k]: value }); pick("_star", null); } } } }));
    return el("div", { class: "star-part" }, el("span", { text: label }),
      carousel(parts[k], { per: 4, start: STAR_PARTS[k].findIndex(([v]) => v === agentLook()[k]), label }));
  };
  const random = btn(t("Al azar"), { icon: "dice", size: "sm", variant: "ghost", onClick: () => {
    const choose = (a) => a[Math.floor(Math.random() * a.length)];
    const now = agentLook();
    saveLook(Object.fromEntries(Object.keys(STAR_PARTS).map((k) => [k, choose(STAR_PARTS[k].filter(([v]) => v !== now[k]))[0]])));
    prefs.agent_color = choose(WZ_ACCENTS.filter(([c]) => c && c !== prefs.agent_color))[0];
    pick("_star", null);
  } });
  const opts = el("div", { class: "wz-opts" },
    el("div", { class: "wz-row2" }, wzField(t("Nombre"), name), wzField(t("Color"), colors)),
    el("div", { class: "star-parts" }, part("shape", t("Forma")), part("eyes", t("Ojos")), part("mouth", t("Boca")),
      part("cheeks", t("Mejillas")), part("acc", t("Accesorio"))));
  // the big star goes through its gestures by itself; the empty chat as in Translay, with its name and what to ask
  const stage = el("div", { class: "star-big" });
  const hello = el("strong", { class: "wz-agent-name" });
  const chips = el("div", { class: "wz-agent-chips" });
  const preview = wzPreview("wz-agent", el("div", { class: "wz-agent-top" }, random), stage, hello, chips);
  let key = "";
  const sync = () => {
    const look = agentLook();
    for (const [k, buttons] of Object.entries(parts)) {
      for (const b of buttons) b.replaceChildren(starThumb({ ...look, [k]: b.dataset.v }, k));
    }
    const now = JSON.stringify(look) + (prefs.agent_color || themeStarColor());
    if (now !== key) { key = now; starSwap(stage, starSvg(look, null, wz.starState)); }
    hello.textContent = t("Hola, soy {name}", { name: prefs.agent_name.trim() || "Lumi" });
    chips.replaceChildren(...[t("Resume este video"), t("¿Qué dijo sobre el sueño?"), t("Explícalo con un ejemplo")]
      .map((s) => el("span", { class: "wz-chip", text: s })));
  };
  clearInterval(wz.starTimer);
  wz.starTimer = setInterval(() => {
    if (!stage.isConnected) return;
    wz.starState = STAR_STATES[(STAR_STATES.indexOf(wz.starState) + 1) % STAR_STATES.length];
    stage.querySelector(".agent-star:not(.leaving)")?.setAttribute("class", ("agent-star " + wz.starState).trim());
  }, 2600);
  return { opts, preview, sync, stop: () => clearInterval(wz.starTimer) };
}

// ------------------------------------------------------------ 6 · YouTube
function stepYouTube() {
  const opts = el("div", { class: "wz-opts" },
    wzList("youtube", [
      { value: "yes", icon: "user", title: t("Conectar al abrir Translay"),
        desc: t("Se abre una ventana de tu navegador para iniciar sesión una vez. Después la sesión se renueva sola.") },
      { value: "no", icon: "clock", title: t("Ahora no"), desc: t("Se conecta cuando quieras en Ajustes › Agregar y descargar.") },
    ], "big"),
    wzField(t("Para qué sirve"), el("ul", { class: "wz-facts" },
      ...[t("Videos con restricción de edad"), t("Cuando YouTube pide verificar que no eres un bot"), t("Tu sesión no sale de este equipo")]
        .map((s) => el("li", {}, icon("check"), s)))));
  const demo = demoStage();
  const preview = wzPreview("wz-demo", demo.box);
  const loop = demoLoop(demo, () => [demoYouTube], () => {});
  return { opts, preview, pause: loop.stop, resume: loop.start, stop: loop.stop };
}

// ------------------------------------------------------------ 7 · Desde el celular
function stepPhone() {
  const opts = el("div", { class: "wz-opts" },
    wzList("network", [
      { value: "yes", icon: "phone", title: t("Permitir acceso desde otros equipos"),
        desc: t("Los equipos y celulares de tu red abren Translay con una dirección. Tú decides qué biblioteca ve cada uno.") },
      { value: "no", icon: "lock", title: t("Solo este equipo"), desc: t("Se activa cuando quieras en Ajustes › Acceso y API.") },
    ], "big"),
    el("p", { class: "wz-note" }, icon("key"), t("Para entrar como propietario desde otro equipo, pon una contraseña en Ajustes › Acceso y API.")));
  const preview = wzPreview("wz-phone");
  const sync = () => {
    const on = wz.network === "yes";
    const url = wz.ip ? `http://${wz.ip}:8765` : "";
    const screen = on
      ? el("div", { class: "phone-screen" },
        el("div", { class: "phone-bar" }, el("span", { class: "wordmark", "data-size": "15" })),
        ...SAMPLE_VIDEOS.map(([, title, dur]) => el("div", { class: "phone-card" }, el("span", { class: "mini-thumb" }, el("span", { class: "mini-dur", text: dur })),
          el("strong", { text: title }))))
      : el("div", { class: "phone-screen off" }, el("span", { class: "wz-ic" }, icon("lock")), el("p", { text: t("Solo este equipo puede abrir la app.") }));
    const addr = el("div", { class: "phone-addr" + (on ? "" : " off") }, icon("globe"),
      el("code", { text: on ? url || t("No se encontró una red local.") : "127.0.0.1" }));
    preview.replaceChildren(addr, el("div", { class: "phone" }, screen));
    const mark = preview.querySelector(".phone-bar .wordmark");
    if (mark) requestAnimationFrame(() => wordmark(mark, 15));
  };
  return { opts, preview, sync };
}

// ------------------------------------------------------------ 8 · Conoce Translay
const TOUR = [
  ["link", t("Pega un enlace"), t("Translay lo descarga, lo traduce y lo dobla mientras lo ves.")],
  ["captions", t("Texto del video"), t("Lo escrito en pantalla, traducido en su lugar. Cópialo o pregúntale al agente.")],
  ["chat", t("Pregúntale al agente"), t("Responde lo que quieras saber del video.")],
  ["code", t("Código de la transcripción"), t("Los comandos y el código del video, listos para copiar.")],
  ["download", t("Exportar"), t("El video doblado, el audio o los subtítulos, en un clic.")],
];
i18nTrack(TOUR);
const TOUR_DEMOS = () => [demoDub, demoScreen, demoAsk, demoCode, demoExport];
function stepTour() {
  wz.tour = 0;
  const opts = el("div", { class: "wz-opts" }, el("div", { class: "wz-list tour" }, ...TOUR.map(([ic, title, desc], i) =>
    el("button", { type: "button", class: "wz-opt", "data-k": "tour", "data-v": String(i), on: { click: () => { loop.jump(i); } } },
      el("span", { class: "wz-ic" }, icon(ic)), el("span", { class: "wz-opt-text" }, el("strong", { text: title }), el("small", { text: desc }))))));
  const demo = demoStage();
  const preview = wzPreview("wz-demo", demo.box);
  const loop = demoLoop(demo, TOUR_DEMOS, (i) => { wz.tour = i; markOn(opts); });
  return { opts, preview, pause: loop.stop, resume: loop.start, stop: loop.stop };
}

// ------------------------------------------------------------ demos: a stage and a cursor that clicks
// One stage for every demo (option-previews skill): a 480×400 field scaled to its box, pieces with Translay's own
// classes and tokens, a cursor that moves and clicks, and one result mark at the end. The demo restarts when done.
const DM_W = 480, DM_H = 400;
const DM_STOP = Symbol("stop");
function demoStage() {
  const canvas = el("div", { class: "dm-canvas" });
  const cursor = el("div", { class: "dm-cursor", "aria-hidden": "true" });
  cursor.innerHTML = '<svg viewBox="0 0 20 28"><path d="M2 2v20.5l5.3-5 3.4 8 3.6-1.6-3.4-7.8H18z"/></svg>';
  const box = el("div", { class: "dm-stage", "aria-hidden": "true" }, canvas);
  const st = { box, canvas, cursor, k: 1 };
  new ResizeObserver(() => {
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;
    st.k = Math.min(w / DM_W, h / DM_H);
    canvas.style.transform = `translate(${(w - DM_W * st.k) / 2}px, ${(h - DM_H * st.k) / 2}px) scale(${st.k})`;
  }).observe(box);
  return st;
}

// runs the demos one after another (or one, again and again); stop() ends it at its next step
function demoLoop(st, list, onIndex) {
  let token = 0, i = 0;
  const run = async (my) => {
    while (my === token) {
      const demos = list();
      onIndex(i);
      const ctx = demoCtx(st, my, () => token);
      st.canvas.replaceChildren();
      st.canvas.classList.remove("out");
      try {
        await demos[i](ctx);
        await ctx.wait(1600);
        st.canvas.classList.add("out");
        await ctx.wait(280);
      } catch (e) {
        if (e !== DM_STOP) console.warn("demo", e);
        return;
      }
      i = (i + 1) % demos.length;
    }
  };
  return {
    start: () => { token++; run(token); },
    stop: () => { token++; },
    jump: (n) => { i = n; token++; run(token); },
  };
}

function demoCtx(st, my, current) {
  const alive = () => { if (current() !== my || !st.box.isConnected) throw DM_STOP; };
  const wait = (ms) => new Promise((ok, no) => setTimeout(() => (current() === my && st.box.isConnected ? ok() : no(DM_STOP)), ms));
  const at = (node, fx = 0.5, fy = 0.5) => {
    const r = node.getBoundingClientRect(), c = st.canvas.getBoundingClientRect();
    return [(r.left - c.left + r.width * fx) / st.k, (r.top - c.top + r.height * fy) / st.k];
  };
  const ctx = {
    wait,
    put(html) { st.canvas.replaceChildren(...[].concat(html), st.cursor); st.cursor.style.transform = `translate(${DM_W * 0.78}px, ${DM_H * 0.92}px)`; return st.canvas; },
    q: (s) => st.canvas.querySelector(s),
    async move(node, fx, fy) {
      alive();
      const [x, y] = at(node, fx, fy);
      st.cursor.style.transform = `translate(${x}px, ${y}px)`;
      await wait(620);
    },
    async click(node, fx, fy) {
      await ctx.move(node, fx, fy);
      st.cursor.classList.add("down");
      node.classList.add("dm-press");
      await wait(140);
      st.cursor.classList.remove("down");
      node.classList.remove("dm-press");
      await wait(160);
    },
    async type(node, text, ms = 38) {
      for (const ch of text) { alive(); node.textContent += ch; await wait(ms); }
    },
    async count(set, from, to, ms) {  // a percent that moves all the time
      const steps = Math.max(1, Math.round(ms / 60));
      for (let s = 0; s <= steps; s++) { alive(); set(Math.round(from + ((to - from) * s) / steps)); await wait(60); }
    },
    done(node) { node.append(el("span", { class: "dm-done" }, icon("check"))); },
  };
  return ctx;
}

const agentName = () => prefs.agent_name.trim() || "Lumi";
// the same sentence in each language (what is written in the video and its translation)
const SLIDE = { en: "Sales grew 40% this year", es: "Las ventas crecieron un 40 % este año", pt: "As vendas cresceram 40% este ano" };
const ASK = { es: "¿Qué dijo sobre el sueño?", en: "What did it say about sleep?", pt: "O que disse sobre o sono?" };
const ANSWER = {
  es: "Que dormir ayuda a fijar lo aprendido: el cerebro repasa el día mientras duermes.",
  en: "That sleep helps lock in what you learned: the brain replays the day while you sleep.",
  pt: "Que dormir ajuda a fixar o aprendido: o cérebro revisa o dia enquanto você dorme.",
};
const STEP_LINE = { es: "Instala el paquete con este comando", en: "Install the package with this command", pt: "Instale o pacote com este comando" };

async function demoDub(c) {
  const field = el("span", { class: "dm-field" }, icon("link"), el("span", { class: "dm-typed" }));
  const add = el("span", { class: "btn sm dark" }, icon("plus"), el("span", { class: "btn-text", text: t("Agregar") }));
  const list = el("div", { class: "dm-list" });
  c.put(el("div", { class: "dm-pad" }, el("strong", { class: "dm-h", text: t("Agrega un video") }), el("div", { class: "dm-row" }, field, add), list));
  await c.wait(400);
  await c.click(field, 0.2);
  await c.type(field.querySelector(".dm-typed"), "youtu.be/Xk3fL9qA2mE");
  await c.click(add);
  const pct = el("b", { class: "dm-pct", text: "0 %" });
  const what = el("span", { text: t("Descargando") });
  const bar = el("i");
  const card = el("div", { class: "dm-video" }, el("span", { class: "mini-thumb" }, el("span", { class: "mini-dur", text: "12:40" })),
    el("span", { class: "dm-vtext" }, el("strong", { text: t("Cómo funciona la memoria") }), el("span", { class: "dm-status" }, pct, what),
      el("span", { class: "bar-track" }, bar)));
  list.append(card);
  const set = (p) => { pct.textContent = `${p} %`; bar.style.setProperty("--p", `${p}%`); };
  await c.count(set, 0, 24, 700);
  what.textContent = t("Traduciendo");
  await c.count(set, 24, 58, 800);
  what.textContent = t("Doblando");
  await c.count(set, 58, 100, 1000);
  card.querySelector(".dm-status").replaceChildren(el("span", { class: "dm-ready" }, icon("check"), t("Listo en {lang}", { lang: langName(targetLang()) })));
  card.querySelector(".bar-track").remove();
}

async function demoScreen(c) {
  const target = targetLang();
  const source = target === "en" ? "pt" : "en";
  const text = el("span", { class: "dm-slide-text", text: SLIDE[source] });
  const slide = el("div", { class: "dm-frame" }, el("span", { class: "dm-slide-h", text: "2026" }), text, el("span", { class: "dm-slide-bars" }, el("i"), el("i"), el("i"), el("i")));
  c.put(el("div", { class: "dm-pad" }, slide));
  await c.wait(500);
  await c.move(text, 0.5, 0.6);
  text.classList.add("hover");
  await c.wait(350);
  text.textContent = SLIDE[target];
  text.classList.add("tr");
  const copy = el("span", { class: "btn xs" }, icon("copy"), el("span", { class: "btn-text", text: t("Copiar") }));
  const ask = el("span", { class: "btn xs" }, icon("chat"), el("span", { class: "btn-text", text: t("Preguntarle a {name}", { name: agentName() }) }));
  const menu = el("div", { class: "dm-menu" }, copy, ask);
  slide.append(menu);
  await c.wait(700);
  await c.click(copy);
  slide.append(el("span", { class: "dm-toast" }, icon("check"), t("Copiado")));
}

async function demoAsk(c) {
  const lang = I18N.lang;
  const star = el("span", { class: "dm-star" }, starSvg(agentLook(), null, ""));
  const msgs = el("div", { class: "dm-msgs" });
  const input = el("span", { class: "dm-field dm-ask" }, el("span", { class: "dm-typed" }), el("span", { class: "dm-ph", text: t("Pregúntale a {name}", { name: agentName() }) }));
  c.put(el("div", { class: "dm-chat" }, el("div", { class: "dm-chat-head" }, star, el("strong", { text: agentName() })), msgs, input));
  await c.wait(400);
  await c.click(input, 0.3);
  input.querySelector(".dm-ph").remove();
  await c.type(input.querySelector(".dm-typed"), ASK[lang] || ASK.es, 34);
  await c.wait(250);
  msgs.append(el("p", { class: "dm-q", text: ASK[lang] || ASK.es }));
  input.querySelector(".dm-typed").textContent = "";
  star.firstChild.setAttribute("class", "agent-star think");
  await c.wait(1300);
  star.firstChild.setAttribute("class", "agent-star talk");
  const a = el("p", { class: "dm-a" });
  msgs.append(a);
  await c.type(a, ANSWER[lang] || ANSWER.es, 22);
  a.append(el("span", { class: "dm-time", text: "05:30" }));
  star.firstChild.setAttribute("class", "agent-star");
}

async function demoCode(c) {
  const target = targetLang();
  const code = el("pre", { class: "dm-code" }, el("code", { text: "pip install requests" }));
  const lines = el("div", { class: "mini-lines dm-lines" },
    el("p", {}, el("b", { text: "02:10" }), STEP_LINE[target] || STEP_LINE.es), code,
    el("p", {}, el("b", { text: "02:24" }), TRANSCRIPT[2][1]));
  c.put(el("div", { class: "dm-pad" }, el("strong", { class: "dm-h", text: t("Transcripción") }), lines));
  await c.wait(500);
  await c.move(code, 0.4, 0.5);
  const copy = el("span", { class: "btn xs dm-copy" }, icon("copy"), el("span", { class: "btn-text", text: t("Copiar") }));
  code.append(copy);
  await c.wait(400);
  await c.click(copy);
  setBtn(copy, t("Copiado"), "check");
}

async function demoExport(c) {
  // como el diálogo de la app (web/index.html › export-dlg): una fila por tipo, con su formato y sus opciones
  const pill = (label) => el("span", { class: "dm-pill", text: label });
  const vDub = pill(t("Doblado")), tSrt = pill(t("Traducidos"));
  const card = (ic, title, fmt, ...pills) => el("div", { class: "dm-ex" },
    el("span", { class: "dm-ex-h" }, icon(ic), title, el("span", { class: "dm-ex-fmt", text: fmt })), el("span", { class: "dm-pills" }, ...pills));
  const video = card("film", t("Video"), "MP4", vDub, pill(t("Original")));
  const audio = card("music", t("Audio"), "M4A", pill(t("Doblado")), pill(t("Original")));
  const text = card("captions", t("Subtítulos"), "SRT", tSrt, pill(t("Del original")));
  const txt = card("lines", t("Texto"), "TXT", pill(t("Traducido")), pill(t("Resumen")));
  const go = el("span", { class: "btn sm dark dm-go" }, icon("download"), el("span", { class: "btn-text", text: t("Exportar") }));
  c.put(el("div", { class: "dm-pad" }, el("div", { class: "dm-ex-top" }, el("span", { class: "mini-thumb" }), el("strong", { text: t("Cómo funciona la memoria") })),
    el("div", { class: "dm-ex-cards" }, video, audio, text, txt), go));
  await c.wait(400);
  await c.click(vDub);
  vDub.classList.add("on");
  video.classList.add("on");
  setBtn(go, t("Exportar 1 archivo"), "download");
  await c.click(tSrt);
  tSrt.classList.add("on");
  text.classList.add("on");
  setBtn(go, t("Exportar {n} archivos", { n: 2 }), "download");
  await c.click(go);
  go.classList.add("busy");
  await c.count((p) => { setBtn(go, t("Exportando {pct} %", { pct: p }), "download"); go.style.setProperty("--p", `${p}%`); }, 0, 100, 1400);
  go.classList.remove("busy");
  setBtn(go, t("Listo"), "check");
}

async function demoYouTube(c) {
  const status = el("small", { text: t("Sin cuenta conectada") });
  const connect = el("span", { class: "btn sm dark" }, icon("user"), el("span", { class: "btn-text", text: t("Conectar con {name}", { name: "Chrome" }) }));
  const row = el("div", { class: "dm-set" }, el("span", { class: "wz-ic" }, icon("video")),
    el("span", { class: "dm-set-text" }, el("strong", { text: t("Cuenta de YouTube") }), status), connect);
  c.put(el("div", { class: "dm-pad" }, el("strong", { class: "dm-h", text: t("Agregar y descargar") }), row));
  await c.wait(500);
  await c.click(connect);
  status.textContent = t("Inicia sesión en YouTube en la ventana de {name} y ciérrala.", { name: "Chrome" });
  setBtn(connect, t("Esperando inicio de sesión…"), "user");
  connect.classList.add("busy");
  const signIn = el("span", { class: "btn sm dark" }, el("span", { class: "btn-text", text: t("Iniciar sesión") }));
  const win = el("div", { class: "dm-window" }, el("div", { class: "dm-window-bar" }, el("i"), el("i"), el("i"), el("span", { text: "accounts.google.com" })),
    el("div", { class: "dm-window-body" }, el("span", { class: "wz-ic" }, icon("user")), el("strong", { text: "YouTube" }), signIn));
  c.q(".dm-pad").append(win);
  await c.wait(500);
  await c.click(signIn);
  win.remove();
  connect.classList.remove("busy");
  setBtn(connect, t("Desconectar"), "x");
  connect.classList.remove("dark");
  status.textContent = t("Cuenta de YouTube conectada. Se usará en las descargas.");
  c.done(row);
}
