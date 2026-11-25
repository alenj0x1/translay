"""En un celular (390 px), en claro y oscuro: nada se sale de la pantalla y el video se abre."""

OVERFLOW = "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth"


def run(t):
    for dark in (False, True):
        mode = "oscuro" if dark else "claro"
        page = t.page("dueño", mobile=True, dark=dark)
        page.evaluate(f"setPref('theme_mode', '{mode}'); applyTheme()") if False else None
        page.evaluate("setView('library')")
        page.wait_for_timeout(500)
        t.check(f"inicio sin desborde lateral ({mode})", page.evaluate(OVERFLOW) <= 1, f"{page.evaluate(OVERFLOW)} px")
        page.evaluate("playItem('e2emain0001')")
        t.wait(lambda: page.evaluate("state.videoId === 'e2emain0001' && state.segments.length === 5"), 15, "el video en el celular")
        page.wait_for_timeout(500)
        t.check(f"reproductor sin desborde lateral ({mode})", page.evaluate(OVERFLOW) <= 1, f"{page.evaluate(OVERFLOW)} px")
        page.evaluate("openPrefs()")
        page.wait_for_timeout(400)
        t.check(f"Ajustes sin desborde lateral ({mode})", page.evaluate(OVERFLOW) <= 1, f"{page.evaluate(OVERFLOW)} px")
        t.screenshot(page, f"celular-{mode}")
        t.no_permission_toast(page, f"celular {mode}")
