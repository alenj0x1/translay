"use strict";
// Bibliotecas (vt/vaults.py): varias bibliotecas, cada una en su carpeta, con sus videos,
// colecciones, glosario, personas guardadas, tema y modo de importar.
//   · selector en el encabezado (cambiar, crear)
//   · Preferencias → Bibliotecas (editar, ubicación, quitar o eliminar)
//   · «Mover a…» en la selección de videos
// Usa lo global de app.js y library.js (state, send, lib, toast, confirmDlg…).

const vaults = { list: [], current: null, dlg: { mode: "new", id: null, folder: "", color: "", icon: "library" } };
const VAULT_COLORS = ["#e4572e", "#f3a712", "#29bf12", "#00a5cf", "#7d5ba6", "#e84f9b", "#2b2d42", "#8d6e63"];
const VAULT_ICONS = [["library", "Biblioteca"], ["flask", "Ciencia"], ["smile", "Humor"], ["music", "Música"],
  ["book", "Aprender"], ["globe", "Mundo"], ["star", "Favoritos"], ["film", "Cine"]];

const currentVault = () => vaults.list.find((v) => v.id === vaults.current) || vaults.list[0] || { name: "Principal", id: "principal" };
const vaultById = (id) => vaults.list.find((v) => v.id === id);
// insignia: el ícono de la biblioteca sobre su color
function vaultBadge(v, cls = "") {
  const b = el("span", { class: ("vbadge " + cls).trim(), "aria-hidden": "true" }, icon(v.icon || "library"));
  b.style.setProperty("--vc", v.color || "var(--fill)");
  return b;
}

function vaultsUpdate(m) {
  const changed = vaults.current && vaults.current !== m.current;
  vaults.list = m.items;
  vaults.current = m.current;
  if (changed) {  // otra biblioteca: la vista empieza desde arriba
    lib.sel = "recent";
    lib.picked.clear();
    lib.meta = {};
    lib.qlib = null;  // la Cola vuelve a mostrar la biblioteca abierta
    if (typeof closeSearch === "function") closeSearch();
  }
  renderVaultBtn();
  renderVaultPop();
  if (typeof renderQueuePanel === "function") {  // la cola muestra lo de la biblioteca abierta
    for (const n of ["#qnav", "#qhead", "#qlist"]) $(n).dataset.sig = "";
    renderQueuePanel();
  }
  if (typeof renderPrefs === "function" && prefsSections.length) renderPrefs();
}

/* ------------------------------------------------------------ selector del encabezado */
function renderVaultBtn() {
  const v = currentVault();
  const b = $("#vault-btn");
  b.replaceChildren(vaultBadge(v), el("span", { class: "btn-text", text: v.name }), icon("chevron", "chev"));
  b.title = `Biblioteca: ${v.name}`;
}
function renderVaultPop() {
  const ul = $("#vault-list");
  ul.replaceChildren(...vaults.list.map((v) => el("li", {},
    el("button", { type: "button", class: "vitem" + (v.id === vaults.current ? " on" : ""),
      on: { click: () => { closeVaultPop(); openVault(v.id); } } },
      vaultBadge(v),
      el("span", { class: "vname", text: v.name }),
      el("span", { class: "vcount", text: String(v.count) }),
      v.id === vaults.current ? icon("check", "vcheck") : null))));
}
function openVault(id) {
  if (id === vaults.current) return;
  send({ type: "vault_open", id });
  if (currentView() === "queue" || currentView() === "prefs") return;
  setView("library");
}
const openVaultPop = () => { renderVaultPop(); $("#vault-pop").hidden = false; };
const closeVaultPop = () => { $("#vault-pop").hidden = true; };
$("#vault-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("#vault-pop").hidden ? openVaultPop() : closeVaultPop();
});
document.addEventListener("click", (e) => { if (!e.target.closest(".vault-wrap")) closeVaultPop(); });
$("#vault-new").addEventListener("click", () => { closeVaultPop(); openVaultDlg("new"); });
$("#vault-manage").addEventListener("click", () => {
  closeVaultPop();
  setView("prefs");
  requestAnimationFrame(() => $("#sec-bibliotecas")?.scrollIntoView({ block: "start" }));
});

/* ------------------------------------------------------------ crear / editar */
function openVaultDlg(mode, id = null) {
  const v = id ? vaultById(id) : null;
  vaults.dlg = { mode, id, folder: "", color: v?.color || VAULT_COLORS[vaults.list.length % VAULT_COLORS.length],
    icon: v?.icon || "library" };
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
  $("#vault-colors").replaceChildren(...VAULT_COLORS.map((c) => {
    const b = el("button", { type: "button", class: "vcolor" + (d.color === c ? " on" : ""), "aria-label": `Color ${c}`,
      on: { click: () => { d.color = c; renderVaultLook(); } } });
    b.style.setProperty("--vc", c);
    return b;
  }));
  $("#vault-icons").replaceChildren(...VAULT_ICONS.map(([ic, t]) => {
    const b = el("button", { type: "button", class: "seg vicon" + (d.icon === ic ? " on" : ""), title: t, "aria-label": t,
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
$("#vault-form").addEventListener("submit", (e) => {
  const dlg = $("#vault-dlg");
  if (e.submitter?.value !== "ok") return;
  const d = vaults.dlg;
  const name = $("#vault-name").value.trim();
  if (!name) { e.preventDefault(); $("#vault-name").focus(); return; }
  const folder = d.where === "folder" ? $("#vault-folder").value.trim() : "";
  if (d.where === "folder" && !folder) { e.preventDefault(); send({ type: "vault_pick_folder", for: "new" }); return; }
  if (d.mode === "new") {
    send({ type: "vault_create", name, folder, color: d.color, icon: d.icon });
    if (currentView() !== "prefs") setView("library");
  } else {
    send({ type: "vault_update", id: d.id, name, color: d.color, icon: d.icon });
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
  const rows = vaults.list.map((v) => {
    const isCur = v.id === vaults.current;
    const acts = el("div", { class: "vacts" },
      isCur ? el("span", { class: "chip", text: "Abierta" })
        : btn("Abrir", { size: "xs", icon: "play", onClick: () => send({ type: "vault_open", id: v.id }) }),
      btn("Editar", { size: "xs", icon: "pencil", variant: "ghost", onClick: () => openVaultDlg("edit", v.id) }),
      v.main ? null : btn("Quitar", { size: "xs", icon: "x", variant: "ghost", title: "Quitar de la lista (los archivos quedan en su carpeta)",
        onClick: async () => {
          if (await confirmDlg(`¿Quitar «${v.name}» de la lista?`,
            "Sus videos y archivos quedan en su carpeta; puedes volver a abrirla con «Abrir carpeta».", "Quitar")) {
            send({ type: "vault_remove", id: v.id, delete_files: false });
          }
        } }),
      v.main ? null : btn("Eliminar", { size: "xs", icon: "trash", variant: "danger", onClick: async () => {
        if (await confirmDlg(`¿Eliminar «${v.name}»?`,
          `Se borran sus ${v.count} videos con sus traducciones, voces y archivos descargados. No se puede deshacer.`, "Eliminar")) {
          send({ type: "vault_remove", id: v.id, delete_files: true });
        }
      } }));
    return el("div", { class: "vrow" + (isCur ? " on" : "") },
      vaultBadge(v, "lg"),
      el("div", { class: "vinfo" },
        el("strong", { text: v.name }),
        el("small", { text: `${v.count} ${v.count === 1 ? "video" : "videos"} · ${v.downloaded} en el equipo` }),
        el("code", { text: v.path, title: v.path })),
      acts);
  });
  ctl.replaceChildren(el("div", { class: "vrows" }, ...rows), el("div", { class: "segs" },
    btn("Nueva biblioteca", { icon: "plus", variant: "dark", onClick: () => openVaultDlg("new") }),
    btn("Abrir carpeta", { icon: "folder", title: "Una carpeta que ya es biblioteca (de un disco externo u otro equipo)",
      onClick: () => send({ type: "vault_pick_folder", for: "open" }) })));
}

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
  return el("div", { class: "menu-wrap" }, b, pop);
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
