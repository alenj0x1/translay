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
    # fondo sin la voz original: con un clic real (el audio necesita un gesto), suena el fondo y el original calla
    page.evaluate("playItem('e2emain0001')")
    t.wait(lambda: page.evaluate("state.videoId === 'e2emain0001' && vEn.readyState >= 2"), 15, "el video con fondo separado")
    t.check("el video trae su fondo separado", page.evaluate("bgUrl()").endswith("/audio/e2emain0001/fondo.m4a"))
    page.evaluate("setView('player')")
    # abre y arranca solo cuando está listo: se pausa y se reanuda como una persona, con clics reales en el botón
    t.wait(lambda: not page.evaluate("vEn.paused"), 10, "el video arranca solo")
    page.hover("#v-en")
    page.click("#c-play")
    t.wait(lambda: page.evaluate("vEn.paused"), 3, "pausa con un clic")
    page.click("#c-play")
    t.wait(lambda: page.evaluate("!vEn.paused && !!state.audio && bgEl.readyState >= 2"), 10, "el video y su fondo sonando")
    t.wait(lambda: page.evaluate("!bgEl.paused && Math.abs(bgEl.currentTime - vEn.currentTime) < 0.3"), 5, "el fondo al compás del video")
    t.wait(lambda: page.evaluate("state.audio.orig.gain.value") < 0.01, 3, "el original en silencio bajo la voz doblada")
    page.evaluate("setMode(false)")
    t.wait(lambda: page.evaluate("state.audio.orig.gain.value") > 0.9 and page.evaluate("bgEl.paused"), 3,
           "en el original, el fondo calla y el original vuelve")
    page.evaluate("setMode(true); togglePlay()")

    # editor de frases: doble clic real en la traducción, corregirla y guardar con Enter; queda al recargar
    page.evaluate("playItem('e2emain0002'); vEn.pause()")
    t.wait(lambda: page.evaluate("state.videoId === 'e2emain0002' && state.segments.length === 5"), 15, "otro video abierto")
    page.evaluate("vEn.pause(); state.autoWait = false")
    cell = page.locator("#transcript li[data-id] > .cell").nth(3)  # la traducción de la segunda frase
    cell.dblclick()
    t.wait(lambda: page.locator("#transcript .seditor textarea").count() == 1, 5, "el editor de la frase")
    page.locator("#transcript .seditor textarea").fill("Hoy hacemos un pan casero en casa.")
    page.locator("#transcript .seditor textarea").press("Enter")
    t.wait(lambda: "Hoy hacemos un pan casero en casa." in page.evaluate("document.querySelector('#transcript').textContent")
           and page.locator("#transcript .seditor").count() == 0, 5, "la traducción corregida en la transcripción")
    page.reload()
    t.wait(lambda: page.evaluate("typeof state !== 'undefined' && !!state.ws && state.ws.readyState === 1"), 20, "recargar")
    page.evaluate("playItem('e2emain0002')")
    t.wait(lambda: page.evaluate("state.videoId === 'e2emain0002' && state.segments.length === 5"), 15, "el video otra vez")
    t.check("la corrección queda guardada", page.evaluate("state.segments[1].translation") == "Hoy hacemos un pan casero en casa.")
    t.no_permission_toast(page, "reproductor")
