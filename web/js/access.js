"use strict";
// Acceso (vt/auth.py), API (vt/api.py) y webhooks (vt/webhooks.py):
//   · inicio de sesión (dueño desde otro equipo, o una biblioteca con contraseña)
//   · vista de invitado: sin lo que no puede hacer (body.guest / body.can-import)
//   · Ajustes → Acceso y API: contraseña, red local, acceso por biblioteca, claves y webhooks
// Usa lo global de app.js, library.js y vaults.js.

state.access = { owner: true, perms: {}, local: true };
state.admin = null;
const LIB_PATH = (location.pathname.match(/^\/b\/([a-z0-9-]+)/) || [])[1] || "";

// ¿puede hacer esto en la biblioteca abierta?  "owner" | "import"
function can(kind) {
  const a = state.access;
  if (a.owner) return true;
  if (kind === "owner") return false;
  const p = a.perms[vaults.current];
  return p === "importar" || p === "escritura";
}
// ¿Se puede pedir este mensaje al servidor? La misma regla que vt/session.py › _allowed, con las listas que manda
// el servidor (owner_only, import_only): lo que no se puede ni se manda, así nadie ve «No tienes permiso…» por algo
// que no pidió. Lo de importar se mide en la biblioteca abierta (el servidor mira la del video; es la misma).
function mayRequest(obj) {
  const a = state.access, t = obj?.type || "";
  if (t === "open" && obj.ephemeral) return !!(a.owner && a.local);  // subtítulos en vivo: el dueño en este equipo
  if (a.owner || !a.owner_only) return true;  // dueño, o aún sin las listas (el servidor decide)
  if (a.owner_only.includes(t) || (a.owner_prefixes || []).some((p) => t.startsWith(p)) || t === "server_restart"
    || (t.startsWith("vault_") && t !== "vault_open")) return false;
  if (t === "vault_open") return !!a.perms[obj.id];
  if (a.import_only.includes(t)) return can("import");
  return true;
}
function applyCan() {
  document.body.classList.toggle("guest", !state.access.owner);
  document.body.classList.toggle("can-import", can("import"));
}

function authUpdate(m) {
  state.access = m;
  applyCan();
  const none = !m.owner && !Object.keys(m.perms || {}).length;
  $("#login-btn").hidden = m.owner || none;
  if (none) showLogin(m);
  else hideLogin();
  if (m.owner) send({ type: "admin_get" });
  else if (currentView() === "prefs") setView("library");  // Ajustes es solo del dueño
}

/* ------------------------------------------------------------ inicio de sesión */
let loginFor = "";  // "" = dueño · id = biblioteca con contraseña
function showLogin(m, asOwner = false) {
  const lockVault = !asOwner && m.asked && m.asked_mode === "clave";
  loginFor = lockVault ? m.asked : "";
  $("#login-title").textContent = lockVault ? m.asked_name : t("Iniciar sesión");
  $("#login-sub").textContent = lockVault ? t("Esta biblioteca requiere contraseña.")
    : m.owner_set ? t("Contraseña de propietario.")
    : m.asked && m.asked_mode === "privada" ? t("Esta biblioteca es privada.")
    : t("Para acceder desde otro equipo se necesita una contraseña de propietario. Configúrala en Ajustes → Acceso y API desde el equipo donde se ejecuta la app.");
  $("#login-form").hidden = !lockVault && !m.owner_set;
  $("#login-err").textContent = "";
  $("#login-pw").value = "";
  const pub = (m.public || []).filter((v) => v.id !== m.asked);
  $("#login-public").replaceChildren(...(pub.length ? [el("h4", { text: t("Bibliotecas públicas") }),
    ...pub.map((v) => el("a", { class: "vitem", href: `/b/${v.id}` }, vaultBadge(v), el("span", { class: "vname", text: v.name })))] : []));
  $("#login-owner").hidden = !lockVault || !m.owner_set;
  $("#login-back").hidden = !(state.access.owner || Object.keys(state.access.perms || {}).length);
  document.body.classList.add("locked");
  $("#login").hidden = false;
  if (!$("#login-form").hidden) $("#login-pw").focus();
}
function hideLogin() {
  document.body.classList.remove("locked");
  $("#login").hidden = true;
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("#login-pw").value, vault: loginFor }) });
  if (r.ok) return location.reload();
  $("#login-err").textContent = t("Contraseña incorrecta");
  $("#login-pw").select();
});
$("#login-owner").addEventListener("click", () => showLogin(state.access, true));
$("#login-back").addEventListener("click", hideLogin);
$("#login-btn").addEventListener("click", () => showLogin({ ...state.access, asked: null }, true));

/* ------------------------------------------------------------ utilidades */
const fill = (box, ...kids) => box.replaceChildren(...kids.filter(Boolean));
function copyAccess(text, what = t("Copiado")) {  // (copyText es la del menú contextual)
  const done = () => toast(`${what}.`, "ok");
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done);
  const ta = el("textarea", { style: "position:fixed;opacity:0" });
  ta.value = text;
  document.body.append(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
  done();
}
const copyBtn = (text, label = t("Copiar"), what = t("Copiado")) =>
  btn(label, { icon: "copy", size: "xs", variant: "ghost", onClick: () => copyAccess(text, what) });
const segsOf = (opts, cur, pick) => el("div", { class: "segs" }, ...opts.map(([v, lbl]) =>
  el("button", { type: "button", class: "seg" + (cur === v ? " on" : ""), on: { click: () => pick(v) } }, lbl)));
const ago = (ts) => {
  if (!ts) return t("nunca");
  const s = Date.now() / 1000 - ts;
  return s < 90 ? t("hace un momento") : s < 3600 ? t("hace {n} min", { n: Math.round(s / 60) })
    : s < 86400 ? t("hace {n} h", { n: Math.round(s / 3600) })
    : new Date(ts * 1000).toLocaleDateString(LOCALE, { day: "numeric", month: "short" });
};
function baseUrl() {
  const a = state.admin;
  return a && a.network && a.urls.length && ["localhost", "127.0.0.1"].includes(location.hostname) ? a.urls[0] : location.origin;
}

/* ------------------------------------------------------------ Ajustes → Acceso y API */
const accBlock = (id, label) => el("div", { class: "pref acc", id }, el("span", { class: "pref-label", text: label }), el("div", { class: "pref-ctl" }));
const ACC = {
  owner: accBlock("pref-acc-owner", t("Contraseña de propietario")),
  net: accBlock("pref-acc-net", t("Acceso desde otros equipos")),
  libs: accBlock("pref-acc-libs", t("Acceso a cada biblioteca")),
  keys: accBlock("pref-acc-keys", t("Claves de API")),
  hooks: accBlock("pref-acc-hooks", "Webhooks"),
};
i18nTrack(ACC);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const ACC_NAV = [["owner", t("Contraseña")], ["net", t("Otros equipos")], ["libs", t("Bibliotecas")], ["keys", t("Claves de API")], ["hooks", "Webhooks"]];
i18nTrack(ACC_NAV);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const accDraft = { pw: {}, key: null, hook: null, newToken: null };

function adminUpdate(m) {
  state.admin = m;
  renderAdmin();
}
function renderAdmin() {
  if (!state.admin) return;
  for (const [k, fn] of [["owner", renderAccOwner], ["net", renderAccNet], ["libs", renderAccLibs], ["keys", renderAccKeys], ["hooks", renderAccHooks]]) {
    if (ACC[k].contains(document.activeElement) && document.activeElement.matches("input, textarea")) continue;  // no borrar lo que se escribe
    fn(ACC[k].querySelector(".pref-ctl"));
  }
}

function renderAccOwner(ctl) {
  const a = state.admin;
  const pw = el("input", { class: "input", type: "password", placeholder: a.owner_set ? t("Nueva contraseña") : t("Contraseña (mín. 6)"),
    autocomplete: "new-password", minlength: 6 });
  const form = el("form", { class: "inline-form", on: { submit: (e) => {
    e.preventDefault();
    if (pw.value.length < 6) return toast(t("La contraseña debe tener al menos 6 caracteres."), "warn");
    send({ type: "admin_owner_pw", password: pw.value });
    toast(t("Contraseña de propietario guardada"), "ok");
  } } }, pw, btn(a.owner_set ? t("Cambiar") : t("Guardar"), { type: "submit", icon: "check", variant: "dark" }));
  fill(ctl, 
    el("small", { class: "label", text: a.owner_set ? t("En este equipo no se solicita. En otros equipos, sí.")
      : t("Sin contraseña, solo este equipo tiene acceso como propietario.") }),
    form,
    el("div", { class: "acts" },
      a.owner_set ? btn(t("Quitar contraseña"), { icon: "x", variant: "ghost", onClick: async () => {
        if (await confirmDlg(t("¿Quitar la contraseña de propietario?"), t("Ya no se podrá acceder como propietario desde otros equipos."), t("Quitar"))) {
          send({ type: "admin_owner_pw", password: "" });
        }
      } }) : null,
      !state.access.local ? btn(t("Cerrar sesión"), { icon: "external", variant: "ghost", onClick: async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        location.reload();
      } }) : null));
}

function renderAccNet(ctl) {
  const a = state.admin;
  fill(ctl, 
    segsOf([[true, t("Sí")], [false, t("No")]], a.network, (on) => send({ type: "admin_network", on })),
    a.network ? el("div", { class: "acc-urls" }, ...(a.urls.length ? a.urls.map((u) => el("div", { class: "acc-url" },
      el("code", { text: u }), copyBtn(u, t("Copiar"), t("Dirección copiada"))))
      : [el("small", { class: "label", text: t("No se encontró una red local.") })])) : null,
    el("small", { class: "label", text: a.network
      ? t("Los equipos y celulares de tu red pueden acceder con esta dirección. Para acceder desde internet, usa un túnel (p. ej., Cloudflare Tunnel) hacia el puerto {port}.", { port: a.port })
      : t("Solo este equipo puede abrir la app.") }));
}

// una fila por biblioteca (elegido 2026-11-14): su patrón asomando en la esquina, el nombre y, a la derecha, el acceso
// en un desplegable (privada, con contraseña o pública y, si no es privada, si los invitados solo ven o importan).
// Debajo, solo cuando hace falta: la contraseña y el enlace para compartir
const ACC_MODE_ICON = { privada: "lock", clave: "key", publica: "globe" };
function renderAccLibs(ctl) {
  const modes = [["privada", t("Privada")], ["clave", t("Con contraseña")], ["publica", t("Pública")]];
  const perms = [["ver", t("Solo ver")], ["importar", t("Ver e importar")]];
  fill(ctl, el("div", { class: "acc-libs" }, ...vaults.list.map((v) => {
    const acc = v.access || { mode: "privada", perm: "ver" };
    const draft = accDraft.pw[v.id] || { mode: acc.mode, perm: acc.perm };
    const apply = (mode, perm, password = "") => {
      if (mode === "clave" && !acc.has_pw && !password) {  // primero la contraseña
        accDraft.pw[v.id] = { mode, perm };
        return renderAccLibs(ctl);
      }
      delete accDraft.pw[v.id];
      send({ type: "admin_vault_access", id: v.id, mode, perm, password });
    };
    const pw = el("input", { class: "input", type: "password", autocomplete: "new-password",
      placeholder: acc.has_pw ? t("Cambiar la contraseña") : t("Contraseña de la biblioteca") });
    const link = `${baseUrl()}/b/${v.id}`;
    const modeName = Object.fromEntries(modes)[draft.mode];
    const permName = draft.mode !== "privada" ? Object.fromEntries(perms)[draft.perm] : "";
    const pick = btn([modeName, permName].filter(Boolean).join(" · "), { icon: ACC_MODE_ICON[draft.mode] || "lock", size: "sm", cls: "acc-pick",
      onClick: (e) => openMenu([
        ...modes.map(([k, name]) => ({ label: name, icon: ACC_MODE_ICON[k], check: draft.mode === k, onClick: () => apply(k, draft.perm) })),
        draft.mode !== "privada" && "sep",
        ...(draft.mode !== "privada" ? perms.map(([k, name]) => ({ label: name, check: draft.perm === k, onClick: () => apply(draft.mode, k) })) : []),
      ].filter(Boolean), e.currentTarget.getBoundingClientRect()) });
    const extra = [
      draft.mode === "clave" ? el("form", { class: "inline-form", on: { submit: (e) => {
        e.preventDefault();
        if (!pw.value) return pw.focus();
        apply("clave", draft.perm, pw.value);
        toast(t("Contraseña de «{name}» guardada", { name: v.name }), "ok");
      } } }, pw, btn(acc.has_pw ? t("Cambiar") : t("Guardar"), { type: "submit", icon: "check" })) : null,
      draft.mode !== "privada" && acc.mode === draft.mode
        ? el("div", { class: "acc-url" }, el("code", { text: link }), copyBtn(link, t("Copiar enlace"), t("Enlace copiado"))) : null,
    ].filter(Boolean);
    const n = v.count ?? 0;
    return el("div", { class: "acc-lib" },
      el("div", { class: "acc-lib-row" },
        vaultAscii(v, 44, 7, "corner"),
        vaultBadge(v, "md"),
        el("div", { class: "vinfo" }, el("strong", { text: v.name }), el("small", { text: n === 1 ? t("1 video") : t("{n} videos", { n }) })),
        pick),
      extra.length ? el("div", { class: "acc-lib-extra" }, ...extra) : null);
  })));
}

function renderAccKeys(ctl) {
  const a = state.admin;
  const name = el("input", { class: "input", type: "text", placeholder: t("Nombre (p. ej. n8n, mi script)"), maxlength: 60 });
  const scope = el("select", { class: "select", "data-deco": "vault" }, el("option", { value: "all", text: t("Todas las bibliotecas") }),
    ...vaults.list.map((v) => el("option", { value: v.id, text: v.name })));
  const d = accDraft.key ||= { perm: "lectura" };
  const rows = a.keys.map((k) => el("div", { class: "acc-row" },
    el("div", { class: "vinfo" }, el("strong", { text: k.name }),
      el("small", { text: `${k.scope === "all" ? t("todas") : vaultById(k.scope)?.name || k.scope} · ${k.perm === "lectura" ? t("lectura") : k.perm === "escritura" ? t("escritura") : k.perm} · ${t("usada {when}", { when: ago(k.used) })}` }),
      el("code", { text: k.hint })),
    btn(t("Revocar"), { icon: "trash", size: "xs", variant: "danger", onClick: async () => {
      if (await confirmDlg(t("¿Revocar la clave «{name}»?", { name: k.name }), t("Las apps y scripts que la usen dejarán de funcionar."), t("Revocar"))) send({ type: "admin_key_revoke", id: k.id });
    } })));
  fill(ctl, 
    accDraft.newToken ? el("div", { class: "acc-token" },
      el("small", { class: "label", text: t("Cópiala ahora. No se volverá a mostrar.") }),
      el("div", { class: "acc-url" }, el("code", { text: accDraft.newToken }), copyBtn(accDraft.newToken, t("Copiar"), t("Clave copiada")),
        btn(t("Listo"), { size: "xs", icon: "check", onClick: () => { accDraft.newToken = null; renderAccKeys(ctl); } }))) : null,
    rows.length ? el("div", { class: "vrows" }, ...rows) : emptyState("lock", t("Sin claves de API"),
      t("Crea una para que tus scripts o n8n lean la biblioteca o importen videos.")),
    el("form", { class: "acc-form", on: { submit: (e) => {
      e.preventDefault();
      send({ type: "admin_key_create", name: name.value || t("Clave"), scope: scope.value, perm: d.perm });
    } } }, name, scope, segsOf([["lectura", t("Lectura")], ["escritura", t("Escritura")]], d.perm, (perm) => { d.perm = perm; renderAccKeys(ctl); }),
      btn(t("Crear clave"), { type: "submit", icon: "plus", variant: "dark" })),
    el("small", { class: "label" }, t("Se usa como {header}.", { header: "Authorization: Bearer vt_…" }), " ",
      el("a", { href: "/api.html", target: "_blank", text: t("Documentación de la API") })));
}
function keyCreated(m) {
  accDraft.newToken = m.token;
  renderAccKeys(ACC.keys.querySelector(".pref-ctl"));
}

function renderAccHooks(ctl) {
  const a = state.admin;
  const cat = a.catalog || {};
  const rows = a.hooks.map((h) => el("div", { class: "acc-row" + (h.active ? "" : " off") },
    el("div", { class: "vinfo" },
      el("strong", { text: h.name }),
      el("small", { text: `${h.vault === "all" ? t("todas las bibliotecas") : vaultById(h.vault)?.name || h.vault} · `
        + (h.events.length ? (h.events.length === 1 ? t("1 evento") : t("{n} eventos", { n: h.events.length })) : t("todos los eventos"))
        + (h.active ? "" : ` · ${t("pausado")}`) }),
      el("code", { text: h.url })),
    el("div", { class: "vacts" },
      btn(t("Probar"), { size: "xs", icon: "spark", onClick: () => { send({ type: "admin_hook_test", id: h.id }); toast(t("Webhook de prueba enviado"), "ok"); } }),
      copyBtn(h.secret, t("Secreto"), t("Secreto copiado")),
      btn(t("Editar"), { size: "xs", icon: "pencil", variant: "ghost", onClick: () => { accDraft.hook = { ...h }; renderAccHooks(ctl); } }),
      btn(t("Quitar"), { size: "xs", icon: "trash", variant: "danger", onClick: async () => {
        if (await confirmDlg(t("¿Quitar el webhook «{name}»?", { name: h.name }), "", t("Quitar"))) send({ type: "admin_hook_remove", id: h.id });
      } }))));
  const log = (a.log || []).slice(0, 8);
  fill(ctl, 
    rows.length ? el("div", { class: "vrows" }, ...rows) : accDraft.hook ? null : emptyState("external", t("Sin webhooks"),
      t("Notifica a otras apps cuando un video se importa, se traduce o se exporta.")),
    accDraft.hook ? hookForm(ctl, cat) : el("div", { class: "acts" },
      btn(t("Agregar webhook"), { icon: "plus", variant: "dark", onClick: () => { accDraft.hook = { events: [], vault: "all", active: true }; renderAccHooks(ctl); } })),
    log.length ? el("div", { class: "acc-log" }, el("h4", { text: t("Últimos envíos") }), ...log.map((x) => el("div", { class: "acc-logrow" + (x.ok ? "" : " bad") },
      el("span", { text: new Date(x.time * 1000).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" }) }),
      el("span", { text: x.event }),
      el("span", { text: x.ok ? `${x.status}` : `${x.status || t("sin respuesta")}${x.attempt > 1 ? ` · ${t("intento {n}", { n: x.attempt })}` : ""}`, title: x.error || "" })))) : null,
    el("small", { class: "label" }, t("Cada aviso es un POST JSON firmado ({header}, HMAC con el secreto).", { header: "X-VT-Signature: sha256=…" }), " ",
      el("a", { href: "/api.html#webhooks", target: "_blank", text: t("Cómo verificarlo") })));
}
function hookForm(ctl, cat) {
  const h = accDraft.hook;
  const name = el("input", { class: "input", type: "text", placeholder: t("Nombre"), maxlength: 60, value: h.name || "" });
  const url = el("input", { class: "input", type: "url", placeholder: "https://…", value: h.url || "", required: true });
  const scope = el("select", { class: "select", "data-deco": "vault" }, el("option", { value: "all", text: t("Todas las bibliotecas") }),
    ...vaults.list.map((v) => el("option", { value: v.id, text: v.name })));
  scope.value = h.vault || "all";
  const all = el("input", { class: "check", type: "checkbox", checked: !h.events.length });
  const boxes = Object.entries(cat).map(([k, t]) => {
    const c = el("input", { class: "check", type: "checkbox", value: k, checked: h.events.includes(k) });
    c.addEventListener("change", () => { all.checked = false; });
    return el("label", { class: "acc-ev" }, c, el("span", { text: t }), el("code", { text: k }));
  });
  all.addEventListener("change", () => { if (all.checked) for (const b of boxes) b.querySelector("input").checked = false; });
  const active = el("input", { class: "check", type: "checkbox", checked: h.active !== false });
  return el("form", { class: "acc-hook", on: { submit: (e) => {
    e.preventDefault();
    const events = all.checked ? [] : boxes.map((b) => b.querySelector("input")).filter((c) => c.checked).map((c) => c.value);
    send({ type: "admin_hook_save", hook: { id: h.id, name: name.value, url: url.value, vault: scope.value, events, active: active.checked } });
    accDraft.hook = null;
  } } },
    el("div", { class: "acc-form" }, name, url, scope),
    el("label", { class: "acc-ev all" }, all, el("span", { text: t("Todos los eventos") })),
    el("div", { class: "acc-evs" }, ...boxes),
    el("label", { class: "acc-ev all" }, active, el("span", { text: t("Activo") })),
    el("div", { class: "acts" },
      btn(t("Guardar webhook"), { type: "submit", icon: "check", variant: "dark" }),
      btn(t("Cancelar"), { variant: "ghost", onClick: () => { accDraft.hook = null; renderAccHooks(ctl); } })));
}
function hooksLog(m) {
  if (!state.admin) return;
  state.admin.log = m.log;
  if (!ACC.hooks.contains(document.activeElement)) renderAccHooks(ACC.hooks.querySelector(".pref-ctl"));
}
