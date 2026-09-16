"""Bus RS-485 virtuel : N pseudo-terminaux reliés par un relais qui rediffuse
chaque octet reçu d'un point vers tous les autres (Linux uniquement).

Permet de faire dialoguer dans un même processus un maître, un serveur esclave
et un espion, chacun ouvrant « son » port série avec pyserial.
"""

from __future__ import annotations

import os
import pty
import select
import threading
import tty


class VirtualBus:
    def __init__(self, endpoints: int = 2, latency_ms: float = 0.0) -> None:
        self._masters: list[int] = []
        self._slaves: list[int] = []
        self.ports: list[str] = []
        for _ in range(endpoints):
            m, s = pty.openpty()
            # Mode brut dès la création : un point non encore ouvert par pyserial
            # resterait sinon en mode « cuit » et renverrait l'écho de tout le trafic.
            tty.setraw(s)
            self._masters.append(m)
            self._slaves.append(s)
            self.ports.append(os.ttyname(s))
        self.latency_ms = latency_ms
        self.bytes_relayed = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._relay, daemon=True)

    def __enter__(self) -> VirtualBus:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        for fd in self._masters + self._slaves:
            try:
                os.close(fd)
            except OSError:
                pass

    def inject(self, data: bytes) -> None:
        """Injecte des octets vus par tous les points (bruit, trafic tiers)."""
        for fd in self._masters:
            os.write(fd, data)

    def _relay(self) -> None:
        while not self._stop.is_set():
            readable, _, _ = select.select(self._masters, [], [], 0.005)
            for fd in readable:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    continue
                if not data:
                    continue
                self.bytes_relayed += len(data)
                for other in self._masters:
                    if other != fd:
                        try:
                            os.write(other, data)
                        except OSError:
                            pass
