"""La página pide sus estilos y scripts con ?v=<huella>: un proxy que guarda los .js/.css en caché (aunque
la app diga no-store) igual entrega los nuevos al actualizar Translay o cambiar el idioma."""

import asyncio
import os
import re

from vt.httpws import AppServer, ui_version, versioned_page

PAGE = ('<link rel="stylesheet" href="css/a.css">\n<script src="i18n.js"></script>\n'
        '<script src="js/b.js"></script>\n<a href="https://x.example/js/c.js">enlace</a>\n')


def test_versioned_page():
    out = versioned_page(PAGE, "abc")
    assert 'href="css/a.css?v=abc"' in out
    assert 'src="i18n.js?v=abc"' in out
    assert 'src="js/b.js?v=abc"' in out
    assert 'href="https://x.example/js/c.js"' in out  # solo los archivos de la app


def test_ui_version_cambia(tmp_path):
    (tmp_path / "js").mkdir()
    f = tmp_path / "js" / "b.js"
    f.write_text("uno")
    v1 = ui_version(tmp_path)
    assert ui_version(tmp_path) == v1
    assert ui_version(tmp_path, "en") != v1  # el idioma también (i18n.js depende de él)
    f.write_text("otro contenido")
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 1_000_000))
    assert ui_version(tmp_path) != v1


def test_servidor_entrega_la_pagina_versionada(tmp_path):
    (tmp_path / "index.html").write_text(PAGE)
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "b.js").write_text("console.log(1)")
    lang = {"v": "es"}

    async def run():
        srv = AppServer({"/": tmp_path}, {}, page_extra=lambda: lang["v"])
        server = await asyncio.start_server(srv._handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def get(path):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
            await w.drain()
            data = await r.read()
            w.close()
            head, _, body = data.partition(b"\r\n\r\n")
            return head.decode(), body.decode()

        head, body = await get("/")
        assert "200" in head.splitlines()[0] and "text/html" in head and "no-store" in head
        v = re.search(r'js/b\.js\?v=(\w+)"', body)[1]
        lang["v"] = "en"
        assert re.search(r'js/b\.js\?v=(\w+)"', (await get("/"))[1])[1] != v
        head, body = await get("/js/b.js?v=" + v)  # el archivo se sirve igual, con o sin ?v=
        assert "200" in head.splitlines()[0] and body == "console.log(1)"
        server.close()

    asyncio.run(run())
