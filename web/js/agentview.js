/* =====================================================================
   El panel del agente como componente (web/js/agentui.js lo llena).
   agentPanel() arma sus piezas: barra, resumen, conversación, sugerencias y la caja para preguntar.
   La pestaña del video y las vistas previas (Personalizar, Ajustes › Agente) salen de esta misma
   función y se llenan con fillAgentPanel(): lo que se ve en la vista previa es el panel de verdad,
   con datos de ejemplo, no una copia parecida.
   ===================================================================== */

// lo que hace cualquier panel del agente (la pestaña del video y las vistas previas de Personalizar y Ajustes):
// el agente del inicio se asoma cada vez que vuelve a verse (al abrir y al subir hasta arriba)…
const agentIntroSeen = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (e.isIntersecting && e.intersectionRatio >= 0.6) {
      e.target.classList.remove("peek");
      void e.target.offsetWidth;  // reinicia la animación
      e.target.classList.add("peek");
    } else if (!e.isIntersecting) {
      e.target.classList.remove("peek", "dormant");  // al volver a subir, se asoma de nuevo
    }
  }
}, { threshold: [0, 0.6] });
// …y al tocarlo, da un saltito y le salen dos corazones, con la cara que tenga (dormido, pensando…): en la barra,
// al inicio y en sus respuestas
function agentBoop(e) {
  const star = e.target.closest(".agent-star");
  if (!star) return;
  clearTimeout(star._joy);
  star.classList.remove("joy");
  void star.getBoundingClientRect();  // reinicia la animación si se toca seguido
  star.classList.add("joy");
  star._joy = setTimeout(() => star.classList.remove("joy"), 1400);
}

function agentPanel() {
  const bar = el("div", { class: "ag-bar" });
  const summary = el("div", { class: "summary" });
  const msgs = el("ol", { class: "ag-msgs" });
  // arriba de todo, el agente: escondido tras un borde, se asoma al abrir el chat y al volver a subir (agentui.js)
  const intro = el("div", { class: "ag-intro" }, el("div", { class: "ag-peek" }), el("strong", { class: "ag-intro-name" }));
  const scroll = el("div", { class: "ag-scroll" }, intro, summary, msgs);
  const suggest = el("div", { class: "ag-suggest" });
  const input = el("textarea", { class: "area", rows: "1", maxlength: "2000", placeholder: t("Pregunta sobre este video"),
    "aria-label": t("Pregunta") });
  // dictar: solo donde el navegador deja grabar (este equipo, o una conexión segura)
  const mic = el("button", { class: "ic ag-mic", type: "button", "aria-label": t("Dictar"), title: t("Dictar"),
    hidden: !(navigator.mediaDevices?.getUserMedia && window.MediaRecorder) || null }, icon("mic"));
  const sendBtn = el("button", { class: "ic", type: "submit", "aria-label": t("Preguntar"), title: t("Preguntar (Enter)") }, icon("up"));
  const form = el("form", { class: "ag-compose" }, input, mic, sendBtn);
  const root = el("div", { class: "agent" }, bar, scroll, suggest, form);
  agentIntroSeen.observe(intro);
  root.addEventListener("click", agentBoop);
  return { root, bar, scroll, intro, summary, msgs, suggest, form, input, mic, send: sendBtn };
}

// la pestaña del video: el mismo panel, con los id que usa el resto de la app
(() => {
  const P = agentPanel();
  const ids = { bar: "ag-bar", scroll: "ag-scroll", intro: "ag-intro", summary: "ag-summary", msgs: "ag-msgs", suggest: "ag-suggest",
    form: "ag-form", input: "ag-input", mic: "ag-mic", send: "ag-send" };
  for (const [k, id] of Object.entries(ids)) P[k].id = id;
  $("#summary").replaceChildren(...P.root.children);
  $("#summary").addEventListener("click", agentBoop);
})();
