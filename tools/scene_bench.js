// Cuánto cuesta cada escena del fondo (web/js/scenes.js) con el tamaño de celda real: ms por cuadro, cuadros por segundo
// que deja el tope de uso y % de un núcleo. Uso: node tools/scene_bench.js web/js/scenes.js
const fs = require("fs"), vm = require("vm");
const ctx = { Math, console, performance };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8") + ";this.SCENES=SCENES;this.sceneCell=sceneCell;this.SCENE_FPS=SCENE_FPS;this.SCENE_SHARE=SCENE_SHARE;", ctx);
for (const [W, H] of [[2560, 1440], [1920, 1080], [1366, 768]]) {
  const [cw, ch] = ctx.sceneCell(W, H), cols = Math.ceil(W / cw), rows = Math.ceil(H / ch), A = W / H, u0 = Math.max(0, (3.2 - A) / 2), cell = cw / H;
  const out = [];
  for (const name of Object.keys(ctx.SCENES)) {
    const f = ctx.SCENES[name], ms = [];
    for (let k = 0; k < 6; k++) {
      const t0 = performance.now();
      for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) f(u0 + (i / cols) * A, j / rows, 3 + k * 0.1, cell, A);
      ms.push(performance.now() - t0);
    }
    ms.sort((a, b) => a - b);
    const m = ms[3], fps = Math.min(ctx.SCENE_FPS, 1000 / Math.max(1000 / ctx.SCENE_FPS, m / ctx.SCENE_SHARE));
    out.push(`${name} ${m.toFixed(0)}ms→${fps.toFixed(1)}cps ${(m * fps / 10).toFixed(1)}%`);
  }
  console.log(`${W}x${H} celda ${cw}x${ch} (${cols * rows}): ` + out.join(" · "));
}
