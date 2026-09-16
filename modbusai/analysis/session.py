"""Historique de session : toutes les observations, quelle que soit leur source."""

from __future__ import annotations

from collections.abc import Iterable

from modbusai.analysis.observations import Observation, SlaveStats, compute_stats
from modbusai.analysis.sniffer import Transaction
from modbusai.modbus.records import ExchangeRecord
from modbusai.transport.records import SerialSettings


class SessionStore:
    def __init__(self) -> None:
        self._observations: list[Observation] = []

    def __len__(self) -> int:
        return len(self._observations)

    def add_record(self, rec: ExchangeRecord, source: str = "maitre") -> Observation:
        obs = Observation.from_record(rec, source)
        self._observations.append(obs)
        return obs

    def add_transaction(self, tr: Transaction, settings: SerialSettings | None) -> Observation:
        resp = tr.response
        obs = Observation(
            timestamp=tr.timestamp,
            slave_id=tr.slave_id,
            function=tr.function,
            status=tr.status,
            response_time_ms=tr.response_time_ms,
            source="espion",
            exception_code=tr.exception_code,
            error=None if resp is None else resp.detail,
            rx_chunks=len(resp.frame.chunks) if resp is not None else 0,
            rx_length=len(resp.frame) if resp is not None else 0,
            settings=settings,
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
