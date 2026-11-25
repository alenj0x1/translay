"""Registro de errores e informe de diagnóstico (vt/diag.py), y las listas de permisos que la sesión le pasa a la página."""

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fresh(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSLAY_LOG_DIR", raising=False)
    from vt import diag
    importlib.reload(diag)
    diag.setup(tmp_path)
    return diag


def test_one_line_per_error_with_time_and_context(tmp_path, monkeypatch):
    diag = fresh(tmp_path, monkeypatch)
    diag.error("cola.video", "algo falló\n  en dos líneas")
    diag.error("cola.video", "algo falló\n  en dos líneas")  # repetido enseguida: una sola vez
    lines = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ERROR cola\.video: algo falló en dos líneas", lines[0])


def test_exception_keeps_the_last_line(tmp_path, monkeypatch, capsys):
    diag = fresh(tmp_path, monkeypatch)
    try:
        raise ValueError("archivo dañado")
    except ValueError:
        diag.exception("exportar")
    assert "ERROR exportar: ValueError: archivo dañado" in (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "Traceback" in capsys.readouterr().err  # el detalle sigue saliendo por la consola


def test_log_is_bounded(tmp_path, monkeypatch):
    diag = fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(diag, "MAX_BYTES", 4000)
    for i in range(400):
        diag.error(f"x{i}", "y" * 40)
    size = (tmp_path / "logs" / "app.log").stat().st_size
    assert size <= 4000 + 200
    assert "ERROR x399" in (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")


def test_log_dir_from_the_desktop_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSLAY_LOG_DIR", str(tmp_path / "escritorio"))
    from vt import diag
    importlib.reload(diag)
    assert diag.setup(tmp_path / "datos") == tmp_path / "escritorio" / "app.log"


def test_report_has_version_system_and_every_log(tmp_path, monkeypatch):
    diag = fresh(tmp_path, monkeypatch)
    diag.error("interfaz.js", "x is not defined")
    (tmp_path / "logs" / "server.log").write_text("Listo: http://127.0.0.1:8765\n", encoding="utf-8")
    text = diag.report({"Perfil": "equilibrado"})
    for part in ("Versión:", "Sistema:", "Perfil: equilibrado", "===== app.log", "x is not defined", "===== server.log", "Listo:"):
        assert part in text


def test_page_gets_the_permission_lists():
    """La página no pide lo que no puede (web/js/access.js › mayRequest) con las mismas listas que usa el servidor."""
    from vt.session import IMPORT_ONLY, OWNER_ONLY, OWNER_PREFIXES, Session

    class Fake:
        owner = False
        perms = {"publica": "ver"}
        any = True

        def public(self):
            return {"owner": False, "perms": self.perms}

    s = Session.__new__(Session)
    s.access, s.admin, s.vaults, s.ws = Fake(), None, type("V", (), {"get": lambda self, x: None, "all": lambda self: []})(), None
    s.vault = type("Vault", (), {"id": "publica"})()
    msg = s._auth_msg()
    assert set(msg["owner_only"]) == OWNER_ONLY and set(msg["import_only"]) == IMPORT_ONLY
    assert tuple(msg["owner_prefixes"]) == OWNER_PREFIXES
    assert "lib_register" in msg["import_only"] and "diag_report" in msg["owner_only"]


def test_report_hides_the_user_and_secrets(tmp_path, monkeypatch):
    """El informe que la persona envía no lleva su nombre de usuario (en ninguna forma de ruta) ni claves."""
    diag = fresh(tmp_path, monkeypatch)
    user = Path.home().name
    samples = [
        f"FileNotFoundError: [Errno 2] No such file: 'C:\\\\Users\\\\{user}\\\\Videos\\\\x.mp4'",  # repr de una ruta
        f"C:\\Users\\{user}\\AppData\\Local\\x.log",
        f"c:/users/{user.lower()}/Downloads/y.txt",
        f"file:///C:%5CUsers%5C{user}%5Cz",
        "Authorization: Bearer vt_abcdefghijklmnopqrstuvwxyz0123",
        "Cookie: vt_s=abcdef123456; other=1",
        "https://hooks.slack.com/services/T000/B000/supersecretvalue",
        "https://x.test/api?token=abc123&b=2",
    ]
    out = diag.scrub("\n".join(samples))
    assert user.lower() not in out.lower(), out
    for secret in ("abcdefghijklmnopqrstuvwxyz0123", "abcdef123456", "supersecretvalue", "abc123"):
        assert secret not in out, (secret, out)
    assert "b=2" in out and "other=1" in out  # lo que no es secreto queda
