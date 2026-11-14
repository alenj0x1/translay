/* =====================================================================
   El panel del agente como componente (web/js/agentui.js lo llena).
   agentPanel() arma sus piezas: barra, resumen, conversación, sugerencias y la caja para preguntar.
   La pestaña del video y las vistas previas (Personalizar, Ajustes › Agente) salen de esta misma
   función y se llenan con fillAgentPanel(): lo que se ve en la vista previa es el panel de verdad,
   con datos de ejemplo, no una copia parecida.
   ===================================================================== */

function agentPanel() {
  const bar = el("div", { class: "ag-bar" });
  const summary = el("div", { class: "summary" });
  const msgs = el("ol", { class: "ag-msgs" });
  const scroll = el("div", { class: "ag-scroll" }, summary, msgs);
  const suggest = el("div", { class: "ag-suggest" });
  const input = el("textarea", { class: "area", rows: "1", maxlength: "2000", placeholder: "Pregunta sobre este video",
    "aria-label": "Pregunta" });
  // dictar: solo donde el navegador deja grabar (este equipo, o una conexión segura)
  const mic = el("button", { class: "ic ag-mic", type: "button", "aria-label": "Dictar", title: "Dictar",
    hidden: !(navigator.mediaDevices?.getUserMedia && window.MediaRecorder) || null }, icon("mic"));
  const sendBtn = el("button", { class: "ic", type: "submit", "aria-label": "Preguntar", title: "Preguntar (Enter)" }, icon("up"));
  const form = el("form", { class: "ag-compose" }, input, mic, sendBtn);
  const root = el("div", { class: "agent" }, bar, scroll, suggest, form);
  return { root, bar, scroll, summary, msgs, suggest, form, input, mic, send: sendBtn };
}

// la pestaña del video: el mismo panel, con los id que usa el resto de la app
(() => {
  const P = agentPanel();
  const ids = { bar: "ag-bar", scroll: "ag-scroll", summary: "ag-summary", msgs: "ag-msgs", suggest: "ag-suggest",
    form: "ag-form", input: "ag-input", mic: "ag-mic", send: "ag-send" };
  for (const [k, id] of Object.entries(ids)) P[k].id = id;
  $("#summary").replaceChildren(...P.root.children);
})();
