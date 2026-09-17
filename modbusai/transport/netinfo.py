"""Adresses IPv4 de la machine.

Le serveur esclave TCP écoute par défaut sur 0.0.0.0 : c'est exact mais
illisible sur un chantier, où l'on veut savoir quelle adresse donner au
superviseur. On renvoie ici les données brutes, la couche ``ui`` les met en
phrase. Aucune trame n'est émise : la socket UDP n'est que « connectée »,
ce qui suffit au système pour désigner l'interface de la route par défaut.
"""

from __future__ import annotations

import socket


def primary_ipv4() -> str:
    """Adresse de l'interface qui porte la route par défaut, vide si indéterminée."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.2)
        sock.connect(("192.0.2.1", 9))  # réseau de documentation (RFC 5737), jamais routé
        return str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        sock.close()


def local_ipv4_addresses() -> list[str]:
    """Adresses IPv4 utilisables de la machine, celle de la route par défaut en tête."""
    found: list[str] = []
    primary = primary_ipv4()
    if primary and not primary.startswith("127."):
        found.append(primary)
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except (OSError, UnicodeError):
        infos = []
    for info in infos:
        addr = str(info[4][0])
        if not addr.startswith("127.") and addr not in found:
            found.append(addr)
    return found


def is_wildcard(host: str) -> bool:
    """Vrai si ``host`` désigne « toutes les interfaces »."""
    return host.strip() in ("", "0.0.0.0", "*")
