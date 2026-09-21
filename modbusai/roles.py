"""Rôles et arbitrage des ports : qui tient quelle ressource.

Un port ne peut servir qu'à un rôle à la fois, mais rien n'interdit de faire
tourner plusieurs rôles en parallèle sur des ports différents : maître sur
COM3 et serveur esclave sur COM7, par exemple, pour se répondre à soi-même ou
simuler un équipement pendant qu'on interroge le vrai.

Table pure (sans Qt) : elle dit quels onglets sont accessibles et si un rôle
peut démarrer sur un port donné. Testable sans interface ; la fenêtre et le
serveur MCP l'appliquent, d'où sa place hors de la couche ``ui``.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass

from modbusai.i18n import tr
from modbusai.transport.records import LinkSettings, SerialSettings


class Role(enum.Enum):
    IDLE = "aucun"
    MASTER = "maître"
    SNIFFER = "espion"
    SLAVE = "serveur esclave"


class Tab(enum.Enum):
    MASTER = "MAÎTRE"
    SNIFFER = "ESPION"
    SCAN = "SCAN RÉSEAU"
    DIAGNOSTIC = "DIAGNOSTIC"
    SLAVE = "SERVEUR ESCLAVE"


MASTER_TABS = (Tab.MASTER, Tab.SCAN, Tab.DIAGNOSTIC)
"""Onglets servis par la même liaison maître : ils se partagent un seul port."""


def port_key(settings: LinkSettings | None, listen: bool = False) -> str:
    """Ressource occupée par une liaison.

    Deux liaisons entrent en conflit quand leur clé est identique : même port
    série, ou même point TCP. ``listen`` distingue le serveur esclave (qui
    ouvre une écoute locale) d'un maître TCP (qui se connecte au loin) :
    écouter sur 502 et interroger un esclave distant sur 502 ne se gênent pas.
    """
    if settings is None:
        return ""
    if isinstance(settings, SerialSettings):
        return settings.port.strip().upper()  # le port série est physique : écoute ou émission, c'est le même
    host = settings.host.strip().lower() or "0.0.0.0"
    return f"{'tcp-ecoute' if listen else 'tcp'}:{host}:{settings.port}"


@dataclass(frozen=True, slots=True)
class Occupancy:
    """Un rôle actif et la ressource qu'il tient."""

    role: Role
    port: str


@dataclass(frozen=True, slots=True)
class TabState:
    enabled: bool
    reason: str = ""


def tab_states(busy_tab: Tab | None = None) -> dict[Tab, TabState]:
    """``busy_tab`` : onglet dont une activité longue occupe la liaison maître
    (scan, campagne, torture). Elle ne verrouille que les onglets qui partagent
    cette liaison ; l'espion et le serveur esclave ont la leur."""
    states = {t: TabState(True) for t in Tab}
    if busy_tab in MASTER_TABS:
        reason = tr("Une activité est en cours dans l'onglet {p0} : arrêtez-la d'abord.").format(p0=tr(busy_tab.value))
        for t in MASTER_TABS:
            if t is not busy_tab:
                states[t] = TabState(False, reason)
    return states


def can_start(wanted: Role, port: str, active: Iterable[Occupancy] = ()) -> tuple[bool, str]:
    """Peut-on démarrer ``wanted`` sur ``port`` ? Sinon, pourquoi."""
    for occupancy in active:
        if occupancy.role is wanted:
            return False, tr("{p0} est déjà actif.").format(p0=tr(wanted.value).capitalize())
        if port and occupancy.port == port:
            return False, tr("{p0} est déjà utilisé par {p1} : choisissez un autre port.").format(
                p0=port, p1=tr(occupancy.role.value)
            )
    return True, ""
