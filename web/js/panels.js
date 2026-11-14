/* =====================================================================
   Paneles con ancho ajustable: la barra lateral (izquierda) y el panel del video (derecha: transcripción,
   agente y personas). Se arrastra su borde; al llegar al mínimo se detiene ahí, y si se sigue arrastrando
   la barra lateral pasa a solo íconos y el panel del video se oculta. Oculto, su borde queda a la derecha
   para volver a sacarlo. Doble clic en un borde: el ancho de siempre. Los anchos se recuerdan (navegador).
   ===================================================================== */

const PANELS = {
  aside: { min: 200, max: 420, def: 256, key: "vt-aside-w", css: "--side-w", hide: 70 },
  panel: { min: 320, max: 760, def: 380, key: "vt-panel-w", css: "--panel-w", hide: 90 },
};

function panelWidth(name, w) {
  const p = PANELS[name];
  document.documentElement.style.setProperty(p.css, `${Math.round(w)}px`);
  try { localStorage.setItem(p.key, String(Math.round(w))); } catch { /* sin almacenamiento */ }
}

for (const name of Object.keys(PANELS)) {
  try {
    const w = +localStorage.getItem(PANELS[name].key);
    if (w >= PANELS[name].min && w <= PANELS[name].max) document.documentElement.style.setProperty(PANELS[name].css, `${w}px`);
  } catch { /* sin almacenamiento */ }
}

function resizer(name) {
  const h = el("div", { class: `rz rz-${name}`, role: "separator", "aria-orientation": "vertical",
    title: name === "aside" ? "Arrastra para cambiar el ancho de la barra lateral" : "Arrastra para cambiar el ancho del panel" });
  h.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    h.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing");
    const p = PANELS[name];
    const startW = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(p.css)) || p.def;
    const right = name === "panel" ? (($("#side").offsetParent && $("#side").getBoundingClientRect().right) || innerWidth - 20) : 0;
    const move = (ev) => {
      const w = name === "aside" ? ev.clientX : right - ev.clientX;
      if (name === "aside") {
        const mini = w < p.min - p.hide;
        if (typeof setSideMini === "function" && mini !== document.body.classList.contains("side-mini")) setSideMini(mini);
        if (!mini) panelWidth(name, Math.min(p.max, Math.max(p.min, w)));
      } else {
        const off = w < p.min - p.hide;
        if (off !== document.body.classList.contains("side-off")) setSide(!off);
        if (!off) panelWidth(name, Math.min(p.max, Math.max(p.min, w)));
      }
      h.classList.toggle("at-edge", w <= p.min || w >= p.max);  // el tope se nota: el borde se marca
    };
    const up = () => {
      // contraído u oculto: al volver a abrirlo tiene el ancho de antes, no el mínimo por el que pasó
      if (document.body.classList.contains(name === "aside" ? "side-mini" : "side-off")) panelWidth(name, startW);
      document.body.classList.remove("resizing");
      h.classList.remove("at-edge");
      h.removeEventListener("pointermove", move);
      h.removeEventListener("pointerup", up);
      h.removeEventListener("pointercancel", up);
    };
    h.addEventListener("pointermove", move);
    h.addEventListener("pointerup", up);
    h.addEventListener("pointercancel", up);
  });
  h.addEventListener("dblclick", () => {
    panelWidth(name, PANELS[name].def);
    if (name === "aside" && typeof setSideMini === "function") setSideMini(false);
    if (name === "panel") setSide(true);
  });
  return h;
}

document.body.append(resizer("aside"), resizer("panel"));
