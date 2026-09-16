"""Serveur esclave RTU : table de données et traitement d'une requête.

Pur : ``SlaveHandler.handle(adu)`` prend une trame reçue et renvoie la trame à
émettre (ou None s'il ne faut pas répondre). Le thread qui lit le port et
émet est dans ``ui/slave_worker.py``.
"""

from __future__ import annotations

import enum
import random
import threading
from dataclasses import dataclass, field

from modbusai.modbus.crc import append_crc, check_crc
from modbusai.modbus.records import FunctionCode

TABLE_SIZE = 65536


class Table(enum.Enum):
    COILS = ("Bobines (0xxxx)", "0", True)
    DISCRETE_INPUTS = ("Entrées TOR (1xxxx)", "1", True)
    INPUT_REGISTERS = ("Registres d'entrée (3xxxx)", "3", False)
    HOLDING_REGISTERS = ("Registres de maintien (4xxxx)", "4", False)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def prefix(self) -> str:
        return self.value[1]

    @property
    def is_bits(self) -> bool:
        return self.value[2]


class DataStore:
    """Quatre tables de 65536 valeurs, partagées entre le thread série et l'interface."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tables: dict[Table, list[int]] = {t: [0] * TABLE_SIZE for t in Table}
        self.version = 0  # incrémenté à chaque écriture, pour rafraîchir la vue

    def get(self, table: Table, address: int, count: int = 1) -> list[int]:
        with self._lock:
            return self._tables[table][address : address + count]

    def set(self, table: Table, address: int, values: list[int] | tuple[int, ...]) -> None:
        mask = 1 if table.is_bits else 0xFFFF
        with self._lock:
            tbl = self._tables[table]
            for i, v in enumerate(values):
                tbl[address + i] = int(v) & mask
            self.version += 1

    def fill(self, table: Table, value: int, start: int = 0, count: int = TABLE_SIZE) -> None:
        self.set(table, start, [value] * count)

    def increment(self, table: Table, start: int, count: int, step: int = 1) -> None:
        """Animation : incrémente une plage (modulo 65536, ou bascule pour les bits)."""
        with self._lock:
            tbl = self._tables[table]
            for i in range(start, min(start + count, TABLE_SIZE)):
                tbl[i] = (tbl[i] ^ 1) if table.is_bits else (tbl[i] + step) & 0xFFFF
            self.version += 1

    def clear(self) -> None:
        with self._lock:
            for t in Table:
                self._tables[t] = [0] * TABLE_SIZE
            self.version += 1


@dataclass(slots=True)
class SlaveConfig:
    slave_ids: set[int] = field(default_factory=lambda: {1})
    response_delay_ms: float = 0.0  # simule un esclave lent
    drop_ratio: float = 0.0  # 0..1 : part des requêtes volontairement ignorées
    corrupt_ratio: float = 0.0  # 0..1 : part des réponses au CRC volontairement faux
    read_only: bool = False  # refuse les écritures (exception 04 : défaut esclave)
    limits: dict[Table, int] = field(default_factory=lambda: {t: TABLE_SIZE for t in Table})
    vendor: str = "ModbusAI"
    product: str = "Serveur esclave RTU"
    revision: str = "0.2.0"


@dataclass(slots=True)
class SlaveCounters:
    requests: int = 0
    responses: int = 0
    exceptions: int = 0
    ignored: int = 0  # autres adresses, trames invalides
    dropped: int = 0
    corrupted: int = 0
    writes: int = 0


@dataclass(frozen=True, slots=True)
class HandledRequest:
    """Ce que le serveur a fait d'une trame reçue (pour le journal)."""

    request: bytes
    response: bytes | None
    slave_id: int | None
    function: int | None
    kind: str  # "réponse", "exception", "ignorée", "perdue", "broadcast", "corrompue", "invalide"
    detail: str = ""


class SlaveHandler:
    _READ_TABLE = {
        FunctionCode.READ_COILS: Table.COILS,
        FunctionCode.READ_DISCRETE_INPUTS: Table.DISCRETE_INPUTS,
        FunctionCode.READ_HOLDING_REGISTERS: Table.HOLDING_REGISTERS,
        FunctionCode.READ_INPUT_REGISTERS: Table.INPUT_REGISTERS,
    }

    def __init__(self, store: DataStore, config: SlaveConfig, rng: random.Random | None = None) -> None:
        self.store = store
        self.config = config
        self.counters = SlaveCounters()
        self._rng = rng or random.Random()

    # ---------------------------------------------------------------- API
    def handle(self, adu: bytes) -> HandledRequest:
        """Trame RTU complète (esclave + PDU + CRC) -> réponse RTU ou None."""
        c = self.counters
        if len(adu) < 4 or not check_crc(adu):
            c.ignored += 1
            return HandledRequest(adu, None, None, None, "invalide", "CRC invalide ou trame trop courte")
        slave = adu[0]
        result = self.handle_pdu(slave, adu[1:-2])
        resp = None
        if result.response is not None:
            resp = append_crc(bytes([slave]) + result.response)
            if result.kind == "corrompue":
                resp = resp[:-1] + bytes([resp[-1] ^ 0xFF])
        return HandledRequest(adu, resp, result.slave_id, result.function, result.kind, result.detail)

    def handle_pdu(self, slave: int, pdu: bytes) -> HandledRequest:
        """Cœur commun RTU / TCP : PDU de requête -> PDU de réponse (sans enveloppe).
        Pour ``kind == "corrompue"``, c'est l'enveloppe qui applique l'altération."""
        c = self.counters
        if not pdu:
            c.ignored += 1
            return HandledRequest(pdu, None, slave, None, "invalide", "PDU vide")
        fc = pdu[0]
        body = pdu[1:]
        broadcast = slave == 0
        if not broadcast and slave not in self.config.slave_ids:
            c.ignored += 1
            return HandledRequest(pdu, None, slave, fc, "ignorée", "adresse non servie")
        try:
            function = FunctionCode(fc)
        except ValueError:
            c.requests += 1
            return self._exception(pdu, slave, fc, 0x01)
        c.requests += 1
        try:
            resp = self._process(function, body)
        except _Exc as exc:
            return self._exception(pdu, slave, fc, exc.code)
        if resp is None:
            return HandledRequest(pdu, None, slave, fc, "ignorée", "requête mal formée")
        if broadcast:
            return HandledRequest(pdu, None, 0, fc, "broadcast", "écriture diffusée, sans réponse")
        if self.config.drop_ratio > 0 and self._rng.random() < self.config.drop_ratio:
            c.dropped += 1
            return HandledRequest(pdu, None, slave, fc, "perdue", "réponse volontairement non émise")
        if self.config.corrupt_ratio > 0 and self._rng.random() < self.config.corrupt_ratio:
            c.corrupted += 1
            return HandledRequest(pdu, resp, slave, fc, "corrompue", "CRC volontairement faux")
        c.responses += 1
        return HandledRequest(pdu, resp, slave, fc, "réponse")

    # ------------------------------------------------------------ interne
    def _exception(self, pdu: bytes, slave: int, fc: int, code: int) -> HandledRequest:
        self.counters.exceptions += 1
        if slave == 0:
            return HandledRequest(pdu, None, 0, fc, "broadcast", f"exception {code:02X} non émise (diffusion)")
        return HandledRequest(pdu, bytes([fc | 0x80, code]), slave, fc, "exception", f"exception {code:02X}")

    def _check_range(self, table: Table, address: int, count: int) -> None:
        if count < 1 or address + count > self.config.limits.get(table, TABLE_SIZE):
            raise _Exc(0x02)

    def _process(self, fc: FunctionCode, body: bytes) -> bytes | None:
        if fc in self._READ_TABLE:
            if len(body) != 4:
                return None
            addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            table = self._READ_TABLE[fc]
            if table.is_bits:
                if not 1 <= count <= 2000:
                    raise _Exc(0x03)
                self._check_range(table, addr, count)
                bits = self.store.get(table, addr, count)
                out = bytearray((count + 7) // 8)
                for i, b in enumerate(bits):
                    if b:
                        out[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(out)]) + bytes(out)
            if not 1 <= count <= 125:
                raise _Exc(0x03)
            self._check_range(table, addr, count)
            regs = self.store.get(table, addr, count)
            return bytes([fc, 2 * count]) + b"".join(r.to_bytes(2, "big") for r in regs)

        if fc is FunctionCode.WRITE_SINGLE_COIL:
            if len(body) != 4:
                return None
            addr, value = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            if value not in (0x0000, 0xFF00):
                raise _Exc(0x03)
            self._write(Table.COILS, addr, [1 if value else 0])
            return bytes([fc]) + body

        if fc is FunctionCode.WRITE_SINGLE_REGISTER:
            if len(body) != 4:
                return None
            addr, value = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
            self._write(Table.HOLDING_REGISTERS, addr, [value])
            return bytes([fc]) + body

        if fc is FunctionCode.WRITE_MULTIPLE_COILS:
            if len(body) < 5:
                return None
            addr, count, nbytes = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big"), body[4]
            if not 1 <= count <= 1968 or nbytes != (count + 7) // 8 or len(body) != 5 + nbytes:
                raise _Exc(0x03)
            data = body[5:]
            self._write(Table.COILS, addr, [(data[i // 8] >> (i % 8)) & 1 for i in range(count)])
            return bytes([fc]) + body[0:4]

        if fc is FunctionCode.WRITE_MULTIPLE_REGISTERS:
            if len(body) < 5:
                return None
            addr, count, nbytes = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big"), body[4]
            if not 1 <= count <= 123 or nbytes != 2 * count or len(body) != 5 + nbytes:
                raise _Exc(0x03)
            data = body[5:]
            self._write(
                Table.HOLDING_REGISTERS, addr, [int.from_bytes(data[2 * i : 2 * i + 2], "big") for i in range(count)]
            )
            return bytes([fc]) + body[0:4]

        if fc is FunctionCode.REPORT_SLAVE_ID:
            ident = self.config.product.encode("ascii", errors="replace")
            payload = bytes([0x01, 0xFF]) + ident
            return bytes([fc, len(payload)]) + payload

        if fc is FunctionCode.READ_DEVICE_ID:
            if len(body) != 3 or body[0] != 0x0E:
                raise _Exc(0x01)
            objects = [(0x00, self.config.vendor), (0x01, self.config.product), (0x02, self.config.revision)]
            enc = b"".join(bytes([oid, len(v.encode())]) + v.encode("ascii", errors="replace") for oid, v in objects)
            return bytes([fc, 0x0E, 0x01, 0x01, 0x00, 0x00, len(objects)]) + enc

        raise _Exc(0x01)

    def _write(self, table: Table, address: int, values: list[int]) -> None:
        self._check_range(table, address, len(values))
        if self.config.read_only:
            raise _Exc(0x04)
        self.store.set(table, address, values)
        self.counters.writes += 1


class _Exc(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code
