"""Estructura del código: nada se pisa en silencio.

Una clase con dos métodos del mismo nombre se queda con el último sin avisar (vt/session.py tenía
_next_dub dos veces). Session se arma con partes (vt/session_*.py): un método repetido entre ellas
también ocultaría a otro según el orden de herencia.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_no_class_defines_a_method_twice():
    repeated = []
    for f in sorted((ROOT / "vt").glob("*.py")):
        for cls in (n for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.ClassDef)):
            seen = set()
            for n in cls.body:
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # @x.setter / @x.deleter repiten el nombre a propósito
                if any(isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter") for d in n.decorator_list):
                    continue
                if n.name in seen:
                    repeated.append(f"{f.name}: {cls.name}.{n.name}")
                seen.add(n.name)
    assert not repeated, repeated


def test_session_parts_do_not_shadow_each_other():
    from vt.session import Session

    owners: dict[str, str] = {}
    clash = []
    for part in Session.__mro__[:-1]:  # Session y sus partes, sin object
        for name, value in vars(part).items():
            if name.startswith("__") or not callable(value) and not isinstance(value, property):
                continue
            if name in owners:
                clash.append(f"{name}: {owners[name]} y {part.__name__}")
            owners[name] = part.__name__
    assert not clash, clash
    assert {"DubMixin", "ImportMixin", "AgentMixin", "LibraryMixin", "AdminMixin"} <= {c.__name__ for c in Session.__mro__}
