"""Detener una respuesta del agente: corta al instante aunque el modelo todavía no haya escrito nada
(mientras lee el video no sale ningún trozo; antes el botón no hacía nada hasta la primera palabra)."""

import http.server
import json
import threading
import time
from pathlib import Path

from vt import llm


def _server(delay: float):
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(delay)  # «leyendo»: nada sale todavía
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for w in ["Hola", " mundo"]:
                chunk = {"choices": [{"delta": {"content": w}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *a):
            pass
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def _client(port: int) -> llm.Server:
    c = llm.Server(Path("x"), Path("y"))
    c.port = port
    return c


def test_stop_while_reading_returns_at_once():
    s = _server(delay=5)
    try:
        flag = threading.Event()
        threading.Timer(0.3, flag.set).start()
        t0 = time.perf_counter()
        r = _client(s.server_address[1]).chat([{"role": "user", "content": "hola"}], stop_flag=flag.is_set)
        assert time.perf_counter() - t0 < 1.5
        assert r["stopped"] and r["text"] == ""
    finally:
        s.shutdown()


def test_answer_without_stop_is_complete():
    s = _server(delay=0)
    try:
        r = _client(s.server_address[1]).chat([{"role": "user", "content": "hola"}], stop_flag=lambda: False)
        assert r["text"] == "Hola mundo" and not r["stopped"]
    finally:
        s.shutdown()


# ------------------------------------------------------------------ descripción corta bajo el título
def test_description_is_clean_and_short():
    from vt import agent

    d = agent.clean_description('Descripción: "En este video, se explica cómo crear agentes con herramientas"')
    assert d == "Se explica cómo crear agentes con herramientas."
    long = "Una frase corta. " + "palabra " * 80
    assert len(agent.clean_description(long)) <= 261


def test_description_prompt_samples_long_videos():
    from types import SimpleNamespace

    from vt import agent

    segs = [{"start": i, "end": i + 1, "text": f"line {i}", "translation": f"frase número {i} del video"} for i in range(3000)]
    tr = SimpleNamespace(segments=segs, data={"name": "x"})
    msgs = agent.describe_messages({"title": "Título"}, tr)
    body = msgs[1]["content"]
    assert "Título" in body and "frase número 0 " in body and "[…]" in body
    assert len(body) < agent.DESCRIBE_CHARS + 600
    import re

    tail = [int(n) for n in re.findall(r"frase número (\d+)", body.split("[…]")[1])]
    assert tail and max(tail) > 2500  # también lee el final del video, no solo el inicio


# ------------------------------------------------------------------ Uso del equipo: descanso entre tandas
def test_background_work_rests_in_proportion():
    import queue
    from types import SimpleNamespace

    from vt.agentsvc import AgentService

    svc = AgentService.__new__(AgentService)
    svc.prefs = SimpleNamespace(values={"agent_usage": 50})
    svc._q = queue.Queue()

    class Srv:
        def chat(self, *a, **kw):
            time.sleep(0.2)
            return {"text": "ok"}
    t0 = time.perf_counter()
    assert svc._paced(Srv()).chat([])["text"] == "ok"
    assert 0.35 < time.perf_counter() - t0 < 0.6  # trabajó 0,2 s y descansó otro tanto
    svc.prefs.values["agent_usage"] = 100
    t0 = time.perf_counter()
    svc._paced(Srv()).chat([])
    assert time.perf_counter() - t0 < 0.3  # al 100 % no descansa
    svc.prefs.values["agent_usage"] = 25
    svc._q.put("pregunta")
    t0 = time.perf_counter()
    svc._paced(Srv()).chat([])
    assert time.perf_counter() - t0 < 0.35  # con una pregunta esperando, no descansa
