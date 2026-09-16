"""Scan d'adresses et d'équipements : plan, classification des réponses, variantes de liaison."""

from __future__ import annotations

import enum
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from modbusai.analysis.identification import DeviceIdentity
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import LinkSettings, Parity, SerialSettings

COMMON_BAUDRATES = (9600, 19200, 38400, 115200, 4800)
COMMON_FRAMINGS = ((Parity.NONE, 1.0), (Parity.EVEN, 1.0), (Parity.NONE, 2.0), (Parity.ODD, 1.0))


class ScanStatus(enum.Enum):
    PRESENT = "présent"  # réponse valide
    PRESENT_EXCEPTION = "présent (exception)"  # répond, mais registre/fonction refusé : l'équipement existe
    NOISY = "réponse corrompue"  # quelque chose répond, CRC faux : vitesse/parité ou ligne
    CONFLICT = "réponse incohérente"  # CRC juste mais mauvais esclave/FC : conflit d'adresse ou écho
    ABSENT = "absent"
    ERROR = "erreur liaison"


@dataclass(frozen=True, slots=True)
class ScanPlan:
    first_slave: int = 1
    last_slave: int = 247
    function: FunctionCode = FunctionCode.READ_HOLDING_REGISTERS
    address: int = 0
    count: int = 1
    timeout_ms: float = 200.0
    retries: int = 1  # essais supplémentaires avant de déclarer absent
    identify: bool = True  # FC43 puis FC17 sur les esclaves présents
    sweep_settings: bool = False  # balayer vitesses / parités courantes (série uniquement)
    base_settings: LinkSettings | None = None

    @property
    def slaves(self) -> range:
        return range(self.first_slave, self.last_slave + 1)

    def probe_request(self, slave_id: int) -> Request:
        return Request(slave_id, self.function, self.address, self.count)

    def settings_variants(self) -> list[LinkSettings]:
        """Jeux de paramètres à essayer : le courant, puis les combinaisons usuelles
        (série uniquement : en TCP il n'y a ni vitesse ni parité)."""
        base = self.base_settings
        if base is None:
            return []
        if not self.sweep_settings or not isinstance(base, SerialSettings):
            return [base]
        variants = [base]
        for baud in COMMON_BAUDRATES:
            for parity, stop in COMMON_FRAMINGS:
                v = replace(base, baudrate=baud, parity=parity, stopbits=stop, bytesize=8)
                if v not in variants:
                    variants.append(v)
        return variants

    @property
    def total_probes(self) -> int:
        return len(self.settings_variants()) * len(self.slaves)


@dataclass(slots=True)
class ScanResult:
    slave_id: int
    settings: LinkSettings
    status: ScanStatus
    response_time_ms: float | None = None
    detail: str = ""
    identity: DeviceIdentity | None = None
    report_id: str = ""
    attempts: int = 1
    records: list[ExchangeRecord] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return self.status in (ScanStatus.PRESENT, ScanStatus.PRESENT_EXCEPTION)

    @property
    def identity_text(self) -> str:
        parts = []
        if self.identity is not None and self.identity.summary() != "-":
            parts.append(self.identity.summary())
        if self.report_id and self.report_id != "-":
            parts.append(self.report_id)
        return " | ".join(parts) if parts else "-"


def classify(record: ExchangeRecord) -> tuple[ScanStatus, str]:
    st = record.status
    if st is ExchangeStatus.OK:
        return ScanStatus.PRESENT, f"répond en {record.response_time_ms:.1f} ms"
    if st is ExchangeStatus.MODBUS_EXCEPTION:
        return ScanStatus.PRESENT_EXCEPTION, record.error_message or "exception"
    if st is ExchangeStatus.CRC_ERROR:
        return ScanStatus.NOISY, record.error_message or "CRC invalide"
    if st is ExchangeStatus.BAD_RESPONSE:
        if record.rx_frame is not None and record.rx_frame.data == record.tx_frame.data:
            return ScanStatus.CONFLICT, "écho de la requête (adaptateur sans direction automatique ?)"
        return ScanStatus.CONFLICT, record.error_message or "réponse incohérente"
    if st is ExchangeStatus.TRANSPORT_ERROR:
        return ScanStatus.ERROR, record.error_message or "erreur liaison"
    return ScanStatus.ABSENT, "aucune réponse"


def merge_attempts(records: list[ExchangeRecord]) -> tuple[ScanStatus, str]:
    """Verdict sur plusieurs essais : le meilleur statut l'emporte, un timeout
    isolé ne masque pas une réponse."""
    order = [
        ScanStatus.PRESENT,
        ScanStatus.PRESENT_EXCEPTION,
        ScanStatus.CONFLICT,
        ScanStatus.NOISY,
        ScanStatus.ERROR,
        ScanStatus.ABSENT,
    ]
    best: tuple[ScanStatus, str] | None = None
    for rec in records:
        c = classify(rec)
        if best is None or order.index(c[0]) < order.index(best[0]):
            best = c
    return best if best is not None else (ScanStatus.ABSENT, "aucune réponse")


def identification_requests(slave_id: int) -> Iterator[Request]:
    yield Request(slave_id, FunctionCode.READ_DEVICE_ID, 1, 0)
    yield Request(slave_id, FunctionCode.REPORT_SLAVE_ID, 0)
