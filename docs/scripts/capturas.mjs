// Capturas de la documentación, el README y la portada (docs/src/assets/capturas/) tomadas de una
// instancia de prueba con videos de dominio público (nunca de una biblioteca personal). Ver
// docs/src/content/docs/development/docs.mdx, «Screenshots».
//   node docs/scripts/capturas.mjs <carpeta> [dark|light] [nombre,nombre…]
// Entorno: TRANSLAY_URL (por defecto http://localhost:8799/), CHROME (un Chromium instalado) y
// PLAYWRIGHT (un package.json cuyo node_modules tenga playwright; por defecto el de docs/).
import { createRequire } from "node:module";
import path from "node:path";
const { chromium } = createRequire(process.env.PLAYWRIGHT || path.join(import.meta.dirname, "..", "package.json"))("playwright");
const [,, out, mode = "dark", only = ""] = process.argv;
const URL = process.env.TRANSLAY_URL || "http://localhost:8799/";
const b = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--autoplay-policy=no-user-gesture-required"] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function page(width = 1440, height = 900, vault = "Principal") {
  const ctx = await b.newContext({ viewport: { width, height }, deviceScaleFactor: 2, colorScheme: mode });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => console.log("  pageerror", e.message));
  await p.goto(URL, { waitUntil: "load" });
  await p.waitForFunction(() => typeof lib !== "undefined" && lib.loaded, null, { timeout: 20000 });
  await p.evaluate((name) => { const v = vaults.list.find((x) => x.name === name); if (v && v.id !== vaults.current) openVault(v.id); }, vault);
  await sleep(2500);
  await p.addStyleTag({ content: "*{caret-color:transparent!important} .toast,.toasts{display:none!important}" });
  return p;
}
const vid = (p, text) => p.evaluate((t) => Object.values(lib.videos).find((v) => (v.title || v.name || "").includes(t))?.id, text);

async function player(p, text, at) {
  await p.evaluate(() => { if (prefs.layout !== "ampliada") setPref("layout", "ampliada"); }); await sleep(600);
  const id = await vid(p, text);
  await p.evaluate((i) => applyRoute(`#/video/${i}`), id);
  await sleep(3500);
  await p.evaluate(async (t) => { const v = document.querySelector("video"); if (!v) return; v.muted = true; v.currentTime = t; try { await v.play(); } catch {} }, at);
  await sleep(2500);
  await p.evaluate(() => { const v = document.querySelector("video"); v && v.pause(); });
  await sleep(800);
  await p.mouse.move(700, 450);
  await sleep(300);
}

const shots = {
  async inicio() { const p = await page(); await p.mouse.move(5, 890); return p; },
  async reproductor() { const p = await page(); await player(p, "Power of Light", 31); return p; },
  async dividido() {
    const p = await page(); await player(p, "Power of Light", 47);
    await p.evaluate(() => [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === "Ver dividido" && x.offsetParent)?.click()); await sleep(800);
    await p.evaluate(() => [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === "Transcripción" && x.offsetParent && !x.closest(".side-tabs"))?.click()); await sleep(1500); await p.mouse.move(700, 450); return p;
  },
  async personas() {
    const p = await page(); await player(p, "Wiseman", 62);
    await p.click(".side-tabs button:has-text('Personas')"); await sleep(1200); return p;
  },
  async coleccion() {
    const p = await page();
    await p.evaluate(() => { const c = lib.collections.find((x) => x.name === "NASA Science"); applyRoute(`#/c/${c.id}`); });
    await sleep(3000); await p.mouse.move(5, 890); return p;
  },
  async cola() { const p = await page(); await p.evaluate(() => applyRoute("#/cola")); await sleep(2000); return p; },
  async importar() {
    const p = await page();
    await p.evaluate(() => openMulti(["HBtdbaSKexU", "1MDw2zrbAAs", "R9IbfB0B4FU", "WD7GVvkDjy0"].map((i) => "https://www.youtube.com/watch?v=" + i).join("\n")));
    await sleep(1500); return p;
  },
  async exportar() {
    const p = await page(); const id = await vid(p, "Power of Light");
    await p.evaluate((i) => openExport([i]), id); await sleep(1500); return p;
  },
  async busqueda() {
    const p = await page(); await p.fill("#lib-q", "luz"); await sleep(2500); return p;
  },
  async bibliotecas() {
    const p = await page();
    await p.evaluate(() => (document.querySelector(".vault-btn") || document.querySelector("[aria-label^='Biblioteca']")).click()); await sleep(1200); return p;
  },
  async preferencias() { const p = await page(); await p.evaluate(() => applyRoute("#/preferencias/apariencia")); await sleep(2000); return p; },
  async acceso() { const p = await page(); await p.evaluate(() => applyRoute("#/preferencias/acceso")); await sleep(2000); return p; },
  async "movil-inicio"() { const p = await page(390, 844); return p; },
};

for (const [name, fn] of Object.entries(shots)) {
  if (only && !only.split(",").includes(name)) continue;
  try {
    const p = await fn();
    await p.screenshot({ path: `${out}/${name}${mode === "light" ? "-claro" : ""}.png` });
    console.log("ok", name);
    await p.context().close();
  } catch (e) { console.log("FAIL", name, e.message.split("\n")[0]); }
}
await b.close();
