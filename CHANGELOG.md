# Changelog

All notable changes to Translay. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

The same entries in Spanish: [CHANGELOG.es.md](https://github.com/alenj0x1/translay/blob/main/CHANGELOG.es.md). Changes waiting for the next version sit under **Unreleased** at the top (this section only exists while there are some, and the docs site doesn't show it); `scripts/release.py` turns it into the new version.

## 1.3.1 · 2026-10-27

### Changed

- Translay is now licensed under MIT (`LICENSE`); the installer ships it.
- Commit messages follow Conventional Commits in English, with a body that details every change.

### Fixed

- The docs changelog no longer shows an empty "Unreleased" section above the latest version, which made it look unreleased: the site only lists released versions.

## 1.3.0 · 2026-10-27

### Added

- Desktop app for Windows with an installer (`Translay_<version>_x64-setup.exe`): it installs without administrator rights, sets up the server and the voice engine by itself, and opens Translay in its own window.
- «Preparar Translay» (Set up Translay) screen: your GPU, whether you'll get Spanish voice or subtitles only, where to store the library, and installation progress on the button itself. New versions automatically update the packages that changed.
- The installer ships Python 3.12 and 3.11, ffmpeg, Node.js and uv verified by SHA-256; Python packages are installed pinned with their hash (`desktop/locks/`).
- Custom title bar that follows the theme, with Preferences and the light/dark switch as icons next to minimize, maximize and close. The start screen opens with the last theme used.
- Preferencias › App de escritorio (Preferences › Desktop app): keep running in the tray when the window is closed (the queue continues and, when it finishes, Translay quits and frees everything), change the Main library's folder, and open the logs.
- Closing the app also closes the server and everything it launched (models, voice, downloads, ffmpeg), even if it is closed abruptly: nothing is left using the GPU or RAM.
- `--data-dir` (or `TRANSLAY_DATA`) sets the data folder, and `TRANSLAY_VENVS` the voice environments folder.
- Documentation in English and Spanish, with diagrams; README and changelog in both languages.

### Changed

- The Plus Jakarta Sans font is served by Translay itself: the interface looks the same without internet.

### Fixed

- When switching between light and dark, the gray buttons no longer flicker.

## 1.2.0 · 2026-10-26

### Added

- Support for machines with unified memory, such as NVIDIA DGX Spark (GB10): the GPU is detected with the system RAM as its memory, so Performance no longer treats it as "no GPU" (it showed «Muy forzado» (Very strained) at 0.02×) and the automatic profile picks «Máxima calidad» (Maximum quality). Machines with a dedicated GPU are unchanged.
- With unified memory, light idle is done together with deep idle: moving the models to RAM freed nothing.

## 1.1.0 · 2026-10-26

### Fixed

- Creating, renaming or deleting a library failed when notifying webhooks and the tab didn't update.
- The id (and the `/b/<id>` link) of a library with accents or ñ no longer breaks: «Océanos» is `oceanos`, not `oc-anos`.
- «Editar» (Edit) and «Otro patrón» (Another pattern) on a library work right there, without going back to the home page.
- Menus no longer close by themselves when something scrolls on its own, and options that open another panel no longer close it on the same click.
- On reload, «Traduce tu primer video» (Translate your first video) and a channel's broken banner no longer flash briefly.
- The «Listo para reproducir» (Ready to play) notice no longer covers the English subtitle.
- The queue no longer replaces already-dubbed sentences with fragments when resuming a video from another point, nor loses text in the second pass.
- Two parts of Translay opening the same transcript at once could end up with different copies and lose saved sentences.
- A sentence whose voice fails no longer leaves the whole video in "error": it is left without voice and retried.
- If the voice process hangs, it is shut down after 5 min instead of locking the GPU forever; if it fails to load, it restarts cleanly.
- Light idle also frees VRAM with Chatterbox and VoxCPM, and an error while putting the models to sleep no longer leaves the state stuck at "loading".
- When merging two people, the cloned voice is no longer lost (especially when reopening the video).
- Very long sentences without punctuation no longer cut off the audio of their voice reference.
- The audio of a finished video no longer stays in memory.
- Library, voices and people are saved without being able to end up half-written, with a backup copy (`.bak`) that is used if the file is damaged.
- «Mover a…» (Move to…) another library gives the files back if any is in use, instead of leaving the video split.
- From another machine on the network (http) you can now play with voice and import files.
- The first server messages are no longer lost on slow connections (the guest saw the owner's interface).
- On reconnecting (or after «Reiniciar ahora» (Restart now)), the video you are watching has queue priority again.
- Enter in the text boxes of dialogs confirms instead of canceling.
- In Cola → Exportaciones (Queue → Exports), «Descargar» (Download) and «Cancelar» (Cancel) work; in the panel, the button to remove an export is visible.
- Deleting the video playing in the thumbnail closes the thumbnail.
- Switching quickly between videos no longer applies one's position or duration to the other.
- Canceling «Importar» (Import) from a collection no longer leaves that collection selected for the next import.
- A guest can no longer open Preferences via the URL (permission warnings appeared in a loop).
- Playing at another speed no longer accumulates audio in memory.
- What you type in Preferences (a password, a URL) is no longer erased if a notice arrives from another tab.
- On phones there is a button to create a collection.
- Deleting the open library closes the video being watched from it.
- The Acceso toasts no longer say «Copiado copiado» (Copied copied).
- Channel avatars and banners are downloaded separately and one at a time: they no longer take up the browser's connections (the video wouldn't load) nor trigger YouTube's limit.

### Security

- Another site open in the browser can no longer use Translay as the owner: the WebSocket and requests that change something require the `Origin` to be the app itself (`--allow-origin` / `TRANSLAY_ORIGINS` for proxies that change the Host).
- `GET /api/v1/exports/{id}` only shows exports of videos that can be seen.
- When a library goes back to "password-protected", earlier sessions no longer come back to life.
- Review of the whole codebase: videos can no longer register file paths (only title, duration and origin); video file paths never leave their folder.
- Uploads only accept video or audio (and the thumbnail, JPEG up to 2 MB); an interrupted upload doesn't leave the file half-written.
- Library files are always served as media or downloads, never as pages, with `X-Content-Type-Options: nosniff`.
- «Desde este equipo» (From this machine) only applies if the request arrives at `localhost`/`127.0.0.1` (protection against *DNS rebinding*).
- Signing in always gives a new token (session fixation), with a maximum of 10 failed attempts every 10 minutes per machine; password hashing no longer stalls the server.
- Importing or viewing a video requires permission on that video's library, not on the open one.
- WebSocket: unmasked frames, control frames that are too long, or messages exceeding 16 MB across fragments close the connection; HTTP headers have a maximum of 100 and 15 s to arrive.
- Channel avatars (`/chan/`) require access like the rest of the thumbnails.

### Added

- **Rendimiento** (Performance, in Preferences): detects GPU, VRAM, RAM and CPU and picks a model profile (Máxima calidad, Equilibrado, Ligero, Solo subtítulos, Subtítulos ligeros — Maximum quality, Balanced, Light, Subtitles only, Light subtitles) with speeds measured on 8, 6, 4 and 2 GB machines and with no GPU. It shows whether each profile runs well, is borderline or strained, how long a video takes and whether it can be watched live; switching profiles restarts Translay by itself.
- VRAM, RAM and CPU thread limits for Translay; RAM and CPU apply immediately (Windows Job Object, no administrator).
- Warnings about why something is slow: strained profile, VRAM spilling into shared memory, low RAM, limits that are too low, another program on the GPU.
- **Papelera** (Trash): deleting videos, or emptying or deleting a library, keeps them for 30 days; «Deshacer» (Undo) in the notice and Preferencias › Papelera (Preferences › Trash) to restore or delete forever.
- Hardware labs (`tools/lab/`) that emulate smaller machines with real VRAM, RAM and CPU limits, and `vt/hardware.py` to detect the machine.
- Sidebar in the player too (it collapses to icons with the button next to the logo).
- «Bajar video» (Download video) in the player bar and in the right-click menu for audio-only videos.
- Buttons that are working show their progress: «Bajando video 42 %» (Downloading video 42%), «Exportando 63 %» (Exporting 63%).

### Changed

- Emptying and deleting a library require typing its name; «Vaciar…» (Empty…) moved from the «Todos» (All) header to the library's «⋯» menu.
- `--model`, `--compute-type`, `--beam`, `--translator`, `--voice` and `--device` no longer have a fixed value: without them, the performance profile decides.
- What you edit (libraries, collections, comments, people) shows up instantly everywhere, without waiting for the server.
- The arrows on the home page rows stay inside the row and only appear if there are more videos in that direction.

## 1.0.0 · 2026-10-25

First public release.

### Translation and dubbing

- Recognition with Whisper large-v3-turbo in streaming mode, with custom VAD and local agreement.
- Translation with Opus-MT big (fp16) and custom layers for Latin American Spanish: sentence splitting, idioms and literal phrasings. NLLB-1.3B and MADLAD-3B as alternatives (`--translator`).
- Custom diarization (WeSpeaker in ONNX + incremental clustering): 97.6% of sentences with the right person across 12 test videos.
- Dubbing with each person's cloned voice (OmniVoice), references of up to 8 s cleaned with DeepFilterNet if noisy, duration fitted to each sentence's slot and WSOLA as a fallback.
- Look-ahead processing: the voice plays in sync with the picture (median offset 0.08 s; 0.25 s on a 28-min video).
- Persistence by video fingerprint: what is processed is not processed again; if the text, the person or the engine changes, the sentence is dubbed again automatically.

### Library

- Home page with «Seguir viendo» (Continue watching) and a row per collection; automatic collections (Recientes, Todos, YouTube channels and categories — Recent, All) and custom ones.
- Multiple libraries, each in its own folder (another drive, for example), with its own videos, collections, glossary, people, theme and import mode; «Mover a…» (Move to…) moves the files.
- Banners and badges with Bauhaus patterns per collection and library; real avatar and banner of the channels.
- Search across all transcripts (English, Spanish and comments, ignoring accents).
- Multi-select to open, process, export, move or delete.

### Import and queue

- YouTube links, playlists, several links at once, CSV with thousands of links, and files from the machine; import straight into a collection.
- A single server-side queue that survives reloading: the video you are watching goes first and follows your jumps; «Priorizar» (Prioritize), pause and a dedicated screen with states.
- Spaced-out downloads, in order or at random, audio only or video, «Solo descargar» (Download only); automatic pause if YouTube asks for verification, and spaced-out retries.
- YouTube session with cookies.txt or from the installed browser.
- Idle mode: the models leave the GPU after 45 s idle and the voice process shuts down after 2 min.

### Player

- Expanded and split view, custom controls, speed from 0.75× to 2× without changing pitch, ES/EN subtitles.
- «Preparando NN % / Listo para reproducir» (Preparing NN% / Ready to play) indicator based on the real dubbing speed; pauses until ready and autoplays the next one.
- Aligned EN | ES transcript with the person speaking, per-sentence comments and marks on the progress bar.
- People: name and voice for each one (their own cloned voice or another person's from the video).
- Glossary per library: fixed or untranslated terms; changing it re-translates and redoes the voice.

### Export

- Translated video (Spanish voice + English as a second track + subtitles), translated audio, original video and audio, SRT subtitles in both languages and TXT transcript; several in a .zip.

### Access and integrations

- Owner without a session from the same machine and with a password from others; each library private, password-protected or public, view-only or view and import.
- Access from other machines on the local network.
- REST API `/api/v1` with per-library keys (read or write).
- Webhooks signed with HMAC-SHA256, with retries and 21 events.

### Interface

- «Translay» design: a single font, light and graphite dark, custom menus, lists and checkboxes, per-area context menu, collapsible sidebar and loading skeleton.
- The address keeps track of where you are: reloading doesn't go back to the home page and back/forward work.

### Installation and documentation

- Docker image with CUDA 12.8, server and voice engine; `docker-compose.yml` and `--owner-password` / `TRANSLAY_OWNER_PASSWORD` for owner access in the container.
- Documentation in Starlight (`docs/`) with reference generated from the code.
- Commit convention (Conventional Commits) with validation in `.githooks/commit-msg`.
