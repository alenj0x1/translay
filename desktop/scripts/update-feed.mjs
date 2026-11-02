// latest.json for the in-app updater (desktop/src-tauri/src/updates.rs): the version, its notes and, for
// Windows, the installer's URL with its signature (the .sig that `tauri build` writes next to the
// installer when createUpdaterArtifacts is on and TAURI_SIGNING_PRIVATE_KEY is set).
//
//   node desktop/scripts/update-feed.mjs --version 1.7.0 --notes notas.md \
//     --base https://github.com/alenj0x1/translay/releases/download/v1.7.0 --out latest.json
//
// --dir: folder with the installer (default: the NSIS bundle folder).

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) =>
  a.startsWith("--") && all[i + 1] && !all[i + 1].startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc, []));
for (const k of ["version", "base", "out"]) if (!args[k]) throw new Error(`falta --${k}`);

const dir = args.dir || fileURLToPath(new URL("../src-tauri/target/release/bundle/nsis/", import.meta.url));
const exe = readdirSync(dir).find((f) => f.endsWith(`_${args.version}_x64-setup.exe`));
if (!exe) throw new Error(`no está el instalador ${args.version} en ${dir}`);
const signature = readFileSync(join(dir, `${exe}.sig`), "utf8").trim();

const feed = {
  version: args.version,
  notes: args.notes ? readFileSync(args.notes, "utf8").trim() : "",
  pub_date: new Date().toISOString(),
  platforms: {
    "windows-x86_64": { signature, url: `${args.base.replace(/\/$/, "")}/${encodeURIComponent(exe)}` },
  },
};
writeFileSync(args.out, JSON.stringify(feed, null, 2));
console.log(`${args.out}: ${exe}`);
