// Después de compilar: revisa los enlaces relativos entre páginas y sus anclas (#…), en los dos idiomas.
// starlight-links-validator no revisa los enlaces relativos, que son los que usan estas páginas.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, posix, sep } from "node:path";
import GithubSlugger from "github-slugger";
const root = process.argv[2] || join(import.meta.dirname, "..", "src", "content", "docs");
const files = [];
const walk = (d) => { for (const f of readdirSync(d)) { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : /\.mdx?$/.test(f) && files.push(p); } };
walk(root);
const rel = (p) => p.slice(root.length + 1).split(sep).join("/").replace(/\.mdx?$/, "");
const urlOf = (r) => "/" + (r === "index" ? "" : r.replace(/(^|\/)index$/, "") + "/");
const pages = new Map();
for (const f of files) {
  const text = readFileSync(f, "utf8");
  const slugger = new GithubSlugger();
  const anchors = new Set();
  let inCode = false;
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith("```")) inCode = !inCode;
    const m = !inCode && /^#{1,6}\s+(.*)$/.exec(line);
    if (m) anchors.add(slugger.slug(m[1].replace(/`/g, "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_]/g, "").trim()));
  }
  pages.set(urlOf(rel(f)), { anchors, text, file: rel(f) });
}
let bad = 0;
for (const [url, p] of pages) {
  const links = [...p.text.matchAll(/\]\(([^)\s]+)\)|^\s+link: ([^\s"]+)|href="([^"]+)"/gm)].map((m) => m[1] || m[2] || m[3]);
  for (const l of links) {
    if (/^(https?:|mailto:|\/)/.test(l)) continue;
    if (/\.(webp|png|svg|jpg)$/.test(l)) continue;
    const [path, anchor] = l.split("#");
    let target = path ? posix.normalize(posix.join(url, path)) : url;
    if (!target.endsWith("/")) target += "/";
    const t = pages.get(target);
    if (!t) { console.log(`${p.file}: no existe la página ${l}`); bad++; continue; }
    if (anchor && !t.anchors.has(decodeURIComponent(anchor))) { console.log(`${p.file}: no existe el ancla ${l}  (tiene: ${[...t.anchors].join(", ")})`); bad++; }
  }
}
console.log(bad ? `${bad} enlaces rotos` : "enlaces relativos y anclas: todo bien");
process.exit(bad ? 1 : 0);
