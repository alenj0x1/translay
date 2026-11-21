"use strict";
// Controles del reproductor, subtítulos (botón, tecla C y clic derecho) y «Copiar para un agente».
// Comparte el ámbito global con app.js (se carga justo después).

/* ------------------------------------------------------------ controles del reproductor */
// Propios (los del navegador no siguen el estilo): reproducir, tiempo, línea de
// avance con lo procesado, idioma, volumen y pantalla completa.
function togglePlay() {
  if (vEn.paused || vEn.ended) {
    state.forcePlay = !readiness.ok;  // reproducir a mano aunque no esté listo
    state.autoWait = false;
    vEn.play();
  } else {
    state.autoWait = false;
    vEn.pause();
  }
}
const syncPlay = () => $("#ctrl").classList.toggle("playing", !vEn.paused && !vEn.ended);
$("#c-play").addEventListener("click", togglePlay);
vEn.addEventListener("click", togglePlay);
vEn.addEventListener("play", syncPlay);
vEn.addEventListener("pause", syncPlay);
vEn.addEventListener("ended", syncPlay);
vEn.addEventListener("durationchange", renderHead);

function trackTime(e) {
  const r = $("#track").getBoundingClientRect();
  return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * (vEn.duration || 0);
}
// la rueda del mouse sobre la barra adelanta o retrocede 5 s por paso
$("#track").addEventListener("wheel", (e) => {
  if (!vEn.duration) return;
  e.preventDefault();
  vEn.currentTime = Math.max(0, Math.min(vEn.duration - 0.1, vEn.currentTime + (e.deltaY < 0 ? 5 : -5)));
}, { passive: false });
$("#track").addEventListener("pointerdown", (e) => {
  if (!vEn.duration) return;
  const track = $("#track");
  track.setPointerCapture(e.pointerId);
  const near = [...$("#t-notes").children].find((i) => Math.abs(i.getBoundingClientRect().left + 3 - e.clientX) < 7);
  vEn.currentTime = near ? +near.dataset.t : trackTime(e);
  const move = (ev) => { vEn.currentTime = trackTime(ev); };
  const up = () => { track.removeEventListener("pointermove", move); track.removeEventListener("pointerup", up); };
  track.addEventListener("pointermove", move);
  track.addEventListener("pointerup", up);
});
$("#track").addEventListener("pointermove", (e) => {
  if (!vEn.duration) return;
  const tip = $("#t-tip");
  const r = $("#track").getBoundingClientRect();
  // cerca de una marca de comentario: se muestra su texto (y un clic salta ahí)
  const near = [...$("#t-notes").children].find((i) => Math.abs(i.getBoundingClientRect().left + 3 - e.clientX) < 7);
  tip.textContent = near ? `${fmt(+near.dataset.t)} · ${near.dataset.text.slice(0, 80)}${near.dataset.text.length > 80 ? "…" : ""}`
    : fmt(trackTime(e));
  tip.classList.toggle("note", !!near);
  tip.style.left = `${Math.max(18, Math.min(r.width - 18, e.clientX - r.left))}px`;
  tip.hidden = false;
});
$("#track").addEventListener("pointerleave", () => { $("#t-tip").hidden = true; });

function setVolume(v, muted = player.muted) {
  player.volume = v;
  player.muted = muted || v === 0;
  $("#c-vol").value = player.muted ? 0 : v;
  $("#ctrl").classList.toggle("muted", player.muted);
  if (state.audio) state.audio.master.gain.setTargetAtTime(player.muted ? 0 : v, state.audio.ctx.currentTime, 0.02);
}
$("#c-vol").addEventListener("input", (e) => setVolume(parseFloat(e.target.value), false));
$("#c-mute").addEventListener("click", () => setVolume(player.volume || 1, !player.muted));
// la rueda del mouse sobre el volumen lo sube o lo baja de a 5 %
$(".ctrl .vol").addEventListener("wheel", (e) => {
  e.preventDefault();
  const v = Math.round(Math.max(0, Math.min(1, (player.muted ? 0 : player.volume) + (e.deltaY < 0 ? 0.05 : -0.05))) * 100) / 100;
  setVolume(v, false);
}, { passive: false });

// velocidad: cada clic pasa a la siguiente; Shift + < / > también
const RATES = [0.75, 1, 1.25, 1.5, 1.75, 2];
const fmtRate = (r) => `${r.toLocaleString(LOCALE)}×`;
function setRate(r) {
  vEn.playbackRate = r;
  try { localStorage.setItem("vt-rate", String(r)); } catch (e) { /* sin almacenamiento */ }
}
// el número gira como una rueda: el nuevo entra desde abajo si sube y desde arriba si baja
let shownRate = null;
function rollRate(r) {
  const odo = $("#c-speed .odo");
  if (shownRate === r) return;
  const dir = shownRate == null ? 0 : r > shownRate ? 1 : -1;
  shownRate = r;
  const now = el("span", { text: fmtRate(r) });
  const old = odo.querySelector("span:not(.out)");
  if (!dir || !old || matchMedia("(prefers-reduced-motion: reduce)").matches) { odo.replaceChildren(now); return; }
  now.style.transform = `translateY(${dir * 100}%)`;
  old.classList.add("out");
  odo.append(now);
  requestAnimationFrame(() => { old.style.transform = `translateY(${-dir * 100}%)`; now.style.transform = "translateY(0)"; });
  setTimeout(() => old.remove(), 340);
}
$("#c-speed").addEventListener("click", () => {
  const i = RATES.indexOf(vEn.playbackRate);
  setRate(RATES[(i + 1) % RATES.length]);
});
// la rueda del mouse sobre la velocidad la sube o la baja (sin dar la vuelta)
$("#c-speed").addEventListener("wheel", (e) => {
  e.preventDefault();
  const i = Math.max(0, RATES.indexOf(vEn.playbackRate));
  setRate(RATES[Math.max(0, Math.min(RATES.length - 1, i + (e.deltaY < 0 ? 1 : -1)))]);
}, { passive: false });
try { const r = parseFloat(localStorage.getItem("vt-rate")); if (RATES.includes(r)) vEn.defaultPlaybackRate = vEn.playbackRate = r; } catch (e) { /* nada */ }
rollRate(vEn.playbackRate);

function toggleFull() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("#pane-en").requestFullscreen?.().catch(() => {});
}
$("#c-full").addEventListener("click", toggleFull);
vEn.addEventListener("dblclick", toggleFull);

/* ------------------------------------------------------------ subtítulos: botón, tecla C y clic derecho */
const subsOn = () => !!(prefs.sub_es || prefs.sub_orig || prefs.screen_text !== false);
function setSub(key, on) {
  setPref(key, on);
  applySubs();
}
function applySubs() {
  document.body.classList.toggle("no-sub-es", !prefs.sub_es);
  document.body.classList.toggle("no-sub-en", !prefs.sub_orig);
  $("#c-cc").classList.toggle("on", !!(prefs.sub_es || prefs.sub_orig));
  if (typeof renderScreenText === "function") renderScreenText();
}
// C: apaga todos los subtítulos (y el texto del video), o vuelve a prender los que estaban
function toggleSubs() {
  if (subsOn()) {
    state.subsWere = { sub_es: !!prefs.sub_es, sub_orig: !!prefs.sub_orig, screen_text: prefs.screen_text !== false };
    for (const k of Object.keys(state.subsWere)) if (state.subsWere[k]) setPref(k, false);
    toast(t("Subtítulos desactivados"), "ok");
  } else {
    const was = state.subsWere || { sub_es: true, sub_orig: true, screen_text: true };
    for (const [k, v] of Object.entries(was)) if (v) setPref(k, true);
    toast(t("Subtítulos activados"), "ok");
  }
  applySubs();
}
const subsMenu = () => [
  state.translates && { label: t("En {lang}", { lang: langName(targetLang()) }), icon: "captions", check: !!prefs.sub_es, onClick: () => setSub("sub_es", !prefs.sub_es) },
  { label: state.translates ? t("Del original ({lang})", { lang: langName(state.lang) }) : t("Subtítulos"), icon: "captions", check: !!prefs.sub_orig,
    onClick: () => setSub("sub_orig", !prefs.sub_orig) },
  state.translates && { label: t("Texto del video en {lang}", { lang: langName(targetLang()) }), icon: "eye", check: prefs.screen_text !== false,
    onClick: () => setSub("screen_text", prefs.screen_text === false) },
  "sep",
  { label: subsOn() ? t("Apagar todos") : t("Prender todos"), icon: subsOn() ? "x" : "check", kbd: "C", onClick: toggleSubs },
].filter(Boolean);
$("#c-cc").addEventListener("click", (e) => {
  openMenu(subsMenu(), e.currentTarget.getBoundingClientRect());  // DOMRect: abajo si cabe, si no arriba
});

/* ------------------------------------------------------------ copiar todo el video para un agente */
// el servidor arma el Markdown (vt/videocontext.py): transcripción con hora y persona, traducción,
// resumen y lo escrito en pantalla; con la posición, también hasta dónde se vio
function copyForAgent(vid, withPosition) {
  state.agentCopy = vid;
  send({ type: "agent_context", video: vid, ...(withPosition ? { position: vEn.currentTime } : {}) });
}

// teclado: espacio reproduce, flechas ±5 s, f pantalla completa, m silencio
document.addEventListener("keydown", (e) => {
  if (currentView() !== "player" || e.target.closest("input, textarea, select, dialog") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === " " || e.key === "k") { e.preventDefault(); togglePlay(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); vEn.currentTime = Math.max(0, vEn.currentTime - 5); }
  else if (e.key === "ArrowRight") { e.preventDefault(); vEn.currentTime = Math.min(vEn.duration || 0, vEn.currentTime + 5); }
  else if (e.key === "f") toggleFull();
  else if (e.key === "c") toggleSubs();
  else if (e.key === "m") setVolume(player.volume || 1, !player.muted);
  else if (e.key === ">" || e.key === "<") {
    const i = RATES.indexOf(vEn.playbackRate);
    setRate(RATES[Math.max(0, Math.min(RATES.length - 1, (i < 0 ? 1 : i) + (e.key === ">" ? 1 : -1)))]);
  }
});

// texto del campo de enlaces según el ancho: nunca cortado
const narrowMQ = window.matchMedia("(max-width: 760px)");
function fitLinkHint() {
  $("#yt-url").placeholder = narrowMQ.matches ? t("Pega un enlace") : t("Pega un enlace de YouTube o Dropbox");
}
narrowMQ.addEventListener("change", fitLinkHint);
fitLinkHint();
