"""El dueño en este equipo: el inicio, la biblioteca y cambiar de biblioteca."""


def visible(page, sel: str) -> bool:
    return page.evaluate(f"(() => {{ const e = document.querySelector({sel!r}); return !!e && !e.hidden && e.offsetParent !== null; }})()")


def run(t):
    page = t.page("dueño")
    t.check("es el dueño", page.evaluate("state.access.owner === true"))
    t.check("biblioteca Principal con 3 videos", page.evaluate("Object.keys(lib.videos).length") == 3,
            str(page.evaluate("Object.keys(lib.videos)")))
    t.check("Ajustes a mano", visible(page, "#prefs-btn"))
    t.check("Agregar a mano", visible(page, "#import-btn"))
    t.check("sin la bienvenida (ya vista)", not page.evaluate("document.querySelector('#welcome-dlg')?.open"))

    page.evaluate("setView('library')")
    t.wait(lambda: page.evaluate("document.querySelectorAll('#grid .card[data-id]').length") >= 3, 10, "las tarjetas de la biblioteca")
    t.check("una tarjeta por video", page.evaluate("document.querySelectorAll('#grid .card[data-id]').length") == 3)

    # cambiar a la biblioteca pública y volver
    page.evaluate("send({ type: 'vault_open', id: 'publica' })")
    t.wait(lambda: page.evaluate("vaults.current") == "publica" and page.evaluate("Object.keys(lib.videos).length") == 2, 10,
           "la biblioteca Pública abierta")
    t.check("Pública con 2 videos", page.evaluate("Object.keys(lib.videos).sort().join()") == "e2epub00001,e2epub00002")
    page.evaluate("send({ type: 'vault_open', id: 'principal' })")
    t.wait(lambda: page.evaluate("vaults.current") == "principal", 10, "de vuelta en Principal")
    t.no_permission_toast(page, "inicio")
