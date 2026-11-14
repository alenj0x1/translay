"""Texto en pantalla (vt/textkind.py, vt/screentext.py): qué se traduce y cómo se sigue en el tiempo."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import screentext  # noqa: E402
from vt.ocr import regions  # noqa: E402
from vt import textkind  # noqa: E402
from vt.textkind import kind, settle  # noqa: E402

CASES = {
    "Welcome to the kitchen": "text",
    "Step 2 - Add the flour slowly": "text",
    "and mix for three minutes": "text",
    "Blazor Full Course": "text",
    "For Beginners": "text",
    "Subscribe for more videos!": "text",
    "Make sure you install Python first.": "text",
    "for the best results, use fresh eggs": "text",
    "if you want to learn more": "text",
    "from the beginning": "text",
    "Chapter 3: Variables and Types": "text",
    "Hello World": "text",
    "# read the config file": "comment",
    "# parsed settings": "comment",
    "// start the server on port 3000": "comment",
    "/* main entry */": "comment",
    "<!-- navbar -->": "comment",
    "def load(path):": "code",
    "data = json.loads(path.read_text())": "code",
    "GameStore.db": "code",
    "EFMigrationsHistory": "code",
    "const app = express();": "code",
    "app.listen(3000, () => {": "code",
    "for (let i = 0; i < 10; i++) {": "code",
    'print("Hello world")': "code",
    "import React from 'react'": "code",
    "public static void main(String[] args)": "code",
    "SELECT * FROM users WHERE id = 1;": "code",
    '<div className="card">': "code",
    "user_name": "code",
    "#include <stdio.h>": "code",
    "$ pip install requests": "command",
    "npm install express --save": "command",
    'git commit -m "fix"': "command",
    r"PS C:\Users\dev> dotnet run": "command",
    "cd my-app": "command",
    "https://docs.python.org/3/": "link",
    "youtube.com/watch?v=YbRe4ilVYJk": "link",
    "dev@example.com": "email",
    "});": "noise",
    "0": "noise",
}


@pytest.mark.parametrize("text,expected", CASES.items())
def test_kind(text, expected):
    assert kind(text) == expected


def test_settle_code_block():
    # en un bloque de código, `data` o `else` sueltos también son código; el comentario se respeta
    assert settle(["comment", "code", "text", "code"]) == ["comment", "code", "code", "code"]
    assert settle(["text", "text", "code"]) == ["text", "text", "code"]


def test_regions_8_connected():
    m = np.zeros((6, 10), bool)
    m[1, 1:3] = True
    m[2, 3] = True       # diagonal: misma región
    m[4, 6:9] = True     # otra región
    r = sorted((x0, y0, x1, y1) for x0, y0, x1, y1, *_ in regions(m))
    assert r == [(1, 1, 4, 3), (6, 4, 9, 5)]


def _line(x0, y0, x1, y1, text, conf=0.99):
    return {"box": (x0, y0, x1, y1), "text": text, "conf": conf}


def test_blocks_group_paragraph_and_split_code():
    lines = [_line(300, 555, 750, 601, "Step 2 - Add the flour slowly"),
             _line(300, 604, 711, 643, "and mix for three minutes"),
             _line(772, 216, 1051, 245, "# read the config file"),
             _line(772, 248, 966, 283, "def load(path):"),
             _line(773, 284, 1206, 319, "data = json.loads(path.read_text())")]
    blocks = screentext.blocks(lines, 1280, 720)
    texts = sorted((b["kind"], b["text"]) for b in blocks)
    assert ("text", "Step 2 - Add the flour slowly and mix for three minutes") in texts
    assert ("comment", "# read the config file") in texts
    assert ("code", "def load(path):\ndata = json.loads(path.read_text())") in texts


def test_tracker_keeps_text_seen_twice_and_drops_flicker():
    tk = screentext.Tracker(step=0.5)
    b = {"box": (0.1, 0.1, 0.3, 0.05), "text": "Welcome to the kitchen", "kind": "text", "conf": 0.99,
         "lines": 1, "bg": "#ffffff", "fg": "#000000"}
    flick = dict(b, box=(0.5, 0.5, 0.2, 0.05), text="Blink", conf=0.7)
    tk.update(1.0, [b, flick])
    tk.update(1.5, [dict(b, text="Welcome to the kitchen", conf=0.97)])
    tk.update(2.0, [])
    done = tk.close_all(2.0)
    assert [i["text"] for i in done] == ["Welcome to the kitchen"]
    assert done[0]["start"] == pytest.approx(0.75) and done[0]["end"] == pytest.approx(1.75)


def test_registry_is_extensible(monkeypatch):
    # un tipo nuevo es una función registrada: se reconoce, tiene su etiqueta y decide si se traduce
    monkeypatch.setattr(textkind, "KINDS", dict(textkind.KINDS))
    textkind.register("hashtag", "Etiqueta", order=5)(lambda t: t.startswith("#") and " " not in t)
    assert kind("#python") == "hashtag"
    assert textkind.KINDS["hashtag"].label == "Etiqueta"
    assert not textkind.translatable("hashtag")
    assert kind("# read the config file") == "comment"


def test_translatable_kinds():
    assert textkind.translatable("text") and textkind.translatable("comment")
    assert not any(textkind.translatable(k) for k in ("code", "command", "link", "email", "noise"))


@pytest.mark.parametrize("text,parts", [
    ("# read the config file", ("# ", "read the config file", "")),
    ("// start the server", ("// ", "start the server", "")),
    ("/* main entry */", ("/* ", "main entry", " */")),
    ("<!-- navbar -->", ("<!-- ", "navbar", " -->")),
])
def test_comment_parts(text, parts):
    assert textkind.comment_parts(text) == parts


def test_gold_does_not_regress():
    """La referencia etiquetada con videos reales (tools/lab/screentext_gold.json): un cambio en las reglas no
    puede bajar el acierto ni traducir más código, comandos o interfaz que la última línea base aceptada."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "lab"))
    import screentext_eval as ev

    r = ev.evaluate(ev.load())
    # lo que ve la persona: traducir de más (tapa código o interfaz) y de menos (texto que queda en inglés);
    # en proporción, porque la referencia crece con cada video
    assert r["translated_wrongly"] / r["lines"] <= 0.04
    assert r["not_translated"] / r["lines"] <= 0.015
    assert r["accuracy"] >= 0.94  # el tipo exacto (código, comando, interfaz…), para los elementos del video


def test_typing_text_is_one_element():
    """Tipografía cinética: «Rea» → «Real-World» → «Real-World Examples» es un solo elemento con el texto final."""
    tk = screentext.Tracker(step=0.5)
    base = {"kind": "text", "conf": 0.99, "lines": 1, "align": "left", "bg": "#000000", "fg": "#ffffff"}
    tk.update(1.0, [dict(base, box=(0.2, 0.5, 0.05, 0.06), text="Rea")])
    tk.update(1.5, [dict(base, box=(0.2, 0.5, 0.15, 0.06), text="Real-World")])
    tk.update(2.0, [dict(base, box=(0.2, 0.5, 0.3, 0.06), text="Real-World Examples")])
    tk.update(2.5, [dict(base, box=(0.2, 0.5, 0.3, 0.06), text="Real-World Examples")])
    done = tk.close_all(3.0)
    assert [i["text"] for i in done] == ["Real-World Examples"]
    assert done[0]["start"] == pytest.approx(0.75)


@pytest.mark.parametrize("text,ctx,expected", [
    ("Documents", {"h": 0.021, "conf": 0.99, "small": 12}, "ui"),            # barra lateral de un navegador
    ("SPECIAL OFFER", {"h": 0.0289, "conf": 0.98, "small": 2}, "text"),      # letra chica en una animación
    ("SPECIAL OFFER", {"h": 0.0289, "conf": 0.98, "small": 12}, "ui"),       # la misma letra en una pantalla
    ("^GHelp ^X Exit", {"h": 0.04, "conf": 0.98}, "ui"),                     # atajos de nano
    ("TAB Q W E R T Y U I O P", {"h": 0.05, "conf": 0.95}, "ui"),            # teclado dibujado
    ("3. Why It Wo", {"h": 0.1, "conf": 0.98}, "text"),                      # título que aparece
    ("Optious", {"h": 0.44, "conf": 0.98}, "text"),                          # logo, no la tecla Option
])
def test_kind_with_context(text, ctx, expected):
    assert kind(text, ctx) == expected


@pytest.mark.parametrize("text,expected", [
    ("exit networkchuck@localhost:~$", "code"),
    ("-rw-rw-r-- 1 networkchuck networkchuck 0 Nov 7 13:06 here", "code"),
    ("rmdir: failed to remove 'mynewdirectory/': Directory not empty", "code"),
    ("FROM ubuntu:20.04", "code"),
    ("RUN some terminal commands", "text"),
    ("docker-demo > docker run myapp", "command"),
    ("22 activity = [\"combing\", \"drinking\"", "code"),
    ("00 64 09 cd 21 b8 01 4c cd 21 54 68", "code"),
    ("U.S.A.", "text"),
    ('"Digital Marketing', "text"),
    ("Outputs (code)", "text"),
    ("@monarchwebworld", "handle"),
])
def test_kind_real_cases(text, expected):
    assert kind(text) == expected
