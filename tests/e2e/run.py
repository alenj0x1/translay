"""Pruebas de punta a punta de Translay: la app entera como la usa una persona (o un agente).

Arma datos de prueba nuevos (tests/e2e/fixture.py), arranca un servidor propio con ellos y recorre la
interfaz con Chrome: el dueño en este equipo, invitados de cada tipo de biblioteca, celular y modo oscuro.
Cada suite falla por sus chequeos y también, sin pedirlo, por cualquier ERROR nuevo del registro de la app,
error de consola, pedido rechazado o aviso de permiso (harness.py).

    python tests/e2e/run.py                    # todas
    python tests/e2e/run.py --suite invitado,ajustes
    python tests/e2e/run.py --changed          # solo las que cubren lo que cambió desde la última pasada completa
    python tests/e2e/run.py --failed           # otra vez las que fallaron la última vez
    python tests/e2e/run.py --headed           # con ventana, para mirarla
    python tests/e2e/run.py --installed        # la app de escritorio instalada (solo lectura, tests/e2e/desktop.py)

Una suite que falla se repite una vez desde el principio; cuenta la segunda. Todo lo que crea una corrida (datos,
servidor, navegador, archivos en Descargas) se borra al terminar, y lo que haya quedado de una corrida anterior se
barre al empezar. Una pasada completa, sin cambios sin guardar, queda anotada en tests/e2e/.record.json.
"""

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

from harness import CHROME, MARK, ROOT, Run, Server, SuiteFailed, git_state, load_json, sweep  # noqa: E402

SUITES = ["inicio", "reproductor", "invitado", "ajustes", "celular"]
RECORD = HERE / ".record.json"
LAST = HERE / ".last-run.json"
CACHE = Path(tempfile.gettempdir()) / "translay-e2e-cache"  # clips generados, se reusan entre corridas (unos MB)
# qué suites cubren cada parte (--changed): la primera regla que coincide; código de prueba compartido o
# código de la app sin regla → todas; documentación → ninguna
RULES = [
    (("docs/", "README", "CHANGELOG", "linkedin/", "tools/lab/", "desktop/"), []),
    (("tests/e2e/suites/",), "suite"),  # la propia suite cambiada
    (("web/js/access.js", "vt/auth.py", "vt/api.py"), ["invitado", "ajustes"]),
    (("web/js/prefs.js", "vt/prefs.py", "vt/diag.py"), ["ajustes"]),
    (("web/js/player.js", "web/js/dubaudio.js", "web/js/comments.js", "web/js/people.js", "web/js/screentext.js"),
     ["reproductor", "invitado"]),
    (("web/css/",), ["inicio", "reproductor", "celular"]),
    (("web/js/home.js", "web/js/library.js", "web/js/vaults.js"), ["inicio", "invitado", "celular"]),
]


def changed_suites() -> list[str]:
    rec = load_json(RECORD, {})
    base = rec.get("commit")
    if not base:
        return SUITES
    files = subprocess.run(["git", "diff", "--name-only", base], cwd=ROOT, capture_output=True, text=True).stdout.split()
    files += subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                            text=True).stdout.split()
    out = set()
    for f in files:
        for prefixes, suites in RULES:
            if f.startswith(prefixes):
                if suites == "suite":
                    out.add(Path(f).stem)
                else:
                    out.update(suites)
                break
        else:
            if f.startswith(("vt/", "web/", "tests/e2e/", "run.py")):
                return SUITES
    return [s for s in SUITES if s in out]


def run_suite(name: str, server: Server, browser, shots: Path) -> dict:
    mod = importlib.import_module(f"suites.{name}")
    t = Run(name, server, browser, shots)
    offset = server.log_size()
    t0 = time.time()
    crashed = ""
    try:
        mod.run(t)
    except SuiteFailed as e:
        crashed = str(e)
    except Exception as e:  # noqa: BLE001  un error del código de prueba también la falla, con su traza
        crashed = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}"
    finally:
        for ctx in t.contexts:
            for p in ctx.pages:
                if crashed:
                    t.screenshot(p, "fallo")
        time.sleep(0.5)  # lo último que la página mandó llega al registro
        t.close()
    extra = t.unexpected(server.errors_since(offset))
    failed = [c for c in t.checks if not c[1]]
    ok = not crashed and not failed and not any(extra.values())
    for k, items in extra.items():
        for x in items[:8]:
            print(f"    FAIL {k}: {x}", flush=True)
    if crashed:
        print(f"    FAIL se detuvo: {crashed}", flush=True)
    return {"suite": name, "ok": ok, "checks": len(t.checks), "failed": [c[0] for c in failed], "crashed": crashed,
            "unexpected": extra, "seconds": round(time.time() - t0, 1)}


def run_installed(shots: Path) -> dict:
    """La app de escritorio instalada (tests/e2e/desktop.py): su propio registro, sin servidor de prueba."""
    import desktop

    t = Run("escritorio", None, None, shots)
    t.skipped, t.extra_errors = False, []
    t0, crashed = time.time(), ""
    try:
        desktop.run(t)
    except SuiteFailed as e:
        crashed = str(e)
    except Exception as e:  # noqa: BLE001
        crashed = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}"
    finally:
        t.close()
    extra = t.unexpected(t.extra_errors)
    failed = [c for c in t.checks if not c[1]]
    ok = not crashed and not failed and not any(extra.values())
    for k, items in extra.items():
        for x in items[:8]:
            print(f"    FAIL {k}: {x}", flush=True)
    if crashed:
        print(f"    FAIL se detuvo: {crashed}", flush=True)
    return {"suite": "escritorio", "ok": ok, "skipped": t.skipped, "checks": len(t.checks), "failed": [c[0] for c in failed],
            "crashed": crashed, "unexpected": extra, "seconds": round(time.time() - t0, 1)}


def _alive(pid: int) -> bool:
    """¿Sigue corriendo ese proceso? (Windows: abrirlo y mirar si ya tiene código de salida)."""
    import ctypes

    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def take_lock(lock: Path) -> bool:
    """Una corrida a la vez: la limpieza del inicio cierra los procesos y borra las carpetas de cualquier corrida."""
    try:
        pid = int(lock.read_text())
        if pid != os.getpid() and _alive(pid):
            return False
    except (OSError, ValueError):
        pass
    lock.write_text(str(os.getpid()))
    import atexit

    atexit.register(lambda: lock.unlink(missing_ok=True))
    return True


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="", help="suites separadas por coma")
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--failed", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--keep", action="store_true", help="no borrar los datos de prueba (para mirarlos)")
    ap.add_argument("--installed", action="store_true", help="la app de escritorio instalada (solo lectura)")
    a = ap.parse_args()
    if a.installed:
        print("== escritorio", flush=True)
        r = run_installed(HERE / "shots")
        print(f"   escritorio: {'se saltó' if r['skipped'] else 'pasó' if r['ok'] else 'FALLÓ'} ({r['checks']} chequeos, {r['seconds']} s)")
        sys.exit(0 if r["ok"] else 1)
    if a.suite:
        names = [s for s in a.suite.split(",") if s]
    elif a.changed:
        names = changed_suites()
    elif a.failed:
        names = [r["suite"] for r in load_json(LAST, {}).get("results", []) if not r["ok"]]
    else:
        names = SUITES
    unknown = [n for n in names if n not in SUITES]
    if unknown:
        sys.exit(f"suites desconocidas: {unknown} (hay: {', '.join(SUITES)})")
    if not names:
        print("nada que correr")
        return
    if not Path(CHROME).exists():
        sys.exit("hace falta Google Chrome")
    from playwright.sync_api import sync_playwright

    from fixture import build

    lock = Path(tempfile.gettempdir()) / (MARK + ".lock")
    if not take_lock(lock):
        sys.exit("ya hay otra corrida e2e en marcha (su limpieza borraría la de esta)")
    sweep()
    # carpetas de corridas anteriores que no se pudieron borrar (un corte a mitad)
    for old in Path(tempfile.gettempdir()).glob(MARK + "-*"):
        if old.is_dir() and old != CACHE:
            shutil.rmtree(old, ignore_errors=True)
    work = Path(tempfile.mkdtemp(prefix=MARK + "-"))
    shots = HERE / "shots"
    shutil.rmtree(shots, ignore_errors=True)
    results, t_all = [], time.time()
    server = None
    try:
        data = work / "datos"
        t0 = time.time()
        build(data, cache=CACHE)
        server = Server(data, work / "servidor.log")
        boot = server.start()
        print(f"datos y servidor listos en {time.time() - t0:.0f} s (arranque {boot:.0f} s) · {server.url}", flush=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME, headless=not a.headed, args=[f"--{MARK}"])
            for name in names:
                print(f"== {name}", flush=True)
                r = run_suite(name, server, browser, shots)
                if not r["ok"]:
                    print(f"   {name} falló; se repite una vez", flush=True)
                    r2 = run_suite(name, server, browser, shots)
                    r2["retried"] = True
                    r = r2
                print(f"   {name}: {'pasó' if r['ok'] else 'FALLÓ'} ({r['checks']} chequeos, {r['seconds']} s)", flush=True)
                results.append(r)
            browser.close()
    finally:
        if server:
            server.stop()
        sweep()
        if a.keep:
            print(f"datos de prueba: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    ok = all(r["ok"] for r in results)
    state = git_state()
    LAST.write_text(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), **state, "results": results}, ensure_ascii=False,
                               indent=1), encoding="utf-8")
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} suites, {sum(r['checks'] for r in results)} chequeos, "
          f"{time.time() - t_all:.0f} s")
    for r in results:
        print(f"  {r['suite']:12s} {'ok ' if r['ok'] else 'FAIL'} {r['seconds']:6.1f} s" + ("  (repetida)" if r.get("retried") else ""))
    if ok and set(names) == set(SUITES) and not state["dirty"]:
        RECORD.write_text(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "commit": state["commit"],
                                      "checks": sum(r["checks"] for r in results)}, indent=1), encoding="utf-8")
        print("Pasada completa anotada en tests/e2e/.record.json")
    if not ok:
        print(f"capturas de los fallos: {shots}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
