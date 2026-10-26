# Translay — instrucciones para Claude Code

App local que traduce y dobla videos EN→ES (servidor Python en `vt/`, interfaz en `web/`, motor de voz en `.venvs/<motor>`). Documentación en `docs/` (Astro + Starlight); empieza por `docs/src/content/docs/funcionamiento/arquitectura.mdx`.

## En cada cambio (obligatorio)

1. **Documentación en el mismo commit.** Actualiza la página de `docs/src/content/docs/` que describe lo que cambiaste (guía de uso, cómo funciona, integraciones o empezar). Si agregas una página, ponle `title`, `description` y `sidebar.order`.
2. **Changelog.** Toda función nueva, arreglo o mejora de rendimiento lleva una línea en «## Sin publicar» de `CHANGELOG.md`, en el grupo que corresponda.
3. **Referencia generada.** Las tablas de CLI, preferencias, eventos y rutas de la API salen del código (`docs/scripts/gen_reference.py`): documenta en el código (el `help=` de argparse, `DETAILS` en `vt/prefs.py`, `CATALOG` en `vt/events.py`, el docstring de `vt/api.py`) y no copies esas tablas a mano.
4. **Commits con la convención** de `docs/src/content/docs/desarrollo/commits.mdx`: `tipo(alcance): descripción` en español, minúscula, sin punto final. El hook `.githooks/commit-msg` lo valida (activar con `git config core.hooksPath .githooks`).
5. Antes de dar por terminado un cambio de documentación, compílala: `cd docs && npm run build`.

## Versiones

`python scripts/release.py --next` sugiere el número; `python scripts/release.py X.Y.Z` libera (ver `docs/src/content/docs/desarrollo/versiones.mdx`). No hagas push ni etiquetes sin que lo pidan.

## Pruebas

`python -m pytest tests` (sin GPU). Para cambios en la interfaz, pruébala en el navegador (escritorio y celular, claro y oscuro) con la configuración `translator` de `.claude/launch.json`.
