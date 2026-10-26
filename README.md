# Translay

Traduce y dobla videos del inglés al español **con la voz de cada persona**, en tu propio equipo y con tu GPU. Pega un enlace de YouTube (o abre un archivo) y míralo en español: subtítulos, transcripción alineada EN | ES y voz clonada sincronizada con la imagen.

**Versión 1.0.0** · [Documentación](https://alenj0x1.github.io/translay/) · [Cambios](CHANGELOG.md) · [Versiones](https://github.com/alenj0x1/translay/releases)

## Qué hace

- **Doblaje con su propia voz:** Whisper reconoce, Opus-MT traduce y OmniVoice clona la voz de cada persona del video (diarización propia). La voz suena sincronizada (desfase mediano 0.08 s).
- **YouTube y archivos:** videos, playlists, varios enlaces o un CSV con miles; una sola cola en el servidor los descarga y procesa, con el video que ves primero.
- **Biblioteca:** colecciones propias y automáticas (canales, categorías), varias bibliotecas en carpetas propias, búsqueda en todas las transcripciones, glosario.
- **Exportar:** video y audio traducidos u originales, subtítulos SRT y transcripción.
- **Acceso e integraciones:** bibliotecas privadas, con contraseña o públicas; API REST con claves y webhooks firmados.

## Empezar

### Con Docker (GPU NVIDIA)

```sh
git clone https://github.com/alenj0x1/translay.git && cd translay
cp .env.example .env          # y cambia TRANSLAY_OWNER_PASSWORD
docker compose up -d --build
```

Abre http://localhost:8765. La primera vez descarga los modelos (~6 GB). Detalle: [Docker](docs/src/content/docs/empezar/docker.mdx).

### En tu equipo

Requisitos: GPU NVIDIA (8 GB+), Python 3.11+, [uv](https://docs.astral.sh/uv/), ffmpeg y Node.js 20+.

```sh
pip install -r requirements.txt
uv venv -p 3.11 .venvs/omnivoice
uv pip install -p .venvs/omnivoice/Scripts/python.exe --torch-backend=cu128 omnivoice deepfilternet soundfile
python run.py
```

En Linux, el Python del motor está en `.venvs/omnivoice/bin/python`. Se abre http://127.0.0.1:8765. Opciones: `python run.py --help`. Detalle: [Instalación](docs/src/content/docs/empezar/instalacion.mdx).

## Documentación

Todo el funcionamiento (guía de uso, arquitectura, pipeline, GPU, datos, API, webhooks y desarrollo) está en **https://alenj0x1.github.io/translay/**, un sitio Starlight que vive en [`docs/`](docs/) y se publica solo en cada cambio. Para verlo en local:

```sh
cd docs
npm install
npm run dev        # http://localhost:4321
```

Las tablas de referencia (opciones de arranque, preferencias, eventos y rutas de la API) se generan desde el código al compilar, y la página de cambios sale de [CHANGELOG.md](CHANGELOG.md).

## Desarrollo

```sh
git config core.hooksPath .githooks     # valida la convención de commits
python -m pytest tests                  # pruebas sin GPU
```

- Commits con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) en español: `feat(cola): priorizar desde la tarjeta`. Ver [CONTRIBUTING.md](CONTRIBUTING.md).
- Cada cambio actualiza su página de la documentación y «Sin publicar» en el changelog.
- Versiones con `python scripts/release.py X.Y.Z` ([Versiones](docs/src/content/docs/desarrollo/versiones.mdx)).

## Estructura

| | |
|---|---|
| `vt/` | Servidor: HTTP + WebSocket propios, reconocimiento, traducción, voz, cola, biblioteca, API |
| `web/` | Interfaz (HTML, CSS por capas y JS sin framework) |
| `tools/` | Herramientas de evaluación y doblaje por línea de comandos |
| `tests/` | Pruebas sin GPU |
| `docs/` | Documentación (Astro + Starlight) |
| `scripts/` | Liberar versiones |
| `data/` | Tu biblioteca, voces y preferencias (no va a git) |
