"use strict";
// Ajustes → Rendimiento (vt/perf.py): tu equipo, el perfil, los límites y los avisos.
// Usa lo global de app.js (send, prefs, toast, PREF_BLOCKS…).

const perf = { data: null, minutes: 10, timer: null };

const PERF_HW = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: t("Tu equipo") }), el("div", { class: "pref-ctl" }));
i18nTrack(PERF_HW);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const PERF_PROFILE = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: t("Perfil") }), el("div", { class: "pref-ctl" }));
i18nTrack(PERF_PROFILE);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const PERF_LIMITS = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: t("Límites") }), el("div", { class: "pref-ctl" }));
i18nTrack(PERF_LIMITS);  // al cambiar de idioma, sus textos también cambian (i18n.js)
const PERF_ALERTS = el("div", { class: "pref perf-pref" }, el("span", { class: "pref-label", text: t("Avisos") }), el("div", { class: "pref-ctl" }));
i18nTrack(PERF_ALERTS);  // al cambiar de idioma, sus textos también cambian (i18n.js)

const gb = (mb) => (mb >= 1024 ? `${(mb / 1024).toLocaleString(LOCALE, { minimumFractionDigits: mb % 1024 ? 1 : 0, maximumFractionDigits: mb % 1024 ? 1 : 0 })} GB` : `${mb} MB`);
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
    el("div", {}, el("strong", { text: main, title: main }), sub ? el("small", { text: sub }) : null));
}

function renderPerf() {
  const d = perf.data;
  if (!d) return;
  const hw = d.hardware;
  const g = hw.gpu;
  // ---------------------------------------------------------------- equipo
  PERF_HW.querySelector(".pref-ctl").replaceChildren(el("div", { class: "hwchips" },
    chip("monitor", g ? g.name.replace(/^NVIDIA (GeForce )?/, "") : t("Sin GPU NVIDIA"),
      g ? (g.unified ? t("{total} de memoria unificada · {free} libres", { total: gb(g.vram_total_mb), free: gb(g.vram_free_mb || 0) })
        : t("{total} de VRAM · {free} libres", { total: gb(g.vram_total_mb), free: gb(g.vram_free_mb || 0) }))
        : t("Se usa la CPU")),
    chip("library", t("{size} de RAM", { size: gb(hw.ram.total_mb || 0) }), t("{size} libres ahora", { size: gb(hw.ram.available_mb || 0) })),
    chip("spark", hw.cpu.name.replace(/\(R\)|\(TM\)|CPU|@.*$/g, "").replace(/\s+/g, " ").trim(),
      t("{cores} núcleos · {threads} hilos", { cores: hw.cpu.cores, threads: hw.cpu.usable_threads }))));

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
        el("span", {}, icon("clock"), p.speed ? t("{min} min de video → ~{time}", { min: perf.minutes, time: fmtMinutes(perf.minutes / p.speed + (p.minutes_per_10 - 10 / p.speed)) }) : "—"),
        el("span", {}, icon(p.live ? "play" : "x"), p.live ? (p.wait_s ? t("En vivo, empieza en ~{s} s", { s: Math.ceil(p.wait_s) }) : t("En vivo")) : t("Solo en la cola")),
        el("span", {}, icon(p.voice ? "speaker" : "comment"), p.voice ? t("Con voz en {lang}", { lang: langName(targetLang()) }) : t("Solo subtítulos"))) : null,
      d.active === id ? el("span", { class: "pcard-tag", text: t("En uso") }) : null);
    return b;
  };
  const cards = [card("auto", t("Automático"), rec, t("Se elige automáticamente según tu equipo. Actual: «{name}».", { name: rec.name })),
    ...d.profiles.map((p) => card(p.id, p.name, p))];
  const restart = d.wanted !== d.active
    ? el("div", { class: "perf-apply" }, el("span", { text: t("Para usar «{name}» es necesario reiniciar Translay (se cargan otros modelos).", { name: d.profiles.find((p) => p.id === d.wanted).name }) }),
      btn(t("Reiniciar ahora"), { icon: "reload", variant: "dark", size: "sm",
        onClick: () => send({ type: "perf_plan", profile: d.choice }) }))  // antes, qué hay que bajar (perfPlan)
    : null;
  const mins = el("select", { class: "select", "aria-label": t("Largo del video") },
    ...[5, 10, 30, 60, 120].map((n) => el("option", { value: n, text: t("{n} min", { n }), selected: n === perf.minutes })));
  mins.addEventListener("change", () => { perf.minutes = Number(mins.value); renderPerf(); });
  PERF_PROFILE.querySelector(".pref-ctl").replaceChildren(...[
    el("div", { class: "perf-calc" }, el("span", { text: t("Tiempos para un video de") }), mins),
    el("div", { class: "pcards" }, ...cards), restart,
    Object.keys(d.cli || {}).length ? el("small", { class: "label", text: t("Fijado por línea de comandos: {list} (tiene prioridad sobre el perfil).", { list: Object.entries(d.cli).map(([k, v]) => `${k} ${v}`).join(", ") }) }) : null].filter(Boolean));

  // ---------------------------------------------------------------- límites
  const limitRow = (key, title, desc, total, fmt, opts) => {
    const sel = el("select", { class: "select", "aria-label": title },
      el("option", { value: 0, text: t("Sin límite"), selected: !d.limits[key] }),
      ...opts.filter((n) => n && (!total || n < total)).map((n) => el("option", { value: n, text: fmt(n), selected: d.limits[key] === n })));
    sel.addEventListener("change", () => send({ type: "perf_set", [key]: Number(sel.value) }));
    return el("div", { class: "set-row" },
      el("div", { class: "set-text" }, el("strong", { text: title }), el("p", { text: desc })),
      el("div", { class: "set-ctl" }, sel));
  };
  const opt = (k) => (prefsSchema.find((p) => p.key === k)?.options || []).map(([v]) => v);
  PERF_LIMITS.querySelector(".pref-ctl").replaceChildren(el("div", { class: "set-rows" }, ...[
    g ? limitRow("vram_mb", "VRAM", t("Memoria de la GPU que puede usar Translay (total: {total}). El perfil automático elige modelos compatibles.", { total: gb(g.vram_total_mb) }),
      g.vram_total_mb, gb, opt("limit_vram_mb")) : null,
    limitRow("ram_mb", "RAM", t("Límite de memoria para Translay y su proceso de voz (total: {total}). El exceso se pagina al disco.", { total: gb(hw.ram.total_mb || 0) }),
      hw.ram.total_mb, gb, opt("limit_ram_mb")),
    limitRow("threads", t("Hilos de la CPU"), t("Hilos que puede usar Translay (total: {total}). El resto queda libre para otros programas.", { total: hw.cpu.threads }),
      hw.cpu.threads + 1, (n) => (n === 1 ? t("1 hilo") : t("{n} hilos", { n })), opt("limit_threads"))].filter(Boolean)));

  // ---------------------------------------------------------------- avisos
  const al = d.alerts || [];
  PERF_ALERTS.querySelector(".pref-ctl").replaceChildren(al.length
    ? el("div", { class: "alerts" }, ...al.map((a) => el("div", { class: `alert ${a.level}` },
      icon(a.level === "bad" ? "x" : a.level === "info" ? "reload" : "clock"), el("span", { text: a.text }))))
    : el("div", { class: "alert ok" }, icon("check"), el("span", { text: d.live.tts_count
      ? t("Todo en orden. La voz tarda ~{s} s por frase.", { s: d.live.tts_p50 }) : t("Todo en orden para este equipo.") })));
}

function fmtMinutes(m) {
  if (m < 1) return t("menos de 1 min");
  if (m < 90) return `${Math.round(m)} min`;
  return `${(m / 60).toLocaleString(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} h`;
}

// mensajes del servidor (web/js/app.js · onMessage)
function perfUpdate(m) {
  perf.data = m;
  if (currentView() === "prefs" && lib.prefSec === "rendimiento") renderPerf();
}
function restarting() {
  toast(t("Reiniciando Translay. Estará disponible en unos segundos."), "warn");
}

// Al reiniciar con otro perfil (vt/modelset.py · plan): si le faltan modelos (o, en la app de escritorio, el
// motor de voz), se dice antes qué se baja y cuánto pesa; y se puede borrar lo que el perfil nuevo no usa.
async function perfPlan(m) {
  const needVoiceEnv = DESKTOP && m.voice_env;
  const down = m.missing_bytes + (needVoiceEnv ? m.voice_env_bytes : 0);
  if (!down && !m.unused_bytes) {
    if (await confirmDlg(t("¿Reiniciar Translay?"), t("El procesamiento en curso se reanudará automáticamente. Tarda unos segundos."), t("Reiniciar"))) {
      send({ type: "server_restart" });
    }
    return;
  }
  const dlg = $("#plan-dlg");
  $("#plan-title").textContent = t("Cambiar a «{name}»", { name: m.name });
  $("#plan-sub").textContent = down
    ? (m.missing.length + (needVoiceEnv ? 1 : 0) === 1
      ? t("Se descarga {size} y Translay se reinicia al terminar. Lo que se esté procesando se retoma solo.", { size: fmtBytes(down) })
      : t("Se descargan {size} y Translay se reinicia al terminar. Lo que se esté procesando se retoma solo.", { size: fmtBytes(down) }))
    : t("Translay se reinicia con los modelos de este perfil. El procesamiento en curso se reanudará automáticamente.");
  const row = (ic, title, detail, bytes) => el("div", { class: "trow st-row" }, el("span", { class: "trow-ic" }, icon(ic)),
    el("div", { class: "vinfo" }, el("strong", { text: title }), detail ? el("small", { text: detail }) : null),
    el("div", { class: "vacts" }, el("span", { class: "st-size", text: fmtBytes(bytes) })));
  $("#plan-list").replaceChildren(...[
    needVoiceEnv ? row("speaker", t("Motor de voz"), t("Se instala una sola vez para el doblaje"), m.voice_env_bytes) : null,
    ...m.missing.map((x) => row("download", x.label, x.purpose, x.bytes))].filter(Boolean));
  $("#plan-list").hidden = !down;
  $("#plan-prune-row").hidden = !m.unused_bytes;
  $("#plan-prune").checked = false;
  $("#plan-prune-text").textContent = m.unused.length === 1
    ? t("Borrar el modelo que este perfil no usa ({size})", { size: fmtBytes(m.unused_bytes) })
    : t("Borrar los {n} modelos que este perfil no usa ({size})", { n: m.unused.length, size: fmtBytes(m.unused_bytes) });
  $("#plan-ok").textContent = down ? t("Descargar y reiniciar") : t("Reiniciar");
  dlg.returnValue = "";
  dlg.showModal();
  await new Promise((r) => dlg.addEventListener("close", r, { once: true }));
  if (dlg.returnValue !== "ok") return;
  const prune = $("#plan-prune").checked;
  if (needVoiceEnv) {  // la app de escritorio instala el motor de voz y vuelve a abrir Translay
    send({ type: "perf_prune", on: prune });
    setTimeout(() => desktopCall("reinstall", { voice: true }), 300);
    return;
  }
  send({ type: "server_restart", prune });
}

