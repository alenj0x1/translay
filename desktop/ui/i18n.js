"use strict";
// Languages of the setup, first-run wizard and startup screens: the same catalogues as Translay's page
// (web/i18n/<lang>.json, copied to shared/i18n by scripts/prepare.mjs), keyed by the Spanish text. The language is the
// one Translay last used (window.__TRANSLAY_LOOK__, saved by the app) or, the first time, Windows' own; Spanish when
// it is none of them. The wizard's Idioma step switches it at once (setLang).
//   t("Instalar")                  → "Install"
//   t("Descargando {x}", { x })    → variables in braces
//   i18nTrack(tabla)               a table built with t() when its file loads (web/js/star.js, vaultlook.js): its texts
//                                  follow the language too
const LANGS = ["es", "en", "pt"];
const I18N = { lang: "es", strings: {} };
// how each language names itself (to pick it without understanding the current one)
const LANG_NATIVE = { es: "Español", en: "English", pt: "Português" };

function t(text, vars) {
  let s = I18N.strings[text] || text;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return s;
}

// Windows' display language, if Translay speaks it
function systemLang() {
  const sys = (navigator.languages || [navigator.language || "es"]).map((l) => l.slice(0, 2).toLowerCase());
  return sys.find((l) => LANGS.includes(l)) || "es";
}

function uiLang() {
  const saved = (window.__TRANSLAY_LOOK__ || {}).lang;
  return LANGS.includes(saved) ? saved : systemLang();
}

// tables translated with t() while their file loaded (before any catalogue): their Spanish originals are kept, so
// each language change writes them again
const I18N_TRACKED = [];
function i18nTrack(x) {
  I18N_TRACKED.push([x, JSON.parse(JSON.stringify(x))]);
  return x;
}
function retranslate(x, orig) {
  for (const k of Object.keys(orig)) {
    if (typeof orig[k] === "string") x[k] = t(orig[k]);
    else if (orig[k] && typeof orig[k] === "object" && x[k] && typeof x[k] === "object") retranslate(x[k], orig[k]);
  }
}

// loads the catalogue of `lang` and translates the page's fixed text ([data-i18n]) and the tracked tables
async function setLang(lang) {
  const next = LANGS.includes(lang) ? lang : "es";
  let strings = {};
  if (next !== "es") {
    try { strings = await (await fetch(`shared/i18n/${next}.json`)).json(); } catch (e) { /* in Spanish */ }
  }
  I18N.lang = next;
  I18N.strings = strings;
  document.documentElement.lang = next;
  for (const n of document.querySelectorAll("[data-i18n]")) {
    if (!n.dataset.i18n) n.dataset.i18n = n.textContent.trim();
    n.textContent = t(n.dataset.i18n);
  }
  for (const [x, orig] of I18N_TRACKED) retranslate(x, orig);
}

async function loadI18n() {
  await setLang(uiLang());
}
