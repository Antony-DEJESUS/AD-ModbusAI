"""Surlignages de la grille : ce qui s'éclaire, de quelle couleur, combien de temps.

Un surlignage désigne un fait (une valeur a changé, un maître vient de lire),
pas une couleur. La charte AD fournit la teinte par défaut ; l'utilisateur peut
la remplacer et couper le surlignage, parce que sur un chantier tout le monde
ne lit pas les mêmes couleurs de la même façon, et qu'un écran de portable en
plein soleil ne rend pas comme un écran de bureau.

La règle du projet tient toujours : aucune couleur n'est écrite ici. Les
valeurs par défaut viennent de ``palette.color(State...)`` ; seule une teinte
choisie par l'utilisateur, rangée dans ses réglages, peut s'y substituer. Un
« Rétablir la charte » revient à la source unique.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor

from modbusai.i18n import tr
from modbusai.ui.palette import State, color

_PREFIX = "highlights"


class Highlight(enum.Enum):
    """Les faits que la grille peut signaler."""

    MASTER_CHANGE = "maitre_changement"
    MASTER_STALE = "maitre_perime"
    SLAVE_ACCESS = "esclave_acces"


@dataclass(frozen=True, slots=True)
class HighlightSpec:
    """Fiche d'un surlignage : ce qu'il montre et ce qu'il vaut par défaut."""

    key: Highlight
    label: str
    description: str
    state: State  # teinte par défaut, prise dans la charte
    seconds: float | None  # durée de l'animation ; None = marquage permanent

    @property
    def animated(self) -> bool:
        return self.seconds is not None


def catalogue() -> tuple[HighlightSpec, ...]:
    """Les fiches, traduites au moment de l'affichage."""
    return (
        HighlightSpec(
            Highlight.MASTER_CHANGE,
            tr("Valeur qui change (onglet MAÎTRE)"),
            tr("En lecture cyclique, la ligne qui s'allume désigne le registre vivant."),
            State.OK,
            5.0,
        ),
        HighlightSpec(
            Highlight.SLAVE_ACCESS,
            tr("Cellule lue ou écrite (onglet SERVEUR ESCLAVE)"),
            tr("Montre ce qu'une supervision interroge réellement, et à quel rythme."),
            State.OK,
            2.0,
        ),
        HighlightSpec(
            Highlight.MASTER_STALE,
            tr("Valeur périmée (onglet MAÎTRE)"),
            tr("La requête a changé sans nouvelle lecture : la valeur affichée ne lui correspond plus."),
            State.MUTED,
            None,
        ),
    )


def spec(key: Highlight) -> HighlightSpec:
    return next(s for s in catalogue() if s.key is key)


# ------------------------------------------------------------------- réglages
def enabled(key: Highlight) -> bool:
    return str(QSettings().value(f"{_PREFIX}/{key.value}/enabled", "1")) not in ("0", "false", "False")


def set_enabled(key: Highlight, value: bool) -> None:
    QSettings().setValue(f"{_PREFIX}/{key.value}/enabled", "1" if value else "0")


def base_color(key: Highlight) -> QColor:
    """Teinte pleine du surlignage : celle de l'utilisateur, sinon la charte."""
    chosen = str(QSettings().value(f"{_PREFIX}/{key.value}/color", "") or "")
    if chosen:
        candidate = QColor(chosen)
        if candidate.isValid():
            return candidate
    return QColor(color(spec(key).state))


def set_color(key: Highlight, value: QColor | None) -> None:
    """``None`` rend la main à la charte."""
    QSettings().setValue(f"{_PREFIX}/{key.value}/color", value.name() if value is not None else "")


def is_custom(key: Highlight) -> bool:
    return bool(str(QSettings().value(f"{_PREFIX}/{key.value}/color", "") or ""))


def seconds(key: Highlight) -> float:
    """Durée de l'animation. Zéro pour un marquage permanent."""
    default = spec(key).seconds
    if default is None:
        return 0.0
    try:
        return max(0.5, min(60.0, float(QSettings().value(f"{_PREFIX}/{key.value}/seconds", default))))
    except (TypeError, ValueError):
        return default


def set_seconds(key: Highlight, value: float) -> None:
    QSettings().setValue(f"{_PREFIX}/{key.value}/seconds", float(value))


def reset(key: Highlight) -> None:
    """Retour à la fiche : surlignage actif, teinte de la charte, durée d'origine."""
    qs = QSettings()
    for suffix in ("enabled", "color", "seconds"):
        qs.remove(f"{_PREFIX}/{key.value}/{suffix}")


def reset_all() -> None:
    for entry in catalogue():
        reset(entry.key)


# --------------------------------------------------------------------- teinte
def tint(key: Highlight, remaining: float = 1.0, peak: float = 0.60, floor: float = 0.12) -> QColor | None:
    """Teinte de fond d'une cellule, ou ``None`` si le surlignage est coupé.

    ``remaining`` va de 1 (l'événement vient de se produire) à 0 (fin de
    l'animation) : l'éclairage s'estompe au lieu de s'éteindre d'un coup.
    """
    if not enabled(key):
        return None
    shade = QColor(base_color(key))
    shade.setAlphaF(max(0.0, min(1.0, floor + (peak - floor) * remaining)))
    return shade


def foreground(key: Highlight) -> QColor | None:
    """Couleur de texte d'un marquage permanent, ou ``None`` s'il est coupé."""
    return QColor(base_color(key)) if enabled(key) else None
