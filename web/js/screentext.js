/* =====================================================================
   Texto en pantalla (vt/screentext.py): lo escrito en el video (títulos, letreros, diapositivas,
   comentarios del código), traducido y puesto encima en el mismo lugar, con el color del fondo y
   del texto originales. El código, los comandos y los enlaces llegan sin traducción: no se tapan.

   Una capa en cada pantalla (la del original en la vista ampliada, la del español en la dividida),
   ubicada sobre la imagen real del video (sin las franjas negras de object-fit: contain).
   ===================================================================== */

const screenText = { items: [], shown: new Map() };  // id → elementos dibujados (uno por capa)
const stLayers = () => document.querySelectorAll(".st-layer");

function screenTextLoad(data) {
  // todo lo leído (también el código, los comandos y los enlaces, que no se traducen): para tocarlo sobre el video
  screenText.all = (data?.items || []).filter((it) => it.box && it.kind !== "noise" && it.kind !== "ui");
  screenText.items = (data?.items || []).filter((it) => it.translation);
  screenText.items.sort((a, b) => a.start - b.start);
  for (const layer of stLayers()) layer.replaceChildren();
  screenText.shown.clear();
  setElements(data?.elements || []);
  renderScreenText();
}

function screenTextAdd(m) {
  if (m.elements) setElements(m.elements);
  screenText.all = (screenText.all || []).concat((m.items || []).filter((it) => it.box && it.kind !== "noise" && it.kind !== "ui"));
  const add = (m.items || []).filter((it) => it.translation);
  if (!add.length) { renderHits(); return; }
  screenText.items.push(...add);
  screenText.items.sort((a, b) => a.start - b.start);
  renderScreenText();
}

/* ------------------------------------------------------------ elementos del video en la transcripción
   Lo que conviene tener a mano de lo escrito en pantalla (vt/videocontext.py): código, comandos,
   enlaces, correos, cuentas y comentarios del código, en su lugar entre las frases. */
const ELEMENT_LABEL = { code: "Código", command: "Comando", link: "Enlace", email: "Correo", handle: "Cuenta",
  comment: "Comentario del código" };
const ELEMENT_ICON = { code: "code", command: "terminal", link: "link", email: "link", handle: "user", comment: "comment" };

function setElements(list) {
  const sig = list.map((e) => `${e.id}:${e.text.length}`).join(",");
  if (sig === state.elementsSig) return;
  state.elements = list;
  state.elementsSig = sig;
  if (typeof renderTranscript === "function" && state.videoId) renderTranscript();
}

function elementItem(e) {
  const li = el("li", { class: `el-row k-${e.kind}`, "data-start": e.start, "data-el": e.id });
  const block = e.kind === "code" || e.kind === "command";
  // código, comandos y comentarios con los colores del tema de Ajustes (web/js/codetheme.js)
  const colored = block || e.kind === "comment";
  const body = colored ? el("pre", { class: "codeblk" }) : el("p", {}, e.text);
  // un comentario lleva su traducción en el mismo bloque, debajo: se lee como el código del video
  if (colored) body.append(highlight(e.kind === "comment" && e.translation ? `${e.text}\n${e.translation}` : e.text));
  const copy = el("button", { type: "button", class: "ic sm el-copy", title: "Copiar", "aria-label": "Copiar" }, icon("copy"));
  li.append(el("div", { class: "el-head" },
    el("time", {}, fmt(e.start)), el("span", { class: "el-kind" }, icon(ELEMENT_ICON[e.kind] || "code"), ELEMENT_LABEL[e.kind] || ""), copy),
  body);
  return li;
}

function elementsText() {
  return (state.elements || []).map((e) => `[${fmt(e.start)}] ${ELEMENT_LABEL[e.kind]}:\n${e.text}`).join("\n\n");
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("#transcript .el-copy");
  if (!b) return;
  ev.stopPropagation();
  const e = (state.elements || []).find((x) => String(x.id) === b.closest("li").dataset.el);
  if (e) copyText(e.text, ELEMENT_LABEL[e.kind] || "Texto");
}, true);

// la imagen dentro del elemento <video> (object-fit: contain deja franjas a los lados o arriba)
function videoRect(v) {
  const W = v.clientWidth, H = v.clientHeight;
  const vw = v.videoWidth, vh = v.videoHeight;
  if (!W || !H || !vw || !vh) return null;
  const s = Math.min(W / vw, H / vh);
  const w = vw * s, h = vh * s;
  return { left: (W - w) / 2, top: (H - h) / 2, width: w, height: h };
}

// el texto entra en su caja: se achica hasta que cabe (no se sale ni se corta)
function fitText(el) {
  let size = parseFloat(el.style.fontSize);
  for (let i = 0; i < 12 && size > 7 && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1); i++) {
    size *= 0.9;
    el.style.fontSize = size + "px";
  }
}

function placeItem(el, it, rect) {
  const [x, y, w, h] = it.box;
  // un poco más grande que el original: tapa también el borde suavizado de las letras
  const pad = Math.max(2, rect.height * 0.004);
  let left = rect.left + x * rect.width - pad, width = w * rect.width + 2 * pad;
  el.style.top = rect.top + y * rect.height - pad + "px";
  el.style.height = h * rect.height + 2 * pad + "px";
  el.style.fontSize = (h * rect.height / (it.lines || 1)) * 0.74 + "px";
  if ((it.lines || 1) === 1) {
    // en español suele ser más largo: la caja crece (hasta 1,6 veces, sin salir del video) antes que achicar la letra
    el.style.left = left + "px";
    el.style.width = width + "px";
    el.style.whiteSpace = "nowrap";
    const need = el.scrollWidth + 1;
    el.style.whiteSpace = "";
    if (need > width) {
      let nw = Math.min(need, width * 1.6);
      if (it.align === "left") nw = Math.min(nw, rect.left + rect.width - left - 2);
      else {
        const cx = left + width / 2;
        nw = Math.min(nw, 2 * (cx - rect.left - 2), 2 * (rect.left + rect.width - 2 - cx));
        left = cx - Math.max(width, nw) / 2;
      }
      width = Math.max(width, nw);
    }
  }
  el.style.left = left + "px";
  el.style.width = width + "px";
  fitText(el);
}

function renderScreenText() {
  renderHits();
  const on = prefs.screen_text !== false && state.translates && screenText.items.length;
  document.body.classList.toggle("has-screen-text", !!on);
  if (!on) {
    for (const layer of stLayers()) layer.replaceChildren();
    screenText.shown.clear();
    return;
  }
  const t = vEn.currentTime;
  const now = new Set(screenText.items.filter((it) => it.start <= t && t < it.end).map((it) => it.id));
  for (const [id, els] of screenText.shown) {
    if (!now.has(id)) { els.forEach((e) => e.remove()); screenText.shown.delete(id); }
  }
  for (const layer of stLayers()) {
    const v = layer.parentElement.querySelector("video");
    const rect = videoRect(v);
    layer.dataset.ok = rect ? "1" : "";
    if (!rect) continue;
    for (const it of screenText.items) {
      if (!now.has(it.id)) continue;
      let els = screenText.shown.get(it.id);
      if (!els) screenText.shown.set(it.id, els = []);
      let el = els.find((e) => e.parentElement === layer);
      const key = `${rect.width}x${rect.height}`;
      if (!el) {
        el = document.createElement("div");
        el.className = "st-item" + (it.kind === "comment" ? " st-code" : "") + (it.align === "left" ? " st-left" : "");
        el.textContent = it.translation;
        el.title = it.text;  // al pasar el mouse: lo que decía en el original
        el.style.background = it.bg;
        el.style.color = it.fg;
        el._item = it;
        layer.append(el);
        els.push(el);
      }
      if (el.dataset.at !== key) {  // se recalcula solo si cambió el tamaño del video
        el.dataset.at = key;
        el.querySelector(".sh-bar")?.remove();
        placeItem(el, it, rect);
        el.append(hitBar(it));  // después de medir: la barrita va afuera, encima
      }
    }
  }
}

vEn.addEventListener("timeupdate", renderScreenText);
vEn.addEventListener("seeked", renderScreenText);
vEn.addEventListener("loadedmetadata", renderScreenText);
// el tamaño del video cambia (ventana, vista ampliada/dividida, pantalla completa, miniatura)
new ResizeObserver(() => renderScreenText()).observe($("#v-en"));
new ResizeObserver(() => renderScreenText()).observe($("#v-es"));

/* ------------------------------------------------------------ tocar lo escrito en el video
   Sobre cada texto que se ve (código, comando, enlace, comentario o texto traducido) hay una zona: al pasar
   el mouse o al hacer clic aparece una barrita con «Copiar» y «Preguntar a Lumi»; el clic derecho tiene lo
   mismo (web/js/contextmenu.js › screenHitMenu). El clic sobre la zona no pausa el video. */
const HIT_LABEL = { ...ELEMENT_LABEL, text: "Texto" };

function hitText(it) {
  // lo que se copia: el código tal cual; un texto traducido, en español
  return it.kind === "text" && it.translation ? it.translation : it.text;
}

function askAgentAbout(it) {
  if (typeof setSide === "function") setSide(true);
  $('#side-tabs [data-tab="summary"]')?.click();
  const what = (HIT_LABEL[it.kind] || "Texto").toLowerCase();
  const f = $("#ag-input");
  f.value = `Sobre este ${what} que aparece en ${fmt(it.start)}:\n${it.text}\n\n`;
  if (typeof fitAgentInput === "function") fitAgentInput();
  f.focus();
  f.setSelectionRange(f.value.length, f.value.length);
}

function hitBar(it) {
  const label = HIT_LABEL[it.kind] || "Texto";
  return el("div", { class: "sh-bar" },
    el("button", { type: "button", title: `Copiar ${label.toLowerCase()}`, on: { click: (e) => { e.stopPropagation(); copyText(hitText(it), label); } } },
      icon("copy"), "Copiar"),
    it.kind === "link" ? el("button", { type: "button", title: "Abrir el enlace", on: { click: (e) => {
      e.stopPropagation(); window.open(/^https?:/i.test(it.text) ? it.text : `https://${it.text}`, "_blank", "noopener");
    } } }, icon("external"), "Abrir") : null,
    el("button", { type: "button", title: "Preguntarle al agente sobre esto", on: { click: (e) => { e.stopPropagation(); askAgentAbout(it); } } },
      icon("agent"), "Preguntar a Lumi"));
}

function renderHits() {
  const all = screenText.all || [];
  const t = vEn.currentTime;
  for (const layer of stLayers()) {
    const v = layer.parentElement.querySelector("video");
    const rect = v && videoRect(v);
    let box = layer.parentElement.querySelector(":scope > .st-hits");
    if (!box) {
      box = el("div", { class: "st-hits" });
      layer.after(box);
    }
    if (!rect || prefs.screen_text === false) { box.replaceChildren(); continue; }
    const on = prefs.screen_text !== false && state.translates;
    const now = all.filter((it) => it.start <= t && t < it.end && !(on && it.translation));
    const sig = now.map((it) => it.id).join(",") + `@${Math.round(rect.width)}x${Math.round(rect.height)}`;
    if (box.dataset.sig === sig) continue;
    box.dataset.sig = sig;
    box.replaceChildren(...now.map((it) => {
      const [x, y, w, h] = it.box;
      const hit = el("div", { class: "st-hit", "data-id": it.id, tabindex: "0",
        style: `left:${rect.left + x * rect.width}px; top:${rect.top + y * rect.height}px; width:${w * rect.width}px; height:${h * rect.height}px`,
        on: { click: (e) => { e.stopPropagation(); hit.classList.toggle("pinned"); } } }, hitBar(it));
      hit._item = it;
      return hit;
    }));
  }
}

/* el recuadro que se desliza: uno por video; al pasar el mouse de un texto a otro se mueve y cambia de tamaño
   (como un foco que va de uno a otro); al salir de todos se desvanece. Aparece en su lugar, sin venir de lejos. */
let glideHide = 0;
function glideTo(target) {
  const screen = target.closest(".screen") || target.parentElement?.parentElement;
  if (!screen) return;
  let g = screen.querySelector(":scope > .sh-glide");
  if (!g) { g = el("div", { class: "sh-glide", "aria-hidden": "true" }); screen.append(g); }
  clearTimeout(glideHide);
  const sr = screen.getBoundingClientRect(), r = target.getBoundingClientRect();
  const pad = 4;
  const pos = { left: r.left - sr.left - pad, top: r.top - sr.top - pad, width: r.width + pad * 2, height: r.height + pad * 2 };
  const fresh = !g.classList.contains("on");
  if (fresh) g.classList.add("still");  // primera vez: aparece ahí mismo
  for (const [k, v] of Object.entries(pos)) g.style[k] = `${v}px`;
  if (fresh) { g.getBoundingClientRect(); g.classList.remove("still"); }
  g.classList.add("on");
}
function glideOff() {
  clearTimeout(glideHide);
  glideHide = setTimeout(() => document.querySelectorAll(".sh-glide.on").forEach((g) => g.classList.remove("on")), 90);
}
document.addEventListener("pointerover", (e) => {
  const t = e.target.closest?.(".st-hit, .st-item");
  if (t) glideTo(t);
});
document.addEventListener("pointerout", (e) => {
  const from = e.target.closest?.(".st-hit, .st-item");
  const to = e.relatedTarget?.closest?.(".st-hit, .st-item");
  if (from && !to) glideOff();
});
