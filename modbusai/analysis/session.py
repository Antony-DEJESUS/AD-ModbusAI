"""Historique de session : toutes les observations, quelle que soit leur source."""

from __future__ import annotations

from collections.abc import Iterable

from modbusai.analysis.observations import Observation, SlaveStats, compute_stats
from modbusai.analysis.sniffer import Transaction
from modbusai.modbus.records import ExchangeRecord
from modbusai.transport.records import LinkSettings


class SessionStore:
    def __init__(self) -> None:
        self._observations: list[Observation] = []

    def __len__(self) -> int:
        return len(self._observations)

    def add_record(self, rec: ExchangeRecord, source: str = "maitre", label: str = "") -> Observation:
        obs = Observation.from_record(rec, source, label)
        self._observations.append(obs)
        return obs

    def add_transaction(self, transaction: Transaction, settings: LinkSettings | None) -> Observation:
        resp = transaction.response
        obs = Observation(
            timestamp=transaction.timestamp,
            slave_id=transaction.slave_id,
            function=transaction.function,
            status=transaction.status,
            response_time_ms=transaction.response_time_ms,
            source="espion",
            exception_code=transaction.exception_code,
            error=None if resp is None else resp.detail,
            rx_chunks=len(resp.frame.chunks) if resp is not None else 0,
            rx_length=len(resp.frame) if resp is not None else 0,
            settings=settings,
            tx_hex=transaction.request.frame.hex,
            rx_hex="" if resp is None else resp.frame.hex,
        )
        self._observations.append(obs)
        return obs

    def observations(self, sources: Iterable[str] | None = None) -> list[Observation]:
        if sources is None:
            return list(self._observations)
        wanted = set(sources)
        return [o for o in self._observations if o.source in wanted]

    def stats(self, sources: Iterable[str] | None = None) -> dict[int, SlaveStats]:
        return compute_stats(self.observations(sources))

    def clear(self) -> None:
        self._observations.clear()
