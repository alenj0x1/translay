"use strict";
// Papelera (vt/trash.py): lo borrado se guarda 30 días y se puede devolver.
// «Deshacer» en el aviso al borrar y Preferencias → Papelera. Usa lo global de app.js.

const trash = { items: [] };

const TRASH_BLOCK = el("div", { class: "pref trash-pref", id: "pref-trash" },
  el("span", { class: "pref-label", text: "En la papelera" }), el("div", { class: "pref-ctl" }));

const TRASH_ICON = { videos: "film", "biblioteca-vaciada": "library", biblioteca: "folder" };

function daysLeft(x) {
  const d = Math.max(0, Math.ceil((x.expires * 1000 - Date.now()) / 86400000));
  return d === 1 ? "Se borra mañana" : `Se borra en ${d} días`;
}

function renderTrash() {
  const ctl = TRASH_BLOCK.querySelector(".pref-ctl");
  if (!trash.items.length) {
    ctl.replaceChildren(el("div", { class: "empty-state small" }, el("span", { class: "vnew-ic" }, icon("trash")),
      el("h3", { text: "La papelera está vacía" }),
      el("p", { text: "Lo que borres (videos, una biblioteca vaciada o eliminada) queda aquí 30 días." })));
    return;
  }
  const when = (t) => new Date(t * 1000).toLocaleString("es", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const rows = trash.items.map((x) => el("div", { class: "trow" },
    el("span", { class: "trow-ic" }, icon(TRASH_ICON[x.kind] || "trash")),
    el("div", { class: "vinfo" },
      el("strong", { text: x.title }),
      el("small", { text: [x.kind === "biblioteca" ? "" : x.vault_name,
        x.count ? `${x.count} ${x.count === 1 ? "video" : "videos"}` : "", `borrado el ${when(x.created)}`, daysLeft(x)]
        .filter(Boolean).join(" · ") })),
    el("div", { class: "vacts" },
      btn("Restaurar", { icon: "undo", size: "sm", onClick: () => send({ type: "trash_restore", id: x.id, vault: x.vault }) }),
      btn("Borrar para siempre", { icon: "trash", size: "sm", variant: "ghost", cls: "icon", title: "Borrar para siempre",
        onClick: async () => {
          if (await confirmDlg(`¿Borrar «${x.title}» para siempre?`, "Ya no se va a poder devolver.", "Borrar para siempre")) {
            send({ type: "trash_purge", id: x.id, vault: x.vault });
          }
        } }))));
  ctl.replaceChildren(el("div", { class: "vrows" }, ...rows), el("div", { class: "acts" },
    btn("Vaciar la papelera", { icon: "trash", size: "sm", variant: "danger", onClick: async () => {
      if (await confirmDlg("¿Vaciar la papelera?", "Todo lo que hay en ella se borra para siempre.", "Vaciar la papelera")) {
        send({ type: "trash_purge", all: true });
      }
    } })));
}

// mensajes del servidor (web/js/app.js · onMessage)
function trashUpdate(m) {
  trash.items = m.items || [];
  renderTrash();
}
function trashed(m) {
  toast(`${m.title}: se movió a la papelera.`, "ok", { label: "Deshacer", onClick: () => send({ type: "trash_restore", id: m.id, vault: m.vault }) });
}
function trashRestored() {
  toast("Se devolvió tal como estaba.", "ok");
}
