"""Descargas: qué errores no se arreglan reintentando (vt/youtube.py)."""

import urllib.error

from vt.youtube import friendly_error, permanent_error


def test_permanent_errors_fail_at_once():
    for msg in ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
                "Join this channel to get access to members-only content like this video",
                "ERROR: [youtube] abc: Video unavailable",
                "Sign in to confirm your age. This video may be inappropriate for some users.",
                "Dropbox no entregó el archivo: revisa que el enlace sea público"):
        assert permanent_error(Exception(msg)), msg
    assert permanent_error(urllib.error.HTTPError("https://x", 404, "Not Found", {}, None))


def test_transient_errors_are_retried():
    assert not permanent_error(ConnectionError("la descarga se cortó"))
    assert not permanent_error(urllib.error.HTTPError("https://x", 503, "Unavailable", {}, None))


def test_friendly_messages():
    assert "privado" in friendly_error(Exception("Private video"))
    assert "miembros" in friendly_error(Exception("members-only content"))
