"""Construction des requêtes RTU et décodage des réponses (FC 01..04, 05, 06, 15, 16).

Pur : octets en entrée, octets ou valeurs en sortie. Aucun accès série.
"""

from __future__ import annotations

from modbusai.modbus.crc import append_crc, check_crc
from modbusai.modbus.exceptions import BadResponse, CrcError, ModbusException
from modbusai.modbus.records import FunctionCode, Request

READ_BITS = (FunctionCode.READ_COILS, FunctionCode.READ_DISCRETE_INPUTS)
READ_REGISTERS = (FunctionCode.READ_HOLDING_REGISTERS, FunctionCode.READ_INPUT_REGISTERS)
WRITE_FUNCTIONS = (
    FunctionCode.WRITE_SINGLE_COIL,
    FunctionCode.WRITE_SINGLE_REGISTER,
    FunctionCode.WRITE_MULTIPLE_COILS,
    FunctionCode.WRITE_MULTIPLE_REGISTERS,
)

IDENTIFICATION_FUNCTIONS = (FunctionCode.REPORT_SLAVE_ID, FunctionCode.READ_DEVICE_ID)
MEI_READ_DEVICE_ID = 0x0E
BROADCAST_ID = 0
"""Adresse de diffusion : tous les esclaves exécutent l'écriture, aucun ne répond."""

MAX_READ_BITS = 2000
MAX_READ_REGISTERS = 125
MAX_WRITE_BITS = 1968
MAX_WRITE_REGISTERS = 123


def validate_request(req: Request) -> None:
    """Lève ValueError si la requête est hors bornes protocole."""
    if not 0 <= req.slave_id <= 247:
        raise ValueError("N° esclave hors plage (0..247)")
    fc = req.function
    if req.slave_id == BROADCAST_ID and fc not in WRITE_FUNCTIONS:
        raise ValueError("Esclave 0 = diffusion : réservée aux écritures, aucun esclave n'y répond")
    if not 0 <= req.address <= 0xFFFF:
        raise ValueError("Adresse hors plage (0..65535)")
    if fc in READ_BITS:
        if not 1 <= req.count <= MAX_READ_BITS:
            raise ValueError(f"Longueur hors plage (1..{MAX_READ_BITS})")
    elif fc in READ_REGISTERS:
        if not 1 <= req.count <= MAX_READ_REGISTERS:
            raise ValueError(f"Longueur hors plage (1..{MAX_READ_REGISTERS})")
    elif fc is FunctionCode.WRITE_SINGLE_COIL:
        if len(req.values) != 1 or req.values[0] not in (0, 1):
            raise ValueError("FC05 : une seule valeur 0 ou 1 attendue")
    elif fc is FunctionCode.WRITE_SINGLE_REGISTER:
        if len(req.values) != 1 or not 0 <= req.values[0] <= 0xFFFF:
            raise ValueError("FC06 : une valeur 0..65535 attendue")
    elif fc is FunctionCode.WRITE_MULTIPLE_COILS:
        if not 1 <= len(req.values) <= MAX_WRITE_BITS:
            raise ValueError(f"FC15 : 1..{MAX_WRITE_BITS} valeurs attendues")
        if any(v not in (0, 1) for v in req.values):
            raise ValueError("FC15 : valeurs 0 ou 1 attendues")
    elif fc is FunctionCode.WRITE_MULTIPLE_REGISTERS:
        if not 1 <= len(req.values) <= MAX_WRITE_REGISTERS:
            raise ValueError(f"FC16 : 1..{MAX_WRITE_REGISTERS} valeurs attendues")
        if any(not 0 <= v <= 0xFFFF for v in req.values):
            raise ValueError("FC16 : valeurs 0..65535 attendues")
    elif fc is FunctionCode.READ_DEVICE_ID:
        if not 1 <= req.address <= 4:
            raise ValueError("FC43 : code de lecture 1..4 attendu")
        if not 0 <= req.count <= 0xFF:
            raise ValueError("FC43 : identifiant d'objet 0..255 attendu")
        return
    elif fc is FunctionCode.REPORT_SLAVE_ID:
        return
    if req.address + max(req.count, len(req.values), 1) > 0x10000:
        raise ValueError("Adresse + longueur dépasse 65535")


def pack_bits(values: tuple[int, ...]) -> bytes:
    """Bits -> octets, LSB en premier (ordre Modbus)."""
    out = bytearray((len(values) + 7) // 8)
    for i, v in enumerate(values):
        if v:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def unpack_bits(data: bytes, count: int) -> tuple[int, ...]:
    return tuple((data[i // 8] >> (i % 8)) & 1 for i in range(count))


def build_pdu(req: Request) -> bytes:
    """PDU (code fonction + données), sans adresse esclave ni CRC."""
    validate_request(req)
    fc = req.function
    if fc in READ_BITS or fc in READ_REGISTERS:
        return bytes([fc]) + req.address.to_bytes(2, "big") + req.count.to_bytes(2, "big")
    if fc is FunctionCode.WRITE_SINGLE_COIL:
        return bytes([fc]) + req.address.to_bytes(2, "big") + (b"\xff\x00" if req.values[0] else b"\x00\x00")
    if fc is FunctionCode.WRITE_SINGLE_REGISTER:
        return bytes([fc]) + req.address.to_bytes(2, "big") + req.values[0].to_bytes(2, "big")
    if fc is FunctionCode.WRITE_MULTIPLE_COILS:
        payload = pack_bits(req.values)
        return (
            bytes([fc])
            + req.address.to_bytes(2, "big")
            + len(req.values).to_bytes(2, "big")
            + bytes([len(payload)])
            + payload
        )
    if fc is FunctionCode.REPORT_SLAVE_ID:
        return bytes([fc])
    if fc is FunctionCode.READ_DEVICE_ID:
        return bytes([fc, MEI_READ_DEVICE_ID, req.address, req.count])
    if fc is FunctionCode.WRITE_MULTIPLE_REGISTERS:
        payload = b"".join(v.to_bytes(2, "big") for v in req.values)
        return (
            bytes([fc])
            + req.address.to_bytes(2, "big")
            + len(req.values).to_bytes(2, "big")
            + bytes([len(payload)])
            + payload
        )
    raise ValueError(f"Code fonction non géré : {fc}")


def build_adu(req: Request) -> bytes:
    """Trame RTU complète : esclave + PDU + CRC."""
    return append_crc(bytes([req.slave_id]) + build_pdu(req))


def expected_response_length(req: Request) -> int | None:
    """Longueur attendue de la réponse normale (esclave + PDU + CRC) ; None si variable."""
    fc = req.function
    if fc in IDENTIFICATION_FUNCTIONS:
        return None
    if fc in READ_BITS:
        return 5 + (req.count + 7) // 8
    if fc in READ_REGISTERS:
        return 5 + 2 * req.count
    return 8  # écritures : écho de 8 octets


def parse_response(req: Request, adu: bytes) -> tuple[int, ...]:
    """Décode une réponse RTU (esclave + PDU + CRC) à ``req``.

    Renvoie les valeurs lues (registres 16 bits ou bits 0/1) ; tuple vide pour
    une écriture acquittée ; octets bruts du corps pour FC17 et FC43 (décodés
    par ``analysis.identification``). Lève ``CrcError``, ``ModbusException``
    ou ``BadResponse``.
    """
    if len(adu) < 5 or not check_crc(adu):
        # Une réponse d'exception fait 5 octets ; en dessous, le CRC ne peut être bon.
        raise CrcError(adu)
    return parse_response_pdu(req, adu[0], adu[1:-2])


def parse_response_pdu(req: Request, slave: int, pdu: bytes) -> tuple[int, ...]:
    """Décode une PDU de réponse (code fonction + données) déjà extraite de son
    enveloppe (CRC en RTU, MBAP en TCP). Lève ``ModbusException`` ou ``BadResponse``."""
    if len(pdu) < 1:
        raise BadResponse("Réponse vide")
    fc = pdu[0]
    body = pdu[1:]
    if slave != req.slave_id:
        raise BadResponse(f"Réponse de l'esclave {slave} au lieu de {req.slave_id}")
    if fc == (req.function | 0x80):
        if len(body) != 1:
            raise BadResponse("Trame d'exception de longueur incorrecte")
        raise ModbusException(req.function, body[0])
    if fc != req.function:
        raise BadResponse(f"Code fonction {fc:02X} au lieu de {req.function:02X}")

    if req.function is FunctionCode.REPORT_SLAVE_ID:
        if len(body) < 1 or body[0] != len(body) - 1:
            raise BadResponse("FC17 : compteur d'octets incohérent")
        return tuple(body[1:])
    if req.function is FunctionCode.READ_DEVICE_ID:
        if len(body) < 6 or body[0] != MEI_READ_DEVICE_ID:
            raise BadResponse("FC43 : type MEI inattendu")
        return tuple(body)

    if req.function in READ_BITS:
        nbytes = (req.count + 7) // 8
        if len(body) != 1 + nbytes or body[0] != nbytes:
            raise BadResponse(f"Longueur de données {len(body) - 1} au lieu de {nbytes}")
        return unpack_bits(body[1:], req.count)
    if req.function in READ_REGISTERS:
        nbytes = 2 * req.count
        if len(body) != 1 + nbytes or body[0] != nbytes:
            raise BadResponse(f"Longueur de données {max(len(body) - 1, 0)} au lieu de {nbytes}")
        return tuple(int.from_bytes(body[i : i + 2], "big") for i in range(1, len(body), 2))

    # Écritures : l'esclave renvoie l'écho de l'adresse et de la valeur / quantité.
    if len(body) != 4:
        raise BadResponse("Acquittement d'écriture de longueur incorrecte")
    addr = int.from_bytes(body[0:2], "big")
    tail = int.from_bytes(body[2:4], "big")
    if addr != req.address:
        raise BadResponse(f"Adresse acquittée {addr} au lieu de {req.address}")
    if req.function is FunctionCode.WRITE_SINGLE_COIL:
        expected = 0xFF00 if req.values[0] else 0x0000
    elif req.function is FunctionCode.WRITE_SINGLE_REGISTER:
        expected = req.values[0]
    else:
        expected = len(req.values)
    if tail != expected:
        raise BadResponse(f"Valeur acquittée 0x{tail:04X} au lieu de 0x{expected:04X}")
    return ()
