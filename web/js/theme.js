"use strict";
// Apariencia en tres partes independientes (Preferencias → Apariencia):
//   modo   sistema | claro | oscuro   → la base: light / dark
//   tema   clasico | claude | pastel | pink | cyberpunk | matrix | code | contraste
//   tono   solo en los temas con TONES (si no, se ignora)
// El bloque de colores es «tema-tono-modo» en web/css/tokens.css (Clásico: "light"/"dark").
// Cambiar el modo conserva tema y tono; cambiar el tema conserva el modo.

const TONES = { pastel: ["lavanda", "menta", "durazno", "cielo"], cyberpunk: ["neon", "electrico"], matrix: ["verde", "ambar"] };
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function themeBase(mode) {
  return mode === "claro" ? "light" : mode === "oscuro" ? "dark" : systemDark.matches ? "dark" : "light";
}

function themeTone(style, tone) {
  const tones = TONES[style];
  return tones ? (tones.includes(tone) ? tone : tones[0]) : "";
}

function themeBlock(mode, style, tone) {
  const base = themeBase(mode);
  if (!style || style === "clasico") return base;
  return [style, themeTone(style, tone), base].filter(Boolean).join("-");
}

function applyTheme(p = prefs) {
  const block = themeBlock(p.theme_mode, p.theme_style, p.theme_tone);
  document.documentElement.dataset.theme = block;
  try { localStorage.setItem("vt-theme-block", block); } catch (e) { /* sin almacenamiento */ }
}

systemDark.addEventListener("change", () => {
  if (typeof prefs !== "undefined" && (prefs.theme_mode || "sistema") === "sistema") applyTheme();
});
