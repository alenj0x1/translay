"""El resumen completo (vt/digest.py) y el encendido del agente (vt/agentsvc.py), sin modelos: un servidor
falso responde el JSON que respondería el modelo."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import digest  # noqa: E402
from vt.store import Transcript  # noqa: E402

SEGS = [
    (0, "Today we install the requests package.", "Hoy instalamos el paquete requests."),
    (30, "Then we write a load function that reads JSON.", "Luego escribimos una función load que lee JSON."),
    (75, "Finally we bake a lemon cake for dessert.", "Por último horneamos un pastel de limón de postre."),
]
SCREEN = {"items": [
    {"id": 1, "start": 10, "end": 15, "kind": "command", "text": "$ pip install requests", "box": [0, 0, .1, .1]},
    {"id": 2, "start": 40, "end": 50, "kind": "code", "text": "def load(path):", "box": [0, 0, .1, .1]},
]}


@pytest.fixture
def tr(tmp_path):
    data = {"id": "vid00000002", "name": "Demo", "lang": "en", "mode": "translate",
            "segments": [{"id": i, "start": s, "end": s + 8, "text": t, "translation": es}
                         for i, (s, t, es) in enumerate(SEGS)], "covered": [[0, 90]]}
    return Transcript(tmp_path / "vid00000002.json", data)


# ------------------------------------------------------------- JSON del modelo
def test_json_whole():
    assert digest._json('{"a": [1, 2]}') == {"a": [1, 2]}


def test_json_drops_thinking():
    assert digest._json('<think>hmm {"x": 1}</think>{"a": 1}') == {"a": 1}


def test_json_repairs_cut_output():
    # se cortó a mitad del segundo punto: queda lo completo
    cut = '{"sections": [{"title": "Uno", "points": [{"t": "0:01", "text": "a"}, {"t": "0:0'
    d = digest._json(cut)
    assert d["sections"][0]["points"] == [{"t": "0:01", "text": "a"}]


def test_json_braces_inside_strings():
    cut = '{"sections": [{"title": "usa {x}", "points": []}], "terms": [{"term": "a\\"}'
    assert digest._json(cut)["sections"][0]["title"] == "usa {x}"


def test_json_garbage():
    assert digest._json("no hay json aquí") == {}


# ------------------------------------------------------------- minutos
def test_snap_by_content(tr):
    chunk = digest._lines(tr, None)
    match = {s["start"]: set(digest_terms(f"{s['text']} {s['translation']}")) for s in tr.segments}
    # el modelo escribió 0:00 pero el punto habla del pastel de limón (1:15)
    assert digest._snap("0:00", chunk, "Hornean un pastel de limón", match) == 75


def test_snap_by_time_to_real_line(tr):
    chunk = digest._lines(tr, None)
    assert digest._snap("0:33", chunk) == 30
    assert digest._snap("9:59", chunk) == 0      # fuera del tramo: el inicio del tramo
    assert digest._snap("", chunk) == 0


def digest_terms(text):
    from vt.agent import _terms
    return _terms(text)


def test_lines_include_screen(tr):
    lines = digest._lines(tr, SCREEN)
    assert any("(on screen, command) $ pip install requests" in s for _, s in lines)
    assert [t for t, _ in lines] == sorted(t for t, _ in lines)


def test_chunks_merge_short_tail():
    lines = [(i, "x" * 100) for i in range(10)]
    cs = digest._chunks(lines, 450)
    assert sum(len(c) for c in cs) == 10
    assert all(len(c) >= 2 for c in cs)


# ------------------------------------------------------------- resumen completo con un modelo falso
class FakeServer:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        if "closing" in messages[0]["content"]:
            return {"text": json.dumps({"overview": "Un video de Python y repostería.",
                                        "takeaways": ["Instala requests", " "], "suggestions": ["¿Qué hace load?"]})}
        return {"text": json.dumps({"sections": [
            {"title": "Instalar", "points": [{"t": "0:00", "text": "Instala el paquete requests"}]},
            {"title": "Postre", "points": [{"t": "0:00", "text": "Hornean un pastel de limón"}]}],
            "terms": [{"term": "requests", "meaning": "librería HTTP", "t": "0:00"},
                      {"term": "Requests", "meaning": "repetido", "t": "0:00"}]})}


def test_summarize(tr):
    srv = FakeServer()
    steps = []
    s = digest.summarize(srv, {"title": "Demo"}, tr, SCREEN, 4096, progress=lambda i, n: steps.append((i, n)),
                         model="falso")
    assert s["version"] == 2 and s["model"] == "falso"
    assert s["overview"].startswith("Un video")
    assert [c["title"] for c in s["chapters"]] == ["Instalar", "Postre"]
    assert s["chapters"][1]["t"] == 75          # ubicado por contenido, no por el 0:00 del modelo
    assert [t["term"] for t in s["terms"]] == ["requests"]   # sin repetidos
    assert s["takeaways"] == ["Instala requests"]
    assert {r["kind"] for r in s["resources"]} == {"command", "code"}
    assert steps[-1][0] == steps[-1][1]


def test_summarize_cancelled(tr):
    assert digest.summarize(FakeServer(), {}, tr, None, 4096, cancelled=lambda: True) is None


def test_as_text(tr):
    s = digest.summarize(FakeServer(), {"title": "Demo"}, tr, SCREEN, 4096)
    txt = digest.as_text("Demo", s)
    for part in ("Resumen", "Ideas clave", "[1:15] Postre", "Conceptos clave", "$ pip install requests"):
        assert part in txt


# ------------------------------------------------------------- encendido
@pytest.mark.skipif(sys.platform != "win32", reason="Job Object de Windows")
def test_server_dies_with_app():
    """El llama-server queda atado a Translay: cerrar el job (lo que hace Windows al morir la app) lo cierra."""
    import subprocess

    from vt import llm

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = llm._bind(p)
        assert job is not None
        job.k32.CloseHandle(job.handle)
        p.wait(10)
        assert p.returncode is not None
    finally:
        if p.poll() is None:
            p.kill()


def test_power_off_unloads(tmp_path, monkeypatch):
    from vt import agentsvc

    sent = []

    class Prefs:
        values = {}

    svc = agentsvc.AgentService(tmp_path, vaults=None, prefs=Prefs(), notify=sent.append, hw=lambda: {"gpu": {}})
    stopped = []

    class Srv:
        class proc:
            @staticmethod
            def poll():
                return None

        def stop(self):
            stopped.append(1)

    svc.server = Srv()
    assert svc.power_state() == "encendido"
    svc.power(False)
    assert stopped and svc.server is None and svc.off
    assert sent[-1]["type"] == "agent_power" and sent[-1]["state"] == "apagado"
