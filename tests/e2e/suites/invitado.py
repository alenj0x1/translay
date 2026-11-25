"""Invitados de cada tipo de biblioteca: lo que pueden ver y hacer, sin avisos de permiso por algo que no pidieron,
y que el servidor siga negando lo que no les toca (aunque lo pidan a mano)."""


def plays(t, page, vid: str, where: str):
    page.evaluate(f"playItem('{vid}')")
    t.wait(lambda: page.evaluate(f"state.videoId === '{vid}' && state.segments.length === 5"), 15, f"{vid} abierto")
    t.wait(lambda: page.evaluate("vEn.readyState") >= 2, 15, f"{vid} cargado")
    page.evaluate("vEn.muted = true; vEn.currentTime = 0; vEn.play()")
    t.wait(lambda: page.evaluate("vEn.currentTime") > 0.8, 10, f"{vid} avanza")
    t.check(f"{vid} se reproduce ({where})", True)
    page.wait_for_timeout(800)  # el pedido de registrar/priorizar llega después de cargar
    t.no_permission_toast(page, f"{where} · {vid}")


def run(t):
    # ---- biblioteca pública, solo ver
    page = t.page("invitado", "/b/publica")
    t.check("invitado (no dueño)", page.evaluate("state.access.owner === false"))
    t.check("permiso «ver» en Pública", page.evaluate("state.access.perms.publica") == "ver")
    t.check("no ve la privada", "principal" not in page.evaluate("Object.keys(state.access.perms)"))
    t.check("sin Ajustes", page.evaluate("getComputedStyle(document.querySelector('#prefs-btn')).display === 'none' || document.querySelector('#prefs-btn').hidden"))
    t.check("sin Agregar (solo ve)", not page.evaluate("document.body.classList.contains('can-import')"))
    t.check("ve los 2 videos públicos", page.evaluate("Object.keys(lib.videos).sort().join()") == "e2epub00001,e2epub00002")
    plays(t, page, "e2epub00001", "solo ver")
    plays(t, page, "e2epub00002", "solo ver")
    page.locator("#transcript li[data-id] > .cell").nth(1).dblclick()  # la traducción de la primera frase
    page.wait_for_timeout(300)
    t.check("un invitado no abre el editor de frases", page.locator("#transcript .seditor").count() == 0)

    # el servidor niega lo que no le toca aunque lo pida a mano (y lo deja en el registro)
    t.expect_error("permiso.prefs_set")
    t.expect_error("permiso.lib_register")
    page.evaluate("state.ws.send(JSON.stringify({ type: 'prefs_set', key: 'theme_mode', value: 'oscuro' }))")
    page.evaluate("state.ws.send(JSON.stringify({ type: 'lib_register', id: 'e2epub00001', title: 'x' }))")
    page.wait_for_timeout(800)
    t.check("el servidor no cambió el tema del dueño", page.evaluate("prefs.theme_mode") != "oscuro")
    page.evaluate("document.querySelectorAll('.toast').forEach(x => x.remove())")  # sus avisos son esperados aquí

    # archivos de otra biblioteca: 403
    t.expect_http("/media/lib/e2emain0001.mp4")
    t.expect_console("status of 403")
    status = page.evaluate("fetch('/media/lib/e2emain0001.mp4').then(r => r.status)")
    t.check("un video privado no se puede bajar", status == 403, str(status))

    # ---- biblioteca pública con «importar»
    page2 = t.page("invitado", "/b/abierta")
    t.check("permiso «importar» en Abierta", page2.evaluate("state.access.perms.abierta") == "importar")
    t.check("con Agregar (puede importar)", page2.evaluate("document.body.classList.contains('can-import')"))
    plays(t, page2, "e2eopen0001", "importar")

    # ---- biblioteca privada: pide iniciar sesión y no muestra nada
    page3 = t.page("invitado", "/b/principal", wait_ready=False)
    t.wait(lambda: page3.evaluate("typeof state !== 'undefined' && !!state.access && state.access.owner === false"), 20, "el acceso del invitado")
    page3.wait_for_timeout(600)
    t.check("en la privada no ve sus videos", not any(v.startswith("e2emain") for v in page3.evaluate("Object.keys(lib.videos)")))
    t.no_permission_toast(page3, "privada")
