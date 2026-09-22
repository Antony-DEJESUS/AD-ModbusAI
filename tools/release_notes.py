"""Extrait d'une version sa section du CHANGELOG, et vérifie l'accord des numéros.

Sert à la publication automatique : le corps de la release GitHub est la section
du CHANGELOG, pas un texte écrit deux fois. Et un tag qui ne correspond pas à
``__version__`` arrête la publication plutôt que de livrer un exécutable mal
nommé.

    python tools/release_notes.py                 section de la version courante
    python tools/release_notes.py 1.1.0           section de cette version
    python tools/release_notes.py --check v1.1.0  compare le tag à __version__
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"


def package_version() -> str:
    text = (ROOT / "modbusai" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'__version__ = "([^"]+)"', text)
    if found is None:
        raise SystemExit("__version__ introuvable dans modbusai/__init__.py")
    return found.group(1)


def section(version: str) -> str:
    """Le bloc « ## <version> ... » jusqu'au titre suivant, sans sa ligne de titre."""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and line[3:].split(" - ")[0].strip() == version:
            start = index
            break
    if start is None:
        raise SystemExit(f"Aucune section « ## {version} » dans CHANGELOG.md")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start + 1 : end]).strip()


def check(tag: str) -> None:
    """Le tag doit porter la version du paquet, préfixe « v » toléré."""
    wanted = package_version()
    given = tag[1:] if tag.startswith("v") else tag
    if given != wanted:
        raise SystemExit(
            f"Tag « {tag} » et __version__ « {wanted} » ne s'accordent pas. "
            "Corrigez modbusai/__init__.py et pyproject.toml, ou reposez le tag."
        )
    section(wanted)  # lève si la section manque : pas de release sans historique
    print(f"Tag {tag} conforme : version {wanted}, section du CHANGELOG présente.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?", help="version à extraire ; par défaut celle du paquet")
    parser.add_argument("--check", metavar="TAG", help="vérifie que le tag correspond à __version__")
    args = parser.parse_args()
    if args.check:
        check(args.check)
        return
    print(section(args.version or package_version()))


if __name__ == "__main__":
    main()
