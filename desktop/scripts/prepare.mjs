// Runs before `tauri dev` and `tauri build`:
// 0. Stages Translay's own code (vt/*.py, web/, run.py) into .stage/translay/ for the installer: copying the
//    folders directly would also bundle __pycache__ and editor leftovers.
// 1. Copies the shared look (font, theme tokens, buttons, title bar) from web/ into ui/shared/, so the setup
//    screen and Translay's own page are styled by the same files.
// 2. Downloads the third-party tools listed in tools.json, verifies each archive's SHA-256 and extracts
//    only the listed files into src-tauri/tools/ (bundled by the installer). Archives are cached in
//    .cache/ so rebuilding does not download them again.
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const web = join(root, "..", "web");
const stage = join(root, ".stage", "translay");
rmSync(stage, { recursive: true, force: true });
mkdirSync(join(stage, "vt"), { recursive: true });
for (const f of readdirSync(join(root, "..", "vt"))) {
  if (f.endsWith(".py")) cpSync(join(root, "..", "vt", f), join(stage, "vt", f));
}
cpSync(web, join(stage, "web"), { recursive: true });
cpSync(join(root, "..", "run.py"), join(stage, "run.py"));
const shared = join(root, "ui", "shared");
rmSync(shared, { recursive: true, force: true });
for (const file of ["css/fonts.css", "css/tokens.css", "css/base.css", "css/components/button.css",
  "css/components/controls.css", "css/components/desktop.css", "js/ui.js", "fonts"]) {
  cpSync(join(web, file), join(shared, file), { recursive: true });
}
const { tools } = JSON.parse(readFileSync(join(root, "tools.json"), "utf8"));
const cache = join(root, ".cache");
const out = join(root, "src-tauri", "tools");
const stamp = join(out, ".stamp");
const wanted = tools.map((t) => t.sha256).join(",");

if (existsSync(stamp) && readFileSync(stamp, "utf8") === wanted) {
  console.log("tools: up to date");
  process.exit(0);
}
mkdirSync(cache, { recursive: true });
rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "licenses"), { recursive: true });

const tar = process.platform === "win32" ? join(process.env.SystemRoot || "C:\Windows", "System32", "tar.exe") : "tar";
const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

for (const tool of tools) {
  const archive = join(cache, decodeURIComponent(tool.url.split("/").pop()));
  let data = existsSync(archive) ? readFileSync(archive) : null;
  if (!data || sha256(data) !== tool.sha256) {
    console.log(`tools: downloading ${tool.name} ${tool.version}`);
    const res = await fetch(tool.url);
    if (!res.ok) throw new Error(`${tool.name}: HTTP ${res.status}`);
    data = Buffer.from(await res.arrayBuffer());
    const got = sha256(data);
    if (got !== tool.sha256) throw new Error(`${tool.name}: SHA-256 mismatch (expected ${tool.sha256}, got ${got})`);
    writeFileSync(archive, data);
  }
  if (tool.file) {  // a single file (a license): copied as is
    writeFileSync(join(out, tool.file), data);
    console.log(`tools: ${tool.name} verified`);
    continue;
  }
  // Windows ships tar (bsdtar) in System32, which reads zip archives and can extract single members
  // (called by full path: Git's GNU tar earlier in the PATH reads "C:" as a remote host).
  const tmp = join(cache, `x-${tool.name}`);
  rmSync(tmp, { recursive: true, force: true });
  mkdirSync(tmp, { recursive: true });
  execFileSync(tar, ["-xf", archive, "-C", tmp, ...Object.keys(tool.files)], { stdio: "inherit" });
  for (const [from, to] of Object.entries(tool.files)) {
    const dest = join(out, to);
    mkdirSync(dirname(dest), { recursive: true });
    cpSync(join(tmp, from), dest, { recursive: true });  // a file or a whole folder (Python)
  }
  rmSync(tmp, { recursive: true, force: true });
  console.log(`tools: ${tool.name} ${tool.version} verified`);
}
writeFileSync(stamp, wanted);
