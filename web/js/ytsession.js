"use strict";
// La sesión de YouTube para descargar: conectar la cuenta, cookies del navegador o un archivo.
// Comparte el ámbito global con app.js (se carga justo después).

/* ------------------------------------------------------------ sesión de YouTube */
// La cuenta conectada (vt/ytsession.py): se inicia sesión una vez en una ventana del
// navegador con un perfil propio de Translay y desde ahí se renueva sola. O, a mano,
// importarla desde un navegador detectado o subir el cookies.txt exportado.
const ytAcc = { status: null, browser: null };
const canConnectYouTube = (a) => !!a?.available && !!a.browsers?.length && state.access.local && state.access.owner;

function connectYouTube(key = ytAcc.browser || ytAcc.status?.browser || ytAcc.status?.browsers?.[0]?.key) {
  send({ type: "yt_connect", browser: key });
}

function renderAccount(a) {
  ytAcc.status = a;
  const browsers = a.browsers || [];
  if (!browsers.some((b) => b.key === ytAcc.browser)) ytAcc.browser = a.browser && browsers.some((b) => b.key === a.browser)
    ? a.browser : browsers[0]?.key || null;
  const name = (browsers.find((b) => b.key === ytAcc.browser) || {}).name || "";
  const acts = $("#yt-acc-acts"), status = $("#yt-acc-status");
  acts.replaceChildren();
  YT_ACCOUNT.hidden = !a.available;
  if (!a.available) return;
  const busy = { conectando: t("Esperando inicio de sesión…"), renovando: t("Renovando…"), desconectando: t("Desconectando…") }[a.busy];
  if (a.connected && !a.expired) {
    acts.append(btn(busy || t("Desconectar"), { icon: "x", disabled: !!busy || !state.access.local,
      onClick: () => send({ type: "yt_disconnect" }) }));
    status.textContent = t("Conectada con {browser} · renovada {ago}", { browser: a.browser_name, ago: ago(a.renewed) });
    return;
  }
  if (!browsers.length) {
    status.textContent = t("No se encontró un navegador compatible (Brave, Chrome, Edge, Vivaldi o Chromium). Usa «Subir cookies.txt».");
    return;
  }
  const label = busy || (a.expired ? t("Volver a conectar con {name}", { name }) : t("Conectar con {name}", { name }));
  const main = btn(label, { icon: "user", variant: "dark", disabled: !!busy || !state.access.local, onClick: () => connectYouTube() });
  acts.append(main);
  if (browsers.length > 1 && !busy) acts.append(btn(t("Otro navegador"), { icon: "chevron", disabled: !state.access.local,
    onClick: (e) => {
      e.stopPropagation();
      openMenu(browsers.map((b) => ({ label: b.name, check: b.key === ytAcc.browser,
        onClick: () => { ytAcc.browser = b.key; renderAccount(ytAcc.status); } })), e.currentTarget.getBoundingClientRect());
    } }));
  status.textContent = !state.access.local ? t("Solo se puede conectar desde el equipo donde se ejecuta Translay.")
    : a.busy === "conectando" ? t("Inicia sesión en YouTube en la ventana de {name} y ciérrala.", { name })
    : a.expired ? t("La sesión de YouTube expiró") : t("Sin cuenta conectada");
}

function renderCookies(m) {
  if (m.account) renderAccount(m.account);
  if (m.connected_now) toast(t("Cuenta de YouTube conectada. Se usará en las descargas."), "ok");
  if (m.disconnected) toast(t("Cuenta de YouTube desconectada y borrada de este equipo."), "ok");
  if (m.cancelled) toast(t("Se cerró la ventana sin iniciar sesión en YouTube."), "warn");
  const box = $("#yt-browsers");
  box.replaceChildren();
  for (const b of m.browsers) {
    box.append(el("button", { type: "button", class: "btn sm", text: t("Importar de {name}", { name: b.name }), on: { click: () => {
      $("#cookies-status").textContent = t("leyendo la sesión de {name}…", { name: b.name });
      send({ type: "cookies_import", browser: b.key });
    } } }));
  }
  const st = m.status || {};
  $("#cookies-status").textContent = st.present
    ? t("Sesión importada · {count} cookies · {session} · {updated}", { count: st.count, updated: st.updated,
      session: st.logged_in ? t("con sesión iniciada") : t("sin sesión iniciada") })
    : t("Sin sesión importada");
  if (m.error) toast(m.error);
  if (m.imported) {
    const fromFile = m.imported.source === "archivo", source = m.imported.source;
    if (m.imported.logged_in) toast(fromFile ? t("Sesión de YouTube importada del archivo. Se usará en las descargas.")
      : t("Sesión de YouTube importada de {source}. Se usará en las descargas.", { source }), "ok");
    else toast(fromFile ? t("Se importaron cookies del archivo, pero no hay una sesión de YouTube iniciada. Inicia sesión en YouTube y vuelve a importar.")
      : t("Se importaron cookies de {source}, pero no hay una sesión de YouTube iniciada. Inicia sesión en YouTube y vuelve a importar.", { source }), "warn");
  }
}

$("#cookies-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  $("#cookies-status").textContent = t("importando el archivo…");
  try {
    const r = await fetch("/api/cookies", { method: "PUT", body: f });
    if (!r.ok) toast(t("No se pudo importar: {error}", { error: await r.text() }));
  } catch (err) {
    toast(t("No se pudo subir el archivo"));
  }
});
