"use strict";
// Comentarios por frase, cuadros para confirmar o escribir, cerrar el video, los huecos de la transcripción,
// la frase activa y la barra de tiempo con lo ya procesado.
// Comparte el ámbito global con app.js (se carga justo después).

/* ------------------------------------------------------------ comentarios por frase */
function renderNotes(segId, notes) {
  const box = document.createElement("div");
  box.className = "notes";
  for (const c of notes) {
    if (state.editing?.seg === segId && state.editing.id === c.id) { box.append(noteEditor()); continue; }
    const item = document.createElement("div");
    item.className = "note";
    const text = document.createElement("p");
    text.textContent = c.text;
    const meta = document.createElement("small");
    const when = new Date((c.updated || c.created) * 1000);
    meta.textContent = `${when.toLocaleDateString(LOCALE, { day: "numeric", month: "short" })} ${when.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })}${c.updated ? " · " + t("editado") : ""}`;
    const acts = document.createElement("span");
    acts.className = "nacts";
    acts.append(noteBtn(t("Editar"), "pencil", () => { state.editing = { seg: segId, id: c.id, draft: c.text }; renderTranscript(); focusEditor(); }),
      noteBtn(t("Eliminar"), "trash", async () => {
        if (await confirmDlg(t("¿Eliminar este comentario?"), "", t("Eliminar"))) {
          send({ type: "comment_delete", video: state.videoId, seg: segId, id: c.id });
        }
      }));
    item.append(text, meta, acts);
    box.append(item);
  }
  if (state.editing?.seg === segId && state.editing.id === null) box.append(noteEditor());
  return box;
}
function noteBtn(text, ic, fn) {
  return btn(text, { icon: ic, size: "xs", onClick: fn });
}
function noteEditor() {
  const ed = state.editing;
  const form = document.createElement("form");
  form.className = "ceditor";
  const ta = el("textarea", { class: "area text" });
  ta.rows = 3;
  ta.maxLength = 4000;
  ta.placeholder = t("Comentario");
  ta.value = ed.draft;
  // crece con el texto (sin tirador para cambiar el alto)
  const grow = () => { ta.style.height = "auto"; ta.style.height = `${ta.scrollHeight + 2}px`; };
  ta.addEventListener("input", () => { ed.draft = ta.value; grow(); });
  requestAnimationFrame(grow);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { state.editing = null; renderTranscript(); }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });
  const acts = document.createElement("div");
  acts.className = "cacts";
  const cancel = btn(t("Cancelar"), { variant: "ghost", size: "xs", onClick: () => { state.editing = null; renderTranscript(); } });
  const save = btn(t("Guardar"), { variant: "dark", size: "xs", type: "submit", icon: "check" });
  acts.append(cancel, save);
  form.append(ta, acts);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text) return;
    send(ed.id ? { type: "comment_edit", video: state.videoId, seg: ed.seg, id: ed.id, text }
      : { type: "comment_add", video: state.videoId, seg: ed.seg, text });
    state.editing = null;
    renderTranscript();
  });
  return form;
}
function focusEditor() {
  const ta = $("#transcript .ceditor .area");
  if (!ta) return;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.closest("li").scrollIntoView({ block: "nearest" });
}

// diálogo de confirmación con el estilo de la página
// typeToConfirm: hay que escribir ese texto (p. ej. el nombre de la biblioteca) para poder aceptar
function confirmDlg(title, text, okLabel, typeToConfirm = "") {
  const dlg = $("#confirm-dlg");
  const ok = $("#confirm-ok");
  const input = $("#confirm-input");
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  ok.textContent = okLabel;
  input.hidden = !typeToConfirm;
  input.value = "";
  input.placeholder = typeToConfirm;
  $("#confirm-type").hidden = !typeToConfirm;
  $("#confirm-type").textContent = typeToConfirm ? t("Escribe «{text}» para confirmar", { text: typeToConfirm }) : "";
  ok.disabled = !!typeToConfirm;
  input.oninput = () => { ok.disabled = input.value.trim() !== typeToConfirm; };
  dlg.returnValue = "";
  dlg.showModal();
  if (typeToConfirm) input.focus();
  return new Promise((resolve) => dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true }));
}

// «Escuchar» una voz: el mismo botón la pausa; una sola suena a la vez
let previewAudio = null;
function previewBtn(url, title) {
  const b = btn(t("Escuchar"), { icon: "speaker", size: "xs", variant: "ghost", title });
  const done = () => { setBtn(b, t("Escuchar"), "speaker"); b.classList.remove("on"); };
  b.addEventListener("click", () => {
    if (previewAudio?.btn === b && !previewAudio.paused) { previewAudio.pause(); return; }
    previewAudio?.pause();
    const a = new Audio(url);
    a.btn = b;
    a.addEventListener("pause", done);
    a.addEventListener("ended", done);
    a.play().then(() => { setBtn(b, t("Pausar"), "pause"); b.classList.add("on"); }).catch(done);
    previewAudio = a;
  });
  return b;
}

// pide un texto (nombre de una colección…); null si se cancela
function promptDlg(title, value, okLabel) {
  const dlg = $("#prompt-dlg");
  const input = $("#prompt-input");
  $("#prompt-title").textContent = title;
  $("#prompt-ok").textContent = okLabel;
  input.value = value || "";
  dlg.returnValue = "";
  dlg.showModal();
  input.select();
  return new Promise((resolve) => dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok" && input.value.trim() ? input.value.trim() : null), { once: true }));
}

// el video abierto se eliminó (desde esta u otra pestaña)
function closeVideo() {
  vEn.pause();
  stopDub();
  send({ type: "unwatch" });
  state.videoId = null;
  state.segments = [];
  state.comments = {};
  state.editing = null;
  screenTextLoad(null);
  vEn.removeAttribute("src");
  vEs.removeAttribute("src");
  vEn.load();
  document.title = "Translay";
  renderTranscript();
  lib.mini = false;  // si sonaba en miniatura, la miniatura se va con él
  document.body.classList.remove("mini");
  if (currentView() === "player") setView("library");
}

const MIN_GAP = 4;  // segundos: lo más corto se ve como una pausa, no como un hueco
// [inicio, fin] de lo que aún no se transcribió, sobre la duración del video
function transcriptGaps() {
  const dur = vEn.duration || lib.videos[state.videoId]?.duration || 0;
  if (!dur) return [];
  const out = [];
  let at = 0;
  for (const [a, b] of [...state.covered].sort((x, y) => x[0] - y[0])) {
    if (a - at >= MIN_GAP) out.push([at, a]);
    at = Math.max(at, b);
  }
  if (dur - at >= MIN_GAP) out.push([at, dur]);
  return out;
}
const gapSig = (gaps) => gaps.map(([a, b]) => `${Math.round(a)}-${Math.round(b)}`).join(",");

// ¿se está transcribiendo justo esta parte? (lo que se reproduce, en vivo o en la cola)
function gapBusy(a, b) {
  const t = vEn.currentTime;
  if (t < a - 1 || t >= b) return false;
  const job = typeof lib !== "undefined" ? lib.queue?.jobs?.find((j) => j.id === state.videoId) : null;
  return state.sending || (state.ahead && feeder.inSpan) || job?.state === "procesando";
}
const gapText = (a, b) => (gapBusy(a, b) ? t("Transcribiendo esta parte") : t("Aún sin transcribir"));

function gapItem([a, b]) {
  const li = el("li", { class: "gap" + (gapBusy(a, b) ? " busy" : ""), title: t("Ir a esta parte") });
  li.dataset.start = a;
  li.dataset.end = b;
  li.append(el("div", { class: "cell" }, el("time", { text: `${fmt(a)} – ${fmt(b)}` }),
    el("p", {}, el("strong", { text: gapText(a, b) }),
      el("span", { text: t("Se transcribe al reproducir esta parte.") }))));
  return li;
}

function renderActive(force) {
  const t = vEn.currentTime;
  for (const li of $("#transcript").querySelectorAll("li.gap")) {  // «transcribiendo» sigue al punto de reproducción
    const txt = gapText(+li.dataset.start, +li.dataset.end);
    const strong = li.querySelector("strong");
    if (strong.textContent !== txt) strong.textContent = txt;
    li.classList.toggle("busy", gapBusy(+li.dataset.start, +li.dataset.end));
  }
  // lo escrito en el video (código, comandos, enlaces): se marca mientras está en pantalla
  for (const li of $("#transcript").querySelectorAll("li.el-row")) {
    li.classList.toggle("now", +li.dataset.start <= t + 0.15 && t < +li.dataset.end + 0.5);
  }
  let active = null;
  for (const s of state.segments) {
    if (s.start <= t + 0.15) active = s;
    else break;
  }
  const ol = $("#transcript");
  const prev = ol.querySelector("li.active");
  const next = active ? ol.querySelector(`li[data-id="${active.id}"]`) : null;
  if (prev === next && !force) return;
  prev?.classList.remove("active");
  if (!next) return;
  next.classList.add("active");
  if (performance.now() - state.userScrollAt > 3000 && !state.editing) {
    const top = next.offsetTop - ol.offsetTop - ol.clientHeight / 3;
    ol.scrollTo({ top, behavior: force ? "auto" : "smooth" });
  }
}

$("#transcript").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-start]");
  if (!li || e.target.closest(".notes, .seditor")) return;
  if (e.target.closest(".cbtn")) {  // comentar esta frase
    state.editing = { seg: Number(li.dataset.id), id: null, draft: "" };
    renderTranscript();
    focusEditor();
    return;
  }
  vEn.currentTime = parseFloat(li.dataset.start);
});
$("#transcript").addEventListener("wheel", () => { state.userScrollAt = performance.now(); }, { passive: true });
$("#transcript").addEventListener("touchmove", () => { state.userScrollAt = performance.now(); }, { passive: true });

function paintRanges(box, ranges, d) {
  box.replaceChildren();
  if (!d || !isFinite(d)) return;
  for (const [a, b] of ranges) {
    const el = document.createElement("b");
    el.style.left = `${(a / d) * 100}%`;
    el.style.width = `${Math.max(0.2, ((b - a) / d) * 100)}%`;
    box.appendChild(el);
  }
}

function renderTimeline() {
  const d = vEn.duration;
  // controles: tramos reconocidos y frases ya dobladas (o traducidas, sin voz)
  paintRanges($("#t-cov"), state.covered, d);
  paintRanges($("#t-dub"), state.segments.filter(segDone).map((s) => [s.start, s.end]), d);
  // comentarios: una marca pequeña sobre la línea de avance (al pasar el mouse se lee)
  const marks = $("#t-notes");
  marks.replaceChildren();
  if (d && isFinite(d)) {
    for (const [sid, notes] of Object.entries(state.comments)) {
      const seg = state.segments.find((x) => String(x.id) === sid);
      if (!seg || !notes.length) continue;
      const i = document.createElement("i");
      i.style.left = `${(seg.start / d) * 100}%`;
      i.dataset.t = seg.start;
      i.dataset.text = notes.map((c) => c.text).join(" · ");
      marks.append(i);
    }
  }
  // vista dividida: bajo el video en español, las frases traducidas
  const tl = $("#tl-es");
  paintRanges(tl, state.segments.filter((s) => s.translation).map((s) => [s.start, s.end]), d);
  if (d && isFinite(d)) tl.append(Object.assign(document.createElement("i"), { className: "head" }));
  paintChapters(d);
  renderHead();
}

// capítulos del resumen (vt/digest.py): la línea de avance se parte en tramos con un hueco
// entre ellos; con menos de dos capítulos (o sin resumen) la línea queda entera
function videoChapters(d = vEn.duration) {
  if (!d || !isFinite(d)) return [];
  const chs = (state.summary?.chapters || []).filter((c) => c.title && c.t >= 0 && c.t < d - 1).sort((a, b) => a.t - b.t);
  return chs.length >= 2 ? chs : [];
}
function chapterAt(sec, chs = videoChapters()) {
  let now = chs[0] || null;
  for (const c of chs) if (c.t <= sec) now = c;
  return now;
}
function paintChapters(d) {
  // una sola máscara para el fondo, lo procesado y el avance: huecos de 2 px en cada inicio de capítulo
  const track = $("#track");
  const cuts = videoChapters(d).slice(1).map((c) => (c.t / d) * 100);
  if (!cuts.length) { track.style.removeProperty("--ch-mask"); track.classList.remove("chapters"); return; }
  const stops = ["#000 0"];
  for (const p of cuts) stops.push(`#000 calc(${p}% - 1px)`, `transparent calc(${p}% - 1px)`, `transparent calc(${p}% + 1px)`, `#000 calc(${p}% + 1px)`);
  track.style.setProperty("--ch-mask", `linear-gradient(to right, ${stops.join(", ")})`);
  track.classList.add("chapters");
}

function renderHead() {
  const d = vEn.duration;
  const t = vEn.currentTime;
  const ch = chapterAt(t, videoChapters(d));
  $("#c-time").replaceChildren(fmt(t), el("small", { text: ` / ${d && isFinite(d) ? fmt(d) : "0:00"}` }));
  const chip = $("#c-chap");  // el capítulo que se está viendo, junto al tiempo
  chip.hidden = !ch;
  if (ch && chip.textContent !== ch.title) { chip.textContent = ch.title; chip.title = ch.title; }
  if (!d || !isFinite(d)) return;
  const pct = `${Math.min(100, (t / d) * 100)}%`;
  $("#t-play").style.width = pct;
  $("#t-head").style.left = pct;
  document.querySelectorAll(".timeline .head").forEach((h) => { h.style.left = pct; });
}

vEn.addEventListener("loadedmetadata", renderTimeline);

// después de cargar todos los scripts: los primeros mensajes del servidor ya encuentran quién los atiende
window.addEventListener("DOMContentLoaded", connect);
