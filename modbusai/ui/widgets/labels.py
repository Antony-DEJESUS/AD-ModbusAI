"""Petites étiquettes typées : titre de section et texte secondaire.

Le style vient de la feuille (``QLabel[variant=...]``), jamais d'une couleur
posée ici : les deux thèmes doivent rester lisibles.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget


def section(text: str, parent: QWidget | None = None) -> QLabel:
    """Titre d'un bloc (au-dessus d'un tableau, d'une console, d'un panneau)."""
    label = QLabel(text, parent)
    label.setProperty("variant", "section")
    return label


def set_variant(widget: QWidget, variant: str) -> None:
    """Change la variante d'un widget déjà affiché (``primary``, ``danger``,
    ``quiet``, ou vide). Qt ne relit la feuille de style qu'après un repolissage."""
    if widget.property("variant") == (variant or None):
        return
    widget.setProperty("variant", variant or None)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def muted(text: str = "", parent: QWidget | None = None) -> QLabel:
    """Texte secondaire : aide, compteur, mention discrète."""
    label = QLabel(text, parent)
    label.setProperty("variant", "muted")
    return label
