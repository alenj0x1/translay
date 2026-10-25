"use strict";

const $ = (s) => document.querySelector(s);
const vEn = $("#v-en");
const vEs = $("#v-es");
const SR = 16000;

const state = {
  ws: null,
  ready: false,
  videoId: null,
  videoName: "",
  segments: [],        // [{id,start,end,text,translation}] ordenadas por inicio
  covered: [],         // [[a,b]] rangos ya procesados
  live: { committed: "", tentative: "" },
  lastSeg: null,       // última frase recibida en vivo
  lastSegAt: 0,
  sending: false,
  audio: null,         // {ctx, node, orig, dub}
  userScrollAt: 0,
  dubMode: true,       // escuchar en español (voz doblada) u original
  ahead: false,        // audio del archivo procesado por delante de la reproducción
  downloads: {},       // descargas de YouTube en curso: id → {title, stage, pct}
  comments: {},        // id de frase → [{id, text, created, updated}]
  editing: null,       // comentario en edición: {seg, id (null = nuevo), draft}
};

// preferencias guardadas en el servidor (vt/prefs.py); valores por defecto hasta recibirlas
let prefs = { layout: "ampliada", audio: "es", duck: "bajo", sub_es: true, sub_en: true, ready_chip: "auto",
  autoplay: true, autoplay_next: true };
let prefsSchema = [];
let prefsSections = [];

/* ------------------------------------------------------------ conexión */
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  setStatus("busy", "conectando");
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    state.ready = false;
    setStatus("off", "sin conexión");
    setTimeout(connect, 1000);
  };
  state.ws = ws;
}

function send(obj) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(obj));
}

function onMessage(m) {
  switch (m.type) {
    case "ready":
      state.ready = true;
      state.models = `${m.device} · ${m.model}${m.translator !== "none" ? " · " + m.translator : ""}`;
      renderPower();
      state.voice = m.voice;
      if (state.videoId) send({ type: "open", id: state.videoId, name: state.videoName });
      send({ type: "library" });
      break;
    case "library":
      libraryUpdate(m);
      break;
    case "queue":
      queueUpdate(m);
      break;
    case "power":
      state.power = m.state;
      renderPower();
      break;
    case "comments":
      if (m.video !== state.videoId) break;
      state.comments = m.comments;
      renderTranscript();
      break;
    case "deleted":
      if (m.videos.includes(state.videoId)) closeVideo();
      break;
    case "library_changed":
      send({ type: "library" });
      break;
    case "batch_added":
      if (m.videos) toast(`${m.videos === 1 ? "1 video agregado" : `${m.videos} videos agregados`} a la cola.`, "ok");
      break;
    case "playlist_added":
      setStatus(...baseStatus);
      $("#yt-url").value = "";
      playlistAdded(m);
      break;
    case "exports":
      exportsUpdate(m);
      break;
    case "export_started":
      exportStarted(m.job);
      break;
    case "yt_queued":
      setStatus(...baseStatus);
      $("#yt-url").value = "";
      break;
    case "transcript":
      if (m.id !== state.videoId) return;
      state.segments = m.segments;
      state.covered = m.covered;
      state.comments = m.comments || {};
      state.editing = null;
      // las voces se bajan a medida que se acercan (cada 80 ms se precargan los próximos 15 s):
      // bajarlas todas al abrir llenaba las conexiones y el video tardaba en cargar
      renderTranscript();
      renderTimeline();
      break;
    case "segment": {
      const gone = new Set([...m.removed, m.segment.id]);
      state.segments = state.segments.filter((s) => !gone.has(s.id));
      state.segments.push(m.segment);
      state.segments.sort((a, b) => a.start - b.start);
      state.lastSeg = m.segment;
      state.lastSegAt = performance.now();
      renderTranscript();
      renderTimeline();
      break;
    }
    case "partial":
      state.live = m;
      break;
    case "translations": {
      const byId = new Map(m.items.map((x) => [x.id, x.translation]));
      for (const s of state.segments) if (byId.has(s.id)) s.translation = byId.get(s.id);
      renderTranscript();
      renderTimeline();
      break;
    }
    case "dub": {
      const seg = state.segments.find((s) => s.id === m.id);
      if (!seg) break;
      seg.dub = { url: m.url, dur: m.dur };
      if (m.speaker !== undefined) seg.speaker = m.speaker;
      const near = seg.end > vEn.currentTime - 1 && seg.start < vEn.currentTime + 20;
      (m.live || near ? loadDub(seg) : Promise.resolve()).then(() => {
        if (m.live && state.sending) liveEnqueue(seg);
      });
      renderTranscript();
      break;
    }
    case "speaker": {
      const seg = state.segments.find((s) => s.id === m.id);
      if (seg) { seg.speaker = m.speaker; renderTranscript(); }
      break;
    }
    case "prefs":
      applyPrefs(m);
      break;
    case "cookies":
      renderCookies(m);
      break;
    case "yt_progress":
      state.downloads[m.id] = m;
      setStatus("busy", downloadText(m), false);
      if (typeof renderQueuePanel === "function") { renderQueuePanel(); refreshCards(); }
      break;
    case "yt_ready":
      delete state.downloads[m.id];
      if (typeof renderQueuePanel === "function") renderQueuePanel();
      setStatus(...baseStatus);
      $("#yt-url").value = "";
      loadVideo(m.video, "yt_" + m.id, m.title, m.audio);
      break;
    case "yt_error":
      state.downloads = {};
      if (typeof renderQueuePanel === "function") renderQueuePanel();
      setStatus(...baseStatus);
      toast(m.error);
      break;
    case "covered":
      state.covered = m.ranges;
      renderTimeline();
      break;
    case "stats":
      if (feeder.ack) feeder.ack();
      state.metrics = `inferencia ${m.infer_ms} ms · búfer ${m.buffer_s.toFixed(1)} s`;
      break;
  }
  renderCaptions();
}

let baseStatus = ["off", "sin conexión"];
function setStatus(kind, text, base = true) {
  if (base) baseStatus = [kind, text];
  const el = $("#status");
  el.dataset.state = kind;
  el.querySelector("span").textContent = text;
}

/* ------------------------------------------------------------ carga de video */
async function fingerprint(file) {
  // huella del contenido: tamaño + primer y último MB (estable aunque se renombre)
  const MB = 1 << 20;
  const parts = [new TextEncoder().encode(String(file.size)),
    await file.slice(0, MB).arrayBuffer(),
    await file.slice(Math.max(0, file.size - MB)).arrayBuffer()];
  return sha256(new Blob(parts));
}

async function sha256(data) {
  const buf = data instanceof Blob ? await data.arrayBuffer() : new TextEncoder().encode(data);
  const h = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

function loadVideo(src, id, name, audioSrc, opts = {}) {
  if (state.videoId) send({ type: "stop" });
  state.videoId = id;
  state.videoName = name;
  state.segments = [];
  state.covered = [];
  state.live = { committed: "", tentative: "" };
  state.lastSeg = null;
  state.sending = false;
  vEn.src = src;
  vEs.src = src;
  stopDub();
  dubBuf.clear();
  // videos guardados en el servidor (YouTube o copia en la biblioteca): los procesa
  // la cola del servidor desde el punto de reproducción. Archivos recién abiertos
  // (aún sin copia): el navegador envía su audio por delante.
  const rel = src.replace(location.origin, "");
  state.serverSide = !!audioSrc || /^\/media\/(yt|lib)\//.test(rel);
  if (state.serverSide) {
    feeder.run++;
    feeder.pcm = null;
    state.ahead = true;
  } else {
    prepareAhead(src);
  }
  readiness.hist = [];
  readiness.need = null;
  readiness.ok = false;
  setMode(prefs.audio !== "original");
  libOnOpen({ id, name, ...opts });
  setView("player");
  $("#file-name").textContent = name;
  $("#file-name").title = name;
  document.title = `${name} · Traductor`;
  renderTranscript();
  renderTimeline();
  renderCaptions();
  send({ type: "open", id, name });
  if (state.serverSide) send({ type: "watch", video: id, t: opts.position || 0 });
  // Preferencias → Video: empieza solo, en cuanto esté listo para reproducirse sin cortes
  state.forcePlay = false;
  state.autoWait = prefs.autoplay !== false;
}

// uno o varios archivos: se abre el primero; los demás quedan en "Siguientes"
// (se copian a la biblioteca y la cola los procesa mientras tanto)
async function openFiles(files) {
  files = files.filter((x) => /^(video|audio)\//.test(x.type));
  if (!files.length) return;
  const ids = [];
  for (const f of files) ids.push(await fingerprint(f));
  if (files.length > 1) {
    setContext({ name: "Archivos abiertos", items: ids, auto: true });
    files.slice(1).forEach((f, i) => importLocal(f, ids[i + 1]));
  }
  loadVideo(URL.createObjectURL(files[0]), ids[0], files[0].name, null, { file: files[0], keepContext: files.length > 1 });
}
$("#file").addEventListener("change", (e) => { openFiles([...e.target.files]); e.target.value = ""; });

window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  openFiles([...e.dataTransfer.files]);
});

// YouTube: el servidor descarga el video y responde yt_ready
function openYouTube(url) {
  if (!/(youtube\.com|youtu\.be)\//.test(url) && !/^[\w-]{11}$/.test(url)) return false;
  const list = (url.match(/[?&]list=([\w-]{10,})/) || [])[1];
  const isList = list && !/^(RD|UL)/.test(list);  // los mix automáticos no son playlists
  const hasVideo = /(?:v=|youtu\.be\/|shorts\/)[\w-]{11}/.test(url);
  if (isList && hasVideo) {
    // enlace de un video dentro de una playlist: elegir
    const dlg = $("#pl-dlg");
    dlg.returnValue = "";
    dlg.onclose = () => {
      if (dlg.returnValue === "playlist") addPlaylist(url);
      else if (dlg.returnValue === "video") openVideoLink(url);
    };
    dlg.showModal();
    return true;
  }
  if (isList) addPlaylist(url);
  else openVideoLink(url);
  return true;
}
function openVideoLink(url) {
  $("#file-name").textContent = "";
  setStatus("busy", "buscando video", false);
  send({ type: "youtube", url });
}
function addPlaylist(url) {
  setStatus("busy", "leyendo la playlist", false);
  send({ type: "playlist", url });
}
$("#yt").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#yt-url").value.trim();
  if (ytLinks(text).length > 1) return openMulti(text);
  openYouTube(text);
});
document.addEventListener("paste", (e) => {
  if (e.target.closest("textarea, dialog")) return;
  const text = e.clipboardData.getData("text").trim();
  if (ytLinks(text).length > 1) { e.preventDefault(); openMulti(text); return; }  // varios: cuadro para revisarlos
  if (e.target.closest("input")) return;
  if (openYouTube(text)) e.preventDefault();
});

/* ------------------------------------------------------------ varios enlaces */
function ytLinks(text) {
  const found = text.match(/(?:https?:\/\/)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\/[^\s,;"'<>]+/gi) || [];
  return [...new Set(found)];
}
function classify(url) {
  const v = (url.match(/(?:v=|youtu\.be\/|shorts\/|live\/)([\w-]{11})/) || [])[1];
  const list = (url.match(/[?&]list=([\w-]{10,})/) || [])[1];
  if (v) return { kind: "video", key: v };
  if (list && !/^(RD|UL)/.test(list)) return { kind: "playlist", key: list };
  return null;
}
function multiParsed() {
  const seen = new Set();
  const out = [];
  for (const u of ytLinks($("#multi-text").value)) {
    const c = classify(u);
    if (c && !seen.has(c.kind + c.key)) { seen.add(c.kind + c.key); out.push({ url: u, ...c }); }
  }
  return out;
}
function updateMulti() {
  const items = multiParsed();
  const nv = items.filter((x) => x.kind === "video").length;
  const np = items.length - nv;
  const known = items.filter((x) => x.kind === "video" && lib.videos["yt_" + x.key]).length;
  const parts = [];
  if (nv) parts.push(nv === 1 ? "1 video" : `${nv} videos`);
  if (np) parts.push(np === 1 ? "1 playlist" : `${np} playlists`);
  if (known) parts.push(known === 1 ? "1 ya está en la biblioteca" : `${known} ya están en la biblioteca`);
  $("#multi-sum").textContent = parts.join(" · ") || "sin enlaces de YouTube";
  $("#multi-go").disabled = !items.length;
}
function openMulti(text = "") {
  $("#multi-text").value = text;
  const sel = $("#multi-coll");
  sel.replaceChildren(new Option("Sin colección", ""));
  for (const c of lib.collections.filter((x) => x.kind === "propia")) sel.append(new Option(c.name, c.id));
  updateMulti();
  $("#yt-url").value = "";
  $("#multi-dlg").showModal();
  $("#multi-text").focus();
}
$("#multi-text").addEventListener("input", updateMulti);
$("#yt-multi").addEventListener("click", () => openMulti($("#yt-url").value.trim()));
$("#multi-dlg").addEventListener("close", () => {
  if ($("#multi-dlg").returnValue !== "ok") return;
  const items = multiParsed();
  if (!items.length) return;
  send({ type: "yt_batch", urls: items.map((x) => x.url), coll: $("#multi-coll").value });
  lib.sel = "all";
  setView("library");
});

(async () => {
  const params = new URLSearchParams(location.search);
  if (params.get("yt")) {
    const go = () => (state.ready ? openYouTube(params.get("yt")) : setTimeout(go, 300));
    go();
  }
  const src = params.get("src");
  if (src) {
    const abs = new URL(src, location.href).href;
    loadVideo(abs, await sha256(abs), decodeURIComponent(abs.split("/").pop()));
  }
})();

/* ------------------------------------------------------------ audio → servidor */
async function ensureAudio() {
  if (state.audio) {
    if (state.audio.ctx.state === "suspended") await state.audio.ctx.resume();
    return;
  }
  const ctx = new AudioContext({ latencyHint: "interactive" });
  state.audio = { ctx };
  await ctx.audioWorklet.addModule("capture-worklet.js");
  const src = ctx.createMediaElementSource(vEn);
  const node = new AudioWorkletNode(ctx, "capture", {
    numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
    processorOptions: { target: SR, chunk: 1600 },
  });
  const mute = ctx.createGain();
  mute.gain.value = 0;
  // original → (ganancia) → parlantes; la captura para el ASR va antes de la ganancia
  const orig = ctx.createGain();
  const dub = ctx.createGain();
  const master = ctx.createGain();  // volumen y silencio de los controles
  orig.gain.value = state.dubMode ? duck() : 1;
  master.gain.value = player.muted ? 0 : player.volume;
  master.connect(ctx.destination);
  src.connect(orig).connect(master);
  dub.connect(master);
  state.audio.orig = orig;
  state.audio.dub = dub;
  state.audio.master = master;
  src.connect(node);
  node.connect(mute).connect(ctx.destination);
  node.port.onmessage = (e) => onPcm(e.data);
  state.audio.node = node;
}

function isCovered(t) {
  return state.covered.some(([a, b]) => t >= a - 0.05 && t < b - 0.25);
}

function onPcm(pcm) {
  if (state.ahead || !state.ready || !state.videoId || vEn.paused || vEn.seeking) return;
  const t = Math.max(0, vEn.currentTime - pcm.length / SR);
  if (isCovered(vEn.currentTime)) {
    // tramo ya transcrito: se muestra lo guardado y no se gasta GPU
    if (state.sending) send({ type: "stop", t });
    state.sending = false;
    return;
  }
  state.sending = true;
  const buf = new ArrayBuffer(8 + pcm.byteLength);
  new DataView(buf).setFloat64(0, t, true);
  new Int16Array(buf, 8).set(pcm);
  state.ws.send(buf);
}

/* ------------------------------------------------------------ audio adelantado */
// El audio del archivo se decodifica en el navegador (ya re-muestreado a 16 kHz)
// y se envía por delante de la reproducción, al ritmo que el servidor procesa
// (un bloque por cada confirmación). Así subtítulos, traducción y voz en español
// están listos cuando el video llega a cada frase: todo suena sincronizado.
// Si el archivo no se puede decodificar, queda la captura en vivo como respaldo.
const AHEAD_OF_DUB = 25;  // segundos máximos de reconocimiento por delante de lo doblado
const AHEAD_CHUNK = 3.0;  // segundos por bloque (más grande = menos inferencias por segundo de video)
const feeder = { pcm: null, pos: 0, run: 0, spanStart: 0, inSpan: false, ack: null };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function prepareAhead(src) {
  const run = ++feeder.run;
  feeder.pcm = null;
  state.ahead = false;
  try {
    const data = await (await fetch(src)).arrayBuffer();
    const buf = await new OfflineAudioContext(1, 1, SR).decodeAudioData(data);
    if (run !== feeder.run) return;
    const n = buf.length;
    const mono = new Float32Array(n);
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < n; i++) mono[i] += d[i] / buf.numberOfChannels;
    }
    feeder.pcm = mono;
    feeder.pos = feeder.spanStart = vEn.currentTime || 0;
    feeder.inSpan = false;
    state.ahead = true;
    feedLoop(run);
  } catch (e) {
    state.ahead = false;  // respaldo: captura mientras se reproduce
  }
}

function waitAck(ms) {
  return new Promise((resolve) => {
    const t = setTimeout(() => { feeder.ack = null; resolve(); }, ms);
    feeder.ack = () => { clearTimeout(t); feeder.ack = null; resolve(); };
  });
}

async function feedLoop(run) {
  while (run === feeder.run) {
    if (!state.ready || !state.videoId || state.ws?.readyState !== WebSocket.OPEN) { await sleep(300); continue; }
    const total = feeder.pcm.length / SR;
    const span = state.covered.find(([a, b]) => feeder.pos >= a - 0.05 && feeder.pos < b - 0.25);
    if (span) {  // ya procesado: se salta
      if (feeder.inSpan) send({ type: "stop" });
      feeder.inSpan = false;
      feeder.pos = feeder.spanStart = span[1];
      continue;
    }
    // no alejarse demasiado de lo ya doblado: reconocimiento y voz comparten la GPU,
    // y lo urgente es doblar lo que se va a escuchar primero
    const lead = state.voice && state.voice !== "none" ? AHEAD_OF_DUB : 120;
    if (feeder.pos > Math.max(vEn.currentTime, dubFrontier()) + lead) { await sleep(400); continue; }
    if (feeder.pos >= total - 0.05) {
      if (feeder.inSpan) send({ type: "end" });
      feeder.inSpan = false;
      await sleep(500);
      continue;
    }
    const a = Math.floor(feeder.pos * SR);
    const b = Math.min(feeder.pcm.length, a + AHEAD_CHUNK * SR);
    const pcm = new Int16Array(b - a);
    for (let i = a; i < b; i++) pcm[i - a] = Math.max(-1, Math.min(1, feeder.pcm[i])) * 32767;
    const msg = new ArrayBuffer(8 + pcm.byteLength);
    new DataView(msg).setFloat64(0, a / SR, true);
    new Int16Array(msg, 8).set(pcm);
    const acked = waitAck(2500);
    state.ws.send(msg);
    feeder.inSpan = true;
    feeder.pos = b / SR;
    await acked;
  }
}

function processedSpan(t) {
  // tramo procesado continuo que contiene t (null si t aún no se procesó)
  return state.covered.find(([a, b]) => t >= a - 0.5 && t < b) || null;
}

function frontier(done) {
  // hasta dónde, desde el punto de reproducción, todo está listo según `done`;
  // nunca más allá del tramo procesado continuo (los huecos no están listos)
  const t = vEn.currentTime;
  const span = processedSpan(t);
  if (!span) return t;
  for (const s of state.segments) {
    if (s.end < t) continue;
    if (s.start >= span[1]) break;
    if (!done(s)) return Math.max(t, s.start);
  }
  return span[1];
}
const dubFrontier = () => frontier((s) => s.dub || !s.translation);

// el servidor dobla primero lo que se va a escuchar
setInterval(() => { if (state.videoId) send({ type: "pos", t: vEn.currentTime }); }, 1000);

function feederSeek(t) {
  if (state.serverSide) { send({ type: "pos", t }); return; }  // la cola salta con el video
  if (!state.ahead || isCovered(t)) return;
  // dentro del tramo que se está enviando no hace falta reiniciar
  if (t >= feeder.spanStart - 0.5 && t <= feeder.pos + 0.5) return;
  if (feeder.inSpan) send({ type: "seek", t });
  feeder.inSpan = false;
  feeder.pos = feeder.spanStart = t;
}


/* ------------------------------------------------------------ buen momento para reproducir */
// Compara lo ya doblado por delante del punto de reproducción con la velocidad
// real del procesamiento. La velocidad se mide en SEGUNDOS DE VOZ doblados por
// segundo: una intro sin voz se procesa casi al instante y, medida en segundos de
// video, daba un "listo" falso que se desincronizaba al empezar a hablar. Para lo
// que viene se asume una densidad de voz pesimista (al menos 70 %).
const readiness = { hist: [], ok: false, need: null };

function isReadyAt(t) {
  const span = processedSpan(t);
  if (!span) return false;
  return !state.segments.some((s) => s.end > t && s.start < t + 10 && !segDone(s) && s.start < span[1]);
}

function readyFrontier() {
  // sin voz basta la traducción
  return state.voice && state.voice !== "none" ? dubFrontier() : frontier((s) => !!s.translation);
}

const segDone = (s) => (state.voice && state.voice !== "none" ? !!s.dub : !!s.translation);

function speechDensity() {
  // fracción de voz en lo ya procesado de este video (mínimo 0.7: por delante puede haber más)
  const cov = state.covered.reduce((a, [x, y]) => a + (y - x), 0);
  const speech = state.segments.reduce((a, s) => a + (s.end - s.start), 0);
  return cov > 30 ? Math.min(1, Math.max(0.7, speech / cov)) : 1;
}

setInterval(() => {
  const box = $("#ready");
  if (!state.videoId || !vEn.duration || !state.ahead) { box.hidden = true; return; }
  const t = vEn.currentTime;
  const end = vEn.duration;
  const f = readyFrontier();
  const now = performance.now() / 1000;
  // voz lista acumulada del video (crece solo cuando se dobla voz, no con silencios)
  const voiced = state.segments.reduce((a, s) => a + (segDone(s) ? s.end - s.start : 0), 0);
  readiness.hist.push([now, voiced]);
  while (readiness.hist.length > 2 && now - readiness.hist[0][0] > 30) readiness.hist.shift();
  const h = readiness.hist;
  let rate = null;
  if (now - h[0][0] >= 8) {
    const mx = h.reduce((a, [x]) => a + x, 0) / h.length;
    const my = h.reduce((a, [, y]) => a + y, 0) / h.length;
    const sxy = h.reduce((a, [x, y]) => a + (x - mx) * (y - my), 0);
    const sxx = h.reduce((a, [x]) => a + (x - mx) ** 2, 0);
    rate = Math.max(0, sxy / (sxx || 1)) / speechDensity();  // segundos de video por segundo
  }
  const left = end - t;
  const MIN_LEAD = 12;
  // más lento que el video: el margen cubre lo que se perdería en los próximos minutos
  let need = 20;
  if (rate !== null) need = rate >= 1 ? MIN_LEAD : MIN_LEAD + Math.min(left, 300) * (1 - rate);
  readiness.need = readiness.need == null ? need : readiness.need * 0.8 + need * 0.2;
  need = Math.max(MIN_LEAD, Math.min(readiness.need, left));
  const lead = f - t;
  // histéresis: una vez listo, solo vuelve a "preparando" si el margen cae bastante
  // sin velocidad medida (primeros 8 s) basta con 30 s listos por delante: alcanza para
  // medirla reproduciendo, y si luego falta margen se pausa sola
  const SAFE_LEAD = 30;
  const ok = f >= end - 1 || lead >= (rate === null ? Math.min(SAFE_LEAD, left)
    : readiness.ok ? need * 0.6 : need);
  readiness.ok = ok;
  // esperar lo listo: arrancar (reproducción automática) o reanudar (pausa por falta de voz)
  const waitPref = prefs.wait_ready !== false;
  if (state.autoWait && vEn.paused && (ok || (!waitPref && vEn.readyState >= 3))) {
    state.autoWait = false;
    vEn.play().catch(() => {});
  } else if (!ok && waitPref && state.dubMode && !vEn.paused && !state.forcePlay && !state.sending) {
    // se reproduce algo aún sin voz en español (un salto o el doblaje se quedó atrás):
    // pausa y sigue sola al estar listo, así no hay cortes
    state.autoWait = true;
    vEn.pause();
  }
  box.dataset.state = ok ? "ok" : "wait";
  // al salir del reposo, los modelos tardan en cargar (la voz, hasta ~20 s): se dice
  box.querySelector("span").textContent = ok ? "Listo para reproducir"
    : state.power === "cargando" ? "Cargando modelos"
    : `${state.autoWait ? "Sigue al estar listo" : "Preparando"} ${Math.min(99, Math.round(lead / need * 100))} %`;
  box.querySelector("em").style.width = `${Math.min(100, lead / need * 100)}%`;
  // visible en pausa (para saber cuándo dar play) y mientras se reproduce solo si
  // el doblaje se queda corto; la preferencia puede ocultarlo del todo
  box.hidden = prefs.ready_chip === "nunca" || (ok && !vEn.paused && prefs.ready_chip !== "siempre");
}, 500);

/* ------------------------------------------------------------ sincronía de videos */
vEn.addEventListener("play", async () => {
  if (!state.audio) {
    // la captura tarda unos ms en montarse: se pausa, se monta y se reanuda en el
    // mismo punto para no perder las primeras palabras
    const t = vEn.currentTime;
    vEn.pause();
    await ensureAudio();
    vEn.currentTime = t;
    vEn.play();
    return;
  }
  ensureAudio();
  vEs.currentTime = vEn.currentTime;
  vEs.play().catch(() => {});
});
vEn.addEventListener("pause", () => {
  vEs.pause();
  // congela también la voz doblada en su punto (al terminar el video, que acabe la frase)
  if (!vEn.ended) state.audio?.ctx.suspend();
});
vEn.addEventListener("ended", () => {
  endLive("end");
  playNextInContext();  // playlist o varios abiertos: sigue el próximo
});
vEn.addEventListener("seeking", () => {
  state.forcePlay = false;  // tras un salto vuelve a esperar lo listo
  if (!vEn.paused) readiness.ok = isReadyAt(vEn.currentTime);
  vEs.currentTime = vEn.currentTime;
  stopDub();
  endLive("seek");
  feederSeek(vEn.currentTime);
});
vEn.addEventListener("ratechange", () => { vEs.playbackRate = vEn.playbackRate; });
vEn.addEventListener("timeupdate", () => {
  if (!vEn.paused && Math.abs(vEs.currentTime - vEn.currentTime) > 0.2) vEs.currentTime = vEn.currentTime;
  renderCaptions();
  renderActive();
  renderHead();
});

function endLive(kind) {
  if (state.sending) send({ type: kind, t: vEn.currentTime });
  state.sending = false;
  state.live = { committed: "", tentative: "" };
  renderCaptions();
}


/* ------------------------------------------------------------ voz en español */
// En vivo: cada frase doblada suena apenas está lista, una tras otra (como un
// intérprete). Al repetir: cada frase suena exactamente en su momento.
const DUCK_LEVELS = { silencio: 0, bajo: 0.14, medio: 0.3 };
const duck = () => DUCK_LEVELS[prefs.duck] ?? 0.14;  // volumen del original bajo la voz en español
const dubBuf = new Map();    // id de frase → AudioBuffer
const player = { cur: null, queue: [], volume: 1, muted: false };

let decodeCtx = null;
// a lo sumo 3 descargas de voz a la vez: el video y sus rangos siempre tienen conexión libre
const dubSlots = { busy: 0, wait: [] };
async function dubFetch(url) {
  while (dubSlots.busy >= 3) await new Promise((r) => dubSlots.wait.push(r));
  dubSlots.busy++;
  try { return await (await fetch(url)).arrayBuffer(); }
  finally { dubSlots.busy--; dubSlots.wait.shift()?.(); }
}

async function loadDub(seg) {
  if (!seg.dub) return;
  const url = seg.dub.url || "/audio/" + seg.dub.file;
  if (dubBuf.get(seg.id)?.url === url) return;
  dubBuf.set(seg.id, { url, buf: null });  // en curso
  try {
    const data = await dubFetch(url);
    // los AudioBuffer sirven en cualquier contexto: se decodifica aunque aún no haya reproducción
    const ctx = state.audio?.ctx || (decodeCtx ||= new OfflineAudioContext(1, 1, 48000));
    dubBuf.set(seg.id, { url, buf: await ctx.decodeAudioData(data) });
  } catch (e) {
    dubBuf.delete(seg.id);  // se reintenta en el próximo tick
  }
}

function stopDub() {
  if (player.cur) {
    try { player.cur.src.stop(); } catch (e) { /* ya terminó */ }
  }
  player.cur = null;
  player.queue = [];
}

function playDub(seg, offset = 0, rate = 1) {
  const item = dubBuf.get(seg.id);
  if (!item?.buf || !state.audio) return;
  const src = state.audio.ctx.createBufferSource();
  src.buffer = item.buf;
  src.playbackRate.value = rate;
  src.connect(state.audio.dub);
  src.start(0, offset);
  player.cur = { src, id: seg.id };
  src.onended = () => {
    if (player.cur?.src === src) {
      player.cur = null;
      liveNext();
    }
  };
}

function liveEnqueue(seg) {
  if (!state.dubMode) return;
  player.queue.push(seg);
  if (!player.cur) liveNext();
}

function liveNext() {
  const seg = player.queue.shift();
  if (!seg) return;
  // si se acumula retraso, se acelera un poco para alcanzar al video
  const lag = player.queue.reduce((a, s) => a + (s.dub?.dur || 0), 0);
  playDub(seg, 0, lag > 3 ? 1.12 : 1);
}

setInterval(() => {
  const t = vEn.currentTime;
  // precarga de las voces de los próximos 15 s
  for (const s of state.segments) {
    if (s.start > t + 15) break;
    if (s.dub && s.end > t - 1 && !dubBuf.has(s.id)) loadDub(s);
  }
  if (!state.dubMode || !state.audio || vEn.paused || state.sending || player.cur) return;
  for (const s of state.segments) {
    if (s.start > t) break;
    const d = s.dub;
    if (!d || t > s.start + d.dur - 0.15) continue;
    if (!dubBuf.get(s.id)?.buf) continue;
    playDub(s, Math.max(0, t - s.start));
    break;
  }
}, 80);

function setMode(dub) {
  state.dubMode = dub;
  for (const b of $("#c-lang").querySelectorAll("button")) b.classList.toggle("on", (b.dataset.v === "es") === dub);
  if (state.audio) state.audio.orig.gain.setTargetAtTime(dub ? duck() : 1, state.audio.ctx.currentTime, 0.05);
  if (!dub) stopDub();
}
$("#c-lang").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setMode(b.dataset.v === "es");
});
setMode(state.dubMode);

/* ------------------------------------------------------------ render */
function segmentAt(t) {
  let found = null;
  for (const s of state.segments) {
    if (s.start - 0.15 <= t && t <= s.end + 0.6) found = s;
    if (s.start > t) break;
  }
  return found;
}

// Subtítulos de máximo 2 líneas: el texto se parte en bloques de ~capMax()
// caracteres (cortando de preferencia tras puntuación).
const capMax = () => (window.innerWidth < 760 ? 50 : 88);

function chunks(text) {
  const CAP_MAX = capMax();
  const out = [];
  let cur = "";
  for (const w of text.split(/\s+/).filter(Boolean)) {
    if (cur && cur.length + 1 + w.length > CAP_MAX) {
      out.push(cur);
      cur = w;
    } else {
      cur = cur ? cur + " " + w : w;
    }
    if (cur.length > CAP_MAX * 0.55 && /[,.;:?!]$/.test(w)) {
      out.push(cur);
      cur = "";
    }
  }
  if (cur) out.push(cur);
  return out;
}

// repetición: el bloque que corresponde al momento t dentro de la frase
function chunkAt(text, start, end, t) {
  const cs = chunks(text);
  if (cs.length < 2) return text;
  const total = cs.reduce((a, c) => a + c.length, 0);
  const f = (t - start) / Math.max(0.1, end - start);
  let acc = 0;
  for (const c of cs) {
    acc += c.length;
    if (f <= acc / total) return c;
  }
  return cs[cs.length - 1];
}

// en vivo: el último bloque, separando confirmado / tentativo
function liveTail(committed, tentative) {
  const c = committed.trim().replace(/\s+/g, " ");
  const full = [c, tentative.trim().replace(/\s+/g, " ")].filter(Boolean).join(" ");
  const cs = chunks(full);
  const last = cs.length ? cs[cs.length - 1] : "";
  const from = full.length - last.length;
  const cut = Math.max(0, c.length - from);
  return [last.slice(0, cut), last.slice(cut)];
}

function renderCaptions() {
  const t = vEn.currentTime;
  const capEn = $("#cap-en");
  const capEs = $("#cap-es");
  let c = "", tt = "", es = "";
  const live = state.sending && (state.live.committed || state.live.tentative);
  if (live) {
    [c, tt] = liveTail(state.live.committed, state.live.tentative);
    const ces = chunks(state.live.es || "");
    es = ces.length ? ces[ces.length - 1] : "";
  } else {
    let seg = segmentAt(t);
    let at = t;
    if (!seg && state.sending && state.lastSeg && performance.now() - state.lastSegAt < 2500) {
      seg = state.lastSeg;
      at = seg.end;
    }
    if (seg) {
      c = chunkAt(seg.text, seg.start, seg.end, at);
      es = seg.translation ? chunkAt(seg.translation, seg.start, seg.end, at) : "";
    }
  }
  capEn.querySelector(".c").textContent = c;
  capEn.querySelector(".t").textContent = c && tt && !tt.startsWith(" ") ? " " + tt : tt;
  capEn.classList.toggle("hidden", !c && !tt);
  capEs.querySelector(".c").textContent = es;
  capEs.classList.toggle("hidden", !es);
  const wide = $("#cap-es-wide");
  wide.querySelector(".c").textContent = es;
  wide.classList.toggle("hidden", !es);
}

function fmt(t) {
  const s = Math.floor(t);
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor(s / 60) % 60).padStart(h ? 2 : 1, "0");
  return (h ? h + ":" : "") + mm + ":" + String(s % 60).padStart(2, "0");
}

function renderTranscript() {
  const ol = $("#transcript");
  const frag = document.createDocumentFragment();
  // personas numeradas por orden de aparición
  const speakers = new Map();
  for (const s of state.segments) {
    if (s.speaker != null && !speakers.has(s.speaker)) speakers.set(s.speaker, speakers.size + 1);
  }
  for (const s of state.segments) {
    const li = document.createElement("li");
    li.dataset.start = s.start;
    li.dataset.id = s.id;
    const who = s.speaker != null && speakers.size > 1 ? `<span class="spk">P${speakers.get(s.speaker)}</span>` : "";
    const time = `<time>${fmt(s.start)}${who}</time>`;
    li.innerHTML = `<div class="cell">${time}<p></p></div><div class="cell">${time}<p></p></div>`;
    const [en, es] = li.querySelectorAll("p");
    en.textContent = s.text;
    es.textContent = s.translation || "—";
    es.classList.toggle("pending", !s.translation);
    const notes = state.comments[String(s.id)] || [];
    const editingHere = state.editing?.seg === s.id;
    li.classList.toggle("has-notes", notes.length > 0);
    li.append(Object.assign(document.createElement("button"), {
      type: "button", className: "cbtn", textContent: "+", title: "Comentar esta frase", ariaLabel: "Comentar esta frase" }));
    if (notes.length || editingHere) li.append(renderNotes(s.id, notes));
    frag.appendChild(li);
  }
  const focused = document.activeElement?.closest?.(".ceditor") ? state.editing : null;
  ol.replaceChildren(frag);
  if (focused) {  // al redibujar (llega una frase nueva) el cuadro sigue donde estaba
    const ta = ol.querySelector(".ceditor textarea");
    ta?.focus();
    ta?.setSelectionRange(ta.value.length, ta.value.length);
  }
  renderActive(true);
}

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
    meta.textContent = `${when.toLocaleDateString("es", { day: "numeric", month: "short" })} ${when.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}${c.updated ? " · editado" : ""}`;
    const acts = document.createElement("span");
    acts.className = "nacts";
    acts.append(noteBtn("Editar", () => { state.editing = { seg: segId, id: c.id, draft: c.text }; renderTranscript(); focusEditor(); }),
      noteBtn("Eliminar", async () => {
        if (await confirmDlg("¿Eliminar este comentario?", "", "Eliminar")) {
          send({ type: "comment_delete", video: state.videoId, seg: segId, id: c.id });
        }
      }));
    item.append(text, meta, acts);
    box.append(item);
  }
  if (state.editing?.seg === segId && state.editing.id === null) box.append(noteEditor());
  return box;
}
function noteBtn(text, fn) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = text;
  b.addEventListener("click", fn);
  return b;
}
function noteEditor() {
  const ed = state.editing;
  const form = document.createElement("form");
  form.className = "ceditor";
  const ta = document.createElement("textarea");
  ta.rows = 3;
  ta.maxLength = 4000;
  ta.placeholder = "Comentario";
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
  const cancel = Object.assign(document.createElement("button"), { type: "button", className: "btn ghost", textContent: "Cancelar" });
  cancel.addEventListener("click", () => { state.editing = null; renderTranscript(); });
  const save = Object.assign(document.createElement("button"), { type: "submit", className: "btn dark", textContent: "Guardar" });
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
  const ta = $("#transcript .ceditor textarea");
  if (!ta) return;
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.closest("li").scrollIntoView({ block: "nearest" });
}

// diálogo de confirmación con el estilo de la página
function confirmDlg(title, text, okLabel) {
  const dlg = $("#confirm-dlg");
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  $("#confirm-ok").textContent = okLabel;
  dlg.returnValue = "";
  dlg.showModal();
  return new Promise((resolve) => dlg.addEventListener("close", () => resolve(dlg.returnValue === "ok"), { once: true }));
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
  vEn.removeAttribute("src");
  vEs.removeAttribute("src");
  vEn.load();
  document.title = "Traductor de video";
  renderTranscript();
  setView("library");
}

function renderActive(force) {
  const t = vEn.currentTime;
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
  const li = e.target.closest("li");
  if (!li || e.target.closest(".notes")) return;
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
  // vista dividida: bajo el video en español, las frases traducidas
  const tl = $("#tl-es");
  paintRanges(tl, state.segments.filter((s) => s.translation).map((s) => [s.start, s.end]), d);
  if (d && isFinite(d)) tl.append(Object.assign(document.createElement("i"), { className: "head" }));
  renderHead();
}

function renderHead() {
  const d = vEn.duration;
  const t = vEn.currentTime;
  $("#c-time").textContent = `${fmt(t)} / ${d && isFinite(d) ? fmt(d) : "0:00"}`;
  if (!d || !isFinite(d)) return;
  const pct = `${Math.min(100, (t / d) * 100)}%`;
  $("#t-play").style.width = pct;
  $("#t-head").style.left = pct;
  document.querySelectorAll(".timeline .head").forEach((h) => { h.style.left = pct; });
}

vEn.addEventListener("loadedmetadata", renderTimeline);

connect();

/* ------------------------------------------------------------ reposo */
// estado en palabras simples; el detalle técnico queda al pasar el mouse
function renderPower() {
  if (!state.ready) return;
  const p = state.power || "reposo";
  const q = typeof lib !== "undefined" ? lib.queue : null;
  const run = q?.jobs.find((j) => j.state === "procesando");
  const dl = q?.jobs.find((j) => j.dl);
  if (run) setStatus("ok", `procesando · ${Math.round(run.dub * 100)} %`);
  else if (dl) setStatus("busy", "descargando");
  else if (p === "cargando") setStatus("busy", "cargando modelos");
  else if (p === "reposo") setStatus("sleep", "en reposo");
  else setStatus("ok", "listo");
  $("#status").title = [state.models, state.metrics].filter(Boolean).join(" · ");
}

/* ------------------------------------------------------------ vista ampliada / dividida */
function setLayout(wide, save = true) {
  document.body.classList.toggle("layout-wide", wide);
  $("#layout").textContent = wide ? "Ver dividido" : "Ver ampliado";
  if (save) setPref("layout", wide ? "ampliada" : "dividida");
  renderActive(true);
}
$("#layout").addEventListener("click", () => setLayout(!document.body.classList.contains("layout-wide")));

/* ------------------------------------------------------------ preferencias */
function setPref(key, value) {
  prefs[key] = value;
  send({ type: "prefs_set", key, value });
}

function applyPrefs(m) {
  prefsSchema = m.schema;
  prefsSections = m.sections || [];
  prefs = { ...prefs, ...m.values };
  setLayout(prefs.layout !== "dividida", false);
  document.body.classList.toggle("no-sub-es", !prefs.sub_es);
  document.body.classList.toggle("no-sub-en", !prefs.sub_en);
  if (state.audio) state.audio.orig.gain.value = state.dubMode ? duck() : 1;
  renderPrefs();
  if (typeof renderLibrary === "function") renderLibrary();
}

const YT_IMPORT = $("#yt-import");
// Pantalla de preferencias: índice a la izquierda (sección → cada opción) y todas
// las opciones a la derecha, agrupadas por sección.
function renderPrefs() {
  const nav = $("#prefs-nav");
  const body = $("#prefs-body");
  const scroll = body.scrollTop;
  $("#stash").append(YT_IMPORT);  // se vuelve a poner en su sección (no se pierde al redibujar)
  nav.replaceChildren();
  body.replaceChildren();
  for (const [sec, title] of prefsSections) {
    const items = prefsSchema.filter((p) => p.section === sec);
    const box = document.createElement("section");
    box.className = "prefs-sec";
    box.id = `sec-${sec}`;
    const h = document.createElement("h3");
    h.textContent = title;
    box.append(h);
    const h4 = document.createElement("h4");
    h4.textContent = title;
    nav.append(h4);
    for (const p of items) {
      const row = document.createElement("div");
      row.className = "pref";
      row.id = `pref-${p.key}`;
      const label = document.createElement("span");
      label.className = "pref-label";
      label.textContent = p.label;
      const ctl = document.createElement("div");
      ctl.className = "pref-ctl";
      const group = document.createElement("div");
      group.className = "segs";
      const opts = p.type === "bool" ? [[true, "Sí"], [false, "No"]] : p.options;
      for (const [value, text] of opts) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "seg" + (prefs[p.key] === value ? " on" : "");
        b.textContent = text;
        b.addEventListener("click", () => { setPref(p.key, value); renderPrefs(); });
        group.append(b);
      }
      ctl.append(group);
      row.append(label, ctl);
      box.append(row);
      nav.append(navButton(p.label, row));
    }
    if (sec === "youtube") {
      box.append(YT_IMPORT);
      nav.append(navButton("Importar sesión", YT_IMPORT));
    }
    body.append(box);
  }
  body.scrollTop = scroll;
  markPrefsNav();
}
function navButton(text, target) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = text;
  b.dataset.target = target.id;
  b.addEventListener("click", () => target.scrollIntoView({ behavior: "smooth", block: "start" }));
  return b;
}
// la opción visible arriba queda marcada en el índice
function markPrefsNav() {
  const body = $("#prefs-body");
  const top = body.getBoundingClientRect().top;
  let cur = null;
  for (const row of body.querySelectorAll(".pref")) {
    if (row.getBoundingClientRect().top - top <= 40) cur = row.id;
  }
  cur ||= body.querySelector(".pref")?.id;
  if (body.scrollTop + body.clientHeight >= body.scrollHeight - 4) cur = [...body.querySelectorAll(".pref")].pop()?.id;
  for (const b of $("#prefs-nav").querySelectorAll("button")) b.classList.toggle("on", b.dataset.target === cur);
}
$("#prefs-body").addEventListener("scroll", markPrefsNav, { passive: true });
$("#prefs-btn").addEventListener("click", () => togglePrefs());

/* ------------------------------------------------------------ pestañas: transcripción / siguientes */
function setSideTab(tab) {
  for (const b of $("#side-tabs").querySelectorAll("button")) b.classList.toggle("on", b.dataset.tab === tab);
  $("#transcript").hidden = tab !== "transcript";
  $("#upnext").hidden = tab !== "upnext";
  if (tab === "transcript") renderActive(true);
  else renderUpNext(true);
}
$("#side-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setSideTab(b.dataset.tab);
});

/* ------------------------------------------------------------ descargas */
const DOWNLOAD_STEPS = [["buscando", "Buscando"], ["video", "Video"], ["audio", "Audio"],
  ["uniendo", "Uniendo"], ["preparando", "Preparando"]];
function downloadText(m) {
  const name = (DOWNLOAD_STEPS.find(([k]) => k === m.stage) || [, m.stage])[1].toLowerCase();
  return m.stage === "video" || m.stage === "audio" ? `descargando ${name} ${m.pct} %` : `${name}…`;
}

/* ------------------------------------------------------------ avisos */
let toastTimer = null;
function toast(text, kind = "error") {
  const t = $("#toast");
  t.textContent = text;
  t.dataset.kind = kind;  // error (rojo) · ok (verde) · warn (ámbar)
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 15000);
}
$("#toast").addEventListener("click", () => { $("#toast").hidden = true; });

/* ------------------------------------------------------------ sesión de YouTube */
// Importarla desde un navegador detectado o subir el cookies.txt exportado.
function renderCookies(m) {
  const box = $("#yt-browsers");
  box.replaceChildren();
  for (const b of m.browsers) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "seg";
    btn.textContent = `Importar de ${b.name}`;
    btn.addEventListener("click", () => {
      $("#cookies-status").textContent = `leyendo la sesión de ${b.name}…`;
      send({ type: "cookies_import", browser: b.key });
    });
    box.append(btn);
  }
  const st = m.status || {};
  $("#cookies-status").textContent = st.present
    ? `Sesión importada · ${st.count} cookies · ${st.logged_in ? "con sesión iniciada" : "sin sesión iniciada"} · ${st.updated}`
    : "Sin sesión importada";
  if (m.error) toast(m.error);
  if (m.imported) {
    const src = m.imported.source === "archivo" ? "del archivo" : `de ${m.imported.source}`;
    if (m.imported.logged_in) toast(`Sesión de YouTube importada ${src}. Las descargas ya la usan.`, "ok");
    else toast(`Se importaron cookies ${src}, pero sin sesión iniciada en YouTube: inicia sesión ahí y vuelve a importar.`, "warn");
  }
}

$("#cookies-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  $("#cookies-status").textContent = "importando el archivo…";
  try {
    const r = await fetch("/api/cookies", { method: "PUT", body: f });
    if (!r.ok) toast(`No se pudo importar: ${await r.text()}`);
  } catch (err) {
    toast("No se pudo subir el archivo.");
  }
});

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
$("#track").addEventListener("pointerdown", (e) => {
  if (!vEn.duration) return;
  const track = $("#track");
  track.setPointerCapture(e.pointerId);
  vEn.currentTime = trackTime(e);
  const move = (ev) => { vEn.currentTime = trackTime(ev); };
  const up = () => { track.removeEventListener("pointermove", move); track.removeEventListener("pointerup", up); };
  track.addEventListener("pointermove", move);
  track.addEventListener("pointerup", up);
});
$("#track").addEventListener("pointermove", (e) => {
  if (!vEn.duration) return;
  const tip = $("#t-tip");
  const r = $("#track").getBoundingClientRect();
  tip.textContent = fmt(trackTime(e));
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

function toggleFull() {
  if (document.fullscreenElement) document.exitFullscreen();
  else $("#pane-en").requestFullscreen?.().catch(() => {});
}
$("#c-full").addEventListener("click", toggleFull);
vEn.addEventListener("dblclick", toggleFull);

// teclado: espacio reproduce, flechas ±5 s, f pantalla completa, m silencio
document.addEventListener("keydown", (e) => {
  if (currentView() !== "player" || e.target.closest("input, textarea, select, dialog") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === " " || e.key === "k") { e.preventDefault(); togglePlay(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); vEn.currentTime = Math.max(0, vEn.currentTime - 5); }
  else if (e.key === "ArrowRight") { e.preventDefault(); vEn.currentTime = Math.min(vEn.duration || 0, vEn.currentTime + 5); }
  else if (e.key === "f") toggleFull();
  else if (e.key === "m") setVolume(player.volume || 1, !player.muted);
});
