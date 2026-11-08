"""Pruebas sin GPU del resumen (vt/summarize.py, vt/summaries.py) y de lo nuevo al exportar:
texto en párrafos, resumen en TXT, «Guardar como» (nombre propuesto y elegido) y la lista de
lo guardado en una carpeta que sobrevive a un reinicio.

    python -m pytest tests/test_summary.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import summarize  # noqa: E402


def segs(n: int, words: int = 20, step: float = 10.0) -> list[dict]:
    return [{"id": i, "start": i * step, "end": i * step + step - 1, "text": " ".join(["palabra"] * words)}
            for i in range(n)]


def test_lines_and_chunks_cover_everything_without_a_fixed_count():
    """Los puntos no tienen límite: un video largo da más tramos (y por eso más puntos)."""
    short = summarize.chunks(summarize.lines(segs(30)))        # ~5 min
    long = summarize.chunks(summarize.lines(segs(600)))        # ~100 min
    assert len(short) == 1 and len(long) > 5
    ls = summarize.lines(segs(600))
    assert sum(len(c) for c in long) == len(ls)                # nada queda afuera
    assert all(b - a >= summarize.LINE_S for (a, _), (b, _) in zip(ls, ls[1:]))
    # un último tramo muy corto se suma al anterior
    assert sum(summarize.words(x) for _, x in long[-1]) >= summarize.CHUNK_TOKENS // 4


def test_points_snap_to_real_lines_and_drop_noise():
    chunk = [(60.0, "a"), (95.0, "b"), (130.0, "c")]
    out = summarize.parse_points(
        "Aquí van los puntos:\n"
        "[1:00] Explica cómo empieza el proyecto.\n"
        "- [01:40] Cuenta que el plan se atrasó dos semanas.\n"
        "[59:00] Un minuto inventado fuera del tramo.\n"
        "[2:15] ok\n"                                           # demasiado corto
        "[1:00] Explica cómo empieza el proyecto.\n", chunk)    # repetido
    assert [p["t"] for p in out] == [60.0, 95.0, 130.0]  # el inventado, en la última línea del tramo
    assert any(p["text"].startswith("Un minuto inventado") and p["t"] == 130.0 for p in out)
    assert len(out) == 3


def test_recommend_by_hardware():
    gpu = lambda mb: {"gpu": {"vram_total_mb": mb}, "ram": {"total_mb": 16384}}  # noqa: E731
    assert summarize.recommend(gpu(8188)) == "qwen3-4b"
    assert summarize.recommend(gpu(6144)) == "qwen3-1.7b"
    assert summarize.recommend(gpu(8188), {"vram_mb": 6144}) == "qwen3-1.7b"
    assert summarize.recommend(gpu(4096)) == "qwen3-1.7b"
    assert summarize.recommend(gpu(2048)) == "qwen3-1.7b"    # no entra en 2 GB: en la CPU
    assert summarize.recommend({"gpu": {"vram_total_mb": 2048}, "ram": {"total_mb": 6144}}) == "qwen3-0.6b"
    assert summarize.recommend({"gpu": None, "ram": {"total_mb": 16384}}) == "qwen3-1.7b"  # en la CPU
    assert summarize.recommend({"gpu": None, "ram": {"total_mb": 4096}}) == "qwen3-0.6b"


def test_summary_runs_by_chunks_with_progress_and_cancel():
    s = summarize.Summarizer("qwen3-0.6b", "cpu")
    calls = []

    def fake(system, user, max_tokens):
        calls.append(user)
        if "Responde solo con el resumen" in user:
            return "Trata de cómo trabajar mejor."
        first = user.split("] ", 1)[0].split("[")[-1]
        return f"[{first}] Explica un punto importante de este tramo."
    s.generate = fake
    s.load = lambda: None  # sin modelo: cuenta palabras
    steps = []
    r = s.summarize(segs(600), "en", "Charla", progress=lambda d, t: steps.append((d, t)))
    parts = len(summarize.chunks(summarize.lines(segs(600))))
    assert parts > 1
    assert len(calls) == parts + 1 and len(r["points"]) == parts
    assert r["overview"] == "Trata de cómo trabajar mejor." and r["model"] == "qwen3-0.6b"
    assert steps[0] == (0, parts + 1) and steps[-1] == (parts + 1, parts + 1)
    assert s.summarize(segs(600), "en", cancelled=lambda: True) is None
    text = summarize.as_text("Charla", r)
    assert text.startswith("Charla\n\nResumen\n\nTrata de cómo") and "[0:00] Explica" in text


def test_long_video_overview_goes_by_groups():
    """Muchos puntos no entran en una sola llamada: un párrafo por grupo y el panorama de esos párrafos."""
    s = summarize.Summarizer("qwen3-0.6b", "cpu")
    s.load = lambda: None
    asked = []

    def fake(system, user, max_tokens):
        asked.append(user)
        if "Responde solo con el párrafo" in user:
            return "Párrafo de una parte."
        if "Responde solo con el resumen" in user:
            assert "lo que se trata en cada parte" in user and "Párrafo de una parte." in user
            return "Panorama."
        first = user.split("] ", 1)[0].split("[")[-1]
        return "\n".join(f"[{first}] Punto número {n} de este tramo, con bastante detalle para ocupar." for n in range(25))
    s.generate = fake
    r = s.summarize(segs(1200), "en")
    parts = sum("Responde solo con el párrafo" in u for u in asked)
    assert parts > 1 and r["overview"] == "Panorama."
    assert all(summarize.words(u) < summarize.CHUNK_TOKENS * 2 for u in asked)


def test_exclusive_gpu_turn_sleeps_and_restores_models():
    from vt.resources import Resources

    log = []

    class M:
        def __init__(self, name):
            self.name = name

        def load(self):
            log.append(("load", self.name))

        def unload(self):
            log.append(("unload", self.name))

    res = Resources(M("asr"), M("mt"))
    with res.use("asr"):
        pass
    log.clear()
    out = res.exclusive(5000, lambda: 1000, lambda: log.append(("sum",)) or 7, release=lambda: log.append(("free",)))
    assert out == 7 and log == [("unload", "asr"), ("sum",), ("free",), ("load", "asr")]
    log.clear()
    assert res.exclusive(500, lambda: 1000, lambda: 8) == 8 and log == []  # cabe: no se toca nada


def test_summaries_queue_and_prefs():
    import json

    from vt.prefs import Prefs
    from vt.store import Store
    from vt.summaries import Summaries

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        store = Store(root / "transcripts")
        tr = store.open("yt_aaaaaaaaaaa")
        tr.data["segments"] = segs(40)
        tr.save()
        prefs = Prefs(root / "prefs.json")
        assert prefs.values["summary_mode"] == "manual" and prefs.values["summary_model"] == "auto"
        assert not prefs.set("summary_model", "gpt-9") and prefs.set("summary_model", "qwen3-0.6b")
        assert not prefs.set("export_dir", 3) and prefs.set("export_dir", "D:/Exportado")
        lib = type("L", (), {"data": {"videos": {"yt_aaaaaaaaaaa": {"title": "Charla"}}},
                             "set_field": lambda self, vid, **kw: self.data["videos"][vid].update(kw)})()
        sent = []
        sums = Summaries(store, lib, None, prefs, sent.append, device="cpu")
        sums._summarizer = lambda: type("S", (), {
            "device": "cpu", "model_dir": lambda self, download=True: root,
            "summarize": lambda self, *a, **k: {"overview": "Hola.", "points": [{"t": 0, "text": "Un punto."}],
                                                "model": "qwen3-0.6b"}})()
        sums.auto("yt_aaaaaaaaaaa")  # manual: no entra solo
        assert sums.state("yt_aaaaaaaaaaa") is None
        prefs.set("summary_mode", "auto")
        sums.auto("yt_aaaaaaaaaaa")
        for _ in range(50):
            if tr.data.get("summary"):
                break
            time.sleep(0.05)
        assert tr.data["summary"]["overview"] == "Hola."
        assert json.loads((root / "transcripts" / "yt_aaaaaaaaaaa.json").read_text(encoding="utf-8"))["summary"]
        assert lib.data["videos"]["yt_aaaaaaaaaaa"]["summarized"] is True
        assert sent[-1]["msg"]["type"] == "summary"
        assert not sums.request("yt_aaaaaaaaaaa")  # ya tiene: solo si se pide rehacerlo


def test_export_plain_text_summary_save_as_and_history():
    from vt.exporter import Exporter, plain_text
    from vt.library import Library
    from vt.store import Store

    s = [{"start": 0, "end": 2, "text": "Hola.", "translation": "Hi.", "speaker": 0},
         {"start": 2.5, "end": 4, "text": "¿Qué tal?", "translation": "How are you?", "speaker": 0},
         {"start": 9, "end": 11, "text": "Bien.", "translation": "Fine.", "speaker": 1}]
    assert plain_text("Charla", s, "text") == "Charla\n\nHola. ¿Qué tal?\n\nBien.\n"

    def wait(job):
        for _ in range(100):
            if job["state"] in ("listo", "error"):
                return
            time.sleep(0.1)

    with tempfile.TemporaryDirectory() as d:
        root, dest = Path(d).resolve() / "data", Path(d).resolve() / "Mis textos"
        root.mkdir()
        store = Store(root / "transcripts")
        tr = store.open("yt_qqqqqqqqqqq")
        tr.data.update(segments=s, lang="en", mode="translate", covered=[[0, 11]])
        tr.data["summary"] = {"overview": "Un saludo.", "points": [{"t": 0, "text": "Se saludan."}], "model": "qwen3-4b"}
        tr.save()
        lib = Library(root / "library.json")
        lib.data["videos"]["yt_qqqqqqqqqqq"] = {"id": "yt_qqqqqqqqqqq", "source": "youtube", "title": "Charla",
                                               "duration": 11, "progress": {"asr": 1.0, "dub": 1.0}}
        proc = type("Q", (), {"progress": lambda self, vid: {"asr": 1.0, "dub": 1.0}, "_job": lambda self, vid: None})()
        ex = Exporter(root, store, lib, proc, None, type("P", (), {"values": {}})(), lambda m: None)
        assert ex.plan(["yt_qqqqqqqqqqq"], ["txt_es"]) == (True, "Charla (texto en español).txt")
        assert ex.plan(["yt_qqqqqqqqqqq"], ["orig_audio"], audio="mp3") == (True, "Charla (audio original).mp3")
        assert ex.plan(["yt_qqqqqqqqqqq"], ["txt_es", "summary"], "Lote") == (False, "Lote")
        from vt.exporter import safe_file
        long = safe_file("x" * 200 + " (subtítulos español).srt")
        assert long.endswith(".srt") and len(long) <= 115  # un título largo no pierde la extensión
        # «Guardar como»: el nombre elegido, en la carpeta elegida
        job = ex.add(["yt_qqqqqqqqqqq"], ["txt_es"], dest=str(dest), filename="saludo.txt")
        wait(job)
        assert job["state"] == "listo", job["error"]
        assert Path(job["path"]) == dest / "saludo.txt"
        assert (dest / "saludo.txt").read_text(encoding="utf-8") == "Charla\n\nHi. How are you?\n\nFine.\n"
        both = ex.add(["yt_qqqqqqqqqqq"], ["txt_orig", "summary"], "Lote", dest=str(dest))
        wait(both)
        assert both["state"] == "listo", both["error"]
        names = sorted(p.name for p in Path(both["path"]).iterdir())
        assert names == ["Charla (resumen).txt", "Charla (texto original).txt"]
        assert "[0:00] Se saludan." in (Path(both["path"]) / "Charla (resumen).txt").read_text(encoding="utf-8")
        # tras reiniciar, lo guardado en una carpeta sigue en la lista con su ruta (si sigue ahí)
        (dest / "saludo.txt").unlink()
        again = Exporter(root, store, lib, proc, None, type("P", (), {"values": {}})(), lambda m: None)
        assert [j["path"] for j in again.public()["jobs"]] == [both["path"]]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
