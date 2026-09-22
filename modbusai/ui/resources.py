"""Accès aux ressources embarquées (logo, icône, CHANGELOG, mode d'emploi PDF), y compris sous PyInstaller."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from modbusai import APP_NAME, __version__


def project_root() -> Path:
    """Racine des ressources : dossier temporaire PyInstaller ou racine du dépôt."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent.parent


def asset_path(name: str) -> Path:
    return project_root() / "assets" / name


def logo_pixmap(size: int = 64, dark: bool = False) -> QPixmap:
    """Marque AD (le A et les lettres « AD »), variante blanche pour le thème sombre.

    L'icône d'application, elle, ne garde que le A sur fond d'accent : voir
    ``app_icon()`` et ``tools/make_logo.py``."""
    suffix = "-blanc" if dark else ""
    for candidate in (size, 128, 256, 512, 64):
        path = asset_path(f"mark-{candidate}{suffix}.png")
        if path.exists():
            pix = QPixmap(str(path))
            if candidate != size and not pix.isNull():
                from PySide6.QtCore import Qt

                pix = pix.scaledToHeight(size, Qt.TransformationMode.SmoothTransformation)
            return pix
    return QPixmap()


def app_icon() -> QIcon:
    for name in ("modbusai.ico", "modbusai-icon-256.png"):
        path = asset_path(name)
        if path.exists():
            return QIcon(str(path))
    return QIcon()


MANUAL_GLOB = "AD-ModbusAI_Mode_d_emploi_v*.pdf"


def _version_key(path: Path) -> tuple[int, ...]:
    """« ..._v1.10.2.pdf » -> (1, 10, 2) : tri numérique, pas alphabétique."""
    match = re.search(r"_v(\d+(?:\.\d+)*)\.pdf$", path.name)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def manual_pdf_path() -> Path | None:
    """Le mode d'emploi PDF embarqué : celui de la version en cours, sinon le plus récent.

    Le PDF est régénéré à part (``docs/manuel/build_manuel.py``) : une version
    corrective peut sortir avec le manuel de la précédente, qui reste valable."""
    docs = project_root() / "docs"
    exact = docs / f"AD-ModbusAI_Mode_d_emploi_v{__version__}.pdf"
    if exact.exists():
        return exact
    found = sorted(docs.glob(MANUAL_GLOB), key=_version_key)
    return found[-1] if found else None


def manual_for_viewer() -> Path | None:
    """Chemin à donner au lecteur PDF du système.

    Sous PyInstaller, le PDF vit dans le dossier temporaire de l'exécutable,
    effacé à sa fermeture : on en dépose une copie dans le dossier temporaire
    de l'utilisateur pour que le lecteur reste ouvert après l'application."""
    source = manual_pdf_path()
    if source is None or not getattr(sys, "_MEIPASS", None):
        return source
    target_dir = Path(tempfile.gettempdir()) / APP_NAME
    target = target_dir / source.name
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
    except OSError:
        return source
    return target


def changelog_text() -> str:
    for base in (project_root(), Path(__file__).resolve().parent.parent.parent):
        path = base / "CHANGELOG.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""
