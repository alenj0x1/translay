"""Ajustes del dueño: cada página abre sin errores, las opciones nuevas están y el informe de diagnóstico se guarda."""

PAGES = ["uso", "apariencia", "video", "audio", "agente", "biblioteca", "exportar", "glosario", "bibliotecas", "acceso",
         "rendimiento", "almacenamiento", "papelera"]


def run(t):
    page = t.page("dueño")
    for sec in PAGES:
        page.evaluate(f"openPrefs('{sec}')")
        t.wait(lambda: page.evaluate("currentView()") == "prefs" and page.evaluate("document.querySelector('#prefs-body').dataset.sec") == sec,
               8, f"Ajustes › {sec}")
        page.wait_for_timeout(250)
    t.check(f"las {len(PAGES)} páginas de Ajustes abren", True)

    page.evaluate("openPrefs('biblioteca')")
    page.wait_for_timeout(300)
    t.check("«Silenciar las otras apps al grabar una ventana» está, apagada",
            page.evaluate("!!document.querySelector('#pref-rec_mute_others') && prefs.rec_mute_others === false"))

    # el informe de diagnóstico, con un clic real; el servidor de prueba lo guarda en la carpeta de la corrida
    page.evaluate("openPrefs('rendimiento')")
    button = page.get_by_role("button", name="Guardar informe")
    t.wait(lambda: button.is_visible(), 10, "el botón «Guardar informe»")
    before = set(t.server.report_dir.glob("Translay-informe-*.txt")) if t.server.report_dir.exists() else set()
    button.click()
    t.wait(lambda: "Guardado en Descargas" in page.evaluate("document.querySelector('.diag-status')?.textContent || ''"), 15,
           "el aviso de informe guardado")
    new = set(t.server.report_dir.glob("Translay-informe-*.txt")) - before
    t.check("un archivo de informe nuevo", len(new) == 1, str(new))
    if new:
        text = next(iter(new)).read_text(encoding="utf-8")
        t.check("el informe trae versión, sistema y app.log", "Versión:" in text and "Sistema:" in text and "app.log" in text, text[:200])
        user = __import__("pathlib").Path.home().name
        t.check("el informe no trae el nombre del usuario", user.lower() not in text.lower(), user)
    t.check("el botón vuelve a estar disponible", button.is_enabled())
    t.no_permission_toast(page, "ajustes")
