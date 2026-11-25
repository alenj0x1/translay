"""El dueño abre un video: transcripción traducida, reproducción, controles, subtítulos y personas."""


def run(t):
    page = t.page("dueño")
    page.evaluate("playItem('e2emain0003')")
    t.wait(lambda: page.evaluate("state.videoId === 'e2emain0003' && state.segments.length === 5"), 15, "la transcripción del video")
    t.check("vista del reproductor", page.evaluate("currentView()") == "player")
    rows = page.evaluate("document.querySelectorAll('#transcript [data-id], #transcript .seg').length")
    t.check("la transcripción dibuja sus frases", rows >= 5, f"{rows} filas")
    t.check("frases traducidas", "Bienvenido a la cocina." in page.evaluate("document.querySelector('#transcript').textContent"))

    t.wait(lambda: page.evaluate("vEn.readyState") >= 2, 15, "el video listo para reproducirse")
    page.evaluate("vEn.muted = true; vEn.currentTime = 0; vEn.play()")
    t.wait(lambda: page.evaluate("vEn.currentTime") > 1.0, 10, "el video avanza")
    page.evaluate("togglePlay()")
    page.wait_for_timeout(300)
    t.check("pausa con el botón", page.evaluate("vEn.paused"))

    page.evaluate("setRate(1.5)")
    t.check("velocidad 1.5×", abs(page.evaluate("vEn.playbackRate") - 1.5) < 0.01)
    page.evaluate("setRate(1)")
    before = page.evaluate("JSON.stringify([prefs.sub_es, prefs.sub_orig])")
    page.evaluate("toggleSubs()")
    page.wait_for_timeout(200)
    t.check("la tecla C cambia los subtítulos", page.evaluate("JSON.stringify([prefs.sub_es, prefs.sub_orig])") != before)
    page.evaluate("toggleSubs()")

    # dos personas en el video: la pestaña Personas las nombra
    t.wait(lambda: page.evaluate("!!document.querySelector('#side-tabs [data-tab=people]') && !document.querySelector('#side-tabs [data-tab=people]').hidden"),
           5, "la pestaña Personas")
    page.click("#side-tabs [data-tab=people]")
    page.wait_for_timeout(300)
    people = page.evaluate("document.querySelectorAll('#people input[list=people-names]').length")
    t.check("dos personas en Personas", people >= 2, f"{people}")
    t.no_permission_toast(page, "reproductor")
