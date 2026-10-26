// Antes de compilar: datos de referencia desde el código (vt/) y el changelog del repo.
// Así las tablas y la página de cambios nunca quedan atrás del código.
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const docs = join(dirname(fileURLToPath(import.meta.url)), "..");
const root = join(docs, "..");

// 1. referencia (CLI, preferencias, eventos, API) leída de vt/ con Python
const py = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const r = spawnSync(py, [join(docs, "scripts", "gen_reference.py")], { stdio: "inherit" });
if (r.status !== 0) {
  console.error("No se pudo generar la referencia: hace falta Python 3.10+ (o la variable PYTHON).");
  process.exit(1);
}

// 2. CHANGELOG.md (raíz del repo) → página «Cambios»
const md = readFileSync(join(root, "CHANGELOG.md"), "utf8")
  .replace(/^# .*\n+/, ""); // el título lo pone la página
const page = `---
title: Cambios
description: Todo lo que cambió en cada versión de Translay.
tableOfContents:
  maxHeadingLevel: 2
editUrl: false
---

{/* Generado desde CHANGELOG.md por scripts/sync.mjs: edita CHANGELOG.md, no este archivo. */}

${md}`;
const out = join(docs, "src", "content", "docs", "cambios.mdx");
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, page);
console.log("changelog sincronizado en src/content/docs/cambios.mdx");
