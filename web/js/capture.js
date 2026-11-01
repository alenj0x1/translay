"use strict";
// Grabar pantalla: una pestaña, una ventana o toda la pantalla (el selector del navegador),
// toda la imagen o una zona, y a la biblioteca como un video más.
//
// Nada se pierde aunque se corte la red o se cierre la pestaña:
//   - MediaRecorder entrega una parte por segundo; cada una se guarda en IndexedDB
//     antes de subirla (PUT /api/capture/<id>/<n>, vt/capture.py) y se borra cuando
//     el servidor la confirma. Sin conexión se sigue grabando y se sube al volver.
//   - Al abrir la app, lo que quedó sin subir (pestaña cerrada, equipo apagado) se
//     termina de subir y se arma solo. Un solo dueño por grabación (navigator.locks).
//   - En vivo, el audio va por un WebSocket propio (otra sesión: no choca con lo que
//     se está viendo) para tener transcripción y traducción mientras se graba. Lo no
//     confirmado («covered») se guarda y se reenvía al reconectar. Si algo no llegó a
//     procesarse en vivo, la cola lo completa con el archivo final.
//
// Zona: al pasar el cursor sobre la vista previa se resaltan los recuadros detectados
// (detectBoxes): donde la imagen se mueve sin parar (un video) y las cajas de bordes
// rectos (ventanas, paneles, reproductores). Clic elige, la rueda pasa al recuadro que
// lo contiene y arrastrar marca una zona a mano. El recorte lo hace el servidor.

const CAP_DB = "translay-capture";
// altura y tope de video (kbit/s) a 30 cuadros: los mismos de vt/capture.py (QUALITY)
const CAP_Q = {
  alta: { label: "Alta", h: 1080, kbps: 4000 },
  media: { label: "Media", h: 720, kbps: 2000 },
  ligera: { label: "Ligera", h: 480, kbps: 900 },
  audio: { label: "Solo audio", h: 0, kbps: 0 },
};
const CAP_PART_MS = 1000;
const CAP_LIVE_KEEP = 600;  // segundos de audio sin confirmar que se guardan para reenviar

const capOpts = { q: "media", fps: 30 };
try { Object.assign(capOpts, JSON.parse(localStorage.getItem("capOpts") || "{}")); } catch { /* sin almacenamiento */ }
if (!CAP_Q[capOpts.q]) capOpts.q = "media";

/* ------------------------------------------------------------ IndexedDB */
// captures: {id, title, lib, q, fps, crop, parts, ended, started}; parts: {id, seq, blob}
let capDbP = null;
function capDb() {
  capDbP ||= new Promise((res, rej) => {
    const r = indexedDB.open(CAP_DB, 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore("captures", { keyPath: "id" });
      r.result.createObjectStore("parts", { keyPath: ["id", "seq"] });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  return capDbP;
}
async function capTx(stores, mode, fn) {
  const db = await capDb();
  return new Promise((res, rej) => {
    const tx = db.transaction(stores, mode);
    let out;
    Promise.resolve(fn(...[stores].flat().map((s) => tx.objectStore(s)))).then((v) => { out = v; });
    tx.oncomplete = () => res(out);
    tx.onerror = tx.onabort = () => rej(tx.error);
  });
}
const idbReq = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
const capPut = (rec) => capTx("captures", "readwrite", (s) => s.put(rec));
const capGetAll = () => capTx("captures", "readonly", (s) => idbReq(s.getAll()));
const capPartPut = (id, seq, blob) => capTx("parts", "readwrite", (s) => s.put({ id, seq, blob }));
const capPartGet = (id, seq) => capTx("parts", "readonly", (s) => idbReq(s.get([id, seq])));
const capPartsDrop = (id, below) => capTx("parts", "readwrite", (s) => s.delete(IDBKeyRange.bound([id, 0], [id, below], false, true)));
const capDrop = (id) => capTx(["captures", "parts"], "readwrite", (c, p) => {
  c.delete(id);
  p.delete(IDBKeyRange.bound([id, 0], [id, Infinity]));
});

/* ------------------------------------------------------------ estimación del peso */
// Lo que mide el archivo final: la zona (o toda la imagen) a la altura de la calidad
function capOutSize(w, h, q) {
  const H = CAP_Q[q].h;
  if (!H || !w || !h) return null;
  const s = Math.min(1, H / h);
  return { w: Math.floor((w * s) / 2) * 2, h: Math.floor((h * s) / 2) * 2 };
}
// kbit/s de video: el tope de la calidad, proporcional a los píxeles (una zona chica pesa menos)
function capKbps(out, q, fps) {
  const { h: H, kbps } = CAP_Q[q];
  if (!H || !out) return 0;
  const share = Math.min(1, Math.max(0.25, (out.w * out.h) / ((H * 16) / 9 * H)));
  return Math.round(kbps * share * (fps < 30 ? 2 / 3 : 1));
}
const capAudioKbps = (q) => (q === "audio" ? 96 : 128);
const capMBperMin = (kbps, q) => ((kbps + capAudioKbps(q)) * 60) / 8 / 1000;
function fmtMB(mb) {
  if (mb >= 1000) return `${(mb / 1000).toLocaleString("es", { maximumFractionDigits: 1 })} GB`;
  return `${mb < 10 ? mb.toLocaleString("es", { maximumFractionDigits: 1 }) : Math.round(mb)} MB`;
}
const fmtClock = (s) => {
  s = Math.floor(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`;
};

/* ------------------------------------------------------------ detección de recuadros */
// Sobre una copia chica de la imagen (DW de ancho). Todo en coordenadas 0..1.
const DW = 480, CELL = 8;
const det = { w: 0, h: 0, prev: null, act: null, boxes: [], rects: [], motion: [], t: 0 };

function detReset() {
  Object.assign(det, { w: 0, h: 0, prev: null, act: null, boxes: [], rects: [], motion: [], t: 0 });
}

function detGray(video, canvas) {
  const vw = video.videoWidth, vh = video.videoHeight;
  if (!vw || !vh) return null;
  const w = DW, h = Math.max(CELL, Math.round((DW * vh) / vw));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const c = canvas.getContext("2d", { willReadFrequently: true });
  c.drawImage(video, 0, 0, w, h);
  const d = c.getImageData(0, 0, w, h).data;
  const g = new Uint8Array(w * h);
  for (let i = 0, j = 0; j < g.length; i += 4, j++) g[j] = (d[i] * 77 + d[i + 1] * 150 + d[i + 2] * 29) >> 8;
  return { g, w, h };
}

// Movimiento: cada celda guarda qué tan seguido cambia; las que cambian casi siempre son video
function detMotion({ g, w, h }) {
  const cw = Math.floor(w / CELL), ch = Math.floor(h / CELL);
  if (!det.prev || det.w !== w || det.h !== h) {
    det.w = w; det.h = h; det.prev = g; det.act = new Float32Array(cw * ch);
    return;
  }
  for (let cy = 0; cy < ch; cy++) {
    for (let cx = 0; cx < cw; cx++) {
      let diff = 0;
      for (let y = cy * CELL; y < cy * CELL + CELL; y += 2) {
        for (let x = cx * CELL; x < cx * CELL + CELL; x += 2) diff += Math.abs(g[y * w + x] - det.prev[y * w + x]);
      }
      const k = cy * cw + cx;
      det.act[k] = det.act[k] * 0.9 + (diff / 16 > 2.5 ? 0.1 : 0);  // ~3 s de memoria
    }
  }
  det.prev = g;
  // celdas activas → grupos conectados (con un hueco de una celda) → sus rectángulos
  const on = (x, y) => x >= 0 && y >= 0 && x < cw && y < ch && det.act[y * cw + x] > 0.18;
  const seen = new Uint8Array(cw * ch), out = [];
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) {
      if (seen[y * cw + x] || !on(x, y)) continue;
      let x0 = x, x1 = x, y0 = y, y1 = y, n = 0;
      const stack = [[x, y]];
      seen[y * cw + x] = 1;
      while (stack.length) {
        const [px, py] = stack.pop();
        n++;
        x0 = Math.min(x0, px); x1 = Math.max(x1, px); y0 = Math.min(y0, py); y1 = Math.max(y1, py);
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            const nx = px + dx, ny = py + dy;
            if (on(nx, ny) && !seen[ny * cw + nx]) { seen[ny * cw + nx] = 1; stack.push([nx, ny]); }
          }
        }
      }
      const r = { x: x0 / cw, y: y0 / ch, w: (x1 - x0 + 1) / cw, h: (y1 - y0 + 1) / ch };
      if (r.w * r.h >= 0.004 && n >= 4) out.push(r);
    }
  }
  det.motion = out;
}

// Cajas: segmentos largos de borde horizontales y verticales que se cierran en rectángulo
function detRects({ g, w, h }) {
  const T = 10, GAP = 2, MINH = 28, MINV = 18;  // T: bordes suaves de interfaces claras (gris sobre blanco)
  const hs = [], vs = [];
  for (let y = 1; y < h; y++) {
    let s = -1, miss = 0;
    for (let x = 0; x <= w; x++) {
      const e = x < w && Math.abs(g[y * w + x] - g[(y - 1) * w + x]) > T;
      if (e) { if (s < 0) s = x; miss = 0; } else if (s >= 0 && ++miss > GAP) {
        if (x - miss - s >= MINH) hs.push({ y, a: s, b: x - miss });
        s = -1; miss = 0;
      }
    }
  }
  for (let x = 1; x < w; x++) {
    let s = -1, miss = 0;
    for (let y = 0; y <= h; y++) {
      const e = y < h && Math.abs(g[y * w + x] - g[y * w + x - 1]) > T;
      if (e) { if (s < 0) s = y; miss = 0; } else if (s >= 0 && ++miss > GAP) {
        if (y - miss - s >= MINV) vs.push({ x, a: s, b: y - miss });
        s = -1; miss = 0;
      }
    }
  }
  // los más largos primero; un borde de 2 px de grosor cuenta una vez
  const thin = (list, key) => {
    list.sort((p, q) => (q.b - q.a) - (p.b - p.a));
    const kept = [];
    for (const s of list) {
      if (!kept.some((k) => Math.abs(k[key] - s[key]) <= 2 && s.a >= k.a - 3 && s.b <= k.b + 3)) kept.push(s);
      if (kept.length >= 160) break;
    }
    return kept;
  };
  const H = thin(hs, "y"), V = thin(vs, "x");
  const rects = [];
  for (let i = 0; i < H.length; i++) {
    for (let j = 0; j < H.length; j++) {
      const t = H[i], b = H[j];
      if (b.y - t.y < MINV) continue;
      const a = Math.max(t.a, b.a), z = Math.min(t.b, b.b);
      if (z - a < MINH) continue;
      const xs = V.filter((v) => v.a <= t.y + 3 && v.b >= b.y - 3 && v.x >= a - 3 && v.x <= z + 3).map((v) => v.x).sort((p, q) => p - q);
      if (xs.length < 2) continue;
      const add = (l, r) => { if (r - l >= MINH) rects.push({ x: l / w, y: t.y / h, w: (r - l) / w, h: (b.y - t.y) / h }); };
      add(xs[0], xs[xs.length - 1]);
      for (let k = 1; k < xs.length; k++) if (xs[k] - xs[k - 1] >= MINH) add(xs[k - 1], xs[k]);
    }
  }
  const out = [];
  for (const r of rects.sort((p, q) => q.w * q.h - p.w * p.h)) {
    if (r.w * r.h < 0.008 || r.w * r.h > 0.97) continue;
    if (!out.some((o) => iou(o, r) > 0.88)) out.push(r);
    if (out.length >= 60) break;
  }
  det.rects = out;
}

function iou(a, b) {
  const x = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
  const y = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const i = x * y;
  return i / (a.w * a.h + b.w * b.h - i || 1);
}
const inside = (r, px, py) => px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h;

// Lo de m que cae dentro de r (0..1)
function covered(r, m) {
  const x = Math.max(0, Math.min(r.x + r.w, m.x + m.w) - Math.max(r.x, m.x));
  const y = Math.max(0, Math.min(r.y + r.h, m.y + m.h) - Math.max(r.y, m.y));
  return (x * y) / (m.w * m.h || 1);
}

// Una pasada: movimiento siempre; cajas cada segundo. Lo que se mueve se ajusta a la caja más
// chica que lo contiene (un video con partes quietas igual toma todo su reproductor).
function detectBoxes(video, canvas) {
  const f = detGray(video, canvas);
  if (!f) return;
  detMotion(f);
  const now = performance.now();
  if (now - det.t > 1000) { det.t = now; detRects(f); }
  const videos = [];
  for (const m of det.motion) {
    const box = det.rects.filter((r) => covered(r, m) > 0.85 && r.w * r.h < 0.9)
      .sort((p, q) => p.w * p.h - q.w * q.h)[0] || (m.w * m.h >= 0.01 ? m : null);
    if (box && !videos.some((v) => iou(v, box) > 0.88)) videos.push({ ...box, video: true });
  }
  det.boxes = [...videos, ...det.rects.filter((r) => !videos.some((v) => iou(v, r) > 0.88))];
}

// Recuadros bajo el cursor, del más chico al más grande (un video primero si está ahí)
function boxesAt(px, py) {
  const list = det.boxes.filter((b) => inside(b, px, py)).sort((a, b) => a.w * a.h - b.w * b.h);
  const vid = list.findIndex((b) => b.video);
  if (vid > 0) list.unshift(...list.splice(vid, 1));
  return list;
}

/* ------------------------------------------------------------ elegir fuente y zona */
const capUI = { stream: null, zone: null, hover: null, level: 0, drag: null, raf: 0, timer: 0 };
const capDlg = $("#cap-dlg"), capPrev = $("#cap-preview"), capBoxes = $("#cap-boxes");
const capWork = document.createElement("canvas");

const canCapture = () => !!navigator.mediaDevices?.getDisplayMedia && window.isSecureContext;
$("#cap-btn").hidden = !canCapture();

async function pickSource() {
  try {
    return await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: 30, max: 30 } },
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      systemAudio: "include", selfBrowserSurface: "exclude", surfaceSwitching: "include", monitorTypeSurfaces: "include",
    });
  } catch (e) {
    if (e?.name !== "NotAllowedError" && e?.name !== "AbortError") toast("No se pudo compartir la pantalla.");
    return null;
  }
}

function capStopStream(s) { s?.getTracks().forEach((t) => t.stop()); }

async function openCapture() {
  $("#import-pop").hidden = true;
  if (capRec.rec) return toast("Ya se está grabando la pantalla.", "warn");
  const s = await pickSource();
  if (!s) return;
  capUseStream(s);
  if (!capDlg.open) capDlg.showModal();
}

function capUseStream(s) {
  capStopStream(capUI.stream);
  capUI.stream = s;
  capUI.zone = capUI.hover = null;
  detReset();
  capPrev.srcObject = s;
  capPrev.play().catch(() => {});
  s.getVideoTracks()[0]?.addEventListener("ended", () => { if (capDlg.open && capUI.stream === s) capDlg.close("cancel"); });
  clearInterval(capUI.timer);
  capUI.timer = setInterval(() => { if (capDlg.open) { detectBoxes(capPrev, capWork); capDraw(); } }, 250);
  capRender();
}

function capSrcSize() {
  return { w: capPrev.videoWidth || 0, h: capPrev.videoHeight || 0 };
}

// la zona elegida en píxeles del video
function capCropPx() {
  const z = capUI.zone, { w, h } = capSrcSize();
  if (!z || !w) return null;
  const even = (n) => Math.floor(n / 2) * 2;  // como la recorta el servidor (H.264: lados pares)
  return { x: even(z.x * w), y: even(z.y * h), w: even(z.w * w), h: even(z.h * h) };
}

function capRender() {
  const hasAudio = !!capUI.stream?.getAudioTracks().length;
  const hasVideo = !!capUI.stream?.getVideoTracks().length;
  $("#cap-warn").textContent = hasAudio ? ""
    : "Esta fuente no trae sonido y sin él no hay nada que traducir. Comparte una pestaña o la pantalla completa con «Compartir audio» activado.";
  $("#cap-go").disabled = !hasAudio;
  const audioOnly = capOpts.q === "audio";
  $("#cap-stage").hidden = audioOnly || !hasVideo;
  $("#cap-zone-row").hidden = audioOnly || !hasVideo;
  $("#cap-fps-row").hidden = audioOnly;
  for (const b of $("#cap-q").children) b.classList.toggle("on", b.dataset.q === capOpts.q);
  for (const b of $("#cap-fps").children) b.classList.toggle("on", Number(b.dataset.fps) === capOpts.fps);
  const src = capSrcSize(), crop = capCropPx();
  const out = capOutSize(crop?.w || src.w, crop?.h || src.h, capOpts.q);
  $("#cap-zone").textContent = !src.w ? "" : crop ? `Zona · ${crop.w} × ${crop.h}` : `Toda la imagen · ${src.w} × ${src.h}`;
  $("#cap-all").hidden = !crop;
  const mb = capMBperMin(capKbps(out, capOpts.q, capOpts.fps), capOpts.q);
  $("#cap-size").textContent = (out ? `${out.w} × ${out.h} · ` : "") + `hasta ${fmtMB(mb)} por minuto, ${fmtMB(mb * 60)} por hora`;
}

// el video ocupa la caja con «contain»: dónde quedó dibujado
function capFit() {
  const r = capBoxes.getBoundingClientRect(), { w, h } = capSrcSize();
  if (!w) return null;
  const s = Math.min(r.width / w, r.height / h);
  return { r, ox: (r.width - w * s) / 2, oy: (r.height - h * s) / 2, dw: w * s, dh: h * s };
}
function capPoint(e) {
  const f = capFit();
  if (!f) return null;
  return { x: Math.min(1, Math.max(0, (e.clientX - f.r.left - f.ox) / f.dw)), y: Math.min(1, Math.max(0, (e.clientY - f.r.top - f.oy) / f.dh)) };
}

function capDraw() {
  const f = capFit();
  const dpr = window.devicePixelRatio || 1;
  const rect = capBoxes.getBoundingClientRect();
  capBoxes.width = Math.round(rect.width * dpr);
  capBoxes.height = Math.round(rect.height * dpr);
  const c = capBoxes.getContext("2d");
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, rect.width, rect.height);
  if (!f) return;
  const px = (b) => [f.ox + b.x * f.dw, f.oy + b.y * f.dh, b.w * f.dw, b.h * f.dh];
  const accent = getComputedStyle(capDlg).getPropertyValue("--cap-mark").trim() || "#4c8dff";
  const sel = capUI.drag?.box || capUI.zone;
  if (sel) {  // fuera de la zona, atenuado
    const [x, y, w, h] = px(sel);
    c.fillStyle = "rgba(0, 0, 0, .5)";
    c.fillRect(f.ox, f.oy, f.dw, f.dh);
    c.clearRect(x, y, w, h);
    c.strokeStyle = accent;
    c.lineWidth = 2;
    c.strokeRect(x + 1, y + 1, w - 2, h - 2);
  }
  if (capUI.hover && !capUI.drag && capUI.hover !== capUI.zone) {
    const [x, y, w, h] = px(capUI.hover);
    c.fillStyle = "rgba(76, 141, 255, .14)";
    c.fillRect(x, y, w, h);
    c.strokeStyle = accent;
    c.lineWidth = 1.5;
    c.setLineDash([6, 4]);
    c.strokeRect(x + 0.75, y + 0.75, w - 1.5, h - 1.5);
    c.setLineDash([]);
  }
}

capBoxes.addEventListener("pointermove", (e) => {
  const p = capPoint(e);
  if (!p) return;
  if (capUI.drag) {
    const a = capUI.drag.from;
    capUI.drag.box = { x: Math.min(a.x, p.x), y: Math.min(a.y, p.y), w: Math.abs(p.x - a.x), h: Math.abs(p.y - a.y) };
  } else {
    const list = boxesAt(p.x, p.y);
    capUI.list = list;
    capUI.level = Math.min(capUI.level, Math.max(0, list.length - 1));
    capUI.hover = list[capUI.level] || null;
  }
  capDraw();
});
capBoxes.addEventListener("pointerleave", () => { capUI.hover = null; capUI.level = 0; capDraw(); });
// la rueda sube al recuadro que contiene al actual (o baja)
capBoxes.addEventListener("wheel", (e) => {
  if (!capUI.list?.length) return;
  e.preventDefault();
  capUI.level = Math.min(capUI.list.length - 1, Math.max(0, capUI.level + (e.deltaY < 0 ? 1 : -1)));
  capUI.hover = capUI.list[capUI.level];
  capDraw();
}, { passive: false });
capBoxes.addEventListener("pointerdown", (e) => {
  const p = capPoint(e);
  if (!p || e.button !== 0) return;
  capBoxes.setPointerCapture(e.pointerId);
  capUI.drag = { from: p, box: null };
});
capBoxes.addEventListener("pointerup", (e) => {
  const d = capUI.drag;
  capUI.drag = null;
  if (!d) return;
  const f = capFit();
  // arrastrar marca la zona; un clic (sin moverse) elige el recuadro resaltado
  const big = d.box && f && d.box.w * f.dw > 12 && d.box.h * f.dh > 12;
  capUI.zone = big ? d.box : capUI.hover || capUI.zone;
  if (capUI.zone && capUI.zone.w > 0.985 && capUI.zone.h > 0.985) capUI.zone = null;
  capUI.hover = null;
  capRender();
  capDraw();
});
$("#cap-all").addEventListener("click", () => { capUI.zone = null; capRender(); capDraw(); });
$("#cap-other").addEventListener("click", async () => {
  const s = await pickSource();
  if (s) capUseStream(s);
});
$("#cap-q").addEventListener("click", (e) => {
  const q = e.target.closest("[data-q]")?.dataset.q;
  if (!q) return;
  capOpts.q = q;
  capSaveOpts();
  capRender();
});
$("#cap-fps").addEventListener("click", (e) => {
  const fps = Number(e.target.closest("[data-fps]")?.dataset.fps);
  if (!fps) return;
  capOpts.fps = fps;
  capSaveOpts();
  capRender();
});
function capSaveOpts() {
  try { localStorage.setItem("capOpts", JSON.stringify(capOpts)); } catch { /* sin almacenamiento */ }
}
capPrev.addEventListener("loadedmetadata", capRender);
capPrev.addEventListener("resize", capRender);
$("#cap-q").replaceChildren(...Object.entries(CAP_Q).map(([k, v]) => el("button", { class: "seg", type: "button", "data-q": k, text: v.label })));

capDlg.addEventListener("close", () => {
  clearInterval(capUI.timer);
  const s = capUI.stream, crop = capCropPx();  // antes de soltar la vista previa (de ella sale el tamaño)
  capUI.stream = null;
  capPrev.srcObject = null;
  if (capDlg.returnValue === "ok" && s) startRecording(s, crop);
  else capStopStream(s);
});

/* ------------------------------------------------------------ grabar */
const capRec = { rec: null, id: null, t0: 0, tick: 0, seq: 0, kbps: 0, chain: null };

function capMime(audioOnly) {
  const list = audioOnly ? ["audio/webm;codecs=opus", "audio/webm"]
    : ["video/webm;codecs=h264,opus", "video/webm;codecs=vp8,opus", "video/webm"];
  return list.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}

async function startRecording(stream, crop) {
  const q = capOpts.q, fps = capOpts.fps, audioOnly = q === "audio";
  const src = { w: stream.getVideoTracks()[0]?.getSettings().width || 0, h: stream.getVideoTracks()[0]?.getSettings().height || 0 };
  const out = capOutSize(crop?.w || src.w, crop?.h || src.h, q);
  const kbps = capKbps(out, q, fps);
  // lo grabado lleva toda la imagen: margen para que la zona conserve su calidad al recortarla
  const share = crop && src.w ? Math.max(1, (src.w * src.h) / (crop.w * crop.h)) : 1;
  const recKbps = audioOnly ? 0 : Math.min(16000, Math.round(kbps * 1.5 * share));
  const tracks = audioOnly ? stream.getAudioTracks() : stream.getTracks();
  let rec;
  try {
    rec = new MediaRecorder(new MediaStream(tracks), { mimeType: capMime(audioOnly), videoBitsPerSecond: recKbps * 1000 || undefined, audioBitsPerSecond: 128000 });
  } catch {
    capStopStream(stream);
    return toast("Este navegador no puede grabar la pantalla.");
  }
  const id = "cap_" + [...crypto.getRandomValues(new Uint8Array(12))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const when = new Date();
  const title = `Grabación de pantalla ${when.toLocaleDateString("es", { day: "numeric", month: "short" })} ${when.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}`;
  const record = { id, title, lib: vaults.current || "", q, fps, crop: crop ? [crop.x, crop.y, crop.w, crop.h].join(",") : "",
    parts: 0, ended: false, started: Date.now() };
  try {
    await capPut(record);
  } catch {
    capStopStream(stream);
    return toast("No se puede guardar la grabación en este navegador (sin espacio o en modo privado).");
  }
  Object.assign(capRec, { rec, id, t0: performance.now(), seq: 0, kbps: kbps + capAudioKbps(q) });
  // el dueño de esta grabación es esta pestaña mientras viva (otra no la sube a la vez)
  capOwn(id, () => new Promise((done) => { capRec.release = done; }));
  // cada parte se guarda en orden (y antes de subirla)
  capRec.chain = Promise.resolve();
  rec.ondataavailable = (e) => {
    if (!e.data.size) return;
    capRec.chain = capRec.chain.then(async () => {
      const seq = capRec.seq++;
      try {
        await capPartPut(id, seq, e.data);
        record.parts = seq + 1;
        await capPut(record);
      } catch {
        toast("El navegador se quedó sin espacio para la grabación: se detuvo.");
        stopRecording();
        return;
      }
      capUpload(record);
    });
  };
  rec.onstop = async () => {
    capStopStream(stream);
    clearInterval(capRec.tick);
    liveStop();
    await capRec.chain;  // la última parte se guarda primero
    record.ended = true;
    await capPut(record).catch(() => {});
    capRec.rec = null;
    capUpload(record);
  };
  stream.getVideoTracks()[0]?.addEventListener("ended", stopRecording);  // «Dejar de compartir» del navegador
  stream.getAudioTracks()[0]?.addEventListener("ended", () => { if (audioOnly) stopRecording(); });
  rec.start(CAP_PART_MS);
  liveStart(id, title, record.lib, stream);
  capRec.tick = setInterval(capBar, 500);
  capBar();
}

function stopRecording() {
  if (capRec.rec?.state === "recording") capRec.rec.stop();
}

/* ------------------------------------------------------------ subir (reanudable) */
const capUp = new Map();  // id → {record, busy, next, delay, state}

// Un solo dueño por grabación entre pestañas; sin Web Locks, la pestaña que la empezó
function capOwn(id, fn) {
  if (!navigator.locks) return fn();
  return navigator.locks.request("translay-cap-" + id, { ifAvailable: true }, (lock) => (lock ? fn() : null));
}

async function capUpload(record) {
  const u = capUp.get(record.id) || { record, busy: false, next: 0, delay: 1000, state: "subiendo" };
  capUp.set(record.id, u);
  if (u.busy) { u.again = true; return; }
  u.busy = true;
  try {
    for (;;) {
      u.again = false;
      const fresh = (await capGetAll()).find((r) => r.id === record.id) || record;
      Object.assign(record, fresh);
      while (u.next < record.parts) {
        const part = await capPartGet(record.id, u.next);
        if (!part) { u.next++; continue; }  // ya confirmada antes de recargar
        const r = await fetch(`/api/capture/${record.id}/${u.next}?lib=${encodeURIComponent(record.lib)}`, { method: "PUT", body: part.blob });
        const next = Number(((await r.text()).match(/next=(\d+)/) || [])[1]);
        if (!r.ok && r.status !== 409) throw new Error(String(r.status));
        if (Number.isNaN(next)) throw new Error("sin respuesta");
        if (next > u.next) await capPartsDrop(record.id, next);
        else if (next < u.next) {  // el servidor perdió partes ya confirmadas: no hay forma de reponerlas
          throw Object.assign(new Error("perdida"), { fatal: true });
        }
        u.next = next;
        u.delay = 1000;
        u.state = "subiendo";
        capBar();
      }
      if (record.ended && !u.again) {
        await capFinish(record, u);
        return;
      }
      if (!u.again) return;
    }
  } catch (e) {
    if (e.fatal) {
      u.state = "error";
      toast("La copia de la grabación en el servidor se perdió; no se pudo terminar.");
      return;
    }
    // sin conexión: lo grabado sigue en este equipo y se reintenta con espera creciente
    u.state = "sin conexión";
    capBar();
    clearTimeout(u.retry);
    u.retry = setTimeout(() => capUpload(record), u.delay);
    u.delay = Math.min(15000, u.delay * 2);
  } finally {
    u.busy = false;
  }
}

async function capFinish(record, u) {
  u.state = "armando";
  capBar();
  const qs = new URLSearchParams({ parts: record.parts, q: record.q, fps: record.fps, crop: record.crop, title: record.title, lib: record.lib });
  const r = await fetch(`/api/capture/${record.id}/end?${qs}`, { method: "PUT" });
  const text = await r.text();
  if (r.status === 409) { u.next = Number((text.match(/next=(\d+)/) || [])[1]) || 0; throw new Error("faltan partes"); }
  if (!r.ok) {
    u.state = "error";
    capBar();
    toast(r.status === 400 ? "La grabación quedó vacía: no se guardó." : `${text}.`);
    if (r.status === 400) await capDrop(record.id).catch(() => {});
    return;
  }
  await capDrop(record.id).catch(() => {});
  capUp.delete(record.id);
  capRec.release?.();
  send({ type: "library" });
  if (prefs.import_mode !== "descargar") send({ type: "queue_add", video: record.id });
  capBar();
  toast(prefs.import_mode !== "descargar" ? "Grabación guardada: ya está en la cola." : "Grabación guardada en la biblioteca.", "ok",
    { label: "Ver", onClick: () => playItem(record.id) });
}

// Al abrir la app: lo que quedó a medias (pestaña cerrada, sin conexión, equipo apagado)
async function capResume() {
  let list = [];
  try { list = await capGetAll(); } catch { return; }
  for (const r of list) {
    if (r.id === capRec.id) continue;
    capOwn(r.id, async () => {
      if (!r.ended) { r.ended = true; await capPut(r).catch(() => {}); }
      await capUpload(r);
      // se queda con la grabación hasta terminarla (o hasta cerrar la pestaña)
      while (capUp.has(r.id) && capUp.get(r.id).state !== "error") await new Promise((res) => setTimeout(res, 2000));
    });
  }
}
// volvió la red: no se espera al próximo reintento
window.addEventListener("online", () => {
  for (const u of capUp.values()) if (u.state === "sin conexión") { clearTimeout(u.retry); capUpload(u.record); }
});

/* ------------------------------------------------------------ en vivo */
const live = { ws: null, id: null, title: "", lib: "", ctx: null, node: null, pending: [], covered: 0, samples: 0, open: false, closed: true, text: "" };

function liveStart(id, title, libId, stream) {
  Object.assign(live, { id, title, lib: libId, pending: [], covered: 0, samples: 0, open: false, closed: false, text: "" });
  liveConnect();
  if (!stream.getAudioTracks().length || !window.AudioContext) return;
  const ctx = new AudioContext();
  live.ctx = ctx;
  ctx.audioWorklet?.addModule("js/capture-worklet.js").then(() => {
    if (live.closed) return;
    const node = new AudioWorkletNode(ctx, "capture", { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      processorOptions: { target: SR, chunk: 1600 } });
    const mute = ctx.createGain();
    mute.gain.value = 0;  // ya se escucha en la fuente: aquí solo se analiza
    ctx.createMediaStreamSource(new MediaStream(stream.getAudioTracks())).connect(node);
    node.connect(mute).connect(ctx.destination);
    node.port.onmessage = (e) => livePcm(e.data);
    live.node = node;
  }).catch(() => {});
}

function livePcm(pcm) {
  const t = live.samples / SR;
  live.samples += pcm.length;
  const buf = new ArrayBuffer(8 + pcm.byteLength);
  new DataView(buf).setFloat64(0, t, true);
  new Int16Array(buf, 8).set(pcm);
  live.pending.push({ t, end: live.samples / SR, buf });
  // lo que no se confirma en 10 min queda para la cola (con el archivo final)
  while (live.pending.length && live.pending[0].end < live.samples / SR - CAP_LIVE_KEEP) live.pending.shift();
  if (live.open && live.ws.readyState === WebSocket.OPEN) live.ws.send(buf);
}

function liveConnect() {
  if (live.closed) return;
  const libPath = (location.pathname.match(/^\/b\/([a-z0-9-]+)/) || [])[1];
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws${libPath ? `?lib=${libPath}` : ""}`);
  ws.binaryType = "arraybuffer";
  live.ws = ws;
  live.open = false;
  ws.onmessage = (e) => {
    if (typeof e.data !== "string") return;
    const m = JSON.parse(e.data);
    if (m.type === "ready") {
      if (live.lib) ws.send(JSON.stringify({ type: "vault_open", id: live.lib }));
      else liveOpen();
    } else if (m.type === "glossary" && !live.open && (!live.lib || m.vault === live.lib)) {
      liveOpen();
    } else if (m.type === "covered") {
      live.covered = Math.max(0, ...m.ranges.map((r) => r[1]));
      live.pending = live.pending.filter((p) => p.end > live.covered);
    } else if (m.type === "segment") {
      live.text = m.segment.translation || m.segment.text || live.text;
      capBar();
    } else if (m.type === "partial" && (m.es || m.committed)) {
      live.text = m.es || `${m.committed} ${m.tentative}`.trim();
      capBar();
    }
  };
  ws.onclose = () => {
    live.open = false;
    capBar();
    if (!live.closed) setTimeout(liveConnect, 1000);
  };
}

// la sesión nueva abre la transcripción y recibe lo que no se confirmó (en orden)
function liveOpen() {
  live.ws.send(JSON.stringify({ type: "open", id: live.id, name: live.title }));
  for (const p of live.pending) live.ws.send(p.buf);
  live.open = true;
  capBar();
}

function liveStop() {
  live.closed = true;
  if (live.ws?.readyState === WebSocket.OPEN) live.ws.send(JSON.stringify({ type: "end" }));
  setTimeout(() => live.ws?.close(), 3000);  // tiempo para cerrar la última frase
  live.node?.disconnect();
  live.ctx?.close().catch(() => {});
  live.node = live.ctx = null;
}

/* ------------------------------------------------------------ barra de grabación */
function capBar() {
  const bar = $("#cap-bar");
  const recording = !!capRec.rec;
  const ups = [...capUp.values()].filter((u) => u.state !== "error");
  bar.hidden = !recording && !ups.length;
  if (bar.hidden) return;
  const offline = ups.some((x) => x.state === "sin conexión") || (recording && !live.open);
  bar.classList.toggle("rec", recording);
  $("#cap-stop").hidden = !recording;
  if (recording) {
    const secs = (performance.now() - capRec.t0) / 1000;
    $("#cap-time").textContent = fmtClock(secs);
    $("#cap-meta").textContent = offline ? "Sin conexión: se guarda en este equipo" : `hasta ${fmtMB((capRec.kbps * secs) / 8 / 1000)}`;
  } else {
    const done = ups.find((x) => x.state === "armando"), u = ups[0];
    $("#cap-time").textContent = done ? "Armando el video" : offline ? "Sin conexión" : "Guardando la grabación";
    $("#cap-meta").textContent = done ? "" : offline ? "Se sube al volver la conexión"
      : u.record.parts ? `${Math.min(99, Math.round((u.next / u.record.parts) * 100))} %` : "";
  }
  $("#cap-live").textContent = recording ? live.text : "";
}

$("#cap-btn").addEventListener("click", openCapture);
$("#cap-stop").addEventListener("click", stopRecording);
window.addEventListener("beforeunload", (e) => {
  // cerrar mientras graba corta la grabación (lo grabado se sube al volver a abrir la app)
  if (capRec.rec) e.preventDefault();
});
if (window.indexedDB) capResume();
