# Translay — instrucciones para Claude Code

App local que traduce y dobla videos EN→ES (servidor Python en `vt/`, interfaz en `web/`, motor de voz en `.venvs/<motor>`, app de escritorio para Windows con instalador en `desktop/`). Documentación en `docs/` (Astro + Starlight, inglés en la raíz y español en `es/`); empieza por `docs/src/content/docs/how-it-works/architecture.mdx`.

## En cada cambio (obligatorio)

1. **Documentación en el mismo commit, en los dos idiomas.** Actualiza la página de `docs/src/content/docs/` (inglés) y la misma en `docs/src/content/docs/es/` (español) que describe lo que cambiaste (guía de uso, cómo funciona, integraciones o empezar). Si agregas una página, créala en los dos con `title`, `description` y `sidebar.order`. Diagramas: nunca de texto; en `docs/src/diagrams.ts` con `<Diagram />`. Si cambia la instalación o el producto, también `README.md` y `README.es.md`.
2. **Changelog.** Toda función nueva, arreglo o mejora de rendimiento lleva una línea en «## Unreleased» de `CHANGELOG.md` (inglés) y en «## Sin publicar» de `CHANGELOG.es.md` (español), en el grupo que corresponda; si la sección no existe (justo después de liberar), créala arriba de la última versión. Nunca dejes esa sección vacía: la documentación solo muestra versiones publicadas.
3. **Referencia generada.** Las tablas de CLI, preferencias, eventos y rutas de la API salen del código (`docs/scripts/gen_reference.py`): documenta en el código (el `help=` de argparse, `DETAILS` en `vt/prefs.py`, `CATALOG` en `vt/events.py`, el docstring de `vt/api.py`) y no copies esas tablas a mano.
4. **Commits con la convención** de `docs/src/content/docs/development/commits.mdx`: Conventional Commits **en inglés**: `type(scope): imperative summary` (minúscula, sin punto final, máx. 72) y un cuerpo con una viñeta por cambio, agrupado por área, que diga qué cambió y por qué. Termina con el trailer `Co-Authored-By` de Claude. El hook `.githooks/commit-msg` lo valida (activar con `git config core.hooksPath .githooks`).
5. Antes de dar por terminado un cambio de documentación, compílala: `cd docs && npm run build`.

## Versiones

`python scripts/release.py --next` sugiere el número; `python scripts/release.py X.Y.Z` libera (ver `docs/src/content/docs/development/releases.mdx`). No hagas push ni etiquetes sin que lo pidan.

## Pruebas

`python -m pytest tests` (sin GPU). Para la app de escritorio: `npm --prefix desktop run dev` (usa el código del repositorio) y `npm --prefix desktop run build` (instalador en `desktop/src-tauri/target/release/bundle/nsis/`); si cambia `requirements.txt`, regenera `desktop/locks/server.txt` (ver `development/releases.mdx`). Para cambios en la interfaz, pruébala en el navegador (escritorio y celular, claro y oscuro) con la configuración `translator` de `.claude/launch.json`.
