"""Campagne de lectures : ce qu'on répète, à quel rythme, combien de temps.

Une campagne est bornée par une durée et / ou un nombre de lectures ; le
premier atteint arrête la campagne. Les paramètres de liaison peuvent être
surchargés (timeout, vitesse, parité...) pour les tests de diagnostic.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from modbusai.analysis.observations import SOURCE_TEST, Observation, SlaveStats, compute_stats
from modbusai.i18n import tr
from modbusai.modbus.records import FunctionCode, Request
from modbusai.transport.records import LinkSettings, Parity, SerialSettings

DEFAULT_DURATION_S = 120.0  # « le test se fait pendant deux minutes »


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    request: Request
    period_ms: int = 200
    duration_s: float | None = DEFAULT_DURATION_S
    max_count: int | None = None
    timeout_ms: float | None = None
    baudrate: int | None = None
    parity: Parity | None = None
    stopbits: float | None = None
    inter_frame_delay_ms: float | None = None
    label: str = "Campagne"
    source: str = SOURCE_TEST  # SOURCE_DEGRADED pour une phase qui provoque volontairement des défauts
    rotation: tuple[int, ...] = ()  # autres esclaves interrogés à tour de rôle avec celui de la requête

    @property
    def slaves(self) -> tuple[int, ...]:
        return (self.request.slave_id, *(s for s in self.rotation if s != self.request.slave_id))

    def request_at(self, step: int) -> Request:
        """Requête du pas ``step`` : la même, ou l'esclave suivant de la rotation."""
        slaves = self.slaves
        if len(slaves) == 1:
            return self.request
        return replace(self.request, slave_id=slaves[step % len(slaves)])

    @property
    def changes_link(self) -> bool:
        return any(
            v is not None
            for v in (self.timeout_ms, self.baudrate, self.parity, self.stopbits, self.inter_frame_delay_ms)
        )

    def apply(self, settings: LinkSettings) -> LinkSettings:
        """Paramètres de liaison pour la campagne. En TCP seul le timeout s'applique."""
        changes: dict = {}
        if self.timeout_ms is not None:
            changes["response_timeout_ms"] = self.timeout_ms
        if isinstance(settings, SerialSettings):
            if self.baudrate is not None:
                changes["baudrate"] = self.baudrate
            if self.parity is not None:
                changes["parity"] = self.parity
            if self.stopbits is not None:
                changes["stopbits"] = self.stopbits
            if self.inter_frame_delay_ms is not None:
                changes["inter_frame_delay_ms"] = self.inter_frame_delay_ms
        return replace(settings, **changes) if changes else settings

    def is_done(self, count: int, elapsed_s: float) -> bool:
        if self.max_count is not None and count >= self.max_count:
            return True
        return self.duration_s is not None and elapsed_s >= self.duration_s

    def expected_count(self) -> int | None:
        """Estimation du nombre de lectures (pour la barre de progression)."""
        if self.max_count is not None:
            return self.max_count
        if self.duration_s is not None and self.period_ms > 0:
            return max(1, int(self.duration_s * 1000 / self.period_ms))
        return None

    def describe(self) -> str:
        parts = [
            f"{self.label}",
            f"esclave {self.request.slave_id}"
            if len(self.slaves) == 1
            else tr("esclaves {p0}").format(p0=", ".join(str(s) for s in self.slaves)),
            f"FC{int(self.request.function):02d} @{self.request.address} x{self.request.count}",
        ]
        parts.append(tr("période {p0} ms").format(p0=self.period_ms))
        if self.duration_s is not None:
            parts.append(f"{self.duration_s:.0f} s")
        if self.max_count is not None:
            parts.append(tr("max {p0} lectures").format(p0=self.max_count))
        if self.timeout_ms is not None:
            parts.append(tr("timeout {p0:.0f} ms").format(p0=self.timeout_ms))
        if self.baudrate is not None:
            parts.append(tr("{p0} bauds").format(p0=self.baudrate))
        if self.parity is not None:
            parts.append(tr("parité {p0}").format(p0=self.parity.name.lower()))
        if self.stopbits is not None:
            parts.append(tr("{p0:g} stop").format(p0=self.stopbits))
        if self.inter_frame_delay_ms is not None:
            parts.append(tr("silence {p0:g} ms").format(p0=self.inter_frame_delay_ms))
        return ", ".join(parts)


def probe_request(
    slave_id: int, function: FunctionCode = FunctionCode.READ_HOLDING_REGISTERS, address: int = 0, count: int = 1
) -> Request:
    return Request(slave_id, function, address, count)


def campaign_stats(spec: CampaignSpec, observations: Iterable[Observation]) -> SlaveStats:
    """Bilan d'une campagne. Avec une rotation, les esclaves interrogés sont
    comptés ensemble : c'est le bus qui est jugé, pas un équipement."""
    slave_id = spec.request.slave_id
    obs = list(observations)
    if len(spec.slaves) > 1:
        obs = [replace(o, slave_id=slave_id) for o in obs]
    return compute_stats(obs).get(slave_id) or SlaveStats(slave_id)
