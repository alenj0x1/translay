"""Libera una versión: número nuevo, changelog, commit y etiqueta.

    python scripts/release.py 1.1.0            # hace todo
    python scripts/release.py 1.1.0 --dry-run  # solo muestra lo que haría
    python scripts/release.py --next           # sugiere el número según los commits

Pasos:
  1. Revisa que el árbol esté limpio y que «Sin publicar» en CHANGELOG.md tenga algo.
  2. Cambia la versión en vt/__init__.py y docs/package.json.
  3. Mueve «Sin publicar» a «## <versión> · <fecha>» y deja una sección vacía nueva.
  4. Commit «chore(release): v<versión>» y etiqueta anotada v<versión> con las notas.

No hace push: revisa y luego `git push --follow-tags`.
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
INIT = ROOT / "vt" / "__init__.py"
DOCS_PKG = ROOT / "docs" / "package.json"
UNRELEASED = "## Sin publicar"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def current() -> str:
    return re.search(r'__version__\s*=\s*"([^"]+)"', INIT.read_text(encoding="utf-8"))[1]


def suggest() -> str:
    """Versionado semántico a partir de los commits desde la última etiqueta."""
    major, minor, patch = map(int, current().split("."))
    try:
        since = git("describe", "--tags", "--abbrev=0")
        log = git("log", f"{since}..HEAD", "--format=%s%n%b")
    except subprocess.CalledProcessError:
        log = git("log", "--format=%s%n%b")
    if re.search(r"^[a-z]+(\(.+\))?!:|^BREAKING CHANGE:", log, re.M):
        return f"{major + 1}.0.0"
    if re.search(r"^feat(\(.+\))?:", log, re.M):
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version", nargs="?", help="x.y.z")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--next", action="store_true", help="sugerir la próxima versión y salir")
    a = ap.parse_args()

    if a.next:
        print(suggest())
        return 0
    if not a.version or not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        ap.error("indica la versión como x.y.z (o usa --next)")
    if git("status", "--porcelain"):
        sys.exit("Hay cambios sin commit: guárdalos antes de liberar.")
    if a.version in git("tag", "--list", f"v{a.version}"):
        sys.exit(f"La etiqueta v{a.version} ya existe.")

    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^{UNRELEASED}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md no tiene la sección «{UNRELEASED}».")
    notes = m[1].strip()
    if not notes:
        sys.exit("«Sin publicar» está vacía: anota los cambios en CHANGELOG.md antes de liberar.")

    today = dt.date.today().isoformat()
    new_text = text[:m.start()] + f"{UNRELEASED}\n\n## {a.version} · {today}\n\n{notes}\n\n" + text[m.end():]
    print(f"{current()} → {a.version} ({today})\n\n{notes}\n")
    if a.dry_run:
        print("(--dry-run: no se cambió nada)")
        return 0

    CHANGELOG.write_text(new_text, encoding="utf-8")
    INIT.write_text(re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{a.version}"',
                           INIT.read_text(encoding="utf-8")), encoding="utf-8")
    pkg = json.loads(DOCS_PKG.read_text(encoding="utf-8"))
    pkg["version"] = a.version
    DOCS_PKG.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    git("add", str(CHANGELOG), str(INIT), str(DOCS_PKG))
    git("commit", "-m", f"chore(release): v{a.version}")
    git("tag", "-a", f"v{a.version}", "-m", f"Translay {a.version}\n\n{notes}")
    print(f"Listo: commit y etiqueta v{a.version}. Para publicarla: git push --follow-tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
