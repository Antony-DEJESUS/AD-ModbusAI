"""Accès aux ressources embarquées (logo, icône, CHANGELOG), y compris sous PyInstaller."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap


def project_root() -> Path:
    """Racine des ressources : dossier temporaire PyInstaller ou racine du dépôt."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent.parent


def asset_path(name: str) -> Path:
    return project_root() / "assets" / name


def logo_pixmap(size: int = 64, dark: bool = False) -> QPixmap:
    """Logo AD Automation, variante blanche pour le thème sombre."""
    suffix = "-blanc" if dark else ""
    for candidate in (size, 128, 256, 512, 64):
        path = asset_path(f"logo-ad-{candidate}{suffix}.png")
        if path.exists():
            pix = QPixmap(str(path))
            if candidate != size and not pix.isNull():
                from PySide6.QtCore import Qt

                pix = pix.scaledToHeight(size, Qt.TransformationMode.SmoothTransformation)
            return pix
    return QPixmap()


def app_icon() -> QIcon:
    for name in ("modbusai.ico", "modbusai-icon-256.png", "logo-ad-256.png"):
        path = asset_path(name)
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def changelog_text() -> str:
    for base in (project_root(), Path(__file__).resolve().parent.parent.parent):
        path = base / "CHANGELOG.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""
