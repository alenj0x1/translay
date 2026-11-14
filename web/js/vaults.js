"use strict";
// Bibliotecas (vt/vaults.py): varias bibliotecas, cada una en su carpeta, con sus videos,
// colecciones, glosario, personas guardadas, tema y modo de importar.
//   · selector en el encabezado (cambiar, crear)
//   · Ajustes → Bibliotecas (editar, ubicación, quitar o eliminar)
//   · «Mover a…» en la selección de videos
// Usa lo global de app.js y library.js (state, send, lib, toast, confirmDlg…).

const vaults = { list: [], current: null, dlg: { mode: "new", id: null, folder: "", color: "", icon: "library" } };
const VAULT_COLORS = ["#e4572e", "#f3a712", "#29bf12", "#00a5cf", "#7d5ba6", "#e84f9b", "#2b2d42", "#8d6e63"];
const VAULT_NAMES = [t("Documentales"), t("Para aprender"), t("Risas"), t("Música en vivo"), t("Charlas"), t("Tecnología"), t("Viajes"),
  t("Cocina"), t("Historia"), t("Podcasts"), t("Pendientes"), t("Favoritos"), t("Clásicos"), t("Entrevistas"), t("Ciencia"), t("Deportes"),
  t("Videojuegos"), t("Tutoriales"), t("Noticias"), t("Para la noche")];
i18nTrack(VAULT_NAMES);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const newPattern = () => Math.random().toString(36).slice(2, 8);
const VAULT_ICONS = [["library", t("Biblioteca")], ["flask", t("Ciencia")], ["smile", t("Humor")], ["music", t("Música")],
  ["book", t("Aprender")], ["globe", t("Mundo")], ["star", t("Favoritos")], ["film", t("Cine")], ["heart", t("Me gusta")], ["atom", t("Tecnología")],
  ["cap", t("Educación")], ["gamepad", t("Videojuegos")], ["ball", t("Deportes")], ["plane", t("Viajes")], ["chat", t("Charlas")],
  ["brush", t("Arte y estilo")], ["news", t("Noticias")], ["paw", t("Animales")]];
i18nTrack(VAULT_ICONS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

const currentVault = () => vaults.list.find((v) => v.id === vaults.current) || vaults.list[0] || { name: t("Principal"), id: "principal" };
const vaultById = (id) => vaults.list.find((v) => v.id === id);
// «3 videos · 2 en el equipo»
function vaultCounts(v) {
  const n = v.count ?? 0;
  return (n === 1 ? t("1 video") : t("{n} videos", { n })) + (v.downloaded != null ? ` · ${t("{n} en el equipo", { n: v.downloaded })}` : "");
}
// insignia: el ícono de la biblioteca sobre su color, sólido (el patrón va solo en los banners; elegido 2026-11-14)
function vaultBadge(v, cls = "") {
  const b = el("span", { class: ("vbadge " + cls).trim(), "aria-hidden": "true" }, icon(v.icon || "library"));
  b.style.setProperty("--vc", v.color || "var(--primary)");
  return b;
}

// distintivo de cada biblioteca en las listas desplegables (web/js/menu.js)
DD_DECO.vault = (o) => (o.value === "all" ? icon("library") : vaultById(o.value) ? vaultBadge(vaultById(o.value)) : null);

function vaultsUpdate(m) {
  const changed = vaults.current && vaults.current !== m.current;
  // se eliminó la biblioteca abierta: su video (archivos ya en la papelera) se cierra
  if (changed && state.videoId && !m.items.some((v) => v.id === vaults.current) && typeof closeVideo === "function") closeVideo();
  vaults.list = m.items;
  vaults.current = m.current;
  if (changed) {  // otra biblioteca: la vista empieza desde arriba
    lib.sel = "home";
    lib.picked.clear();
    lib.meta = {};
    lib.qlib = null;  // la Cola vuelve a mostrar la biblioteca abierta
    if (typeof closeSearch === "function") closeSearch();
  }
  renderVaultBtn();
  renderVaultPop();
  if (typeof syncAccent === "function") syncAccent();  // Ajustes → Apariencia
  if (typeof applyCan === "function") applyCan();  // los permisos son por biblioteca
  if (typeof renderQueuePanel === "function") {  // la cola muestra lo de la biblioteca abierta
    for (const n of ["#qnav", "#qhead", "#qlist"]) $(n).dataset.sig = "";
    renderQueuePanel();
  }
  if (typeof renderPrefs === "function" && prefsSections.length) renderPrefs();
  if ($("#vault-screen").open) renderVaultScreen();
}

/* ------------------------------------------------------------ selector del encabezado */
function renderSideVault() {
  const v = currentVault();
  const box = $("#side-vault");
  if (!box) return;
  box.replaceChildren(
    vaultBadge(v, "lg"),
    el("div", { class: "sv-info" }, el("strong", { text: v.name }),
      el("small", { text: vaultCounts(v) })),
    el("button", { type: "button", class: "ic sm owner-only", title: t("Editar la biblioteca"), "aria-label": t("Editar la biblioteca"),
      on: { click: () => editVault(v.id) } }, icon("pencil")));
}
// editar una biblioteca: el diálogo se abre ahí mismo (sin cambiar de biblioteca ni de pantalla)
function editVault(id) {
  if (vaultById(id)) openVaultDlg("edit", id);
}

// otro patrón para el banner de una biblioteca: se ve al instante y se guarda en el servidor
function reshuffleVault(id) {
  if (vaultById(id)) send({ type: "vault_update", id, pattern: newPattern() });
}
// nombre, color, ícono o patrón: se ven en todos lados al instante (encabezado, menú, tarjetas, acento)
OPTIMISTIC.vault_update = (m) => {
  const v = vaultById(m.id);
  if (!v) return;
  for (const k of ["name", "color", "icon", "pattern"]) if (m[k] != null && (k === "pattern" || m[k])) v[k] = m[k];
  refreshVaultViews();
};
function refreshVaultViews() {
  renderVaultBtn();
  renderVaultPop();
  if (typeof syncAccent === "function") syncAccent();
  renderVaultViews();
}

function renderVaultBtn() {
  renderSideVault();
  const v = currentVault();
  const b = $("#vault-btn");
  b.replaceChildren(vaultBadge(v), el("span", { class: "btn-text", text: v.name }), icon("chevron", "chev"));
  b.title = t("Biblioteca: {name}", { name: v.name });
}
function renderVaultPop() {
  const ul = $("#vault-list");
  ul.replaceChildren(...vaults.list.map((v) => el("li", { class: v.id === vaults.current ? "on" : "" },
    vaultAscii(v, 34, 5, "corner"),
    el("button", { type: "button", class: "vitem" + (v.id === vaults.current ? " on" : ""),
      on: { click: () => { closeVaultPop(); openVault(v.id); } } },
      vaultBadge(v),
      el("span", { class: "vname", text: v.name }),
      el("span", { class: "vcount", text: String(v.count) })),
    el("button", { type: "button", class: "ic sm vedit owner-only", title: t("Editar «{name}»", { name: v.name }), "aria-label": t("Editar «{name}»", { name: v.name }),
      on: { click: (e) => { e.stopPropagation(); closeVaultPop(); editVault(v.id); } } }, icon("pencil")))));
}
function openVault(id) {
  // otra biblioteca: se entra por su inicio
  if (id !== vaults.current) send({ type: "vault_open", id });
  lib.sel = "home";
  if (currentView() !== "library") setView("library");
  else renderLibrary();
}
const openVaultPop = () => { renderVaultPop(); $("#vault-pop").hidden = false; };
const closeVaultPop = () => { $("#vault-pop").hidden = true; };
$("#vault-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("#vault-pop").hidden ? openVaultPop() : closeVaultPop();
});
document.addEventListener("click", (e) => { if (!e.target.closest(".vault-wrap")) closeVaultPop(); });
$("#vault-new").addEventListener("click", () => { closeVaultPop(); openVaultDlg("new"); });
$("#vault-manage").addEventListener("click", openVaultScreen);

/* ------------------------------------------------------------ crear / editar */
function openVaultDlg(mode, id = null) {
  const v = id ? vaultById(id) : null;
  vaults.dlg = { mode, id, folder: "", color: v?.color || VAULT_COLORS[vaults.list.length % VAULT_COLORS.length],
    icon: v?.icon || "library", pattern: v ? v.pattern || "" : newPattern() };
  $("#vault-dlg-title").textContent = mode === "new" ? t("Nueva biblioteca") : t("Editar «{name}»", { name: v.name });
  $("#vault-name").value = v ? v.name : "";
  $("#vault-go").textContent = mode === "new" ? t("Crear") : t("Guardar");
  $("#vault-where").hidden = mode !== "new";
  $("#vault-path").hidden = mode === "new";
  $("#vault-path").textContent = v ? v.path : "";
  $("#vault-folder").value = "";
  setWhere("app");
  renderVaultLook();
  const dlg = $("#vault-dlg");
  dlg.returnValue = "";
  dlg.showModal();
  $("#vault-name").focus();
}
function renderVaultLook() {
  const d = vaults.dlg;
  // vista previa: el banner con el color elegido, su ícono y su nombre
  const pv = { id: d.id || "new", color: d.color, icon: d.icon, pattern: d.pattern };
  $("#vault-preview").replaceChildren(vaultAscii(pv, 90, 14, "fill"), vaultBadge(pv, "xl"),
    el("strong", { text: $("#vault-name").value.trim() || $("#vault-name").placeholder.split(",")[0] }));
  $("#vault-colors").replaceChildren(...VAULT_COLORS.map((c) => {
    const b = el("button", { type: "button", class: "vcolor" + (d.color === c ? " on" : ""), "aria-label": t("Color {color}", { color: c }),
      on: { click: () => { d.color = c; renderVaultLook(); } } });
    b.style.setProperty("--vc", c);
    return b;
  }));
  $("#vault-icons").replaceChildren(...VAULT_ICONS.map(([ic, lbl]) => {
    const b = el("button", { type: "button", class: "btn vicon" + (d.icon === ic ? " on" : ""), title: lbl, "aria-label": lbl,
      on: { click: () => { d.icon = ic; renderVaultLook(); } } }, icon(ic));
    return b;
  }));
}
function setWhere(where) {
  for (const b of $("#vault-where-segs").querySelectorAll(".seg")) b.classList.toggle("on", b.dataset.where === where);
  $("#vault-folder-row").hidden = where !== "folder";
  vaults.dlg.where = where;
}
$("#vault-where-segs").addEventListener("click", (e) => {
  const b = e.target.closest(".seg");
  if (!b) return;
  setWhere(b.dataset.where);
  if (b.dataset.where === "folder" && !$("#vault-folder").value) send({ type: "vault_pick_folder", for: "new" });
});
$("#vault-pick").addEventListener("click", () => send({ type: "vault_pick_folder", for: "new" }));
$("#vault-name").addEventListener("input", () => {
  $("#vault-preview strong").textContent = $("#vault-name").value.trim() || $("#vault-name").placeholder.split(",")[0];
});
$("#vault-reshuffle").addEventListener("click", () => { vaults.dlg.pattern = newPattern(); renderVaultLook(); });
// todo al azar: nombre (si es nueva), color, ícono y banner
$("#vault-random").addEventListener("click", () => {
  const d = vaults.dlg;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  if (d.mode === "new") {
    const used = new Set(vaults.list.map((v) => v.name));
    $("#vault-name").value = pick(VAULT_NAMES.filter((n) => !used.has(n)).length ? VAULT_NAMES.filter((n) => !used.has(n)) : VAULT_NAMES);
  }
  d.color = pick(VAULT_COLORS.filter((c) => c !== d.color));
  d.icon = pick(VAULT_ICONS.map(([ic]) => ic).filter((ic) => ic !== d.icon));
  d.pattern = newPattern();
  renderVaultLook();
});
$("#vault-form").addEventListener("submit", (e) => {
  const dlg = $("#vault-dlg");
  if (e.submitter?.value !== "ok") return;
  const d = vaults.dlg;
  const name = $("#vault-name").value.trim();
  if (!name) { e.preventDefault(); $("#vault-name").focus(); return; }
  const folder = d.where === "folder" ? $("#vault-folder").value.trim() : "";
  if (d.where === "folder" && !folder) { e.preventDefault(); send({ type: "vault_pick_folder", for: "new" }); return; }
  if (d.mode === "new") {
    send({ type: "vault_create", name, folder, color: d.color, icon: d.icon, pattern: d.pattern });
    if (currentView() !== "prefs") setView("library");
  } else {
    send({ type: "vault_update", id: d.id, name, color: d.color, icon: d.icon, pattern: d.pattern });
  }
  dlg.close("ok");
});

// carpeta elegida en el cuadro de Windows (lo abre el servidor, que corre en este equipo)
function vaultFolder(m) {
  if (!m.path) return;
  if (m.for === "open") return send({ type: "vault_open_folder", folder: m.path });
  $("#vault-folder").value = m.path;
}

/* ------------------------------------------------------------ Ajustes → Bibliotecas */
const VAULTS_BLOCK = el("div", { class: "pref vaults-pref", id: "pref-vaults" },
  el("span", { class: "pref-label", text: t("Tus bibliotecas") }), el("div", { class: "pref-ctl" }));
i18nTrack(VAULTS_BLOCK);  // al cambiar de idioma, sus textos también cambian (i18n.js)
function renderVaultsPref() {
  const ctl = VAULTS_BLOCK.querySelector(".pref-ctl");
  ctl.replaceChildren(el("div", { class: "vcards" }, ...vaults.list.map((v) => vaultCard(v, "pref")), newVaultCard()),
    el("div", { class: "acts" }, btn(t("Abrir carpeta"), { icon: "folder", size: "sm", title: t("Abre una biblioteca existente (de un disco externo u otro equipo)"),
      onClick: () => send({ type: "vault_pick_folder", for: "open" }) })));
}

// cuántos videos tiene: la abierta, lo que hay ahora (la lista de bibliotecas se actualiza menos seguido)
const vaultCount = (v) => (v.id === vaults.current && typeof lib !== "undefined" && lib.loaded ? Object.keys(lib.videos).length : (v.count || 0));
// menú de una biblioteca (botón «Más» y clic derecho)
function vaultMenu(v, at) {
  const isCur = v.id === vaults.current;
  const owner = !document.body.classList.contains("guest");
  const count = vaultCount(v);
  openMenu([
      { head: v.name },
      !isCur && { label: t("Abrir"), icon: "arrow", onClick: () => { closeVaultScreen(); openVault(v.id); } },
      owner && { label: t("Editar…"), icon: "pencil", onClick: () => { closeVaultScreen(); editVault(v.id); } },
      "sep",
      owner && !v.main && { label: t("Quitar de la lista"), icon: "x", onClick: async () => {
        if (await confirmDlg(t("¿Quitar «{name}» de la lista?", { name: v.name }),
          t("Sus videos y archivos se conservan en su carpeta. Puedes volver a abrirla con «Abrir carpeta»."), t("Quitar"))) {
          send({ type: "vault_remove", id: v.id, delete_files: false });
        }
      } },
      owner && count > 0 && { label: t("Vaciar…"), icon: "trash", danger: true, onClick: async () => {
        if (await confirmDlg(t("¿Vaciar «{name}»?", { name: v.name }),
          count === 1 ? t("Su video, con traducciones, voces, descargas y colecciones, se moverá a la papelera. Puedes restaurarlo durante 30 días.")
            : t("Sus {n} videos, con traducciones, voces, descargas y colecciones, se moverán a la papelera. Puedes restaurarlos durante 30 días.", { n: count }),
          t("Vaciar"), v.name)) {
          send({ type: "lib_clear", vault: v.id });
        }
      } },
      owner && !v.main && { label: t("Eliminar"), icon: "trash", danger: true, onClick: async () => {
        if (await confirmDlg(t("¿Eliminar «{name}»?", { name: v.name }),
          t("La biblioteca, con sus {n} videos y todos sus archivos, se moverá a la papelera. Puedes restaurarla durante 30 días.", { n: v.count }),
          t("Eliminar"), v.name)) {
          send({ type: "vault_remove", id: v.id, delete_files: true });
        }
      } },
    ], at);
}

// tarjeta de biblioteca: banner con su color · ícono · nombre · cifras · acciones (Ajustes › Bibliotecas)
// mode "pref": con su carpeta y botones · "pick": toda la tarjeta la abre
function vaultCard(v, mode) {
  const isCur = v.id === vaults.current;
  const owner = !document.body.classList.contains("guest");
  const counts = vaultCounts(v);
  const menu = (at) => vaultMenu(v, at);
  const card = el("article", { class: `vcard ${mode}` + (isCur ? " on" : ""), "data-vault": v.id },
    el("div", { class: "vcard-top" }, vaultAscii(v, 160, 14, "fill"), vaultBadge(v, "lg"),  // su escena de caracteres, como en la pantalla de Bibliotecas
      isCur ? el("span", { class: "chip vcur", text: t("Abierta") }) : null),
    el("div", { class: "vcard-body" },
      el("div", { class: "vcard-name" }, el("strong", { text: v.name }), v.access && v.access.mode !== "privada"
        ? el("span", { class: "chip", text: v.access.mode === "publica" ? t("Pública") : t("Con contraseña") }) : null),
      el("small", { text: counts }),
      mode === "pref" ? el("code", { class: "vpath", text: v.path, title: v.path }) : null),
    el("div", { class: "vcard-acts" },
      mode === "pref" && !isCur ? btn(t("Abrir"), { size: "sm", icon: "arrow", onClick: () => openVault(v.id) }) : null,
      mode === "pref" && owner ? btn(t("Editar"), { size: "sm", icon: "pencil", variant: "ghost", onClick: () => editVault(v.id) }) : null,
      el("span", { class: "grow" }),
      btn(t("Más"), { size: "sm", icon: "dots", variant: "ghost", cls: "icon", title: t("Más opciones"), onClick: (e) => { e.stopPropagation(); menu(e.currentTarget.getBoundingClientRect()); } })));
  if (mode === "pick") {
    card.tabIndex = 0;
    card.addEventListener("click", () => { closeVaultScreen(); openVault(v.id); });
    card.addEventListener("keydown", (e) => { if (e.key === "Enter") card.click(); });
  }
  card.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); menu({ x: e.clientX, y: e.clientY }); });
  return card;
}
function newVaultCard() {
  return el("button", { type: "button", class: "vcard new owner-only", on: { click: () => { closeVaultScreen(); openVaultDlg("new"); } } },
    el("span", { class: "vnew-ic" }, icon("plus")), el("strong", { text: t("Nueva biblioteca") }),
    el("small", { text: t("Con su propio color, ícono y carpeta") }));
}

/* ------------------------------------------------------------ pantalla de bibliotecas */
// la abierta destacada, con una escena de caracteres en su color, y las demás al lado en tarjetas compactas con
// su patrón asomando en la esquina derecha (elegido 2026-11-14)

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
function vaultStats(v) {
  const n = vaultCount(v);
  const parts = [n === 1 ? t("1 video") : t("{n} videos", { n })];
  if (v.downloaded != null) parts.push(t("{n} en el equipo", { n: v.downloaded }));
  if (v.access && v.access.mode !== "privada") parts.push(v.access.mode === "publica" ? t("Pública") : t("Con contraseña"));
  return parts.join(" · ");
}
function vaultPickable(node, v) {
  node.tabIndex = 0;
  node.addEventListener("click", () => { closeVaultScreen(); if (v.id !== vaults.current) openVault(v.id); });
  node.addEventListener("keydown", (e) => { if (e.key === "Enter") node.click(); });
  node.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); vaultMenu(v, { x: e.clientX, y: e.clientY }); });
  return node;
}
function moreBtn(v) {
  return btn(t("Más"), { size: "sm", icon: "dots", variant: "ghost", cls: "icon vmore", title: t("Más opciones"),
    onClick: (e) => { e.stopPropagation(); vaultMenu(v, e.currentTarget.getBoundingClientRect()); } });
}
// la abierta: grande, con su escena de fondo
function vaultHero(v) {
  return vaultPickable(el("article", { class: "vhero", "data-vault": v.id },
    vaultAscii(v, 150, 34, "fill"),
    moreBtn(v),
    el("div", { class: "vhero-info" }, vaultBadge(v, "xl"),
      el("div", { class: "vhero-text" }, el("strong", { text: v.name }), el("small", { text: vaultStats(v) })))), v);
}
// las demás: compactas, con el patrón solo en la esquina derecha
function vaultMini(v) {
  return vaultPickable(el("article", { class: "vmini", "data-vault": v.id },
    vaultAscii(v, 40, 9, "corner"),
    vaultBadge(v, "md"),
    el("div", { class: "vmini-text" }, el("strong", { text: v.name }), el("small", { text: vaultStats(v) })),
    moreBtn(v)), v);
}
function newVaultMini() {
  return el("button", { type: "button", class: "vmini new owner-only", on: { click: () => { closeVaultScreen(); openVaultDlg("new"); } } },
    el("span", { class: "vnew-ic" }, icon("plus")), el("strong", { text: t("Nueva biblioteca") }));
}
function renderVaultScreen() {
  const cur = currentVault();
  const others = vaults.list.filter((v) => v.id !== cur.id);
  $("#vault-grid").replaceChildren(vaultHero(cur), el("div", { class: "vside" }, ...others.map(vaultMini), newVaultMini()));
}
function openVaultScreen() {
  closeVaultPop();
  renderVaultScreen();
  $("#vault-screen").showModal();
}
function closeVaultScreen() { if ($("#vault-screen").open) $("#vault-screen").close(); }
function renderVaultViews() {
  if ($("#vault-screen").open) renderVaultScreen();
  if (currentView() === "prefs" && typeof renderPrefs === "function") renderPrefs();
}
$("#vault-screen-manage").addEventListener("click", () => { closeVaultScreen(); openPrefs("bibliotecas"); });
$("#vault-screen-folder").addEventListener("click", () => send({ type: "vault_pick_folder", for: "open" }));

/* ------------------------------------------------------------ mover videos */
// botón con menú de las demás bibliotecas (en la selección del estante)
function moveMenu(ids, after) {
  const others = vaults.list.filter((v) => v.id !== vaults.current);
  if (!others.length) return null;
  const pop = el("div", { class: "popover move-pop", hidden: true },
    el("ul", {}, ...others.map((v) => el("li", {}, el("button", { type: "button", class: "vitem", on: { click: () => {
      pop.hidden = true;
      send({ type: "vault_move", videos: ids(), to: v.id });
      after?.();
    } } }, vaultBadge(v), el("span", { class: "vname", text: v.name }))))));
  const b = btn(t("Mover a…"), { icon: "folder", onClick: (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; } });
  return el("div", { class: "menu-wrap owner-only" }, b, pop);
}
document.addEventListener("click", (e) => {
  for (const p of document.querySelectorAll(".move-pop")) if (!p.parentElement.contains(e.target)) p.hidden = true;
});

/* ------------------------------------------------------------ videos de otras bibliotecas */
// la cola es una sola: para mostrar los de otra biblioteca se piden su título y miniatura
lib.meta = {};
const metaAsked = new Set();
let metaTimer = null;
function videoInfo(id) {
  const v = lib.videos[id] || lib.meta[id];
  if (!v && !metaAsked.has(id)) {
    metaAsked.add(id);
    clearTimeout(metaTimer);
    metaTimer = setTimeout(() => send({ type: "lib_meta", ids: [...metaAsked].filter((x) => !lib.meta[x]).slice(0, 300) }), 150);
  }
  return v;
}
function libMeta(m) {
  Object.assign(lib.meta, m.videos);
  if (typeof renderQueuePanel === "function") renderQueuePanel();
  if (currentView() === "queue") { $("#qlist").dataset.sig = ""; renderQueueScreen(); }
}
// abrir un video de otra biblioteca: primero se cambia a esa biblioteca
function playAcross(id, vaultId) {
  if (!vaultId || vaultId === vaults.current) return playItem(id);
  lib.openAfterSwitch = id;
  send({ type: "vault_open", id: vaultId });
}
