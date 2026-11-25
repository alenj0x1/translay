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
  lang: "en",          // idioma en que se habla el video abierto ("" mientras se detecta)
  translates: true,    // se traduce y dobla; si no, solo se transcribe (en su idioma, sin voz)
  ahead: false,        // audio del archivo procesado por delante de la reproducción
  downloads: {},       // descargas de YouTube en curso: id → {title, stage, pct}
  comments: {},        // id de frase → [{id, text, created, updated}]
  people: { names: {}, voices: {}, refs: {} },  // «Personas»: nombre, voz elegida y voz de referencia
  editing: null,       // comentario en edición: {seg, id (null = nuevo), draft}
};

// preferencias guardadas en el servidor (vt/prefs.py); valores por defecto hasta recibirlas
let prefs = { theme_mode: "sistema", layout: "ampliada", audio: "es", duck: "bajo", sub_es: true, sub_orig: true, ready_chip: "auto",
  autoplay: true, autoplay_next: true };
let prefsAltSections = {};
let prefsGroups = [];  // bloques del inicio de Ajustes (vt/prefs.py › SECTION_GROUPS)
let prefsSchema = [];
let prefsSections = [];
let prefsVaultKeys = [];  // las que son de cada biblioteca (vt/vaults.py)

/* ------------------------------------------------------------ conexión */
function connect() {
  // /b/<biblioteca>: la página abre esa biblioteca (y es lo único que ve un invitado)
  const libPath = (location.pathname.match(/^\/b\/([a-z0-9-]+)/) || [])[1];
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws${libPath ? `?lib=${libPath}` : ""}`);
  ws.binaryType = "arraybuffer";
  setStatus("busy", t("conectando"));
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    state.ready = false;
    setStatus("off", t("sin conexión"));
    setTimeout(connect, 1000);
  };
  state.ws = ws;
}

// Lo que se edita se ve al instante: cada tipo de mensaje puede tener su cambio local
// (OPTIMISTIC[tipo], en library.js y vaults.js); la respuesta del servidor luego lo confirma.
const OPTIMISTIC = {};
// YouTube o un enlace compartido (Dropbox): el servidor lo descarga
const isRemote = (v) => v?.source === "youtube" || v?.source === "link";
// ¿se espera voz en español? (un video que solo se transcribe no lleva voz)
const wantsVoice = () => !!state.voice && state.voice !== "none" && state.translates;
// idiomas que reconoce el servidor (vt/langs.py): sus códigos llegan con «ready»; el nombre, langName (i18n.js)
let LANGS = { en: 1, pt: 1, it: 1, es: 1 };
// Ajustes › Uso: «Transcribir y resumir» quita todo lo de traducción y voz
const transcribeMode = () => prefs.app_mode === "transcribir";
function applyAppMode() {
  document.body.classList.toggle("app-transcribe", transcribeMode());
  if (typeof syncImportTask === "function") syncImportTask();
  // exportar: sin traducción, lo marcado por defecto es el texto
  const kinds = document.querySelectorAll("#export-form input[name=kind]");
  if (transcribeMode()) for (const k of kinds) if (k.value.startsWith("es_") || ["srt_es", "txt_es", "txt"].includes(k.value)) k.checked = false;
  if (transcribeMode() && ![...kinds].some((k) => k.checked)) { const t = [...kinds].find((k) => k.value === "txt_orig"); if (t) t.checked = true; }
}
// ¿se traduce y dobla este video de la biblioteca? (como Transcript.translates en vt/store.py)
function translatesV(v) {
  if (transcribeMode()) return false;
  const l = v?.lang || "en";
  const tg = targetLang();
  return (v?.mode || (l === tg ? "transcribe" : "translate")) === "translate" && l !== tg && l in LANGS;
}

function send(obj) {
  try { OPTIMISTIC[obj.type]?.(obj); } catch (e) { console.error(e); }
  if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(obj));
}

function onMessage(m) {
  switch (m.type) {
    case "ready":
      state.ready = true;
      state.models = `${m.device} · ${m.model}${m.translator !== "none" ? " · " + m.translator : ""}`;
      renderPower();
      state.voice = m.voice;
      if (m.langs) LANGS = m.langs;
      state.summaryRec = m.summary?.recommended || "";  // modelo de resumen que entra en este equipo
      // al reconectar, la pestaña sigue en su biblioteca (la responde con todo: lista, prefs, videos)
      if (typeof vaults !== "undefined" && vaults.current) send({ type: "vault_open", id: vaults.current });
      if (state.videoId) send({ type: "open", id: state.videoId, name: state.videoName });
      // la sesión nueva no sabe qué se está viendo: la cola vuelve a darle prioridad
      if (state.videoId && state.serverSide && canImport() && (currentView() === "player" || lib.mini)) send({ type: "watch", video: state.videoId, t: vEn.currentTime || 0 });
      send({ type: "library" });
      send({ type: "glossary_get" });
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
    case "search_results":
      searchResults(m);
      break;
    case "glossary":
      glossaryUpdate(m.entries);
      break;
    case "vaults":
      vaultsUpdate(m);
      break;
    case "auth":
      authUpdate(m);
      break;
    case "admin":
      adminUpdate(m);
      break;
    case "admin_key":
      keyCreated(m);
      break;
    case "webhooks_log":
      hooksLog(m);
      break;
    case "denied":
      toast(t("No tienes permiso para esta acción en esta biblioteca"), "warn");
      break;
    case "rec_mute":  // «Silenciar las otras apps al grabar una ventana» (capture.js)
      if (m.error === "no_window") toast(t("No se reconoció la ventana. Las otras apps siguen con sonido."), "warn");
      else if (m.muted) toast(t("Las otras apps quedan en silencio hasta que termines de grabar"), "ok");
      break;
    case "vault_folder":
      vaultFolder(m);
      break;
    case "vault_error":
      toast(m.error, "warn");
      storageError();  // web/js/storage.js
      break;
    case "vault_moved": {
      const movedMsg = m.moved === 1 ? t("1 video movido a «{to}».", { to: m.to }) : t("{n} videos movidos a «{to}».", { n: m.moved, to: m.to });
      toast(m.moved ? movedMsg + (m.skipped ? " " + t("{n} siguen en descarga o proceso. Muévelos cuando terminen.", { n: m.skipped }) : "")
        : t("Los videos siguen en descarga o proceso. Muévelos cuando terminen."), m.moved ? "ok" : "warn");
      break;
    }
    case "lib_meta":
      libMeta(m);
      break;
    case "video_fetch":
      toast(m.count ? (m.count === 1 ? t("Video completo en la cola de descargas, sin volver a traducir.")
        : t("{n} videos completos en la cola de descargas, sin volver a traducir.", { n: m.count }))
        : t("Ya tienen el video completo"), m.count ? "ok" : "warn");
      break;
    case "people_saved":
      if (m.vault === state.videoVault) { state.peopleSaved = m.items; renderPeople(); }
      break;
    case "glossary_applied":
      if (m.segments) toast(t("Glosario aplicado: {phrases} en {videos} se tradujeron de nuevo; su voz se rehace en la cola.", {
        phrases: m.segments === 1 ? t("1 frase") : t("{n} frases", { n: m.segments }),
        videos: m.videos === 1 ? t("1 video") : t("{n} videos", { n: m.videos }) }), "ok");
      break;
    case "people":
      state.people.names = m.speaker_names || {};
      state.people.voices = m.voice_map || {};
      renderTranscript();
      renderPeople();
      if (m.redub) toast(m.redub === 1 ? t("Se rehace la voz de 1 frase en la cola.") : t("Se rehace la voz de {n} frases en la cola.", { n: m.redub }), "ok");
      break;
    case "comments":
      if (m.video !== state.videoId) break;
      state.comments = m.comments;
      renderTranscript();
      renderTimeline();
      break;
    case "deleted":
      if (m.videos.includes(state.videoId)) closeVideo();
      break;
    case "perf": perfUpdate(m); break;              // web/js/perf.js
    case "perf_plan": perfPlan(m); break;
    case "restarting": restarting(m); break;
    case "trashed": trashed(m); break;              // web/js/trash.js
    case "trash": trashUpdate(m); break;
    case "storage": storageUpdate(m); break;         // web/js/storage.js
    case "storage_freed": storageFreed(m); break;
    case "trash_restored": trashRestored(m); break;
    case "yt_blocked":
      if (canConnectYouTube(m.account) && m.session !== "cuenta")
        toast(t("YouTube solicitó verificar que no eres un bot. Las descargas se pausan 20 min."), "warn",
          { label: t("Conectar YouTube"), onClick: () => connectYouTube() });
      else toast(m.account?.expired ? t("Tu sesión de YouTube expiró. Las descargas se pausan 20 min.") : m.error, "warn",
        m.account?.expired && canConnectYouTube(m.account) ? { label: t("Volver a conectar"), onClick: () => connectYouTube() } : null);
      break;
    case "yt_need_account":
      if (canConnectYouTube(m.account))
        toast(t("Un video tiene restricción de edad. Conecta tu cuenta de YouTube."), "warn",
          { label: t("Conectar YouTube"), onClick: () => connectYouTube() });
      break;
    case "library_changed":
      send({ type: "library" });
      send({ type: "glossary_get" });
      break;
    case "batch_added": {
      if (m.errors?.length) toast(cap(m.errors[0]) + ".", "warn");
      if (lib.pendingImport && m.ids) {  // con enlaces de Dropbox: los ids los da el servidor
        afterImport(m.ids.filter((id) => id !== state.videoId), lib.pendingImport);
        lib.pendingImport = null;
      }
      if (m.videos && !m.quiet) toast(m.videos === 1 ? t("1 video agregado a la cola.") : t("{n} videos agregados a la cola.", { n: m.videos }), "ok");
      // un video vive en una sola biblioteca: los que ya están en otra no se duplican
      const away = Object.entries(m.elsewhere || {});
      if (away.length) toast(away.map(([n, k]) => k === 1 ? t("1 ya estaba en «{n}»", { n }) : t("{k} ya estaban en «{n}»", { k, n })).join(" · ")
        + ". " + t("Puedes moverlos desde esa biblioteca."), "warn");
      break;
    }
    case "playlist_added":
      setStatus(...baseStatus);
      $("#yt-url").value = ""; updateImportBtn();
      playlistAdded(m);
      break;
    case "exports":
      exportsUpdate(m);
      break;
    case "export_folder":
      exportFolderPicked(m);
      break;
    case "export_started":
      exportStarted(m.job);
      break;
    case "yt_queued":
      setStatus(...baseStatus);
      $("#yt-url").value = ""; updateImportBtn();
      break;
    case "transcript":
      if (m.id !== state.videoId) return;
      state.segments = m.segments;
      state.covered = m.covered;
      state.comments = m.comments || {};
      state.people = { names: m.speaker_names || {}, voices: m.voice_map || {}, refs: m.voice_refs || {} };
      state.prefix = m.prefix || "";      // archivos de su biblioteca (/v/<id>/…; Principal sin prefijo)
      applyLang(m.lang, m.translates);
      state.videoVault = m.vault;
      send({ type: "people_get", vault: m.vault });
      state.editing = null;
      // las voces se bajan a medida que se acercan (cada 80 ms se precargan los próximos 15 s):
      // bajarlas todas al abrir llenaba las conexiones y el video tardaba en cargar
      renderTranscript();
      renderTimeline();
      summaryFromTranscript(m);
      screenTextLoad(m.screen_text);   // web/js/screentext.js
      break;
    case "screen_text":
      screenTextAdd(m);
      break;
    case "agent_power":
    case "agent_chat":
    case "agent_state":
    case "agent_delta":
    case "agent_done":
    case "agent_error":
    case "agent_dictated":
      agentEvent(m);   // web/js/agentui.js
      break;
    case "agent_models":  // Ajustes › Agente › Modelo: cuáles son compatibles con este equipo
      state.agentModels = m;
      if (currentView() === "prefs" && lib.prefSec === "agente") renderPrefs();
      break;
    case "video_description": {  // la descripción corta llegó (vt/agentsvc.py)
      const v = lib.videos[m.video];
      if (v) v.description = m.text;
      if (m.video === state.videoId) renderVideoDesc();
      break;
    }
    case "agent_model_dl": {  // un modelo del agente bajando desde Ajustes
      const x = state.agentModels?.models.find((y) => y.key === m.key);
      if (x) {
        x.downloading = m.state === "descargando" ? m.pct : null;
        if (m.state === "listo") x.downloaded = true;
      }
      if (m.state === "error") toast(m.error);
      if (currentView() === "prefs" && lib.prefSec === "agente") renderPrefs();
      break;
    }
    case "agent_context":
      if (m.video === state.agentCopy) {
        state.agentCopy = null;
        copyText(m.text, t("Contexto del video copiado para tu agente, con marcas de tiempo y texto en pantalla"));
      }
      break;
    case "summary":
    case "summary_state":
      summaryUpdate(m);
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
    case "update":  // versión nueva en GitHub (web/js/desktop.js)
      if (DESKTOP) onUpdateInfo(m);
      break;
    case "lang":  // idioma detectado (o cambiado) del video abierto
      if (lib.videos[state.videoId]) Object.assign(lib.videos[state.videoId], { lang: m.lang, mode: m.mode });
      if (m.reset) {  // era otro idioma: lo reconocido se borró y se rehace
        state.segments = [];
        state.covered = [];
        state.comments = {};
        renderTranscript();
        renderTimeline();
      }
      applyLang(m.lang, m.translates);
      renderTranscript();
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
    case "target":
      // otro idioma de destino: el video abierto vuelve con la traducción y la voz de ese idioma (lo que falte se hace)
      if (state.videoId) send({ type: "open", id: state.videoId, name: state.videoName });
      send({ type: "library" });
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
      $("#yt-url").value = ""; updateImportBtn();
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
      if (gapSig(transcriptGaps()) !== state.gapSig) renderTranscript();  // un hueco se llenó o se partió
      break;
    case "stats":
      if (feeder.ack) feeder.ack();
      state.metrics = t("inferencia {ms} ms · búfer {s} s", { ms: m.infer_ms, s: m.buffer_s.toFixed(1) });
      break;
  }
  renderCaptions();
}

let baseStatus = ["off", t("sin conexión")];
i18nTrack(baseStatus);  // al cambiar de idioma, sus textos también cambian (i18n.js)
// El estado del encabezado solo se ve sin conexión o con algo puntual (buscando un video, leyendo una
// playlist): el del trabajo de fondo y el reposo de los modelos van en la Cola (data-base)
function setStatus(kind, text, base = true) {
  if (base) baseStatus = [kind, text];
  const el = $("#status");
  el.dataset.state = kind;
  el.dataset.base = base ? "1" : "0";
  el.querySelector("span").textContent = cap(text);
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
  // crypto.subtle solo existe con https o en este equipo; desde otro equipo de la red (http) se calcula aquí
  const h = window.crypto?.subtle ? await crypto.subtle.digest("SHA-256", buf) : sha256js(new Uint8Array(buf));
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

function sha256js(bytes) {
  const K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  const n = bytes.length, total = Math.ceil((n + 9) / 64) * 64;
  const m = new Uint8Array(total);
  m.set(bytes);
  m[n] = 0x80;
  const dv = new DataView(m.buffer);
  dv.setUint32(total - 8, Math.floor(n / 0x20000000));
  dv.setUint32(total - 4, (n << 3) >>> 0);
  const w = new Uint32Array(64);
  const rot = (x, r) => (x >>> r) | (x << (32 - r));
  for (let o = 0; o < total; o += 64) {
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(o + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rot(w[i - 15], 7) ^ rot(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rot(w[i - 2], 17) ^ rot(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const t1 = (h + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
      const t2 = ((rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    [a, b, c, d, e, f, g, h].forEach((x, i) => { H[i] = (H[i] + x) >>> 0; });
  }
  const out = new DataView(new ArrayBuffer(32));
  H.forEach((x, i) => out.setUint32(i * 4, x));
  return out.buffer;
}

function loadVideo(src, id, name, audioSrc, opts = {}) {
  if (state.videoId) send({ type: "stop" });
  state.videoId = id;
  state.videoName = name;
  if (typeof screenTextLoad === "function") screenTextLoad(null);  // lo del video anterior no queda encima
  state.segments = [];
  state.covered = [];
  state.live = { committed: "", tentative: "" };
  state.lastSeg = null;
  state.sending = false;
  vEn.src = src;
  vEs.src = src;
  // solo audio descargado: se ve su miniatura en lugar del video
  const lv = typeof lib !== "undefined" ? lib.videos[id] : null;
  vEn.poster = vEs.poster = lv?.audio_only ? lv.thumb || "" : "";
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
  applyLang(lib.videos[id]?.lang, translatesV(lib.videos[id]));  // al llegar su transcripción se confirma
  libOnOpen({ id, name, ...opts });
  setView("player");
  $("#file-name").textContent = name;
  $("#file-name").title = name;
  renderVideoDesc();
  document.title = `${name} · Translay`;
  renderTranscript();
  renderTimeline();
  renderCaptions();
  send({ type: "open", id, name });
  // priorizar en la cola es de quien puede importar: a un invitado que solo ve, el servidor se lo niega
  if (state.serverSide && canImport()) send({ type: "watch", video: id, t: opts.position || 0 });
  // Ajustes → Video: empieza solo, en cuanto esté listo para reproducirse sin cortes
  state.forcePlay = false;
  state.autoWait = prefs.autoplay !== false;
}

// uno o varios archivos: se abre el primero; los demás quedan en "Siguientes"
// (se copian a la biblioteca y la cola los procesa mientras tanto)
async function openFiles(files) {
  // un .csv trae enlaces de YouTube: se revisan en el cuadro de varios enlaces
  for (const f of files.filter(isCsv)) importCsvFile(f);
  files = files.filter((x) => /^(video|audio)\//.test(x.type));
  if (!files.length) return;
  const ids = [];
  for (const f of files) ids.push(await fingerprint(f));
  const mode = importMode();
  if (mode !== "abrir") {  // a la cola (y viendo un video, sin interrumpirlo)
    files.forEach((f, i) => importLocal(f, ids[i]));
    if (mode === "siguiente") addedWhileWatching(ids);
    else toast(ids.length === 1 ? t("Importado y agregado a la cola") : t("{n} archivos importados a la cola", { n: ids.length }), "ok");
    return;
  }
  if (files.length > 1) {
    setContext({ name: t("Archivos abiertos"), items: ids, auto: true });
    files.slice(1).forEach((f, i) => importLocal(f, ids[i + 1]));
  }
  loadVideo(URL.createObjectURL(files[0]), ids[0], files[0].name, null, { file: files[0], keepContext: files.length > 1 });
}
$("#file").addEventListener("change", (e) => { openFiles([...e.target.files]); e.target.value = ""; });

// arrastrar archivos: toda la ventana los recibe y lo dice mientras están encima
let dragDepth = 0;
const dragFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (dragFiles(e) && can("import")) { dragDepth++; $("#drop-zone").hidden = false; } });
window.addEventListener("dragleave", (e) => { if (dragFiles(e) && --dragDepth <= 0) { dragDepth = 0; $("#drop-zone").hidden = true; } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("#drop-zone").hidden = true;
  openFiles([...e.dataTransfer.files]);
});

// YouTube o Dropbox: el servidor descarga el video
function openYouTube(url) {
  if (classify(url)?.link) { importVideos([url]); return true; }
  if (!/(youtube\.com|youtu\.be)\//.test(url) && !/^[\w-]{11}$/.test(url)) return false;
  const list = (url.match(/[?&]list=([\w-]{10,})/) || [])[1];
  const isList = list && !/^(RD|UL)/.test(list);  // los mix automáticos no son playlists
  const hasVideo = /(?:v=|youtu\.be\/|shorts\/)[\w-]{11}/.test(url);
  if (isList && hasVideo && currentView() === "player") { openVideoLink(url); return true; }
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
// viendo un video y la preferencia no es "Abrirlo": lo nuevo no saca del video
function watchingKeep() {
  return currentView() === "player" && !!state.videoId && prefs.add_while_watching !== "abrir";
}

// Todo lo importado va directo a la cola del servidor (sobrevive a recargar la página).
// Fuera del reproductor solo se procesa; viendo un video, según Ajustes → Video.
function importMode() {
  return currentView() === "player" && state.videoId ? prefs.add_while_watching || "siguiente" : "fondo";
}
function importVideos(urls) {
  const mode = importMode();
  const found = urls.map((u) => classify(u)).filter((c) => c?.kind === "video");
  const ids = [...new Set(found.filter((c) => !c.link).map((c) => "yt_" + c.key))].filter((id) => id !== state.videoId);
  if (found.some((c) => c.link)) lib.pendingImport = mode;  // sigue al responder el servidor (batch_added)
  send({ type: "yt_batch", urls, coll: $("#multi-coll").value || "", quiet: true, front: mode === "abrir", ...takeImportOpts() });
  $("#yt-url").value = ""; updateImportBtn();
  if (!lib.pendingImport) afterImport(ids, mode);
}
function afterImport(ids, mode) {
  if (!ids.length) return;
  if (mode === "abrir") {
    lib.openWhenReady = ids[0];  // se abre apenas termine de descargarse
    toast(t("Se abrirá cuando termine la descarga"), "ok");
  } else if (mode === "siguiente") {
    addedWhileWatching(ids);
  } else {
    const only = prefs.import_mode === "descargar";
    const tr = transcribeMode();
    const n = ids.length;
    toast(n === 1 ? (only ? (tr ? t("Importado. Se descargará sin transcribir") : t("Importado. Se descargará sin traducir")) : t("Importado y agregado a la cola"))
      : only ? (tr ? t("{n} videos importados: se descargan sin transcribir.", { n }) : t("{n} videos importados: se descargan sin traducir.", { n }))
      : t("{n} videos importados a la cola.", { n }), "ok");
    // importado desde una colección o categoría: se queda ahí
    if (currentView() === "library" && !$("#multi-coll").value) { lib.sel = "home"; renderLibrary(); }
  }
}

// lo agregado entra a la cola; "a continuación" además va justo después del actual en Siguientes
function addedWhileWatching(ids) {
  if (prefs.add_while_watching === "siguiente") {
    const items = contextItems().filter((id) => !ids.includes(id));
    const base = items.includes(state.videoId) ? items : [state.videoId];
    const at = base.indexOf(state.videoId) + 1;
    setContext({ name: lib.ctx?.name || t("A continuación"), items: [...base.slice(0, at), ...ids, ...base.slice(at)], auto: true });
    lib.showUpNext = true;  // se abre la pestaña en cuanto el video nuevo llegue a la biblioteca
    renderUpNext();
    toast(ids.length === 1 ? t("Se reproducirá a continuación.") : t("{n} videos a continuación.", { n: ids.length }), "ok");
  } else {
    toast(ids.length === 1 ? t("Agregado a la cola. Se procesará en segundo plano") : t("{n} videos a la cola.", { n: ids.length }), "ok");
  }
}

function openVideoLink(url) {
  if (classify(url)?.kind === "video") return importVideos([url]);
  $("#file-name").textContent = "";
  $("#file-desc").hidden = true;
  $("#file-desc").textContent = "";
  setStatus("busy", t("buscando video"), false);
  send({ type: "youtube", url });
}
function addPlaylist(url) {
  setStatus("busy", t("leyendo la playlist"), false);
  send({ type: "playlist", url, ...takeImportOpts() });
}
// Traducir y doblar, o solo transcribir lo que se agregue: se elige en el panel o en la portada vacía y se
// recuerda en este navegador. En «Transcribir y resumir» (Ajustes › Uso) no se elige: todo se transcribe.
let importTask = "";
try { importTask = localStorage.getItem("translay.import-task") || ""; } catch { /* sin almacenamiento */ }
function takeImportOpts() { return { lang: "auto", mode: transcribeMode() ? "transcribe" : importTask }; }
function importTaskSegs() {
  if (transcribeMode()) return null;
  const seg = (value, ic, text) => el("button", { type: "button", class: "seg" + (importTask === value ? " on" : ""), "data-task": value,
    on: { click: (e) => {
      e.stopPropagation();
      importTask = value;
      try { localStorage.setItem("translay.import-task", value); } catch { /* sin almacenamiento */ }
      for (const b of document.querySelectorAll(".import-segs > .seg")) b.classList.toggle("on", b.dataset.task === value);
      if (typeof swapWelcomeTitle === "function") swapWelcomeTitle();
    } } }, icon(ic), text);
  return el("div", { class: "segs import-segs" }, seg("", "spark", t("Traducir y doblar")), seg("transcribe", "comment", t("Solo transcribir")));
}
function syncImportTask() { const box = $("#import-task"); box.replaceChildren(...[importTaskSegs()].filter(Boolean)); box.hidden = transcribeMode(); }
syncImportTask();

// un enlace (o varios) desde el panel, la portada o pegado: true si se agregó
function addFromText(text) {
  if (!text) { toast(t("Pega un enlace de YouTube o Dropbox"), "warn"); return false; }
  if (ytLinks(text).length > 1) { openMulti(text); return true; }
  if (!ytLinks(text).length && !/^[\w-]{11}$/.test(text)) {
    toast(t("El enlace no es de YouTube ni de Dropbox. Copia el enlace del video y pégalo aquí."), "warn");
    return false;
  }
  if (/dropbox\.com\//i.test(text) && !classify(text)) {
    toast(t("El enlace de Dropbox no corresponde a un video. Abre el video en Dropbox y copia su enlace."), "warn");
    return false;
  }
  return openYouTube(text);
}
$("#yt").addEventListener("submit", (e) => {
  e.preventDefault();
  e.stopPropagation();
  if (addFromText($("#yt-url").value.trim())) {
    $("#yt-url").value = "";
    $("#import-pop").hidden = true;
  }
});
function updateImportBtn() {}  // (antes: «Agregar» deshabilitado sin enlace; ahora avisa al tocarlo)
$("#yt").addEventListener("click", (e) => e.stopPropagation());

document.addEventListener("paste", (e) => {
  if (e.target.closest("textarea, dialog")) return;
  const text = e.clipboardData.getData("text").trim();
  if (ytLinks(text).length > 1) { e.preventDefault(); openMulti(text); return; }  // varios: cuadro para revisarlos
  if (e.target.closest("input")) return;
  if (openYouTube(text)) e.preventDefault();
});

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

// ¿El original y la traducción dicen lo mismo? (un video en español marcado con otro idioma: la
// «traducción» repite el texto). Entonces se muestra uno solo, no dos líneas iguales.
const _words = (t) => new Set(String(t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
  .split(/[^a-z0-9ñ]+/).filter((w) => w.length > 1));
function sameText(a, b) {
  const x = _words(a), y = _words(b);
  if (!x.size || !y.size) return false;
  let both = 0;
  for (const w of x) if (y.has(w)) both++;
  return both / Math.max(x.size, y.size) >= 0.6;
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
      const shown = state.translates ? seg.translation : seg.text;  // solo transcribir: en su idioma
      es = shown ? chunkAt(shown, seg.start, seg.end, at) : "";
    }
  }
  if (es && state.translates && sameText(`${c} ${tt}`, es)) c = tt = "";  // dos líneas iguales: solo una
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
  // tramos que aún no se transcribieron, en su lugar entre las frases: así un salto hacia
  // adelante no parece un error (se transcriben al reproducirlos o cuando llegue la cola)
  const gaps = state.segments.length || state.covered.length ? transcriptGaps() : [];
  state.gapSig = gapSig(gaps);
  let g = 0;
  // lo escrito en el video (código, comandos, enlaces…), en su momento entre las frases (web/js/screentext.js)
  const els = state.elements || [];
  let k = 0;
  for (const s of state.segments) {
    while (g < gaps.length && gaps[g][0] <= s.start) frag.appendChild(gapItem(gaps[g++]));
    while (k < els.length && els[k].start <= s.start) frag.appendChild(elementItem(els[k++]));
    const li = document.createElement("li");
    li.dataset.start = s.start;
    li.dataset.id = s.id;
    const who = s.speaker != null && speakers.size > 1
      ? `<span class="spk ${whoClass(speakers.get(s.speaker))}">${escapeHtml(personName(s.speaker, speakers.get(s.speaker)))}</span>` : "";
    const time = `<time>${fmt(s.start)}${who}</time>`;
    const n = (state.comments[String(s.id)] || []).length;
    const time1 = time;
    li.innerHTML = `<div class="cell">${time1}<p></p></div><div class="cell">${time}<p></p></div>`;
    const [en, es] = li.querySelectorAll("p");
    en.textContent = s.text;
    const shown = state.translates ? s.translation : s.text;  // solo transcribir: una columna, en su idioma
    es.textContent = shown || "—";
    es.classList.toggle("pending", !shown);
    li.classList.toggle("same", !!(state.translates && shown && sameText(s.text, shown)));  // ya en español: una columna
    const notes = state.comments[String(s.id)] || [];
    const editingHere = state.editing?.seg === s.id;
    li.classList.toggle("has-notes", notes.length > 0);
    // con comentarios: el botón muestra cuántos (siempre visible) y sirve para agregar otro
    li.append(n
      ? el("button", { type: "button", class: "cbtn has", title: n === 1 ? t("1 comentario · agregar otro") : t("{n} comentarios · agregar otro", { n }) },
        icon("comment"), String(n))
      : el("button", { type: "button", class: "cbtn", title: t("Comentar esta frase"), "aria-label": t("Comentar esta frase") }, icon("plus")));
    if (notes.length || editingHere) li.append(renderNotes(s.id, notes));
    frag.appendChild(li);
  }
  while (g < gaps.length) frag.appendChild(gapItem(gaps[g++]));
  while (k < els.length) frag.appendChild(elementItem(els[k++]));
  const focused = document.activeElement?.closest?.(".ceditor") ? state.editing : null;
  ol.replaceChildren(frag);
  if (!state.segments.length) ol.append(emptyState("comment", t("Aún no hay transcripción"),
    t("La transcripción aparece aquí a medida que se reconoce el audio."), "li"));
  if (focused) {  // al redibujar (llega una frase nueva) el cuadro sigue donde estaba
    const ta = ol.querySelector(".ceditor .area");
    ta?.focus();
    ta?.setSelectionRange(ta.value.length, ta.value.length);
  }
  renderActive(true);
  if (typeof lib !== "undefined") updateSideTabs();  // aparece «Personas» cuando hay personas
}

/* ------------------------------------------------------------ reposo */
// estado en palabras simples; el detalle técnico queda al pasar el mouse
function renderPower() {
  if (!state.ready) return;
  const p = state.power || "reposo";
  const q = typeof lib !== "undefined" ? lib.queue : null;
  const run = q?.jobs.find((j) => j.state === "procesando");
  const dl = q?.jobs.find((j) => j.dl);
  if (run) setStatus("ok", t("procesando · {pct} %", { pct: Math.round(run.dub * 100) }));
  else if (dl) setStatus("busy", dl.dl.speed ? t("descargando · {speed}/s", { speed: fmtBytes(dl.dl.speed) }) : t("descargando"));
  else if (p === "cargando") setStatus("busy", t("cargando modelos"));
  else if (p === "reposo") setStatus("sleep", t("en reposo"));
  else setStatus("ok", t("listo"));
  $("#status").title = [state.models, state.metrics].filter(Boolean).join(" · ");
  if (typeof renderQueuePanel === "function" && lib.queue) renderQueuePanel();  // «preparando los modelos» en la Cola
}

// bajo el título: la descripción corta del video (aparece con un fundido cuando llega)
function renderVideoDesc() {
  const p = $("#file-desc");
  const text = lib.videos[state.videoId]?.description || "";
  if (p.textContent === text) return;
  p.textContent = text;
  p.title = text;
  p.hidden = !text;
  if (text) p.animate?.([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: "ease-out" });
}

/* ------------------------------------------------------------ vista ampliada / dividida */
function setLayout(wide, save = true) {
  document.body.classList.toggle("layout-wide", wide);
  setBtn($("#layout"), wide ? t("Ver dividido") : t("Ver ampliado"), wide ? "columns" : "expand");
  if (save) setPref("layout", wide ? "ampliada" : "dividida");
  renderActive(true);
}
$("#layout").addEventListener("click", () => setLayout(!document.body.classList.contains("layout-wide")));

/* ------------------------------------------------------------ comentarios y personas: al instante */
OPTIMISTIC.comment_add = (m) => {
  if (m.video !== state.videoId) return;
  const k = String(m.seg);
  (state.comments[k] ||= []).push({ id: "tmp-" + Date.now(), text: m.text, created: Date.now() / 1000 });
  renderTranscript();
  renderTimeline();
};
OPTIMISTIC.comment_edit = (m) => {
  const c = (state.comments[String(m.seg)] || []).find((x) => x.id === m.id);
  if (c && m.video === state.videoId) { c.text = m.text; c.updated = Date.now() / 1000; renderTranscript(); }
};
OPTIMISTIC.comment_delete = (m) => {
  const k = String(m.seg);
  if (m.video !== state.videoId || !state.comments[k]) return;
  state.comments[k] = state.comments[k].filter((x) => x.id !== m.id);
  renderTranscript();
  renderTimeline();
};
OPTIMISTIC.people_set = (m) => {
  if (m.video !== state.videoId) return;
  if (m.name != null) state.people.names[String(m.spk)] = m.name;
  if (m.voice != null) state.people.voices[String(m.spk)] = m.voice;
  renderTranscript();
};

/* ------------------------------------------- pestañas: transcripción / resumen / siguientes / personas */
function setSideTab(tab) {
  for (const b of $("#side-tabs").querySelectorAll("button")) b.classList.toggle("on", b.dataset.tab === tab);
  $("#transcript").hidden = tab !== "transcript";
  $("#upnext").hidden = tab !== "upnext";
  $("#people").hidden = tab !== "people";
  $("#summary").hidden = tab !== "summary";
  if (tab === "transcript") renderActive(true);
  else if (tab === "people") renderPeople();
  else if (tab === "summary") { renderSummary(); agentOpen(); renderAgent(); $("#ag-input").focus({ preventScroll: true }); }
  else renderUpNext(true);
}

// la barra de pestañas solo aparece si hay algo más que la transcripción
function updateSideTabs() {
  const up = $('#side-tabs [data-tab="upnext"]');
  const pe = $('#side-tabs [data-tab="people"]');
  const su = $('#side-tabs [data-tab="summary"]');
  const items = typeof contextItems === "function" ? contextItems().filter((id) => lib.videos[id]) : [];
  up.hidden = items.length < 2;
  pe.hidden = !state.segments.some((s) => s.speaker != null);
  su.hidden = !state.segments.length && !state.summary;
  if (typeof agentTabLabel === "function") agentTabLabel();
  $("#side-tabs").hidden = up.hidden && pe.hidden && su.hidden;
  const on = $("#side-tabs button.on");
  if (!on || on.hidden) setSideTab("transcript");
}
$("#side-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setSideTab(b.dataset.tab);
});

/* ------------------------------------------------------------ descargas */
const DOWNLOAD_STEPS = [["buscando", t("Buscando")], ["video", t("Video")], ["audio", t("Audio")],
  ["uniendo", t("Uniendo")], ["preparando", t("Preparando")]];
i18nTrack(DOWNLOAD_STEPS);  // al cambiar de idioma, sus textos también cambian (i18n.js)
function downloadText(m) {
  if (m.stage === "video") return t("descargando video {pct} %", { pct: m.pct });
  if (m.stage === "audio") return t("descargando audio {pct} %", { pct: m.pct });
  const name = { buscando: t("buscando"), uniendo: t("uniendo"), preparando: t("preparando") }[m.stage] || m.stage;
  return `${name}…`;
}

/* ------------------------------------------------------------ avisos */
let toastTimer = null;
// action: { label, onClick } — un botón en el aviso (p. ej. «Deshacer»)
function toast(text, kind = "error", action = null) {
  const t = $("#toast");
  t.replaceChildren(...[el("span", { class: "toast-text", text }),
    action ? btn(action.label, { size: "xs", cls: "toast-act", onClick: (e) => { e.stopPropagation(); hideToast(); action.onClick(); } }) : null]
    .filter(Boolean));
  t.dataset.kind = kind;  // error (rojo) · ok (verde) · warn (ámbar)
  t.classList.remove("out");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, action ? 12000 : 15000);
}
// se va desvaneciéndose (overlays.css · toast-out) y luego se oculta
function hideToast() {
  const t = $("#toast");
  clearTimeout(toastTimer);
  if (t.hidden || t.classList.contains("out")) return;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { t.hidden = true; return; }
  t.classList.add("out");
  t.addEventListener("animationend", () => { if (t.classList.contains("out")) { t.hidden = true; t.classList.remove("out"); } }, { once: true });
}
$("#toast").addEventListener("click", hideToast);

/* ------------------------------------------------------------ avisos del navegador */
function requestNotify() {
  if (!("Notification" in window)) {
    toast(t("Este navegador no admite notificaciones"), "warn");
    setPref("notify", false);
    renderPrefs();
    return;
  }
  Notification.requestPermission().then((p) => {
    if (p !== "granted") {
      toast(t("El navegador bloqueó las notificaciones"), "warn");
      setPref("notify", false);
      renderPrefs();
    } else {
      notifyUser(t("Notificaciones activadas"), t("Recibirás un aviso cuando termine una descarga, un video o una exportación."), true);
    }
  });
}
// solo con la pestaña en segundo plano (si se está mirando, basta el aviso de la página)
function notifyUser(title, body, force = false) {
  if (!prefs.notify || !("Notification" in window) || Notification.permission !== "granted") return;
  if (!force && !document.hidden) return;
  const n = new Notification(title, { body, tag: `vt-${title}` });
  n.onclick = () => { window.focus(); n.close(); };
}
// varios eventos seguidos se juntan en un solo aviso (con miles en la cola serían demasiados)
const notifyBuf = {};
function notifyLater(kind, name) {
  const b = (notifyBuf[kind] ||= { names: [], timer: null });
  b.names.push(name);
  clearTimeout(b.timer);
  b.timer = setTimeout(() => {
    const n = b.names.length;
    // kind es un identificador que manda library.js («traducidos», «descargados»): cada uno tiene sus frases
    const one = { traducidos: t("Traducido: {name}", { name: b.names[0] }), descargados: t("Descargado: {name}", { name: b.names[0] }) }[kind];
    const many = { traducidos: t("{n} videos traducidos", { n }), descargados: t("{n} videos descargados", { n }) }[kind];
    notifyUser(n === 1 ? one || `${kind[0].toUpperCase() + kind.slice(1)}: ${b.names[0]}` : many || `${n} videos ${kind}`,
      n === 1 ? "" : b.names.slice(0, 3).join(" · ") + (n > 3 ? "…" : ""));
    b.names = [];
  }, 4000);
}

// Enter en un cuadro de texto de un diálogo acepta (el envío implícito tomaría «Cancelar», el primero)
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.isComposing) return;
  const inp = e.target.closest?.("dialog form[method=dialog] input");
  if (!inp) return;
  e.preventDefault();
  const ok = inp.form.querySelector('button[value="ok"]');
  if (ok && !ok.disabled) inp.form.requestSubmit(ok);
}, true);
