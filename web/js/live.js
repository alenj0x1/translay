"use strict";
// Subtítulos en vivo sobre cualquier ventana (app de escritorio). Esta página vive en una ventana transparente,
// siempre encima y que deja pasar los clics (desktop/src-tauri/src/live.rs):
// - La app captura lo que suena en el equipo (WASAPI loopback) y manda trozos de 100 ms (PCM int16 mono 16 kHz)
//   por un canal; aquí se reenvían al servidor por /ws con su tiempo, como la transcripción en vivo de una
//   grabación (capture.js), pero en una sesión efímera: el servidor reconoce y traduce sin guardar nada
//   ({"type":"open","ephemeral":true}, vt/session.py; solo el dueño en este equipo).
// - Se muestran las dos últimas líneas: la frase anterior más tenue y la que se está diciendo.
// - La app avisa cuando el mouse pasa por encima (live-hover): aparece la manija, y solo sobre ella la ventana toma
//   el mouse para arrastrarla (live_grip dice dónde está).
// - Los errores van al registro del servidor (client_error), como los de la página principal.

const TAURI = window.__TAURI__;
const SR = 16000;
const KEEP_S = 5;       // sin conexión: lo último que se reenvía al volver
const IDLE_MS = 6000;   // sin texto nuevo: la franja se va

const $ = (s) => document.querySelector(s);
const view = { root: $("#live"), strip: $("#strip"), grip: $("#grip"), prev: $("#prev"), now: $("#now") };
const live = { ws: null, open: false, samples: 0, pending: [], prevId: null, prevText: "", nowText: "", idle: 0, errors: new Set(),
  // latencia: cuándo llegó cada trozo (reloj de la página) para medir de la voz al texto en pantalla
  arrived: [], stats: { segments: 0, latency: [] } };
window.liveStats = live.stats;

function clientError(kind, message) {
  const key = `${kind}|${message}`;
  if (live.errors.has(key) || live.errors.size > 50) return;
  live.errors.add(key);
  console.warn(`[${kind}] ${message}`);
  if (live.ws?.readyState === WebSocket.OPEN) live.ws.send(JSON.stringify({ type: "client_error", kind, message: String(message).slice(0, 400) }));
}
window.addEventListener("error", (e) => { if (e.message) clientError("vivo.js", `${e.message} @ live.js:${e.lineno}`); });
window.addEventListener("unhandledrejection", (e) => clientError("vivo.promesa", e.reason?.message || String(e.reason)));

/* ------------------------------------------------------------ texto */
function render() {
  const now = live.nowText, prev = live.prevText;
  const waiting = !now && !prev;
  view.root.classList.toggle("waiting", waiting);
  // sin frase abierta, la última confirmada va con el color principal
  view.prev.textContent = now ? prev : "";
  view.now.textContent = waiting ? t("Escuchando…") : now || prev;
  clearTimeout(live.idle);
  view.root.classList.remove("idle");
  live.idle = setTimeout(() => view.root.classList.add("idle"), waiting ? 2500 : IDLE_MS);
}

/* ------------------------------------------------------------ servidor */
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  live.ws = ws;
  live.open = false;
  ws.onmessage = (e) => {
    if (typeof e.data !== "string") return;
    const m = JSON.parse(e.data);
    if (m.type === "ready") {
      ws.send(JSON.stringify({ type: "open", id: `live_${Date.now().toString(36)}`, ephemeral: true }));
      for (const p of live.pending) ws.send(p.buf);
      live.pending = [];
      live.open = true;
    } else if (m.type === "auth" && !(m.owner && m.local)) {
      clientError("vivo", "la sesión en vivo es solo para el dueño en este equipo");
    } else if (m.type === "partial") {
      live.nowText = (m.es || `${m.committed || ""} ${m.tentative || ""}`).trim();
      render();
    } else if (m.type === "segment") {
      const s = m.segment;
      live.prevId = s.id;
      live.prevText = s.translation || s.text || "";
      live.nowText = "";
      latency(s.end);
      render();
    } else if (m.type === "translations") {
      const x = (m.items || []).find((i) => i.id === live.prevId);
      if (x?.translation) { live.prevText = x.translation; render(); }
    } else if (m.type === "denied") {
      clientError("vivo", `rechazado: ${m.what}`);
    }
  };
  ws.onclose = () => {
    live.open = false;
    setTimeout(connect, 1000);  // el servidor se reinició: la sesión vuelve sola
  };
}

// de la voz al texto: el final de la frase (tiempo del audio) contra cuándo llegó ese audio y cuándo se ve
function latency(end) {
  const a = live.arrived.find((x) => x.t >= end);
  if (!a) return;
  live.stats.segments++;
  live.stats.latency.push(Math.round(performance.now() - a.at));
  if (live.stats.latency.length > 200) live.stats.latency.shift();
}

function onAudio(data) {
  const pcm = new Int16Array(data instanceof ArrayBuffer ? data : data.buffer || new Uint8Array(data).buffer);
  const t = live.samples / SR;
  live.samples += pcm.length;
  const buf = new ArrayBuffer(8 + pcm.byteLength);
  new DataView(buf).setFloat64(0, t, true);
  new Int16Array(buf, 8).set(pcm);
  live.arrived.push({ t: live.samples / SR, at: performance.now() });
  if (live.arrived.length > 600) live.arrived.shift();
  if (live.open && live.ws.readyState === WebSocket.OPEN) {
    live.ws.send(buf);
  } else {
    live.pending.push({ end: live.samples / SR, buf });
    while (live.pending.length && live.pending[0].end < live.samples / SR - KEEP_S) live.pending.shift();
  }
}

/* ------------------------------------------------------------ ventana */
// la manija va pegada a la izquierda de la franja, con su mismo alto; la app sabe dónde está para tomar el mouse ahí
function placeGrip() {
  const r = view.strip.getBoundingClientRect();
  const w = view.grip.offsetWidth, gap = 6;
  const left = Math.max(0, r.left - gap - w);
  view.grip.style.left = `${left}px`;
  view.grip.style.height = `${r.height}px`;
  TAURI.core.invoke("live_grip", { x: left, y: r.top, w, h: r.height }).catch(() => {});
}

function start() {
  render();
  new ResizeObserver(placeGrip).observe(view.strip);
  window.addEventListener("resize", placeGrip);
  placeGrip();
  TAURI.event.listen("live-hover", (e) => view.root.classList.toggle("hover", !!e.payload?.over));
  TAURI.event.listen("live-error", (e) => clientError("vivo.audio", e.payload?.message || ""));
  view.grip.addEventListener("pointerdown", (e) => {
    if (e.button === 0) TAURI.window.getCurrentWindow().startDragging().catch((err) => clientError("vivo", `mover: ${err}`));
  });
  connect();
  const ch = new TAURI.core.Channel();
  ch.onmessage = onAudio;
  TAURI.core.invoke("live_audio", { onAudio: ch }).catch((err) => clientError("vivo", `audio: ${err}`));
  // se muestra cuando ya está pintada con su letra (antes, la ventana se vería vacía un instante)
  document.fonts.ready.then(() => requestAnimationFrame(() => requestAnimationFrame(() =>
    TAURI.core.invoke("live_shown").catch((err) => clientError("vivo", `mostrar: ${err}`)))));
}

if (TAURI?.core) start();
else render();  // en el navegador solo se ve la franja (sin audio)
