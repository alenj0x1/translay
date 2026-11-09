# Changelog

All notable changes to Translay. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

The same entries in Spanish: [CHANGELOG.es.md](https://github.com/alenj0x1/translay/blob/main/CHANGELOG.es.md). Changes waiting for the next version sit under **Unreleased** at the top (this section only exists while there are some, and the docs site doesn't show it); `scripts/release.py` turns it into the new version.

## 1.11.0 · 2026-11-08

### Added

- Preferences › Apariencia: «Color de énfasis» (Accent color) picks the color of buttons, progress and playback (the theme's or one of seven); «Color de cada biblioteca» (Color of each library) now overrides it only when turned on.

### Fixed

- Adding a link: pressing Enter with something that isn't a YouTube or Dropbox link shows a notice instead of doing nothing, and a video that can't be downloaded (private, deleted, members-only, age-restricted or a link that needs an account) goes to «Con error» at once with a notice saying which one and why, instead of retrying silently for 20 minutes.
- Desktop app: the install and model download percentages follow what is written and downloaded as it happens; before, Hugging Face's Xet downloads kept the folder at 0 MB until the end and Windows listed files still being written with their old size, so the bar stayed still and then jumped.
- Queue and «Agregar» panels close when you tap anything outside them, the other button included (some elements stopped the click and the panel stayed open).
- Record the screen: after picking a window or a tab, Translay stays in front instead of hiding behind it, and the dialog warns that a window or the whole screen records the whole computer's sound (a call included).
- Summary: «Resumir» (Summarize) appears as soon as the transcription finishes, without leaving the video and coming back; if the open video already has sentences on the server that the tab didn't get, it asks for the transcript again.
- Library: selecting videos on the home page shows the selection actions (they were missing), and on a phone they stay under the header however far down you scroll; right-clicking a card's checkbox opens the video's menu.
- Preferences › Rendimiento: a long processor name («AMD Ryzen 7 7730U with Radeon Graphics») wraps to two lines instead of spilling out of its card.

## 1.10.0 · 2026-11-08

### Added

- Video summary: the «Resumen» (Summary) tab tells what the video was about and lists all its important points, each with its minute (a click jumps there); there is no fixed number of points, a long video has more. It is made on your computer with a small language model (Qwen3 4B, 1.7B or 0.6B, chosen for your machine or in Preferences › Resumen) and comes out in Spanish whatever the video's language. «Resumir» (Summarize) makes it when you ask, or every video is summarized when the queue finishes it. The API has `GET` and `POST /api/v1/videos/{id}/summary`, and webhooks get `resumen.listo` and `resumen.error`.
- Export: «Texto en español» (Spanish text), «Texto del original» (Original text) and «Resumen» (Summary) as TXT files.
- Export: on this computer, Translay asks where to save with the Windows dialog («Guardar como» with the proposed name, or a folder for several files), starting in the last folder you used; Preferences › Exportar can set a fixed folder instead. Each export in the Queue list shows where it was saved, its context menu has «Mostrar en el Explorador» (Show in Explorer) and «Copiar la ruta» (Copy the path), and what was saved to a folder stays in the list after a restart.
- Library: each card shows the language spoken in the video (EN, PT, ES…) next to its duration.

### Fixed

- Phone header: the library button no longer overlaps the logo, «Agregar» shows only its icon on narrow screens (the rule pointed at old markup) and no button drops to a second row at 320 px; the grey line under the header is gone.
- Player: the rounded corners no longer show a thin black line under the light controls.

## 1.9.0 · 2026-11-02

### Added

- Export: choose the audio quality («Alta», «Media» or «Liviana», the light one in mono) and Opus as a third format, besides M4A and MP3; the dialog shows the approximate size. Videos can be exported at 480p or 360p. The API takes `"quality"` and `"video"`.
- Export: «Guardar en» (Save to) saves straight to a folder of this computer, another drive included, without going through the data drive or leaving a second copy, and several files go loose in folders instead of a `.zip` (ready for a USB drive); «Mostrar en la carpeta» opens it in the Explorer. The API takes `"dest"` (only the owner, from this computer).
- Preferences › Storage: how much downloads, models, the Spanish voice, the trash and the rest take, with the free space of each drive; it frees downloads never translated, the largest ones one by one, models (each one with what it's for, which profiles use it and when it was last used), loose files, the trash, exports and the desktop installer cache.
- Profiles and models: the desktop app installer asks for the profile after installing the server (with the recommended one marked and what each one downloads), installs the voice engine only if the profile uses it and downloads its models, so Translay opens ready. Choosing another profile says which models are missing and how much they weigh before restarting, downloads them on restart (and installs the voice engine in the app if needed), and can delete the ones the new profile doesn't use.

### Fixed

- Exports to download no longer stay on disk until the next restart: they're deleted when removed from the Queue panel, after 24 hours while the server runs, and right away if they fail. `.tmp` files left by an interrupted write are deleted on startup.

## 1.8.0 · 2026-11-02

### Added

- Exporting several videos: the `.zip` uses folders like the sidebar. From a channel, collection, playlist or category everything goes in one folder with its name; from «Todos», «Recientes» or a search, «Carpetas» (Folders) chooses one folder per channel (the default), collection or playlist, or none. The API takes `"layout"` and `"folder"`.

## 1.7.1 · 2026-11-01

### Changed

- Desktop app: new versions are announced instead of installed by the app: «Descargar» opens the installer in your browser and you run it as usual. Windows Defender's machine-learning scan took the release build that downloaded and ran its own installer for a trojan and deleted it.

### Fixed

- Docs site: the menu button only shows on phones, with one icon (three lines closed, X open) and room next to the language selector; the page outline on the right is narrower.
- Docs site: code blocks with a terminal or title bar join it without rounded corners in between, and two-column tables without titles no longer show an empty first row.

## 1.7.0 · 2026-11-01

### Added

- Desktop app: Translay updates itself. It looks for new versions on GitHub when it opens and every 6 hours (Preferencias › App de escritorio › «Buscar actualizaciones»: automatically or only manually), shows the notes and installs with «Actualizar a» and the new version, then opens again. It waits for the queue, downloads and exports to finish, and only installs updates signed with Translay's key.
- Portuguese → Spanish: Portuguese videos are translated and dubbed like English ones, with Opus-MT itc-itc (as good as MADLAD-3B in the lab and ten times faster) and rules that rewrite Brazilian idioms and colloquial forms («pisou na bola», «pra», «tá») before translating.
- Automatic language detection: new videos (links, files and screen recordings) have no language to choose; Whisper detects it from the first seconds of speech (100 % correct in the lab in English, Portuguese and Spanish, also with background noise). A language Translay can't translate yet is only transcribed, in that language.
- «Solo transcribir» (Transcribe only) for any language: «Agregar ▾» › «Agregar y solo transcribir», or «Idioma y traducción» in the video's menu; switching between translating and transcribing deletes nothing. The new preference «Solo transcribir lo que está en» (Only transcribe what is in; Spanish by default) decides which detected language is only transcribed. The API takes `"lang": "auto|en|pt|es"` and `"task": "translate|transcribe"` when importing.
- Search finds more than what is said: the box («Buscar videos y lo que se dice») groups results into «Videos» (title or channel of the library's videos, as normal cards), «Colecciones y canales» (collections, playlists, categories and channels by name; a click opens it) and «En lo que se dice» (transcripts, translation and comments, as before), with a count such as «2 videos · 5 frases · 1 colección».
- A translator per source language: each one loads the first time a video in its language arrives and only one is on the GPU at a time, so memory doesn't grow with languages. The Portuguese one is prepared from the official OPUS-MT release (pinned and SHA-256 verified) the first time it is needed, without stopping other videos.

### Changed

- «Subtítulos en inglés» is now «Subtítulos del original» (Original subtitles), in Preferences and in Export: the SRT is named with the video's language (`.pt.srt`) and the MP4 tags the original track with its real language. Your preference carries over and the API still accepts `srt_en`.
- Performance profiles say the translator tier (`big` or `base`) instead of a model name, since each language has its own.
- «Agregar ▾» offers «Agregar y traducir» and «Agregar y solo transcribir» in place of «Está en español: solo transcribir»; the language is always detected.
- «Importar» is now «Agregar» (Add), a split button whose main part does what you use most in this browser (from 3 uses; otherwise «Agregar»): paste a link, «Subir» files, «Capturar» the screen or «Pegar enlaces». Its ▾ always opens the full panel: the link field with «Agregar y traducir» / «Agregar y solo transcribir» and the cards «Archivos», «Grabar pantalla» and «Varios enlaces». The new preference «Botón Agregar» (Preferencias › Agregar y descargar, formerly «Importar y descargas») can keep it always as «Agregar». Everything that adds content says «Agregar» too (collection headers, empty library, context menus, «Agregar varios enlaces»); «Importar sesión» and the API's `import` route and `import_mode` key don't change.

### Fixed

- Desktop app: the window buttons (minimize, maximize, close) no longer get cut off on narrower windows; the title bar switches to icons earlier and the search box gives up its space.
- Live recognition has rules for each language (words a sentence rarely ends with, and the phrases Whisper makes up on silence, such as «Subtítulos realizados por la comunidad de Amara.org»): before, only English ones existed, so Spanish videos now get cleaner sentences too.

## 1.6.0 · 2026-11-01

### Added

- Record the screen («Importar › Grabar pantalla»): a tab, a window or the whole screen, all of it or a zone. Hovering the preview highlights the boxes it detects (a playing video, even inside part of a page, windows and panels); click to pick one, scroll to the box around it or drag to mark one by hand. Quality Alta, Media, Ligera or Solo audio and 30 or 15 fps, with the estimated size per minute and per hour. It is transcribed and translated live while recording, then compressed (H.264 + AAC) and added to the queue. Nothing is lost if the connection drops, the server restarts or the tab closes: each second stays in the browser until the server confirms it and the upload resumes on its own.

- Empty lists explain themselves with an icon, a title and what will appear there (Queue sections, Exports and other screens) instead of an empty box or a bare «Nada aquí».

- Export audio as MP3: when you check translated or original audio, «Formato del audio» lets you choose M4A or MP3 (192 kbps); the browser remembers it. The API takes `"audio": "mp3"`.

### Fixed

- A batch export no longer fails entirely because of one video: if one can't be exported (for example, it was removed from YouTube and was never downloaded), it is skipped, the rest continue and the `.zip` includes `omitidos.txt` with the reason. Errors are shown in plain words instead of yt-dlp's raw text.
- When part of a collection isn't downloaded, its header button is «Exportar descargados (N)» and exports only what is on your computer; before, «Exportar» exported the whole collection and tried to download from YouTube what was missing.
- Exporting audio shows progress while each file is converted (a two-hour mix takes over a minute) and large batches show the percentage with one decimal and before the title, so the panel no longer looks stuck at 0 %.

### Performance

- Exports convert and mix several videos at once (up to six, half the processor's threads): about three times faster on a large batch, e.g. 8.6 hours of audio to MP3 in under two minutes. Each file goes into the `.zip` as soon as it's ready and its loose copy is deleted, so a batch takes up its size once on disk instead of twice; a cancelled export deletes what it had made.

## 1.5.0 · 2026-11-01

### Added

- «Seleccionar descargados (N)» (Select downloaded) in a collection's header selects only the videos already on your computer, leaving out the ones still in the queue, so you can export them (for example, only the audio) or move them.
- Connect your YouTube account: «Conectar con Brave» (or your default browser) opens a window with Translay's own browser profile; you sign in once, close it, and downloads use that session. It renews itself before downloading if it's more than a week old and whenever YouTube asks to verify you are not a bot (the download is retried without the 20-minute pause). No extensions, no `cookies.txt` to export, and your everyday browser can stay open.
- When YouTube asks to verify you are not a bot or a video is age-restricted, the notice offers «Conectar YouTube».

### Fixed

- Videos imported by link that kept their YouTube id as the name get their title and channel: the lookup now runs in the background over every library, resumes after a restart and retries every hour (before, it ran once and was lost if Translay closed or YouTube didn't answer).
- On a phone, a group of options that didn't fit on one line became a misshapen pill: it now shows one option per row, and preferences with more than four options («Sesión para descargar») use a dropdown list.
- On a phone, the header buttons stay on one row (the «Biblioteca» button no longer drops alone to a second row), and the header and the side pills no longer stretch on pages with little content.
- In dark mode, switches use the same gray as the selected option instead of an almost white tone.
- The notice with a button («Deshacer», «Conectar YouTube») no longer squeezes its text into half of a phone's width.

### Security

- The connected account keeps only the youtube.com cookies, encrypted with DPAPI and handed to yt-dlp in memory (no plain-text file). Translay talks to the browser over a private pipe, not a network port, only asks for cookies, never touches your everyday profile and stores nothing about the account. «Desconectar» signs out in Google and deletes the profile.

## 1.4.0 · 2026-10-28

### Added

- Dropbox links: paste a shared link to a video (also from a folder, like `dropbox.com/scl/fo/…/video.mp4`) in «Importar», in the several-links dialog, in a CSV or through the API. It enters the queue, downloads with progress like a YouTube video and its card says «Dropbox».
- Videos that are already in Spanish: «Importar ▾ › Está en español: solo transcribir», or «Idioma del video» (Video language) in the context menu. They are transcribed in Spanish without translation or dubbing, play with the original audio and a single subtitle, and the transcript shows one column.
- «Renombrar…» (Rename…) in a video's context menu gives it your own name (for example, instead of `21_10`); it stays even if the video is downloaded again. Also `PATCH /api/v1/videos/{id}` with `{"title"}`.
- The import API takes `"lang": "es"`, and a video's data includes its `lang` and the shared `url`.

### Changed

- The light profiles («Ligero» and «Subtítulos ligeros») use Whisper `small` instead of `small.en`, so they also recognize Spanish.

### Fixed

- On a phone, the player's video had no width and didn't show.

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
