"use strict";
// Acceso (vt/auth.py), API (vt/api.py) y webhooks (vt/webhooks.py):
//   · inicio de sesión (dueño desde otro equipo, o una biblioteca con contraseña)
//   · vista de invitado: sin lo que no puede hacer (body.guest / body.can-import)
//   · Preferencias → Acceso y API: contraseña, red local, acceso por biblioteca, claves y webhooks
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
}

/* ------------------------------------------------------------ inicio de sesión */
let loginFor = "";  // "" = dueño · id = biblioteca con contraseña
function showLogin(m, asOwner = false) {
  const lockVault = !asOwner && m.asked && m.asked_mode === "clave";
  loginFor = lockVault ? m.asked : "";
  $("#login-title").textContent = lockVault ? m.asked_name : "Entrar";
  $("#login-sub").textContent = lockVault ? "Esta biblioteca pide contraseña."
    : m.owner_set ? "Contraseña del dueño."
    : m.asked && m.asked_mode === "privada" ? "Esta biblioteca es privada."
    : "Desde otro equipo se entra con la contraseña del dueño, y aún no hay una: ponla en Preferencias → Acceso y API desde el equipo donde corre la app.";
  $("#login-form").hidden = !lockVault && !m.owner_set;
  $("#login-err").textContent = "";
  $("#login-pw").value = "";
  const pub = (m.public || []).filter((v) => v.id !== m.asked);
  $("#login-public").replaceChildren(...(pub.length ? [el("h4", { text: "Bibliotecas públicas" }),
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
  $("#login-err").textContent = "Contraseña incorrecta.";
  $("#login-pw").select();
});
$("#login-owner").addEventListener("click", () => showLogin(state.access, true));
$("#login-back").addEventListener("click", hideLogin);
$("#login-btn").addEventListener("click", () => showLogin({ ...state.access, asked: null }, true));

/* ------------------------------------------------------------ utilidades */
const fill = (box, ...kids) => box.replaceChildren(...kids.filter(Boolean));
function copyText(text, what = "Copiado") {
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
const copyBtn = (text, label = "Copiar", what = "Copiado") =>
  btn(label, { icon: "copy", size: "xs", variant: "ghost", onClick: () => copyText(text, what) });
const segsOf = (opts, cur, pick) => el("div", { class: "segs" }, ...opts.map(([v, t]) =>
  el("button", { type: "button", class: "seg" + (cur === v ? " on" : ""), on: { click: () => pick(v) } }, t)));
const ago = (t) => {
  if (!t) return "nunca";
  const s = Date.now() / 1000 - t;
  return s < 90 ? "hace un momento" : s < 3600 ? `hace ${Math.round(s / 60)} min` : s < 86400 ? `hace ${Math.round(s / 3600)} h`
    : new Date(t * 1000).toLocaleDateString("es", { day: "numeric", month: "short" });
};
function baseUrl() {
  const a = state.admin;
  return a && a.network && a.urls.length && ["localhost", "127.0.0.1"].includes(location.hostname) ? a.urls[0] : location.origin;
}

/* ------------------------------------------------------------ Preferencias → Acceso y API */
const accBlock = (id, label) => el("div", { class: "pref acc", id }, el("span", { class: "pref-label", text: label }), el("div", { class: "pref-ctl" }));
const ACC = {
  owner: accBlock("pref-acc-owner", "Contraseña del dueño"),
  net: accBlock("pref-acc-net", "Acceso desde otros equipos"),
  libs: accBlock("pref-acc-libs", "Quién entra a cada biblioteca"),
  keys: accBlock("pref-acc-keys", "Claves de API"),
  hooks: accBlock("pref-acc-hooks", "Webhooks"),
};
const ACC_NAV = [["owner", "Contraseña"], ["net", "Otros equipos"], ["libs", "Bibliotecas"], ["keys", "Claves de API"], ["hooks", "Webhooks"]];
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
  const pw = el("input", { class: "input", type: "password", placeholder: a.owner_set ? "Nueva contraseña" : "Contraseña (mín. 6)",
    autocomplete: "new-password", minlength: 6 });
  const form = el("form", { class: "inline-form", on: { submit: (e) => {
    e.preventDefault();
    if (pw.value.length < 6) return toast("La contraseña debe tener al menos 6 caracteres.", "warn");
    send({ type: "admin_owner_pw", password: pw.value });
    toast("Contraseña del dueño guardada.", "ok");
  } } }, pw, btn(a.owner_set ? "Cambiar" : "Guardar", { type: "submit", icon: "check", variant: "dark" }));
  fill(ctl, 
    el("small", { class: "label", text: a.owner_set ? "Desde este equipo entras sin contraseña; desde otros, con esta."
      : "Sin contraseña, solo se entra como dueño desde este equipo." }),
    form,
    el("div", { class: "acts" },
      a.owner_set ? btn("Quitar contraseña", { icon: "x", variant: "ghost", onClick: async () => {
        if (await confirmDlg("¿Quitar la contraseña del dueño?", "Desde otros equipos ya no se podrá entrar como dueño.", "Quitar")) {
          send({ type: "admin_owner_pw", password: "" });
        }
      } }) : null,
      !state.access.local ? btn("Cerrar sesión", { icon: "external", variant: "ghost", onClick: async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        location.reload();
      } }) : null));
}

function renderAccNet(ctl) {
  const a = state.admin;
  fill(ctl, 
    segsOf([[true, "Sí"], [false, "No"]], a.network, (on) => send({ type: "admin_network", on })),
    a.network ? el("div", { class: "acc-urls" }, ...(a.urls.length ? a.urls.map((u) => el("div", { class: "acc-url" },
      el("code", { text: u }), copyBtn(u, "Copiar", "Dirección copiada")))
      : [el("small", { class: "label", text: "No se encontró una red local." })])) : null,
    el("small", { class: "label", text: a.network
      ? "Otros equipos y celulares de tu misma red entran con esta dirección. Para entrar desde internet, usa un túnel (p. ej. Cloudflare Tunnel) hacia el puerto " + a.port + "."
      : "Solo este equipo puede abrir la app." }));
}

function renderAccLibs(ctl) {
  const modes = [["privada", "Solo yo"], ["clave", "Con contraseña"], ["publica", "Pública"]];
  const perms = [["ver", "Solo ver"], ["importar", "Ver e importar"]];
  fill(ctl, el("div", { class: "vrows" }, ...vaults.list.map((v) => {
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
      placeholder: acc.has_pw ? "Cambiar la contraseña" : "Contraseña de la biblioteca" });
    const link = `${baseUrl()}/b/${v.id}`;
    return el("div", { class: "vrow acc-lib" },
      vaultBadge(v, "lg"),
      el("div", { class: "vinfo" },
        el("strong", { text: v.name }),
        segsOf(modes, draft.mode, (mode) => apply(mode, draft.perm)),
        draft.mode !== "privada" ? segsOf(perms, draft.perm, (perm) => apply(draft.mode, perm)) : null,
        draft.mode === "clave" ? el("form", { class: "inline-form", on: { submit: (e) => {
          e.preventDefault();
          if (!pw.value) return pw.focus();
          apply("clave", draft.perm, pw.value);
          toast(`Contraseña de «${v.name}» guardada.`, "ok");
        } } }, pw, btn(acc.has_pw ? "Cambiar" : "Guardar", { type: "submit", icon: "check" })) : null,
        draft.mode !== "privada" && acc.mode === draft.mode
          ? el("div", { class: "acc-url" }, el("code", { text: link }), copyBtn(link, "Copiar enlace", "Enlace copiado")) : null));
  })));
}

function renderAccKeys(ctl) {
  const a = state.admin;
  const name = el("input", { class: "input", type: "text", placeholder: "Nombre (p. ej. n8n, mi script)", maxlength: 60 });
  const scope = el("select", { class: "select", "data-deco": "vault" }, el("option", { value: "all", text: "Todas las bibliotecas" }),
    ...vaults.list.map((v) => el("option", { value: v.id, text: v.name })));
  const d = accDraft.key ||= { perm: "lectura" };
  const rows = a.keys.map((k) => el("div", { class: "acc-row" },
    el("div", { class: "vinfo" }, el("strong", { text: k.name }),
      el("small", { text: `${k.scope === "all" ? "todas" : vaultById(k.scope)?.name || k.scope} · ${k.perm} · usada ${ago(k.used)}` }),
      el("code", { text: k.hint })),
    btn("Revocar", { icon: "trash", size: "xs", variant: "danger", onClick: async () => {
      if (await confirmDlg(`¿Revocar la clave «${k.name}»?`, "Lo que la use dejará de funcionar.", "Revocar")) send({ type: "admin_key_revoke", id: k.id });
    } })));
  fill(ctl, 
    accDraft.newToken ? el("div", { class: "acc-token" },
      el("small", { class: "label", text: "Cópiala ahora: no se vuelve a mostrar." }),
      el("div", { class: "acc-url" }, el("code", { text: accDraft.newToken }), copyBtn(accDraft.newToken, "Copiar", "Clave copiada"),
        btn("Listo", { size: "xs", icon: "check", onClick: () => { accDraft.newToken = null; renderAccKeys(ctl); } }))) : null,
    rows.length ? el("div", { class: "vrows" }, ...rows) : null,
    el("form", { class: "acc-form", on: { submit: (e) => {
      e.preventDefault();
      send({ type: "admin_key_create", name: name.value || "Clave", scope: scope.value, perm: d.perm });
    } } }, name, scope, segsOf([["lectura", "Lectura"], ["escritura", "Escritura"]], d.perm, (perm) => { d.perm = perm; renderAccKeys(ctl); }),
      btn("Crear clave", { type: "submit", icon: "plus", variant: "dark" })),
    el("small", { class: "label" }, "Se usa como ", el("code", { text: "Authorization: Bearer vt_…" }), ". ",
      el("a", { href: "/api.html", target: "_blank", text: "Documentación de la API" })));
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
      el("small", { text: `${h.vault === "all" ? "todas las bibliotecas" : vaultById(h.vault)?.name || h.vault} · `
        + (h.events.length ? `${h.events.length} ${h.events.length === 1 ? "evento" : "eventos"}` : "todos los eventos")
        + (h.active ? "" : " · pausado") }),
      el("code", { text: h.url })),
    el("div", { class: "vacts" },
      btn("Probar", { size: "xs", icon: "spark", onClick: () => { send({ type: "admin_hook_test", id: h.id }); toast("Aviso de prueba enviado.", "ok"); } }),
      copyBtn(h.secret, "Secreto", "Secreto copiado"),
      btn("Editar", { size: "xs", icon: "pencil", variant: "ghost", onClick: () => { accDraft.hook = { ...h }; renderAccHooks(ctl); } }),
      btn("Quitar", { size: "xs", icon: "trash", variant: "danger", onClick: async () => {
        if (await confirmDlg(`¿Quitar el webhook «${h.name}»?`, "", "Quitar")) send({ type: "admin_hook_remove", id: h.id });
      } }))));
  const log = (a.log || []).slice(0, 8);
  fill(ctl, 
    rows.length ? el("div", { class: "vrows" }, ...rows) : null,
    accDraft.hook ? hookForm(ctl, cat) : el("div", { class: "acts" },
      btn("Agregar webhook", { icon: "plus", variant: "dark", onClick: () => { accDraft.hook = { events: [], vault: "all", active: true }; renderAccHooks(ctl); } })),
    log.length ? el("div", { class: "acc-log" }, el("h4", { text: "Últimos envíos" }), ...log.map((x) => el("div", { class: "acc-logrow" + (x.ok ? "" : " bad") },
      el("span", { text: new Date(x.time * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) }),
      el("span", { text: x.event }),
      el("span", { text: x.ok ? `${x.status}` : `${x.status || "sin respuesta"}${x.attempt > 1 ? ` · intento ${x.attempt}` : ""}`, title: x.error || "" })))) : null,
    el("small", { class: "label" }, "Cada aviso es un POST JSON firmado (", el("code", { text: "X-VT-Signature: sha256=…" }),
      ", HMAC con el secreto). ", el("a", { href: "/api.html#webhooks", target: "_blank", text: "Cómo verificarlo" })));
}
function hookForm(ctl, cat) {
  const h = accDraft.hook;
  const name = el("input", { class: "input", type: "text", placeholder: "Nombre", maxlength: 60, value: h.name || "" });
  const url = el("input", { class: "input", type: "url", placeholder: "https://…", value: h.url || "", required: true });
  const scope = el("select", { class: "select", "data-deco": "vault" }, el("option", { value: "all", text: "Todas las bibliotecas" }),
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
    el("label", { class: "acc-ev all" }, all, el("span", { text: "Todos los eventos" })),
    el("div", { class: "acc-evs" }, ...boxes),
    el("label", { class: "acc-ev all" }, active, el("span", { text: "Activo" })),
    el("div", { class: "acts" },
      btn("Guardar webhook", { type: "submit", icon: "check", variant: "dark" }),
      btn("Cancelar", { variant: "ghost", onClick: () => { accDraft.hook = null; renderAccHooks(ctl); } })));
}
function hooksLog(m) {
  if (!state.admin) return;
  state.admin.log = m.log;
  if (!ACC.hooks.contains(document.activeElement)) renderAccHooks(ACC.hooks.querySelector(".pref-ctl"));
}
