"""Registro de idiomas: todo lo que cambia de un idioma a otro, como datos.

Cada idioma dice cómo lo llaman los motores (Whisper, NLLB, Opus-MT, FFmpeg) y cómo
se nombra en la interfaz. Agregar un idioma es agregar una entrada aquí (y sus
reglas de texto en `vt/textproc.py`, si las tiene); el resto del código no nombra
idiomas.

  SOURCES   idiomas que se reconocen en un video (lo que se habla)
  TARGETS   idiomas a los que se traduce y dobla (y en los que se ve la interfaz)
  target()  el destino elegido en Ajustes («Traducir a»; por defecto, el idioma de la app)

Se traduce cuando el idioma del video no es el destino y la persona no eligió «solo
transcribir» (ver `vt/store.py`).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    code: str   # ISO 639-1: el de Whisper, la API y los datos guardados
    name: str   # en español («inglés»); para otros idiomas de interfaz, ver NAMES
    iso3: str   # ISO 639-2/B: metadatos de FFmpeg y etiqueta de Opus-MT multilingüe (>>spa<<)
    nllb: str   # token de NLLB-200 (escritura incluida)
    tts: str    # nombre que esperan los motores de voz


LANGS: dict[str, Lang] = {
    "en": Lang("en", "inglés", "eng", "eng_Latn", "English"),
    "es": Lang("es", "español", "spa", "spa_Latn", "Spanish"),
    "pt": Lang("pt", "portugués", "por", "por_Latn", "Portuguese"),
}
SOURCES = ("en", "pt", "es")
TARGETS = ("es", "en", "pt")
DEFAULT_TARGET = "es"  # el de antes de los idiomas: lo guardado sin idioma de destino está en español
DEFAULT_SOURCE = "en"  # idioma de un video cuando no se sabe (datos de antes de los idiomas)

# nombre de cada idioma en cada idioma de interfaz: NAMES[interfaz][idioma]
NAMES = {
    "es": {"en": "inglés", "es": "español", "pt": "portugués"},
    "en": {"en": "English", "es": "Spanish", "pt": "Portuguese"},
    "pt": {"en": "inglês", "es": "espanhol", "pt": "português"},
}
# cómo se llama cada idioma a sí mismo (para elegirlo sin entender el actual)
NATIVE = {"es": "Español", "en": "English", "pt": "Português"}

# cómo se le pide a un modelo de lenguaje que responda en cada idioma (los prompts están en inglés)
PROMPT = {"es": "Latin American Spanish", "en": "English", "pt": "Brazilian Portuguese"}

_target = DEFAULT_TARGET
_ui = DEFAULT_TARGET


def ui() -> str:
    """Idioma de la app (Ajustes › Idioma): la interfaz, el agente y los resúmenes."""
    return _ui


def set_ui(code: str) -> bool:
    global _ui
    if code not in TARGETS or code == _ui:
        return False
    _ui = code
    return True


def target() -> str:
    """Idioma al que se traduce y dobla ahora (Ajustes › «Traducir a»)."""
    return _target


def set_target(code: str) -> bool:
    """Cambia el destino. True si cambió."""
    global _target
    if code not in TARGETS or code == _target:
        return False
    _target = code
    return True


def is_target(code) -> bool:
    return code in TARGETS


def get(code: str | None) -> Lang:
    return LANGS[code if code in LANGS else DEFAULT_SOURCE]


def is_source(code) -> bool:
    return code in SOURCES


def name(code: str | None, ui: str = "es") -> str:
    """Nombre del idioma en el idioma de la interfaz `ui` (en minúscula donde se escribe así)."""
    return NAMES.get(ui, NAMES["es"]).get(code) or get(code).name


def system() -> str:
    """Idioma del sistema, si es uno de la interfaz (si no, inglés). En Windows, el de la interfaz de Windows."""
    import locale
    import sys

    code = ""
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                code = buf.value
        except Exception:  # noqa: BLE001
            code = ""
    if not code:
        code = (locale.getlocale()[0] or "")
    code = code.replace("_", "-").split("-")[0].lower()
    return code if code in TARGETS else "en"
