"""Liaison Modbus TCP : même interface que ``SerialLink``.

Bloquante et synchrone, sans Qt. Le flux TCP n'a pas de silences : la
délimitation des trames s'appuie sur la longueur annoncée dans l'en-tête MBAP
(octets 4-5), seule connaissance de Modbus admise dans cette couche.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import datetime

from modbusai.transport.records import (
    ByteChunk,
    Direction,
    LinkCounters,
    LinkState,
    RawFrame,
    TcpSettings,
    TransmitNotAllowed,
    TransportError,
)

_HEADER = 6  # octets nécessaires pour connaître la longueur totale (MBAP)
_MAX_FRAME = 7 + 253


def _mbap_frame_length(header: bytes) -> int | None:
    if len(header) < _HEADER:
        return None
    length = int.from_bytes(header[4:6], "big")
    if length < 2 or length > 254:
        return None
    return _HEADER + length


class TcpLink:
    def __init__(self, settings: TcpSettings, *, allow_tx: bool = True) -> None:
        self.settings = settings
        self.allow_tx = allow_tx
        self.counters = LinkCounters()
        self._sock: socket.socket | None = None
        self._state = LinkState.CLOSED
        self._last_error: str | None = None
        self._buffer = b""

    # ------------------------------------------------------------------ état
    @property
    def state(self) -> LinkState:
        return self._state

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------ ouverture
    def open(self) -> None:
        if self.is_open:
            return
        s = self.settings
        try:
            sock = socket.create_connection((s.host, s.port), timeout=s.connect_timeout_ms / 1000)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as exc:  # noqa: BLE001 - erreurs réseau variées (gaierror, timeout, refus)
            self._state = LinkState.ERROR
            self._last_error = str(exc)
            raise TransportError(f"Connexion à {s.summary()} impossible : {exc}") from exc
        self._sock = sock
        self._buffer = b""
        self._state = LinkState.OPEN
        self._last_error = None
        self.counters = LinkCounters(opened_at=datetime.now())

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._state = LinkState.CLOSED

    # ------------------------------------------------------------- émission
    def send(self, data: bytes) -> RawFrame:
        if not self.allow_tx:
            raise TransmitNotAllowed("Liaison ouverte en mode passif : émission interdite")
        sock = self._require_open()
        wall = datetime.now()
        self._buffer = b""
        try:
            t0 = time.perf_counter_ns()
            sock.sendall(data)
            t1 = time.perf_counter_ns()
        except OSError as exc:
            self._fail(exc)
            raise TransportError(f"Erreur d'émission : {exc}") from exc
        self.counters.frames_tx += 1
        self.counters.bytes_tx += len(data)
        return RawFrame(direction=Direction.TX, data=bytes(data), t_first_ns=t0, t_last_ns=t1, wall_time=wall)

    # ------------------------------------------------------------ réception
    def receive(self, timeout_ms: float) -> RawFrame | None:
        """Attend une trame MBAP complète sous ``timeout_ms`` ; None si rien n'arrive."""
        sock = self._require_open()
        deadline = time.perf_counter_ns() + int(timeout_ms * 1_000_000)
        chunks: list[ByteChunk] = []
        wall: datetime | None = None
        try:
            while True:
                total = _mbap_frame_length(self._buffer)
                if total is not None and len(self._buffer) >= total:
                    frame, self._buffer = self._buffer[:total], self._buffer[total:]
                    return self._make_frame(frame, chunks, wall)
                if self._buffer and total is None and len(self._buffer) >= _HEADER:
                    # En-tête incohérent : on purge et on rend ce qu'on a comme trame invalide
                    frame, self._buffer = self._buffer, b""
                    return self._make_frame(frame, chunks, wall)
                remaining = deadline - time.perf_counter_ns()
                if remaining <= 0:
                    return None
                sock.settimeout(remaining / 1e9)
                try:
                    data = sock.recv(4096)
                except TimeoutError:
                    return None
                if not data:
                    raise TransportError("Connexion fermée par l'équipement")
                now = time.perf_counter_ns()
                if wall is None:
                    wall = datetime.now()
                chunks.append(ByteChunk(bytes(data), now))
                self._buffer += data
        except TransportError:
            self._fail(Exception("connexion fermée"))
            raise
        except OSError as exc:
            self._fail(exc)
            raise TransportError(f"Erreur de réception : {exc}") from exc

    def read_loop(self, stop: threading.Event) -> Iterator[RawFrame]:
        """Flux continu de trames MBAP (utile pour un client passif ou un serveur)."""
        sock = self._require_open()
        try:
            while not stop.is_set():
                total = _mbap_frame_length(self._buffer)
                if total is not None and len(self._buffer) >= total:
                    frame, self._buffer = self._buffer[:total], self._buffer[total:]
                    yield self._make_frame(frame, [], None)
                    continue
                sock.settimeout(0.05)
                try:
                    data = sock.recv(4096)
                except TimeoutError:
                    continue
                if not data:
                    raise TransportError("Connexion fermée par l'équipement")
                self._buffer += data
        except OSError as exc:
            self._fail(exc)
            raise TransportError(f"Erreur de réception : {exc}") from exc

    # -------------------------------------------------------------- interne
    def _make_frame(self, data: bytes, chunks: list[ByteChunk], wall: datetime | None) -> RawFrame:
        now = time.perf_counter_ns()
        first = chunks[0].t_ns if chunks else now
        last = chunks[-1].t_ns if chunks else now
        self.counters.frames_rx += 1
        self.counters.bytes_rx += len(data)
        return RawFrame(Direction.RX, data, first, last, wall or datetime.now(), tuple(chunks), None)

    def _require_open(self) -> socket.socket:
        if self._sock is None:
            raise TransportError("Liaison fermée")
        return self._sock

    def _fail(self, exc: Exception) -> None:
        self.counters.io_errors += 1
        self._state = LinkState.ERROR
        self._last_error = str(exc)
