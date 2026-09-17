"""Thèmes clair / sombre : palette Qt construite depuis la charte (``ui/palette.py``)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from modbusai.ui import palette as charte

THEMES = ("clair", "sombre")


def system_theme(app: QApplication) -> str:
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None and scheme() == Qt.ColorScheme.Dark:
        return "sombre"
    return "clair"


def build_palette(t: charte.Tokens) -> QPalette:
    """Palette Qt : les widgets non couverts par la feuille de style restent
    dans la charte (menus natifs, éditeurs de cellule, dialogues système)."""
    p = QPalette()
    c = QColor
    p.setColor(QPalette.ColorRole.Window, c(t.window))
    p.setColor(QPalette.ColorRole.WindowText, c(t.text))
    p.setColor(QPalette.ColorRole.Base, c(t.surface))
    p.setColor(QPalette.ColorRole.AlternateBase, c(t.surface_alt))
    p.setColor(QPalette.ColorRole.ToolTipBase, c(t.elevated))
    p.setColor(QPalette.ColorRole.ToolTipText, c(t.text))
    p.setColor(QPalette.ColorRole.Text, c(t.text))
    p.setColor(QPalette.ColorRole.PlaceholderText, c(t.muted))
    p.setColor(QPalette.ColorRole.Button, c(t.elevated))
    p.setColor(QPalette.ColorRole.ButtonText, c(t.text))
    p.setColor(QPalette.ColorRole.BrightText, c(t.error))
    p.setColor(QPalette.ColorRole.Link, c(t.accent))
    p.setColor(QPalette.ColorRole.LinkVisited, c(t.accent_pressed))
    p.setColor(QPalette.ColorRole.Highlight, c(t.accent))
    p.setColor(QPalette.ColorRole.HighlightedText, c(t.on_accent))
    p.setColor(QPalette.ColorRole.Light, c(t.hover))
    p.setColor(QPalette.ColorRole.Midlight, c(t.hover))
    p.setColor(QPalette.ColorRole.Mid, c(t.border))
    p.setColor(QPalette.ColorRole.Dark, c(t.border_strong))
    p.setColor(QPalette.ColorRole.Shadow, QColor(0, 0, 0, 96))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, c(t.muted))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, c(t.border))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, c(t.muted))
    return p


def theme_icons(t: charte.Tokens) -> dict[str, str]:
    """Chevrons et coche, dans les couleurs du thème."""
    from modbusai.ui.icons import check, chevron

    return {
        "down": chevron(QColor(t.text), "down"),
        "up": chevron(QColor(t.text), "up"),
        "down_disabled": chevron(QColor(t.muted), "down"),
        "check": check(QColor(t.on_accent)),
    }


def apply_theme(app: QApplication, name: str) -> str:
    """Applique le thème (charte + palette + feuille de style) et renvoie son nom."""
    from modbusai.ui.style import build_qss

    name = name if name in THEMES else "clair"
    tokens = charte.use(name)
    app.setStyle("Fusion")
    app.setPalette(build_palette(tokens))
    app.setStyleSheet(build_qss(tokens, theme_icons(tokens)))
    return name
