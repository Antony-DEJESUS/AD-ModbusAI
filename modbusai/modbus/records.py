"""Enregistrement structuré d'un échange Modbus : la matière première du futur
module de diagnostic.

Un ``ExchangeRecord`` est produit pour CHAQUE requête émise, qu'elle ait réussi
ou non. Il embarque les trames brutes (``RawFrame``) de la couche transport et
le verdict de la couche Modbus.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from modbusai.transport.records import RawFrame, SerialSettings


class FunctionCode(enum.IntEnum):
    READ_COILS = 0x01
    READ_DISCRETE_INPUTS = 0x02
    READ_HOLDING_REGISTERS = 0x03
    READ_INPUT_REGISTERS = 0x04
    WRITE_SINGLE_COIL = 0x05
    WRITE_SINGLE_REGISTER = 0x06
    WRITE_MULTIPLE_COILS = 0x0F
    WRITE_MULTIPLE_REGISTERS = 0x10


class ExchangeStatus(enum.Enum):
    OK = "ok"
    TIMEOUT = "timeout"  # aucun octet reçu dans le délai
    CRC_ERROR = "crc_error"  # trame reçue mais CRC faux (bruit, collision, mauvais bauds)
    MODBUS_EXCEPTION = "modbus_exception"  # réponse FC|0x80 + code, voir ``exception_code``
    BAD_RESPONSE = "bad_response"  # CRC juste mais incohérente : mauvais esclave, mauvais FC, longueur
    TRANSPORT_ERROR = "transport_error"  # port fermé/disparu, erreur d'E/S


@dataclass(frozen=True, slots=True)
class Request:
    """Ce que l'utilisateur demande, indépendamment de l'encodage trame."""

    slave_id: int
    function: FunctionCode
    address: int  # adresse de départ, base 0 (protocole)
    count: int = 1  # nombre de registres / bobines à lire ou écrire
    values: tuple[int, ...] = ()  # valeurs à écrire (FC 05/06/15/16), vide en lecture


@dataclass(frozen=True, slots=True)
class ExchangeRecord:
    """Trace complète d'une requête et de son issue."""

    seq: int  # numéro d'ordre dans la session (1, 2, 3...)
    timestamp: datetime  # horloge murale au moment de l'émission
    request: Request
    settings: SerialSettings  # instantané des paramètres liaison au moment de l'échange
    tx_frame: RawFrame
    rx_frame: RawFrame | None  # None si timeout ou erreur transport
    status: ExchangeStatus
    response_time_ms: float | None  # fin TX -> premier octet RX ; None si rien reçu
    exception_code: int | None = None  # renseigné si status == MODBUS_EXCEPTION
    error_message: str | None = None  # libellé humain pour la console
    values: tuple[int, ...] | None = None  # registres (16 bits) ou bits (0/1) décodés, si OK

    @property
    def slave_id(self) -> int:
        return self.request.slave_id

    @property
    def function(self) -> FunctionCode:
        return self.request.function

    @property
    def ok(self) -> bool:
        return self.status is ExchangeStatus.OK
