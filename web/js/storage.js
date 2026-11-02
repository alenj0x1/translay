"use strict";
// Almacenamiento (vt/storage.py): cuánto ocupa cada cosa de Translay y qué se puede liberar.
// Preferencias → Almacenamiento. Nada se borra sin confirmar. Usa lo global de app.js y ui.js.

const storage = { data: null, more: false, busy: "" };

const STORAGE_SUMMARY = el("div", { class: "pref st-pref", id: "pref-storage" }, el("div", { class: "pref-ctl" }));
const STORAGE_LIBS = el("div", { class: "pref st-pref" }, el("div", { class: "pref-ctl" }));
const STORAGE_LARGEST = el("div", { class: "pref st-pref" }, el("div", { class: "pref-ctl" }));
const STORAGE_MODELS = el("div", { class: "pref st-pref" }, el("div", { class: "pref-ctl" }));
const STORAGE_APP = el("div", { class: "pref st-pref" }, el("div", { class: "pref-ctl" }));

const stBytes = (b) => fmtBytes(b) || "0 B";
const stSum = (libs, k) => libs.reduce((n, l) => n + (l[k]?.bytes || 0), 0);
const stCount = (libs, k) => libs.reduce((n, l) => n + (l[k]?.count || 0), 0);
const stPlural = (n, one, many) => `${n.toLocaleString("es")} ${n === 1 ? one : many}`;
// «hoy», «ayer», «hace 5 días», «hace 2 meses»
function stAgo(t) {
  const days = Math.floor((Date.now() / 1000 - t) / 86400);
  if (days < 1) return "hoy";
  if (days < 2) return "ayer";
  if (days < 60) return `hace ${days} días`;
  return `hace ${Math.round(days / 30)} meses`;
}
function stDur(s) {
  const m = Math.round((s || 0) / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : m ? `${m} min` : "menos de 1 min";
}

function storageScan() {
  if (can("owner")) send({ type: "storage_scan" });
}

async function storageFree(msg, title, text, okLabel) {
  if (!(await confirmDlg(title, text, okLabel))) return;
  storage.busy = msg.what + (msg.repo || "") + (msg.videos || []).join();
  renderStorage();
  send({ type: "storage_free", ...msg });
}

// fila: ícono (con el color de su tipo en la barra) · nombre y detalle · tamaño y acción
const ST_COLOR = { download: "media", film: "media", check: "media", spark: "models", speaker: "voice", book: "text",
  trash: "trash", x: "trash" };
function stRow(ic, title, detail, bytes, action) {
  return el("div", { class: "trow st-row" },
    el("span", { class: `trow-ic c-${ST_COLOR[ic] || "other"}` }, icon(ic)),
    el("div", { class: "vinfo" }, el("strong", { text: title }),
      ...[detail].flat().filter(Boolean).map((t) => el("small", { text: t }))),
    el("div", { class: "vacts" }, bytes != null ? el("span", { class: "st-size", text: bytes === "…" ? "Midiendo…" : stBytes(bytes) }) : null, action));
}

function freeBtn(label, key, onClick, ic = "trash") {
  const busy = storage.busy === key;
  return btn(busy ? "Liberando…" : label, { icon: ic, size: "sm", variant: "ghost", disabled: !!storage.busy, onClick });
}

function renderStorage() {
  const d = storage.data;
  const ctl = (b) => b.querySelector(".pref-ctl");
  if (!d) {
    ctl(STORAGE_SUMMARY).replaceChildren(el("div", { class: "st-skel" }, el("i"), el("i"), el("i")));
    for (const b of [STORAGE_LIBS, STORAGE_LARGEST, STORAGE_MODELS, STORAGE_APP]) ctl(b).replaceChildren();
    return;
  }
  const libs = d.libraries;
  const many = libs.length > 1;
  const by = (k) => many ? libs.filter((l) => l[k]?.bytes).map((l) => `${l.name} ${stBytes(l[k].bytes)}`).join(" · ") : "";
  const models = d.models.reduce((n, m) => n + m.bytes, 0);
  const other = (d.extra.exports || 0) + (d.extra.labs || 0) + (d.extra.session || 0) + (d.install || 0);
  const parts = [
    ["Descargas", stSum(libs, "media"), "media"], ["Modelos", models, "models"], ["Voz en español", stSum(libs, "dubs"), "voice"],
    ["Textos y miniaturas", stSum(libs, "text"), "text"], ["Papelera y sueltos", stSum(libs, "trash") + stSum(libs, "loose"), "trash"],
    ["Otros", other, "other"],
  ].filter(([, b]) => b > 0);
  const total = parts.reduce((n, [, b]) => n + b, 0) || 1;

  // resumen: barra por tipo y el espacio libre de cada disco
  ctl(STORAGE_SUMMARY).replaceChildren(
    el("div", { class: "st-total" }, el("strong", { text: stBytes(total) }),
      el("span", { text: d.disks.map((x) => `${stBytes(x.free)} libres en ${x.path.replace(/\\$/, "")}`).join(" · ") })),
    el("div", { class: "st-bar" }, ...parts.map(([t, b, c]) => el("i", { class: `c-${c}`, style: `flex-grow:${b}`, title: `${t} ${stBytes(b)}` }))),
    el("div", { class: "st-legend" }, ...parts.map(([t, b, c]) => el("span", {}, el("i", { class: `c-${c}` }), `${t} `, el("b", { text: stBytes(b) })))));

  // bibliotecas (sumadas; con varias, el detalle por biblioteca)
  const free = stSum(libs, "free"), nFree = stCount(libs, "free");
  const loose = stSum(libs, "loose"), trashB = stSum(libs, "trash");
  ctl(STORAGE_LIBS).replaceChildren(el("div", { class: "vrows" },
    stRow("download", "Descargas", [stPlural(stCount(libs, "media"), "video o audio", "videos y audios"), by("media")].filter(Boolean).join(" · "),
      stSum(libs, "media"), null),
    nFree ? stRow("film", "Sin traducir", stPlural(nFree, "descarga que nunca se tradujo", "descargas que nunca se tradujeron"),
      free, freeBtn("Liberar", "untranslated", () => storageFree({ what: "untranslated" },
        `¿Liberar ${stPlural(nFree, "descarga", "descargas")} sin traducir?`,
        `Se borra la copia en el equipo (${stBytes(free)}). Los videos siguen en la biblioteca y se vuelven a bajar al abrirlos o exportarlos.`,
        "Liberar"))) : null,
    stSum(libs, "dubs") ? stRow("speaker", "Voz en español", by("dubs") || "Las frases dobladas de cada video", stSum(libs, "dubs"), null) : null,
    stSum(libs, "text") ? stRow("book", "Textos y miniaturas", by("text") || "Transcripciones, voces, personas y miniaturas", stSum(libs, "text"), null) : null,
    trashB ? stRow("trash", "Papelera", "Se vacía sola a los 30 días", trashB,
      freeBtn("Vaciar", "trash", () => storageFree({ what: "trash" }, "¿Vaciar la papelera?",
        "Todo lo que hay en ella se borra para siempre.", "Vaciar la papelera"))) : null,
    loose ? stRow("x", "Archivos sueltos", stCount(libs, "loose") === 1 ? "1 archivo que ya no es de ningún video o quedó a medias"
      : `${stPlural(stCount(libs, "loose"), "archivo", "archivos")} que ya no son de ningún video o quedaron a medias`, loose,
      freeBtn("Borrar", "loose", () => storageFree({ what: "loose" }, "¿Borrar los archivos sueltos?",
        `No son de ningún video de tus bibliotecas (${stBytes(loose)}).`, "Borrar"))) : null));

  // lo que más ocupa: de a uno
  const items = d.largest;
  const shown = storage.more ? items : items.slice(0, 8);
  ctl(STORAGE_LARGEST).replaceChildren(items.length ? el("div", { class: "vrows" }, ...shown.map((x) =>
    stRow(x.translated ? "check" : "film", x.title, [stDur(x.duration), x.translated ? "Traducido" : "Sin traducir",
      many ? libs.find((l) => l.id === x.vault)?.name : ""].filter(Boolean).join(" · "), x.bytes,
      freeBtn("Liberar", "videos" + x.video, () => storageFree({ what: "videos", vault: x.vault, videos: [x.video] },
        `¿Liberar «${x.title}»?`, `Se borra la copia en el equipo (${stBytes(x.bytes)}). Sigue en la biblioteca y se vuelve a bajar al abrirlo${x.translated ? ". La traducción y la voz se conservan" : ""}.`,
        "Liberar"))))) : emptyState("download", "No hay descargas", "Lo que bajes de YouTube o de un enlace aparece aquí, de lo que más ocupa a lo que menos."),
  ...(items.length > 8 ? [el("div", { class: "acts" }, btn(storage.more ? "Ver menos" : `Ver ${items.length - 8} más`, { icon: "chevron", size: "sm", variant: "ghost",
    onClick: () => { storage.more = !storage.more; renderStorage(); } }))] : []));

  // modelos: para qué sirve, qué perfiles lo usan y cuándo se usó por última vez
  const since = new Date((d.usage_since || Date.now() / 1000) * 1000).toLocaleDateString("es", { day: "numeric", month: "short" });
  const lastUse = (m) => m.in_use ? "En uso ahora" : m.used ? `Usado por última vez ${stAgo(m.used)}` : `Sin usar desde el ${since}`;
  const profilesOf = (m) => m.profiles.length ? `Perfiles ${m.profiles.join(", ")}` : "Ningún perfil lo usa";
  ctl(STORAGE_MODELS).replaceChildren(d.models.length ? el("div", { class: "vrows" }, ...d.models.map((m) =>
    stRow("spark", m.label, [m.purpose, `${lastUse(m)} · ${profilesOf(m)}`], m.bytes, m.in_use ? el("span", { class: "chip ok", text: "En uso" })
      : freeBtn("Borrar", "model" + m.repo, () => storageFree({ what: "model", repo: m.repo }, `¿Borrar ${m.label}?`,
        `${m.purpose}. ${lastUse(m)}. ${m.profiles.length ? `Lo usan los perfiles ${m.profiles.join(", ")}: si cambias a uno, se vuelve a descargar (${stBytes(m.bytes)}).`
          : "Ningún perfil lo usa."} Libera ${stBytes(m.bytes)}.`, "Borrar el modelo"))))) :
    emptyState("spark", "Sin modelos descargados", "Se descargan la primera vez que se usan."),
  ...(() => {  // de una vez: todo lo que el perfil que usas no necesita
    const off = d.models.filter((m) => !m.in_use);
    const bytes = off.reduce((n, m) => n + m.bytes, 0);
    return off.length > 1 ? [el("div", { class: "acts" }, freeBtn(`Borrar los que tu perfil no usa · ${stBytes(bytes)}`, "unused_models",
      () => storageFree({ what: "unused_models" }, `¿Borrar ${off.length} modelos que tu perfil no usa?`,
        `${off.map((m) => m.label).join(", ")}. Libera ${stBytes(bytes)}. Si cambias a un perfil que use alguno, se vuelve a descargar.`,
        "Borrar los modelos")))] : [];
  })());

  // de la app
  const x = d.extra;
  const app = [
    x.exports ? stRow("zip", "Exportaciones para descargar", "Se borran solas a las 24 h", x.exports,
      freeBtn("Borrar", "exports", () => storageFree({ what: "exports" }, "¿Borrar las exportaciones?",
        "Lo que ya descargaste queda en tu carpeta de descargas.", "Borrar"))) : null,
    d.has_install ? stRow("update", "Caché de instalación", "Paquetes que solo aceleran la próxima actualización", d.install ?? "…",
      d.install ? freeBtn("Borrar", "install", () => storageFree({ what: "install" }, "¿Borrar la caché de instalación?",
        `Libera ${stBytes(d.install)}. La próxima actualización descarga los paquetes de nuevo.`, "Borrar")) : null) : null,
    x.labs ? stRow("flask", "Mediciones de rendimiento", "Pruebas de desarrollo (data/labs)", x.labs,
      freeBtn("Borrar", "labs", () => storageFree({ what: "labs" }, "¿Borrar las mediciones?",
        `Libera ${stBytes(x.labs)}. Translay no las usa: son de las pruebas de desarrollo.`, "Borrar"))) : null,
    x.session ? stRow("user", "Sesión de YouTube", "El navegador aparte con el que entras a YouTube", x.session, null) : null,
  ].filter(Boolean);
  ctl(STORAGE_APP).replaceChildren(el("div", { class: "vrows" }, ...app));
  STORAGE_APP.closest(".set-group")?.toggleAttribute("hidden", !app.length);
}

// mensajes del servidor (web/js/app.js · onMessage)
function storageUpdate(m) {
  storage.data = m;
  storage.busy = "";
  if (lib.prefSec === "almacenamiento") renderStorage();
}
function storageError() {  // «vault_error» mientras se liberaba: el botón vuelve
  if (storage.busy) { storage.busy = ""; renderStorage(); }
}
function storageFreed(m) {
  storage.busy = "";
  toast(m.bytes ? `Se liberaron ${stBytes(m.bytes)}.` : "No había nada que liberar.", "ok");
}
