/* =====================================================================
   El agente del video (pestaña lateral; vt/agentsvc.py en el servidor).
   Conversa sobre el video abierto con un modelo local: sabe lo que se dice, lo que se ve y hasta dónde
   vas. Cada [m:ss] de sus respuestas es un botón que lleva a ese momento. Las sugerencias cambian según
   el video; «Generar el resumen» pide el resumen de siempre (web/js/summary.js), que queda arriba.
   Se personaliza en Ajustes › Agente: nombre, avatar, color y cómo responde.
   ===================================================================== */

state.agent = { messages: [], suggestions: [], pending: null, status: null, video: null, power: "apagado", model: "" };
const AGENT_STEP = { descargando: () => t("Descargando"), cargando: () => t("Cargando el modelo"), pensando: () => t("Preparando la respuesta"),
  buscando: () => t("Buscando en el video"), leyendo: () => t("Leyendo el video"), escribiendo: () => t("Escribiendo") };

const agentName = () => (prefs.agent_name || "").trim() || "Translay";
// cómo está el agente según su modelo: «sleep» apagado, «wake» mientras se enciende (al tocar Encender o al
// preguntar con el modelo apagado), «» despierto
let agentMoodFixed = null;  // la vista previa: su agente de ejemplo está siempre despierto
function agentMood() {
  if (agentMoodFixed !== null) return agentMoodFixed;
  const a = state.agent, st = a.status?.state;
  if (["descargando", "cargando"].includes(st) || (a.waking && a.power === "apagado")) return "wake";
  if (a.power === "apagado" && !a.pending) return "sleep";
  return "";
}

// el personaje del agente (web/js/star.js); state: "think" mientras piensa, "talk" mientras escribe
function agentAvatar(state = "") {
  const a = el("span", { class: "ag-avatar star" }, starSvg(agentLook(), null, state));
  if (prefs.agent_color) a.style.setProperty("--ag", prefs.agent_color);
  return a;
}

// la pestaña lleva el nombre del agente
function agentTabLabel() {
  const b = $('#side-tabs [data-tab="summary"]');
  if (b) b.textContent = agentName();
}

function agentOpen() {
  if (!state.videoId) return;
  if (state.agent.video !== state.videoId) {
    state.agent = { messages: [], suggestions: [], pending: null, status: null, video: state.videoId };
    renderAgent();
  }
  send({ type: "agent_open", video: state.videoId, position: vEn.currentTime || 0 });
}

/* ------------------------------------------------------------ texto de las respuestas
   Markdown sencillo, armado con nodos (nunca innerHTML con lo que escribe el modelo): párrafos, viñetas,
   listas numeradas, **negritas**, `código`, bloques ``` con colores y [m:ss] como botones. */
const STAMP_RE = /\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]/g;

function inline(text) {
  const frag = document.createDocumentFragment();
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    frag.append(text.slice(last, m.index));
    if (m[1] != null) frag.append(el("strong", { text: m[1] }));
    else if (m[2] != null) frag.append(el("code", { class: "ag-code", text: m[2] }));
    else {
      const sec = m[5] != null ? +m[3] * 3600 + +m[4] * 60 + +m[5] : +m[3] * 60 + +m[4];
      frag.append(el("button", { type: "button", class: "ag-ts", "data-t": sec, title: t("Ir a este momento") }, fmt(sec)));
    }
    last = m.index + m[0].length;
  }
  frag.append(text.slice(last));
  return frag;
}

function richText(text) {
  const box = el("div", { class: "ag-text" });
  const lines = text.replace(/\r/g, "").split("\n");
  let list = null, code = null;
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      if (code) { box.append(code); code = null; } else { code = el("pre", { class: "codeblk" }); code._t = ""; }
      continue;
    }
    if (code) { code.append(highlight((code.childNodes.length ? "\n" : "") + line)); continue; }
    const item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (item) {
      const ordered = /^\s*\d/.test(line);
      if (!list || list.tagName !== (ordered ? "OL" : "UL")) { list = el(ordered ? "ol" : "ul"); box.append(list); }
      list.append(el("li", {}, inline(item[1])));
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const h = line.match(/^\s*#{1,4}\s+(.*)$/);
    box.append(h ? el("p", { class: "ag-h" }, inline(h[1])) : el("p", {}, inline(line)));
  }
  if (code) box.append(code);  // se está escribiendo: el bloque aún sin cerrar
  return box;
}

/* ------------------------------------------------------------ encendido
   Apagado: el modelo no ocupa memoria (también entra solo en reposo tras 5 min sin preguntas). Las
   sugerencias funcionan igual: al tocar una, se enciende y responde. «Encender» lo carga y lee el
   video de antemano, así la primera pregunta sale al instante. */
// la barra (avatar, nombre, estado, encender y personalizar); sin acciones, sus botones solo se muestran
function agentBarNodes(v) {
  const on = v.power === "encendido";
  const label = v.busy ? v.statusText : on ? (v.model ? t("Encendido · {model}", { model: v.model }) : t("Encendido")) : t("Apagado");
  const dot = el("i", { class: "ag-dot " + (v.busy ? "busy" : on ? "on" : "off") });
  const b = el("button", { type: "button", class: "btn xs ghost ag-power", disabled: v.busy || v.canPower === false || null,
    title: on ? t("Apagar y liberar memoria") : t("Encender y preparar el video"),
    on: v.onPower ? { click: () => v.onPower(!on) } : {} }, icon("power"), on ? t("Apagar") : t("Encender"));
  const custom = v.custom ? el("button", { type: "button", class: "btn xs ghost icon ag-custom", title: t("Personalizar el agente"),
    "aria-label": t("Personalizar el agente"), on: v.onCustom ? { click: v.onCustom } : {} }, icon("brush")) : null;
  return [agentAvatar(v.mood ?? (v.busy ? "think" : "")), el("span", { class: "ag-name", text: agentName() }), el("span", { class: "ag-status" }, dot, label), b, custom];
}

function renderAgentBar() {
  const a = state.agent;
  $("#ag-bar").replaceChildren(...agentBarNodes({
    mood: agentMood() || (a.pending || (a.status && !["listo", undefined].includes(a.status.state)) ? "think" : ""),
    power: a.power, model: a.model, busy: a.power === "ocupado" || (a.status && !["listo", undefined].includes(a.status.state)),
    statusText: agentStatusText(), canPower: canImport(), custom: isOwner(), onCustom: openAgentDlg,
    onPower: (on) => {
      if (on) { a.waking = true; renderAgent(); }  // se despierta ya, sin esperar al servidor
      send({ type: "agent_power", video: state.videoId, on, position: vEn.currentTime || 0 });
    } }));
}

function agentColor(node) {
  if (prefs.agent_color) node.style.setProperty("--ag", prefs.agent_color);
  else node.style.removeProperty("--ag");
}

/* ------------------------------------------------------------ vista previa
   El panel del agente (web/js/agentview.js) lleno con un video de ejemplo: el resumen con capítulos,
   conceptos y recursos, dos preguntas y las sugerencias. Está en Personalizar y en Ajustes › Agente, al
   lado de las opciones, y cambia con cada una (el tono no se puede mostrar sin el modelo). */
const PREVIEW_SUMMARY = {
  overview: t("Un curso corto de Python: cómo instalar un paquete, leer un archivo de configuración y probar que todo funciona."),
  takeaways: [t("Instala los paquetes con pip dentro de un entorno virtual"), t("Guarda la configuración en un archivo JSON aparte")],
  chapters: [{ t: 134, title: t("Instalar el paquete"), points: [
    { t: 134, text: t("Abre la terminal e instala requests con pip") },
    { t: 185, text: t("Comprueba la versión instalada") }] }],
  points: [],
  terms: [{ t: 210, term: t("Entorno virtual"), meaning: t("Una carpeta con su propio Python y paquetes, aparte del sistema.") }],
  resources: [{ kind: "command", text: "$ pip install requests", t: 140 }, { kind: "link", text: "https://docs.python.org/3/", t: 302 }],
};
i18nTrack(PREVIEW_SUMMARY);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const PREVIEW_MESSAGES = [
  { role: "user", content: t("¿En qué minuto explica cómo instalar el paquete?") },
  { role: "assistant", content: t("[2:14] Lo explica aquí: abre la terminal y escribe `pip install requests`. Después, en [3:05], muestra cómo comprobar que quedó instalado.") },
  { role: "user", content: t("¿Qué comandos se usan?") },
  { role: "assistant", content: t("Dos, los dos en la terminal:\n- [2:20] `pip install requests` instala el paquete.\n- [3:05] `pip show requests` muestra la versión.\n```\n$ pip install requests\n$ pip show requests\n```") },
];
i18nTrack(PREVIEW_MESSAGES);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const PREVIEW_SUGGESTIONS = [{ q: t("¿Qué hace la función load?") }, { q: t("¿Qué me falta por ver?") }];
i18nTrack(PREVIEW_SUGGESTIONS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

function agentPreview() {
  const P = agentPanel();
  P.root.classList.add("ag-preview");
  P.root.setAttribute("aria-label", t("Vista previa"));
  P.root._panel = P;
  P.summary.append(summaryCard(PREVIEW_SUMMARY));
  fillSuggestions(P.suggest, PREVIEW_SUGGESTIONS);
  P.input.readOnly = true;
  P.input.tabIndex = -1;
  P.form.addEventListener("submit", (e) => e.preventDefault());
  fillAgentPreview(P);
  return P.root;
}

// lo que cambia con la personalización, sobre el mismo panel: no se rehace, así no sube al cambiar algo
function fillAgentPreview(P) {
  agentColor(P.root);
  P.bar.replaceChildren(...agentBarNodes({ power: "encendido", model: "", custom: true, mood: "" }));
  fillAgentIntro(P.intro, "");
  agentMoodFixed = "";
  try { fillAgentMessages(P.msgs, PREVIEW_MESSAGES, null); } finally { agentMoodFixed = null; }
}

function refreshAgentPreviews() {
  document.querySelectorAll(".ag-preview").forEach((n) => n._panel && fillAgentPreview(n._panel));
}

/* ------------------------------------------------------------ personalizar sin salir del video
   Las mismas opciones de Ajustes › Agente (nombre, avatar, color y cómo responde), con los mismos
   controles; cada cambio se ve al instante en la conversación. El modelo y dónde corre, en «Más ajustes». */
const AGENT_DLG_KEYS = ["agent_name", "agent_avatar", "agent_color", "agent_tone"];

function renderAgentDlg() {
  const rows = AGENT_DLG_KEYS.map((k) => prefsSchema.find((p) => p.key === k)).filter(Boolean).map((p) =>
    el("div", { class: "set-row" + (p.type === "text" && p.multiline ? " wide" : "") },
      el("div", { class: "set-text" }, el("strong", { text: p.label })),
      el("div", { class: "set-ctl" }, prefControl(p))));
  $("#agent-dlg-rows").replaceChildren(...rows);
  const side = $("#agent-dlg-preview");
  if (side.firstChild) refreshAgentPreviews(); else side.append(agentPreview());  // la misma, no una nueva
}

function openAgentDlg() {
  renderAgentDlg();
  const dlg = $("#agent-dlg");
  dlg.showModal();
  dlg.addEventListener("close", () => {
    document.activeElement?.blur?.();  // guarda el texto que se estaba escribiendo
    if (dlg.returnValue === "more") { openPrefs("agente"); }
    renderAgent();
  }, { once: true });
}

// al elegir un avatar o un color, el diálogo y la conversación se redibujan (los textos se guardan solos)
$("#agent-dlg-rows").addEventListener("click", (e) => {
  if (e.target.closest("button")) setTimeout(() => { renderAgentDlg(); renderAgent(); });
});
$("#agent-dlg-rows").addEventListener("input", (e) => {
  if (e.target.closest(".pref-text")) setTimeout(renderAgent, 800);
});

/* ------------------------------------------------------------ dibujo */
function renderAgent() {
  agentTabLabel();
  const box = $("#summary");
  if (!box) return;
  agentColor(box);  // burbujas, minutos y avatar con el color del agente (también los del resumen)
  if (box.hidden) return;
  const a = state.agent;
  renderAgentBar();
  const sc = $("#ag-scroll");
  const intro = $("#ag-intro");
  fillAgentIntro(intro);
  // sin conversación ni resumen: el agente grande en el centro, con lo que sabe hacer debajo
  const empty = !a.messages.length && !a.pending && !$("#ag-summary")?.childElementCount;
  const wasEmpty = sc.classList.contains("is-empty");
  const from = wasEmpty && !empty ? intro.querySelector(".agent-star")?.getBoundingClientRect() : null;
  sc.classList.toggle("is-empty", empty);
  fillAgentMessages($("#ag-msgs"), a.messages, a.pending);
  renderSuggestions();
  syncSendBtn();
  agentStickBottom(sc);
  if (from) agentFly(from, intro);
}

// baja al final si la persona no subió a leer; marca que el movimiento es del chat, no suyo
function agentStickBottom(sc = $("#ag-scroll")) {
  if (state.agent.stick === false) return;
  sc.dataset.auto = "1";
  sc.scrollTop = sc.scrollHeight;
  requestAnimationFrame(() => { delete sc.dataset.auto; });
}

// mientras escribe: solo cambia el texto de la respuesta en curso (redibujar toda la conversación con cada palabra
// movía el scroll y no dejaba subir a leer: «vibraba»)
function renderPendingText() {
  const a = state.agent;
  const li = $("#ag-msgs .ag-msg.bot.pending");
  if (!li || !a.pending) return false;
  const who = li.querySelector(".ag-who");
  li.replaceChildren(who, richText(a.pending.text), ...[...li.children].filter((x) => x.classList.contains("ag-card")));
  who.querySelector(".agent-star")?.setAttribute("class", "agent-star talk");
  agentStickBottom();
  return true;
}

// la primera pregunta: el agente vuela del centro a su lugar en la respuesta; el del inicio queda guardado hasta
// que se vuelva a subir hasta arriba
function agentFly(from, intro) {
  const target = [...document.querySelectorAll("#ag-msgs .ag-msg.bot .ag-avatar")].pop();
  intro.classList.add("dormant");
  if (!target || !from.width || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const to = target.getBoundingClientRect();
  const ghost = el("div", { class: "ag-fly" }, starSvg(agentLook(), null, "think"));
  Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` });
  document.body.append(ghost);
  const sc = $("#ag-scroll");
  sc.classList.add("ag-flying");  // la respuesta puede redibujarse mientras vuela: se esconde por clase, no por nodo
  const dx = to.left - from.left, dy = to.top - from.top, k = to.width / from.width;
  ghost.animate([{ transform: "none" }, { transform: `translate(${dx}px, ${dy}px) scale(${k})` }],
    { duration: 520, easing: "cubic-bezier(.5, 0, .2, 1)", fill: "forwards" }).onfinish = () => {
    sc.classList.remove("ag-flying");
    ghost.remove();
  };
}

// el botón de enviar: detener mientras responde (si no hay nada escrito); si hay, preguntar (queda en cola)
function syncSendBtn() {
  const a = state.agent;
  const busy = !!a.pending && !$("#ag-input").value.trim();
  const sendBtn = $("#ag-send");
  sendBtn.replaceChildren(icon(busy ? "stop" : "up"));
  sendBtn.setAttribute("aria-label", busy ? t("Detener") : t("Preguntar"));
  sendBtn.title = busy ? t("Detener la respuesta") : t("Preguntar (Enter)");
  sendBtn.classList.toggle("stop", busy);
  if (a.pending && !busy) sendBtn.title = t("Preguntar al terminar (queda en cola)");
}

// lo que el agente sabe hacer, como chips: los marcados con true dejan la pregunta empezada en la caja
// para completarla; los demás preguntan al tocarlos
const AGENT_CAN = [
  ["clock", t("Encontrar un momento"), t("¿En qué minuto"), true],
  ["book", t("Explicar un concepto"), t("Explícame"), true],
  ["play", t("Lo que me falta"), t("¿Qué me falta por ver?")],
  ["code", t("Código y comandos"), t("¿Qué código y comandos aparecen y para qué sirve cada uno?")],
  ["cap", t("Preguntas de repaso"), t("Hazme 3 preguntas de repaso sobre lo que ya vi.")],
  ["globe", t("Qué significa una palabra"), t("¿Qué significa"), true],
];
i18nTrack(AGENT_CAN);  // al cambiar de idioma, sus textos también cambian (i18n.js)

function agentCan(q, open) {
  if (!open) { agentAsk(q); return; }
  const f = $("#ag-input");
  f.value = q + " ";
  fitAgentInput();
  f.focus();
  f.setSelectionRange(f.value.length, f.value.length);
}

// el agente al inicio del chat: su estrella grande y su nombre. Se redibuja solo si cambió cómo se ve (así no
// repite la entrada con cada mensaje)
function fillAgentIntro(box, mood = agentMood()) {
  if (!box) return;
  const key = JSON.stringify(agentLook()) + (prefs.agent_color || themeStarColor());
  box.querySelector(".ag-intro-name").textContent = agentName();
  if (box.dataset.key === key) {
    if (box.dataset.mood !== mood) {
      box.dataset.mood = mood;
      box.querySelector(".agent-star")?.setAttribute("class", ("agent-star " + mood).trim());
      // al apagarse (o despertar) vuelve a asomarse entero con su nuevo gesto, también si estaba guardado tras la
      // primera pregunta: antes quedaba escondido y solo se veían las «z»
      if (box.classList.contains("dormant") || box.classList.contains("peek")) {
        box.classList.remove("dormant", "peek");
        void box.offsetWidth;
        box.classList.add("peek");
      }
    }
    return;
  }
  box.dataset.key = key;
  box.querySelector(".ag-peek").replaceChildren(starSvg(agentLook()));
  box.dataset.mood = mood;
  box.querySelector(".agent-star")?.setAttribute("class", ("agent-star " + mood).trim());
  box.classList.add("has-star");
  // estaba oculto (sin estrella): se vuelve a observar para que se asome apenas se ve
  // (las vistas previas se llenan antes de entrar en la página: se espera a que estén)
  let tries = 0;
  const reobserve = () => {
    if (!box.isConnected) { if (++tries < 60) requestAnimationFrame(reobserve); return; }
    agentIntroSeen.unobserve(box);
    agentIntroSeen.observe(box);
  };
  requestAnimationFrame(reobserve);
}
// la conversación (con lo que puede hacer si aún no hay preguntas)
function fillAgentMessages(ol, messages, pending) {
  const frag = document.createDocumentFragment();
  if (!messages.length && !pending) {
    frag.append(el("li", { class: "ag-hello" }, el("div", { class: "ag-can" }, ...AGENT_CAN.map(([ic, label, q, open]) =>
      el("button", { type: "button", class: "ag-chip", title: q, on: { click: () => agentCan(q, open) } }, icon(ic), label)))));
  }
  messages.forEach((m, i) => frag.append(agentMessage(m, i)));
  if (pending) frag.append(agentMessage({ role: "assistant", content: pending.text, pending: true, steps: pending.steps }, -1));
  if (ol.id === "ag-msgs") {
    (state.agent.queue || []).forEach((q, i) => frag.append(el("li", { class: "ag-msg user queued" },
      el("p", { text: q }),
      el("span", { class: "ag-queued" }, icon("clock"), t("En cola"),
        el("button", { type: "button", class: "ag-copy", title: t("Quitar de la cola"), "aria-label": t("Quitar de la cola"),
          on: { click: () => { state.agent.queue.splice(i, 1); renderAgent(); } } }, icon("x"))))));
  }
  ol.replaceChildren(frag);
}

// la hora de un mensaje (los guardados traen t en segundos)
const msgTime = (t) => (t ? new Date(t * 1000).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" }) : "");

// copiar un mensaje: el botón aparece al pasar el mouse, junto a su hora
function msgTools(m) {
  return el("span", { class: "ag-tools" },
    m.t ? el("time", { text: msgTime(m.t) }) : null,
    m.content ? el("button", { type: "button", class: "ag-copy", title: t("Copiar"), "aria-label": t("Copiar el mensaje"),
      on: { click: () => copyText(m.content, t("Mensaje copiado")) } }, icon("copy")) : null);
}

// mientras trabaja: cada paso (buscar, leer, escribir) con su marca; el actual con los puntitos
function agentSteps(steps) {
  if (!steps?.length) return null;
  return el("ol", { class: "ag-steps" }, ...steps.map((s, i) => el("li", { class: i === steps.length - 1 ? "now" : "done" },
    i === steps.length - 1 ? el("i", { class: "ag-dots" }, el("b"), el("b"), el("b")) : icon("check"), s)));
}

/* ------------------------------------------------------------ tarjetas de las acciones (vt/agentintents.py) */
function agentCard(c) {
  if (!c) return null;
  if (c.type === "export") {
    const pre = el("pre", { class: "ag-card-pre", text: c.content.split("\n").slice(0, 14).join("\n") + "\n…" });
    const download = () => {
      const a = el("a", { href: URL.createObjectURL(new Blob([c.content], { type: "text/markdown" })), download: c.file || "video.md" });
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    };
    return el("div", { class: "ag-card" },
      el("div", { class: "ag-card-head" }, icon("agent"), el("strong", { text: c.title }),
        el("small", { text: t("{n} mil caracteres", { n: Math.round(c.content.length / 1000) || 1 }) })),
      pre,
      el("div", { class: "ag-card-acts" },
        btn(t("Copiar"), { icon: "copy", size: "sm", variant: "dark", onClick: () => copyText(c.content, t("Contenido copiado")) }),
        btn(t("Descargar .md"), { icon: "download", size: "sm", variant: "ghost", onClick: download })));
  }
  if (c.type === "moment") {
    return el("div", { class: "ag-card" },
      el("button", { type: "button", class: "ag-card-moment", on: { click: () => { vEn.currentTime = c.t; if (vEn.paused) togglePlay(); } } },
        el("b", { class: "ag-ts", text: fmt(c.t) }), el("span", { text: c.text || t("Ir a este momento") })));
  }
  if (c.type === "alert") {
    const active = state.alerts?.[state.videoId]?.topic === c.topic;
    return el("div", { class: "ag-card" },
      el("div", { class: "ag-card-head" }, icon("bell"), el("strong", { text: t("Aviso: {topic}", { topic: c.topic }) }),
        el("small", { text: c.times.length === 1 ? t("1 momento") : t("{n} momentos", { n: c.times.length }) })),
      el("div", { class: "ag-card-times" }, ...c.times.map((x) => el("button", { type: "button", class: "ag-ts", title: x.text,
        on: { click: () => { vEn.currentTime = x.t; } } }, fmt(x.t)))),
      el("div", { class: "ag-card-acts" }, active
        ? btn(t("Quitar aviso"), { icon: "x", size: "sm", variant: "ghost", onClick: () => { setAlert(null); renderAgent(); } })
        : btn(t("Volver a avisarme"), { icon: "bell", size: "sm", variant: "ghost", onClick: () => { setAlert(c); renderAgent(); } })));
  }
  return null;
}

/* ------------------------------------------------------------ las acciones: las hace la vista */
function agentAction(a) {
  if (!a) return;
  if (a.type === "seek") { vEn.currentTime = a.t; if (vEn.paused) togglePlay(); }
  else if (a.type === "subs") {
    if (a.value === "off") { setPref("sub_es", false); setPref("sub_orig", false); }
    else { setPref("sub_es", a.value === "es"); setPref("sub_orig", a.value === "en"); }
    applySubs();
  } else if (a.type === "save") {
    const want = a.collection.toLowerCase();
    const c = lib.collections.find((x) => x.kind === "propia" && x.name.toLowerCase() === want)
      || lib.collections.find((x) => x.kind === "propia" && x.name.toLowerCase().includes(want));
    if (c) { if (!c.items.includes(state.videoId)) send({ type: "coll_toggle", coll: c.id, video: state.videoId, on: true }); toast(t("Guardado en «{name}»", { name: c.name }), "ok"); }
    else { send({ type: "coll_create", name: a.collection, video: state.videoId }); toast(t("Colección «{name}» creada con este video", { name: a.collection }), "ok"); }
  } else if (a.type === "alert") setAlert(a);
}

/* ------------------------------------------------------------ avisos mientras ves
   Los momentos se marcan en la barra de avance; al llegar a cada uno aparece un aviso (y uno del sistema si
   están activadas las notificaciones). Uno por video, mientras la pestaña está abierta. */
state.alerts = {};
function setAlert(a) {
  if (!state.videoId) return;
  if (a) state.alerts[state.videoId] = { topic: a.topic, times: a.times, fired: new Set() };
  else delete state.alerts[state.videoId];
  drawAlerts();
}
function drawAlerts() {
  let box = $("#t-alerts");
  if (!box) { box = el("div", { class: "t-alerts", id: "t-alerts" }); $("#track")?.append(box); }
  const a = state.alerts[state.videoId];
  const d = vEn.duration || 0;
  box.replaceChildren(...(a && d ? a.times.map((x) => el("i", { style: `left: ${(x.t / d) * 100}%`, title: `${fmt(x.t)} · ${a.topic}` })) : []));
}
vEn.addEventListener("loadedmetadata", drawAlerts);
vEn.addEventListener("timeupdate", () => {
  const a = state.alerts?.[state.videoId];
  if (!a || vEn.paused) return;
  const now = vEn.currentTime;
  const hit = a.times.find((x) => !a.fired.has(x.t) && now >= x.t && now < x.t + 3);
  if (!hit) return;
  a.fired.add(hit.t);
  toast(t("Ahora: {topic} · {text}", { topic: a.topic, text: hit.text.slice(0, 80) }), "ok");
  if (prefs.notify && document.hidden && typeof notifyUser === "function") notifyUser(t("Ahora: {topic}", { topic: a.topic }), hit.text.slice(0, 120));
});

function agentMessage(m, i) {
  if (m.role === "user") return el("li", { class: "ag-msg user", "data-i": i }, el("p", {}, inline(m.content)), msgTools(m));
  const body = m.content ? richText(m.content) : !m.pending ? null : el("div", { class: "ag-text" },
    agentSteps(m.steps) || el("p", { class: "ag-wait" }, el("i", { class: "ag-dots" }, el("b"), el("b"), el("b")), agentStatusText()));
  const li = el("li", { class: "ag-msg bot" + (m.pending ? " pending" : ""), "data-i": i },
    el("div", { class: "ag-who" }, agentAvatar(m.pending ? (m.content ? "talk" : agentMood() === "wake" ? "wake" : "think") : agentMood()), el("span", { class: "ag-name", text: agentName() }), m.pending ? null : msgTools(m)),
    body, agentCard(m.card));
  if (!m.pending) {
    // completado: un check verde se entiende sin leer; al lado, el modelo y cuánto tardó
    const secs = m.stats?.total_s ?? m.s;
    const model = m.stats?.model || (m.model && m.model !== "acción" ? (state.agentModels?.models.find((x) => x.key === m.model)?.name || "") : "");
    // detenida: sin el check, con la marca de detener (lo escrito hasta ahí queda)
    li.append(el("p", { class: "ag-meta" + (m.fresh ? " fresh" : "") + (m.stopped ? " stopped" : ""), title: m.stopped ? t("Detenida") : t("Completado") },
      el("span", { class: "ag-ok" }, icon(m.stopped ? "stop" : "check")),
      [m.stopped ? t("Detenida") : "", model, secs != null && secs > 0 ? `${Number(secs).toFixed(1)} s` : ""].filter(Boolean).join(" · "),
      // la última detenida se puede seguir desde donde quedó
      m.stopped && i === state.agent.messages.length - 1 && !state.agent.pending
        ? el("button", { type: "button", class: "ag-continue", on: { click: agentContinue } }, icon("play"), t("Continuar")) : null));
  }
  return li;
}

function agentStatusText() {
  const s = state.agent.status;
  if (!s || s.state === "listo") return t("Pensando");
  const step = AGENT_STEP[s.state]?.() || t("Pensando");
  return s.state === "descargando" ? `${step} ${s.detail} · ${s.pct || 0} %` : s.detail && s.state === "cargando" ? `${step} (${s.detail})` : step;
}

// las sugerencias; sin onPick solo se muestran
function fillSuggestions(box, list, onPick) {
  box.replaceChildren(...list.map((s) => el("button", { type: "button", class: "ag-chip" + (s.action ? " action" : ""),
    on: onPick ? { click: () => onPick(s) } : {} }, icon(s.action === "summary" ? "lines" : "spark"), s.q)));
  box.hidden = !list.length;
}

function renderSuggestions() {
  const a = state.agent;
  // «Resumir» solo a quien puede pedirlo (al invitado que solo ve, el servidor se lo niega)
  const list = a.pending ? [] : (a.suggestions || []).filter((s) => !(s.action === "summary" && (state.summary || state.summaryJob || !canImport())));
  fillSuggestions($("#ag-suggest"), list, (s) => (s.action === "summary" ? requestSummary() : agentAsk(s.q)));
}

/* ------------------------------------------------------------ preguntar */
function agentAsk(q) {
  q = (q || "").trim();
  if (!q || !state.videoId) return;
  if (state.agent.mention != null) {  // el momento mencionado va delante: «[1:23] ¿qué dice aquí?»
    q = `[${fmt(state.agent.mention)}] ${q}`;
    state.agent.mention = null;
    renderMention();
  }
  if (state.agent.pending) {  // está respondiendo: la pregunta espera su turno
    (state.agent.queue ||= []).push(q);
    state.agent.stick = true;
    renderAgent();
    return;
  }
  if (state.agent.power === "apagado") state.agent.waking = true;  // empieza a despertar mientras carga el modelo
  const id = Math.random().toString(36).slice(2, 10);
  state.agent.messages.push({ role: "user", content: q, t: Date.now() / 1000 });
  state.agent.pending = { id, text: "", steps: [] };
  state.agent.stick = true;
  send({ type: "agent_ask", video: state.videoId, q, position: vEn.currentTime || 0, id });
  renderAgent();
}

// «Continuar»: la respuesta detenida sigue desde donde quedó (lo escrito se queda a la vista mientras tanto)
function agentContinue() {
  const a = state.agent;
  const last = a.messages.at(-1);
  if (!last?.stopped || a.pending || !state.videoId) return;
  const id = Math.random().toString(36).slice(2, 10);
  a.messages.pop();
  a.pending = { id, text: last.content || "", steps: [] };
  a.stick = true;
  send({ type: "agent_continue", video: state.videoId, position: vEn.currentTime || 0, id });
  renderAgent();
}

$("#ag-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = $("#ag-input");
  // respondiendo y sin nada escrito: el botón detiene; con algo escrito, lo pone en cola
  if (state.agent.pending && !f.value.trim()) {  // detener: se ve al instante, aunque el modelo tarde en soltar
    send({ type: "agent_stop", video: state.videoId });
    const p = state.agent.pending;
    const stopping = t("Deteniendo");
    if ((p.steps ||= []).at(-1) !== stopping) p.steps.push(stopping);
    renderAgent();
    return;
  }
  agentAsk(f.value);
  f.value = "";
  fitAgentInput();
});
$("#ag-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#ag-form").requestSubmit(); }
});
function fitAgentInput() {
  const f = $("#ag-input");
  f.style.height = "auto";
  f.style.height = Math.min(140, f.scrollHeight) + "px";
}
$("#ag-input").addEventListener("input", () => { fitAgentInput(); syncSendBtn(); });

/* ------------------------------------------------------------ mencionar un momento
   Desde el clic derecho en la barra de avance: el momento queda como una píldora sobre la caja (con su X) y
   la próxima pregunta va sobre él. */
function agentMention(t) {
  state.agent.mention = t;
  if (typeof setSide === "function") setSide(true);
  $('#side-tabs [data-tab="summary"]')?.click();
  renderMention();
  $("#ag-input").focus();
}
function renderMention() {
  const form = $("#ag-form");
  let box = form.querySelector(".ag-mention");
  const at = state.agent.mention;
  if (at == null) { box?.remove(); return; }
  if (!box) { box = el("div", { class: "ag-mention" }); form.prepend(box); }
  box.replaceChildren(el("span", { class: "ag-ts", title: t("Ir a este momento"), on: { click: () => { vEn.currentTime = at; } } }, fmt(at)),
    el("small", { text: t("Pregunta sobre este momento") }),
    el("button", { type: "button", class: "ag-copy", title: t("Quitar"), "aria-label": t("Quitar el momento"),
      on: { click: () => { state.agent.mention = null; renderMention(); } } }, icon("x")));
}

/* ------------------------------------------------------------ dictar
   El micrófono graba en el navegador (opus) hasta que lo vuelves a tocar (o un minuto); el servidor lo
   transcribe con el Whisper de Translay y el texto queda en la caja, para revisarlo antes de preguntar. */
const DICTATE_MAX_MS = 60_000;
const dictation = { rec: null, chunks: [], timer: 0, id: "", busy: false };

function dictationUI() {
  const b = $("#ag-mic"), f = $("#ag-input");
  const recording = !!dictation.rec;
  b.classList.toggle("on", recording);
  b.classList.toggle("busy", dictation.busy);
  b.disabled = dictation.busy;
  b.replaceChildren(icon(recording ? "stop" : "mic"));
  b.setAttribute("aria-label", recording ? t("Terminar de dictar") : t("Dictar"));
  b.title = recording ? t("Terminar de dictar") : t("Dictar");
  f.placeholder = recording ? t("Escuchando…")
    : dictation.busy ? t("Transcribiendo…") : t("Pregunta sobre este video");
}

async function startDictation() {
  if (dictation.rec || dictation.busy || !state.videoId) return;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    toast(t("No se pudo acceder al micrófono. Revisa los permisos."));
    return;
  }
  const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find((t) => MediaRecorder.isTypeSupported(t));
  const rec = new MediaRecorder(stream, type ? { mimeType: type, audioBitsPerSecond: 32000 } : {});
  dictation.chunks = [];
  rec.ondataavailable = (e) => { if (e.data.size) dictation.chunks.push(e.data); };
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    clearTimeout(dictation.timer);
    dictation.rec = null;
    const blob = new Blob(dictation.chunks, { type: rec.mimeType || "audio/webm" });
    if (blob.size < 1000) { dictationUI(); return; }  // un toque sin hablar
    dictation.busy = true;
    dictation.id = Math.random().toString(36).slice(2, 10);
    dictationUI();
    const b64 = await new Promise((ok) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result).split(",")[1] || "");
      r.readAsDataURL(blob);
    });
    send({ type: "agent_dictate", video: state.videoId, audio: b64, id: dictation.id });
  };
  dictation.rec = rec;
  rec.start();
  dictation.timer = setTimeout(stopDictation, DICTATE_MAX_MS);
  dictationUI();
}

function stopDictation() {
  if (dictation.rec && dictation.rec.state !== "inactive") dictation.rec.stop();
}

function dictated(m) {
  if (m.id && m.id !== dictation.id) return;
  dictation.busy = false;
  dictationUI();
  if (m.error) { toast(m.error); return; }
  if (!m.text) { toast(t("No se detectó voz. Acércate al micrófono e inténtalo de nuevo.")); return; }
  const f = $("#ag-input");
  f.value = (f.value.trim() ? f.value.trimEnd() + " " : "") + m.text;
  fitAgentInput();
  f.focus();
  f.setSelectionRange(f.value.length, f.value.length);
}

$("#ag-mic").addEventListener("click", () => (dictation.rec ? stopDictation() : startDictation()));
$("#ag-scroll").addEventListener("scroll", () => {
  const sc = $("#ag-scroll");
  if (sc.dataset.auto) return;  // lo movió el chat al llegar texto nuevo
  state.agent.stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 40;  // si subes a leer, no te baja
});
// subir con la rueda, el dedo o el teclado suelta el final al instante (sin esperar a alejarse 40 px)
$("#ag-scroll").addEventListener("wheel", (e) => { if (e.deltaY < 0) state.agent.stick = false; }, { passive: true });
$("#ag-scroll").addEventListener("touchmove", () => { const sc = $("#ag-scroll"); if (sc.scrollHeight - sc.scrollTop - sc.clientHeight > 4) state.agent.stick = false; }, { passive: true });
$("#ag-scroll").addEventListener("keydown", (e) => { if (["ArrowUp", "PageUp", "Home"].includes(e.key)) state.agent.stick = false; });

$("#ag-msgs").addEventListener("click", (e) => {
  const b = e.target.closest(".ag-ts");
  if (b) { vEn.currentTime = +b.dataset.t; if (vEn.paused) togglePlay(); }
});

/* ------------------------------------------------------------ del servidor */
function agentEvent(m) {
  const a = state.agent;
  if (m.type === "agent_power") {
    a.power = m.state;
    if (m.state !== "apagado") a.waking = false;
    if (m.model) a.model = m.model;
  } else if (m.type === "agent_chat") {
    if (m.video !== state.videoId) return;
    a.video = m.video;
    a.messages = m.messages || [];
    a.suggestions = m.suggestions || [];
    a.status = m.state;
    a.power = m.power || a.power;
    a.model = m.model || a.model;
  } else if (m.type === "agent_state") {
    a.status = m;
    // los pasos de la respuesta en curso (buscar, leer, escribir…), sin repetir el último
    const label = AGENT_STEP[m.state] && m.state !== "listo" ? AGENT_STEP[m.state]() + (m.detail && m.state === "leyendo" ? ` · ${m.detail}` : "") : "";
    if (a.pending && label && a.pending.steps.at(-1) !== label) a.pending.steps.push(label);
  } else if (m.type === "agent_delta") {
    if (!a.pending) a.pending = { id: m.id, text: "" };
    a.pending.text += m.text;
    if (a.pending.text.length > m.text.length && renderPendingText()) return;  // la primera palabra redibuja todo
  } else if (m.type === "agent_done") {
    a.messages.push({ role: "assistant", content: m.text, stats: m.stats, card: m.card, t: Date.now() / 1000, fresh: true, stopped: m.stopped,
      model: m.card || m.action ? "acción" : undefined });
    a.pending = null;
    a.waking = false;
    agentAction(m.action);  // lo que pidió hacer (ir a un momento, subtítulos, guardar, avisos)
    a.status = null;
    if (a.queue?.length) setTimeout(() => agentAsk(a.queue.shift()), 400);  // la siguiente en la cola
    else send({ type: "agent_open", video: state.videoId, position: vEn.currentTime || 0 });  // sugerencias nuevas
  } else if (m.type === "agent_dictated") {
    dictated(m);
    return;
  } else if (m.type === "agent_error") {
    a.pending = null;
    a.waking = false;
    a.status = null;
    toast(m.error);
    if (a.queue?.length) setTimeout(() => agentAsk(a.queue.shift()), 400);
  }
  renderAgent();
}

// menú del clic derecho sobre un mensaje
function agentMsgMenu(li) {
  const m = state.agent.messages[+li.dataset.i];
  if (!m) return null;
  return [
    { label: t("Copiar"), icon: "copy", onClick: () => copyText(m.content, t("Texto copiado")) },
    m.role === "user" && { label: t("Preguntar de nuevo"), icon: "reload", onClick: () => agentAsk(m.content) },
    "sep",
    { label: t("Borrar la conversación"), icon: "trash", onClick: () => send({ type: "agent_clear", video: state.videoId }) },
    isOwner() && { label: t("Personalizar el agente…"), icon: "brush", onClick: openAgentDlg },  // la misma ventana del pincel
  ];
}
