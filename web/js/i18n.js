// Idiomas de la interfaz (vt/i18n.py): el texto está escrito en español y t() lo busca en el catálogo del idioma
// de la app, que el servidor entrega antes que este archivo en /i18n.js (window.I18N). Lo que falta, en español.
//   t("Agregar")                          → "Add"
//   t("Quedan {n} videos", { n: 3 })      → "3 videos left"
//   translateDom(raíz)                    los textos y atributos fijos de index.html (y de plantillas fijas)
const I18N = window.I18N || { lang: "es", strings: {} };
document.documentElement.lang = I18N.lang;

function t(text, vars) {
  let out = I18N.strings[text] || text;
  if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return out;
}

// el nombre de un idioma en el de la app («inglés», "English", «inglês»)
const LANG_NAMES = {
  es: { en: "inglés", es: "español", pt: "portugués", it: "italiano", ja: "japonés", ko: "coreano" },
  en: { en: "English", es: "Spanish", pt: "Portuguese", it: "Italian", ja: "Japanese", ko: "Korean" },
  pt: { en: "inglês", es: "espanhol", pt: "português", it: "italiano", ja: "japonês", ko: "coreano" },
};
function langName(code) {
  return (LANG_NAMES[I18N.lang] || LANG_NAMES.es)[code] || (code ? code.toUpperCase() : t("el original"));
}

// idioma al que se traduce y dobla (Ajustes › Traducir a; por defecto, el de la app). applyPrefs lo actualiza.
let TARGET = I18N.lang;
const targetLang = () => TARGET;
// formato de fechas y números del idioma de la app
const LOCALES = { es: "es-419", en: "en-US", pt: "pt-BR" };
let LOCALE = LOCALES[I18N.lang] || I18N.lang;

/* ------------------------------------------------------------ cambiar de idioma sin recargar
   Lo que se tradujo al cargar (tablas de textos, nodos armados una vez) se registra con i18nTrack. Al cambiar de
   idioma: se baja el catálogo nuevo, cada texto ya traducido se reconoce por su original en español (el catálogo
   viejo al revés) y se pone en el idioma nuevo, en la página y en lo registrado; después la app redibuja sus vistas
   (los textos con variables salen de nuevo de t()). */
const I18N_TRACKED = [];
function i18nTrack(x) { I18N_TRACKED.push(x); return x; }
const I18N_ATTRS_ALL = ["placeholder", "title", "aria-label", "data-tip", "alt", "data-label", "data-short"];
const I18N_SKIP = "#transcript, #ag-msgs, .vtitle, .vdesc, input, textarea, [contenteditable]";  // contenido, no interfaz

async function switchLang(lang) {
  if (lang === I18N.lang) return false;
  const res = await fetch("i18n.js", { cache: "no-store" });
  const src = await res.text();
  const next = JSON.parse(src.slice(src.indexOf("{"), src.lastIndexOf("}") + 1));
  if (next.lang !== lang) return false;
  const oldLang = I18N.lang;
  const back = new Map(Object.entries(I18N.strings).map(([k, v]) => [v, k]));  // texto en el idioma de antes → original
  const keys = new Set(Object.keys(next.strings));
  const swap = (s) => {
    if (typeof s !== "string" || !s.trim()) return s;
    const lead = s.match(/^\s*/)[0], tail = s.match(/\s*$/)[0], core = s.trim();
    // (un texto sin traducción se mostraba en español: también es su original)
    const orig = oldLang === "es" ? core : back.get(core) ?? (keys.has(core) || core in I18N.strings ? core : null);
    if (orig == null || (oldLang === "es" && !keys.has(orig) && lang !== "es")) return s;
    return lead + (lang === "es" ? orig : next.strings[orig] || orig) + tail;
  };
  const walkDom = (root) => {
    if (!root) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement?.closest(I18N_SKIP) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
    for (let n = w.nextNode(); n; n = w.nextNode()) { const v = swap(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; }
    const all = root.nodeType === 1 ? [root, ...root.querySelectorAll("*")] : [...root.querySelectorAll("*")];
    for (const el of all) {
      if (el.closest(I18N_SKIP)) continue;
      for (const a of I18N_ATTRS_ALL) { const v = el.getAttribute(a); if (v) { const nv = swap(v); if (nv !== v) el.setAttribute(a, nv); } }
    }
  };
  const walkData = (x, seen = new Set()) => {
    if (!x || typeof x !== "object" || seen.has(x)) return;
    seen.add(x);
    if (x instanceof Node) { walkDom(x); return; }
    for (const k of Object.keys(x)) {
      if (typeof x[k] === "string") x[k] = swap(x[k]);
      else if (typeof x[k] === "object") walkData(x[k], seen);
    }
  };
  walkDom(document.body);
  for (const x of I18N_TRACKED) walkData(x);
  I18N.lang = next.lang;
  I18N.strings = next.strings;
  LOCALE = LOCALES[I18N.lang] || I18N.lang;
  document.documentElement.lang = I18N.lang;
  return true;
}

const I18N_ATTRS = ["placeholder", "title", "aria-label", "data-tip", "alt", "data-label"];
function translateDom(root = document.body) {
  if (I18N.lang === "es" || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const s = n.nodeValue.trim();
    if (s && I18N.strings[s]) n.nodeValue = n.nodeValue.replace(s, I18N.strings[s]);
  }
  root.querySelectorAll("*").forEach((el) => {
    for (const a of I18N_ATTRS) {
      const v = el.getAttribute(a);
      if (v && I18N.strings[v.trim()]) el.setAttribute(a, I18N.strings[v.trim()]);
    }
  });
}
