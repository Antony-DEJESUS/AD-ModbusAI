"""Décodage passif : classer les trames vues sur le bus et les apparier en transactions.

Sur un bus RS-485 deux fils, l'écoute voit passer requêtes et réponses sans
savoir qui parle. On s'appuie sur la grammaire des trames (longueurs, codes
fonction) et sur l'état « une requête attend sa réponse » pour lever les
ambiguïtés (une requête de lecture et une réponse de 3 octets de données font
toutes deux 8 octets ; un acquittement d'écriture est l'écho de la requête).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime

from modbusai.modbus.crc import check_crc
from modbusai.modbus.exceptions import exception_label
from modbusai.modbus.records import ExchangeStatus, FunctionCode
from modbusai.transport.records import Direction, RawFrame

_READ_FCS = {0x01, 0x02, 0x03, 0x04}
_WRITE_SINGLE_FCS = {0x05, 0x06}
_WRITE_MULTI_FCS = {0x0F, 0x10}
_KNOWN_FCS = _READ_FCS | _WRITE_SINGLE_FCS | _WRITE_MULTI_FCS | {0x11, 0x2B}
MIN_FRAME_LENGTH = 4  # esclave + FC + CRC


class FrameKind(enum.Enum):
    REQUEST = "requête"
    RESPONSE = "réponse"
    EXCEPTION = "exception"
    BROADCAST = "diffusion"
    INVALID = "CRC invalide"  # bruit, collision, fragment
    UNKNOWN = "inconnue"  # CRC juste mais grammaire non reconnue


@dataclass(frozen=True, slots=True)
class SniffedFrame:
    frame: RawFrame
    kind: FrameKind
    slave_id: int | None = None
    function: int | None = None
    address: int | None = None
    count: int | None = None
    detail: str = ""

    @property
    def wall_time(self) -> datetime:
        return self.frame.wall_time


@dataclass(slots=True)
class Transaction:
    request: SniffedFrame
    response: SniffedFrame | None = None
    status: ExchangeStatus = ExchangeStatus.TIMEOUT
    response_time_ms: float | None = None
    exception_code: int | None = None

    @property
    def slave_id(self) -> int:
        return self.request.slave_id or 0

    @property
    def function(self) -> int:
        return self.request.function or 0

    @property
    def timestamp(self) -> datetime:
        return self.request.wall_time


@dataclass(slots=True)
class BusCounters:
    frames: int = 0
    invalid: int = 0
    unknown: int = 0
    requests: int = 0
    responses: int = 0
    exceptions: int = 0
    broadcasts: int = 0
    bytes_total: int = 0
    slaves_seen: set[int] = field(default_factory=set)


# ------------------------------------------------------------ grammaire
def _as_request(data: bytes) -> SniffedFrame | None:
    """Tente d'interpréter ``data`` (CRC déjà vérifié) comme une requête."""
    slave, fc = data[0], data[1]
    body = data[2:-2]
    if fc in _READ_FCS and len(body) == 4:
        addr, count = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
        limit = 2000 if fc in (1, 2) else 125
        if 1 <= count <= limit:
            return SniffedFrame(_raw(data), FrameKind.REQUEST, slave, fc, addr, count, f"lecture {count} @ {addr}")
    if fc in _WRITE_SINGLE_FCS and len(body) == 4:
        addr, value = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big")
        if fc == 0x05 and value not in (0x0000, 0xFF00):
            return None
        return SniffedFrame(_raw(data), FrameKind.REQUEST, slave, fc, addr, 1, f"écriture 0x{value:04X} @ {addr}")
    if fc in _WRITE_MULTI_FCS and len(body) >= 6:
        addr, count, nbytes = int.from_bytes(body[0:2], "big"), int.from_bytes(body[2:4], "big"), body[4]
        expected = (count + 7) // 8 if fc == 0x0F else 2 * count
        if nbytes == expected and len(body) == 5 + nbytes and count >= 1:
            return SniffedFrame(_raw(data), FrameKind.REQUEST, slave, fc, addr, count, f"écriture {count} @ {addr}")
    if fc == 0x11 and len(body) == 0:
        return SniffedFrame(_raw(data), FrameKind.REQUEST, slave, fc, None, None, "identification FC17")
    if fc == 0x2B and len(body) == 3 and body[0] == 0x0E:
        return SniffedFrame(_raw(data), FrameKind.REQUEST, slave, fc, body[1], body[2], "identification FC43")
    return None


def _as_response(data: bytes, expected_fc: int | None = None) -> SniffedFrame | None:
    """Tente d'interpréter ``data`` comme une réponse (normale ou exception)."""
    slave, fc = data[0], data[1]
    body = data[2:-2]
    if fc & 0x80 and len(body) == 1:
        code = body[0]
        return SniffedFrame(
            _raw(data),
            FrameKind.EXCEPTION,
            slave,
            fc & 0x7F,
            None,
            None,
            f"exception {code:02X} : {exception_label(code)}",
        )
    if expected_fc is not None and fc != expected_fc:
        return None
    if fc in _READ_FCS and len(body) >= 2 and body[0] == len(body) - 1:
        return SniffedFrame(_raw(data), FrameKind.RESPONSE, slave, fc, None, None, f"{body[0]} octets de données")
    if fc in _WRITE_SINGLE_FCS | _WRITE_MULTI_FCS and len(body) == 4:
        addr = int.from_bytes(body[0:2], "big")
        return SniffedFrame(_raw(data), FrameKind.RESPONSE, slave, fc, addr, None, "acquittement d'écriture")
    if fc == 0x11 and len(body) >= 2 and body[0] == len(body) - 1:
        return SniffedFrame(_raw(data), FrameKind.RESPONSE, slave, fc, None, None, "identification FC17")
    if fc == 0x2B and len(body) >= 6 and body[0] == 0x0E:
        return SniffedFrame(_raw(data), FrameKind.RESPONSE, slave, fc, None, None, "identification FC43")
    return None


_raw_cache: RawFrame | None = None


def _raw(data: bytes) -> RawFrame:
    """Les fonctions de grammaire travaillent sur des octets ; la RawFrame réelle
    est réattachée par le décodeur (voir ``_attach``)."""
    return (
        _raw_cache
        if _raw_cache is not None and _raw_cache.data == data
        else RawFrame(Direction.RX, data, 0, 0, datetime.now())
    )


def _attach(sf: SniffedFrame, frame: RawFrame) -> SniffedFrame:
    return SniffedFrame(frame, sf.kind, sf.slave_id, sf.function, sf.address, sf.count, sf.detail)


def split_merged(frame: RawFrame) -> list[RawFrame]:
    """Une réponse rapide peut arriver collée à sa requête dans le même bloc
    USB. Si le CRC global est faux, on cherche un préfixe à CRC valide et
    grammaire connue, et on découpe récursivement."""
    data = frame.data
    if len(data) < 2 * MIN_FRAME_LENGTH or check_crc(data):
        return [frame]
    for cut in range(MIN_FRAME_LENGTH, len(data) - MIN_FRAME_LENGTH + 1):
        head = data[:cut]
        if not check_crc(head):
            continue
        if _as_request(head) is None and _as_response(head) is None:
            continue
        rest = data[cut:]
        # Horodatage approché : la coupure est placée au prorata des octets
        t_cut = frame.t_first_ns + (frame.t_last_ns - frame.t_first_ns) * cut // len(data)
        first = RawFrame(
            frame.direction, head, frame.t_first_ns, t_cut, frame.wall_time, frame.chunks, frame.silence_before_ns
        )
        second = RawFrame(frame.direction, rest, t_cut, frame.t_last_ns, frame.wall_time, (), 0)
        return [first, *split_merged(second)]
    return [frame]


# ------------------------------------------------------------- décodeur
class PassiveDecoder:
    """Classe les trames et les apparie en transactions.

    ``feed(frame)`` renvoie les trames classées ; les transactions complètes
    (ou en timeout) sont accumulées dans ``completed`` et récupérées par
    ``pop_completed()``.
    """

    def __init__(self, response_timeout_ms: float = 1000.0) -> None:
        self.response_timeout_ns = int(response_timeout_ms * 1_000_000)
        self.counters = BusCounters()
        self._pending: Transaction | None = None
        self._completed: list[Transaction] = []

    @property
    def pending(self) -> Transaction | None:
        return self._pending

    def pop_completed(self) -> list[Transaction]:
        out, self._completed = self._completed, []
        return out

    def feed(self, frame: RawFrame) -> list[SniffedFrame]:
        out: list[SniffedFrame] = []
        for part in split_merged(frame):
            out.append(self._classify(part))
        return out

    def flush(self, now_ns: int) -> None:
        """Clôt la transaction en attente si le délai de réponse est dépassé."""
        p = self._pending
        if p is not None and now_ns - p.request.frame.t_last_ns > self.response_timeout_ns:
            self._complete(p, None)

    # ----------------------------------------------------------- interne
    def _classify(self, frame: RawFrame) -> SniffedFrame:
        global _raw_cache
        _raw_cache = frame
        c = self.counters
        c.frames += 1
        c.bytes_total += len(frame.data)
        data = frame.data
        if len(data) < MIN_FRAME_LENGTH or not check_crc(data):
            c.invalid += 1
            sf = SniffedFrame(frame, FrameKind.INVALID, detail=f"{len(data)} octets, CRC invalide")
            # Une trame invalide pendant l'attente d'une réponse compte comme réponse corrompue
            p = self._pending
            if p is not None and frame.t_first_ns - p.request.frame.t_last_ns <= self.response_timeout_ns:
                self._complete(p, sf)
            return sf

        p = self._pending
        # 1. Réponse attendue ?
        if p is not None and data[0] == p.request.slave_id:
            resp = _as_response(data, p.request.function)
            if resp is not None:
                resp = _attach(resp, frame)
                self._complete(p, resp)
                return resp
        # 2. Requête ?
        req = _as_request(data)
        if req is not None:
            req = _attach(req, frame)
            if p is not None:
                self._complete(p, None)  # la précédente n'a pas eu de réponse
            if req.slave_id == 0:
                c.broadcasts += 1
                return SniffedFrame(frame, FrameKind.BROADCAST, 0, req.function, req.address, req.count, req.detail)
            c.requests += 1
            c.slaves_seen.add(req.slave_id or 0)
            self._pending = Transaction(req)
            return req
        # 3. Réponse orpheline (requête manquée : début d'écoute, collision)
        resp = _as_response(data)
        if resp is not None:
            resp = _attach(resp, frame)
            c.responses += 1
            c.slaves_seen.add(resp.slave_id or 0)
            return SniffedFrame(
                frame,
                resp.kind,
                resp.slave_id,
                resp.function,
                resp.address,
                resp.count,
                resp.detail + " (sans requête vue)",
            )
        c.unknown += 1
        return SniffedFrame(frame, FrameKind.UNKNOWN, data[0], data[1], detail="grammaire non reconnue")

    def _complete(self, tr: Transaction, resp: SniffedFrame | None) -> None:
        tr.response = resp
        if resp is None:
            tr.status = ExchangeStatus.TIMEOUT
        elif resp.kind is FrameKind.INVALID:
            tr.status = ExchangeStatus.CRC_ERROR
            tr.response_time_ms = (resp.frame.t_first_ns - tr.request.frame.t_last_ns) / 1_000_000
        else:
            tr.response_time_ms = (resp.frame.t_first_ns - tr.request.frame.t_last_ns) / 1_000_000
            self.counters.responses += 1
            if resp.kind is FrameKind.EXCEPTION:
                tr.status = ExchangeStatus.MODBUS_EXCEPTION
                tr.exception_code = resp.frame.data[2]
                self.counters.exceptions += 1
            else:
                tr.status = ExchangeStatus.OK
        self._completed.append(tr)
        if self._pending is tr:
            self._pending = None


def function_name(fc: int | None) -> str:
    if fc is None:
        return "-"
    try:
        return f"FC{fc:02d} {FunctionCode(fc).name.replace('_', ' ').lower()}"
    except ValueError:
        return f"FC{fc:02d}"
