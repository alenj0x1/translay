"""Ajustes guardados en el servidor (data/prefs.json).

Un solo lugar: el esquema define cada preferencia (tipo, opciones, valor por
defecto, texto) y la vista arma el panel a partir de él. Para agregar una
preferencia nueva basta sumar una entrada a SCHEMA y leerla en la vista.
"""

import json
import threading
from pathlib import Path

from . import langs, llm, summarize

# [clave, título, descripción, ícono, solo en el modo] — cada sección es una página de Ajustes. Con el
# quinto valor, la página solo aparece en ese modo de la app (app_mode); ALT_SECTIONS: otro título en el otro
SECTIONS = [
    ["uso", "Uso", "Traducir y doblar, o solo transcribir y resumir.", "sliders"],
    ["bibliotecas", "Bibliotecas", "Tus bibliotecas: cada una con sus videos, colecciones, glosario y forma de importar.", "library"],
    ["apariencia", "Apariencia", "Cómo se ve Translay en esta biblioteca.", "sun"],
    ["video", "Reproducción", "Comportamiento al abrir, terminar o agregar videos durante la reproducción.", "video"],
    ["audio", "Audio y subtítulos", "Audio y textos que se muestran sobre el video.", "speaker"],
    ["biblioteca", "Agregar y descargar", "Qué hacer al agregar videos y la sesión de YouTube para descargarlos.", "download"],
    ["agente", "Agente", "Asistente de cada video: nombre, apariencia, estilo de respuesta y modelo.", "agent"],
    ["exportar", "Exportar", "Ubicación de los archivos exportados.", "download"],
    ["glosario", "Glosario", "Términos con traducción fija o que se dejan como en el original.", "book", "traducir"],
    ["acceso", "Acceso y API", "Acceso desde otros equipos, claves de API y webhooks.", "lock"],
    ["rendimiento", "Rendimiento", "Tu equipo, los modelos de Translay y los límites de GPU, RAM y CPU.", "spark"],
    ["almacenamiento", "Almacenamiento", "Espacio que ocupa Translay y qué puedes liberar.", "drive"],
    ["papelera", "Papelera", "Elementos eliminados en los últimos 30 días. Puedes restaurarlos.", "trash"],
]
SCHEMA = [
    # modo de la app: traducir y doblar, o solo transcribir y resumir (sin nada de traducción ni voz)
    {"key": "app_mode", "section": "uso", "label": "Usar Translay para", "type": "choice", "default": "traducir",
     "options": [["traducir", "Traducir y doblar"], ["transcribir", "Transcribir y resumir"]]},
    # idioma (vt/langs.py): uno solo para la interfaz, la traducción, el agente y los resúmenes; se elige al
    # empezar (por defecto, el del sistema). «Traducir a» lo separa para la traducción y la voz
    {"key": "language", "section": "uso", "label": "Idioma", "type": "choice", "default": "",
     "options": [["", "Del sistema"]] + [[c, langs.NATIVE[c]] for c in langs.TARGETS]},
    {"key": "target_lang", "section": "uso", "label": "Traducir a", "type": "choice", "default": "",
     "options": [["", "El idioma de la app"]] + [[c, langs.NATIVE[c]] for c in langs.TARGETS]},
    # rendimiento (vt/perf.py, web/js/perf.js): con su propia pantalla, no en filas
    {"key": "perf_profile", "section": "_perf", "label": "Perfil", "type": "choice", "default": "auto",
     "options": [["auto", "Automático"], ["calidad", "Máxima calidad"], ["equilibrado", "Equilibrado"],
                 ["ligero", "Ligero"], ["texto", "Solo subtítulos"], ["texto-ligero", "Subtítulos ligeros"]]},
    {"key": "limit_vram_mb", "section": "_perf", "label": "VRAM", "type": "choice", "default": 0,
     "options": [[0, "Sin límite"], [1024, "1 GB"], [2048, "2 GB"], [3072, "3 GB"], [4096, "4 GB"], [5120, "5 GB"], [6144, "6 GB"], [7168, "7 GB"], [8192, "8 GB"], [10240, "10 GB"], [12288, "12 GB"], [16384, "16 GB"], [24576, "24 GB"]]},
    {"key": "limit_ram_mb", "section": "_perf", "label": "RAM", "type": "choice", "default": 0,
     "options": [[0, "Sin límite"], [2048, "2 GB"], [3072, "3 GB"], [4096, "4 GB"], [6144, "6 GB"], [8192, "8 GB"], [10240, "10 GB"], [12288, "12 GB"], [16384, "16 GB"], [24576, "24 GB"], [32768, "32 GB"], [49152, "48 GB"], [65536, "64 GB"]]},
    {"key": "models_prune", "section": "_perf", "label": "Borrar modelos que no se usan", "type": "bool", "default": False},
    {"key": "limit_threads", "section": "_perf", "label": "Hilos", "type": "choice", "default": 0,
     "options": [[0, "Sin límite"], [1, "1 hilo"], [2, "2 hilos"], [3, "3 hilos"], [4, "4 hilos"], [6, "6 hilos"], [8, "8 hilos"], [10, "10 hilos"], [12, "12 hilos"], [16, "16 hilos"], [20, "20 hilos"], [24, "24 hilos"], [32, "32 hilos"], [48, "48 hilos"], [64, "64 hilos"]]},
    # apariencia: claro u oscuro (web/css/tokens.css, web/js/theme.js)
    {"key": "theme_mode", "section": "apariencia", "label": "Modo", "type": "choice", "default": "sistema",
     "options": [["sistema", "Según el sistema"], ["claro", "Claro"], ["oscuro", "Oscuro"]]},
    {"key": "accent_color", "section": "apariencia", "label": "Color de énfasis", "type": "choice", "default": "#7d5ba6",
     "options": [["", "Del tema"], ["#e4572e", "Coral"], ["#f3a712", "Ámbar"], ["#29bf12", "Verde"], ["#00a5cf", "Celeste"],
                 ["#7d5ba6", "Violeta"], ["#e84f9b", "Rosa"], ["#8d6e63", "Café"]]},
    # el fondo del inicio (web/js/home.js › homeLight): una escena ASCII con los colores del tema (web/js/scenes.js)
    # o una imagen propia
    {"key": "home_bg", "section": "apariencia", "label": "Fondo", "type": "choice", "default": "translay",
     "options": [["translay", "Translay"], ["recorrido", "Recorrido"], ["luna", "Luna"], ["tierra", "Tierra"], ["nubes", "Nubes"],
                 ["atardecer", "Atardecer"], ["mar", "Fondo marino"], ["arrecife", "Arrecife"], ["ballena", "Ballena"], ["medusas", "Medusas"],
                 ["abismo", "Abismo"], ["naufragio", "Naufragio"], ["arañas", "Arañas"], ["arañas y perro", "Arañas, Shade y Manchita"],
                 ["imagen", "Imagen propia"]]},
    # la escena de fondo (web/js/scenes.js) se detiene sola para dejarle el equipo a lo que importa
    {"key": "bg_pause_video", "section": "apariencia", "label": "Pausar al reproducir un video", "type": "bool", "default": True},
    {"key": "bg_pause_blur", "section": "apariencia", "label": "Pausar con la ventana en segundo plano", "type": "bool", "default": True},
    {"key": "home_bg_rev", "section": "_inicio", "label": "Imagen del inicio", "type": "text", "default": "", "max": 20},
    # la bienvenida de primer uso (web/js/welcome.js) ya se vio o se omitió: no vuelve a abrirse
    {"key": "welcomed", "section": "_inicio", "label": "Bienvenida", "type": "bool", "default": False},
    {"key": "accent_lib", "section": "apariencia", "label": "Color de cada biblioteca", "type": "bool", "default": False},
    # colores del código que aparece en los videos (web/js/codetheme.js): la transcripción y el agente
    {"key": "code_theme", "section": "apariencia", "label": "Colores del código", "type": "choice", "default": "vscode-dark",
     "options": [["vscode-dark", "Visual Studio Code Dark"], ["one-dark", "One Dark"], ["catppuccin-mocha", "Catppuccin Mocha"],
                 ["catppuccin-latte", "Catppuccin Latte"], ["dracula", "Dracula"], ["monokai", "Monokai"], ["nord", "Nord"],
                 ["github-light", "GitHub Light"]]},
    {"key": "layout", "section": "video", "label": "Vista del video", "type": "choice", "default": "ampliada",
     "options": [["ampliada", "Ampliada"], ["dividida", "Dividida"]]},
    {"key": "autoplay", "section": "video", "label": "Reproducir al abrir un video", "type": "bool", "default": True},
    {"key": "autoplay_next", "section": "video", "label": "Reproducir el siguiente al terminar", "type": "bool",
     "default": True},
    {"key": "wait_ready", "section": "video", "label": "Pausar hasta que esté listo", "type": "bool",
     "default": True},
    {"key": "add_while_watching", "section": "video", "label": "Al agregar un video mientras ves otro",
     "type": "choice", "default": "siguiente",
     "options": [["siguiente", "Reproducir a continuación"], ["fondo", "Procesar en segundo plano"],
                 ["abrir", "Abrir"]]},
    {"key": "ready_chip", "section": "video", "label": "Indicador de reproducción", "type": "choice",
     "default": "auto",
     "options": [["auto", "En pausa o con poco margen"], ["siempre", "Siempre"], ["nunca", "Nunca"]]},
    {"key": "audio", "section": "audio", "label": "Audio al abrir un video", "type": "choice", "default": "es",
     "options": [["es", "Doblado"], ["original", "Original"]]},
    # vt/separation.py: el fondo (música y efectos) separado de la voz original, debajo de la voz doblada
    {"key": "bg_separate", "section": "audio", "label": "Fondo sin la voz original", "type": "bool", "default": True},
    {"key": "duck", "section": "audio", "label": "Volumen del audio original", "type": "choice",
     "default": "bajo", "options": [["silencio", "Silencio"], ["bajo", "Bajo"], ["medio", "Medio"]]},
    {"key": "sub_es", "section": "audio", "label": "Subtítulos traducidos", "type": "bool", "default": True},
    {"key": "sub_orig", "section": "audio", "label": "Subtítulos del original", "type": "bool", "default": True},
    # texto en pantalla (vt/screentext.py): lo escrito en el video, traducido encima en el mismo lugar
    {"key": "screen_text", "section": "audio", "label": "Texto del video traducido", "type": "bool", "default": True},
    {"key": "import_mode", "section": "biblioteca", "label": "Al agregar", "type": "choice", "default": "traducir",
     "options": [["traducir", "Descargar y traducir"], ["descargar", "Solo descargar"]]},
    {"key": "download_what", "section": "biblioteca", "label": "Qué descargar", "type": "choice", "default": "video",
     "options": [["video", "Video y audio"], ["audio", "Solo el audio (más rápido)"]]},
    {"key": "transcribe_lang", "section": "biblioteca", "label": "Solo transcribir videos en",
     "type": "choice", "default": "",
     # del registro de idiomas (vt/langs.py); «» = el idioma al que se traduce (lo que ya está en él no se traduce)
     "options": [["", "El idioma al que traduces"]] + [[c, langs.NATIVE[c]] for c in langs.SOURCES]
                + [["ninguno", "Ningún otro"]]},
    {"key": "download_order", "section": "biblioteca", "label": "Orden de las descargas", "type": "choice",
     "default": "orden", "options": [["orden", "En el orden de la cola"], ["aleatorio", "Aleatorio"]]},
    # vt/appmute.py: en Windows 10 una ventana graba el sonido de todo el equipo
    {"key": "rec_mute_others", "section": "biblioteca", "label": "Silenciar las otras apps al grabar una ventana",
     "type": "bool", "default": False},
    {"key": "notify", "section": "biblioteca", "label": "Notificaciones del navegador", "type": "bool", "default": False},
    {"key": "lib_channels", "section": "biblioteca", "label": "Canales en la barra lateral", "type": "bool",
     "default": True},
    # el agente de cada video (vt/agentsvc.py): su nombre, cómo se ve, cómo responde y su modelo
    {"key": "agent_name", "section": "agente", "label": "Nombre", "type": "text", "default": "Translay", "max": 32},
    # el agente es una estrella que se arma a gusto (web/js/star.js): JSON con ojos, boca, mejillas y accesorio
    {"key": "agent_avatar", "section": "agente", "label": "Avatar", "type": "text", "default": "", "max": 400},
    {"key": "agent_color", "section": "agente", "label": "Color", "type": "choice", "default": "",
     "options": [["", "Del tema"], ["#e4572e", "Coral"], ["#f3a712", "Ámbar"], ["#29bf12", "Verde"], ["#00a5cf", "Celeste"],
                 ["#7d5ba6", "Violeta"], ["#e84f9b", "Rosa"], ["#8d6e63", "Café"]]},
    {"key": "agent_tone", "section": "agente", "label": "Estilo de respuesta", "type": "text", "default": "", "max": 600,
     "multiline": True},
    {"key": "agent_model", "section": "agente", "label": "Modelo", "type": "choice", "default": "auto",
     "options": [["auto", "Automático"]] + [[k, m.name] for k, m in llm.MODELS.items()]},
    {"key": "agent_device", "section": "agente", "label": "Dispositivo", "type": "choice", "default": "auto",
     "options": [["auto", "Automático"], ["gpu", "Tarjeta gráfica"], ["igpu", "Integrada"], ["cpu", "Procesador"]]},
    # cuánto del equipo usa el agente en lo que hace solo (resumen, descripción, preparar): vt/agentsvc.py
    {"key": "agent_usage", "section": "agente", "label": "Uso del equipo", "type": "range", "default": 50,
     "min": 25, "max": 100, "step": 5, "stops": [25, 50, 75, 100], "unit": "%"},
    # resumen (vt/summaries.py): manual con el botón Resumir o al terminar de procesar cada video
    {"key": "summary_mode", "section": "agente", "label": "Resumir", "type": "choice", "default": "auto",
     "options": [["manual", "Manualmente"], ["auto", "Al procesar cada video"]]},
    # exportar en este equipo: preguntar con el cuadro de Windows (en la última carpeta) o una carpeta fija;
    # desde otro equipo, el navegador decide dónde se descarga
    {"key": "export_ask", "section": "exportar", "label": "Al exportar", "type": "choice", "default": "preguntar",
     "options": [["preguntar", "Preguntar dónde guardar"], ["carpeta", "Guardar siempre en una carpeta"]]},
    {"key": "export_dir", "section": "_export", "label": "Carpeta", "type": "path", "default": ""},
    {"key": "export_last_dir", "section": "_export", "label": "Última carpeta", "type": "path", "default": ""},
    {"key": "yt_session", "section": "biblioteca", "label": "Sesión para descargar", "type": "choice",
     "default": "ninguna",
     "options": [["ninguna", "Ninguna"], ["cuenta", "Cuenta conectada"], ["firefox", "Firefox"], ["brave", "Brave"], ["chrome", "Chrome"],
                 ["edge", "Edge"], ["archivo", "Archivo cookies.txt"]]},
]
# grupo (dentro de su página) y descripción de cada opción
DETAILS = {
    "app_mode": ("", "Transcribir y resumir oculta la traducción y la voz. Puedes agregar o grabar videos, leer su "
                 "transcripción y generar resúmenes. Lo ya traducido se conserva."),
    "models_prune": ("Rendimiento", "Al reiniciar con otro perfil, borra los modelos que no usa. Se desactiva después de aplicarse."),
    "theme_mode": ("Tema", "Claro, oscuro o según el sistema. Cada biblioteca guarda su propio modo."),
    "accent_color": ("Tema", "El color de botones, avance y reproducción."),
    "home_bg": ("Fondo", "Una escena animada hecha de caracteres, o una imagen tuya. Va detrás de todas las pantallas."),
    "bg_pause_video": ("Fondo", "La escena se detiene mientras se reproduce un video y sigue al pausarlo."),
    "bg_pause_blur": ("Fondo", "La escena se detiene cuando usas otra ventana y sigue al volver a Translay."),
    "accent_lib": ("Tema", "Usar el color de la biblioteca abierta en vez del color de énfasis."),
    "code_theme": ("Código", "Los colores del código, los comandos y los comentarios que aparecen escritos en los videos. "
                               "Cada tema cambia a su versión clara u oscura con el modo de la app."),
    "autoplay": ("Al abrir y terminar", "El video se reproduce automáticamente al abrirlo."),
    "autoplay_next": ("Al abrir y terminar", "Al terminar, reproduce el siguiente de la colección o playlist."),
    "wait_ready": ("Al abrir y terminar", "Si una parte aún no tiene voz doblada, se pausa y se reanuda cuando esté lista."),
    "add_while_watching": ("Durante la reproducción", "Qué hacer con un enlace que importas mientras ves otro video."),
    "layout": ("Vista", "Ampliada: un solo video grande y la transcripción al lado. Dividida: original y traducido lado a lado."),
    "ready_chip": ("Vista", "El aviso «listo para reproducir» sobre el video."),
    "audio": ("Voz", "Audio con el que empieza cada video. Puedes cambiarlo en cualquier momento desde el reproductor."),
    "bg_separate": ("Voz", "Separa la música y los efectos de la voz original al terminar de doblar un video, para que "
                    "la voz doblada suene sobre el fondo entero sin el idioma original debajo. Necesita el motor de voz."),
    "duck": ("Voz", "Volumen del audio original bajo la voz doblada, en lo que aún no tiene el fondo separado."),
    "sub_es": ("Subtítulos", "La traducción, en la parte inferior del video."),
    "sub_orig": ("Subtítulos", "La transcripción en el idioma original, en la parte superior del video."),
    "screen_text": ("Subtítulos", "Detecta el texto del video (títulos, letreros, diapositivas) y muestra su "
                    "traducción encima, en el mismo lugar. El código, los comandos y los enlaces se dejan como están; "
                    "los comentarios del código sí se traducen."),
    "transcribe_lang": ("Al agregar", "Un video en este idioma se transcribe sin traducir ni doblar, además de los que "
                        "ya están en el idioma al que traduces. Translay detecta el idioma de cada video; en cada uno se "
                        "puede cambiar."),
    "language": ("Idioma", "El idioma de Translay: la interfaz, la traducción y la voz, el agente y los resúmenes."),
    "target_lang": ("Idioma", "Al cambiarlo, los videos se traducen y doblan a este idioma al abrirlos. Lo ya "
                    "traducido a otros idiomas se conserva y vuelve si lo eliges de nuevo."),
    "import_mode": ("Al agregar", "Traducir y doblar todo, o solo descargarlo (para verlo o exportar el original)."),
    "download_what": ("Al agregar", "Descargar solo el audio es más rápido y ocupa menos espacio. El video se puede descargar después."),
    "download_order": ("Descargas", "En modo aleatorio se descarga de toda la cola en orden variado. Los videos priorizados siempre van primero."),
    "rec_mute_others": ("Grabar pantalla", "En Windows 10 una ventana graba el sonido de todo el equipo. Esto silencia las demás "
                        "aplicaciones mientras grabas y les devuelve el sonido al terminar. En Windows 11 no hace falta."),
    "notify": ("Notificaciones y vista", "Notificación del sistema al terminar una descarga, un video o una exportación."),
    "lib_channels": ("Notificaciones y vista", "Mostrar los canales de YouTube en la barra lateral de la biblioteca."),
    "agent_name": ("Apariencia", "Nombre que se muestra en la pestaña del video y en las respuestas."),
    "agent_avatar": ("Apariencia", "Arma tu agente: ojos, boca y un accesorio. Toma el color elegido abajo, piensa y responde con gestos."),
    "agent_color": ("Apariencia", "Color del avatar, de las respuestas y de las marcas de tiempo. «Del tema» usa el color de énfasis de la app."),
    "agent_tone": ("Estilo de respuesta", "Instrucción libre sobre el tono, la extensión o el público. Por ejemplo, "
                   "«explícame como a alguien que recién empieza, con ejemplos» o «respuestas cortas y en viñetas»."),
    "agent_model": ("Modelo", "Automático usa el que mejor responde en tu equipo (medido en GPU, gráfica integrada y "
                    "solo procesador). La lista indica cuáles son compatibles con tu equipo, qué tan bien respondieron en el "
                    "laboratorio y cuáles ya están descargados. Los nuevos se descargan aquí o con la primera pregunta. "
                    "Se borran en Almacenamiento."),
    "agent_device": ("Modelo", "Automático usa la tarjeta gráfica si tiene memoria libre; si no, la gráfica integrada "
                     "o el procesador."),
    "agent_usage": ("Modelo", "Lo que el agente hace solo (el resumen, la descripción de cada video, prepararse al "
                    "encender) se detiene entre tandas para dejar la tarjeta gráfica y el procesador a tus otros programas. "
                    "Con menos, el resto del equipo va más fluido y eso tarda más. Tus preguntas siempre van a toda velocidad. "
                    "Sin tarjeta gráfica, también limita los núcleos del procesador que usa."),
    "summary_mode": ("Resumen", "Manualmente, desde «Generar el resumen» en las sugerencias del agente. Al procesar, se genera automáticamente "
                     "al terminar la transcripción (usa la GPU unos minutos por video)."),
    "export_ask": ("Dónde guardar", "Preguntar abre el diálogo de Windows en la última carpeta usada. Desde otro "
                   "equipo, lo exportado se descarga con el navegador."),
    "yt_session": ("Sesión", "Con tu sesión, YouTube permite descargar videos con restricción de edad y solicita menos verificaciones."),
}
# solo en un modo de la app (las de traducción y voz no aparecen al solo transcribir)
ONLY = {k: "traducir" for k in ("layout", "wait_ready", "ready_chip", "audio", "duck", "bg_separate", "sub_es", "transcribe_lang",
                                 "screen_text")}
# otro texto en el modo «transcribir»: {clave: {"label", "desc", "options"}}
ALT = {
    "sub_orig": {"label": "Subtítulos", "desc": "La transcripción, sobre el video."},
    "import_mode": {"desc": "Transcribir todo lo que agregas, o solo descargarlo (para verlo o exportar el original).",
                    "options": [["traducir", "Descargar y transcribir"], ["descargar", "Solo descargar"]]},
}
ALT_SECTIONS = {"audio": ["Subtítulos", "Texto que se muestra sobre el video."]}
# bloques del inicio de Ajustes y de su barra lateral (web/js/app.js › renderPrefsHome); «escritorio» es la página
# que agrega la app de escritorio (web/js/desktop.js)
SECTION_GROUPS = [
    ["General", ["uso", "apariencia", "escritorio"]],
    ["Mirar", ["video", "audio", "agente"]],
    ["Videos", ["biblioteca", "exportar", "glosario"]],
    ["Bibliotecas y acceso", ["bibliotecas", "acceso"]],
    ["Equipo", ["rendimiento", "almacenamiento", "papelera"]],
]
for _p in SCHEMA:
    _p["group"], _p["desc"] = DETAILS.get(_p["key"], ("", ""))
    if _p["key"] in ONLY:
        _p["only"] = ONLY[_p["key"]]
    if _p["key"] in ALT:
        _p["alt"] = ALT[_p["key"]]
_BY_KEY = {p["key"]: p for p in SCHEMA}


class Prefs:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.listeners = []  # f(clave, valor) después de cada cambio guardado
        self.values = {p["key"]: p["default"] for p in SCHEMA}
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved.update(self._migrate(saved))
            for k, v in saved.items():
                if self._valid(k, v):
                    self.values[k] = v

    @staticmethod
    def _migrate(saved: dict) -> dict:
        """Ajustes de antes con otro nombre: "theme" (un solo valor) pasa al modo claro u
        oscuro; "sub_en" (subtítulos en inglés) a "sub_orig" (los del idioma del video); sin
        "language", el español de siempre."""
        out = {}
        if isinstance(saved.get("agent_avatar"), str) and not saved["agent_avatar"].startswith("{"):
            out["agent_avatar"] = ""  # el ícono de antes («agent», «star»…): pasa a la estrella por defecto
        if saved and "language" not in saved:
            out["language"] = "es"  # de antes de los idiomas: todo estaba en español, aunque el sistema no lo esté
        if "sub_en" in saved and "sub_orig" not in saved:
            out["sub_orig"] = saved["sub_en"]
        old = saved.get("theme")
        if old and "theme_mode" not in saved:
            dark = old in ("oscuro", "claude-oscuro", "pink-noche", "cyberpunk", "cyberpunk-electrico", "matrix",
                           "matrix-ambar", "code", "contraste")
            out["theme_mode"] = "oscuro" if dark else "claro"
        return out

    @staticmethod
    def _valid(key, value) -> bool:
        p = _BY_KEY.get(key)
        if p is None:
            return False
        if p["type"] == "bool":
            return isinstance(value, bool)
        if p["type"] == "path":  # una carpeta de este equipo (la elige el cuadro de Windows)
            return isinstance(value, str) and len(value) < 1000
        if p["type"] == "text":  # texto libre (el nombre y el tono del agente)
            return isinstance(value, str) and len(value) <= p.get("max", 200)
        if p["type"] == "range":  # una cantidad (deslizador)
            return isinstance(value, (int, float)) and not isinstance(value, bool) and p["min"] <= value <= p["max"]
        return value in [o[0] for o in p["options"]]

    def set(self, key: str, value) -> bool:
        if not self._valid(key, value):
            return False
        with self._lock:
            self.values[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.values, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        for f in self.listeners:
            f(key, value)
        return True

    @staticmethod
    def kind(key: str) -> str:
        return (_BY_KEY.get(key) or {}).get("type", "")

    def public(self) -> dict:
        """Esquema y valores para la vista; los textos, en el idioma de la app (vt/i18n.py)."""
        from . import i18n

        ui = self.ui_lang
        schema = [{**p, **{k: i18n.tree(p[k], ui) for k in ("label", "group", "desc", "alt") if k in p},
                   **({"options": [[o[0], i18n.t(o[1], ui)] + o[2:] for o in p["options"]]} if "options" in p else {})}
                  for p in SCHEMA]
        return {"type": "prefs", "sections": [s[:1] + i18n.tree(s[1:3], ui) + s[3:] for s in SECTIONS],
                "schema": schema, "values": dict(self.values), "alt_sections": i18n.tree(ALT_SECTIONS, ui),
                "groups": [[i18n.t(n, ui), keys] for n, keys in SECTION_GROUPS], "lang": ui}

    @property
    def ui_lang(self) -> str:
        """Idioma de la interfaz, el agente y los resúmenes: el elegido o el del sistema."""
        return self.values.get("language") or langs.system()

    @property
    def target(self) -> str:
        """Idioma al que se traduce y dobla: «Traducir a» o, si no, el de la app."""
        return self.values.get("target_lang") or self.ui_lang

    @property
    def own_lang(self) -> str | None:
        """Además del destino, el idioma que solo se transcribe («Solo transcribir videos en»)."""
        v = self.values.get("transcribe_lang")
        return v if langs.is_source(v) else None

    @property
    def translating(self) -> bool:
        """¿La app traduce y dobla? En «Transcribir y resumir» no hay traducción ni voz."""
        return self.values.get("app_mode") != "transcribir"
