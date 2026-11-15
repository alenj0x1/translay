"use strict";
// Cómo se ve cada biblioteca, sin depender del resto de la app: también la usa el asistente de primer uso de la app
// de escritorio (desktop/ui/wizard.js, copiada por desktop/scripts/prepare.mjs).
//   VAULT_COLORS, VAULT_ICONS     los colores y los avatares que se pueden elegir
//   newPattern()                  otra semilla para su patrón («Otro patrón»)
//   vaultBadge(v, clase)          su avatar: el ícono en blanco sobre su color (sólido, elegido 2026-11-14)
//   vaultAscii(v, cols, filas)    su campo de caracteres, en su color (banners y tarjetas)
// Usa el(), icon() (web/js/ui.js), t() e i18nTrack() (web/js/i18n.js).

const VAULT_COLORS = ["#e4572e", "#f3a712", "#29bf12", "#00a5cf", "#7d5ba6", "#e84f9b", "#2b2d42", "#8d6e63"];
const newPattern = () => Math.random().toString(36).slice(2, 8);
const VAULT_ICONS = [["library", t("Biblioteca")], ["flask", t("Ciencia")], ["smile", t("Humor")], ["music", t("Música")],
  ["book", t("Aprender")], ["globe", t("Mundo")], ["star", t("Favoritos")], ["film", t("Cine")], ["heart", t("Me gusta")], ["atom", t("Tecnología")],
  ["cap", t("Educación")], ["gamepad", t("Videojuegos")], ["ball", t("Deportes")], ["plane", t("Viajes")], ["chat", t("Charlas")],
  ["brush", t("Arte y estilo")], ["news", t("Noticias")], ["paw", t("Animales")]];
i18nTrack(VAULT_ICONS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

// insignia: el ícono de la biblioteca sobre su color, sólido (el patrón va solo en los banners; elegido 2026-11-14)
function vaultBadge(v, cls = "") {
  const b = el("span", { class: ("vbadge " + cls).trim(), "aria-hidden": "true" }, icon(v.icon || "library"));
  b.style.setProperty("--vc", v.color || "var(--primary)");
  return b;
}

// campo de caracteres por densidad (el estilo de las escenas, web/js/scenes.js), quieto: cada biblioteca el suyo
const ASCII_RAMP = " .·:-=+*#%@";
function asciiField(seed, cols, rows) {
  let h = 2166136261;
  for (const ch of String(seed)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  const s = ((h >>> 0) % 1000) / 97;
  const out = [];
  for (let y = 0; y < rows; y++) {
    let line = "";
    for (let x = 0; x < cols; x++) {
      const v = (Math.sin(x * 0.16 + s * 1.7 + Math.sin(y * 0.45 + s) * 1.4) + Math.sin(y * 0.38 - x * 0.06 + s) + 1.4) / 3.6;
      line += ASCII_RAMP[Math.max(0, Math.min(10, Math.floor(v * v * 11)))];
    }
    out.push(line);
  }
  return out.join("\n");
}
function vaultAscii(v, cols, rows, cls) {
  const pre = el("pre", { class: "vascii " + cls, "aria-hidden": "true", text: asciiField(`${v.id}:${v.pattern || ""}`, cols, rows) });
  pre.style.setProperty("--vc", v.color || "var(--primary)");
  return pre;
}
