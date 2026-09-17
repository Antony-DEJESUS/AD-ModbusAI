"""Dimensions et polices dérivées du texte, jamais de constantes en pixels.

Sous Windows à 125 ou 150 % d'échelle, Qt agrandit la police mais pas les
largeurs écrites en dur : les libellés se font couper. On dimensionne donc à
partir des métriques de la police du widget.

Y vit aussi la police « chiffres tabulaires » : dans un tableau rafraîchi en
continu, des chiffres de largeurs différentes font danser les colonnes.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QWidget


def text_width(widget: QWidget, *samples: str, extra: int = 0) -> int:
    """Largeur du plus long des textes qu'un widget doit pouvoir montrer."""
    metrics = widget.fontMetrics()
    return max(metrics.horizontalAdvance(sample) for sample in samples) + extra


def line_height(widget: QWidget, lines: float = 1.0, extra: int = 0) -> int:
    return int(widget.fontMetrics().height() * lines) + extra


def tabular(font: QFont) -> QFont:
    """Même police, chiffres à chasse fixe (``tnum``)."""
    numeric = QFont(font)
    try:
        numeric.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):  # Qt plus ancien : on garde la police telle quelle
        pass
    return numeric


def use_tabular_figures(widget: QWidget) -> None:
    """Applique les chiffres tabulaires au widget (tableaux, compteurs, mesures)."""
    widget.setFont(tabular(widget.font()))


def mono_font(point_size: int | None = None) -> QFont:
    """Police à chasse fixe du système, chiffres tabulaires compris."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setStyleHint(QFont.StyleHint.Monospace)
    if point_size is not None:
        font.setPointSize(point_size)
    return tabular(font)
