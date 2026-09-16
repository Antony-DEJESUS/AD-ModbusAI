"""Observations unifiées (maître, espion, scan, tests) et statistiques par esclave."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from modbusai.modbus.records import ExchangeRecord, ExchangeStatus
from modbusai.transport.records import LinkSettings


@dataclass(frozen=True, slots=True)
class Observation:
    """Un échange vu depuis n'importe quelle source, réduit à ce que la
    statistique et le diagnostic exploitent."""

    timestamp: datetime
    slave_id: int
    function: int
    status: ExchangeStatus
    response_time_ms: float | None
    source: str  # "maitre", "espion", "scan", "test"
    exception_code: int | None = None
    error: str | None = None
    rx_chunks: int = 0  # nombre de blocs USB ayant composé la réponse
    rx_length: int = 0
    tx_to_rx_echo: bool = False  # la réponse est l'écho exact de la requête (adaptateur)
    settings: LinkSettings | None = None

    @classmethod
    def from_record(cls, rec: ExchangeRecord, source: str = "maitre") -> Observation:
        echo = rec.rx_frame is not None and rec.rx_frame.data == rec.tx_frame.data
        return cls(
            timestamp=rec.timestamp,
            slave_id=rec.slave_id,
            function=int(rec.function),
            status=rec.status,
            response_time_ms=rec.response_time_ms,
            source=source,
            exception_code=rec.exception_code,
            error=rec.error_message,
            rx_chunks=len(rec.rx_frame.chunks) if rec.rx_frame is not None else 0,
            rx_length=len(rec.rx_frame) if rec.rx_frame is not None else 0,
            tx_to_rx_echo=echo,
            settings=rec.settings,
        )


@dataclass(slots=True)
class SlaveStats:
    slave_id: int
    total: int = 0
    ok: int = 0
    timeout: int = 0
    crc_error: int = 0
    exception: int = 0
    bad_response: int = 0
    transport_error: int = 0
    echo: int = 0
    exceptions_by_code: Counter = field(default_factory=Counter)
    functions: Counter = field(default_factory=Counter)
    response_times: list[float] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    sources: Counter = field(default_factory=Counter)

    # ------------------------------------------------------------- ratios
    @property
    def ok_ratio(self) -> float:
        return self.ok / self.total if self.total else 0.0

    @property
    def timeout_ratio(self) -> float:
        return self.timeout / self.total if self.total else 0.0

    @property
    def crc_ratio(self) -> float:
        return self.crc_error / self.total if self.total else 0.0

    @property
    def exception_ratio(self) -> float:
        return self.exception / self.total if self.total else 0.0

    @property
    def error_ratio(self) -> float:
        """Tout ce qui n'est ni OK ni exception Modbus (une exception est une réponse valide)."""
        return (
            (self.timeout + self.crc_error + self.bad_response + self.transport_error) / self.total
            if self.total
            else 0.0
        )

    @property
    def answered(self) -> int:
        """Réponses reçues et exploitables (OK ou exception) : l'esclave existe."""
        return self.ok + self.exception

    # -------------------------------------------------------------- temps
    @property
    def rt_min(self) -> float | None:
        return min(self.response_times) if self.response_times else None

    @property
    def rt_max(self) -> float | None:
        return max(self.response_times) if self.response_times else None

    @property
    def rt_avg(self) -> float | None:
        return statistics.fmean(self.response_times) if self.response_times else None

    @property
    def rt_p95(self) -> float | None:
        if not self.response_times:
            return None
        ordered = sorted(self.response_times)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    @property
    def rt_jitter(self) -> float | None:
        """Écart-type des temps de réponse (ms)."""
        return statistics.pstdev(self.response_times) if len(self.response_times) >= 2 else None


def compute_stats(observations: Iterable[Observation]) -> dict[int, SlaveStats]:
    stats: dict[int, SlaveStats] = {}
    for obs in observations:
        st = stats.setdefault(obs.slave_id, SlaveStats(obs.slave_id))
        st.total += 1
        st.functions[obs.function] += 1
        st.sources[obs.source] += 1
        if st.first_seen is None or obs.timestamp < st.first_seen:
            st.first_seen = obs.timestamp
        if st.last_seen is None or obs.timestamp > st.last_seen:
            st.last_seen = obs.timestamp
        if obs.status is ExchangeStatus.OK:
            st.ok += 1
        elif obs.status is ExchangeStatus.TIMEOUT:
            st.timeout += 1
        elif obs.status is ExchangeStatus.CRC_ERROR:
            st.crc_error += 1
        elif obs.status is ExchangeStatus.MODBUS_EXCEPTION:
            st.exception += 1
            if obs.exception_code is not None:
                st.exceptions_by_code[obs.exception_code] += 1
        elif obs.status is ExchangeStatus.BAD_RESPONSE:
            st.bad_response += 1
        elif obs.status is ExchangeStatus.TRANSPORT_ERROR:
            st.transport_error += 1
        if obs.tx_to_rx_echo:
            st.echo += 1
        if obs.response_time_ms is not None and obs.status in (ExchangeStatus.OK, ExchangeStatus.MODBUS_EXCEPTION):
            st.response_times.append(obs.response_time_ms)
    return stats
