# Changelog

All notable changes to Translay. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

The same entries in Spanish: [CHANGELOG.es.md](https://github.com/alenj0x1/translay/blob/main/CHANGELOG.es.md). Changes waiting for the next version sit under **Unreleased** at the top (this section only exists while there are some, and the docs site doesn't show it); `scripts/release.py` turns it into the new version.

## Unreleased

### Added

- Player: the progress line shows the video's chapters (from its summary) as stretches with a small gap between them; hovering shows the chapter's name over the time, the current chapter appears next to the time, and a summary that arrives while watching adds them without reloading.
- Italian videos: detected, transcribed, translated into Spanish and Portuguese with Opus-MT itc-itc and into English with roa-eng (the models Portuguese already uses, so nothing new to download) and dubbed; with Italian abbreviations and the subtitle credits Whisper makes up on silence («Sottotitoli creati dalla comunità Amara.org», «Sottotitoli a cura di QTSS»).
- Japanese and Korean videos: detected, transcribed, translated into Spanish, Portuguese and English with MADLAD-400 3B (8 to 10 chrF points above every Opus-MT measured on FLEURS) and dubbed. Its ~3 GB are downloaded with the first Japanese or Korean video, not with the profile. Japanese sentences are split after 。！？ and joined without spaces live, a pause closes them with 。, Korean ones split without needing a capital, and the phrases Whisper writes on silence in each language («ご視聴ありがとうございました», «다음 영상에서 만나요») are dropped.
- Screen recording: «Silenciar las otras apps al grabar una ventana» (Settings › Add and download, off by default) mutes every other application while a window is recorded on Windows 10, where a window brings the whole computer's sound, and gives them their sound back when the recording stops or its tab closes.
- Settings › Performance › **Guardar informe** (Save report) writes a diagnostics report (version, Windows build, profile and the last lines of the logs) to Downloads, or downloads it from another computer; every error now leaves one line in `app.log`, with time and context.
- Dubbing: **Fondo sin la voz original** (Background without the original voice, Settings › Audio and subtitles, on by default): when a video finishes dubbing (or the owner opens one dubbed earlier), its music and effects are separated from the original voice (CDX23, on the voice engine), and the player and the export put the dubbed voice over that background instead of the original turned down, so the original language is no longer heard underneath.
- Transcript: edit a sentence's translation right there (double-click or right-click › **Editar traducción**). **Rehacer voz** (Redo voice) dubs it again in three takes to listen to and choose from; a sentence fixed by hand keeps its text when the glossary or the translator changes.

### Changed

- Sign-in: **Volver** (Back) moved to the top left of the card, with an arrow, instead of sitting between the password and the public libraries.
- Screen recording: on Windows 11 a recorded window brings only the sound of its application, not the whole computer's (Windows 10 can't separate it, so there it stays as before and the dialog says so).

### Fixed

- Updates reach everyone at once behind a proxy that caches `.js` and `.css` (such as Nginx Proxy Manager's «Cache Assets»): the page asks for its styles and scripts with `?v=` and a fingerprint of the interface files and the language (the scene worker and the `scenes.js` it loads too). Before, the proxy kept serving the previous version for hours.
- Agent: a "Solo ver" guest no longer sees the chat, the suggestions, **Encender** or «Preguntar a Lumi», which the server refuses to them; the agent tab explains that asking it is for whoever can import. The agent's bar no longer shows a stray «null» to whoever isn't the owner.
- Guests who can only view no longer get «No tienes permiso para esta acción en esta biblioteca» every time they open a video: the player only asks the queue to prioritize the open video (`watch`) when the library allows importing, and the agent's «Resumir» suggestion is hidden from them.
- Agent on Linux and in Docker: the summary, the short descriptions and the questions no longer fail trying to download the Windows `llama-server`. The Docker image builds `llama-server` with CUDA from the same llama.cpp version, and outside Windows Translay uses the one in `TRANSLAY_LLAMA_SERVER` or in the `PATH` (`LLAMA_CUDA_IMAGE` and `LLAMA_CUDA_ARCHITECTURES` build it for a single GPU, e.g. GB10).
- Screen recording: a recording is no longer lost when its page never comes back. Each second carries the recording's options, and if the server receives nothing for a minute (the recorded tab or window was closed and then the browser, the app was closed, or Translay was opened at another address) it puts together what it has and adds it to the library; if the page comes back with the missing seconds, the video is completed.
- Desktop app: closing the window while recording stops and saves the recording first, and Translay no longer quits from the tray in the middle of a recording or its upload.
- Guests: a «Solo ver» guest no longer gets «No tienes permiso para esta acción en esta biblioteca» when opening a video (the page asked to register it in the library). The page now only asks the server for what the viewer may do.
- Guests: a video that isn't fully dubbed no longer stays paused for a «Solo ver» guest at «Se reanuda al estar listo 0 %». Nothing is processed for them, so they hear the original where the voice is missing and the bar says so.
- The page shows Translay's icon in the browser tab (it asked for `/favicon.ico` and got an error).
- Screen recording: a recording no longer fills the disk. The server stops taking it with 1 GB left free (or at 24 GB per recording); the rest waits on this device under **Sin espacio en el disco** and is uploaded once there is room.
- Korean videos: subtitle credits Whisper writes over music with other wording («한글자막 제공 및 자막 제공 및…») and, in any language, sentences that end in the same few words repeated three times are no longer shown or dubbed (only with low confidence, like the other made-up phrases).
- Desktop app: the window only opens the address of the server it started (loopback and the port it chose), read from the server's own output, never from its errors.

## 1.14.0 · 2026-11-14

### Added

- Desktop app: **Ver la bienvenida** (Settings › App de escritorio) shows the first-run wizard again without reinstalling; only what is changed there is applied.
- Languages: Translay in Spanish, English and Portuguese. One choice of language (Settings › Uso › Idioma, the system's by default; existing installs stay in Spanish) for the interface, translation and voice, the agent and summaries; **Traducir a** (Translate into) separates it for translation and dubbing. Changing the language applies at once, without reloading the app.
- Languages: each video keeps its translation and dubbed voice per language. Choosing another language brings back what was already done in it, and what's missing is translated and dubbed when the video is opened.
- Translation routes measured on FLEURS: English → Portuguese with Opus-MT tc-big en-pt, Spanish → Portuguese with Opus-MT itc-itc, and Spanish/Portuguese → English with Opus-MT tc-bible roa-eng, prepared from the official release like itc-itc.
- Interface catalogs (web/i18n/*.json, keyed by the Spanish text) for the whole app and the server's messages; `tools/i18n.py` lists what's missing and a test requires complete catalogs.
- Agent: a character you build — a rounded star with its shape, eyes, mouth, cheeks and an accessory (Settings › Agente › Avatar, with «Al azar»). It sleeps while its model is off, wakes up while it loads, thinks and talks while answering, and hops with hearts when you tap it. In an empty chat it sits in the middle with what it can do below; with the first question it flies into its answer.
- Agent: quick actions (export, jump to a moment, subtitles, save, alerts) understand Spanish, English and Portuguese and answer in the app's language.
- Libraries screen: the open library highlighted with its character scene, the others in compact cards with their pattern in the corner; the libraries menu shows each pattern too.
- Export: a new dialog with the video's thumbnail and three cards (Video, Audio, Text) holding their options; the button says how many files will be saved.
- A carousel component for option rows (four per page, arrows on the sides), first used by the agent's creator.
- Lab `tools/lab/lang_adherence.py`: how often each agent model answers in the requested language.
- Settings: a home page with a card for each section, in five blocks (General, Watching, Videos, Libraries and access, Computer), and a search that also finds the options inside each section; the sidebar uses the same blocks.
- Look: animated scenes made of characters as the app's background (Translay, the default, with the logo's wave speaking; seabed, sunset, jellyfish and spiders) in the theme's colors, a new logo (a voice wave and «translay») and JetBrains Mono for code and technical data. Code blocks follow light and dark mode: each code theme has its light and dark version. Menu icons tilt slightly on hover, and the main content has a rounded top-left corner where the header and the sidebar meet. The header and the panels are slightly see-through, so the background scene shows behind them. Selected text takes the theme's color.
- Backgrounds: a journey in new scenes, each one also a background of its own — **Luna** (Translay's icons orbiting the Moon), **Tierra** (the Earth turning with its continents and clouds), **Nubes** (clouds), **Arrecife** (a coral reef with a sea turtle), **Ballena** (a whale crossing the open sea), **Abismo** (the deep, with an anglerfish and its glowing lure) and **Naufragio** (a shipwreck on the seabed) — and **Recorrido**, which travels through all of them by itself, from the logo to the Moon, down to the Earth, the sunset and the bottom of the sea. In the welcome, the backgrounds are shown in two columns.
- Agent: **Uso del equipo** (Settings › Agente) sets how much of the computer the summary and descriptions take: they rest between requests, and on CPU-only computers it also limits the cores. Questions keep full speed.
- Player: a short description under the video's title (one or two sentences), written by the agent's smallest model when the video finishes processing, or taken from its summary.
- Agent: **Continuar** (Continue) picks up a stopped answer from where it was left.
- Text in the video: titles, signs, slides and code comments written in a video are read on the CPU (PP-OCRv5), translated and shown on top of the original in the same place and colors; the translated video carries them burned into the image. Code, commands and links are left as they are, and new kinds of elements are added with one function in `vt/textkind.py`. On by default (Ajustes › Audio y subtítulos › «Texto del video en español»), also at `GET /api/v1/videos/{id}/screen-text`.
- Transcript: code, commands, links and code comments written in the video show in their place among the sentences, with a button to copy them and a click to jump there.
- «Copiar para un agente» (right click on the video, a sentence or a card) copies the whole video as Markdown for any agent: transcript with times, people and translation, summary, what's on screen and how far you watched; also at `GET /api/v1/videos/{id}/context`.
- Agent: the «Resumen» tab becomes the video's agent. Ask it anything about the video (what is said, what's on screen, in which minute something happens, what you still have to watch) and it answers on your computer, without internet, with each moment as a button that jumps there and suggestions that follow the video. It runs with llama.cpp on the graphics card, integrated graphics or the processor, with the model chosen for your machine; name, avatar, color, tone and model in Ajustes › Agente. The summary is its first card.
- Code colors: code, commands and comments in the transcript and the agent are highlighted with the theme chosen in Ajustes › Apariencia (Visual Studio Code Dark by default; One Dark, Catppuccin, Dracula, Monokai, Nord and GitHub Light).
- Player: a subtitles button (CC) and the <kbd>C</kbd> key to choose or turn off the subtitles and the video's text, also from the right-click menu.
- Summary: much more complete, written by the agent's model from what is said and what is on screen: overview, ideas to take away, chapters with their points and moments, key terms, and links, commands and code from the video as resources. Generated automatically when the video is ready (Ajustes › Agente).
- Agent: customize its name, avatar, color and tone from its own tab (brush button) without leaving the video; its answers come in a bubble tinted with its color, each moment is a button with ▶ in that color, and a sample video (summary with chapters, terms and resources, and a few questions) stays beside the options to show how it will look, also in Settings.
- Player: code, commands, links and translated text in the video can be copied or sent to the agent from the video itself (hover, click or right-click), with a highlight box that glides from one to the next; the transcript's code and commands have «Preguntar a Lumi» too.
- Agent: actions with their own card, instant and also while it is off: export the video for Claude or another agent (copy or download .md), jump to a moment or to where something is explained, change the subtitles, save the video to a collection, and notices while watching (marked on the progress bar, with a notice when you reach each one).
- Agent: right-click a moment on the progress bar to ask about it; it appears as a mention above the question box.
- Agent: shows each step while it answers (loading the model, reading the video, writing), and every message shows its time and a copy button; finished answers end with a green check, and questions asked while it answers wait in a queue.
- Agent: before the first question it shows what it can do as chips that ask or start the question for you.
- Agent: dictate questions with the microphone button; Translay's Whisper writes what you said in the box so you can review it before sending.
- Settings › Agente: the model list shows which models are compatible with your computer, which one is recommended, how well each answered in the lab and which are downloaded; the chosen model can be downloaded ahead with its progress on the button. Agent models appear in Settings › Almacenamiento, are deleted one at a time and «Borrar los que tu perfil no usa» no longer deletes them.
- Settings › Agente: a «Del tema» color, marked with its own icon, that follows the app's accent color.
- Agent: turn it on or off from its tab (off, the model leaves memory; it also sleeps after 5 minutes without questions). Question suggestions come from the summary, so they work while it is off and clicking one turns it on. Default models chosen with the lab: Qwen3.5 4B or Gemma 4 E2B on graphics cards, Qwen3.5 0.8B on integrated graphics and Qwen3.5 2B or 0.8B on the processor.
- Welcome on first launch (in the browser, with `run.py` or Docker): four steps to choose the language (Windows' by default), name and style the library, pick mode, background scene and accent color (they change behind the dialog as you choose) and build the agent's star. Each choice is saved at once; «Omitir» (Skip) closes it.
- Desktop app: a first-run wizard in the window while the voice engine and the models download, with the download's progress in its bottom strip. Steps on the left and, for each, its options next to a live preview: language (the wizard switches at once) and which language is only transcribed, how you'll use Translay, the main library (name, color, avatar and pattern, with its banner), appearance (the window itself changes), the agent's star, YouTube and access from your phone (both optional), and short demos of the app with a cursor that clicks. Translay opens with all of it applied once the wizard ends and the server is ready.
- Desktop app: the startup screen shows the background scene you chose (the «Translay» scene the first time), what is loading in words with its percentage and tips about the app, in your accent color and language.

### Changed

- Desktop app, first-run wizard › Apariencia: the mode is chosen from three little windows (system, light, dark) and the background from a thumbnail of each scene, instead of rows with icons; the Exportar demo shows the export dialog as it is now (aligned rows).
- Player: play as a bare icon, the current time stronger than the total, a progress line without a handle that grows on hover, controls that only show with the mouse over the video, speed as a number that rolls like a wheel, and a language picker that opens inside the bar with the original and every dubbing language (one the video isn't in yet is marked and prepared right there). Text in the video: Copy and Ask go in one pill that appears where the mouse is, Ask with the agent's own star. The mouse wheel works on the progress line (5 s), the volume (5 %) and the speed.
- Agent, summary and description prompts are in English with an instruction to answer in the app's language, repeated at the end of each request: answers in the requested language went from 0–93 % to 93–100 % across the four default models and three languages.
- Fallback translator: MADLAD-400 3B (Apache-2.0) instead of NLLB-200 (CC-BY-NC); it ties or beats NLLB on the measured pairs.
- Video cards open with a click anywhere (no «Ver»/«Continuar» button and no play button over the thumbnail); «⋯» opens the right-click menu, which replaces the lone «X» to remove from a collection.
- The video's title, description and buttons sit below the video. Dialogs close when clicking outside.
- Dark theme: no borders and no greys lighter than the active one; chosen options use the accent color; dialogs, fields, tabs, the transcript panel, code blocks and every Settings page follow it. Library avatars are solid; the create/edit library dialog shows the library's scene with «Otro patrón» and «Al azar». Settings › Acceso lists one row per library with its access in a dropdown.
- Banner light behind collection and channel headers is softer.
- The accent color is remembered in the browser and applied before the page paints (no white buttons and logo while loading).
- Settings: the YouTube session moved into Agregar y descargar (Add and download), and Uso now says what it is for.
- Accent color: soft pastels in light mode with text in a deep tone of the same color (no more black text on green); each swatch in Settings shows its light and dark versions, split by a wavy diagonal.
- Background (formerly «Fondo del inicio»): the thumbnail and color lights and the gallery are replaced by the scenes; your own image stays.
- Interface texts reviewed across the app so they read like a finished product: «Descargar» instead of «Bajar», «Iniciar sesión» and «propietario», «Priorizar», «Notificaciones», «Estilo de respuesta», «Dispositivo», «Ideas clave», «Subtítulos activados» and short notices without colons or a trailing period.
- The chosen option in tabs, option groups, ES / EN and active buttons is marked by its tone alone, without a ring or shadow.
- Home: what you are watching comes first, large, with the light of its thumbnail behind; the add box left the home page (adding and recording are in the top bar). The background is chosen in Settings › Apariencia › «Fondo del inicio»: the video's light, the accent color's, plain or your own image, with the real home page as a preview. Eight more backgrounds in a gallery (Aurora, Atardecer, Océano, Bosque, Brasa, Medianoche, Arena, Niebla), and the featured text switches between light and dark to stay readable over any background. On large screens the featured video grows with the window and shows its summary's key ideas and first chapters, each one a button to that moment.
- The sidebar and the video's panel change width by dragging their edge; past the minimum the sidebar turns into icons and the panel hides (drag its edge back to show it). The «Transcripción» button above the video is gone: the panel holds more than the transcript.
- Header: the buttons are always the same and in the same place (Grabar, Agregar, Cola, Biblioteca, Ajustes), with the open screen's one highlighted; «Biblioteca» no longer turns into «Volver al video». An open video stays in the thumbnail at the bottom right also when paused, to go back to it.
- Library: hovering over a downloaded video plays a silent preview in its thumbnail, like YouTube.
- Collections, playlists, channels and categories open with a header (badge, name, videos and actions) with the light of their banner or thumbnails behind, like YouTube's ambient mode. The dot pattern is gone from banners, cards and libraries.
- Dark theme: pure neutral grays without the bluish tint (background #161616, panels #181818, fields #1f1f1f, menus #1a1a1a).
- Desktop app: new icon (the voice wave in violet on a dark square) in the window, taskbar, Start menu and installer, and the new logo on the setup and startup screens.
- Desktop app: the setup and startup screens and the installer are in Spanish, English and Portuguese.
- Website: a new home page with the app's design (dark neutral, no borders, violet accent) and its character scenes running live: the page's whole background is a journey through those scenes as you scroll: Translay's icons orbit the Moon, you descend to the Earth, through the clouds to the sunset, and dive past the reef, a whale, jellyfish and the abyss to a shipwreck on the seabed in the footer, live demos of each feature (a player with transcript, people and how each sentence fits, the on-screen text translated with Copy and Ask Lumi, a chat with Lumi and its star builder, libraries with their patterns and search, add, queue and export, and the pipeline), a tour of current screenshots, a playground where the scene, accent color and mode change the whole page, and updated facts about languages. The documentation uses the new logo, colors and JetBrains Mono.
- Documentation: screenshots retaken with the new design, with new ones of the agent and the text in the video; «Your first video» explains how the language is chosen (Settings › Uso › Idioma and «Traducir a»), and the Library guide explains that dialogs close when clicking outside.
- Export: one aligned row per type (Video, Audio, Subtitles and Text) with its format next to its name, its options and the quality or format at the right, and shorter option names; the chosen card takes only a hint of the accent color and the chosen quality or folder option uses the accent's selection tone.
- Documentation: screenshots follow the page's light or dark theme, retaken with the default violet accent; the previous and next page links are smaller and without a border. The README uses the new logo.

### Fixed

- Desktop app: when the download is done and the packages are being unpacked, the install says «Terminando de instalar» with a waiting bar instead of standing still at 97 %.
- Libraries: «Nueva biblioteca» and «Editar» open on top of the Libraries screen instead of closing it first (no flash), and «Cancelar» goes back to it.
- The rounded corner where the header meets the sidebar follows the sidebar while it opens or closes, instead of jumping ahead of it.
- Header on phones: the library button no longer sits under the add button, and on very narrow screens (320 px) every button stays in the first row.
- Demo library: cards no longer show «Doblado 2 %» (the covered time is stretched with the sentences), and each demo video has its own dubbed audio.
- The player no longer requests a missing dubbed audio over and over (thousands of requests); a missing file isn't requested again and a network error retries after a few seconds.
- The agent's chat no longer jitters when scrolling while it writes: only the answer being written is updated.
- Look: the background scenes use at most 15 % of one processor core on any computer (larger cells on big screens, a usage cap and positions computed once per frame), and stop while a video plays and while another window is in front (both can be turned off in Settings › Apariencia).
- Look: the background scene is drawn in its own thread, from pre-drawn characters and only where something changed, so navigating no longer slows down (it took up to half of the interface's time on a full-screen window).
- Settings: the chosen option's pill now slides to the new one in every option group (redrawing the page used to make it jump).
- Agent: stopping an answer works at once, also while it is still reading the video, and keeps what it wrote so far.
- Release script: it no longer fails in a Windows console when printing the notes; it writes its output in UTF-8.
- Settings › Agente: the «El de énfasis» color swatch was invisible.
- Agent: if Translay is closed abruptly, the model server closes with it instead of staying in memory.

## 1.13.0 · 2026-11-13

### Added

- Transcript and «Personas»: each person in a video has their own muted color (blue, violet, teal, gold, pink), on their name in the transcript and on their P1, P2…, so you can follow who speaks at a glance.
- Home: the add box comes in with a soft animation when you arrive, and its title changes with a short animation when you pick «Traducir y doblar» or «Solo transcribir».
- Documentation site: a new home page that presents Translay, with a playable sample of the player and its aligned transcript, the five steps of dubbing, every feature, real screenshots, the profile picked for each GPU, access and API, installation, what's new in the latest version and frequent questions, in English and Spanish and in light and dark.

### Changed

- Option groups (Traducir y doblar / Solo transcribir, light or dark, export formats…): the chosen option is a pill that slides softly to the new one; so do the player's side tabs (Transcripción, Resumen, Personas) and the ES / EN switch.
- Dialogs fade in softly and notices rise when they appear and fade out when they leave, instead of popping in.
- Dark theme: dialogs, menus, fields and the chosen option use the new darker grays, just above the bars, instead of the old lighter gray; text fields and dropdowns have no gray fill, only a thin line.
- Collections, channels and categories without their own banner always get a color: the gray dot field is gone.
- Documentation and README: every screenshot was retaken with the current version, in dark and light.

### Fixed

- Library: with videos selected, the title, how many and the actions stay on one row; when the actions don't fit, they show only their icon instead of overlapping or spilling out.
- Player: «Listo para reproducir» (Ready to play) no longer covers the English subtitle at the top of the expanded view, and in the split view the transcript shows the original small above the Spanish instead of two very narrow columns.

## 1.12.0 · 2026-11-12

### Added

- Queue: **Detener** (Stop) and **Continuar** (Continue) on each job stop a single video's download and processing without losing its place; **Detener todo** (Stop all) now stops downloads too, not only processing (the video you watch keeps going).
- Transcript: stretches not transcribed yet appear among the sentences as «Aún sin transcribir» (Not transcribed yet), or «Transcribiendo esta parte» while they are processed, so jumping ahead doesn't look like an error; a click goes there.
- Desktop app: on Windows 11, resting the mouse on maximize or holding it opens the snap layouts.
- Record the screen: if the source changes shape halfway (from a phone to a desktop screen), the final video fits both in one frame without stretching; before, everything was squeezed into the first source's shape.
- Settings › Use: **Transcribir y resumir** (Transcribe and summarize), a mode to record or add videos and use their transcript and summaries; nothing about translation or voice appears and the server doesn't load the translator or the voice. What was translated is kept, and what you add in this mode stays as only transcribed.
- Home: the add box («Traduce un video», Translate a video) stays at the top of Home even when there are videos, with the link field, «Subir archivos», «Grabar pantalla» and «Varios enlaces»; the big featured video below it is gone (what you're watching stays in its «Seguir viendo» row). Dragging files onto the window shows «Suelta para agregar».

### Changed

- Queue: «Priorizar» left the library (it read like sorting the library) and is **Hacer primero** (Do first) in the Queue; jobs no longer show «en pausa» or a play button (they read like resuming the queue): the title opens the video and right-click has **Abrir el video**.
- Settings › App de escritorio: «Seguir en la bandeja» says Translay still quits when the queue is stopped or has nothing in process.
- Header: «Grabar» (Record) and «Agregar» (Add) as two separate buttons; no more split buttons (Agregar ▾, Ver ▾, Conectar ▾), nor the button that changed its action with use (its preference «Botón Agregar» is gone). The Add panel chooses «Traducir y doblar» or «Solo transcribir» and each source says what it accepts.
- «Preferencias» is now «Ajustes» (Settings), with a gear icon.
- The header logo goes first, on the left, in its own colors (coral with the white mark) instead of the theme's accent; the sidebar button moves to its right.
- Dark theme: bars and cards are darker, just above the page background. Light theme: the page is almost the white of the bars, a little dimmer, instead of gray.
- The header no longer shows «En reposo» or the queue's work: the Queue panel says it, and the header only shows a status without connection or for something specific (looking up a video).
- Collection and library patterns: a solid color with an even dot field instead of Bauhaus shapes (circles, triangles and squares).

### Fixed

- A Spanish video (a Zoom class recorded live) was recognized as English: with noise or a waiting room Whisper said «English» with little confidence and translated everything into English and back. Live detection no longer decides below 50 %, the queue detects from three points of the file, and it confirms a language decided live with the whole file, redoing it if it was wrong.
- A video that isn't translated (already in Spanish) always plays instead of staying in «Preparando» (it waited for a translation that never comes), and when a subtitle's original and translation say the same, only one is shown.
- Record the screen: «Sin conexión» no longer stays forever when only the live transcription didn't connect; a source that stops sending picture says so, one that disappears ends and saves the recording, and a recording the server rejects says why instead of retrying forever.

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
