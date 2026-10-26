# Contribuir

1. Activa la validación de commits (una vez por clon):

   ```sh
   git config core.hooksPath .githooks
   git config commit.template .gitmessage
   ```

2. Mensajes con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) en español:

   ```
   feat(cola): priorizar desde la tarjeta
   fix(voz): referencias sin recortar
   docs(api): ejemplo de exportación
   ```

   Tipos: `feat` `fix` `perf` `refactor` `style` `docs` `test` `build` `ci` `chore` `revert`. Detalle en [docs/…/desarrollo/commits.mdx](docs/src/content/docs/desarrollo/commits.mdx).

3. La documentación cambia en el mismo commit que el código: la página de `docs/` que corresponda y una línea en «Sin publicar» de [CHANGELOG.md](CHANGELOG.md). El hook rechaza un `feat`, `fix` o `perf` que toque la app sin eso. Ver [Mantener la documentación](docs/src/content/docs/desarrollo/documentacion.mdx).

4. Antes de proponer el cambio:

   ```sh
   python -m pytest tests
   cd docs && npm run build
   ```

Para liberar una versión: [Versiones](docs/src/content/docs/desarrollo/versiones.mdx).
