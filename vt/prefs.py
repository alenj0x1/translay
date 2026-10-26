"""Preferencias guardadas en el servidor (data/prefs.json).

Un solo lugar: el esquema define cada preferencia (tipo, opciones, valor por
defecto, texto) y la vista arma el panel a partir de él. Para agregar una
preferencia nueva basta sumar una entrada a SCHEMA y leerla en la vista.
"""

import json
import threading
from pathlib import Path

SECTIONS = [["apariencia", "Apariencia"], ["video", "Video"], ["audio", "Audio"], ["subtitulos", "Subtítulos"], ["biblioteca", "Biblioteca"], ["youtube", "YouTube"]]
SCHEMA = [
    # apariencia: modo (la base clara u oscura) · tema · tono; el bloque de colores es
    # «tema-tono-modo» en web/css/tokens.css (ver web/js/theme.js)
    {"key": "theme_mode", "section": "apariencia", "label": "Modo", "type": "choice", "default": "sistema",
     "options": [["sistema", "Según el sistema"], ["claro", "Claro"], ["oscuro", "Oscuro"]]},
    {"key": "theme_style", "section": "apariencia", "label": "Tema", "type": "choice", "default": "clasico",
     "options": [["clasico", "Clásico"], ["claude", "Claude"], ["pastel", "Pastel"], ["pink", "Pink"],
                 ["cyberpunk", "Cyberpunk"], ["matrix", "Matrix"], ["code", "Code"], ["contraste", "Alto contraste"]]},
    {"key": "theme_tone", "section": "apariencia", "label": "Tono", "type": "choice", "default": "",
     "options": [["", "—"], ["lavanda", "Lavanda"], ["menta", "Menta"], ["durazno", "Durazno"], ["cielo", "Cielo"],
                 ["neon", "Neón"], ["electrico", "Eléctrico"], ["verde", "Verde"], ["ambar", "Ámbar"]]},
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
    {"key": "sub_es", "section": "subtitulos", "label": "Subtítulos en español", "type": "bool", "default": True},
    {"key": "sub_en", "section": "subtitulos", "label": "Subtítulos en inglés", "type": "bool", "default": True},
    {"key": "lib_channels", "section": "biblioteca", "label": "Canales en la barra lateral", "type": "bool",
     "default": True},
    {"key": "yt_session", "section": "youtube", "label": "Sesión para descargar", "type": "choice",
     "default": "ninguna",
     "options": [["ninguna", "No usar"], ["firefox", "Firefox"], ["brave", "Brave"], ["chrome", "Chrome"],
                 ["edge", "Edge"], ["archivo", "Archivo cookies.txt"]]},
]
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
        """La preferencia vieja "theme" (un solo valor) pasa a modo · tema · tono."""
        old = saved.get("theme")
        if not old or "theme_style" in saved:
            return {}
        table = {"claro": ("claro", "clasico", ""), "oscuro": ("oscuro", "clasico", ""),
                 "claude": ("claro", "claude", ""), "claude-oscuro": ("oscuro", "claude", ""),
                 "pastel": ("claro", "pastel", "lavanda"), "pastel-menta": ("claro", "pastel", "menta"),
                 "pastel-durazno": ("claro", "pastel", "durazno"), "pastel-cielo": ("claro", "pastel", "cielo"),
                 "pink": ("claro", "pink", ""), "pink-noche": ("oscuro", "pink", ""),
                 "cyberpunk": ("oscuro", "cyberpunk", "neon"), "cyberpunk-electrico": ("oscuro", "cyberpunk", "electrico"),
                 "matrix": ("oscuro", "matrix", "verde"), "matrix-ambar": ("oscuro", "matrix", "ambar"),
                 "code": ("oscuro", "code", ""), "code-claro": ("claro", "code", ""),
                 "contraste": ("oscuro", "contraste", "")}
        mode, style, tone = table.get(old, ("sistema", "clasico", ""))
        return {"theme_mode": mode, "theme_style": style, "theme_tone": tone}

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
