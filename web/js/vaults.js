"use strict";
// Bibliotecas (vt/vaults.py): varias bibliotecas, cada una en su carpeta, con sus videos,
// colecciones, glosario, personas guardadas, tema y modo de importar.
//   · selector en el encabezado (cambiar, crear)
//   · Preferencias → Bibliotecas (editar, ubicación, quitar o eliminar)
//   · «Mover a…» en la selección de videos
// Usa lo global de app.js y library.js (state, send, lib, toast, confirmDlg…).

const vaults = { list: [], current: null, dlg: { mode: "new", id: null, folder: "", color: "", icon: "library" } };
const VAULT_COLORS = ["#e4572e", "#f3a712", "#29bf12", "#00a5cf", "#7d5ba6", "#e84f9b", "#2b2d42", "#8d6e63"];
const VAULT_NAMES = ["Documentales", "Para aprender", "Risas", "Música en vivo", "Charlas", "Tecnología", "Viajes",
  "Cocina", "Historia", "Podcasts", "Pendientes", "Favoritos", "Clásicos", "Entrevistas", "Ciencia", "Deportes",
  "Videojuegos", "Tutoriales", "Noticias", "Para la noche"];
const newPattern = () => Math.random().toString(36).slice(2, 8);
const VAULT_ICONS = [["library", "Biblioteca"], ["flask", "Ciencia"], ["smile", "Humor"], ["music", "Música"],
  ["book", "Aprender"], ["globe", "Mundo"], ["star", "Favoritos"], ["film", "Cine"], ["heart", "Me gusta"], ["atom", "Tecnología"],
  ["cap", "Educación"], ["gamepad", "Videojuegos"], ["ball", "Deportes"], ["plane", "Viajes"], ["chat", "Charlas"],
  ["brush", "Arte y estilo"], ["news", "Noticias"], ["paw", "Animales"]];

const currentVault = () => vaults.list.find((v) => v.id === vaults.current) || vaults.list[0] || { name: "Principal", id: "principal" };
const vaultById = (id) => vaults.list.find((v) => v.id === id);
// insignia: el ícono de la biblioteca sobre su color
function vaultBadge(v, cls = "") {
  const b = el("span", { class: ("vbadge " + cls).trim(), "aria-hidden": "true" }, icon(v.icon || "library"));
  b.style.setProperty("--vc", v.color || "var(--primary)");
  return b;
}

// distintivo de cada biblioteca en las listas desplegables (web/js/menu.js)
DD_DECO.vault = (o) => (o.value === "all" ? icon("library") : vaultById(o.value) ? vaultBadge(vaultById(o.value)) : null);

function vaultsUpdate(m) {
  const changed = vaults.current && vaults.current !== m.current;
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
  if (typeof applyAccent === "function") applyAccent(prefs.accent_lib ? currentVault().color : null);  // Preferencias → Apariencia
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
      el("small", { text: `${v.count ?? 0} ${v.count === 1 ? "video" : "videos"}` + (v.downloaded != null ? ` · ${v.downloaded} en el equipo` : "") })),
    el("button", { type: "button", class: "ic sm owner-only", title: "Editar la biblioteca", "aria-label": "Editar la biblioteca",
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
  if (typeof applyAccent === "function") applyAccent(prefs.accent_lib ? currentVault().color : null);
  renderVaultViews();
}

function renderVaultBtn() {
  renderSideVault();
  const v = currentVault();
  const b = $("#vault-btn");
  b.replaceChildren(vaultBadge(v), el("span", { class: "btn-text", text: v.name }), icon("chevron", "chev"));
  b.title = `Biblioteca: ${v.name}`;
}
function renderVaultPop() {
  const ul = $("#vault-list");
  ul.replaceChildren(...vaults.list.map((v) => el("li", { class: v.id === vaults.current ? "on" : "" },
    el("button", { type: "button", class: "vitem" + (v.id === vaults.current ? " on" : ""),
      on: { click: () => { closeVaultPop(); openVault(v.id); } } },
      vaultBadge(v),
      el("span", { class: "vname", text: v.name }),
      el("span", { class: "vcount", text: String(v.count) })),
    el("button", { type: "button", class: "ic sm vedit owner-only", title: `Editar «${v.name}»`, "aria-label": `Editar «${v.name}»`,
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
  $("#vault-dlg-title").textContent = mode === "new" ? "Nueva biblioteca" : `Editar «${v.name}»`;
  $("#vault-name").value = v ? v.name : "";
  $("#vault-go").textContent = mode === "new" ? "Crear" : "Guardar";
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
  $("#vault-preview").replaceChildren(vaultBanner(pv, "fill"), vaultBadge(pv, "lg"),
    el("strong", { text: $("#vault-name").value.trim() || $("#vault-name").placeholder.split(",")[0] }));
  $("#vault-colors").replaceChildren(...VAULT_COLORS.map((c) => {
    const b = el("button", { type: "button", class: "vcolor" + (d.color === c ? " on" : ""), "aria-label": `Color ${c}`,
      on: { click: () => { d.color = c; renderVaultLook(); } } });
    b.style.setProperty("--vc", c);
    return b;
  }));
  $("#vault-icons").replaceChildren(...VAULT_ICONS.map(([ic, t]) => {
    const b = el("button", { type: "button", class: "btn vicon" + (d.icon === ic ? " on" : ""), title: t, "aria-label": t,
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
$("#vault-shuffle").addEventListener("click", () => { vaults.dlg.pattern = newPattern(); renderVaultLook(); });
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

/* ------------------------------------------------------------ Preferencias → Bibliotecas */
const VAULTS_BLOCK = el("div", { class: "pref vaults-pref", id: "pref-vaults" },
  el("span", { class: "pref-label", text: "Tus bibliotecas" }), el("div", { class: "pref-ctl" }));
function renderVaultsPref() {
  const ctl = VAULTS_BLOCK.querySelector(".pref-ctl");
  ctl.replaceChildren(el("div", { class: "vcards" }, ...vaults.list.map((v) => vaultCard(v, "pref")), newVaultCard()),
    el("div", { class: "acts" }, btn("Abrir carpeta", { icon: "folder", size: "sm", title: "Una carpeta que ya es biblioteca (de un disco externo u otro equipo)",
      onClick: () => send({ type: "vault_pick_folder", for: "open" }) })));
}

// tarjeta de biblioteca: banner con su color · ícono · nombre · cifras · acciones
// mode "pref": con su carpeta y botones · "pick": toda la tarjeta la abre (pantalla de bibliotecas)
function vaultCard(v, mode) {
  const isCur = v.id === vaults.current;
  const owner = !document.body.classList.contains("guest");
  const counts = `${v.count ?? 0} ${v.count === 1 ? "video" : "videos"}` + (v.downloaded != null ? ` · ${v.downloaded} en el equipo` : "");
  const menu = (at) => {
    openMenu([
      { head: v.name },
      !isCur && { label: "Abrir", icon: "arrow", onClick: () => { closeVaultScreen(); openVault(v.id); } },
      owner && { label: "Editar…", icon: "pencil", onClick: () => { closeVaultScreen(); editVault(v.id); } },
      owner && { label: "Otro patrón", icon: "shuffle", onClick: () => reshuffleVault(v.id) },
      "sep",
      owner && !v.main && { label: "Quitar de la lista", icon: "x", onClick: async () => {
        if (await confirmDlg(`¿Quitar «${v.name}» de la lista?`,
          "Sus videos y archivos quedan en su carpeta; puedes volver a abrirla con «Abrir carpeta».", "Quitar")) {
          send({ type: "vault_remove", id: v.id, delete_files: false });
        }
      } },
      owner && !v.main && { label: "Eliminar", icon: "trash", danger: true, onClick: async () => {
        if (await confirmDlg(`¿Eliminar «${v.name}»?`,
          `Se borran sus ${v.count} videos con sus traducciones, voces y archivos descargados. No se puede deshacer.`, "Eliminar")) {
          send({ type: "vault_remove", id: v.id, delete_files: true });
        }
      } },
    ], at);
  };
  const card = el("article", { class: `vcard ${mode}` + (isCur ? " on" : ""), "data-vault": v.id },
    el("div", { class: "vcard-top" }, vaultBanner(v, "fill"), vaultBadge(v, "lg"),
      isCur ? el("span", { class: "chip vcur", text: "Abierta" }) : null),
    el("div", { class: "vcard-body" },
      el("div", { class: "vcard-name" }, el("strong", { text: v.name }), v.access && v.access.mode !== "privada"
        ? el("span", { class: "chip", text: v.access.mode === "publica" ? "Pública" : "Con contraseña" }) : null),
      el("small", { text: counts }),
      mode === "pref" ? el("code", { class: "vpath", text: v.path, title: v.path }) : null),
    el("div", { class: "vcard-acts" },
      mode === "pref" && !isCur ? btn("Abrir", { size: "sm", icon: "arrow", onClick: () => openVault(v.id) }) : null,
      mode === "pref" && owner ? btn("Editar", { size: "sm", icon: "pencil", variant: "ghost", onClick: () => editVault(v.id) }) : null,
      el("span", { class: "grow" }),
      btn("Más", { size: "sm", icon: "dots", variant: "ghost", cls: "icon", title: "Más opciones", onClick: (e) => { e.stopPropagation(); menu(e.currentTarget.getBoundingClientRect()); } })));
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
    el("span", { class: "vnew-ic" }, icon("plus")), el("strong", { text: "Nueva biblioteca" }),
    el("small", { text: "Con su propio color, ícono y carpeta" }));
}

/* ------------------------------------------------------------ pantalla de bibliotecas */
function renderVaultScreen() {
  $("#vault-grid").replaceChildren(...vaults.list.map((v) => vaultCard(v, "pick")), newVaultCard());
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
  const b = btn("Mover a…", { icon: "folder", onClick: (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; } });
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
