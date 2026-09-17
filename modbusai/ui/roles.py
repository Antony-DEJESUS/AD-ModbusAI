"""Rôles exclusifs sur le port et blocages entre onglets.

Table pure (sans Qt) : pour un rôle, un état de connexion et une activité en
cours, dit quels onglets sont accessibles et pourquoi les autres ne le sont
pas. Testable sans interface ; la fenêtre ne fait que l'appliquer.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from modbusai.i18n import tr


class Role(enum.Enum):
    IDLE = "aucun"
    MASTER = "maître"
    SNIFFER = "espion"
    SLAVE = "esclave"


class Tab(enum.Enum):
    MASTER = "MAÎTRE"
    SNIFFER = "ESPION"
    SCAN = "SCAN RÉSEAU"
    DIAGNOSTIC = "DIAGNOSTIC"
    SLAVE = "SERVEUR ESCLAVE"


MASTER_TABS = (Tab.MASTER, Tab.SCAN, Tab.DIAGNOSTIC)


@dataclass(frozen=True, slots=True)
class TabState:
    enabled: bool
    reason: str = ""


def tab_states(role: Role, connected: bool, busy_tab: Tab | None = None) -> dict[Tab, TabState]:
    """``busy_tab`` : onglet dont une activité longue occupe la liaison (scan, campagne, cycle)."""
    states = {t: TabState(True) for t in Tab}
    if role is Role.SNIFFER:
        for t in Tab:
            if t is not Tab.SNIFFER:
                states[t] = TabState(False, tr("Arrêtez l'écoute (onglet ESPION) pour libérer le port."))
        return states
    if role is Role.SLAVE:
        for t in Tab:
            if t is not Tab.SLAVE:
                states[t] = TabState(False, tr("Arrêtez le serveur esclave pour libérer le port."))
        return states
    if busy_tab is not None:
        for t in Tab:
            if t is not busy_tab:
                states[t] = TabState(
                    False, f"Une activité est en cours dans l'onglet {busy_tab.value} : arrêtez-la d'abord."
                )
        return states
    if role is Role.MASTER and connected:
        # Onglets accessibles : démarrer l'écoute ou le serveur ferme d'abord la
        # liaison maître (un seul rôle tient le port), inutile de les verrouiller.
        hint = tr("La liaison maître sera fermée automatiquement pour libérer le port.")
        states[Tab.SNIFFER] = TabState(True, hint)
        states[Tab.SLAVE] = TabState(True, hint)
    return states


def can_start(role: Role, connected: bool, wanted: Role, busy: bool) -> tuple[bool, str]:
    """Peut-on démarrer ``wanted`` depuis l'état courant ?"""
    if busy:
        return False, tr("Une activité est en cours : arrêtez-la d'abord.")
    if wanted is Role.MASTER:
        if role is Role.IDLE:
            return True, ""
        if role is Role.MASTER:
            return (not connected), tr("Déjà connecté.")
        return False, tr("Arrêtez d'abord l'espion ou le serveur esclave : le port est occupé.")
    if role in (Role.IDLE, Role.MASTER):
        return True, ""  # la liaison maître est fermée avant de céder le port
    return False, tr("Un autre rôle occupe déjà le port.")
