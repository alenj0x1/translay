"""Genera los datos de referencia de la documentación a partir del código.

Lo que la documentación muestra como tabla (opciones de línea de comandos,
preferencias, eventos de webhooks, rutas de la API, tipos de exportación y la
versión) se lee directo de `vt/` con `ast`, sin importar los módulos (no hace
falta GPU, torch ni faster-whisper). Así esas tablas no se desactualizan: si el
código cambia, la documentación cambia al compilarla.

    python docs/scripts/gen_reference.py          # escribe docs/src/data/*.json
"""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VT = ROOT / "vt"
OUT = ROOT / "docs" / "src" / "data"


def parse(name: str) -> ast.Module:
    return ast.parse((VT / name).read_text(encoding="utf-8"))


def literal(mod: ast.Module, name: str):
    """Valor de una asignación de nivel superior (`NOMBRE = <literal>`)."""
    for node in mod.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(f"{name} no está en el módulo")


def cli_options() -> list[dict]:
    """Las llamadas `p.add_argument(...)` de vt/app.py."""
    out = []
    for node in ast.walk(parse("app.py")):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            flag = ast.literal_eval(node.args[0])
            kw = {k.arg: k.value for k in node.keywords}
            item = {"flag": flag}
            if "default" in kw:
                try:
                    item["default"] = ast.literal_eval(kw["default"])
                except ValueError:  # se lee de una variable de entorno
                    item["default"] = ""
                if item["default"] is None:  # sin valor fijo: lo decide el perfil de rendimiento
                    item["default"] = "según el perfil"
            action = ast.literal_eval(kw["action"]) if "action" in kw else None
            if action == "version":
                continue
            if action == "store_true":
                item["default"] = False
                item["switch"] = True
            if "help" in kw:
                try:
                    item["help"] = ast.literal_eval(kw["help"])
                except ValueError:  # texto armado con los modelos de vt/translate.py
                    models = literal(parse("translate.py"), "MODELS")
                    item["help"] = "none | " + " | ".join(models) + " | repo de HF (Marian CT2) (por defecto, el del perfil)"
            out.append(item)
    return out


def api_routes() -> list[dict]:
    """La tabla del docstring de vt/api.py: «MÉTODO  /ruta  descripción»."""
    doc = ast.get_docstring(parse("api.py")) or ""
    out = []
    for line in doc.splitlines():
        m = re.match(r"\s+(GET|POST|PUT|DELETE)\s+(/\S+)\s*(.*)$", line)
        if m:
            out.append({"method": m[1], "path": m[2], "notes": m[3].strip()})
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    init = (VT / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__\s*=\s*"([^"]+)"', init)[1]

    prefs = parse("prefs.py")
    sections = literal(prefs, "SECTIONS")
    schema = literal(prefs, "SCHEMA")
    details = literal(prefs, "DETAILS")
    for p in schema:
        p["group"], p["desc"] = details.get(p["key"], ("", ""))
    vault_prefs = literal(parse("vaults.py"), "VAULT_PREFS")

    events = parse("events.py")
    exporter = parse("exporter.py")
    auth = parse("auth.py")

    data = {
        "version": {"version": version},
        "cli": cli_options(),
        "prefs": {"sections": [dict(zip(("key", "title", "desc", "icon"), s)) for s in sections],
                  "schema": schema, "per_library": list(vault_prefs)},
        "events": {"catalog": [{"name": k, "desc": v} for k, v in literal(events, "CATALOG").items()],
                   "coalesce": sorted(literal(events, "COALESCE")),
                   "coalesce_s": literal(events, "COALESCE_S"),
                   "retries": list(literal(parse("webhooks.py"), "RETRIES"))},
        "exports": [{"kind": k, "name": v[0], "ext": v[1]} for k, v in literal(exporter, "KINDS").items()],
        "api": api_routes(),
        "access": {"modes": list(literal(auth, "MODES")), "perms": list(literal(auth, "PERMS")),
                   "session_days": literal(auth, "SESSION_DAYS")},
    }
    for name, value in data.items():
        (OUT / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"referencia generada en {OUT.relative_to(ROOT)} (v{version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
