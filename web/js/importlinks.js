"use strict";
// Agregar varios enlaces a la vez y una lista .csv con miles de enlaces.
// Comparte el ámbito global con app.js (se carga justo después).

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
