"use strict";
// Preferencias → Rendimiento (vt/perf.py): tu equipo, el perfil, los límites y los avisos.
// Usa lo global de app.js (send, prefs, toast, PREF_BLOCKS…).

const perf = { data: null, minutes: 10, timer: null };

const PERF_HW = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: "Tu equipo" }), el("div", { class: "pref-ctl" }));
const PERF_PROFILE = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: "Perfil" }), el("div", { class: "pref-ctl" }));
const PERF_LIMITS = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: "Límites" }), el("div", { class: "pref-ctl" }));
const PERF_ALERTS = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: "Avisos" }), el("div", { class: "pref-ctl" }));

const gb = (mb) => (mb >= 1024 ? `${(mb / 1024).toFixed(mb % 1024 ? 1 : 0).replace(".", ",")} GB` : `${mb} MB`);
const STATE_ICON = { bien: "check", limite: "clock", forzado: "up", "muy-forzado": "x" };

function perfStart() {
  if (!can("owner")) return;
  send({ type: "perf_get" });
  clearInterval(perf.timer);
  // mientras se mira la página, los avisos en vivo se actualizan solos
  perf.timer = setInterval(() => {
    if (currentView() === "prefs" && lib.prefSec === "rendimiento") send({ type: "perf_get" });
    else clearInterval(perf.timer);
  }, 6000);
}

function chip(ic, main, sub) {
  return el("div", { class: "hwchip" }, el("span", { class: "hwchip-ic" }, icon(ic)),
    el("div", {}, el("strong", { text: main }), sub ? el("small", { text: sub }) : null));
}

function renderPerf() {
  const d = perf.data;
  if (!d) return;
  const hw = d.hardware;
  const g = hw.gpu;
  // ---------------------------------------------------------------- equipo
  PERF_HW.querySelector(".pref-ctl").replaceChildren(el("div", { class: "hwchips" },
    chip("monitor", g ? g.name.replace(/^NVIDIA (GeForce )?/, "") : "Sin GPU NVIDIA",
      g ? `${gb(g.vram_total_mb)} de VRAM · ${gb(g.vram_free_mb || 0)} libres` : "Se usa la CPU"),
    chip("library", `${gb(hw.ram.total_mb || 0)} de RAM`, `${gb(hw.ram.available_mb || 0)} libres ahora`),
    chip("spark", hw.cpu.name.replace(/\(R\)|\(TM\)|CPU|@.*$/g, "").replace(/\s+/g, " ").trim(),
      `${hw.cpu.cores} núcleos · ${hw.cpu.usable_threads} hilos`)));

  // ---------------------------------------------------------------- perfil
  const rec = d.profiles.find((p) => p.id === d.recommended);
  const card = (id, title, p, extra) => {
    const on = d.choice === id;
    const b = el("button", { type: "button", class: "pcard" + (on ? " on" : ""),
      on: { click: () => send({ type: "perf_set", profile: id }) } },
      el("div", { class: "pcard-head" }, el("strong", { text: title }),
        p ? el("span", { class: `pstate ${p.state}` }, icon(STATE_ICON[p.state]), p.state_label) : null),
      el("p", { text: extra || p.desc }),
      p ? el("div", { class: "pcard-facts" },
        el("span", {}, icon("clock"), p.speed ? `${perf.minutes} min de video → ~${fmtMinutes(perf.minutes / p.speed + (p.minutes_per_10 - 10 / p.speed))}` : "—"),
        el("span", {}, icon(p.live ? "play" : "x"), p.live ? (p.wait_s ? `En vivo, empieza en ~${Math.ceil(p.wait_s)} s` : "En vivo") : "Solo en la cola"),
        el("span", {}, icon(p.voice ? "speaker" : "comment"), p.voice ? "Con voz en español" : "Solo subtítulos")) : null,
      d.active === id ? el("span", { class: "pcard-tag", text: "En uso" }) : null);
    return b;
  };
  const cards = [card("auto", "Automático", rec, `Elige solo según tu equipo: ahora, «${rec.name}».`),
    ...d.profiles.map((p) => card(p.id, p.name, p))];
  const restart = d.wanted !== d.active
    ? el("div", { class: "perf-apply" }, el("span", { text: `Para usar «${d.profiles.find((p) => p.id === d.wanted).name}» hay que reiniciar Translay (se cargan otros modelos).` }),
      btn("Reiniciar ahora", { icon: "reload", variant: "dark", size: "sm", onClick: async () => {
        if (await confirmDlg("¿Reiniciar Translay?", "Lo que se esté procesando se retoma solo al volver. Tarda unos segundos.", "Reiniciar")) {
          send({ type: "server_restart" });
        }
      } }))
    : null;
  const mins = el("select", { class: "select", "aria-label": "Largo del video" },
    ...[5, 10, 30, 60, 120].map((n) => el("option", { value: n, text: `${n} min`, selected: n === perf.minutes })));
  mins.addEventListener("change", () => { perf.minutes = Number(mins.value); renderPerf(); });
  PERF_PROFILE.querySelector(".pref-ctl").replaceChildren(...[
    el("div", { class: "perf-calc" }, el("span", { text: "Tiempos para un video de" }), mins),
    el("div", { class: "pcards" }, ...cards), restart,
    Object.keys(d.cli || {}).length ? el("small", { class: "label", text: `Por línea de comandos se fijó: ${Object.entries(d.cli).map(([k, v]) => `${k} ${v}`).join(", ")} (gana sobre el perfil).` }) : null].filter(Boolean));

  // ---------------------------------------------------------------- límites
  const limitRow = (key, title, desc, total, fmt, opts) => {
    const sel = el("select", { class: "select", "aria-label": title },
      el("option", { value: 0, text: "Sin límite", selected: !d.limits[key] }),
      ...opts.filter((n) => n && (!total || n < total)).map((n) => el("option", { value: n, text: fmt(n), selected: d.limits[key] === n })));
    sel.addEventListener("change", () => send({ type: "perf_set", [key]: Number(sel.value) }));
    return el("div", { class: "set-row" },
      el("div", { class: "set-text" }, el("strong", { text: title }), el("p", { text: desc })),
      el("div", { class: "set-ctl" }, sel));
  };
  const opt = (k) => (prefsSchema.find((p) => p.key === k)?.options || []).map(([v]) => v);
  PERF_LIMITS.querySelector(".pref-ctl").replaceChildren(el("div", { class: "set-rows" }, ...[
    g ? limitRow("vram_mb", "VRAM", `Cuánta memoria de la GPU puede usar Translay (tiene ${gb(g.vram_total_mb)}). El perfil automático elige modelos que entren.`,
      g.vram_total_mb, gb, opt("limit_vram_mb")) : null,
    limitRow("ram_mb", "RAM", `Tope de memoria para Translay y su proceso de voz (el equipo tiene ${gb(hw.ram.total_mb || 0)}). Lo que no entra se pasa al disco.`,
      hw.ram.total_mb, gb, opt("limit_ram_mb")),
    limitRow("threads", "Hilos de la CPU", `Cuántos hilos puede usar (tiene ${hw.cpu.threads}). Deja el resto libre para otros programas.`,
      hw.cpu.threads + 1, (n) => `${n} ${n === 1 ? "hilo" : "hilos"}`, opt("limit_threads"))].filter(Boolean)));

  // ---------------------------------------------------------------- avisos
  const al = d.alerts || [];
  PERF_ALERTS.querySelector(".pref-ctl").replaceChildren(al.length
    ? el("div", { class: "alerts" }, ...al.map((a) => el("div", { class: `alert ${a.level}` },
      icon(a.level === "bad" ? "x" : a.level === "info" ? "reload" : "clock"), el("span", { text: a.text }))))
    : el("div", { class: "alert ok" }, icon("check"), el("span", { text: d.live.tts_count
      ? `Todo en orden: la voz tarda ~${d.live.tts_p50} s por frase.` : "Todo en orden para este equipo." })));
}

function fmtMinutes(m) {
  if (m < 1) return "menos de 1 min";
  if (m < 90) return `${Math.round(m)} min`;
  return `${(m / 60).toFixed(1).replace(".", ",")} h`;
}

// mensajes del servidor (web/js/app.js · onMessage)
function perfUpdate(m) {
  perf.data = m;
  if (currentView() === "prefs" && lib.prefSec === "rendimiento") renderPerf();
}
function restarting() {
  toast("Reiniciando Translay: vuelve solo en unos segundos.", "warn");
}
