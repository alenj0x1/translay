/* =====================================================================
   Resumen del video abierto (pestaña «Resumen» del panel lateral)
   De qué se trató y sus puntos importantes, cada uno con su minuto (clic: salta
   ahí). Lo hace el servidor (vt/summaries.py): «Resumir» lo pide y el avance
   llega como summary_state; el resultado, como summary.
   ===================================================================== */

state.summary = null;       // {overview, points: [{t, text}], model, created} del video abierto
state.summaryJob = null;    // {state: "en cola"|"descargando"|"resumiendo"|"error", pct, error}

const SUMMARY_STEP = { "en cola": "En cola", descargando: "Descargando el modelo", resumiendo: "Resumiendo" };

function summaryReady() {
  // se resume la transcripción completa: mientras se transcribe, aún no
  const p = lib.videos[state.videoId]?.progress;
  return state.segments.length > 0 && (!p || p.asr >= 0.99);
}

function requestSummary(force = false) {
  if (!state.videoId) return;
  state.summaryJob = { state: "en cola", pct: 0, error: "" };
  send({ type: "summarize", video: state.videoId, force });
  renderSummary();
}

function summaryText() {
  const s = state.summary;
  if (!s) return "";
  const out = [s.overview, ""];
  if (s.takeaways?.length) out.push("Ideas clave", ...s.takeaways.map((t) => `- ${t}`), "");
  if (s.chapters?.length) for (const ch of s.chapters) out.push(`[${fmtDur(ch.t)}] ${ch.title}`, ...ch.points.map((p) => `  [${fmtDur(p.t)}] ${p.text}`), "");
  else out.push(...s.points.map((p) => `[${fmtDur(p.t)}] ${p.text}`), "");
  if (s.terms?.length) out.push("Conceptos clave", ...s.terms.map((x) => `- ${x.term}: ${x.meaning}`), "");
  if (s.resources?.length) out.push("Recursos", ...s.resources.map((r) => `[${fmtDur(r.t)}] ${r.text}`));
  return out.join("\n").trim();
}

function renderSummary() {
  // el resumen es una tarjeta al comienzo de la conversación con el agente (web/js/agentui.js)
  const box = $("#ag-summary");
  if ($("#summary").hidden) return;
  const job = state.summaryJob;
  const s = state.summary;
  const can = canImport();
  if (job && job.state !== "error") {
    const label = `${SUMMARY_STEP[job.state] || "Resumiendo"}${job.state === "en cola" ? "" : ` ${job.pct || 0} %`}`;
    box.replaceChildren(el("div", { class: "sum-card busy" }, el("div", { class: "sum-title" }, icon("lines"), label),
      el("p", { class: "sum-note", text: job.state === "descargando" ? "Solo la primera vez. Después funciona sin conexión."
        : "Puedes seguir viendo el video." }),
      can ? btn("Cancelar", { icon: "x", variant: "ghost", onClick: () => send({ type: "summary_cancel", video: state.videoId }) }) : null));
    return;
  }
  if (!s || s.empty) {
    const err = job?.state === "error" ? job.error : "";
    box.replaceChildren(...(err ? [el("div", { class: "sum-card" }, el("div", { class: "sum-title" }, icon("lines"), "No se pudo resumir"),
      el("p", { class: "sum-note", text: err }), can ? btn("Reintentar", { icon: "reload", variant: "ghost", onClick: () => requestSummary(true) }) : null)] : []));
    return;
  }
  const card = summaryCard(s, box.dataset.closed !== String(s.created));
  card.addEventListener("toggle", () => { box.dataset.closed = card.open ? "" : String(s.created); });
  box.replaceChildren(card);
  box.dataset.shown = String(s.created);
  markSummaryPoint(true);
}

// la tarjeta del resumen (la del video y la de las vistas previas del agente, con un resumen de ejemplo)
function summaryCard(s, open = true) {
  return el("details", { class: "sum-card", open: open ? "" : null },
    el("summary", { class: "sum-title" }, icon("lines"), "Resumen del video", icon("chevron")), ...summaryParts(s));
}

// el contenido de la tarjeta (también la vista previa de Ajustes › Agente, con un resumen de ejemplo)
function summaryParts(s) {
  // versión 2 (vt/digest.py): panorama, ideas, capítulos, conceptos y recursos; la 1 traía solo puntos
  const parts = [el("div", { class: "sum-overview" }, ...s.overview.split(/\n+/).filter(Boolean).map((t) => el("p", { text: t })))];
  if (s.takeaways?.length) {
    parts.push(el("div", { class: "sum-block" }, el("h4", { text: "Ideas clave" }),
      el("ul", { class: "sum-take" }, ...s.takeaways.map((t) => el("li", { text: t })))));
  }
  const point = (p) => el("li", { "data-t": p.t, title: "Ver desde aquí" }, el("time", { text: fmtDur(p.t) }), el("p", { text: p.text }));
  if (s.chapters?.length) {
    parts.push(el("div", { class: "sum-block" }, el("h4", { text: "Capítulos" }), ...s.chapters.map((ch) =>
      el("div", { class: "sum-chapter" },
        el("button", { type: "button", class: "sum-ch-title", "data-t": ch.t, title: "Ver desde aquí" },
          el("time", { text: fmtDur(ch.t) }), el("span", { text: ch.title })),
        el("ol", { class: "sum-points" }, ...ch.points.map(point))))));
  } else {
    parts.push(el("ol", { class: "sum-points" }, ...s.points.map(point)));
  }
  if (s.terms?.length) {
    parts.push(el("div", { class: "sum-block" }, el("h4", { text: "Conceptos clave" }),
      el("dl", { class: "sum-terms" }, ...s.terms.flatMap((x) => [
        el("dt", {}, el("button", { type: "button", class: "ag-ts", "data-t": x.t, title: "Ir a este momento" }, fmtDur(x.t)), x.term),
        el("dd", { text: x.meaning })]))));
  }
  if (s.resources?.length) {
    parts.push(el("div", { class: "sum-block" }, el("h4", { text: "Recursos del video" }), ...s.resources.map((r) => {
      const code = r.kind === "code" || r.kind === "command";
      const body = code ? el("pre", { class: "codeblk" }) : el("p", { class: "sum-res-text", text: r.text });
      if (code) body.append(highlight(r.text));
      return el("div", { class: "sum-res" }, el("button", { type: "button", class: "ag-ts", "data-t": r.t, title: "Ir a este momento" }, fmtDur(r.t)), body);
    })));
  }
  return parts;
}

// el punto que se está viendo, marcado como la frase de la transcripción
function markSummaryPoint(force = false) {
  const box = $("#ag-summary");
  if ($("#summary").hidden || !state.summary) return;
  const t = vEn.currentTime || 0;
  const items = box.querySelectorAll(".sum-points li");
  let now = null;
  for (const li of items) if (+li.dataset.t <= t + 0.5) now = li;
  if (!force && now === box._now) return;
  box._now = now;
  for (const li of items) li.classList.toggle("active", li === now);
}
vEn.addEventListener("timeupdate", () => markSummaryPoint());

$("#ag-summary").addEventListener("click", (e) => {
  const li = e.target.closest(".sum-points li[data-t], .sum-ch-title[data-t], .ag-ts[data-t]");
  if (li) vEn.currentTime = +li.dataset.t;
});

// del servidor: el resumen del video abierto (al abrirlo, al terminar o desde otra pestaña)
function summaryFromTranscript(m) {
  state.summary = m.summary || null;
  if ("summary_state" in m) state.summaryJob = m.summary_state || null;
  renderSummary();
}
function summaryUpdate(m) {
  if (m.type === "summary") {
    state.summary = m.summary;
    state.summaryJob = null;
    renderSummary();
    toast("Resumen listo", "ok", $("#summary").hidden ? { label: "Ver", onClick: () => setSideTab("summary") } : undefined);
    return;
  }
  const before = state.summaryJob;
  state.summaryJob = m.state || null;
  if (m.state?.state === "error" && before?.state !== "error") toast(m.state.error);
  renderSummary();
}
