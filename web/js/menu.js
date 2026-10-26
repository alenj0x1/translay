"use strict";
// Menús propios (sin los nativos del navegador): el contextual (web/js/contextmenu.js)
// y las listas desplegables. Usa el() e icon() de web/js/ui.js.
//
// openMenu(items, at, opts)
//   items: [{ label, icon, badge, kbd, onClick, danger, disabled, check, sub: [...] }, "sep", { head: "texto" }]
//   at:    { x, y } (junto al mouse) o un DOMRect (debajo de ese elemento)

let menuOpen = null;

function closeMenu() {
  for (const m of document.querySelectorAll(".menu")) m.remove();
  menuOpen?.onClose?.();
  menuOpen = null;
}

function buildMenu(items, depth = 0) {
  const box = el("div", { class: "menu", role: "menu" });
  for (const it of items) {
    if (!it) continue;
    if (it === "sep") { if (box.lastChild && !box.lastChild.classList.contains("menu-sep")) box.append(el("div", { class: "menu-sep" })); continue; }
    if (it.head) { box.append(el("div", { class: "menu-head", text: it.head })); continue; }
    const b = el("button", { type: "button", role: "menuitem", class: "menu-item" + (it.danger ? " danger" : "") + (it.sub ? " sub" : "") + (it.check ? " current" : ""),
      disabled: !!it.disabled, title: it.title || null },
      it.badge || (it.icon ? icon(it.icon) : el("i", { class: "menu-gap" })),
      el("span", { class: "mi-label", text: it.label }),
      it.check ? icon("check") : it.kbd ? el("kbd", { text: it.kbd }) : null);
    if (it.sub) {
      let child = null;
      const open = () => {
        for (const c of box.querySelectorAll(":scope ~ .menu.d" + (depth + 1))) c.remove();
        for (const m of document.querySelectorAll(`.menu.d${depth + 1}`)) m.remove();
        child = buildMenu(it.sub, depth + 1);
        (document.querySelector("dialog[open]") || document.body).append(child);
        place(child, b.getBoundingClientRect(), true);
        for (const s of box.querySelectorAll(".menu-item.hl")) s.classList.remove("hl");
        b.classList.add("hl");
      };
      b.addEventListener("mouseenter", open);
      b.addEventListener("click", open);
    } else {
      b.addEventListener("mouseenter", () => { for (const m of document.querySelectorAll(`.menu.d${depth + 1}`)) m.remove(); });
      b.addEventListener("click", () => { closeMenu(); it.onClick?.(); });
    }
    box.append(b);
  }
  // sin separadores sobrantes al final
  while (box.lastChild?.classList.contains("menu-sep")) box.lastChild.remove();
  box.classList.add("d" + depth);
  return box;
}

// lo ubica dentro de la ventana: si no cabe abajo/derecha, se abre hacia arriba/izquierda
function place(m, at, side = false) {
  const vw = innerWidth, vh = innerHeight, pad = 8;
  const r = m.getBoundingClientRect();
  let x, y;
  if (at instanceof DOMRect) {
    if (side) { x = at.right + 4; y = at.top - 6; if (x + r.width > vw - pad) x = at.left - r.width - 4; }
    else {
      // debajo si cabe (o hay lugar razonable, con scroll); si no, arriba
      const below = vh - at.bottom - 6 - pad, above = at.top - 6 - pad;
      x = at.left;
      if (r.height <= below || below >= Math.min(260, above)) { m.style.maxHeight = `${below}px`; y = at.bottom + 6; }
      else { m.style.maxHeight = `${above}px`; y = at.top - 6 - Math.min(r.height, above); }
      if (!side && m.dataset.width === "anchor") m.style.minWidth = `${at.width}px`;
      m.style.left = `${Math.max(pad, Math.min(x, vw - m.getBoundingClientRect().width - pad))}px`;
      m.style.top = `${Math.max(pad, y)}px`;
      return;
    }
    if (!side && m.dataset.width === "anchor") m.style.minWidth = `${at.width}px`;
  } else {
    x = at.x; y = at.y;
    if (x + r.width > vw - pad) x = Math.max(pad, x - r.width);
    if (y + r.height > vh - pad) y = Math.max(pad, y - r.height);
  }
  m.style.left = `${Math.max(pad, Math.min(x, vw - r.width - pad))}px`;
  m.style.top = `${Math.max(pad, Math.min(y, vh - r.height - pad))}px`;
  m.style.maxHeight = `${vh - pad * 2}px`;
}

function openMenu(items, at, opts = {}) {
  closeMenu();
  const m = buildMenu(items);
  if (!m.childElementCount) return null;
  if (opts.anchorWidth) m.dataset.width = "anchor";
  // dentro de un diálogo abierto (capa superior), el menú va en él para quedar encima
  (document.querySelector("dialog[open]") || document.body).append(m);
  place(m, at);
  menuOpen = { el: m, onClose: opts.onClose };
  const sel = m.querySelector(".menu-item.current") || m.querySelector(".menu-item:not([disabled])");
  if (opts.focus !== false) sel?.focus({ preventScroll: true });
  sel?.scrollIntoView({ block: "nearest" });
  return m;
}

document.addEventListener("pointerdown", (e) => { if (menuOpen && !e.target.closest(".menu")) closeMenu(); }, true);
addEventListener("blur", closeMenu);
addEventListener("resize", closeMenu);
document.addEventListener("scroll", (e) => { if (menuOpen && !e.target.closest?.(".menu")) closeMenu(); }, true);
document.addEventListener("keydown", (e) => {
  if (!menuOpen) return;
  const menus = [...document.querySelectorAll(".menu")];
  const cur = document.activeElement?.closest(".menu") || menus[menus.length - 1];
  const items = [...cur.querySelectorAll(".menu-item:not([disabled])")];
  const i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.preventDefault(); closeMenu(); }
  else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
  else if (e.key === "ArrowRight" && document.activeElement?.classList.contains("sub")) {
    e.preventDefault(); document.activeElement.click(); document.querySelector(".menu:last-of-type .menu-item")?.focus();
  } else if (e.key === "ArrowLeft" && menus.length > 1) { e.preventDefault(); cur.remove(); menus[menus.length - 2].querySelector(".hl")?.focus(); }
});

/* ------------------------------------------------------------ lista desplegable */
// Reemplaza la vista de un <select> (que sigue guardando el valor) por un botón y un
// menú propio. decorate(option) → elemento opcional (distintivo, ícono) para cada opción.
function dropdown(select, decorate = null) {
  if (select._dd) {
    if (decorate) select._dd.decorate = decorate;
    select._dd.refresh();
    return select._dd;
  }
  select.classList.add("native");
  select.tabIndex = -1;
  const btnEl = el("button", { type: "button", class: "dd", "aria-haspopup": "listbox" });
  select.after(btnEl);
  const deco = (o) => (select._dd?.decorate && o ? select._dd.decorate(o) : null);
  const refresh = () => {
    const o = select.selectedOptions[0];
    btnEl.replaceChildren(deco(o) || el("i", { class: "menu-gap" }), el("span", { class: "dd-label", text: o ? o.textContent : "" }), icon("chevron", "chev"));
    btnEl.firstChild.classList?.contains("menu-gap") && btnEl.firstChild.remove();
    btnEl.disabled = select.disabled;
  };
  const choose = (v) => { select.value = v; refresh(); select.dispatchEvent(new Event("change", { bubbles: true })); };
  btnEl.addEventListener("click", () => {
    if (menuOpen?.owner === btnEl) return closeMenu();
    const items = [];
    for (const node of select.children) {
      if (node.tagName === "OPTGROUP") {
        items.push("sep", { head: node.label });
        for (const o of node.children) items.push(opt(o));
      } else items.push(opt(node));
    }
    function opt(o) { return { label: o.textContent, badge: deco(o), check: o.value === select.value, onClick: () => choose(o.value) }; }
    const m = openMenu(items, btnEl.getBoundingClientRect(), { anchorWidth: true, onClose: () => btnEl.classList.remove("open") });
    if (m) {
      menuOpen.owner = btnEl;
      m.classList.add("dd-menu");
      btnEl.classList.add("open");

    }
  });
  select.addEventListener("change", refresh);
  new MutationObserver(refresh).observe(select, { childList: true, subtree: true });
  select._dd = { refresh, button: btnEl, decorate: decorate || DD_DECO[select.dataset.deco] || null };
  refresh();
  return select._dd;
}

// toda lista .select que aparezca en la página usa el menú propio; data-deco elige sus distintivos
const DD_DECO = {};
function enhanceSelects() {
  for (const s of document.querySelectorAll("select.select:not(.native)")) if (s.parentNode) dropdown(s);
}
new MutationObserver(enhanceSelects).observe(document.body, { childList: true, subtree: true });
enhanceSelects();
