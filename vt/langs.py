"""Registro de idiomas: todo lo que cambia de un idioma a otro, como datos.

Cada idioma dice cómo lo llaman los motores (Whisper, NLLB, Opus-MT, FFmpeg) y cómo
se nombra en la interfaz. Agregar un idioma es agregar una entrada aquí (y sus
reglas de texto en `vt/textproc.py`, si las tiene); el resto del código no nombra
idiomas.

  SOURCES   idiomas que se reconocen en un video (lo que se habla)
  TARGETS   idiomas a los que se traduce y dobla
  TARGET    el destino de hoy: español latinoamericano

Se traduce cuando el idioma del video no es el destino y la persona no eligió «solo
transcribir» (ver `vt/store.py`).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Lang:
    code: str   # ISO 639-1: el de Whisper, la API y los datos guardados
    name: str   # en español, para la interfaz («inglés»)
    iso3: str   # ISO 639-2/B: metadatos de FFmpeg y etiqueta de Opus-MT multilingüe (>>spa<<)
    nllb: str   # token de NLLB-200 (escritura incluida)
    tts: str    # nombre que esperan los motores de voz


LANGS: dict[str, Lang] = {
    "en": Lang("en", "inglés", "eng", "eng_Latn", "English"),
    "es": Lang("es", "español", "spa", "spa_Latn", "Spanish"),
    "pt": Lang("pt", "portugués", "por", "por_Latn", "Portuguese"),
}
SOURCES = ("en", "pt", "es")
TARGETS = ("es",)
TARGET = "es"
DEFAULT_SOURCE = "en"  # idioma de un video cuando no se sabe (datos de antes de los idiomas)


def get(code: str | None) -> Lang:
    return LANGS[code if code in LANGS else DEFAULT_SOURCE]


def is_source(code) -> bool:
    return code in SOURCES


def name(code: str | None) -> str:
    return get(code).name
