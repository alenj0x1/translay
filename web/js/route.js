"use strict";
// Dónde estás, en la dirección (#/…): al recargar se vuelve ahí y atrás/adelante del
// navegador funcionan. Usa lo global de library.js y app.js.
//   #/                       inicio
//   #/c/<colección>          una colección, playlist, canal o categoría
//   #/video/<id>             el reproductor con ese video
//   #/cola                   la pantalla de la Cola
//   #/preferencias/<sección>

const route = { pending: location.hash, restored: false, applying: false };

function routeNow() {
  const view = currentView();
  if (view === "player") return state.videoId && lib.videos[state.videoId] ? `#/video/${encodeURIComponent(state.videoId)}` : "#/";
  if (view === "queue") return "#/cola";
  if (view === "prefs") return lib.prefSec ? `#/preferencias/${encodeURIComponent(lib.prefSec)}` : "#/preferencias";
  return lib.sel && lib.sel !== "home" ? `#/c/${encodeURIComponent(lib.sel)}` : "#/";
}

// se llama después de cada cambio de vista, colección, sección o video
function syncRoute() {
  if (!route.restored || route.applying) return;
  const h = routeNow();
  if (h === (location.hash || "#/")) return;
  history.pushState(null, "", h === "#/" ? location.pathname + location.search : h);
}

function applyRoute(hash) {
  const [, kind, arg] = (hash || "").match(/^#\/([^/]*)\/?(.*)$/) || [];
  const id = arg ? decodeURIComponent(arg) : "";
  route.applying = true;
  try {
    if (kind === "video" && lib.videos[id]) {
      if (state.videoId !== id) playItem(id);
      else setView("player");
    } else if (kind === "cola") {
      setView("queue");
    } else if (kind === "preferencias" && can("owner")) {  // invitados: la biblioteca
      if (id) lib.prefSec = id;
      setView("prefs");
      if (typeof renderPrefs === "function") renderPrefs();
    } else {
      lib.sel = kind === "c" && lib.collections.some((c) => c.id === id) ? id : "home";
      lib.picked.clear();
      if (typeof closeSearch === "function") closeSearch();
      if (currentView() !== "library") setView("library");
      else renderLibrary();
    }
  } finally {
    route.applying = false;
  }
}

// la primera vez que llega la biblioteca: volver a donde se estaba
function routeRestore() {
  if (route.restored) return;
  route.restored = true;
  if (route.pending && route.pending !== "#/") applyRoute(route.pending);
  // un video recién pedido aún se está cargando: su dirección queda igual
  const h = /^#\/video\//.test(route.pending) && currentView() === "player" ? route.pending : routeNow();
  history.replaceState(null, "", h === "#/" ? location.pathname + location.search : h);
}

addEventListener("popstate", () => { if (route.restored) applyRoute(location.hash); });
