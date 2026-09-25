"""Liaison série : ouverture/fermeture, émission, réception horodatée.

Bloquante et synchrone, sans aucune dépendance Qt : c'est ``ui/workers.py`` qui
l'isole dans un thread. Ne connaît pas Modbus.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import datetime

import serial

from modbusai.transport.framing import RtuFramer
from modbusai.transport.records import (
    ByteChunk,
    Direction,
    LinkCounters,
    LinkState,
    Parity,
    RawFrame,
    SerialSettings,
    TransmitNotAllowed,
    TransportError,
)

_PARITY = {Parity.NONE: serial.PARITY_NONE, Parity.EVEN: serial.PARITY_EVEN, Parity.ODD: serial.PARITY_ODD}
_STOPBITS = {1.0: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2.0: serial.STOPBITS_TWO}
_BYTESIZE = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}
# Port fermé par un autre fil en pleine lecture : sous Linux, pyserial passe un
# descripteur None à select() et lève TypeError ; sous Windows, SerialException.
_IO_ERRORS = (serial.SerialException, OSError, TypeError, ValueError)


class SerialLink:
    """Accès au port série.

    ``allow_tx=False`` prépare le mode passif : ``send()`` refuse d'émettre et
    RTS/DTR ne sont jamais pilotés, la liaison ne fait qu'écouter.
    """

    def __init__(self, settings: SerialSettings, *, allow_tx: bool = True) -> None:
        self.settings = settings
        self.allow_tx = allow_tx
        self.counters = LinkCounters()
        self._ser: serial.Serial | None = None
        self._state = LinkState.CLOSED
        self._last_error: str | None = None
        self._gap_ns = int(settings.frame_gap_ms * 1_000_000)
        # Le timeout de lecture pyserial = silence de fin de trame : quand read()
        # revient vide, le silence est acquis. Granularité 1 ms sous Windows.
        self._read_timeout_s = max(settings.frame_gap_ms, 1.0) / 1000.0

    # ------------------------------------------------------------------ état
    @property
    def state(self) -> LinkState:
        return self._state

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ------------------------------------------------------------ ouverture
    def open(self) -> None:
        if self.is_open:
            return
        s = self.settings
        try:
            ser = serial.Serial()
            ser.port = s.port
            ser.baudrate = s.baudrate
            ser.bytesize = _BYTESIZE[s.bytesize]
            ser.parity = _PARITY[s.parity]
            ser.stopbits = _STOPBITS[float(s.stopbits)]
            ser.timeout = self._read_timeout_s
            ser.write_timeout = 1.0
            # pyserial monte RTS et DTR par défaut à l'ouverture : on les fixe
            # explicitement. RTS reste bas au repos (monté pendant l'émission si
            # rts_toggle) ; en mode passif les deux restent bas pour ne jamais
            # activer l'émetteur d'un adaptateur RS-485.
            ser.rts = False
            ser.dtr = s.dtr if self.allow_tx else False
            ser.open()
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception as exc:  # noqa: BLE001 - pyserial lève des types propres à l'OS (termios.error…)
            self._state = LinkState.ERROR
            self._last_error = str(exc)
            raise TransportError(f"Ouverture de {s.port} impossible : {exc}") from exc
        self._ser = ser
        self._state = LinkState.OPEN
        self._last_error = None
        self.counters = LinkCounters(opened_at=datetime.now())

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except (serial.SerialException, OSError):
                pass
        self._ser = None
        self._state = LinkState.CLOSED

    # ------------------------------------------------------------- émission
    def send(self, data: bytes) -> RawFrame:
        """Émet ``data`` et renvoie la trame TX horodatée (début / fin d'émission)."""
        if not self.allow_tx:
            raise TransmitNotAllowed("Liaison ouverte en mode passif : émission interdite")
        ser = self._require_open()
        wall = datetime.now()
        try:
            ser.reset_input_buffer()
            if self.settings.rts_toggle:
                ser.rts = True
            t0 = time.perf_counter_ns()
            ser.write(data)
            ser.flush()  # attend la fin réelle de l'émission côté driver
            t1 = time.perf_counter_ns()
            if self.settings.rts_toggle:
                ser.rts = False
        except _IO_ERRORS as exc:
            raise self._io_error(ser, exc, "Erreur d'émission") from exc
        self.counters.frames_tx += 1
        self.counters.bytes_tx += len(data)
        return RawFrame(direction=Direction.TX, data=bytes(data), t_first_ns=t0, t_last_ns=t1, wall_time=wall)

    # ------------------------------------------------------------ réception
    def receive(self, timeout_ms: float) -> RawFrame | None:
        """Attend une trame : premier octet sous ``timeout_ms``, puis lecture
        jusqu'à un silence de ``frame_gap_ms``. Renvoie None si rien n'arrive."""
        ser = self._require_open()
        framer = RtuFramer(self._gap_ns)
        deadline = time.perf_counter_ns() + int(timeout_ms * 1_000_000)
        try:
            while True:
                data = ser.read(ser.in_waiting or 1)
                now = time.perf_counter_ns()
                if data:
                    frames = framer.feed(ByteChunk(bytes(data), now))
                    if frames:  # un silence >= gap est apparu entre deux blocs
                        return self._account_rx(frames[0])
                    continue
                if framer.has_pending:
                    frame = framer.flush()  # read() vide = silence acquis
                    assert frame is not None
                    return self._account_rx(frame)
                if now >= deadline:
                    return None
        except _IO_ERRORS as exc:
            raise self._io_error(ser, exc, "Erreur de réception") from exc

    def read_loop(self, stop: threading.Event) -> Iterator[RawFrame]:
        """Écoute continue : produit chaque trame vue sur le bus jusqu'à ``stop``.
        Base du futur mode passif ; fonctionne aussi avec ``allow_tx=False``."""
        ser = self._require_open()
        framer = RtuFramer(self._gap_ns)
        try:
            while not stop.is_set():
                data = ser.read(ser.in_waiting or 1)
                now = time.perf_counter_ns()
                if data:
                    for frame in framer.feed(ByteChunk(bytes(data), now)):
                        yield self._account_rx(frame)
                elif framer.has_pending:
                    frame = framer.flush(now)
                    if frame is not None:
                        yield self._account_rx(frame)
        except _IO_ERRORS as exc:
            raise self._io_error(ser, exc, "Erreur de réception") from exc

    # -------------------------------------------------------------- interne
    def _require_open(self) -> serial.Serial:
        if self._ser is None or not self._ser.is_open:
            raise TransportError("Liaison fermée")
        return self._ser

    def _io_error(self, ser: serial.Serial, exc: Exception, what: str) -> TransportError:
        """Traduit une faute d'entrée / sortie en TransportError. Un port fermé
        par un autre fil pendant l'opération se dit « Liaison fermée »."""
        self._fail(exc)
        if not ser.is_open:
            return TransportError("Liaison fermée")
        return TransportError(f"{what} : {exc}")

    def _fail(self, exc: Exception) -> None:
        self.counters.io_errors += 1
        self._state = LinkState.ERROR
        self._last_error = str(exc)

    def _account_rx(self, frame: RawFrame) -> RawFrame:
        self.counters.frames_rx += 1
        self.counters.bytes_rx += len(frame.data)
        return frame
