"use strict";
// El audio del video hacia el servidor, el audio procesado por delante, cuándo conviene
// reproducir, la sincronía entre los videos, la voz doblada sobre el original y el selector de idioma.
// Comparte el ámbito global con app.js (se carga justo después).

/* ------------------------------------------------------------ audio → servidor */
async function ensureAudio() {
  if (state.audio) {
    if (state.audio.ctx.state === "suspended") await state.audio.ctx.resume();
    return;
  }
  const ctx = new AudioContext({ latencyHint: "interactive" });
  const src = ctx.createMediaElementSource(vEn);
  // original → (ganancia) → parlantes; la captura para el ASR va antes de la ganancia
  const orig = ctx.createGain();
  const dub = ctx.createGain();
  const master = ctx.createGain();  // volumen y silencio de los controles
  orig.gain.value = state.dubMode ? duck() : 1;
  master.gain.value = player.muted ? 0 : player.volume;
  master.connect(ctx.destination);
  src.connect(orig).connect(master);
  dub.connect(master);
  state.audio = { ctx, orig, dub, master };  // completo antes de esperar nada: la voz ya puede sonar
  // la captura (reconocer en vivo lo que suena) necesita https o este equipo; sin ella,
  // lo hace la cola del servidor
  if (!ctx.audioWorklet) return;
  try {
    await ctx.audioWorklet.addModule("js/capture-worklet.js");
  } catch (e) {
    console.warn("sin captura de audio", e);
    return;
  }
  const node = new AudioWorkletNode(ctx, "capture", {
    numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
    processorOptions: { target: SR, chunk: 1600 },
  });
  const mute = ctx.createGain();
  mute.gain.value = 0;
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
    const lead = wantsVoice() ? AHEAD_OF_DUB : 120;
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
  return wantsVoice() ? dubFrontier() : frontier((s) => !!s.translation);
}

const segDone = (s) => (wantsVoice() ? !!s.dub : !!s.translation);

function speechDensity() {
  // fracción de voz en lo ya procesado de este video (mínimo 0.7: por delante puede haber más)
  const cov = state.covered.reduce((a, [x, y]) => a + (y - x), 0);
  const speech = state.segments.reduce((a, s) => a + (s.end - s.start), 0);
  return cov > 30 ? Math.min(1, Math.max(0.7, speech / cov)) : 1;
}

setInterval(() => {
  const box = $("#ready");
  if (!state.videoId || !vEn.duration) { box.hidden = true; return; }
  if (!state.translates && state.lang) {
    // en su idioma (p. ej. ya en español) no hay voz que esperar: se reproduce siempre; lo que aún no
    // se transcribió se marca en la transcripción y se transcribe mientras se escucha
    box.hidden = true;
    readiness.ok = true;
    if (state.autoWait && vEn.paused && vEn.readyState >= 2) {
      state.autoWait = false;
      vEn.play().catch(() => {});
    }
    return;
  }
  if (!state.ahead) { box.hidden = true; return; }
  const pos = vEn.currentTime;
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
  const left = end - pos;
  const MIN_LEAD = 12;
  // más lento que el video: el margen cubre lo que se perdería en los próximos minutos
  let need = 20;
  if (rate !== null) need = rate >= 1 ? MIN_LEAD : MIN_LEAD + Math.min(left, 300) * (1 - rate);
  readiness.need = readiness.need == null ? need : readiness.need * 0.8 + need * 0.2;
  need = Math.max(MIN_LEAD, Math.min(readiness.need, left));
  const lead = f - pos;
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
  const readyPct = Math.min(99, Math.round(lead / need * 100));
  box.querySelector("span").textContent = ok ? t("Listo para reproducir")
    : state.power === "cargando" ? t("Cargando modelos")
    : state.autoWait ? t("Se reanuda al estar listo {pct} %", { pct: readyPct }) : t("Preparando {pct} %", { pct: readyPct });
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
vEn.addEventListener("ratechange", () => {
  vEs.playbackRate = vEn.playbackRate;
  stopDub();  // la frase en curso se retoma a la nueva velocidad
  rollRate(vEn.playbackRate);
});
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
  try {
    const res = await fetch(url);
    if (!res.ok) throw Object.assign(new Error(`voz ${res.status}`), { status: res.status });
    return await res.arrayBuffer();
  }
  finally { dubSlots.busy--; dubSlots.wait.shift()?.(); }
}

async function loadDub(seg) {
  if (!seg.dub) return;
  const url = seg.dub.url || (state.prefix || "") + "/audio/" + seg.dub.file;
  const had = dubBuf.get(seg.id);
  if (had?.url === url && !(had.retryAt && Date.now() >= had.retryAt)) return;
  dubBuf.set(seg.id, { url, buf: null });  // en curso
  try {
    const data = await dubFetch(url);
    // los AudioBuffer sirven en cualquier contexto: se decodifica aunque aún no haya reproducción
    const ctx = state.audio?.ctx || (decodeCtx ||= new OfflineAudioContext(1, 1, 48000));
    dubBuf.set(seg.id, { url, buf: await ctx.decodeAudioData(data) });
  } catch (e) {
    // si el archivo no existe (404) no se vuelve a pedir; si falló la red, se reintenta en unos segundos (antes se
    // reintentaba en cada vuelta: miles de pedidos por un archivo que faltaba)
    if (e.status === 404 || e.status === 410) dubBuf.set(seg.id, { url, buf: null, missing: true });
    else dubBuf.set(seg.id, { url, buf: null, retryAt: Date.now() + 5000 });
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
  if (vEn.playbackRate !== 1) return playDubStretched(seg, item, offset, rate * vEn.playbackRate);
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

// otra velocidad: la voz va por un <audio> que acelera sin cambiar el tono (preservesPitch)
function playDubStretched(seg, item, offset, rate) {
  const a = new Audio(item.url);
  a.preservesPitch = true;
  a.playbackRate = rate;
  a.currentTime = offset;
  const node = state.audio.ctx.createMediaElementSource(a);
  node.connect(state.audio.dub);
  // al terminar o cortarse, el elemento y su nodo se sueltan (si no, se acumulan frase a frase)
  const release = () => { a.pause(); node.disconnect(); a.removeAttribute("src"); a.load(); };
  const handle = { stop: release };
  player.cur = { src: handle, id: seg.id };
  a.addEventListener("ended", () => {
    release();
    if (player.cur?.src === handle) {
      player.cur = null;
      liveNext();
    }
  });
  a.play().catch(() => {});
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
    const b = dubBuf.get(s.id);
    if (s.dub && s.end > t - 1 && (!b || (b.retryAt && Date.now() >= b.retryAt))) loadDub(s);
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
  dub = dub && state.translates;
  state.dubMode = dub;
  renderLangPick();
  if (state.audio) state.audio.orig.gain.setTargetAtTime(dub ? duck() : 1, state.audio.ctx.currentTime, 0.05);
  if (!dub) stopDub();
}
// idioma del video abierto. Si solo se transcribe: se escucha el original, con un solo
// subtítulo (en su idioma) y una columna
function applyLang(lang, translates) {
  state.lang = lang || "";
  state.translates = translates ?? translatesV({ lang });
  const code = state.lang ? state.lang.toUpperCase() : t("Original");
  $("#pane-en .tag").textContent = state.lang ? t("{code} · original", { code }) : t("Original");
  document.body.classList.toggle("native", !state.translates);
  setMode(state.translates && prefs.audio !== "original");
  // dividida mostraría el mismo video dos veces: siempre ampliada (sin cambiar la preferencia)
  setLayout(!state.translates || prefs.layout !== "dividida", false);
}
// el idioma que se escucha: el original o cualquiera de los de destino. Uno en el que el video todavía no está se
// elige igual (pasa a ser «Traducir a») y se procesa ahí mismo: la traducción y la voz llegan mientras se mira
const PICK_LANGS = ["es", "en", "pt"];
const capLang = (code) => { const n = langName(code); return n.charAt(0).toUpperCase() + n.slice(1); };
function renderLangPick() {
  const name = $("#c-lang-name");
  if (!name) return;
  name.textContent = state.dubMode ? capLang(TARGET) : (state.lang ? capLang(state.lang) : t("Original"));
}
function openLangPick() {
  const menu = $("#c-lang-menu"), btn = $("#c-lang-btn");
  // en la misma barra, uno al lado del otro: el que aún no está se marca tenue y lo dice al pasar el mouse
  const item = (label, note, on, act) => el("button", { type: "button", role: "option", class: (on ? "on" : "") + (note && note !== t("Original") ? " later" : ""),
    "aria-selected": String(on), title: note || null, on: { click: () => { closeLangPick(); act(); } } }, label,
    // el que todavía hay que procesar lleva su marca: así se sabe antes de elegirlo
    note && note !== t("Original") ? el("span", { class: "c-lang-todo", "aria-hidden": "true" }, icon("reload")) : null);
  const items = [item(state.lang ? capLang(state.lang) : t("Original"), t("Original"), !state.dubMode, () => setMode(false))];
  for (const code of PICK_LANGS) {
    if (code === state.lang) continue;
    const current = code === TARGET && state.translates;
    items.push(item(capLang(code), current ? "" : t("Se prepara al elegirlo"), current && state.dubMode, () => {
      if (current) { setMode(true); return; }
      // otro idioma: el servidor vuelve a abrir el video en él y lo que falte se traduce y dobla (case "target")
      setPref("target_lang", code);
      toast(t("Preparando el video en {lang}", { lang: langName(code) }), "ok");
    }));
  }
  menu.replaceChildren(...items);
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
}
function closeLangPick() {
  $("#c-lang-menu").hidden = true;
  $("#c-lang-btn").setAttribute("aria-expanded", "false");
}
$("#c-lang-btn").addEventListener("click", () => ($("#c-lang-menu").hidden ? openLangPick() : closeLangPick()));
document.addEventListener("pointerdown", (e) => { if (!$("#c-lang-menu").hidden && !$("#c-lang").contains(e.target)) closeLangPick(); }, true);
$("#c-lang-menu").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeLangPick(); $("#c-lang-btn").focus(); } });
setMode(state.dubMode);
