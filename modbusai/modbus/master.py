"""Maître Modbus : exécute une ``Request`` et produit toujours un ``ExchangeRecord``.

L'enveloppe (RTU avec CRC, ou TCP avec MBAP) est une stratégie ``Framing`` ;
la liaison (série ou TCP) est n'importe quel objet exposant ``send`` /
``receive`` / ``settings``.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Protocol

from modbusai.modbus.exceptions import BadResponse, CrcError, ModbusException
from modbusai.modbus.mbap import build_mbap, parse_mbap
from modbusai.modbus.pdu import BROADCAST_ID, build_adu, build_pdu, parse_response, parse_response_pdu
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, Request
from modbusai.transport.records import Direction, LinkSettings, RawFrame, TcpSettings, TransportError

BROADCAST_TURNAROUND_MS = 100.0
"""Pause après une diffusion : les esclaves exécutent l'écriture sans répondre,
le maître leur laisse ce délai avant la requête suivante (norme : 100 à 200 ms)."""


class Link(Protocol):
    settings: LinkSettings

    def send(self, data: bytes) -> RawFrame: ...
    def receive(self, timeout_ms: float) -> RawFrame | None: ...


class Framing(Protocol):
    def encode(self, req: Request) -> bytes: ...
    def decode(self, req: Request, data: bytes) -> tuple[int, ...]: ...


class RtuFraming:
    def encode(self, req: Request) -> bytes:
        return build_adu(req)

    def decode(self, req: Request, data: bytes) -> tuple[int, ...]:
        return parse_response(req, data)


class TcpFraming:
    def __init__(self) -> None:
        self._tid = 0

    def encode(self, req: Request) -> bytes:
        self._tid = (self._tid + 1) & 0xFFFF
        return build_mbap(self._tid, req.slave_id, build_pdu(req))

    def decode(self, req: Request, data: bytes) -> tuple[int, ...]:
        try:
            mbap = parse_mbap(data)
        except ValueError as exc:
            raise BadResponse(f"Enveloppe MBAP invalide : {exc}") from exc
        if mbap.transaction_id != self._tid:
            raise BadResponse(f"Transaction {mbap.transaction_id} au lieu de {self._tid}")
        return parse_response_pdu(req, mbap.unit_id, mbap.pdu)


def framing_for(settings: LinkSettings) -> Framing:
    return TcpFraming() if isinstance(settings, TcpSettings) else RtuFraming()


class ModbusMaster:
    def __init__(self, link: Link, seq_start: int = 0, framing: Framing | None = None) -> None:
        self.link = link
        self.framing = framing or framing_for(link.settings)
        self._seq = seq_start  # dernier numéro attribué ; continu sur la session même après reconnexion

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def settings(self) -> LinkSettings:
        return self.link.settings

    def execute(self, req: Request, timeout_ms: float | None = None) -> ExchangeRecord:
        """Émet la requête, attend la réponse, décode. Ne lève que ``ValueError``
        (requête hors bornes) ; toute autre issue est encodée dans le statut.
        ``timeout_ms`` remplace le délai de la liaison (scan, tests de diagnostic)."""
        adu = self.framing.encode(req)  # ValueError si hors bornes : à la charge de l'appelant
        self._seq += 1
        seq = self._seq
        timestamp = datetime.now()
        settings = self.link.settings

        def record(status: ExchangeStatus, rx: RawFrame | None, rt: float | None, **kw) -> ExchangeRecord:
            return ExchangeRecord(seq, timestamp, req, settings, tx, rx, status, rt, **kw)

        try:
            tx = self.link.send(adu)
        except TransportError as exc:
            now = time.perf_counter_ns()
            tx = RawFrame(Direction.TX, adu, now, now, timestamp)
            return record(ExchangeStatus.TRANSPORT_ERROR, None, None, error_message=str(exc))

        broadcast = req.slave_id == BROADCAST_ID
        timeout = settings.response_timeout_ms if timeout_ms is None else timeout_ms
        if broadcast:
            timeout = min(timeout, BROADCAST_TURNAROUND_MS)
        try:
            rx = self.link.receive(timeout)
        except TransportError as exc:
            return record(ExchangeStatus.TRANSPORT_ERROR, None, None, error_message=str(exc))

        if rx is None and broadcast:
            # Silence attendu : c'est la réussite d'une diffusion, pas un timeout
            return record(ExchangeStatus.OK, None, None, values=(), error_message="Diffusion : aucune réponse attendue")
        if rx is None:
            return record(ExchangeStatus.TIMEOUT, None, None, error_message=f"Timeout ({timeout:g} ms)")

        response_time_ms = (rx.t_first_ns - tx.t_last_ns) / 1_000_000
        try:
            values = self.framing.decode(req, rx.data)
        except CrcError as exc:
            return record(ExchangeStatus.CRC_ERROR, rx, response_time_ms, error_message=str(exc))
        except ModbusException as exc:
            return record(
                ExchangeStatus.MODBUS_EXCEPTION, rx, response_time_ms, exception_code=exc.code, error_message=str(exc)
            )
        except BadResponse as exc:
            return record(ExchangeStatus.BAD_RESPONSE, rx, response_time_ms, error_message=str(exc))
        return record(ExchangeStatus.OK, rx, response_time_ms, values=values)


RtuMaster = ModbusMaster  # compatibilité : ``RtuMaster(link)`` choisit l'enveloppe selon la liaison
