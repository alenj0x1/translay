"""Acciones del agente (vt/agentintents.py): pedidos que la app resuelve sin el modelo."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import agentintents  # noqa: E402
from vt.store import Transcript  # noqa: E402

SEGS = [
    (0, "Welcome to the course.", "Bienvenidos al curso."),
    (30, "Today we talk about prices and discounts.", "Hoy hablamos de precios y descuentos."),
    (95, "Install the requests package with pip.", "Instala el paquete requests con pip."),
    (200, "Prices change with demand.", "Los precios cambian con la demanda."),
]


@pytest.fixture
def tr(tmp_path):
    data = {"id": "vid00000003", "name": "Curso", "lang": "en", "mode": "translate",
            "segments": [{"id": i, "start": s, "end": s + 8, "text": t, "translation": es}
                         for i, (s, t, es) in enumerate(SEGS)], "covered": [[0, 210]]}
    return Transcript(tmp_path / "vid00000003.json", data)


INFO = {"title": "Curso de prueba"}


def route(q, tr):
    return agentintents.route(q, INFO, tr, None, 40)


def test_export_for_claude(tr):
    r = route("exporta esto para Claude", tr)
    assert r["card"]["type"] == "export" and r["card"]["target"] == "Claude"
    assert "Curso de prueba" in r["card"]["content"] and r["card"]["file"].endswith(".md")


def test_export_other_agent(tr):
    assert route("pásalo a ChatGPT", tr)["card"]["target"] == "ChatGPT"


def test_seek_explicit_time(tr):
    r = route("llévame al minuto 1:35", tr)
    assert r["action"] == {"type": "seek", "t": 95}
    assert "requests" in r["card"]["text"]


def test_seek_by_topic(tr):
    r = route("llévame a donde explica cómo instalar requests", tr)
    assert r["action"]["t"] == 95


def test_subtitles(tr):
    assert route("pon los subtítulos en inglés", tr)["action"] == {"type": "subs", "value": "en"}
    assert route("quita los subtítulos", tr)["action"] == {"type": "subs", "value": "off"}


def test_save(tr):
    assert route("guarda este video en Python", tr)["action"] == {"type": "save", "collection": "Python"}


def test_alert(tr):
    r = route("avísame cuando hablen de precios", tr)
    assert r["action"]["type"] == "alert" and r["action"]["topic"] == "precios"
    assert [x["t"] for x in r["action"]["times"]] == [30, 200]


def test_alert_nothing(tr):
    r = route("avísame cuando hablen de dinosaurios", tr)
    assert "action" not in r and "dinosaurios" in r["text"]


def test_plain_question_goes_to_model(tr):
    assert route("¿de qué trata el video?", tr) is None
    assert route("¿qué es la demanda?", tr) is None


# ------------------------------------------------------------- en inglés y portugués
def route_in(q, tr, ui):
    return agentintents.route(q, INFO, tr, None, 40, ui=ui)


@pytest.mark.parametrize("q,ui,kind", [
    ("send this to ChatGPT", "en", "export"),
    ("take me to minute 3", "en", "seek"),
    ("turn off the subtitles", "en", "subs"),
    ("save this video to Python", "en", "save"),
    ("let me know when they talk about prices", "en", "alert"),
    ("manda isso para o Claude", "pt", "export"),
    ("me leva para o minuto 3", "pt", "seek"),
    ("tira as legendas", "pt", "subs"),
    ("salva este vídeo em Python", "pt", "save"),
    ("me avisa quando falarem do pacote requests", "pt", "alert"),
])
def test_phrases_in_each_language(tr, q, ui, kind):
    r = route_in(q, tr, ui)
    got = (r.get("action") or r.get("card") or {}).get("type")
    assert got == kind, (q, r)


def test_reply_in_app_language_whatever_the_question(tr):
    assert route_in("take me to 1:35", tr, "es")["text"] == "Vamos a [1:35]."
    assert route_in("llévame al 1:35", tr, "en")["text"] == "Going to [1:35]."
    assert route_in("save this to Python", tr, "pt")["text"] == "Vou salvar em «Python»."
    assert route_in("pon los subtítulos en inglés", tr, "en")["text"] == "Done: subtitles in English."
    assert route_in("what is the video about?", tr, "en") is None
    assert set(agentintents.PHRASES) >= {"es", "en", "pt"}
