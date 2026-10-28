// Data for the docs diagrams (components/Diagram.astro), shared by the English and Spanish pages.
// Layouts are vertical where they would otherwise be wide, so the text keeps its size on a phone.
type Lang = "en" | "es";
const t = (lang: Lang, en: string, es: string) => (lang === "es" ? es : en);

// The page (in the desktop window or a browser) talks to the server over WebSocket; the queue runs
// the models on the GPU and asks the voice process for each line.
export const architecture = (lang: Lang) => ({
  width: 440,
  height: 880,
  label: t(lang,
    "The desktop app opens Translay's web page, which talks to the Python server over HTTP and WebSocket; the server's queue runs Whisper, Opus-MT and WeSpeaker on the GPU and asks the voice process, through pipes, for each line in Spanish.",
    "La app de escritorio abre la página web de Translay, que habla con el servidor en Python por HTTP y WebSocket; la cola del servidor corre Whisper, Opus-MT y WeSpeaker en la GPU y le pide al proceso de voz, por tuberías, cada frase en español."),
  groups: [
    { x: 10, y: 20, w: 420, h: 160, title: t(lang, "Window or browser", "Ventana o navegador"), icon: "app-window" },
    { x: 10, y: 270, w: 420, h: 350, title: t(lang, "Server · Python (vt/)", "Servidor · Python (vt/)"), icon: "server" },
    { x: 10, y: 690, w: 420, h: 170, title: t(lang, "Voice process (.venvs/)", "Proceso de voz (.venvs/)"), icon: "microphone" },
  ],
  nodes: [
    { id: "ui", x: 120, y: 100, icon: "browser", label: t(lang, "Web interface\n(web/)", "Interfaz web\n(web/)") },
    { id: "app", x: 320, y: 100, icon: "device-desktop", label: t(lang, "Desktop app\n(desktop/)", "App de escritorio\n(desktop/)") },
    { id: "http", x: 120, y: 360, icon: "plug-connected", label: t(lang, "HTTP + WebSocket\n(httpws.py)", "HTTP + WebSocket\n(httpws.py)") },
    { id: "queue", x: 120, y: 530, icon: "list-numbers", label: t(lang, "Queue\n(processor.py)", "Cola\n(processor.py)") },
    { id: "models", x: 320, y: 530, icon: "cpu", label: "Whisper · Opus-MT\nWeSpeaker" },
    { id: "voice", x: 120, y: 780, icon: "speakerphone", label: t(lang, "Cloned voice\n(OmniVoice)", "Voz clonada\n(OmniVoice)") },
  ],
  edges: [
    { from: "app", to: "ui", label: t(lang, "opens", "abre"), dashed: true },
    { from: "ui", to: "http", label: "WebSocket /ws" },
    { from: "http", to: "queue", label: t(lang, "session", "sesión") },
    { from: "queue", to: "models", label: "GPU" },
    { from: "queue", to: "voice", label: t(lang, "pipes (ipc.py)", "tuberías (ipc.py)") },
  ],
});

// One line of English becomes one line of Spanish in the speaker's voice.
export const pipeline = (lang: Lang) => ({
  width: 260,
  height: 930,
  label: t(lang,
    "Mono 16 kHz audio goes through voice detection, streaming recognition with Whisper, translation with Opus-MT, speaker diarization and the cloned voice with OmniVoice.",
    "El audio mono a 16 kHz pasa por la detección de voz, el reconocimiento en streaming con Whisper, la traducción con Opus-MT, la diarización y la voz clonada con OmniVoice."),
  nodes: [
    { id: "audio", x: 130, y: 55, icon: "wave-sine", label: t(lang, "Audio\n16 kHz mono", "Audio\n16 kHz mono") },
    { id: "vad", x: 130, y: 220, icon: "ear", label: t(lang, "Voice detection\n(vad.py)", "Detección de voz\n(vad.py)") },
    { id: "asr", x: 130, y: 385, icon: "messages", label: "Whisper\n(streaming.py)" },
    { id: "mt", x: 130, y: 550, icon: "language", label: "Opus-MT\n(translate.py)" },
    { id: "spk", x: 130, y: 715, icon: "users", label: t(lang, "Diarization\n(speakers.py)", "Diarización\n(speakers.py)") },
    { id: "tts", x: 130, y: 875, icon: "speakerphone", label: t(lang, "Cloned voice\n(dub.py)", "Voz clonada\n(dub.py)") },
  ],
  edges: [
    { from: "audio", to: "vad", label: t(lang, "30 ms frames", "tramas de 30 ms") },
    { from: "vad", to: "asr", label: t(lang, "speech", "voz") },
    { from: "asr", to: "mt", label: t(lang, "closed lines", "frases cerradas") },
    { from: "mt", to: "spk", label: t(lang, "Spanish text", "texto en español") },
    { from: "spk", to: "tts", label: t(lang, "voice reference", "referencia de voz") },
  ],
});

// The desktop app: first launch installs the runtime with uv; every launch starts the server and opens its page.
export const desktop = (lang: Lang) => ({
  width: 440,
  height: 620,
  label: t(lang,
    "On first launch the window installs Python environments with the bundled uv from pinned locks; on every launch it starts the hidden server, which prints its address, and the window opens Translay's page.",
    "La primera vez, la ventana instala los entornos de Python con el uv incluido a partir de locks fijados; cada vez, inicia el servidor oculto, que avisa su dirección, y la ventana abre la página de Translay."),
  groups: [
    { x: 10, y: 20, w: 420, h: 160, title: t(lang, "Desktop app · Tauri 2", "App de escritorio · Tauri 2"), icon: "app-window" },
    { x: 10, y: 260, w: 420, h: 170, title: t(lang, "App data (AppData)", "Datos de la app (AppData)"), icon: "folder" },
  ],
  nodes: [
    { id: "win", x: 120, y: 100, icon: "device-desktop", label: t(lang, "Window", "Ventana") },
    { id: "setup", x: 320, y: 100, icon: "download", label: t(lang, "Setup\n(uv + locks)", "Instalación\n(uv + locks)") },
    { id: "server", x: 120, y: 350, icon: "server", label: t(lang, "Server\n(run.py)", "Servidor\n(run.py)") },
    { id: "envs", x: 320, y: 350, icon: "brand-python", label: t(lang, "Python\nenvironments", "Entornos\nde Python") },
    { id: "page", x: 120, y: 550, icon: "browser", label: t(lang, "Translay page", "Página de Translay") },
  ],
  edges: [
    { from: "win", to: "setup", label: t(lang, "first time", "primera vez") },
    { from: "setup", to: "envs", label: t(lang, "creates", "crea") },
    { from: "envs", to: "server", label: t(lang, "runs", "corre") },
    { from: "win", to: "server", label: t(lang, "starts", "inicia") },
    { from: "server", to: "page", label: "127.0.0.1" },
  ],
});
