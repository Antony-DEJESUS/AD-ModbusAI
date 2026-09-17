"""Charte graphique AD Automation : gris foncé et terracotta.

Source unique des couleurs de l'interface. La palette Qt (``ui/theme.py``), la
feuille de style (``ui/style.py``) et les couleurs d'état des pages en sortent :
aucune couleur n'est écrite en dur dans un widget, sinon un des deux thèmes
finit par devenir illisible.

L'accent terracotta est la signature de la marque : il est réservé à ce qui
engage (bouton principal, onglet actif, focus, sélection, progression). Les
couleurs d'état (vert, ambre, rouge, violet) qualifient une mesure et changent
de nuance selon le thème pour rester lisibles sur leur fond.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class State(enum.Enum):
    """Qualité d'une mesure, pas une couleur : la nuance dépend du thème."""

    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    SPECIAL = "special"
    MUTED = "muted"


@dataclass(frozen=True, slots=True)
class Tokens:
    name: str
    window: str  # fond de l'application
    surface: str  # champs, tables, consoles
    surface_alt: str  # lignes alternées, fonds secondaires
    card: str  # panneaux et cartes posés sur le fond
    elevated: str  # boutons, menus, infobulles
    hover: str
    border: str
    border_strong: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str  # fond teinté (onglet actif, sélection douce)
    on_accent: str  # texte posé sur l'accent
    ok: str
    warn: str
    error: str
    special: str

    def state(self, state: State) -> str:
        return {
            State.OK: self.ok,
            State.WARN: self.warn,
            State.ERROR: self.error,
            State.SPECIAL: self.special,
            State.MUTED: self.muted,
        }[state]


DARK = Tokens(
    name="sombre",
    window="#232221",
    surface="#1B1A19",
    surface_alt="#201F1E",
    card="#292827",
    elevated="#2F2E2B",
    hover="#37352F",
    border="#3B3936",
    border_strong="#4E4B46",
    text="#ECE7E0",
    muted="#9B938A",
    accent="#D97757",
    accent_hover="#E68C6E",
    accent_pressed="#C2603E",
    accent_soft="#38281F",
    on_accent="#201E1C",
    ok="#5FBF8B",
    warn="#E0A83E",
    error="#F0665E",
    special="#B892F0",
)

LIGHT = Tokens(
    name="clair",
    window="#F5F2EC",
    surface="#FFFFFF",
    surface_alt="#FAF8F3",
    card="#FFFFFF",
    elevated="#FFFFFF",
    hover="#EFEAE1",
    border="#DFD8CB",
    border_strong="#C3B9A8",
    text="#241F1B",
    muted="#786F65",
    accent="#C2603E",
    accent_hover="#D97757",
    accent_pressed="#A44E30",
    accent_soft="#F6E5DB",
    on_accent="#FFFFFF",
    ok="#177A50",
    warn="#8F6310",
    error="#C43B31",
    special="#7B54BE",
)

THEMES: dict[str, Tokens] = {DARK.name: DARK, LIGHT.name: LIGHT}
_current = LIGHT


def use(name: str) -> Tokens:
    """Fixe le thème courant et renvoie ses jetons."""
    global _current
    _current = THEMES.get(name, LIGHT)
    return _current


def current() -> Tokens:
    return _current


def color(state: State) -> str:
    """Couleur d'état lisible sur le thème courant."""
    return _current.state(state)
