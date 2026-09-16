"""Serveur TCP minimal pour le rôle esclave : accepte plusieurs clients, découpe
le flux en trames par la longueur MBAP et confie chaque trame à un rappel qui
rend la réponse à émettre (ou None). Aucune connaissance de Modbus au-delà de
la longueur d'en-tête."""

from __future__ import annotations

import selectors
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from modbusai.transport.records import TransportError
from modbusai.transport.tcp_link import _mbap_frame_length

FrameHandler = Callable[[bytes, str], bytes | None]  # (trame, client) -> réponse


@dataclass(slots=True)
class TcpServerCounters:
    connections: int = 0
    active: int = 0
    frames_rx: int = 0
    frames_tx: int = 0
    invalid: int = 0
    clients: set[str] = field(default_factory=set)


class TcpServer:
    def __init__(self, host: str, port: int, handler: FrameHandler, *, response_delay_ms: float = 0.0) -> None:
        self.host = host
        self.port = port
        self.handler = handler
        self.response_delay_ms = response_delay_ms
        self.counters = TcpServerCounters()
        self._listen: socket.socket | None = None
        self._sel = selectors.DefaultSelector()
        self._buffers: dict[socket.socket, bytes] = {}

    @property
    def bound_port(self) -> int:
        return self._listen.getsockname()[1] if self._listen is not None else self.port

    def open(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen(8)
            srv.setblocking(False)
        except OSError as exc:
            raise TransportError(f"Écoute sur {self.host}:{self.port} impossible : {exc}") from exc
        self._listen = srv
        self._sel.register(srv, selectors.EVENT_READ)

    def close(self) -> None:
        for sock in list(self._buffers):
            self._drop(sock)
        if self._listen is not None:
            try:
                self._sel.unregister(self._listen)
                self._listen.close()
            except (OSError, KeyError, ValueError):
                pass
            self._listen = None

    def serve(self, stop: threading.Event) -> None:
        """Boucle bloquante jusqu'à ``stop``."""
        if self._listen is None:
            raise TransportError("Serveur non ouvert")
        while not stop.is_set():
            for key, _mask in self._sel.select(timeout=0.05):
                if key.fileobj is self._listen:
                    self._accept()
                else:
                    self._read(key.fileobj)  # type: ignore[arg-type]

    # ------------------------------------------------------------ interne
    def _accept(self) -> None:
        assert self._listen is not None
        try:
            conn, addr = self._listen.accept()
        except OSError:
            return
        conn.setblocking(False)
        self._buffers[conn] = b""
        self._sel.register(conn, selectors.EVENT_READ)
        self.counters.connections += 1
        self.counters.active += 1
        self.counters.clients.add(f"{addr[0]}:{addr[1]}")

    def _read(self, conn: socket.socket) -> None:
        try:
            data = conn.recv(4096)
        except OSError:
            data = b""
        if not data:
            self._drop(conn)
            return
        buf = self._buffers.get(conn, b"") + data
        client = self._client_name(conn)
        while True:
            total = _mbap_frame_length(buf)
            if total is None:
                if len(buf) >= 6:  # en-tête incohérent : on purge
                    self.counters.invalid += 1
                    buf = b""
                break
            if len(buf) < total:
                break
            frame, buf = buf[:total], buf[total:]
            self.counters.frames_rx += 1
            resp = self.handler(frame, client)
            if resp is not None:
                if self.response_delay_ms > 0:
                    time.sleep(self.response_delay_ms / 1000)
                try:
                    conn.sendall(resp)
                    self.counters.frames_tx += 1
                except OSError:
                    self._drop(conn)
                    return
        self._buffers[conn] = buf

    def _drop(self, conn: socket.socket) -> None:
        try:
            self._sel.unregister(conn)
        except (KeyError, ValueError):
            pass
        try:
            conn.close()
        except OSError:
            pass
        if conn in self._buffers:
            del self._buffers[conn]
            self.counters.active = max(0, self.counters.active - 1)

    @staticmethod
    def _client_name(conn: socket.socket) -> str:
        try:
            host, port = conn.getpeername()[:2]
            return f"{host}:{port}"
        except OSError:
            return "?"
