"""El agente de cada video (vt/agent.py, vt/videocontext.py, vt/llm.py): contexto, búsqueda, citas propias,
sugerencias. Sin modelos: lo que decide qué lee el modelo y cómo se citan las respuestas."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import agent, llm, videocontext  # noqa: E402
from vt.store import Transcript  # noqa: E402

SEGS = [
    (0, "What if you could turn strangers into loyal customers?", "¿Y si pudieras convertir a desconocidos en clientes leales?"),
    (40, "The four main stages are awareness, consideration, conversion and loyalty.",
     "Las cuatro etapas principales son conocimiento, consideración, conversión y lealtad."),
    (64, "Real example: a coffee subscription brand.", "Ejemplo real: una marca de suscripción de café."),
    (82, "They sign up for a 30-day trial after a limited-time offer.",
     "Se inscriben en una prueba de 30 días después de una oferta por tiempo limitado."),
    (120, "Pro tip: start by writing down your customer journey.", "Consejo: empieza por escribir el recorrido de tu cliente."),
]


@pytest.fixture
def tr(tmp_path):
    data = {"id": "vid00000001", "name": "Funnel", "lang": "en", "mode": "translate",
            "segments": [{"id": i, "start": s, "end": s + 6, "text": t, "translation": es}
                         for i, (s, t, es) in enumerate(SEGS)], "covered": [[0, 130]]}
    return Transcript(tmp_path / "vid00000001.json", data)


SCREEN = {"items": [
    {"id": 1, "start": 90, "end": 95, "kind": "command", "text": "$ pip install requests", "box": [0, 0, .1, .1]},
    {"id": 2, "start": 91, "end": 99, "kind": "command", "text": "$ pip install requests", "box": [0, 0, .1, .1]},
    {"id": 3, "start": 100, "end": 102, "kind": "code", "text": "def load(path):", "box": [0, 0, .1, .1]},
    {"id": 4, "start": 103, "end": 110, "kind": "code", "text": "def load(path):\n    return json.loads(path)", "box": [0, 0, .1, .1]},
]}


def test_elements_dedupe_and_typing():
    els = videocontext.elements(SCREEN)
    assert [e["kind"] for e in els] == ["command", "code"]
    assert els[0]["times"] == [90, 91]
    assert els[1]["text"].endswith("return json.loads(path)")  # el bloque escrito en vivo, en su versión completa


def test_markdown_has_times_translation_and_position(tr):
    md = videocontext.markdown({"title": "Funnel", "duration": 130}, tr, SCREEN, position=65)
    assert "[0:40] The four main stages" in md and "→ Las cuatro etapas" in md
    assert "La persona lo vio hasta [1:05] (50 %)" in md
    assert "```\n$ pip install requests\n```" in md


def test_context_full_or_fragments(tr):
    full, mode = agent.context({"title": "Funnel"}, tr, None, "", budget=10_000)
    assert mode == "completo" and "[2:00]" in full
    part, mode = agent.context({"title": "Funnel"}, tr, None, "¿Cuánto dura la prueba?", budget=120)
    assert mode == "fragmentos" and "30" in part


def test_search_finds_spanish_question_in_translation(tr):
    parts = agent.chunks(tr, size=10)
    hit = agent.search(parts, "¿Qué ejemplo de café usa?", k=1)
    assert hit and hit[0]["start"] == 64


def test_cite_adds_the_moment(tr):
    out = agent.cite("La prueba dura 30 días después de una oferta por tiempo limitado.", tr)
    assert "[1:22]" in out
    assert agent.cite("Hola, ¡con gusto!", tr) == "Hola, ¡con gusto!"            # nada que citar
    assert agent.cite("Ya está citado [0:40].", tr) == "Ya está citado [0:40]."   # no repite
    code = "```\ndef load(path):\n```"
    assert agent.cite(code, tr) == code                                           # el código queda igual


def test_messages_put_context_first_and_question_last(tr):
    msgs, _ = agent.messages({"title": "Funnel"}, tr, None, "¿Qué ejemplo usa?", position=30, name="Lumi",
                             tone="respuestas cortas")
    assert msgs[0]["role"] == "system" and "Eres Lumi" in msgs[0]["content"] and "respuestas cortas" in msgs[0]["content"]
    assert msgs[-1]["content"].startswith("(La persona va en el minuto 0:30") and msgs[-1]["content"].endswith("¿Qué ejemplo usa?")
    # la posición no va en el sistema: así el servidor reutiliza lo ya leído entre preguntas
    assert "0:30" not in msgs[0]["content"]


def test_suggestions_follow_the_video(tr):
    s = agent.suggestions({"duration": 130}, tr, SCREEN, position=60)
    qs = [x["q"] for x in s]
    assert s[0] == {"q": "Generar el resumen del video", "action": "summary"}
    assert "¿Qué me falta por ver desde donde voy?" in qs
    assert any("comandos" in q for q in qs)


def test_stamps_and_clean():
    assert agent.stamps("ver [1:05] y [1:02:03]") == [65, 3723]
    assert agent.clean("<think>razono</think>\nHola") == "Hola"


def test_models_are_pinned():
    for m in llm.MODELS.values():
        assert m.rev and m.file.endswith(".gguf") and m.gb > 0
    for files in llm.BUILDS.values():
        for name, size, sha in files:
            assert len(sha) == 64 and size > 1_000_000 and name.endswith(".zip")


def test_devices_parser(monkeypatch, tmp_path):
    out = ("Available devices:\n  Vulkan0: NVIDIA GeForce RTX 4060 (7956 MiB, 7188 MiB free)\n"
           "  Vulkan1: Intel(R) UHD Graphics 730 (8085 MiB, 7425 MiB free)\n")

    class R:
        stdout = out
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: R())
    d = llm.devices(tmp_path / "x.exe")
    assert [x["integrated"] for x in d] == [False, True] and d[0]["mb"] == 7956
