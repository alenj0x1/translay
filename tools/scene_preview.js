// Dibuja una escena del inicio (web/js/scenes.js) como texto, para revisarla sin navegador:
//   node tools/scene_preview.js web/js/scenes.js mar 160 40 3   (escena, columnas, filas, segundo)
const fs = require("fs"), vm = require("vm");
const [file, name, cols = "160", rows = "40", t = "3"] = process.argv.slice(2);
const ctx = { Math, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(file, "utf8") + "\nthis.SCENES = SCENES; this.RAMP = RAMP;", ctx);
const C = +cols, Rw = +rows, A = 3.2, cell = A / C;
let out = "";
for (let j = 0; j < Rw; j++) {
  let line = "";
  for (let i = 0; i < C; i++) {
    const r = ctx.SCENES[name](i / C * A, j / Rw, +t, cell);
    const n = Math.min(10, Math.round(r[0] * 10));
    line += r[1] === 1 && n > 0 ? "\x1b[35m" + ctx.RAMP[n] + "\x1b[0m" : n < 2 ? " " : ctx.RAMP[n];
  }
  out += line + "\n";
}
process.stdout.write(out.replace(/\x1b\[\d+m/g, ""));
