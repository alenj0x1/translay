"""Libera una versión: número nuevo, changelog, commit y etiqueta.

    python scripts/release.py 1.1.0            # hace todo
    python scripts/release.py 1.1.0 --dry-run  # solo muestra lo que haría
    python scripts/release.py --next           # sugiere el número según los commits

Pasos:
  1. Revisa que el árbol esté limpio y que «Unreleased» (CHANGELOG.md) y «Sin publicar»
     (CHANGELOG.es.md) tengan algo.
  2. Cambia la versión en vt/__init__.py, docs/package.json y la app de escritorio
     (desktop/package.json, Cargo.toml, Cargo.lock y tauri.conf.json).
  3. Mueve esas secciones a «## <versión> · <fecha>» y deja una sección vacía nueva en cada changelog.
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
# cada changelog con el título de su sección de cambios sin publicar
CHANGELOGS = [(ROOT / "CHANGELOG.md", "## Unreleased"), (ROOT / "CHANGELOG.es.md", "## Sin publicar")]
INIT = ROOT / "vt" / "__init__.py"
PACKAGES = [ROOT / "docs" / "package.json", ROOT / "desktop" / "package.json", ROOT / "desktop" / "src-tauri" / "tauri.conf.json"]
CARGO = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
CARGO_LOCK = ROOT / "desktop" / "src-tauri" / "Cargo.lock"


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

    today = dt.date.today().isoformat()
    updated = []
    for path, heading in CHANGELOGS:
        text = path.read_text(encoding="utf-8")
        m = re.search(rf"^{heading}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if not m:
            sys.exit(f"{path.name} no tiene la sección «{heading[3:]}».")
        notes = m[1].strip()
        if not notes:
            sys.exit(f"«{heading[3:]}» está vacía: anota los cambios en {path.name} antes de liberar.")
        updated.append((path, text[:m.start()] + f"{heading}\n\n## {a.version} · {today}\n\n{notes}\n\n" + text[m.end():], notes))
    notes = updated[0][2]  # la etiqueta lleva las notas en inglés
    print(f"{current()} → {a.version} ({today})\n\n{notes}\n")
    if a.dry_run:
        print("(--dry-run: no se cambió nada)")
        return 0

    for path, text, _ in updated:
        path.write_text(text, encoding="utf-8")
    INIT.write_text(re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{a.version}"',
                           INIT.read_text(encoding="utf-8")), encoding="utf-8")
    for pkg_path in PACKAGES:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        pkg["version"] = a.version
        pkg_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CARGO.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{a.version}"', CARGO.read_text(encoding="utf-8"), count=1),
                     encoding="utf-8")
    CARGO_LOCK.write_text(re.sub(r'(name = "translay"\nversion = )"[^"]+"', rf'\g<1>"{a.version}"',
                                 CARGO_LOCK.read_text(encoding="utf-8")), encoding="utf-8")

    git("add", *(str(p) for p, _ in CHANGELOGS), str(INIT), *(str(p) for p in PACKAGES), str(CARGO), str(CARGO_LOCK))
    git("commit", "-m", f"chore(release): v{a.version}")
    git("tag", "-a", f"v{a.version}", "-m", f"Translay {a.version}\n\n{notes}")
    print(f"Listo: commit y etiqueta v{a.version}. Para publicarla: git push --follow-tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
