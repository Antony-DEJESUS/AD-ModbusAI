"""Thèmes clair / sombre : palettes Qt appliquées au style Fusion."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("clair", "sombre")


def system_theme(app: QApplication) -> str:
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None and scheme() == Qt.ColorScheme.Dark:
        return "sombre"
    return "clair"


def dark_palette() -> QPalette:
    p = QPalette()
    window = QColor(45, 45, 48)
    base = QColor(30, 30, 32)
    text = QColor(230, 230, 230)
    disabled = QColor(128, 128, 128)
    highlight = QColor(42, 130, 218)
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 43))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(60, 60, 64))
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    p.setColor(QPalette.ColorRole.Button, QColor(58, 58, 62))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.ColorRole.Link, QColor(90, 160, 255))
    p.setColor(QPalette.ColorRole.Highlight, highlight)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Light, QColor(80, 80, 84))
    p.setColor(QPalette.ColorRole.Midlight, QColor(65, 65, 68))
    p.setColor(QPalette.ColorRole.Mid, QColor(50, 50, 53))
    p.setColor(QPalette.ColorRole.Dark, QColor(25, 25, 27))
    p.setColor(QPalette.ColorRole.Shadow, QColor(10, 10, 10))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(80, 80, 80))
    return p


def light_palette() -> QPalette:
    p = QPalette()
    window = QColor(240, 240, 240)
    text = QColor(20, 20, 20)
    disabled = QColor(150, 150, 150)
    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(246, 246, 246))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled)
    p.setColor(QPalette.ColorRole.Button, QColor(235, 235, 235))
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor(200, 0, 0))
    p.setColor(QPalette.ColorRole.Link, QColor(0, 90, 200))
    p.setColor(QPalette.ColorRole.Highlight, QColor(48, 140, 198))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Light, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Midlight, QColor(225, 225, 225))
    p.setColor(QPalette.ColorRole.Mid, QColor(190, 190, 190))
    p.setColor(QPalette.ColorRole.Dark, QColor(160, 160, 160))
    p.setColor(QPalette.ColorRole.Shadow, QColor(100, 100, 100))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def apply_theme(app: QApplication, name: str) -> str:
    """Applique le thème (palette + feuille de style) et renvoie son nom normalisé."""
    from modbusai.ui.style import build_qss

    name = name if name in THEMES else "clair"
    app.setStyle("Fusion")
    app.setPalette(dark_palette() if name == "sombre" else light_palette())
    app.setStyleSheet(build_qss())
    return name
