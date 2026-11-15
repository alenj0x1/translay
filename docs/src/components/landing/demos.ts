// La portada en movimiento: el fondo de caracteres de toda la página (un viaje del logo al fondo del mar), las escenas
// chicas (la estación en órbita del reproductor, la lechuga de la diapositiva) y cada demostración. Usa lo que la app
// deja como globales en la página (Landing.astro las incrusta desde web/js): SCENES, sceneRenderer y scenePalette
// (scenes.js), wordmark (brand.js), starSvg, STAR_PARTS y STAR_DEFAULT (star.js) y asciiField (vaults.js).
/* eslint-disable @typescript-eslint/no-explicit-any */
declare const SCENES: Record<string, (u: number, v: number, t: number, cell: number, A: number) => [number, number] | number[]>;
declare function sceneRenderer(ctx: CanvasRenderingContext2D, make: (w: number, h: number) => HTMLCanvasElement): any;
declare function scenePalette(): { colors: string[]; fade: number };
declare function starSvg(look: any, color?: string | null, cls?: string): SVGSVGElement;
declare const STAR_PARTS: Record<string, [string, string][]>;
declare const STAR_DEFAULT: Record<string, string>;
declare function asciiField(seed: string, cols: number, rows: number): string;

const $ = <T extends Element = HTMLElement>(s: string, r: ParentNode = document) => r.querySelector(s) as T;
const $$ = <T extends Element = HTMLElement>(s: string, r: ParentNode = document) => [...r.querySelectorAll(s)] as T[];
const D = JSON.parse($("#lp-data").textContent || "{}");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const root = document.documentElement;
const clamp = (x: number, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const fract = (x: number) => x - Math.floor(x);
const hash = (a: number, b: number) => fract(Math.sin(a * 127.1 + b * 311.7) * 43758.5);
const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
// algo se mueve solo mientras se ve (y nunca con «reducir movimiento»)
const seen = new WeakMap<Element, boolean>();
const io = new IntersectionObserver((es) => es.forEach((e) => seen.set(e.target, e.isIntersecting)), { rootMargin: "80px" });
const watch = (el: Element) => { io.observe(el); return () => !!seen.get(el) && !document.hidden; };
const copyText = async (text: string, label?: Element | null, done = D.t.copied) => {
  try { await navigator.clipboard.writeText(text); } catch { /* sin portapapeles */ }
  if (!label) return;
  const before = label.textContent;
  label.textContent = done;
  setTimeout(() => (label.textContent = before), 1400);
};

// ------------------------------------------------------------ tema, encabezado y menú
function setTheme(next: string) {
  root.classList.add("theme-switch");
  root.dataset.theme = next;
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switch")));
  try { localStorage.setItem("starlight-theme", next); } catch { /* sin almacenamiento */ }
  $$<HTMLButtonElement>("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === next));
  agentPaint();
}
$("#theme").addEventListener("click", () => setTheme(root.dataset.theme === "dark" ? "light" : "dark"));
const nav = $(".nav");
const onScroll = () => nav.classList.toggle("scrolled", scrollY > 8);
addEventListener("scroll", onScroll, { passive: true }); onScroll();
const menu = $("#menu");
const closeMenu = () => { nav.classList.remove("open"); menu.setAttribute("aria-expanded", "false"); };
menu.addEventListener("click", () => { const o = nav.classList.toggle("open"); menu.setAttribute("aria-expanded", String(o)); });
$$("#nav-links a").forEach((a) => a.addEventListener("click", closeMenu));
document.addEventListener("pointerdown", (e) => { if (nav.classList.contains("open") && !nav.contains(e.target as Node)) closeMenu(); }, true);

// ------------------------------------------------------------ escenas propias de la portada
// la estación en órbita (el «video» del reproductor): estrellas que titilan, un planeta con su borde de atmósfera
// y continentes, y la estación con sus paneles cruzando despacio
SCENES.orbita = (u, v, t) => {
  const px = u - 1.6, py = v - 1.78, d = Math.hypot(px, py);
  if (d < 1.02) {
    if (d > .985) return [.75, 1];
    const lit = clamp(.35 + (px * .55 - py * .9));
    const land = Math.sin(u * 9 + Math.sin(v * 7) * 2 + t * .05) * Math.sin(v * 11 - u * 3) > .25;
    const swirl = .08 * Math.sin(u * 24 + v * 30 + t * .4);
    return [clamp(.12 + lit * .7 + swirl), land ? 3 : 0];
  }
  const sx = .7 + fract(t * .018) * 1.9, sy = .34 + Math.sin(t * .3) * .01, dx = u - sx, dy = v - sy;
  if (Math.abs(dy) < .028 && Math.abs(dx) < .055) return [.95, 0];
  if (Math.abs(dy) < .016 && Math.abs(dx) < .19 && Math.abs(dx) > .07) return [.7 + .2 * Math.sin(dx * 90), 1];
  const h = hash(Math.floor(u * 60), Math.floor(v * 34));
  if (h > .975) return [.25 + .35 * (.5 + .5 * Math.sin(t * 2 + h * 80)), h > .995 ? 2 : 0];
  return [0, 0];
};
// la lechuga de la diapositiva: hojas que se mecen sobre su maceta
SCENES.lechuga = (u, v, t) => {
  const cx = 1.6, sway = Math.sin(t * .9) * .015;
  if (v > .72 && v < .98 && Math.abs(u - cx) < .32 - (v - .72) * .3) return [v < .76 ? .45 : .75, 0];
  for (let k = 0; k < 7; k++) {
    const a = -1.2 + k * .4, len = .32 + .06 * Math.sin(k * 2.1);
    const ex = cx + Math.sin(a) * len * .55 + sway * (1 - v), ey = .62 - Math.cos(a) * len * .7;
    const q = ((u - ex) / (len * .42)) ** 2 + ((v - ey) / (len * .6)) ** 2;
    if (q < 1) return [.55 + (1 - q) * .4 + .08 * Math.sin((u + v) * 60), k % 3 === 0 ? 2 : 1];
  }
  return [0, 0];
};
// el viaje (web/js/scenes.js › JOURNEY): del logo a la Luna y la Tierra, entre las nubes hasta el atardecer y, bajo el
// mar, del arrecife al naufragio en el fondo, justo en el pie; aquí lo mueve el scroll
declare const JOURNEY: [string, number][];
declare function journeyAt(depth: number, u: number, v: number, t: number, cell: number, A: number): [number, number];
const SEA = JOURNEY.findIndex(([n]) => n === "mar");
let depth = 0;
let bgOverride: string | null = null;
SCENES.viaje = (u, v, t, cell, A) => journeyAt(depth, u, v, t, cell, A);

type Live = { cv: HTMLCanvasElement; r: any; name: string; w: number; h: number; on: () => boolean };
const lives: Live[] = [];
let palKey = "";
function mount(cv: HTMLCanvasElement, name: string, always = false) {
  const r = sceneRenderer(cv.getContext("2d")!, (w, h) => Object.assign(document.createElement("canvas"), { width: w, height: h }));
  const l: Live = { cv, r, name, w: 0, h: 0, on: always ? () => !document.hidden : watch(cv) };
  r.scene(name);
  const p = scenePalette();
  r.palette(p.colors, p.fade, '"JetBrains Mono"');
  const fit = () => {
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h || (w === l.w && h === l.h)) return;
    l.w = w; l.h = h;
    r.resize(w, h, Math.min(devicePixelRatio || 1, 2));
  };
  fit();
  new ResizeObserver(fit).observe(cv);
  lives.push(l);
  return l;
}
function repaint() {
  const p = scenePalette(), k = JSON.stringify(p);
  if (k === palKey) return;
  palKey = k;
  for (const l of lives) l.r.palette(p.colors, p.fade);
}

// la profundidad: cuánto se bajó por la página; bajo el agua, un medidor en metros
const gauge = $("#depth");
function onDepth() {
  const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
  depth = clamp(scrollY / max);
  const under = depth > JOURNEY[SEA][1] - .02 && !bgOverride;
  gauge.classList.toggle("on", under);
  if (under) gauge.querySelector("b")!.textContent = `${Math.round(((depth - JOURNEY[SEA][1]) / (1 - JOURNEY[SEA][1])) * 4000)} m`;
}
addEventListener("scroll", onDepth, { passive: true }); addEventListener("resize", onDepth);

let bg: Live | null = null;
document.fonts.load('12px "JetBrains Mono"').finally(() => {
  bg = mount($<HTMLCanvasElement>("#bg"), "viaje", true);
  $$<HTMLCanvasElement>("canvas.mini-scene").forEach((cv) => mount(cv, cv.dataset.scene || "orbita"));
  palKey = JSON.stringify(scenePalette());
  onDepth();
  new MutationObserver(repaint).observe(root, { attributes: true, attributeFilter: ["data-theme", "style"] });
  let last = 0;
  const loop = (ms: number) => {
    requestAnimationFrame(loop);
    if (ms - last < 110) return;  // ~9 cuadros por segundo: las escenas son lentas
    last = ms;
    for (const l of lives) if (l.on()) l.r.frame(reduce ? 4 : ms / 1000);
  };
  if (reduce) { for (const l of lives) l.r.frame(4); addEventListener("scroll", () => bg && bg.r.frame(4), { passive: true }); }
  else requestAnimationFrame(loop);
});

// el velo: el fondo se apaga detrás de cada bloque de contenido (nada de texto sobre caracteres) y se ve entero en
// los espacios entre secciones, como ventanas al paisaje mientras se baja
const veilEls = $$("main .sec > .wrap, .hero-in, .hero-shot, .stats-sec .wrap, .foot-in, .foot-legal");
let veilRaf = 0;
function veil() {
  veilRaf = 0;
  const cv = $("#bg");
  const H = innerHeight, F = 70, dim = root.dataset.theme === "light" ? .3 : .2;
  const spans = veilEls.map((el) => el.getBoundingClientRect()).filter((r) => r.bottom > -F && r.top < H + F && r.height)
    .map((r) => [r.top - 24, r.bottom + 24]).sort((a, b) => a[0] - b[0]);
  const merged: number[][] = [];
  for (const s of spans) { const m = merged[merged.length - 1]; if (m && s[0] <= m[1] + F) m[1] = Math.max(m[1], s[1]); else merged.push([...s]); }
  const stops: string[] = ["rgba(0,0,0,1) -100px"];
  for (const [a, b] of merged) stops.push(`rgba(0,0,0,1) ${a - F}px`, `rgba(0,0,0,${dim}) ${a}px`, `rgba(0,0,0,${dim}) ${b}px`, `rgba(0,0,0,1) ${b + F}px`);
  const g = `linear-gradient(to bottom, ${stops.join(", ")})`;
  cv.style.setProperty("mask-image", g);
  cv.style.setProperty("-webkit-mask-image", g);
}
const askVeil = () => { if (!veilRaf) veilRaf = requestAnimationFrame(veil); };
addEventListener("scroll", askVeil, { passive: true }); addEventListener("resize", askVeil);
new MutationObserver(askVeil).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
veil();

// ------------------------------------------------------------ 1 · el reproductor de muestra
const P = D.player;
const lines: any[] = D.lines;
const pl = $("#pl");
const plOn = watch(pl);
let now = 0.5, playing = !reduce, plang: string = D.lang === "es" ? "es" : "en";
const BARS = "▁▂▃▄▅▆▇█";
const barsFor = (seed: number, n: number, k = 0) => Array.from({ length: n }, (_, j) => BARS[Math.floor(hash(seed, j + k) * 7.99)]).join("");
let shownLine = -2;
function plRender() {
  const i = lines.findIndex((l) => now >= l.t && now < l.end);
  const l = lines[i];
  $("#pl-time").textContent = fmt(now);
  $("#pl-head").style.width = `${(now / D.end) * 100}%`;
  $("#pl-orig").textContent = l && plang !== "en" ? l.en : "";
  $("#pl-tr").textContent = l ? l[plang] : "";
  $("#pl-who").style.background = l ? `var(--who-${l.who})` : "transparent";
  pl.classList.toggle("talking", !!l && playing);
  // la frase y su espacio: la doblada dura lo mismo que la original (habla mientras suena)
  if (l) {
    const n = Math.max(6, Math.round((l.end - l.t) * 5));
    const k = playing ? Math.floor(now * 6) : 0;
    $("#fit-slot").textContent = barsFor(i + 1, n);
    $("#fit-take").textContent = plang === "en" ? barsFor(i + 1, n) : barsFor(i + 40, n, k);
    $("#fit-slot").style.setProperty("--w", `${((l.end - l.t) / 6.5) * 100}%`);
    $("#fit-take").style.setProperty("--w", `${((l.end - l.t) / 6.5) * 100}%`);
  }
  if (i === shownLine) return;
  shownLine = i;
  $$("[data-line]").forEach((li) => li.classList.toggle("on", Number(li.dataset.line) === i));
  const on = $(`[data-line="${i}"]`);
  const list = $("#pl-tr-list");
  if (on && list.offsetParent) list.scrollTo({ top: on.offsetTop - list.offsetTop - 12, behavior: reduce ? "auto" : "smooth" });
}
const langBtn = $("#pl-lang-btn"), langMenu = $("#pl-lang-menu");
// el idioma: su nombre y una flechita; al tocarlo, los idiomas se despliegan ahí mismo en la barra (como en la app)
const langOpen = (on: boolean) => { langMenu.hidden = !on; langBtn.setAttribute("aria-expanded", String(on)); };
langBtn.addEventListener("click", () => langOpen(true));
document.addEventListener("click", (e) => { if (!langMenu.hidden && !(e.target as Element).closest("#pl-lang")) langOpen(false); });
function plLang(k: string) {
  plang = k;
  $$("[data-plang]").forEach((b) => b.classList.toggle("on", b.dataset.plang === k));
  $("#pl-lang-name").textContent = $(`[data-plang="${k}"]`).textContent;
  langOpen(false);
  $$("[data-tr]").forEach((s) => { s.textContent = k === "en" ? "" : lines[Number(s.dataset.tr)][k]; });
  shownLine = -2; plRender();
}
$$("[data-plang]").forEach((b) => b.addEventListener("click", () => plLang(b.dataset.plang!)));
const playBtn = $("#pl-play");
const setPlaying = (on: boolean) => { playing = on; pl.classList.toggle("paused", !on); playBtn.setAttribute("aria-label", on ? P.pause : P.play); plRender(); };
playBtn.addEventListener("click", () => setPlaying(!playing));
// la velocidad: un clic pasa a la siguiente y la rueda sube o baja; el número rueda como un odómetro
const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
let speedAt = 1;
const speedBtn = $("#pl-speed");
function setSpeed(i: number) {
  i = Math.max(0, Math.min(SPEEDS.length - 1, i));
  if (i === speedAt) return;
  const up = i > speedAt;
  speedAt = i;
  const odo = speedBtn.querySelector(".odo")!, old = odo.querySelector("span:not(.out)") as HTMLElement;
  const nu = document.createElement("span");
  nu.textContent = `${String(SPEEDS[i]).replace(".", D.lang === "es" ? "," : ".")}×`;
  if (reduce || !old) { odo.replaceChildren(nu); return; }
  old.classList.add("out");
  nu.style.transform = `translateY(${up ? 100 : -100}%)`;
  odo.append(nu);
  requestAnimationFrame(() => { old.style.transform = `translateY(${up ? -100 : 100}%)`; nu.style.transform = ""; });
  setTimeout(() => old.remove(), 340);
}
speedBtn.addEventListener("click", () => setSpeed(speedAt === SPEEDS.length - 1 ? 0 : speedAt + 1));
speedBtn.addEventListener("wheel", (e) => { e.preventDefault(); setSpeed(speedAt + (e.deltaY < 0 ? 1 : -1)); }, { passive: false });
$("#pl-track").addEventListener("wheel", (e) => { e.preventDefault(); now = clamp(now + (e.deltaY < 0 ? 5 : -5), 0, D.end - .1); plRender(); }, { passive: false });
$("#pl-track").addEventListener("click", (e) => {
  const r = $("#pl-track").getBoundingClientRect();
  now = clamp((e.clientX - r.left) / r.width) * D.end; plRender();
});
$$<HTMLButtonElement>("[data-at]").forEach((b) => b.addEventListener("click", () => { now = Number(b.dataset.at) + .05; plRender(); }));
$$<HTMLButtonElement>(".tr-copy").forEach((b) => b.addEventListener("click", () => copyText(b.dataset.copy!, b.querySelector("span"), P.copied)));
$$<HTMLButtonElement>("[data-ptab]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-ptab]").forEach((x) => x.classList.toggle("on", x === b));
  $$<HTMLElement>("[data-ppane]").forEach((p) => (p.hidden = p.dataset.ppane !== b.dataset.ptab));
}));
// los siguientes: miniaturas hechas con el patrón de caracteres de la app, cada una en su color
document.fonts.load('10px "JetBrains Mono"').finally(() => {
  $$<HTMLElement>("[data-next]").forEach((pre) => (pre.textContent = asciiField(`next:${pre.dataset.next}`, 24, 8)));
});
// personas: el nombre se cambia ahí mismo y se ve en toda la transcripción; la voz se elige con sus píldoras
$$<HTMLElement>("[data-person]").forEach((n) => n.addEventListener("input", () => {
  const w = Number(n.dataset.person);
  const name = n.textContent?.trim() || P.people[w];
  $$(`[data-who-name="${w}"]`).forEach((x) => (x.textContent = name));
  $(`[data-avatar="${w}"]`).textContent = name[0].toUpperCase();
  // la otra persona elige «la de {nombre}»: también se renombra
  const other = $(`[data-voice="${1 - w}:1"]`);
  if (other) other.textContent = P.voices[1].replace("{name}", name);
}));
// la referencia de cada persona: sus barras (siempre las mismas) y, al escucharla, un avance que las recorre
$$<HTMLElement>("[data-ref]").forEach((r) => {
  [...r.children].forEach((b, j) => (b as HTMLElement).style.setProperty("--h", `${22 + hash(Number(r.dataset.ref) + 7, j) * 78}%`));
});
let refTimer = 0;
$$<HTMLButtonElement>("[data-ref-play]").forEach((btn) => btn.addEventListener("click", () => {
  const was = btn.classList.contains("on");
  clearInterval(refTimer);
  $$("[data-ref-play]").forEach((x) => x.classList.remove("on"));
  $$("[data-ref] i").forEach((x) => x.classList.remove("past"));
  if (was) return;
  btn.classList.add("on");
  const bars = [...$(`[data-ref="${btn.dataset.refPlay}"]`).children];
  let k = 0;
  refTimer = window.setInterval(() => {
    bars[k]?.classList.add("past");
    if (++k > bars.length) { clearInterval(refTimer); btn.classList.remove("on"); bars.forEach((x) => x.classList.remove("past")); }
  }, 300);
}));
$$<HTMLElement>("[data-person]").forEach((n) => n.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); n.blur(); } }));
$$<HTMLButtonElement>("[data-voice]").forEach((b) => b.addEventListener("click", () => {
  const [w] = b.dataset.voice!.split(":");
  $$(`[data-voice^="${w}:"]`).forEach((x) => x.classList.toggle("on", x === b));
}));
plLang(plang);
setPlaying(playing);
let plLast = performance.now();
setInterval(() => {
  const t = performance.now(), dt = (t - plLast) / 1000;
  plLast = t;
  if (!playing || !plOn()) return;
  now += dt * SPEEDS[speedAt];
  if (now >= D.end) now = 0;
  plRender();
}, 100);

// ------------------------------------------------------------ 2 · el texto del video
const S = D.screen;
const slide = $("#slide");
const box = $("#st-box");
let stCur: HTMLElement | null = null;
$("#st-toggle").addEventListener("click", () => {
  const on = !slide.classList.contains("on");
  slide.classList.toggle("on", on);
  $("#st-toggle").setAttribute("aria-pressed", String(on));
  $("#st-toggle .switch").classList.toggle("on", on);
});
function stShow(el: HTMLElement, x?: number, y?: number) {
  stCur = el;
  const s = slide.getBoundingClientRect(), r = el.getBoundingClientRect();
  slide.style.setProperty("--rx", `${r.left - s.left - 6}px`);
  slide.style.setProperty("--ry", `${r.top - s.top - 4}px`);
  slide.style.setProperty("--rw", `${r.width + 12}px`);
  slide.style.setProperty("--rh", `${r.height + 8}px`);
  slide.classList.add("ring");
  box.hidden = false;
  $$<HTMLElement>("[data-st-open]", box).forEach((b) => (b.hidden = el.dataset.kind !== "link"));
  // la píldora sale donde está el mouse (justo debajo del puntero, o arriba si abajo no cabe), siempre dentro del video;
  // sin mouse (teclado), debajo del texto
  const px = x ?? r.left, py = y ?? r.bottom - 4, bw = box.offsetWidth, bh = box.offsetHeight, gap = 14;
  let top = py - s.top + gap;
  if (top + bh > s.height - 8) top = py - s.top - gap - bh;
  box.style.left = `${clamp(px - s.left - 18, 8, s.width - bw - 8)}px`;
  box.style.top = `${clamp(top, 8, s.height - bh - 8)}px`;
}
$$<HTMLElement>(".st").forEach((el) => {
  el.addEventListener("mouseenter", (e) => stShow(el, e.clientX, e.clientY));
  el.addEventListener("focus", () => stShow(el));
  el.addEventListener("click", (e) => stShow(el, e.clientX, e.clientY));
});
slide.addEventListener("mouseleave", () => { slide.classList.remove("ring"); box.hidden = true; });
const shownText = (el: HTMLElement) => ((slide.classList.contains("on") && el.querySelector(".st-tr")) || el.querySelector(".st-orig"))!.textContent || "";
box.addEventListener("click", (e) => {
  const b = (e.target as Element).closest("button");
  if (!b || !stCur) return;
  const act = b.dataset.stAct;
  if (act === "copy") copyText(shownText(stCur), b.querySelector("span"), S.copied);
  if (act === "open") window.open("https://www.nasa.gov/", "_blank", "noopener");
  if (act === "ask") agentAsk(stCur.dataset.kind === "code" || stCur.dataset.kind === "comment" ? 1 : 0, true);
});

// ------------------------------------------------------------ 3 · Lumi: la conversación y el creador de la estrella
const A = D.agent;
let look: Record<string, string> = { ...STAR_DEFAULT };
let starColor = "";
const STAR_COLORS = ["", "#f3c25a", "#e4572e", "#29bf12", "#00a5cf", "#e84f9b", "#8d6e63"];
declare function mixHex(hex: string, other: string, w: number): string;
// el color «del tema», como en la app: el de énfasis, en pastel en claro (tokens.css › --accent)
const colorNow = () => {
  if (starColor) return starColor;
  const base = root.style.getPropertyValue("--accent-base").trim() || "#7d5ba6";
  return root.dataset.theme === "light" ? mixHex(base, "#ffffff", .4) : base;
};
let mood = "";
declare function starSwap(stage: Element, svg: SVGSVGElement): void;
let lookKey = "";
// la estrella grande del creador, como en la app: al cambiar algo, la actual sale por un lado y la nueva entra por el
// opuesto con un rebote (star.js › starSwap); al tocarla salta con corazones; sola, pasa por sus gestos
const mkStage = $("#mk-star");
const mkCurrent = () => mkStage.querySelector<SVGSVGElement>(".agent-star:not(.leaving)");
mkStage.addEventListener("click", () => {
  const s = mkCurrent();
  if (!s) return;
  s.classList.remove("joy"); void s.getBoundingClientRect(); s.classList.add("joy");
  setTimeout(() => s.classList.remove("joy"), 1200);
});
const mkOn = watch(mkStage);
let gesture = 0;
setInterval(() => {
  const s = mkCurrent();
  if (!s || !mkOn() || reduce) return;
  gesture = (gesture + 1) % 3;
  s.classList.remove("think", "talk");
  if (gesture) s.classList.add(gesture === 1 ? "think" : "talk");
}, 2600);
function agentPaint() {
  if (typeof starSvg !== "function") return;
  const c = colorNow();
  const key = JSON.stringify([look, c]);
  if (key !== lookKey) {
    const first = !lookKey;
    lookKey = key;
    if (first || typeof starSwap !== "function") mkStage.replaceChildren(starSvg(look, c));
    else starSwap(mkStage, starSvg(look, c));
  }
  $("#ag-av").replaceChildren(starSvg(look, c, mood));
  $("#pl-lumi-star").replaceChildren(starSvg(look, c));
  $("#st-star").replaceChildren(starSvg(look, c));
  $("#ag-big").replaceChildren(starSvg(look, c, mood));
  // las muestras se actualizan en su lugar (como refresh() en la app): las filas no se rearman ni saltan
  for (const [k, buttons] of Object.entries(partBtns)) {
    for (const b of buttons) {
      const on = look[k] === b.dataset.v;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
      b.replaceChildren(thumbOf(k, b.dataset.v!, c));
    }
  }
  $$<HTMLElement>("#mk-colors .swatch").forEach((b) => b.classList.toggle("on", b.dataset.c === starColor));
}
// como starThumb en la app: de cerca, y en ojos, boca y mejillas sin el accesorio (puede tapar la cara)
function thumbOf(k: string, v: string, c: string) {
  const face = ["eyes", "mouth", "cheeks"].includes(k);
  const svg = starSvg({ ...look, [k]: v, ...(face ? { acc: "ninguno" } : {}) }, c);
  svg.setAttribute("viewBox", "4 1 72 70");
  return svg;
}
// el carrusel de la app (web/js/ui.js › carousel): de a 4, flechas pegadas a la tira, deshabilitadas con una sola página
const CHEVRON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6l6 -6"/></svg>';
function carousel(items: HTMLElement[], per = 4) {
  const track = document.createElement("div"); track.className = "carousel-track"; track.append(...items);
  const nav = (cls: string) => { const b = document.createElement("button"); b.type = "button"; b.className = `carousel-nav ${cls}`; b.innerHTML = CHEVRON; return b; };
  const prev = nav("prev"), next = nav("next");
  const box = document.createElement("div"); box.className = "carousel"; box.style.setProperty("--per", String(per));
  box.append(prev, track, next);
  const page = () => track.clientWidth + parseFloat(getComputedStyle(track).columnGap || "0");
  const sync = () => {
    const single = items.length <= per;
    box.classList.toggle("single", single);
    prev.disabled = single || track.scrollLeft < 2;
    next.disabled = single || track.scrollLeft + track.clientWidth > track.scrollWidth - 2;
  };
  prev.addEventListener("click", () => track.scrollBy({ left: -page() }));
  next.addEventListener("click", () => track.scrollBy({ left: page() }));
  track.addEventListener("scroll", sync, { passive: true });
  new ResizeObserver(sync).observe(track);
  sync();
  return box;
}
const partBtns: Record<string, HTMLButtonElement[]> = {};
$$<HTMLElement>("[data-part]").forEach((row) => {
  const k = row.dataset.part!;
  partBtns[k] = STAR_PARTS[k].map(([v, name]) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "star-opt"; b.dataset.v = v; b.title = name; b.setAttribute("aria-label", name);
    b.addEventListener("click", () => { if (look[k] !== v) { look = { ...look, [k]: v }; agentPaint(); } });
    return b;
  });
  row.replaceChildren(carousel(partBtns[k]));
});
$("#mk-colors").replaceChildren(...STAR_COLORS.map((c2) => {
  const b = document.createElement("button");
  b.type = "button"; b.className = "swatch" + (c2 ? "" : " theme"); b.dataset.c = c2;
  b.style.setProperty("--vc", c2 || "var(--accent-base)");
  b.addEventListener("click", () => { starColor = c2; agentPaint(); });
  return b;
}));
$("#mk-random").addEventListener("click", () => {
  for (const k of Object.keys(STAR_PARTS)) { const o = STAR_PARTS[k]; look[k] = o[Math.floor(Math.random() * o.length)][0]; }
  starColor = STAR_COLORS[Math.floor(Math.random() * STAR_COLORS.length)];
  agentPaint();
});
const msgs = $("#ag-msgs");
let busy = false;
function agentAsk(i: number, scroll = false) {
  if (busy) return;
  if (scroll) $("#agente").scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  busy = true;
  const [q, a, moments] = A.chips[i];
  $("#ag-body").classList.add("chatting");
  const qb = document.createElement("p"); qb.className = "msg me"; qb.textContent = q;
  msgs.append(qb);
  while (msgs.children.length > 4) msgs.firstElementChild!.remove();
  mood = "think"; agentPaint();
  setTimeout(() => {
    mood = "talk"; agentPaint();
    const ab = document.createElement("div"); ab.className = "msg bot";
    const p = document.createElement("p"); ab.append(p); msgs.append(ab);
    let k = 0;
    const type = setInterval(() => {
      k += 3; p.textContent = a.slice(0, k);
      msgs.scrollTop = msgs.scrollHeight;
      if (k < a.length) return;
      clearInterval(type);
      const row = document.createElement("div"); row.className = "moments";
      for (const [t, label] of moments) {
        const m = document.createElement("button"); m.type = "button"; m.className = "moment";
        m.innerHTML = `<span class="t">▶ ${fmt(t)}</span>`;
        m.append(document.createTextNode(label));
        m.addEventListener("click", () => { now = t + .05; setPlaying(true); plRender(); $("#doblaje").scrollIntoView({ behavior: reduce ? "auto" : "smooth" }); });
        row.append(m);
      }
      ab.append(row);
      msgs.scrollTop = msgs.scrollHeight;
      mood = ""; agentPaint(); busy = false;
    }, reduce ? 1 : 22);
  }, reduce ? 50 : 1100);
}
$$<HTMLButtonElement>("[data-chip]").forEach((b) => b.addEventListener("click", () => agentAsk(Number(b.dataset.chip), !!b.dataset.jump)));
agentPaint();

// ------------------------------------------------------------ 4 · bibliotecas con su patrón
const L = D.libs;
let libSel = 0;
const seeds = L.list.map((l: any[], i: number) => `${i}:${l[0]}`);
const charBox = () => { const s = document.createElement("span"); s.className = "mono"; s.style.cssText = "position:absolute;visibility:hidden;font-size:11px;line-height:13px"; s.textContent = "@@@@@@@@@@"; document.body.append(s); const w = s.offsetWidth / 10; s.remove(); return w || 6.6; };
let cw = 6.6;
function libPaint() {
  const l = L.list[libSel];
  const hero = $("#lib-hero");
  hero.style.setProperty("--vc", l[1]);
  const pre = $("#lib-ascii");
  pre.textContent = asciiField(seeds[libSel], Math.ceil(hero.clientWidth / cw) + 2, Math.ceil(hero.clientHeight / 13) + 1);
  $("#lib-name").textContent = l[0];
  $("#lib-count").textContent = `${l[3]} ${L.videos}`;
  const card = $(`[data-lib="${libSel}"]`);
  $("#lib-badge").innerHTML = card.querySelector(".lib-badge")!.innerHTML;
  $$("[data-lib]").forEach((b) => b.classList.toggle("on", b === card));
  $$<HTMLElement>("[data-lib]").forEach((b, i) => { b.querySelector("pre")!.textContent = asciiField(seeds[i], 26, 7); });
}
$$<HTMLButtonElement>("[data-lib]").forEach((b) => b.addEventListener("click", () => { libSel = Number(b.dataset.lib); libPaint(); }));
$("#lib-shuffle").addEventListener("click", () => { seeds[libSel] = `${libSel}:${Math.random().toString(36).slice(2, 8)}`; libPaint(); });
document.fonts.load('11px "JetBrains Mono"').finally(() => { cw = charBox(); libPaint(); new ResizeObserver(() => libPaint()).observe($("#lib-hero")); });
// la búsqueda se escribe sola y encuentra la frase en los dos idiomas
const sq = $("#sq"), hits = $("#hits");
const sqOn = watch(sq);
let sqStep = 0;
setInterval(() => {
  if (!sqOn() || reduce) { if (reduce) { sq.textContent = L.q; hits.classList.add("on"); } return; }
  const q: string = L.q, n = q.length;
  sqStep = (sqStep + 1) % (n + 26);
  const k = sqStep <= n ? sqStep : sqStep < n + 18 ? n : Math.max(0, n - (sqStep - n - 18));
  sq.textContent = q.slice(0, k);
  hits.classList.toggle("on", k === n);
}, 160);

// ------------------------------------------------------------ 5 · agregar, la cola y exportar
const F = D.flow;
type Job = { st: number; title: string; pct: number };
let jobs: Job[] = F.jobs.map(([, title]: string[], i: number) => ({ st: i, title, pct: [42, 78, 0][i] }));
const jobsEl = $("#jobs");
const flowOn = watch(jobsEl);
// cada trabajo conserva su fila: solo cambian el número, el estado y la barra (nada se redibuja ni parpadea); una
// fila nueva entra una sola vez con su animación
const jobRows = new WeakMap<Job, HTMLLIElement>();
function jobsPaint() {
  const rows = jobs.map((j) => {
    let li = jobRows.get(j);
    if (!li) {
      li = document.createElement("li");
      li.className = "job";
      li.innerHTML = `<span class="job-pct"></span><span class="job-t"><b></b><span class="muted small"></span></span><i class="job-bar"><i></i></i>`;
      li.querySelector("b")!.textContent = j.title;
      jobRows.set(j, li);
    }
    li.classList.toggle("done", j.st === 3);
    li.querySelector(".job-pct")!.textContent = j.st === 2 ? "—" : j.st === 3 ? "✓" : `${Math.floor(j.pct)} %`;
    li.querySelector(".small")!.textContent = j.st < 3 ? F.jobs[j.st][0] : "";
    (li.querySelector(".job-bar i") as HTMLElement).style.width = `${j.st === 3 ? 100 : j.pct}%`;
    return li;
  });
  rows.forEach((li, i) => { if (jobsEl.children[i] !== li) jobsEl.insertBefore(li, jobsEl.children[i] || null); });
  while (jobsEl.children.length > rows.length) jobsEl.lastElementChild!.remove();
}
const addIn = $("#add-in");
const LINK = "https://youtu.be/ocean-currents-101";
let addT = 0;
setInterval(() => {
  if (!flowOn() || reduce) return;
  for (const j of jobs) {
    if (j.st === 0) { j.pct += 3.5; if (j.pct >= 100) { j.st = 1; j.pct = 0; } break; }
  }
  const pj = jobs.find((j) => j.st === 1);
  if (pj) { pj.pct += 2.2; if (pj.pct >= 100) { pj.st = 3; } }
  if (!jobs.some((j) => j.st === 0)) { const q = jobs.find((j) => j.st === 2); if (q) q.st = 0; }
  jobs = jobs.filter((j) => !(j.st === 3 && Math.random() < .04));
  // cada tanto, alguien pega un enlace y se agrega a la cola
  addT++;
  if (addT > 22 && addT <= 22 + LINK.length / 3) { addIn.textContent = LINK.slice(0, (addT - 22) * 3); addIn.classList.add("typed"); }
  if (addT === 32) { $("#add-go").classList.add("press"); }
  if (addT === 34) {
    $("#add-go").classList.remove("press");
    addIn.textContent = F.ph; addIn.classList.remove("typed");
    if (jobs.length < 5) jobs.push({ st: 2, title: F.jobs[2][1], pct: 0 });
    addT = 0;
  }
  jobsPaint();
}, 300);
jobsPaint();
$("#add-go").addEventListener("click", () => { if (jobs.length < 5) { jobs.push({ st: 2, title: F.jobs[1][1], pct: 0 }); jobsPaint(); } });
const expCount = () => {
  const n = $$(".exp-card .pill-opt.on").length;
  $("#exp-n").textContent = n === 1 ? F.files[0] : F.files[1].replace("2", String(n));
  ($("#exp-go") as HTMLButtonElement).disabled = n === 0;
};
$$<HTMLButtonElement>(".exp-card .pill-opt").forEach((b) => b.addEventListener("click", () => { b.classList.toggle("on"); expCount(); }));
expCount();

// ------------------------------------------------------------ cómo funciona: la frase pasa por cada etapa
const pipe = $("#pipe");
const pipeOn = watch(pipe);
let stage = 0;
const paintPipe = () => $$("[data-step]", pipe).forEach((s) => s.classList.toggle("on", Number(s.dataset.step) === stage));
paintPipe();
setInterval(() => { if (pipeOn() && !reduce) { stage = (stage + 1) % 5; paintPipe(); } }, 2200);
const wave = $("[data-wave]");
setInterval(() => { if (pipeOn()) wave.textContent = barsFor(3, 10, reduce ? 0 : Math.floor(performance.now() / 140)); }, 140);

// ------------------------------------------------------------ hazlo tuyo: el fondo de esta página, el color y el modo
$$<HTMLButtonElement>("[data-scene-pick]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-scene-pick]").forEach((x) => x.classList.toggle("on", x === b));
  const id = b.dataset.scenePick!;
  bgOverride = id === "viaje" ? null : id;
  if (bg) bg.r.scene(bgOverride || "viaje");
  onDepth();
}));
const syncAccent = () => {
  const cur = root.style.getPropertyValue("--accent-base").trim().toLowerCase();
  $$<HTMLButtonElement>("[data-accent]").forEach((b) => b.classList.toggle("on", b.dataset.accent === cur));
};
$$<HTMLButtonElement>("[data-accent]").forEach((b) => b.addEventListener("click", () => {
  root.style.setProperty("--accent-base", b.dataset.accent!);
  try { localStorage.setItem("lp-accent", b.dataset.accent!); } catch { /* sin almacenamiento */ }
  syncAccent(); agentPaint();
}));
syncAccent();
$$<HTMLButtonElement>("[data-mode]").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.mode!)));
$$<HTMLButtonElement>("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === root.dataset.theme));

// ------------------------------------------------------------ capturas, rendimiento, instalar y la captura del héroe
$$<HTMLButtonElement>("[data-tour]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-tour]").forEach((x) => x.classList.toggle("on", x === b));
  $$("[data-tour-pane]").forEach((p) => p.classList.toggle("on", p.dataset.tourPane === b.dataset.tour));
}));
const T = D.t;
function setGpu(i: number) {
  const p = D.perf[i];
  $$("[data-gpu]").forEach((b) => b.classList.toggle("on", Number(b.dataset.gpu) === i));
  $("#pf-name").textContent = p.profile[D.lang];
  $("#pf-voice span").textContent = p.voice ? T.yes : T.noVoice;
  $("#pf-state").textContent = p.speed >= 1.5 ? T.good : T.edge;
  $("#pf-state").classList.toggle("warn", p.speed < 1.5);
  $("#pf-speed").textContent = `${p.speed}×`;
  $("#pf-fill").style.width = `${Math.min(100, (p.speed / 3.5) * 100)}%`;
  const num = (n: number) => n.toLocaleString(D.lang === "es" ? "es" : "en", { maximumFractionDigits: 1 });
  $("#pf-vram").textContent = `~${num(p.vram)} GB`;
  $("#pf-ram").textContent = `~${num(p.ram)} GB`;
  $("#pf-takes").textContent = T.takes.replace("X", num(Math.round((10 / p.speed) * 10) / 10));
}
$$("[data-gpu]").forEach((b) => b.addEventListener("click", () => setGpu(Number(b.dataset.gpu))));
setGpu(0);
$$("[data-inst]").forEach((b) => b.addEventListener("click", () => {
  $$("[data-inst]").forEach((x) => x.classList.toggle("on", x === b));
  $$("[data-inst-pane]").forEach((p) => p.classList.toggle("on", p.dataset.instPane === b.dataset.inst));
}));
$$<HTMLButtonElement>(".copy").forEach((b) => b.addEventListener("click", () => {
  const code = b.parentElement!.querySelector("code")!.innerText.replace(/\s+#.*$/gm, "");
  copyText(code, b.querySelector("span"));
}));
const tilt = $("#tilt");
const doTilt = () => {
  const r = tilt.getBoundingClientRect();
  const p = clamp(1 - (r.top - innerHeight * .3) / (innerHeight * .6));
  tilt.style.setProperty("--p", reduce ? "1" : p.toFixed(3));
};
addEventListener("scroll", doTilt, { passive: true }); addEventListener("resize", doTilt); doTilt();
