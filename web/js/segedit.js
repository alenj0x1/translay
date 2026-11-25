"use strict";
// Editor de frases (vt/session_edit.py): corregir la traducción de una frase ahí mismo en la transcripción, rehacer su
// voz y elegir entre tres tomas. Se abre con doble clic en la traducción o con «Editar traducción» del clic derecho;
// solo el dueño. Comparte el ámbito global con app.js.
//   state.segEdit = { seg, draft, busy, takes: [{url, dur}], pick }

state.segEdit = null;
const canEditSeg = () => !!(isOwner() && state.translates && state.videoId);
const hasVoice = () => !!state.voice && state.voice !== "none";

function openSegEdit(id) {
  const s = state.segments.find((x) => x.id === id);
  if (!s || !canEditSeg()) return;
  state.editing = null;  // un cuadro a la vez (comentario o traducción)
  state.segEdit = { seg: id, draft: s.translation || "", busy: false, takes: [], pick: null };
  renderTranscript();
  focusSegEdit(true);
}

function closeSegEdit() {
  if (!state.segEdit) return;
  state.segEdit = null;
  renderTranscript();
}

function focusSegEdit(selectAll) {
  const ta = $("#transcript .seditor textarea");
  if (!ta) return;
  ta.focus();
  if (selectAll) ta.select();
  else ta.setSelectionRange(ta.value.length, ta.value.length);
}

// Rehacer voz: guarda el texto (si cambió) y pide tres tomas en el mismo pedido, así salen del texto nuevo
function redoSegVoice() {
  const ed = state.segEdit;
  const text = ed.draft.trim();
  if (!text) return;
  ed.busy = hasVoice();
  ed.takes = [];
  ed.pick = null;
  send({ type: "seg_edit", video: state.videoId, seg: ed.seg, translation: text, takes: hasVoice() ? 3 : 0 });
  if (!hasVoice()) state.segEdit = null;  // sin motor de voz solo se guarda el texto
  renderTranscript();
}

function playTake(k) {
  const ed = state.segEdit;
  const take = ed?.takes[k];
  if (!take) return;
  ed.pick = k;
  segEditAudio.src = take.url;
  segEditAudio.play().catch(() => {});
  send({ type: "seg_take", video: state.videoId, seg: ed.seg, k });
  renderTranscript();
}
const segEditAudio = new Audio();

function segEditTakes(m) {
  const ed = state.segEdit;
  if (!ed || ed.seg !== m.id) return;
  ed.busy = false;
  ed.takes = m.items || [];
  ed.pick = ed.takes.length ? 0 : null;  // la primera toma ya suena como voz de la frase
  renderTranscript();
}

// El cuadro dentro de la fila de la frase (renderTranscript lo agrega bajo la traducción)
function segEditor(s) {
  const ed = state.segEdit;
  const ta = el("textarea", { class: "area", rows: 2, maxlength: 600, "aria-label": t("Traducción") });
  ta.value = ed.draft;
  ta.addEventListener("input", () => { ed.draft = ta.value; });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); closeSegEdit(); }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); redoSegVoice(); }
  });
  const takes = el("div", { class: "stakes" });
  if (ed.busy) {
    takes.append(el("span", { class: "stakes-busy", text: t("Generando tomas…") }));
  } else {
    ed.takes.forEach((tk, k) => takes.append(
      el("button", { type: "button", class: "btn xs ghost take" + (ed.pick === k ? " on" : ""),
        on: { click: () => playTake(k) } }, icon("play"), t("Toma {n}", { n: k + 1 }))));
  }
  const acts = el("div", { class: "cacts" },
    btn(ed.takes.length ? t("Cerrar") : t("Cancelar"), { variant: "ghost", size: "xs", onClick: closeSegEdit }),
    btn(hasVoice() ? t("Rehacer voz") : t("Guardar"), { icon: hasVoice() ? "reload" : "check", variant: "dark", size: "xs",
      disabled: ed.busy, onClick: redoSegVoice }));
  return el("div", { class: "seditor", on: { click: (e) => e.stopPropagation() } }, ta,
    ed.takes.length || ed.busy ? takes : null, acts);
}

$("#transcript").addEventListener("dblclick", (e) => {
  const li = e.target.closest("li[data-id]");
  if (!li || e.target.closest(".notes, .seditor") || !canEditSeg()) return;
  const cells = li.querySelectorAll(":scope > .cell");
  if (e.target.closest(".cell") !== cells[cells.length - 1]) return;  // la traducción, no el original
  e.preventDefault();
  getSelection()?.removeAllRanges();
  openSegEdit(Number(li.dataset.id));
});
