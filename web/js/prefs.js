"use strict";
// Ajustes: el inicio con sus bloques, cada página con sus opciones (vt/prefs.py) y la búsqueda.
// Comparte el ámbito global con app.js (se carga justo después).

/* ------------------------------------------------------------ preferencias */
// lo cambiado aquí que el servidor todavía no confirma: un aviso de «prefs» de otro cambio anterior trae el valor
// viejo y no debe pisarlo (al guardar dos cosas seguidas, se veía un instante lo anterior)
const prefsPending = {};
function setPref(key, value) {
  prefs[key] = value;
  prefsPending[key] = { value, until: Date.now() + 3000 };
  send({ type: "prefs_set", key, value });
  if (key === "app_mode") applyAppMode();
  if (key.startsWith("accent_") && typeof syncAccent === "function") syncAccent();
  if (key.startsWith("agent_") && typeof refreshAgentPreviews === "function") { refreshAgentPreviews(); renderAgent(); }
  if (key === "agent_device") { state.agentModels = null; }  // cambia cuál entra y cuál se recomienda
  if (key.startsWith("home_bg") && typeof syncSceneBg === "function") syncSceneBg();
  if (key.startsWith("home_bg") && currentView() === "library" && typeof renderHome === "function" && lib.sel === "home") renderHome();
}

function applyPrefs(m) {
  if (typeof syncExportOpts === "function") setTimeout(syncExportOpts);  // la carpeta de Exportar, en el diálogo
  prefsSchema = m.schema;
  prefsSections = m.sections || [];
  prefsAltSections = m.alt_sections || {};
  prefsGroups = m.groups || [];
  if (DESKTOP) prefsSections = [...prefsSections, DESKTOP_SECTION];  // web/js/desktop.js
  // dónde guardar lo exportado solo se elige en este equipo (desde otro, lo descarga el navegador)
  if (!(state.access?.local && state.access?.owner)) prefsSections = prefsSections.filter(([k]) => k !== "exportar");
  prefsVaultKeys = m.vault_keys || [];
  const before = JSON.stringify(prefs);
  prefs = { ...prefs, ...m.values };
  for (const [k, p] of Object.entries(prefsPending)) {
    if (m.values[k] === p.value || Date.now() > p.until) delete prefsPending[k];  // confirmado (o no llegó)
    else prefs[k] = p.value;
  }
  TARGET = prefs.target_lang || m.lang || I18N.lang;  // i18n.js
  // otro idioma de la app: sin recargar (i18n.js › switchLang); después se redibuja todo lo que tiene texto
  if (m.lang && m.lang !== I18N.lang && !langSwitching) {
    langSwitching = true;
    switchLang(m.lang).catch((e) => console.warn("idioma:", e)).finally(() => {
      langSwitching = false;
      prefsSigSeen = "";  // Ajustes se redibuja entero, con su esquema en el idioma nuevo
      applyPrefs(m);
      rerenderForLang();
    });
    return;
  }
  applyTheme();
  if (typeof syncSceneBg === "function") syncSceneBg();
  applyAppMode();
  if (typeof syncAccent === "function") syncAccent();
  setLayout(!state.translates || prefs.layout !== "dividida", false);
  applySubs();
  if (typeof applyCodeTheme === "function") applyCodeTheme();
  if (typeof renderAgent === "function") renderAgent();
  if (state.audio) state.audio.orig.gain.value = state.dubMode ? duck() : 1;
  // la confirmación de un cambio hecho aquí no trae nada nuevo: Ajustes no se redibuja (con «Al azar» llegaban
  // varias seguidas y la página parpadeaba)
  const same = JSON.stringify(prefs) === before && prefsSigSeen === JSON.stringify([m.schema?.length, m.sections, m.lang]);
  prefsSigSeen = JSON.stringify([m.schema?.length, m.sections, m.lang]);
  if (!same) renderPrefs();
  if (typeof renderLibrary === "function") renderLibrary();
  if (typeof maybeWelcome === "function") maybeWelcome();  // la primera vez: la bienvenida (web/js/welcome.js)
}
let prefsSigSeen = "";
let langSwitching = false;
// después de cambiar de idioma: cada vista vuelve a dibujarse con t() en el idioma nuevo (lo fijo ya lo cambió
// switchLang); lo que está abierto queda abierto
function rerenderForLang() {
  const call = (name, ...a) => { try { if (typeof window[name] === "function") window[name](...a); } catch (e) { console.warn(name, e); } };
  for (const f of ["renderVaultBtn", "renderSideVault", "renderLibrary", "renderTranscript", "renderSummary", "renderAgent",
    "renderQueuePanel", "renderPower", "applySubs", "renderPeople", "renderUpNext", "agentTabLabel"]) call(f);
  if ($("#welcome-dlg")?.open) call("renderWelcome");
  if (typeof renderActive === "function") renderActive(true);
  document.title = state.videoName ? `${state.videoName} · Translay` : "Translay";
}

const YT_IMPORT = $("#yt-import");
const YT_ACCOUNT = $("#yt-account");
// Ajustes como en una app: las secciones a la izquierda (una página cada una) y,
// en la página, las opciones agrupadas con su descripción. Los bloques propios
// (bibliotecas, glosario, sesión de YouTube, acceso) van como un grupo más.
const PREF_BLOCKS = {
  escritorio: () => desktopPrefsBlocks(),
  bibliotecas: () => [[VAULTS_BLOCK, t("Tus bibliotecas"), t("Abre, edita, cambia el acceso o elimina una biblioteca. Pueden estar en otra carpeta o disco.")]],
  glosario: () => [[GLOSSARY_BLOCK, t("Términos"), t("Si la traducción queda vacía, el término se mantiene como en el original (nombres, marcas, siglas). Al guardar, se vuelven a traducir las frases que lo usan.")]],
  biblioteca: () => [[YT_ACCOUNT, t("Cuenta de YouTube"), t("Inicia sesión una vez en una ventana del navegador. Translay guarda solo las cookies de YouTube, cifradas, y las renueva automáticamente. Se recomienda una cuenta secundaria.")],
    [YT_IMPORT, t("Importar sesión"), t("Importa la sesión de un navegador de este equipo o sube un archivo cookies.txt. Solo se guardan las cookies de YouTube.")]],
  rendimiento: () => {
    perfStart();
    renderPerf();
    return [[PERF_HW, t("Tu equipo"), ""], [PERF_PROFILE, t("Perfil"), t("Modelos que usa Translay. Los tiempos y el estado se basan en mediciones reales en equipos similares al tuyo.")],
      [PERF_LIMITS, t("Límites"), t("Recursos del equipo que puede usar Translay. Los límites de RAM y CPU se aplican de inmediato.")],
      [PERF_ALERTS, t("Avisos"), ""]];
  },
  almacenamiento: () => {
    storageScan();
    renderStorage();
    return [[STORAGE_SUMMARY, t("Espacio usado"), ""],
      [STORAGE_LIBS, t("Bibliotecas"), t("Los videos liberados siguen en la biblioteca y se descargan de nuevo al abrirlos.")],
      [STORAGE_LARGEST, t("Mayor uso de espacio"), ""],
      [STORAGE_MODELS, t("Modelos"), t("Los del perfil que usas no se pueden borrar. Los demás se vuelven a descargar si los necesitas.")],
      [STORAGE_APP, "Translay", ""]];
  },
  papelera: () => { if (can("owner")) send({ type: "trash_list" }); return [[TRASH_BLOCK, t("En la papelera"), t("Los elementos se eliminan automáticamente a los 30 días.")]]; },
  acceso: () => [
    [ACC.owner, t("Contraseña de propietario"), t("Permite acceder como propietario desde otros equipos. En este equipo no se solicita.")],
    [ACC.net, t("Acceso desde otros equipos"), t("Permite acceder a Translay desde otros equipos y celulares de tu red local.")],
    [ACC.libs, t("Acceso a cada biblioteca"), t("Privada, con contraseña o pública, y si los invitados solo pueden ver o también importar.")],
    [ACC.keys, t("Claves de API"), t("Para que otras apps y scripts usen Translay. Cada clave sirve para todas las bibliotecas o una, de lectura o escritura.")],
    [ACC.hooks, "Webhooks", t("Notificaciones a otras apps cuando ocurre un evento: un video listo, cambios en la cola, descargas, exportaciones…")],
  ],
};
i18nTrack(PREF_BLOCKS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

function prefControl(p) {
  if (p.key === "theme_mode") return appearanceRow(p);
  let opts = p.type === "bool" ? [[true, t("Sí")], [false, t("No")]] : p.options;
  if (p.key === "summary_model" && state.summaryRec) {  // «Automático» dice cuál usa en este equipo
    const rec = p.options.find(([k]) => k === state.summaryRec);
    opts = opts.map(([k, lbl]) => [k, k === "auto" && rec ? t("Automático ({name})", { name: rec[1] }) : lbl]);
  }
  if (p.key === "export_ask") return exportAskRow(p);
  if (p.key === "accent_color") return accentRow(p);
  if (p.key === "code_theme") return codeThemeRow(p);
  if (p.key === "agent_color") return swatchRow(p);
  if (p.key === "agent_avatar") return avatarRow(p);
  if (p.key === "agent_model") return agentModelRow(p);
  if (p.key === "home_bg") return homeBgRow(p);
  if (p.type === "text") return textRow(p);
  if (p.type === "range") return rangeRow(p);
  if (p.type === "bool") {  // interruptor
    const on = prefs[p.key] === true;
    return el("button", { type: "button", class: "switch" + (on ? " on" : ""), role: "switch", "aria-checked": String(on), "aria-label": p.label,
      on: { click: () => { setPref(p.key, !on); if (p.key === "notify" && !on) requestNotify(); renderPrefs(); } } }, el("i"));
  }
  if (opts.length > 4) {  // muchas opciones: lista desplegable (como grupo no caben en una fila)
    // el <option> guarda la posición: el valor vuelve con su tipo (número, texto…)
    const sel = el("select", { class: "select", "aria-label": p.label,
      on: { change: (e) => { setPref(p.key, opts[+e.target.value][0]); renderPrefs(); } } },
      ...opts.map(([value, text], i) => el("option", { value: String(i), text, selected: prefs[p.key] === value })));
    return el("div", { class: "pref-dd" }, sel);
  }
  return el("div", { class: "segs" }, ...opts.map(([value, text]) => el("button", { type: "button", class: "seg" + (prefs[p.key] === value ? " on" : ""),
    on: { click: () => { setPref(p.key, value); renderPrefs(); } } }, text)));
}

// una cantidad: deslizador propio con el valor en números. Se arrastra hasta donde uno quiera y se detiene un
// instante en los niveles habituales (topes suaves); doble clic vuelve al valor por defecto; rueda y flechas
// ajustan de a un paso. Se guarda al soltar.
function rangeRow(p) {
  let v = prefs[p.key] ?? p.default;
  const pct = (x) => ((x - p.min) / (p.max - p.min)) * 100;
  const fill = el("i", { class: "rg-fill" });
  const thumb = el("b", { class: "rg-thumb" });
  const track = el("div", { class: "rg-track" }, fill, thumb);
  const out = el("output", { class: "rg-val" });
  const box = el("div", { class: "rg", role: "slider", tabindex: "0", "aria-label": p.label,
    "aria-valuemin": p.min, "aria-valuemax": p.max }, track, out);
  const show = (x) => {
    v = x;
    fill.style.width = thumb.style.left = `${pct(x)}%`;
    out.textContent = `${x} ${p.unit || ""}`.trim();
    box.setAttribute("aria-valuenow", x);
  };
  const clamp = (x) => Math.min(p.max, Math.max(p.min, Math.round(x / p.step) * p.step));
  const save = () => { if (v !== prefs[p.key]) setPref(p.key, v); };
  const at = (e) => {
    const r = track.getBoundingClientRect();
    let x = p.min + ((e.clientX - r.left) / r.width) * (p.max - p.min);
    const stop = (p.stops || []).find((s) => Math.abs(s - x) <= (p.max - p.min) * 0.03);  // tope suave
    return clamp(stop ?? x);
  };
  box.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    box.setPointerCapture(e.pointerId);
    box.classList.add("drag");
    show(at(e));
    const move = (ev) => show(at(ev));
    const up = () => { box.classList.remove("drag"); box.removeEventListener("pointermove", move); save(); };
    box.addEventListener("pointermove", move);
    box.addEventListener("pointerup", up, { once: true });
    box.addEventListener("pointercancel", up, { once: true });
  });
  box.addEventListener("dblclick", () => { show(p.default); save(); });
  box.addEventListener("keydown", (e) => {
    const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (!d) return;
    e.preventDefault();
    show(clamp(v + d * p.step));
    save();
  });
  box.addEventListener("wheel", (e) => {
    e.preventDefault();
    show(clamp(v + (e.deltaY < 0 ? 1 : -1) * p.step));
    clearTimeout(box._t);
    box._t = setTimeout(save, 400);
  }, { passive: false });
  show(v);
  return box;
}

// color de énfasis: muestras (la primera, el del tema); con «Color de cada biblioteca» manda el de la biblioteca
function accentRow(p) {
  const cur = prefs.accent_color || "";
  return el("div", { class: "vcolors accent-colors" + (prefs.accent_lib ? " off" : "") }, ...p.options.map(([value, name]) =>
    el("button", { type: "button", class: "vcolor" + (value ? " split" : " theme") + (cur === value ? " on" : ""), title: name,
      "aria-label": name, "aria-pressed": String(cur === value), style: value ? `--vc: ${value}` : null,
      on: { click: () => { setPref(p.key, value); renderPrefs(); } } }, value ? splitSwatch() : icon("theme"))));
}

// texto libre (el nombre y el tono del agente): se guarda al dejar de escribir
function textRow(p) {
  const multi = !!p.multiline;
  const f = el(multi ? "textarea" : "input", { class: multi ? "area pref-text" : "field pref-text", maxlength: p.max || 200,
    "aria-label": p.label, rows: multi ? 3 : null, placeholder: p.key === "agent_tone"
      ? t("Ejemplo: explícame como a alguien que recién empieza, con ejemplos y en viñetas") : p.label });
  f.value = prefs[p.key] ?? "";
  let timer;
  const save = () => { clearTimeout(timer); const v = f.value.trim(); if (v !== (prefs[p.key] ?? "")) setPref(p.key, v); };
  f.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(save, 700); });
  f.addEventListener("blur", save);
  return el("div", { class: "pref-textwrap" + (multi ? " multi" : "") }, f);
}

const HOME_PREVIEW_W = 1120;
// fondo del inicio: las opciones a la izquierda y, al lado, el inicio de verdad
// (la misma luz y el mismo destacado de web/js/home.js, con lo que sigues viendo)
function homeBgRow(p) {
  const cur = homeBgMode();
  const ICON = { translay: "mic", recorrido: "arrow", luna: "moon", tierra: "globe", nubes: "sun", mar: "globe", arrecife: "flask", ballena: "music", atardecer: "theme", medusas: "spark", abismo: "eye", naufragio: "drive", "arañas": "atom", "arañas y perro": "paw", imagen: "upload" };
  const list = el("div", { class: "opt-list" }, ...p.options.map(([value, text]) => el("button", { type: "button",
    class: "code-theme" + (cur === value ? " on" : ""), "aria-pressed": String(cur === value), on: { click: () => {
      if (value === "imagen" && !prefs.home_bg_rev) { pickHomeBg(); return; }  // sin imagen aún: primero elegirla
      setPref(p.key, value); renderPrefs();
    } } }, icon(ICON[value] || "film"), text)),
    cur === "imagen" ? btn(t("Cambiar imagen"), { icon: "upload", size: "sm", variant: "ghost", onClick: pickHomeBg }) : null);
  const lead = typeof heroVideo === "function" ? heroVideo() : null;
  // el inicio se arma a tamaño de escritorio (HOME_PREVIEW_W) y se reduce entero: una miniatura fiel, sin apretar nada
  const first = typeof homeRows === "function" ? homeRows(lead?.v.id)[0] : null;  // y la primera fila, como en el inicio
  const stage = el("div", { class: "hp-stage" }, homeLight(lead?.v, cur, true),
    lead ? hero(lead) : el("p", { class: "home-preview-empty", text: t("Aquí aparecerá lo que sigues viendo") }),
    first ? row(first) : null);
  const preview = el("div", { class: "home-preview", "aria-label": t("Vista previa del inicio") }, stage);
  const fit = () => {
    const k = preview.clientWidth / HOME_PREVIEW_W;
    stage.style.transform = `scale(${k})`;
    preview.style.height = `${Math.round(stage.offsetHeight * k)}px`;
  };
  new ResizeObserver(fit).observe(preview);
  new ResizeObserver(fit).observe(stage);
  return el("div", { class: "opt-split" }, list, preview);
}

// la imagen propia: se reduce en el navegador (hasta 1920 px, JPEG) y se guarda en data/ui/home-bg.jpg
function pickHomeBg() {
  const f = el("input", { type: "file", accept: "image/*" });
  f.addEventListener("change", async () => {
    const file = f.files[0];
    if (!file) return;
    try {
      const bmp = await createImageBitmap(file);
      const k = Math.min(1, 1920 / bmp.width);
      const c = el("canvas", { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.85));
      const r = await fetch("/api/home-bg", { method: "PUT", body: blob });
      if (!r.ok) throw new Error(await r.text());
      setPref("home_bg_rev", String(Date.now()));
      setPref("home_bg", "imagen");
      renderPrefs();
    } catch {
      toast(t("No se pudo usar esa imagen. Prueba con otra."));
    }
  });
  f.click();
}

// color propio (el del agente): muestras como las del color de énfasis
function swatchRow(p) {
  const cur = prefs[p.key] || "";
  return el("div", { class: "vcolors", "data-pref": p.key }, ...p.options.map(([value, name]) =>
    el("button", { type: "button", class: "vcolor" + (value ? "" : " theme") + (cur === value ? " on" : ""), title: name, "data-v": value,
      "aria-label": name, "aria-pressed": String(cur === value), style: value ? `--vc: ${value}` : null,
      on: { click: () => { setPref(p.key, value); renderPrefs(); if (typeof renderAgent === "function") renderAgent(); } } },
    value ? null : icon("theme"))));
}

// modelo del agente: agrupados por si son compatibles con este equipo, con su calidad en el laboratorio y su tamaño
// (vt/agentsvc.py › catalog); «Automático» dice cuál usaría
// calidad en el laboratorio: palabra y su color (de verde a ámbar; «Poco confiable», el que inventa respuestas, en un rojo apagado)
const QUALITY_LEVEL = (q) => (q == null ? null : q >= 0.97 ? [t("Excelente"), "exc"] : q >= 0.9 ? [t("Muy buena"), "good"]
  : q >= 0.8 ? [t("Buena"), "ok"] : [t("Básica"), "low"]);
function agentModelRow(p) {
  const cat = state.agentModels;
  if (!cat) send({ type: "agent_models" });  // llega en un momento y la página se redibuja
  const info = new Map((cat?.models || []).map((m) => [m.key, m]));
  const name = (k) => info.get(k)?.name || (p.options.find(([v]) => v === k) || [k, k])[1];
  const gb = (m) => `${m.gb.toLocaleString(LOCALE, { maximumFractionDigits: 1 })} GB`;
  const opt = (k, text, hint) => { const o = new Option(text, k, false, (prefs[p.key] || "auto") === k); if (hint) o._hint = hint; return o; };
  const sel = el("select", { class: "select", "aria-label": p.label, on: { change: (e) => { setPref(p.key, e.target.value); renderPrefs(); } } });
  sel.append(opt("auto", cat?.recommended ? t("Automático ({name})", { name: name(cat.recommended) }) : t("Automático")));
  if (cat) {
    const ms = [...info.values()].sort((a, b) => (b.quality ?? 0) - (a.quality ?? 0));
    const hint = (m) => () => {
      const [word, tone] = m.honest ? QUALITY_LEVEL(m.quality) || ["", ""] : [t("Poco confiable"), "bad"];
      return el("kbd", { class: "model-hint" }, word ? el("b", { class: "q-" + tone, text: word }) : null,
        word ? " · " : "", m.downloaded ? t("descargado") : gb(m));
    };
    const groups = [
      [t("Recomendado"), ms.filter((m) => m.key === cat.recommended)],
      [t("Compatibles"), ms.filter((m) => m.key !== cat.recommended && m.fits && !m.slow)],
      [t("Lentos en este equipo"), ms.filter((m) => m.key !== cat.recommended && m.fits && m.slow)],
      [t("Necesitan más memoria"), ms.filter((m) => m.key !== cat.recommended && !m.fits)],
    ];
    for (const [label, list] of groups) {
      if (!list.length) continue;
      const g = el("optgroup", { label });
      for (const m of list) g.append(opt(m.key, m.name, hint(m)));
      sel.append(g);
    }
  } else {
    for (const [k, t] of p.options) if (k !== "auto") sel.append(opt(k, t));
  }
  return el("div", { class: "pref-model" }, el("div", { class: "pref-dd" }, sel), agentModelFile(cat));
}

// el archivo del modelo que se va a usar: descargado, bajando (avance en el botón) o «Descargar» de antemano
function agentModelFile(cat) {
  const key = prefs.agent_model && prefs.agent_model !== "auto" ? prefs.agent_model : cat?.recommended;
  const m = cat?.models.find((x) => x.key === key);
  if (!m) return null;
  const size = `${m.gb.toLocaleString(LOCALE, { maximumFractionDigits: 1 })} GB`;
  if (m.downloaded) return el("p", { class: "pref-model-file" }, icon("check"), t("Descargado · {size}", { size }));
  if (!canImport()) return el("p", { class: "pref-model-file", text: t("Se descarga con la primera pregunta · {size}", { size }) });
  const busy = m.downloading != null;
  return btn(busy ? t("Descargando {pct} %", { pct: m.downloading }) : t("Descargar · {size}", { size }), { icon: "download", size: "sm", variant: "ghost",
    disabled: busy, onClick: () => { m.downloading = 0; send({ type: "agent_model_download", key: m.key }); renderPrefs(); } });
}

// avatar del agente: íconos de línea, el elegido con su color
// el creador del agente (web/js/star.js): la estrella grande con sus estados y, al lado, cada parte con su muestra
// la estrella grande del creador es siempre el mismo elemento: Ajustes se redibuja al guardar (y otra vez cuando el
// servidor confirma), y así la transición de una estrella a otra sigue sin cortarse
// (los estados, el cambio de una estrella a otra y las muestras de cada parte están en web/js/star.js)
const starStage = { el: null, key: null, state: "", timer: null };
function avatarRow(p) {
  const look = agentLook();
  const key = () => JSON.stringify(agentLook()) + (prefs.agent_color || themeStarColor());
  const current = () => starSvg(agentLook(), null, starStage.state);
  if (!starStage.el) {
    starStage.el = el("div", { class: "star-big" }, current());
    starStage.el.addEventListener("click", agentBoop);  // tocarla: se pone contenta (web/js/agentview.js)
    starStage.key = key();
    // la vista previa pasa sola por sus gestos: en reposo, pensando y respondiendo (sin selector: elegido 2026-11-14)
    starStage.timer = setInterval(() => {
      if (!starStage.el.isConnected) return;
      starStage.state = STAR_STATES[(STAR_STATES.indexOf(starStage.state) + 1) % STAR_STATES.length];
      starStage.el.querySelector(".agent-star:not(.leaving)")?.setAttribute("class", ("agent-star " + starStage.state).trim());
    }, 2600);
  }
  const stage = starStage.el;
  const sync = () => {  // si cambió algo (aquí, otro color, el servidor), la nueva entra sobre la anterior
    if (starStage.key !== key()) { starStage.key = key(); starSwap(stage, current()); }
  };
  sync();
  const opts = {};  // parte → sus botones (para marcar la elegida y redibujar sus muestras)
  const refresh = () => {
    const now = agentLook();
    for (const [k, buttons] of Object.entries(opts)) {
      for (const b of buttons) {
        const on = now[k] === b.dataset.v;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", String(on));
        b.replaceChildren(starThumb({ ...now, [k]: b.dataset.v }, k));
      }
    }
    sync();
  };
  const save = (patch) => {
    setPref(p.key, JSON.stringify({ ...agentLook(), ...patch }));
    if (typeof renderAgent === "function") renderAgent();
    if (typeof refreshAgentPreviews === "function") refreshAgentPreviews();
  };
  const part = (k, label) => {
    opts[k] = STAR_PARTS[k].map(([value, name]) => {
      const b = el("button", { type: "button", class: "star-opt" + (look[k] === value ? " on" : ""), title: name, "aria-label": name,
        "aria-pressed": String(look[k] === value), "data-v": value }, starThumb({ ...look, [k]: value }, k));
      b.addEventListener("click", () => { if (agentLook()[k] !== value) { save({ [k]: value }); refresh(); } });
      return b;
    });
    // de a 4, grandes, con flechas para ver las anteriores y las siguientes (web/js/ui.js › carousel)
    return el("div", { class: "star-part" }, el("span", { text: label }),
      carousel(opts[k], { per: 4, start: opts[k].find((b) => b.classList.contains("on")), label }));
  };
  // al azar: todas las partes y el color, sin redibujar la página (el color, en su fila, se marca aparte)
  const random = btn(t("Al azar"), { icon: "dice", size: "sm", variant: "ghost", onClick: () => {
    const pick = (a) => a[Math.floor(Math.random() * a.length)];
    const now = agentLook();
    const patch = Object.fromEntries(Object.keys(STAR_PARTS).map((k) => [k, pick(STAR_PARTS[k].filter(([v]) => v !== now[k]))[0]]));
    const colors = (prefsSchema.find((x) => x.key === "agent_color")?.options || []).map((o) => o[0]).filter((c) => c && c !== prefs.agent_color);
    if (colors.length) {
      setPref("agent_color", pick(colors));
      document.querySelectorAll('[data-pref="agent_color"] [data-v]').forEach((x) => x.classList.toggle("on", x.dataset.v === prefs.agent_color));
    }
    save(patch);
    refresh();
  } });
  return el("div", { class: "star-maker" }, el("div", { class: "star-stage" }, stage, random),
    el("div", { class: "star-parts" }, part("shape", t("Forma")), part("eyes", t("Ojos")), part("mouth", t("Boca")),
      part("cheeks", t("Mejillas")), part("acc", t("Accesorio"))));
}

// colores del código (web/js/codetheme.js): los temas a la izquierda y, al lado, cómo se ve un ejemplo
function codeThemeRow(p) {
  const cur = CODE_THEMES[prefs.code_theme] ? prefs.code_theme : CODE_THEME_DEFAULT;
  const pre = el("pre", { class: "code-sample" });
  pre.append(highlight(CODE_SAMPLE));
  const list = el("div", { class: "code-themes opt-list" }, ...p.options.map(([value, name]) => {
    const t = codeThemeFor(value);  // su muestra en la versión del modo actual (claro u oscuro)
    return el("button", { type: "button", class: "code-theme" + (cur === value ? " on" : ""), "aria-pressed": String(cur === value),
      style: `--b: ${t.bg}; --c1: ${t.kw}; --c2: ${t.str}; --c3: ${t.fn}; --c4: ${t.com}`,
      on: { click: () => { setPref(p.key, value); applyCodeTheme(value); renderPrefs(); } } },
    el("i", { class: "code-swatch" }, el("b"), el("b"), el("b"), el("b")), name);
  }));
  return el("div", { class: "opt-split" }, list, pre);
}

// dónde guardar lo exportado: preguntar o una carpeta fija (que se elige con el cuadro de Windows)
function exportAskRow(p) {
  const dir = prefs.export_dir || "";
  const fixed = prefs.export_ask === "carpeta" && dir;
  return el("div", { class: "segs" },
    el("button", { type: "button", class: "seg" + (fixed ? "" : " on"), on: { click: () => { setPref("export_ask", "preguntar"); renderPrefs(); } } }, t("Preguntar")),
    el("button", { type: "button", class: "seg" + (fixed ? " on" : ""), title: dir,
      on: { click: () => { if (!dir || fixed) send({ type: "export_pick_folder" }); else { setPref("export_ask", "carpeta"); renderPrefs(); } } } },
    icon("folder"), dir ? shortPath(dir) : t("Elegir carpeta")));
}

function renderPrefs() {
  const nav = $("#prefs-nav");
  const body = $("#prefs-body");
  // escribiendo en esta misma página (una contraseña, una URL): se redibuja al salir del cuadro,
  // no a mitad (un aviso de otra pestaña borraría lo escrito)
  const f = document.activeElement;
  if (f && body.contains(f) && f.matches("input:not([type=checkbox]):not([type=radio]):not([type=range]), textarea")
      && body.dataset.sec === lib.prefSec) {
    if (!renderPrefs.pending) {
      renderPrefs.pending = true;
      f.addEventListener("blur", () => setTimeout(() => { renderPrefs.pending = false; renderPrefs(); }, 400), { once: true });
    }
    return;
  }
  $("#stash").append(YT_ACCOUNT, YT_IMPORT, GLOSSARY_BLOCK, VAULTS_BLOCK, TRASH_BLOCK,
    STORAGE_SUMMARY, STORAGE_LIBS, STORAGE_LARGEST, STORAGE_MODELS, STORAGE_APP, PERF_HW, PERF_PROFILE, PERF_LIMITS, PERF_ALERTS,
    ...Object.values(ACC));  // se vuelven a poner en su página
  if (!prefsSections.length) return;
  if (lib.prefSec === "youtube") lib.prefSec = "biblioteca";  // YouTube ahora está en Agregar y descargar
  if (!lib.prefSec || !prefsSections.some(([k]) => k === lib.prefSec)) lib.prefSec = "inicio";
  if (typeof syncRoute === "function" && currentView() === "prefs") syncRoute();
  const vaultKeys = new Set(prefsVaultKeys);
  const vaultName = typeof currentVault === "function" && vaults.list.length > 1 ? currentVault().name : "";
  // páginas y opciones de un solo modo (Ajustes › Uso): al solo transcribir no aparece lo de traducción
  const mode = transcribeMode() ? "transcribir" : "traducir";
  const sections = prefsSections.filter((s) => !s[4] || s[4] === mode).map((s) =>
    mode === "transcribir" && prefsAltSections[s[0]] ? [s[0], ...prefsAltSections[s[0]], s[3]] : s);
  if (lib.prefSec !== "inicio" && !sections.some(([k]) => k === lib.prefSec)) lib.prefSec = "inicio";
  // la barra lateral: el inicio y, debajo, las secciones por bloque (como en el inicio)
  const navItem = (k, title, ic) => el("button", { type: "button", class: "item" + (k === lib.prefSec ? " active" : ""),
    on: { click: () => { lib.prefSec = k; renderPrefs(); body.scrollTop = 0; } } }, el("span", {}, icon(ic || "sliders"), title));
  nav.replaceChildren(...prefsBlocks(sections).flatMap(([g, list]) => [el("h4", { text: g }), ...list.map(([k, title, , ic]) => navItem(k, title, ic))]));
  if (lib.prefSec === "inicio") {
    body.replaceChildren(renderPrefsHome(sections));
    body.dataset.sec = lib.prefSec;
    return;
  }
  const [sec, title, desc] = sections.find(([k]) => k === lib.prefSec);
  // volver al inicio de Ajustes (también con el botón Ajustes del encabezado)
  const back = el("button", { type: "button", class: "pref-back", on: { click: () => { lib.prefSec = "inicio"; renderPrefs(); body.scrollTop = 0; } } },
    icon("chevron"), t("Ajustes"));
  const page = el("div", { class: "pref-page" },
    el("header", { class: "pref-head" }, back, el("h2", { text: title }), desc ? el("p", { text: desc }) : null,
      vaultName && prefsSchema.some((p) => p.section === sec && vaultKeys.has(p.key)) || sec === "glosario" && vaultName
        ? el("span", { class: "pref-scope" }, vaultBadge(currentVault(), "xs"), t("Se guarda en «{name}»", { name: vaultName })) : null));
  // opciones, por grupo
  const groups = new Map();
  for (const base of prefsSchema.filter((x) => x.section === sec && (!x.only || x.only === mode))) {
    const p = mode === "transcribir" && base.alt ? { ...base, ...base.alt } : base;
    if (!groups.has(p.group)) groups.set(p.group, []);
    groups.get(p.group).push(p);
  }
  for (const [g, items] of groups) {
    const rows = items.map((p) => {
      const ctl = prefControl(p);
      if (!ctl) return null;
      // un texto largo (el tono del agente) o la cuadrícula de temas de código: a lo ancho, debajo del título
      const wide = (p.type === "text" && p.multiline) || p.key === "code_theme" || p.key === "home_bg";
      return el("div", { class: "set-row" + (wide ? " wide" : ""), id: `pref-${p.key}` },
        el("div", { class: "set-text" }, el("strong", { text: p.label }), p.desc ? el("p", { text: p.desc }) : null),
        el("div", { class: "set-ctl" }, ctl));
    }).filter(Boolean);
    // un grupo de una sola opción no repite su título (la opción ya lo tiene)
    if (rows.length) page.append(el("section", { class: "set-group" }, g && rows.length > 1 ? el("h3", { text: g }) : null, el("div", { class: "set-rows" }, ...rows)));
  }
  // bloques propios de la página
  if (sec === "bibliotecas") renderVaultsPref();
  if (sec === "acceso") renderAdmin();
  for (const [block, t, d] of (PREF_BLOCKS[sec] ? PREF_BLOCKS[sec]() : [])) {
    page.append(el("section", { class: "set-group block" }, el("h3", { text: t }), d ? el("p", { class: "set-desc", text: d }) : null, block));
  }
  // Ajustes › Agente: la vista previa es la misma al redibujar la página (no vuelve arriba al cambiar algo)
  let keep = null;
  if (sec === "agente" && typeof agentPreview === "function") {
    const old = body.querySelector(".pref-split-side .ag-preview");
    keep = old ? [old, old.querySelector(".ag-scroll").scrollTop] : null;
    if (old) refreshAgentPreviews();
    const [head, ...rest] = page.children;
    page.replaceChildren(head, el("div", { class: "pref-split" }, el("div", { class: "pref-split-main" }, ...rest),
      el("aside", { class: "pref-split-side" }, old || agentPreview())));
  }
  body.replaceChildren(page);
  if (keep) keep[0].querySelector(".ag-scroll").scrollTop = keep[1];
  body.dataset.sec = lib.prefSec;
}
// las secciones repartidas en sus bloques; las que no están en ninguno, en uno sin título al final
function prefsBlocks(sections) {
  const byKey = new Map(sections.map((s) => [s[0], s]));
  const used = new Set();
  const out = prefsGroups.map(([g, keys]) => [g, keys.filter((k) => byKey.has(k)).map((k) => { used.add(k); return byKey.get(k); })])
    .filter(([, list]) => list.length);
  const rest = sections.filter((s) => !used.has(s[0]));
  if (rest.length) out.push([t("Más"), rest]);
  return out;
}

// el inicio de Ajustes: una tarjeta por sección (ícono, título y qué hay dentro), por bloque, y una búsqueda que
// también encuentra las opciones de cada sección («subtítulos» lleva a Audio y subtítulos)
function renderPrefsHome(sections) {
  const grid = el("div", { class: "set-home-grid" });
  const draw = (q) => {
    q = (q || "").trim().toLowerCase();
    const hit = (s) => !q || [s[1], s[2], ...prefsSchema.filter((p) => p.section === s[0]).flatMap((p) => [p.label, p.desc])]
      .some((t) => (t || "").toLowerCase().includes(q));
    const blocks = prefsBlocks(sections).map(([g, list]) => [g, list.filter(hit)]).filter(([, list]) => list.length);
    grid.replaceChildren(...(blocks.length ? blocks.map(([g, list]) => el("section", { class: "set-home-block" },
      el("h3", { text: g }),
      el("div", { class: "set-cards" }, ...list.map(([k, title, desc, ic]) => el("button", { type: "button", class: "set-card",
        on: { click: () => { lib.prefSec = k; renderPrefs(); $("#prefs-body").scrollTop = 0; } } },
        el("span", { class: "set-card-ic" }, icon(ic || "sliders")), el("strong", { text: title }), desc ? el("p", { text: desc }) : null)))))
      : [emptyState("search", t("Sin resultados"), t("Prueba con otra palabra, como «subtítulos» o «modelo»."))]));
  };
  const input = el("input", { type: "search", placeholder: t("Buscar en ajustes"), "aria-label": t("Buscar en ajustes"),
    on: { input: (e) => draw(e.target.value) } });
  draw("");
  return el("div", { class: "pref-page set-home" },
    el("header", { class: "pref-head set-home-head" }, el("h2", { text: t("Ajustes") }),
      el("label", { class: "field set-search" }, icon("search"), input)),
    grid);
}
function markPrefsNav() {}  // (antes: índice que seguía el scroll; ahora cada sección es su página)
function openPrefs(sec) {
  lib.prefSec = sec;
  setView("prefs");
  renderPrefs();
}

// Apariencia: el modo, con íconos.
function appearanceRow(p) {
  const choose = (value) => {
    setPref(p.key, value);
    applyTheme();
    renderPrefs();
  };
  const seg = (value, on, ...kids) => el("button", { type: "button", class: "seg" + (on ? " on" : ""), on: { click: () => choose(value) } }, ...kids);
  if (p.key === "theme_mode") {
    const icons = { sistema: "monitor", claro: "sun", oscuro: "moon" };
    return el("div", { class: "segs" }, ...p.options.map(([v, t]) => seg(v, prefs.theme_mode === v, icon(icons[v]), t)));
  }
  return null;
}

$("#prefs-btn").addEventListener("click", () => togglePrefs());
