"use strict";
// Apariencia: modo sistema | claro | oscuro → el bloque de colores "light" o "dark"
// de web/css/tokens.css.

const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function themeBase(mode) {
  return mode === "claro" ? "light" : mode === "oscuro" ? "dark" : systemDark.matches ? "dark" : "light";
}

function applyTheme(p = prefs) {
  const block = themeBase(p.theme_mode);
  const root = document.documentElement;
  if (root.dataset.theme && root.dataset.theme !== block) {
    // sin transiciones durante el cambio: cada botón animaba su gris de un tema al otro (parpadeo)
    root.classList.add("theme-switch");
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switch")));
  }
  root.dataset.theme = block;
  try { localStorage.setItem("vt-theme-block", block); } catch (e) { /* sin almacenamiento */ }
}

systemDark.addEventListener("change", () => {
  if (typeof prefs !== "undefined" && (prefs.theme_mode || "sistema") === "sistema") applyTheme();
});
