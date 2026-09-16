"""Outils réseau pour le mode TCP : ping système dans un thread, ouverture des
connexions réseau Windows. Aucune commande n'est construite à partir d'une
saisie libre : l'hôte est validé avant d'être passé en argument (jamais via un
shell)."""

from __future__ import annotations

import ipaddress
import os
import platform
import re
import subprocess
import sys

from PySide6.QtCore import QThread, Signal

_HOSTNAME = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$"
)


def valid_host(host: str) -> bool:
    host = host.strip()
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOSTNAME.match(host)) and len(host) <= 253


def ping_command(host: str, count: int = 4) -> list[str]:
    if platform.system() == "Windows":
        return ["ping", "-n", str(count), "-w", "1000", host]
    return ["ping", "-c", str(count), "-W", "1", host]


class PingWorker(QThread):
    finished_with = Signal(str, bool)  # sortie, succès

    def __init__(self, host: str, count: int = 4, parent=None) -> None:
        super().__init__(parent)
        self.host = host.strip()
        self.count = count

    def run(self) -> None:
        if not valid_host(self.host):
            self.finished_with.emit(f"Hôte invalide : {self.host!r}", False)
            return
        try:
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            proc = subprocess.run(
                ping_command(self.host, self.count),
                capture_output=True,
                text=True,
                timeout=15 + self.count * 2,
                creationflags=flags,
                encoding=sys.getdefaultencoding(),
                errors="replace",
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            self.finished_with.emit(out.strip() or "(aucune sortie)", proc.returncode == 0)
        except FileNotFoundError:
            self.finished_with.emit("Commande ping introuvable sur ce système.", False)
        except subprocess.TimeoutExpired:
            self.finished_with.emit("Ping : délai dépassé.", False)


def network_connections_available() -> bool:
    return platform.system() == "Windows"


def open_network_connections() -> str | None:
    """Ouvre le panneau « Connexions réseau » (ncpa.cpl). Renvoie un message d'erreur, ou None."""
    if not network_connections_available():
        return "Disponible uniquement sous Windows."
    try:
        os.startfile("ncpa.cpl")  # type: ignore[attr-defined]
        return None
    except OSError as exc:
        return f"Ouverture impossible : {exc}"
