"""Maître RTU : exécute une ``Request`` et produit toujours un ``ExchangeRecord``."""

from __future__ import annotations

import time
from datetime import datetime

from modbusai.modbus.exceptions import BadResponse, CrcError, ModbusException
from modbusai.modbus.pdu import build_adu, parse_response
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, Request
from modbusai.transport.records import Direction, RawFrame, TransportError
from modbusai.transport.serial_link import SerialLink


class RtuMaster:
    def __init__(self, link: SerialLink, seq_start: int = 0) -> None:
        self.link = link
        self._seq = seq_start  # dernier numéro attribué ; continu sur la session même après reconnexion

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def settings(self):
        return self.link.settings

    def execute(self, req: Request, timeout_ms: float | None = None) -> ExchangeRecord:
        """Émet la requête, attend la réponse, décode. Ne lève que ``ValueError``
        (requête hors bornes) ; toute autre issue est encodée dans le statut.
        ``timeout_ms`` remplace le délai de la liaison (scan, tests de diagnostic)."""
        adu = build_adu(req)  # ValueError si hors bornes : à la charge de l'appelant
        self._seq += 1
        seq = self._seq
        timestamp = datetime.now()
        settings = self.link.settings

        try:
            tx = self.link.send(adu)
        except TransportError as exc:
            now = time.perf_counter_ns()
            tx = RawFrame(Direction.TX, adu, now, now, timestamp)
            return ExchangeRecord(
                seq, timestamp, req, settings, tx, None, ExchangeStatus.TRANSPORT_ERROR, None, error_message=str(exc)
            )

        timeout = settings.response_timeout_ms if timeout_ms is None else timeout_ms
        try:
            rx = self.link.receive(timeout)
        except TransportError as exc:
            return ExchangeRecord(
                seq, timestamp, req, settings, tx, None, ExchangeStatus.TRANSPORT_ERROR, None, error_message=str(exc)
            )

        if rx is None:
            return ExchangeRecord(
                seq,
                timestamp,
                req,
                settings,
                tx,
                None,
                ExchangeStatus.TIMEOUT,
                None,
                error_message=f"Timeout ({timeout:g} ms)",
            )

        response_time_ms = (rx.t_first_ns - tx.t_last_ns) / 1_000_000
        try:
            values = parse_response(req, rx.data)
        except CrcError as exc:
            return ExchangeRecord(
                seq,
                timestamp,
                req,
                settings,
                tx,
                rx,
                ExchangeStatus.CRC_ERROR,
                response_time_ms,
                error_message=str(exc),
            )
        except ModbusException as exc:
            return ExchangeRecord(
                seq,
                timestamp,
                req,
                settings,
                tx,
                rx,
                ExchangeStatus.MODBUS_EXCEPTION,
                response_time_ms,
                exception_code=exc.code,
                error_message=str(exc),
            )
        except BadResponse as exc:
            return ExchangeRecord(
                seq,
                timestamp,
                req,
                settings,
                tx,
                rx,
                ExchangeStatus.BAD_RESPONSE,
                response_time_ms,
                error_message=str(exc),
            )
        return ExchangeRecord(seq, timestamp, req, settings, tx, rx, ExchangeStatus.OK, response_time_ms, values=values)
