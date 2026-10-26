"""Eventos de la app, para los webhooks (vt/webhooks.py) y quien quiera escucharlos.

    from . import events
    events.emit("video.procesado", vault="ciencia", video="yt_…", title="…")

Cada evento lleva el id de su biblioteca (o None si es general: la cola, YouTube).
"""

import threading

# nombre → descripción (la vista arma la lista de eventos para elegir a partir de esto)
CATALOG = {
    "video.agregado": "Videos agregados a una biblioteca",
    "video.descargado": "Video descargado",
    "video.procesado": "Video traducido y doblado",
    "video.error": "Video con error",
    "video.movido": "Videos movidos a otra biblioteca",
    "video.eliminado": "Videos eliminados",
    "coleccion.creada": "Colección o playlist creada",
    "coleccion.cambio": "Colección cambiada (videos o nombre)",
    "coleccion.eliminada": "Colección eliminada",
    "biblioteca.creada": "Biblioteca creada",
    "biblioteca.cambio": "Biblioteca cambiada (nombre, acceso)",
    "biblioteca.eliminada": "Biblioteca eliminada",
    "cola.cambio": "Cambios en la cola (resumen, cada pocos segundos)",
    "cola.pausa": "Procesamiento en pausa o reanudado",
    "cola.terminada": "Cola terminada",
    "descarga.progreso": "Avance de las descargas (cada pocos segundos)",
    "exportacion.lista": "Exportación lista para descargar",
    "exportacion.error": "Exportación con error",
    "glosario.cambio": "Glosario cambiado",
    "comentario.cambio": "Comentarios de una frase",
    "youtube.bloqueo": "YouTube pidió verificación (descargas en pausa)",
}
# los muy frecuentes se agrupan: se manda el último cada COALESCE_S segundos
COALESCE = {"cola.cambio", "descarga.progreso"}
COALESCE_S = 5

_sinks: list = []
_lock = threading.Lock()


def subscribe(fn):
    """fn(nombre, biblioteca, datos)"""
    with _lock:
        _sinks.append(fn)


def emit(name: str, vault: str | None = None, **data):
    for fn in list(_sinks):
        try:
            fn(name, vault, data)
        except Exception as e:  # un oyente que falla no corta a quien emite
            print(f"[eventos] {name}: {e}", flush=True)
