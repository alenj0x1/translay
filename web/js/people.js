"use strict";
// Las personas de cada video (nombre y voz) y el glosario de la biblioteca.
// Comparte el ámbito global con app.js (se carga justo después).

/* ------------------------------------------------------------ personas del video */
const escapeHtml = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
// color de la persona n (1, 2…, en orden de aparición): el mismo en la transcripción y en Personas
function whoClass(n) { return `who-${(n - 1) % 5}`; }
function personName(spk, n) { return state.people.names[String(spk)] || `P${n}`; }

// Nombre de cada persona y la voz que usa en español (la suya clonada o la de otra persona)
function renderPeople() {
  updateSideTabs();
  const box = $("#people");
  if (box.hidden) return;
  const order = new Map(), count = new Map();
  for (const s of state.segments) {
    if (s.speaker == null) continue;
    if (!order.has(s.speaker)) order.set(s.speaker, order.size + 1);
    count.set(s.speaker, (count.get(s.speaker) || 0) + 1);
  }
  if (box.contains(document.activeElement)) return;  // no redibujar mientras se escribe un nombre
  const refs = state.people.refs || {};
  const saved = state.peopleSaved || [];
  const savedUrl = (v) => v?.startsWith("p:") ? saved.find((p) => p.id === v.slice(2))?.url : null;
  const names = el("datalist", { id: "people-names" }, ...saved.map((p) => el("option", { value: p.name })));
  const vname = typeof currentVault === "function" ? (vaultById(state.videoVault) || currentVault()).name : t("la biblioteca");
  const rows = [...order].map(([spk, n]) => {
    const key = String(spk);
    const name = el("input", { class: "input", type: "text", maxlength: 60, placeholder: t("Persona {n}", { n }), list: "people-names",
      value: state.people.names[key] || "", "aria-label": t("Nombre de la persona {n}", { n }) });
    name.addEventListener("change", () => send({ type: "people_set", video: state.videoId, spk: key, name: name.value }));
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") name.blur(); });
    const voice = el("select", { class: "select", "aria-label": t("Voz en {lang}", { lang: langName(targetLang()) }) },
      el("option", { value: "", text: refs[key] ? t("Su propia voz") : t("Su voz (aún sin referencia)") }),
      ...[...order].filter(([o]) => o !== spk && refs[String(o)])
        .map(([o, m]) => el("option", { value: String(o), text: t("Voz de {name}", { name: personName(o, m) }) })),
      saved.length ? el("optgroup", { label: t("Guardadas en «{name}»", { name: vname }) },
        ...saved.map((p) => el("option", { value: `p:${p.id}`, text: t("Voz de {name}", { name: p.name }) }))) : null);
    voice.value = state.people.voices[key] || "";
    voice.addEventListener("change", () => send({ type: "people_set", video: state.videoId, spk: key, voice: voice.value }));
    const used = state.people.voices[key] || key;
    const usedUrl = savedUrl(used) || refs[used];
    const listen = usedUrl ? previewBtn(usedUrl, t("Escuchar la voz de referencia")) : null;
    // guardar a esta persona (nombre y su voz) para usarla en otros videos de la biblioteca
    const nm = (state.people.names[key] || "").trim();
    const same = saved.find((p) => p.name.toLowerCase() === nm.toLowerCase() && nm);
    const keep = refs[key] ? btn(same ? t("Actualizar voz") : t("Guardar"), { icon: "bookmark", size: "xs", variant: "ghost", cls: "owner-only",
      title: t("Guardar su nombre y su voz en «{name}»", { name: vname }),
      onClick: () => send({ type: "people_save", video: state.videoId, spk: key, name: nm || t("Persona {n}", { n }), id: same?.id || "" }) }) : null;
    return el("div", { class: "person" },
      el("span", { class: `chip who ${whoClass(n)}`, text: `P${n}` }),
      el("div", { class: "pfields" }, name, voice),
      el("div", { class: "pmeta" }, el("small", { text: count.get(spk) === 1 ? t("1 frase") : t("{n} frases", { n: count.get(spk) }) }),
        el("span", { class: "pacts" }, keep, listen)));
  });
  // las guardadas en la biblioteca (para escucharlas u olvidarlas)
  const kept = saved.length ? el("div", { class: "people-saved" },
    el("h4", { text: t("Guardadas en «{name}»", { name: vname }) }),
    ...saved.map((p) => el("div", { class: "psaved" },
      el("span", { text: p.name }),
      el("span", { class: "pacts" },
        previewBtn(p.url, t("Escuchar esta voz")),
        btn(t("Olvidar"), { icon: "x", size: "xs", variant: "ghost", cls: "owner-only", onClick: async () => {
          if (await confirmDlg(t("¿Olvidar a {name}?", { name: p.name }), t("Los videos que usan esta voz recuperarán la voz original de cada persona al procesarse de nuevo."), t("Olvidar"))) {
            send({ type: "people_forget", id: p.id, vault: state.videoVault });
          }
        } }))))) : null;
  box.replaceChildren(names, ...rows, kept || "");
  if (typeof can === "function" && !can("owner")) {
    for (const x of box.querySelectorAll("input, select")) x.disabled = true;
  }
}

/* ------------------------------------------------------------ glosario */
const GLOSSARY_BLOCK = el("div", { class: "pref glossary", id: "pref-glossary" },
  el("span", { class: "pref-label", text: t("Términos") }), el("div", { class: "pref-ctl" }));
i18nTrack(GLOSSARY_BLOCK);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const glossary = { entries: [], dirty: false };

function glossaryUpdate(entries) {
  glossary.entries = entries || [];
  if (!glossary.dirty) renderGlossary(glossary.entries);
}
function renderGlossary(entries) {
  const ctl = GLOSSARY_BLOCK.querySelector(".pref-ctl");
  const rows = el("div", { class: "grows" });
  const addRow = (e = { src: "", dst: "" }) => {
    const src = el("input", { class: "input", type: "text", maxlength: 120, placeholder: t("Como en el original"), value: e.src });
    const dst = el("input", { class: "input", type: "text", maxlength: 120, placeholder: t("Sin traducir"), value: e.dst });
    const row = el("div", { class: "grow" }, src, el("span", { class: "arrow", text: "→" }), dst,
      btn(t("Quitar"), { icon: "x", size: "xs", variant: "ghost", onClick: () => { row.remove(); glossary.dirty = true; } }));
    for (const i of [src, dst]) i.addEventListener("input", () => { glossary.dirty = true; });
    rows.append(row);
    return src;
  };
  for (const e of entries) addRow(e);
  if (!entries.length) addRow();
  const save = btn(t("Guardar glosario"), { icon: "check", variant: "dark", onClick: () => {
    const items = [...rows.querySelectorAll(".grow")].map((r) => {
      const [a, b] = r.querySelectorAll("input");
      return { src: a.value.trim(), dst: b.value.trim() };
    }).filter((x) => x.src);
    glossary.dirty = false;
    send({ type: "glossary_set", entries: items });
    toast(t("Glosario guardado. Se volverán a traducir las frases afectadas."), "ok");
  } });
  ctl.replaceChildren(rows, el("div", { class: "acts" },
    btn(t("Agregar término"), { icon: "plus", onClick: () => addRow().focus() }), save),
    el("small", { class: "label", text: t("Si la traducción queda vacía, el término se mantiene como en el original (nombres, marcas, siglas).") }));
}
renderGlossary([]);
