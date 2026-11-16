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
let LANGS = { en: 1, pt: 1, es: 1 };
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

/* ------------------------------------------------------------ varios enlaces */
// enlaces de YouTube y de Dropbox (vt/links.py)
function ytLinks(text) {
  const found = text.match(/(?:https?:\/\/)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\/[^\s,;"'<>]+/gi) || [];
  const dbx = text.match(/(?:https?:\/\/)?(?:www\.)?dropbox\.com\/[^\s,;"'<>]+/gi) || [];
  return [...new Set([...found, ...dbx])];
}
// Dropbox: solo enlaces a un archivo de video o audio (no a una carpeta)
const MEDIA_EXT = /\.(mp4|m4v|webm|mkv|mov|avi|ts|flv|wmv|3gp|mpg|mpeg|mp3|m4a|wav|ogg|opus|flac|aac)$/i;
function classify(url) {
  const dbx = url.match(/dropbox\.com(\/[^?#\s]+)/i);
  if (dbx) return MEDIA_EXT.test(dbx[1]) && dbx[1].split("/").filter(Boolean).length >= 3
    ? { kind: "video", key: "dbx:" + dbx[1], link: true } : null;
  const v = (url.match(/(?:v=|youtu\.be\/|shorts\/|live\/)([\w-]{11})/) || [])[1];
  const list = (url.match(/[?&]list=([\w-]{10,})/) || [])[1];
  if (v) return { kind: "video", key: v };
  if (list && !/^(RD|UL)/.test(list)) return { kind: "playlist", key: list };
  return null;
}
/* ------------------------------------------------------------ importar desde .csv */
const isCsv = (f) => /\.csv$/i.test(f.name) || f.type === "text/csv";

// CSV con comillas y separador , ; o tabulación (el que más aparezca en la primera línea)
function parseCsv(text) {
  const first = text.split(/\r?\n/, 1)[0] || "";
  const sep = [",", ";", "\t"].sort((a, b) => first.split(b).length - first.split(a).length)[0];
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === sep) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

// enlaces de cualquier celda; IDs sueltos solo si una columna se llama id / video_id / youtube_id
function linksFromCsv(text) {
  const rows = parseCsv(text.replace(/^﻿/, ""));
  const links = new Set(ytLinks(text));
  const header = (rows[0] || []).map((h) => h.trim().toLowerCase().replace(/[\s-]+/g, "_"));
  const idCols = header.map((h, i) => (/^(id|video_?id|youtube_?id|yt_?id)$/.test(h) ? i : -1)).filter((i) => i >= 0);
  for (const r of rows.slice(1)) {
    for (const i of idCols) {
      const v = (r[i] || "").trim();
      // un id real mezcla letras, números o guiones; una palabra común («Engineering») no cuenta
      if (/^[\w-]{11}$/.test(v) && !/^[A-Za-z][a-z]+$/.test(v)) links.add(`https://youtu.be/${v}`);
    }
  }
  return [...links];
}

async function importCsvFile(file, append = false) {
  const links = linksFromCsv(await file.text());
  if (!links.length) { toast(t("«{name}» no tiene enlaces de YouTube ni de Dropbox.", { name: file.name }), "warn"); return; }
  if (append && $("#multi-dlg").open) {
    const prev = $("#multi-text").value.trim();
    $("#multi-text").value = (prev ? prev + "\n" : "") + links.join("\n");
    updateMulti();
  } else {
    openMulti(links.join("\n"));
  }
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
  const known = items.filter((x) => x.kind === "video" && !x.link && lib.videos["yt_" + x.key]).length;
  const parts = [];
  if (nv) parts.push(nv === 1 ? t("1 video") : t("{n} videos", { n: nv }));
  if (np) parts.push(np === 1 ? t("1 playlist") : t("{n} playlists", { n: np }));
  if (known) parts.push(known === 1 ? t("1 ya está en la biblioteca") : t("{n} ya están en la biblioteca", { n: known }));
  $("#multi-sum").textContent = cap(parts.join(" · ")) || t("Sin enlaces de YouTube ni de Dropbox");
  $("#multi-go").disabled = !items.length;
}
// target: id de la colección o categoría donde se guarda lo importado (desde su cabecera)
function openMulti(text = "", target = "") {
  $("#multi-text").value = text;
  const sel = $("#multi-coll");
  sel.replaceChildren(new Option(t("Sin colección"), ""));
  const own = lib.collections.filter((x) => x.kind === "propia");
  if (own.length) {
    const g = el("optgroup", { label: t("Colecciones") });
    for (const c of own) g.append(new Option(c.name, c.id));
    sel.append(g);
  }
  // las categorías de YouTube (web/js/patterns.js) y las que ya existan
  const cats = [...new Set([...Object.keys(CATEGORY_ICON), ...lib.collections.filter((x) => x.kind === "categoría").map((c) => c.name)])]
    .sort((a, b) => a.localeCompare(b, LOCALE));
  const g = el("optgroup", { label: t("Categorías") });
  for (const n of cats) g.append(new Option(n, "cat-" + slugify(n)));
  sel.append(g);
  sel.value = target;
  dropdown(sel, (o) => {
    if (!o.value) return icon("x");
    const c = lib.collections.find((x) => x.id === o.value) || { id: o.value, name: o.textContent, kind: o.value.startsWith("cat-") ? "categoría" : "propia" };
    return collBadge(c);
  });
  updateMulti();
  $("#yt-url").value = ""; updateImportBtn();
  $("#multi-dlg").showModal();
  $("#multi-text").focus();
}
// igual que _slug de vt/library.py (los ids de las categorías)
const slugify = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "x";
$("#multi-text").addEventListener("input", updateMulti);
$("#multi-csv").addEventListener("change", (e) => {
  for (const f of e.target.files) importCsvFile(f, true);
  e.target.value = "";
});
$("#multi-dlg").addEventListener("close", () => {
  if ($("#multi-dlg").returnValue !== "ok") {
    importTask = "";
    $("#multi-coll").value = "";  // cancelado: la colección elegida no queda para la próxima importación
    return;
  }
  const items = multiParsed();
  if (!items.length) return;
  importVideos(items.map((x) => x.url));
  $("#multi-coll").value = "";
});

window.addEventListener("DOMContentLoaded", async () => {
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
});

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
  renderHead();
}

function renderHead() {
  const d = vEn.duration;
  const t = vEn.currentTime;
  $("#c-time").replaceChildren(fmt(t), el("small", { text: ` / ${d && isFinite(d) ? fmt(d) : "0:00"}` }));
  if (!d || !isFinite(d)) return;
  const pct = `${Math.min(100, (t / d) * 100)}%`;
  $("#t-play").style.width = pct;
  $("#t-head").style.left = pct;
  document.querySelectorAll(".timeline .head").forEach((h) => { h.style.left = pct; });
}

vEn.addEventListener("loadedmetadata", renderTimeline);

// después de cargar todos los scripts: los primeros mensajes del servidor ya encuentran quién los atiende
window.addEventListener("DOMContentLoaded", connect);

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

/* ------------------------------------------------------------ preferencias */
// lo cambiado aquí que el servidor todavía no confirma: un aviso de «prefs» de otro cambio anterior trae el valor
// viejo y no debe pisarlo (al guardar dos cosas seguidas, se veía un instante lo anterior)
const prefsPending = {};
function setPref(key, value) {
  prefs[key] = value;
  prefsPending[key] = { value, until: Date.now() + 3000 };
  send({ type: "prefs_set", key, value });
  if (key === "app_mode") applyAppMode();
  if (key.startsWith("accent_") && typeof syncAccent === "function") syncAccent();
  if (key.startsWith("agent_") && typeof refreshAgentPreviews === "function") { refreshAgentPreviews(); renderAgent(); }
  if (key === "agent_device") { state.agentModels = null; }  // cambia cuál entra y cuál se recomienda
  if (key.startsWith("home_bg") && typeof syncSceneBg === "function") syncSceneBg();
  if (key.startsWith("home_bg") && currentView() === "library" && typeof renderHome === "function" && lib.sel === "home") renderHome();
}

function applyPrefs(m) {
  if (typeof syncExportOpts === "function") setTimeout(syncExportOpts);  // la carpeta de Exportar, en el diálogo
  prefsSchema = m.schema;
  prefsSections = m.sections || [];
  prefsAltSections = m.alt_sections || {};
  prefsGroups = m.groups || [];
  if (DESKTOP) prefsSections = [...prefsSections, DESKTOP_SECTION];  // web/js/desktop.js
  // dónde guardar lo exportado solo se elige en este equipo (desde otro, lo descarga el navegador)
  if (!(state.access?.local && state.access?.owner)) prefsSections = prefsSections.filter(([k]) => k !== "exportar");
  prefsVaultKeys = m.vault_keys || [];
  const before = JSON.stringify(prefs);
  prefs = { ...prefs, ...m.values };
  for (const [k, p] of Object.entries(prefsPending)) {
    if (m.values[k] === p.value || Date.now() > p.until) delete prefsPending[k];  // confirmado (o no llegó)
    else prefs[k] = p.value;
  }
  TARGET = prefs.target_lang || m.lang || I18N.lang;  // i18n.js
  // otro idioma de la app: sin recargar (i18n.js › switchLang); después se redibuja todo lo que tiene texto
  if (m.lang && m.lang !== I18N.lang && !langSwitching) {
    langSwitching = true;
    switchLang(m.lang).catch((e) => console.warn("idioma:", e)).finally(() => {
      langSwitching = false;
      prefsSigSeen = "";  // Ajustes se redibuja entero, con su esquema en el idioma nuevo
      applyPrefs(m);
      rerenderForLang();
    });
    return;
  }
  applyTheme();
  if (typeof syncSceneBg === "function") syncSceneBg();
  applyAppMode();
  if (typeof syncAccent === "function") syncAccent();
  setLayout(!state.translates || prefs.layout !== "dividida", false);
  applySubs();
  if (typeof applyCodeTheme === "function") applyCodeTheme();
  if (typeof renderAgent === "function") renderAgent();
  if (state.audio) state.audio.orig.gain.value = state.dubMode ? duck() : 1;
  // la confirmación de un cambio hecho aquí no trae nada nuevo: Ajustes no se redibuja (con «Al azar» llegaban
  // varias seguidas y la página parpadeaba)
  const same = JSON.stringify(prefs) === before && prefsSigSeen === JSON.stringify([m.schema?.length, m.sections, m.lang]);
  prefsSigSeen = JSON.stringify([m.schema?.length, m.sections, m.lang]);
  if (!same) renderPrefs();
  if (typeof renderLibrary === "function") renderLibrary();
  if (typeof maybeWelcome === "function") maybeWelcome();  // la primera vez: la bienvenida (web/js/welcome.js)
}
let prefsSigSeen = "";
let langSwitching = false;
// después de cambiar de idioma: cada vista vuelve a dibujarse con t() en el idioma nuevo (lo fijo ya lo cambió
// switchLang); lo que está abierto queda abierto
function rerenderForLang() {
  const call = (name, ...a) => { try { if (typeof window[name] === "function") window[name](...a); } catch (e) { console.warn(name, e); } };
  for (const f of ["renderVaultBtn", "renderSideVault", "renderLibrary", "renderTranscript", "renderSummary", "renderAgent",
    "renderQueuePanel", "renderPower", "applySubs", "renderPeople", "renderUpNext", "agentTabLabel"]) call(f);
  if ($("#welcome-dlg")?.open) call("renderWelcome");
  if (typeof renderActive === "function") renderActive(true);
  document.title = state.videoName ? `${state.videoName} · Translay` : "Translay";
}

const YT_IMPORT = $("#yt-import");
const YT_ACCOUNT = $("#yt-account");
// Ajustes como en una app: las secciones a la izquierda (una página cada una) y,
// en la página, las opciones agrupadas con su descripción. Los bloques propios
// (bibliotecas, glosario, sesión de YouTube, acceso) van como un grupo más.
const PREF_BLOCKS = {
  escritorio: () => desktopPrefsBlocks(),
  bibliotecas: () => [[VAULTS_BLOCK, t("Tus bibliotecas"), t("Abre, edita, cambia el acceso o elimina una biblioteca. Pueden estar en otra carpeta o disco.")]],
  glosario: () => [[GLOSSARY_BLOCK, t("Términos"), t("Si la traducción queda vacía, el término se mantiene como en el original (nombres, marcas, siglas). Al guardar, se vuelven a traducir las frases que lo usan.")]],
  biblioteca: () => [[YT_ACCOUNT, t("Cuenta de YouTube"), t("Inicia sesión una vez en una ventana del navegador. Translay guarda solo las cookies de YouTube, cifradas, y las renueva automáticamente. Se recomienda una cuenta secundaria.")],
    [YT_IMPORT, t("Importar sesión"), t("Importa la sesión de un navegador de este equipo o sube un archivo cookies.txt. Solo se guardan las cookies de YouTube.")]],
  rendimiento: () => {
    perfStart();
    renderPerf();
    return [[PERF_HW, t("Tu equipo"), ""], [PERF_PROFILE, t("Perfil"), t("Modelos que usa Translay. Los tiempos y el estado se basan en mediciones reales en equipos similares al tuyo.")],
      [PERF_LIMITS, t("Límites"), t("Recursos del equipo que puede usar Translay. Los límites de RAM y CPU se aplican de inmediato.")],
      [PERF_ALERTS, t("Avisos"), ""]];
  },
  almacenamiento: () => {
    storageScan();
    renderStorage();
    return [[STORAGE_SUMMARY, t("Espacio usado"), ""],
      [STORAGE_LIBS, t("Bibliotecas"), t("Los videos liberados siguen en la biblioteca y se descargan de nuevo al abrirlos.")],
      [STORAGE_LARGEST, t("Mayor uso de espacio"), ""],
      [STORAGE_MODELS, t("Modelos"), t("Los del perfil que usas no se pueden borrar. Los demás se vuelven a descargar si los necesitas.")],
      [STORAGE_APP, "Translay", ""]];
  },
  papelera: () => { if (can("owner")) send({ type: "trash_list" }); return [[TRASH_BLOCK, t("En la papelera"), t("Los elementos se eliminan automáticamente a los 30 días.")]]; },
  acceso: () => [
    [ACC.owner, t("Contraseña de propietario"), t("Permite acceder como propietario desde otros equipos. En este equipo no se solicita.")],
    [ACC.net, t("Acceso desde otros equipos"), t("Permite acceder a Translay desde otros equipos y celulares de tu red local.")],
    [ACC.libs, t("Acceso a cada biblioteca"), t("Privada, con contraseña o pública, y si los invitados solo pueden ver o también importar.")],
    [ACC.keys, t("Claves de API"), t("Para que otras apps y scripts usen Translay. Cada clave sirve para todas las bibliotecas o una, de lectura o escritura.")],
    [ACC.hooks, "Webhooks", t("Notificaciones a otras apps cuando ocurre un evento: un video listo, cambios en la cola, descargas, exportaciones…")],
  ],
};
i18nTrack(PREF_BLOCKS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

function prefControl(p) {
  if (p.key === "theme_mode") return appearanceRow(p);
  let opts = p.type === "bool" ? [[true, t("Sí")], [false, t("No")]] : p.options;
  if (p.key === "summary_model" && state.summaryRec) {  // «Automático» dice cuál usa en este equipo
    const rec = p.options.find(([k]) => k === state.summaryRec);
    opts = opts.map(([k, lbl]) => [k, k === "auto" && rec ? t("Automático ({name})", { name: rec[1] }) : lbl]);
  }
  if (p.key === "export_ask") return exportAskRow(p);
  if (p.key === "accent_color") return accentRow(p);
  if (p.key === "code_theme") return codeThemeRow(p);
  if (p.key === "agent_color") return swatchRow(p);
  if (p.key === "agent_avatar") return avatarRow(p);
  if (p.key === "agent_model") return agentModelRow(p);
  if (p.key === "home_bg") return homeBgRow(p);
  if (p.type === "text") return textRow(p);
  if (p.type === "range") return rangeRow(p);
  if (p.type === "bool") {  // interruptor
    const on = prefs[p.key] === true;
    return el("button", { type: "button", class: "switch" + (on ? " on" : ""), role: "switch", "aria-checked": String(on), "aria-label": p.label,
      on: { click: () => { setPref(p.key, !on); if (p.key === "notify" && !on) requestNotify(); renderPrefs(); } } }, el("i"));
  }
  if (opts.length > 4) {  // muchas opciones: lista desplegable (como grupo no caben en una fila)
    // el <option> guarda la posición: el valor vuelve con su tipo (número, texto…)
    const sel = el("select", { class: "select", "aria-label": p.label,
      on: { change: (e) => { setPref(p.key, opts[+e.target.value][0]); renderPrefs(); } } },
      ...opts.map(([value, text], i) => el("option", { value: String(i), text, selected: prefs[p.key] === value })));
    return el("div", { class: "pref-dd" }, sel);
  }
  return el("div", { class: "segs" }, ...opts.map(([value, text]) => el("button", { type: "button", class: "seg" + (prefs[p.key] === value ? " on" : ""),
    on: { click: () => { setPref(p.key, value); renderPrefs(); } } }, text)));
}

// una cantidad: deslizador propio con el valor en números. Se arrastra hasta donde uno quiera y se detiene un
// instante en los niveles habituales (topes suaves); doble clic vuelve al valor por defecto; rueda y flechas
// ajustan de a un paso. Se guarda al soltar.
function rangeRow(p) {
  let v = prefs[p.key] ?? p.default;
  const pct = (x) => ((x - p.min) / (p.max - p.min)) * 100;
  const fill = el("i", { class: "rg-fill" });
  const thumb = el("b", { class: "rg-thumb" });
  const track = el("div", { class: "rg-track" }, fill, thumb);
  const out = el("output", { class: "rg-val" });
  const box = el("div", { class: "rg", role: "slider", tabindex: "0", "aria-label": p.label,
    "aria-valuemin": p.min, "aria-valuemax": p.max }, track, out);
  const show = (x) => {
    v = x;
    fill.style.width = thumb.style.left = `${pct(x)}%`;
    out.textContent = `${x} ${p.unit || ""}`.trim();
    box.setAttribute("aria-valuenow", x);
  };
  const clamp = (x) => Math.min(p.max, Math.max(p.min, Math.round(x / p.step) * p.step));
  const save = () => { if (v !== prefs[p.key]) setPref(p.key, v); };
  const at = (e) => {
    const r = track.getBoundingClientRect();
    let x = p.min + ((e.clientX - r.left) / r.width) * (p.max - p.min);
    const stop = (p.stops || []).find((s) => Math.abs(s - x) <= (p.max - p.min) * 0.03);  // tope suave
    return clamp(stop ?? x);
  };
  box.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    box.setPointerCapture(e.pointerId);
    box.classList.add("drag");
    show(at(e));
    const move = (ev) => show(at(ev));
    const up = () => { box.classList.remove("drag"); box.removeEventListener("pointermove", move); save(); };
    box.addEventListener("pointermove", move);
    box.addEventListener("pointerup", up, { once: true });
    box.addEventListener("pointercancel", up, { once: true });
  });
  box.addEventListener("dblclick", () => { show(p.default); save(); });
  box.addEventListener("keydown", (e) => {
    const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (!d) return;
    e.preventDefault();
    show(clamp(v + d * p.step));
    save();
  });
  box.addEventListener("wheel", (e) => {
    e.preventDefault();
    show(clamp(v + (e.deltaY < 0 ? 1 : -1) * p.step));
    clearTimeout(box._t);
    box._t = setTimeout(save, 400);
  }, { passive: false });
  show(v);
  return box;
}

// color de énfasis: muestras (la primera, el del tema); con «Color de cada biblioteca» manda el de la biblioteca
function accentRow(p) {
  const cur = prefs.accent_color || "";
  return el("div", { class: "vcolors accent-colors" + (prefs.accent_lib ? " off" : "") }, ...p.options.map(([value, name]) =>
    el("button", { type: "button", class: "vcolor" + (value ? " split" : " theme") + (cur === value ? " on" : ""), title: name,
      "aria-label": name, "aria-pressed": String(cur === value), style: value ? `--vc: ${value}` : null,
      on: { click: () => { setPref(p.key, value); renderPrefs(); } } }, value ? splitSwatch() : icon("theme"))));
}

// texto libre (el nombre y el tono del agente): se guarda al dejar de escribir
function textRow(p) {
  const multi = !!p.multiline;
  const f = el(multi ? "textarea" : "input", { class: multi ? "area pref-text" : "field pref-text", maxlength: p.max || 200,
    "aria-label": p.label, rows: multi ? 3 : null, placeholder: p.key === "agent_tone"
      ? t("Ejemplo: explícame como a alguien que recién empieza, con ejemplos y en viñetas") : p.label });
  f.value = prefs[p.key] ?? "";
  let timer;
  const save = () => { clearTimeout(timer); const v = f.value.trim(); if (v !== (prefs[p.key] ?? "")) setPref(p.key, v); };
  f.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(save, 700); });
  f.addEventListener("blur", save);
  return el("div", { class: "pref-textwrap" + (multi ? " multi" : "") }, f);
}

const HOME_PREVIEW_W = 1120;
// fondo del inicio: las opciones a la izquierda y, al lado, el inicio de verdad
// (la misma luz y el mismo destacado de web/js/home.js, con lo que sigues viendo)
function homeBgRow(p) {
  const cur = homeBgMode();
  const ICON = { translay: "mic", recorrido: "arrow", luna: "moon", tierra: "globe", nubes: "sun", mar: "globe", arrecife: "flask", ballena: "music", atardecer: "theme", medusas: "spark", abismo: "eye", naufragio: "drive", "arañas": "atom", "arañas y perro": "paw", imagen: "upload" };
  const list = el("div", { class: "opt-list" }, ...p.options.map(([value, text]) => el("button", { type: "button",
    class: "code-theme" + (cur === value ? " on" : ""), "aria-pressed": String(cur === value), on: { click: () => {
      if (value === "imagen" && !prefs.home_bg_rev) { pickHomeBg(); return; }  // sin imagen aún: primero elegirla
      setPref(p.key, value); renderPrefs();
    } } }, icon(ICON[value] || "film"), text)),
    cur === "imagen" ? btn(t("Cambiar imagen"), { icon: "upload", size: "sm", variant: "ghost", onClick: pickHomeBg }) : null);
  const lead = typeof heroVideo === "function" ? heroVideo() : null;
  // el inicio se arma a tamaño de escritorio (HOME_PREVIEW_W) y se reduce entero: una miniatura fiel, sin apretar nada
  const first = typeof homeRows === "function" ? homeRows(lead?.v.id)[0] : null;  // y la primera fila, como en el inicio
  const stage = el("div", { class: "hp-stage" }, homeLight(lead?.v, cur, true),
    lead ? hero(lead) : el("p", { class: "home-preview-empty", text: t("Aquí aparecerá lo que sigues viendo") }),
    first ? row(first) : null);
  const preview = el("div", { class: "home-preview", "aria-label": t("Vista previa del inicio") }, stage);
  const fit = () => {
    const k = preview.clientWidth / HOME_PREVIEW_W;
    stage.style.transform = `scale(${k})`;
    preview.style.height = `${Math.round(stage.offsetHeight * k)}px`;
  };
  new ResizeObserver(fit).observe(preview);
  new ResizeObserver(fit).observe(stage);
  return el("div", { class: "opt-split" }, list, preview);
}

// la imagen propia: se reduce en el navegador (hasta 1920 px, JPEG) y se guarda en data/ui/home-bg.jpg
function pickHomeBg() {
  const f = el("input", { type: "file", accept: "image/*" });
  f.addEventListener("change", async () => {
    const file = f.files[0];
    if (!file) return;
    try {
      const bmp = await createImageBitmap(file);
      const k = Math.min(1, 1920 / bmp.width);
      const c = el("canvas", { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.85));
      const r = await fetch("/api/home-bg", { method: "PUT", body: blob });
      if (!r.ok) throw new Error(await r.text());
      setPref("home_bg_rev", String(Date.now()));
      setPref("home_bg", "imagen");
      renderPrefs();
    } catch {
      toast(t("No se pudo usar esa imagen. Prueba con otra."));
    }
  });
  f.click();
}

// color propio (el del agente): muestras como las del color de énfasis
function swatchRow(p) {
  const cur = prefs[p.key] || "";
  return el("div", { class: "vcolors", "data-pref": p.key }, ...p.options.map(([value, name]) =>
    el("button", { type: "button", class: "vcolor" + (value ? "" : " theme") + (cur === value ? " on" : ""), title: name, "data-v": value,
      "aria-label": name, "aria-pressed": String(cur === value), style: value ? `--vc: ${value}` : null,
      on: { click: () => { setPref(p.key, value); renderPrefs(); if (typeof renderAgent === "function") renderAgent(); } } },
    value ? null : icon("theme"))));
}

// modelo del agente: agrupados por si son compatibles con este equipo, con su calidad en el laboratorio y su tamaño
// (vt/agentsvc.py › catalog); «Automático» dice cuál usaría
// calidad en el laboratorio: palabra y su color (de verde a ámbar; «Poco confiable», el que inventa respuestas, en un rojo apagado)
const QUALITY_LEVEL = (q) => (q == null ? null : q >= 0.97 ? [t("Excelente"), "exc"] : q >= 0.9 ? [t("Muy buena"), "good"]
  : q >= 0.8 ? [t("Buena"), "ok"] : [t("Básica"), "low"]);
function agentModelRow(p) {
  const cat = state.agentModels;
  if (!cat) send({ type: "agent_models" });  // llega en un momento y la página se redibuja
  const info = new Map((cat?.models || []).map((m) => [m.key, m]));
  const name = (k) => info.get(k)?.name || (p.options.find(([v]) => v === k) || [k, k])[1];
  const gb = (m) => `${m.gb.toLocaleString(LOCALE, { maximumFractionDigits: 1 })} GB`;
  const opt = (k, text, hint) => { const o = new Option(text, k, false, (prefs[p.key] || "auto") === k); if (hint) o._hint = hint; return o; };
  const sel = el("select", { class: "select", "aria-label": p.label, on: { change: (e) => { setPref(p.key, e.target.value); renderPrefs(); } } });
  sel.append(opt("auto", cat?.recommended ? t("Automático ({name})", { name: name(cat.recommended) }) : t("Automático")));
  if (cat) {
    const ms = [...info.values()].sort((a, b) => (b.quality ?? 0) - (a.quality ?? 0));
    const hint = (m) => () => {
      const [word, tone] = m.honest ? QUALITY_LEVEL(m.quality) || ["", ""] : [t("Poco confiable"), "bad"];
      return el("kbd", { class: "model-hint" }, word ? el("b", { class: "q-" + tone, text: word }) : null,
        word ? " · " : "", m.downloaded ? t("descargado") : gb(m));
    };
    const groups = [
      [t("Recomendado"), ms.filter((m) => m.key === cat.recommended)],
      [t("Compatibles"), ms.filter((m) => m.key !== cat.recommended && m.fits && !m.slow)],
      [t("Lentos en este equipo"), ms.filter((m) => m.key !== cat.recommended && m.fits && m.slow)],
      [t("Necesitan más memoria"), ms.filter((m) => m.key !== cat.recommended && !m.fits)],
    ];
    for (const [label, list] of groups) {
      if (!list.length) continue;
      const g = el("optgroup", { label });
      for (const m of list) g.append(opt(m.key, m.name, hint(m)));
      sel.append(g);
    }
  } else {
    for (const [k, t] of p.options) if (k !== "auto") sel.append(opt(k, t));
  }
  return el("div", { class: "pref-model" }, el("div", { class: "pref-dd" }, sel), agentModelFile(cat));
}

// el archivo del modelo que se va a usar: descargado, bajando (avance en el botón) o «Descargar» de antemano
function agentModelFile(cat) {
  const key = prefs.agent_model && prefs.agent_model !== "auto" ? prefs.agent_model : cat?.recommended;
  const m = cat?.models.find((x) => x.key === key);
  if (!m) return null;
  const size = `${m.gb.toLocaleString(LOCALE, { maximumFractionDigits: 1 })} GB`;
  if (m.downloaded) return el("p", { class: "pref-model-file" }, icon("check"), t("Descargado · {size}", { size }));
  if (!canImport()) return el("p", { class: "pref-model-file", text: t("Se descarga con la primera pregunta · {size}", { size }) });
  const busy = m.downloading != null;
  return btn(busy ? t("Descargando {pct} %", { pct: m.downloading }) : t("Descargar · {size}", { size }), { icon: "download", size: "sm", variant: "ghost",
    disabled: busy, onClick: () => { m.downloading = 0; send({ type: "agent_model_download", key: m.key }); renderPrefs(); } });
}

// avatar del agente: íconos de línea, el elegido con su color
// el creador del agente (web/js/star.js): la estrella grande con sus estados y, al lado, cada parte con su muestra
// la estrella grande del creador es siempre el mismo elemento: Ajustes se redibuja al guardar (y otra vez cuando el
// servidor confirma), y así la transición de una estrella a otra sigue sin cortarse
// (los estados, el cambio de una estrella a otra y las muestras de cada parte están en web/js/star.js)
const starStage = { el: null, key: null, state: "", timer: null };
function avatarRow(p) {
  const look = agentLook();
  const key = () => JSON.stringify(agentLook()) + (prefs.agent_color || themeStarColor());
  const current = () => starSvg(agentLook(), null, starStage.state);
  if (!starStage.el) {
    starStage.el = el("div", { class: "star-big" }, current());
    starStage.el.addEventListener("click", agentBoop);  // tocarla: se pone contenta (web/js/agentview.js)
    starStage.key = key();
    // la vista previa pasa sola por sus gestos: en reposo, pensando y respondiendo (sin selector: elegido 2026-11-14)
    starStage.timer = setInterval(() => {
      if (!starStage.el.isConnected) return;
      starStage.state = STAR_STATES[(STAR_STATES.indexOf(starStage.state) + 1) % STAR_STATES.length];
      starStage.el.querySelector(".agent-star:not(.leaving)")?.setAttribute("class", ("agent-star " + starStage.state).trim());
    }, 2600);
  }
  const stage = starStage.el;
  const sync = () => {  // si cambió algo (aquí, otro color, el servidor), la nueva entra sobre la anterior
    if (starStage.key !== key()) { starStage.key = key(); starSwap(stage, current()); }
  };
  sync();
  const opts = {};  // parte → sus botones (para marcar la elegida y redibujar sus muestras)
  const refresh = () => {
    const now = agentLook();
    for (const [k, buttons] of Object.entries(opts)) {
      for (const b of buttons) {
        const on = now[k] === b.dataset.v;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", String(on));
        b.replaceChildren(starThumb({ ...now, [k]: b.dataset.v }, k));
      }
    }
    sync();
  };
  const save = (patch) => {
    setPref(p.key, JSON.stringify({ ...agentLook(), ...patch }));
    if (typeof renderAgent === "function") renderAgent();
    if (typeof refreshAgentPreviews === "function") refreshAgentPreviews();
  };
  const part = (k, label) => {
    opts[k] = STAR_PARTS[k].map(([value, name]) => {
      const b = el("button", { type: "button", class: "star-opt" + (look[k] === value ? " on" : ""), title: name, "aria-label": name,
        "aria-pressed": String(look[k] === value), "data-v": value }, starThumb({ ...look, [k]: value }, k));
      b.addEventListener("click", () => { if (agentLook()[k] !== value) { save({ [k]: value }); refresh(); } });
      return b;
    });
    // de a 4, grandes, con flechas para ver las anteriores y las siguientes (web/js/ui.js › carousel)
    return el("div", { class: "star-part" }, el("span", { text: label }),
      carousel(opts[k], { per: 4, start: opts[k].find((b) => b.classList.contains("on")), label }));
  };
  // al azar: todas las partes y el color, sin redibujar la página (el color, en su fila, se marca aparte)
  const random = btn(t("Al azar"), { icon: "dice", size: "sm", variant: "ghost", onClick: () => {
    const pick = (a) => a[Math.floor(Math.random() * a.length)];
    const now = agentLook();
    const patch = Object.fromEntries(Object.keys(STAR_PARTS).map((k) => [k, pick(STAR_PARTS[k].filter(([v]) => v !== now[k]))[0]]));
    const colors = (prefsSchema.find((x) => x.key === "agent_color")?.options || []).map((o) => o[0]).filter((c) => c && c !== prefs.agent_color);
    if (colors.length) {
      setPref("agent_color", pick(colors));
      document.querySelectorAll('[data-pref="agent_color"] [data-v]').forEach((x) => x.classList.toggle("on", x.dataset.v === prefs.agent_color));
    }
    save(patch);
    refresh();
  } });
  return el("div", { class: "star-maker" }, el("div", { class: "star-stage" }, stage, random),
    el("div", { class: "star-parts" }, part("shape", t("Forma")), part("eyes", t("Ojos")), part("mouth", t("Boca")),
      part("cheeks", t("Mejillas")), part("acc", t("Accesorio"))));
}

// colores del código (web/js/codetheme.js): los temas a la izquierda y, al lado, cómo se ve un ejemplo
function codeThemeRow(p) {
  const cur = CODE_THEMES[prefs.code_theme] ? prefs.code_theme : CODE_THEME_DEFAULT;
  const pre = el("pre", { class: "code-sample" });
  pre.append(highlight(CODE_SAMPLE));
  const list = el("div", { class: "code-themes opt-list" }, ...p.options.map(([value, name]) => {
    const t = codeThemeFor(value);  // su muestra en la versión del modo actual (claro u oscuro)
    return el("button", { type: "button", class: "code-theme" + (cur === value ? " on" : ""), "aria-pressed": String(cur === value),
      style: `--b: ${t.bg}; --c1: ${t.kw}; --c2: ${t.str}; --c3: ${t.fn}; --c4: ${t.com}`,
      on: { click: () => { setPref(p.key, value); applyCodeTheme(value); renderPrefs(); } } },
    el("i", { class: "code-swatch" }, el("b"), el("b"), el("b"), el("b")), name);
  }));
  return el("div", { class: "opt-split" }, list, pre);
}

// dónde guardar lo exportado: preguntar o una carpeta fija (que se elige con el cuadro de Windows)
function exportAskRow(p) {
  const dir = prefs.export_dir || "";
  const fixed = prefs.export_ask === "carpeta" && dir;
  return el("div", { class: "segs" },
    el("button", { type: "button", class: "seg" + (fixed ? "" : " on"), on: { click: () => { setPref("export_ask", "preguntar"); renderPrefs(); } } }, t("Preguntar")),
    el("button", { type: "button", class: "seg" + (fixed ? " on" : ""), title: dir,
      on: { click: () => { if (!dir || fixed) send({ type: "export_pick_folder" }); else { setPref("export_ask", "carpeta"); renderPrefs(); } } } },
    icon("folder"), dir ? shortPath(dir) : t("Elegir carpeta")));
}

function renderPrefs() {
  const nav = $("#prefs-nav");
  const body = $("#prefs-body");
  // escribiendo en esta misma página (una contraseña, una URL): se redibuja al salir del cuadro,
  // no a mitad (un aviso de otra pestaña borraría lo escrito)
  const f = document.activeElement;
  if (f && body.contains(f) && f.matches("input:not([type=checkbox]):not([type=radio]):not([type=range]), textarea")
      && body.dataset.sec === lib.prefSec) {
    if (!renderPrefs.pending) {
      renderPrefs.pending = true;
      f.addEventListener("blur", () => setTimeout(() => { renderPrefs.pending = false; renderPrefs(); }, 400), { once: true });
    }
    return;
  }
  $("#stash").append(YT_ACCOUNT, YT_IMPORT, GLOSSARY_BLOCK, VAULTS_BLOCK, TRASH_BLOCK,
    STORAGE_SUMMARY, STORAGE_LIBS, STORAGE_LARGEST, STORAGE_MODELS, STORAGE_APP, PERF_HW, PERF_PROFILE, PERF_LIMITS, PERF_ALERTS,
    ...Object.values(ACC));  // se vuelven a poner en su página
  if (!prefsSections.length) return;
  if (lib.prefSec === "youtube") lib.prefSec = "biblioteca";  // YouTube ahora está en Agregar y descargar
  if (!lib.prefSec || !prefsSections.some(([k]) => k === lib.prefSec)) lib.prefSec = "inicio";
  if (typeof syncRoute === "function" && currentView() === "prefs") syncRoute();
  const vaultKeys = new Set(prefsVaultKeys);
  const vaultName = typeof currentVault === "function" && vaults.list.length > 1 ? currentVault().name : "";
  // páginas y opciones de un solo modo (Ajustes › Uso): al solo transcribir no aparece lo de traducción
  const mode = transcribeMode() ? "transcribir" : "traducir";
  const sections = prefsSections.filter((s) => !s[4] || s[4] === mode).map((s) =>
    mode === "transcribir" && prefsAltSections[s[0]] ? [s[0], ...prefsAltSections[s[0]], s[3]] : s);
  if (lib.prefSec !== "inicio" && !sections.some(([k]) => k === lib.prefSec)) lib.prefSec = "inicio";
  // la barra lateral: el inicio y, debajo, las secciones por bloque (como en el inicio)
  const navItem = (k, title, ic) => el("button", { type: "button", class: "item" + (k === lib.prefSec ? " active" : ""),
    on: { click: () => { lib.prefSec = k; renderPrefs(); body.scrollTop = 0; } } }, el("span", {}, icon(ic || "sliders"), title));
  nav.replaceChildren(...prefsBlocks(sections).flatMap(([g, list]) => [el("h4", { text: g }), ...list.map(([k, title, , ic]) => navItem(k, title, ic))]));
  if (lib.prefSec === "inicio") {
    body.replaceChildren(renderPrefsHome(sections));
    body.dataset.sec = lib.prefSec;
    return;
  }
  const [sec, title, desc] = sections.find(([k]) => k === lib.prefSec);
  // volver al inicio de Ajustes (también con el botón Ajustes del encabezado)
  const back = el("button", { type: "button", class: "pref-back", on: { click: () => { lib.prefSec = "inicio"; renderPrefs(); body.scrollTop = 0; } } },
    icon("chevron"), t("Ajustes"));
  const page = el("div", { class: "pref-page" },
    el("header", { class: "pref-head" }, back, el("h2", { text: title }), desc ? el("p", { text: desc }) : null,
      vaultName && prefsSchema.some((p) => p.section === sec && vaultKeys.has(p.key)) || sec === "glosario" && vaultName
        ? el("span", { class: "pref-scope" }, vaultBadge(currentVault(), "xs"), t("Se guarda en «{name}»", { name: vaultName })) : null));
  // opciones, por grupo
  const groups = new Map();
  for (const base of prefsSchema.filter((x) => x.section === sec && (!x.only || x.only === mode))) {
    const p = mode === "transcribir" && base.alt ? { ...base, ...base.alt } : base;
    if (!groups.has(p.group)) groups.set(p.group, []);
    groups.get(p.group).push(p);
  }
  for (const [g, items] of groups) {
    const rows = items.map((p) => {
      const ctl = prefControl(p);
      if (!ctl) return null;
      // un texto largo (el tono del agente) o la cuadrícula de temas de código: a lo ancho, debajo del título
      const wide = (p.type === "text" && p.multiline) || p.key === "code_theme" || p.key === "home_bg";
      return el("div", { class: "set-row" + (wide ? " wide" : ""), id: `pref-${p.key}` },
        el("div", { class: "set-text" }, el("strong", { text: p.label }), p.desc ? el("p", { text: p.desc }) : null),
        el("div", { class: "set-ctl" }, ctl));
    }).filter(Boolean);
    // un grupo de una sola opción no repite su título (la opción ya lo tiene)
    if (rows.length) page.append(el("section", { class: "set-group" }, g && rows.length > 1 ? el("h3", { text: g }) : null, el("div", { class: "set-rows" }, ...rows)));
  }
  // bloques propios de la página
  if (sec === "bibliotecas") renderVaultsPref();
  if (sec === "acceso") renderAdmin();
  for (const [block, t, d] of (PREF_BLOCKS[sec] ? PREF_BLOCKS[sec]() : [])) {
    page.append(el("section", { class: "set-group block" }, el("h3", { text: t }), d ? el("p", { class: "set-desc", text: d }) : null, block));
  }
  // Ajustes › Agente: la vista previa es la misma al redibujar la página (no vuelve arriba al cambiar algo)
  let keep = null;
  if (sec === "agente" && typeof agentPreview === "function") {
    const old = body.querySelector(".pref-split-side .ag-preview");
    keep = old ? [old, old.querySelector(".ag-scroll").scrollTop] : null;
    if (old) refreshAgentPreviews();
    const [head, ...rest] = page.children;
    page.replaceChildren(head, el("div", { class: "pref-split" }, el("div", { class: "pref-split-main" }, ...rest),
      el("aside", { class: "pref-split-side" }, old || agentPreview())));
  }
  body.replaceChildren(page);
  if (keep) keep[0].querySelector(".ag-scroll").scrollTop = keep[1];
  body.dataset.sec = lib.prefSec;
}
// las secciones repartidas en sus bloques; las que no están en ninguno, en uno sin título al final
function prefsBlocks(sections) {
  const byKey = new Map(sections.map((s) => [s[0], s]));
  const used = new Set();
  const out = prefsGroups.map(([g, keys]) => [g, keys.filter((k) => byKey.has(k)).map((k) => { used.add(k); return byKey.get(k); })])
    .filter(([, list]) => list.length);
  const rest = sections.filter((s) => !used.has(s[0]));
  if (rest.length) out.push([t("Más"), rest]);
  return out;
}

// el inicio de Ajustes: una tarjeta por sección (ícono, título y qué hay dentro), por bloque, y una búsqueda que
// también encuentra las opciones de cada sección («subtítulos» lleva a Audio y subtítulos)
function renderPrefsHome(sections) {
  const grid = el("div", { class: "set-home-grid" });
  const draw = (q) => {
    q = (q || "").trim().toLowerCase();
    const hit = (s) => !q || [s[1], s[2], ...prefsSchema.filter((p) => p.section === s[0]).flatMap((p) => [p.label, p.desc])]
      .some((t) => (t || "").toLowerCase().includes(q));
    const blocks = prefsBlocks(sections).map(([g, list]) => [g, list.filter(hit)]).filter(([, list]) => list.length);
    grid.replaceChildren(...(blocks.length ? blocks.map(([g, list]) => el("section", { class: "set-home-block" },
      el("h3", { text: g }),
      el("div", { class: "set-cards" }, ...list.map(([k, title, desc, ic]) => el("button", { type: "button", class: "set-card",
        on: { click: () => { lib.prefSec = k; renderPrefs(); $("#prefs-body").scrollTop = 0; } } },
        el("span", { class: "set-card-ic" }, icon(ic || "sliders")), el("strong", { text: title }), desc ? el("p", { text: desc }) : null)))))
      : [emptyState("search", t("Sin resultados"), t("Prueba con otra palabra, como «subtítulos» o «modelo»."))]));
  };
  const input = el("input", { type: "search", placeholder: t("Buscar en ajustes"), "aria-label": t("Buscar en ajustes"),
    on: { input: (e) => draw(e.target.value) } });
  draw("");
  return el("div", { class: "pref-page set-home" },
    el("header", { class: "pref-head set-home-head" }, el("h2", { text: t("Ajustes") }),
      el("label", { class: "field set-search" }, icon("search"), input)),
    grid);
}
function markPrefsNav() {}  // (antes: índice que seguía el scroll; ahora cada sección es su página)
function openPrefs(sec) {
  lib.prefSec = sec;
  setView("prefs");
  renderPrefs();
}

// Apariencia: el modo, con íconos.
function appearanceRow(p) {
  const choose = (value) => {
    setPref(p.key, value);
    applyTheme();
    renderPrefs();
  };
  const seg = (value, on, ...kids) => el("button", { type: "button", class: "seg" + (on ? " on" : ""), on: { click: () => choose(value) } }, ...kids);
  if (p.key === "theme_mode") {
    const icons = { sistema: "monitor", claro: "sun", oscuro: "moon" };
    return el("div", { class: "segs" }, ...p.options.map(([v, t]) => seg(v, prefs.theme_mode === v, icon(icons[v]), t)));
  }
  return null;
}

$("#prefs-btn").addEventListener("click", () => togglePrefs());

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

/* ------------------------------------------------------------ sesión de YouTube */
// La cuenta conectada (vt/ytsession.py): se inicia sesión una vez en una ventana del
// navegador con un perfil propio de Translay y desde ahí se renueva sola. O, a mano,
// importarla desde un navegador detectado o subir el cookies.txt exportado.
const ytAcc = { status: null, browser: null };
const canConnectYouTube = (a) => !!a?.available && !!a.browsers?.length && state.access.local && state.access.owner;

function connectYouTube(key = ytAcc.browser || ytAcc.status?.browser || ytAcc.status?.browsers?.[0]?.key) {
  send({ type: "yt_connect", browser: key });
}

function renderAccount(a) {
  ytAcc.status = a;
  const browsers = a.browsers || [];
  if (!browsers.some((b) => b.key === ytAcc.browser)) ytAcc.browser = a.browser && browsers.some((b) => b.key === a.browser)
    ? a.browser : browsers[0]?.key || null;
  const name = (browsers.find((b) => b.key === ytAcc.browser) || {}).name || "";
  const acts = $("#yt-acc-acts"), status = $("#yt-acc-status");
  acts.replaceChildren();
  YT_ACCOUNT.hidden = !a.available;
  if (!a.available) return;
  const busy = { conectando: t("Esperando inicio de sesión…"), renovando: t("Renovando…"), desconectando: t("Desconectando…") }[a.busy];
  if (a.connected && !a.expired) {
    acts.append(btn(busy || t("Desconectar"), { icon: "x", disabled: !!busy || !state.access.local,
      onClick: () => send({ type: "yt_disconnect" }) }));
    status.textContent = t("Conectada con {browser} · renovada {ago}", { browser: a.browser_name, ago: ago(a.renewed) });
    return;
  }
  if (!browsers.length) {
    status.textContent = t("No se encontró un navegador compatible (Brave, Chrome, Edge, Vivaldi o Chromium). Usa «Subir cookies.txt».");
    return;
  }
  const label = busy || (a.expired ? t("Volver a conectar con {name}", { name }) : t("Conectar con {name}", { name }));
  const main = btn(label, { icon: "user", variant: "dark", disabled: !!busy || !state.access.local, onClick: () => connectYouTube() });
  acts.append(main);
  if (browsers.length > 1 && !busy) acts.append(btn(t("Otro navegador"), { icon: "chevron", disabled: !state.access.local,
    onClick: (e) => {
      e.stopPropagation();
      openMenu(browsers.map((b) => ({ label: b.name, check: b.key === ytAcc.browser,
        onClick: () => { ytAcc.browser = b.key; renderAccount(ytAcc.status); } })), e.currentTarget.getBoundingClientRect());
    } }));
  status.textContent = !state.access.local ? t("Solo se puede conectar desde el equipo donde se ejecuta Translay.")
    : a.busy === "conectando" ? t("Inicia sesión en YouTube en la ventana de {name} y ciérrala.", { name })
    : a.expired ? t("La sesión de YouTube expiró") : t("Sin cuenta conectada");
}

function renderCookies(m) {
  if (m.account) renderAccount(m.account);
  if (m.connected_now) toast(t("Cuenta de YouTube conectada. Se usará en las descargas."), "ok");
  if (m.disconnected) toast(t("Cuenta de YouTube desconectada y borrada de este equipo."), "ok");
  if (m.cancelled) toast(t("Se cerró la ventana sin iniciar sesión en YouTube."), "warn");
  const box = $("#yt-browsers");
  box.replaceChildren();
  for (const b of m.browsers) {
    box.append(el("button", { type: "button", class: "btn sm", text: t("Importar de {name}", { name: b.name }), on: { click: () => {
      $("#cookies-status").textContent = t("leyendo la sesión de {name}…", { name: b.name });
      send({ type: "cookies_import", browser: b.key });
    } } }));
  }
  const st = m.status || {};
  $("#cookies-status").textContent = st.present
    ? t("Sesión importada · {count} cookies · {session} · {updated}", { count: st.count, updated: st.updated,
      session: st.logged_in ? t("con sesión iniciada") : t("sin sesión iniciada") })
    : t("Sin sesión importada");
  if (m.error) toast(m.error);
  if (m.imported) {
    const fromFile = m.imported.source === "archivo", source = m.imported.source;
    if (m.imported.logged_in) toast(fromFile ? t("Sesión de YouTube importada del archivo. Se usará en las descargas.")
      : t("Sesión de YouTube importada de {source}. Se usará en las descargas.", { source }), "ok");
    else toast(fromFile ? t("Se importaron cookies del archivo, pero no hay una sesión de YouTube iniciada. Inicia sesión en YouTube y vuelve a importar.")
      : t("Se importaron cookies de {source}, pero no hay una sesión de YouTube iniciada. Inicia sesión en YouTube y vuelve a importar.", { source }), "warn");
  }
}

$("#cookies-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  $("#cookies-status").textContent = t("importando el archivo…");
  try {
    const r = await fetch("/api/cookies", { method: "PUT", body: f });
    if (!r.ok) toast(t("No se pudo importar: {error}", { error: await r.text() }));
  } catch (err) {
    toast(t("No se pudo subir el archivo"));
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


/* ------------------------------------------------------------ personas del video */
const escapeHtml = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// color de la persona n (1, 2…, en orden de aparición): el mismo en la transcripción y en Personas
function whoClass(n) { return `who-${(n - 1) % 5}`; }
function personName(spk, n) { return state.people.names[String(spk)] || `P${n}`; }

// Nombre de cada persona y la voz que usa en español (la suya clonada o la de otra persona)
function renderPeople() {
  updateSideTabs();
  const box = $("#people");
  if (box.hidden) return;
  const order = new Map(), count = new Map();
  for (const s of state.segments) {
    if (s.speaker == null) continue;
    if (!order.has(s.speaker)) order.set(s.speaker, order.size + 1);
    count.set(s.speaker, (count.get(s.speaker) || 0) + 1);
  }
  if (box.contains(document.activeElement)) return;  // no redibujar mientras se escribe un nombre
  const refs = state.people.refs || {};
  const saved = state.peopleSaved || [];
  const savedUrl = (v) => v?.startsWith("p:") ? saved.find((p) => p.id === v.slice(2))?.url : null;
  const names = el("datalist", { id: "people-names" }, ...saved.map((p) => el("option", { value: p.name })));
  const vname = typeof currentVault === "function" ? (vaultById(state.videoVault) || currentVault()).name : t("la biblioteca");
  const rows = [...order].map(([spk, n]) => {
    const key = String(spk);
    const name = el("input", { class: "input", type: "text", maxlength: 60, placeholder: t("Persona {n}", { n }), list: "people-names",
      value: state.people.names[key] || "", "aria-label": t("Nombre de la persona {n}", { n }) });
    name.addEventListener("change", () => send({ type: "people_set", video: state.videoId, spk: key, name: name.value }));
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") name.blur(); });
    const voice = el("select", { class: "select", "aria-label": t("Voz en {lang}", { lang: langName(targetLang()) }) },
      el("option", { value: "", text: refs[key] ? t("Su propia voz") : t("Su voz (aún sin referencia)") }),
      ...[...order].filter(([o]) => o !== spk && refs[String(o)])
        .map(([o, m]) => el("option", { value: String(o), text: t("Voz de {name}", { name: personName(o, m) }) })),
      saved.length ? el("optgroup", { label: t("Guardadas en «{name}»", { name: vname }) },
        ...saved.map((p) => el("option", { value: `p:${p.id}`, text: t("Voz de {name}", { name: p.name }) }))) : null);
    voice.value = state.people.voices[key] || "";
    voice.addEventListener("change", () => send({ type: "people_set", video: state.videoId, spk: key, voice: voice.value }));
    const used = state.people.voices[key] || key;
    const usedUrl = savedUrl(used) || refs[used];
    const listen = usedUrl ? previewBtn(usedUrl, t("Escuchar la voz de referencia")) : null;
    // guardar a esta persona (nombre y su voz) para usarla en otros videos de la biblioteca
    const nm = (state.people.names[key] || "").trim();
    const same = saved.find((p) => p.name.toLowerCase() === nm.toLowerCase() && nm);
    const keep = refs[key] ? btn(same ? t("Actualizar voz") : t("Guardar"), { icon: "bookmark", size: "xs", variant: "ghost", cls: "owner-only",
      title: t("Guardar su nombre y su voz en «{name}»", { name: vname }),
      onClick: () => send({ type: "people_save", video: state.videoId, spk: key, name: nm || t("Persona {n}", { n }), id: same?.id || "" }) }) : null;
    return el("div", { class: "person" },
      el("span", { class: `chip who ${whoClass(n)}`, text: `P${n}` }),
      el("div", { class: "pfields" }, name, voice),
      el("div", { class: "pmeta" }, el("small", { text: count.get(spk) === 1 ? t("1 frase") : t("{n} frases", { n: count.get(spk) }) }),
        el("span", { class: "pacts" }, keep, listen)));
  });
  // las guardadas en la biblioteca (para escucharlas u olvidarlas)
  const kept = saved.length ? el("div", { class: "people-saved" },
    el("h4", { text: t("Guardadas en «{name}»", { name: vname }) }),
    ...saved.map((p) => el("div", { class: "psaved" },
      el("span", { text: p.name }),
      el("span", { class: "pacts" },
        previewBtn(p.url, t("Escuchar esta voz")),
        btn(t("Olvidar"), { icon: "x", size: "xs", variant: "ghost", cls: "owner-only", onClick: async () => {
          if (await confirmDlg(t("¿Olvidar a {name}?", { name: p.name }), t("Los videos que usan esta voz recuperarán la voz original de cada persona al procesarse de nuevo."), t("Olvidar"))) {
            send({ type: "people_forget", id: p.id, vault: state.videoVault });
          }
        } }))))) : null;
  box.replaceChildren(names, ...rows, kept || "");
  if (typeof can === "function" && !can("owner")) {
    for (const x of box.querySelectorAll("input, select")) x.disabled = true;
  }
}

/* ------------------------------------------------------------ glosario */
const GLOSSARY_BLOCK = el("div", { class: "pref glossary", id: "pref-glossary" },
  el("span", { class: "pref-label", text: t("Términos") }), el("div", { class: "pref-ctl" }));
i18nTrack(GLOSSARY_BLOCK);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const glossary = { entries: [], dirty: false };

function glossaryUpdate(entries) {
  glossary.entries = entries || [];
  if (!glossary.dirty) renderGlossary(glossary.entries);
}
function renderGlossary(entries) {
  const ctl = GLOSSARY_BLOCK.querySelector(".pref-ctl");
  const rows = el("div", { class: "grows" });
  const addRow = (e = { src: "", dst: "" }) => {
    const src = el("input", { class: "input", type: "text", maxlength: 120, placeholder: t("Como en el original"), value: e.src });
    const dst = el("input", { class: "input", type: "text", maxlength: 120, placeholder: t("Sin traducir"), value: e.dst });
    const row = el("div", { class: "grow" }, src, el("span", { class: "arrow", text: "→" }), dst,
      btn(t("Quitar"), { icon: "x", size: "xs", variant: "ghost", onClick: () => { row.remove(); glossary.dirty = true; } }));
    for (const i of [src, dst]) i.addEventListener("input", () => { glossary.dirty = true; });
    rows.append(row);
    return src;
  };
  for (const e of entries) addRow(e);
  if (!entries.length) addRow();
  const save = btn(t("Guardar glosario"), { icon: "check", variant: "dark", onClick: () => {
    const items = [...rows.querySelectorAll(".grow")].map((r) => {
      const [a, b] = r.querySelectorAll("input");
      return { src: a.value.trim(), dst: b.value.trim() };
    }).filter((x) => x.src);
    glossary.dirty = false;
    send({ type: "glossary_set", entries: items });
    toast(t("Glosario guardado. Se volverán a traducir las frases afectadas."), "ok");
  } });
  ctl.replaceChildren(rows, el("div", { class: "acts" },
    btn(t("Agregar término"), { icon: "plus", onClick: () => addRow().focus() }), save),
    el("small", { class: "label", text: t("Si la traducción queda vacía, el término se mantiene como en el original (nombres, marcas, siglas).") }));
}
renderGlossary([]);

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
