"""Preferencias guardadas en el servidor (data/prefs.json).

Un solo lugar: el esquema define cada preferencia (tipo, opciones, valor por
defecto, texto) y la vista arma el panel a partir de él. Para agregar una
preferencia nueva basta sumar una entrada a SCHEMA y leerla en la vista.
"""

import json
import threading
from pathlib import Path

# [clave, título, descripción, ícono] — cada sección es una página de Preferencias
SECTIONS = [
    ["bibliotecas", "Bibliotecas", "Tus bibliotecas: cada una con sus videos, colecciones, glosario y forma de importar.", "library"],
    ["apariencia", "Apariencia", "Cómo se ve Translay en esta biblioteca.", "sun"],
    ["video", "Reproducción", "Qué pasa al abrir, terminar o agregar videos mientras miras.", "video"],
    ["audio", "Audio y subtítulos", "Qué escuchas y qué textos aparecen sobre el video.", "speaker"],
    ["biblioteca", "Importar y descargas", "Qué se hace con lo que importas y cómo se descarga.", "download"],
    ["glosario", "Glosario", "Términos con traducción fija o que se dejan en inglés.", "book"],
    ["youtube", "YouTube", "La sesión que se usa para descargar.", "play"],
    ["acceso", "Acceso y API", "Quién entra desde otros equipos, claves de API y webhooks.", "lock"],
]
SCHEMA = [
    # apariencia: claro u oscuro (web/css/tokens.css, web/js/theme.js)
    {"key": "theme_mode", "section": "apariencia", "label": "Modo", "type": "choice", "default": "sistema",
     "options": [["sistema", "Según el sistema"], ["claro", "Claro"], ["oscuro", "Oscuro"]]},
    {"key": "accent_lib", "section": "apariencia", "label": "Color de cada biblioteca", "type": "bool", "default": False},
    {"key": "layout", "section": "video", "label": "Vista del video", "type": "choice", "default": "ampliada",
     "options": [["ampliada", "Ampliada"], ["dividida", "Dividida"]]},
    {"key": "autoplay", "section": "video", "label": "Reproducir al abrir un video", "type": "bool", "default": True},
    {"key": "autoplay_next", "section": "video", "label": "Reproducir el siguiente al terminar", "type": "bool",
     "default": True},
    {"key": "wait_ready", "section": "video", "label": "Pausar hasta que esté listo", "type": "bool",
     "default": True},
    {"key": "add_while_watching", "section": "video", "label": "Al agregar un video mientras ves otro",
     "type": "choice", "default": "siguiente",
     "options": [["siguiente", "Ponerlo a continuación"], ["fondo", "Procesarlo en segundo plano"],
                 ["abrir", "Abrirlo"]]},
    {"key": "ready_chip", "section": "video", "label": "Indicador de reproducción", "type": "choice",
     "default": "auto",
     "options": [["auto", "En pausa o si falta margen"], ["siempre", "Siempre"], ["nunca", "Nunca"]]},
    {"key": "audio", "section": "audio", "label": "Al abrir un video, escuchar", "type": "choice", "default": "es",
     "options": [["es", "En español"], ["original", "Original"]]},
    {"key": "duck", "section": "audio", "label": "Original bajo la voz en español", "type": "choice",
     "default": "bajo", "options": [["silencio", "Silencio"], ["bajo", "Bajo"], ["medio", "Medio"]]},
    {"key": "sub_es", "section": "audio", "label": "Subtítulos en español", "type": "bool", "default": True},
    {"key": "sub_en", "section": "audio", "label": "Subtítulos en inglés", "type": "bool", "default": True},
    {"key": "import_mode", "section": "biblioteca", "label": "Al importar", "type": "choice", "default": "traducir",
     "options": [["traducir", "Descargar y traducir"], ["descargar", "Solo descargar"]]},
    {"key": "download_what", "section": "biblioteca", "label": "Qué descargar", "type": "choice", "default": "video",
     "options": [["video", "Video y audio"], ["audio", "Solo el audio (más rápido)"]]},
    {"key": "download_order", "section": "biblioteca", "label": "Orden de las descargas", "type": "choice",
     "default": "orden", "options": [["orden", "En el orden de la cola"], ["aleatorio", "Aleatorio (variado)"]]},
    {"key": "notify", "section": "biblioteca", "label": "Avisos del navegador", "type": "bool", "default": False},
    {"key": "lib_channels", "section": "biblioteca", "label": "Canales en la barra lateral", "type": "bool",
     "default": True},
    {"key": "yt_session", "section": "youtube", "label": "Sesión para descargar", "type": "choice",
     "default": "ninguna",
     "options": [["ninguna", "No usar"], ["firefox", "Firefox"], ["brave", "Brave"], ["chrome", "Chrome"],
                 ["edge", "Edge"], ["archivo", "Archivo cookies.txt"]]},
]
# grupo (dentro de su página) y descripción de cada opción
DETAILS = {
    "theme_mode": ("Tema", "Claro, oscuro o el que use tu sistema. Cada biblioteca recuerda el suyo."),
    "accent_lib": ("Tema", "Usar el color de la biblioteca abierta en botones, avance y reproducción, en vez del color del tema."),
    "autoplay": ("Al abrir y terminar", "El video empieza solo cuando lo abres."),
    "autoplay_next": ("Al abrir y terminar", "Al terminar, sigue con el próximo de la colección o playlist."),
    "wait_ready": ("Al abrir y terminar", "Si llegas a una parte que aún no tiene voz en español, se pausa y sigue cuando esté lista."),
    "add_while_watching": ("Mientras miras", "Qué hacer con un enlace que importas mientras ves otro video."),
    "layout": ("Vista", "Ampliada: un solo video grande y la transcripción al lado. Dividida: original y traducido lado a lado."),
    "ready_chip": ("Vista", "El aviso «listo para reproducir» sobre el video."),
    "audio": ("Voz", "Con qué audio empieza cada video; se cambia en cualquier momento con ES / EN."),
    "duck": ("Voz", "Qué tan fuerte queda el audio original debajo de la voz en español."),
    "sub_es": ("Subtítulos", "La traducción, abajo del video."),
    "sub_en": ("Subtítulos", "Lo que se dice en inglés, arriba del video."),
    "import_mode": ("Al importar", "Traducir y doblar todo, o solo descargarlo (para verlo o exportar el original)."),
    "download_what": ("Al importar", "Solo el audio es mucho más rápido y ocupa menos; el video se puede bajar después."),
    "download_order": ("Descargas", "Aleatorio descarga variado de toda la cola; lo priorizado siempre va primero."),
    "notify": ("Avisos y vista", "Un aviso del sistema cuando termina una descarga, un video o una exportación."),
    "lib_channels": ("Avisos y vista", "Mostrar los canales de YouTube en la barra lateral de la biblioteca."),
    "yt_session": ("Sesión", "Con tu sesión, YouTube deja bajar videos con restricción de edad y pide menos verificaciones."),
}
for _p in SCHEMA:
    _p["group"], _p["desc"] = DETAILS.get(_p["key"], ("", ""))
_BY_KEY = {p["key"]: p for p in SCHEMA}


class Prefs:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.values = {p["key"]: p["default"] for p in SCHEMA}
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            saved.update(self._migrate(saved))
            for k, v in saved.items():
                if self._valid(k, v):
                    self.values[k] = v

    @staticmethod
    def _migrate(saved: dict) -> dict:
        """La preferencia vieja "theme" (un solo valor) pasa al modo claro u oscuro."""
        old = saved.get("theme")
        if not old or "theme_mode" in saved:
            return {}
        dark = old in ("oscuro", "claude-oscuro", "pink-noche", "cyberpunk", "cyberpunk-electrico", "matrix",
                       "matrix-ambar", "code", "contraste")
        return {"theme_mode": "oscuro" if dark else "claro"}

    @staticmethod
    def _valid(key, value) -> bool:
        p = _BY_KEY.get(key)
        if p is None:
            return False
        if p["type"] == "bool":
            return isinstance(value, bool)
        return value in [o[0] for o in p["options"]]

    def set(self, key: str, value) -> bool:
        if not self._valid(key, value):
            return False
        with self._lock:
            self.values[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.values, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        return True

    def public(self) -> dict:
        return {"type": "prefs", "sections": SECTIONS, "schema": SCHEMA, "values": dict(self.values)}
