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
};

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
      setStatus("ok", `${m.device} · ${m.model}${m.translator !== "none" ? " · " + m.translator : ""}`);
      if (state.videoId) send({ type: "open", id: state.videoId, name: state.videoName });
      break;
    case "transcript":
      if (m.id !== state.videoId) return;
      state.segments = m.segments;
      state.covered = m.covered;
      for (const s of state.segments) if (s.dub) loadDub(s);
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
      loadDub(seg).then(() => {
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
    case "covered":
      state.covered = m.ranges;
      renderTimeline();
      break;
    case "stats":
      if (feeder.ack) feeder.ack();
      $("#metrics").textContent = `inferencia ${m.infer_ms} ms · búfer ${m.buffer_s.toFixed(1)} s`;
      break;
  }
  renderCaptions();
}

function setStatus(kind, text) {
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

function loadVideo(src, id, name) {
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
  prepareAhead(src);
  $("#file-name").textContent = name;
  document.title = `${name} · Traductor`;
  renderTranscript();
  renderTimeline();
  renderCaptions();
  send({ type: "open", id, name });
}

$("#file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (f) loadVideo(URL.createObjectURL(f), await fingerprint(f), f.name);
});

window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", async (e) => {
  e.preventDefault();
  const f = [...e.dataTransfer.files].find((x) => /^(video|audio)\//.test(x.type));
  if (f) loadVideo(URL.createObjectURL(f), await fingerprint(f), f.name);
});

(async () => {
  const src = new URLSearchParams(location.search).get("src");
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
  orig.gain.value = state.dubMode ? DUCK : 1;
  src.connect(orig).connect(ctx.destination);
  dub.connect(ctx.destination);
  state.audio.orig = orig;
  state.audio.dub = dub;
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
const AHEAD_CHUNK = 1.5;  // segundos por bloque
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

function feederSeek(t) {
  if (!state.ahead || isCovered(t)) return;
  // dentro del tramo que se está enviando no hace falta reiniciar
  if (t >= feeder.spanStart - 0.5 && t <= feeder.pos + 0.5) return;
  if (feeder.inSpan) send({ type: "seek", t });
  feeder.inSpan = false;
  feeder.pos = feeder.spanStart = t;
}

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
vEn.addEventListener("ended", () => endLive("end"));
vEn.addEventListener("seeking", () => {
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
const DUCK = 0.14;           // volumen del original mientras se escucha en español
const dubBuf = new Map();    // id de frase → AudioBuffer
const player = { cur: null, queue: [] };

let decodeCtx = null;
async function loadDub(seg) {
  if (!seg.dub) return;
  const url = seg.dub.url || "/audio/" + seg.dub.file;
  if (dubBuf.get(seg.id)?.url === url) return;
  dubBuf.set(seg.id, { url, buf: null });  // en curso
  try {
    const data = await (await fetch(url)).arrayBuffer();
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
  $("#mode").textContent = dub ? "Escuchar original" : "Escuchar en español";
  if (state.audio) state.audio.orig.gain.setTargetAtTime(dub ? DUCK : 1, state.audio.ctx.currentTime, 0.05);
  if (!dub) stopDub();
}
$("#mode").addEventListener("click", () => setMode(!state.dubMode));
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
    frag.appendChild(li);
  }
  ol.replaceChildren(frag);
  renderActive(true);
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
  if (performance.now() - state.userScrollAt > 3000) {
    const top = next.offsetTop - ol.offsetTop - ol.clientHeight / 3;
    ol.scrollTo({ top, behavior: force ? "auto" : "smooth" });
  }
}

$("#transcript").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (li) vEn.currentTime = parseFloat(li.dataset.start);
});
$("#transcript").addEventListener("wheel", () => { state.userScrollAt = performance.now(); }, { passive: true });
$("#transcript").addEventListener("touchmove", () => { state.userScrollAt = performance.now(); }, { passive: true });

function renderTimeline() {
  const d = vEn.duration;
  for (const id of ["#tl-en", "#tl-es"]) {
    const tl = $(id);
    tl.replaceChildren();
    if (!d || !isFinite(d)) continue;
    // EN: rangos transcritos. ES: frases con traducción.
    const ranges = id === "#tl-en"
      ? state.covered
      : state.segments.filter((s) => s.translation).map((s) => [s.start, s.end]);
    for (const [a, b] of ranges) {
      const el = document.createElement("b");
      el.style.left = `${(a / d) * 100}%`;
      el.style.width = `${Math.max(0.2, ((b - a) / d) * 100)}%`;
      tl.appendChild(el);
    }
    const head = document.createElement("i");
    head.className = "head";
    tl.appendChild(head);
  }
  renderHead();
}

function renderHead() {
  const d = vEn.duration;
  if (!d) return;
  document.querySelectorAll(".timeline .head").forEach((h) => { h.style.left = `${(vEn.currentTime / d) * 100}%`; });
}

vEn.addEventListener("loadedmetadata", renderTimeline);

connect();
