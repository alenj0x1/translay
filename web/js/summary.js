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
  return [s.overview, "", ...s.points.map((p) => `[${fmtDur(p.t)}] ${p.text}`)].join("\n");
}

function renderSummary() {
  const box = $("#summary");
  if (box.hidden) return;
  const job = state.summaryJob;
  const s = state.summary;
  const can = canImport();
  if (job && job.state !== "error") {
    const label = `${SUMMARY_STEP[job.state] || "Resumiendo"}${job.state === "en cola" ? "" : ` ${job.pct || 0} %`}`;
    box.replaceChildren(emptyState("lines", s ? "Rehaciendo el resumen" : "Resumiendo el video",
      job.state === "descargando" ? "Solo la primera vez: después se resume sin conexión."
        : "Puedes seguir viendo el video. Te aviso cuando esté listo.", "div", btn(label, { icon: "lines", variant: "dark", disabled: true, cls: "sum-run" }),
      can ? btn("Cancelar", { icon: "x", variant: "ghost", onClick: () => send({ type: "summary_cancel", video: state.videoId }) }) : null));
    return;
  }
  if (!s || s.empty) {
    const ready = summaryReady();
    const err = job?.state === "error" ? job.error : "";
    box.replaceChildren(emptyState("lines", err ? "No se pudo resumir" : "Aún sin resumen",
      err || (ready ? "Translay lo escribe en tu equipo, sin internet, a partir de lo que se dice en el video."
        : "Se puede resumir cuando termine la transcripción."),
      "div", can && ready ? btn(err ? "Reintentar" : "Resumir", { icon: "lines", variant: "dark", onClick: () => requestSummary(!!s) }) : null));
    return;
  }
  const overview = el("div", { class: "sum-overview" }, ...s.overview.split(/\n+/).filter(Boolean).map((t) => el("p", { text: t })));
  const points = el("ol", { class: "sum-points" }, ...s.points.map((p) =>
    el("li", { "data-t": p.t, title: "Ver desde aquí" }, el("time", { text: fmtDur(p.t) }), el("p", { text: p.text }))));
  const fresh = box.dataset.shown !== String(s.created);  // otro resumen (o recién hecho): desde arriba
  box.replaceChildren(overview, points);
  if (fresh) box.scrollTop = 0;
  box.dataset.shown = String(s.created);
  markSummaryPoint(true);
}

// el punto que se está viendo, marcado como la frase de la transcripción
function markSummaryPoint(force = false) {
  const box = $("#summary");
  if (box.hidden || !state.summary) return;
  const t = vEn.currentTime || 0;
  const items = box.querySelectorAll(".sum-points li");
  let now = null;
  for (const li of items) if (+li.dataset.t <= t + 0.5) now = li;
  if (!force && now === box._now) return;
  box._now = now;
  for (const li of items) li.classList.toggle("active", li === now);
}
vEn.addEventListener("timeupdate", () => markSummaryPoint());

$("#summary").addEventListener("click", (e) => {
  const li = e.target.closest(".sum-points li[data-t]");
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
    toast("Resumen listo.", "ok", $("#summary").hidden ? { label: "Ver", onClick: () => setSideTab("summary") } : undefined);
    return;
  }
  const before = state.summaryJob;
  state.summaryJob = m.state || null;
  if (m.state?.state === "error" && before?.state !== "error") toast(m.state.error);
  renderSummary();
}
