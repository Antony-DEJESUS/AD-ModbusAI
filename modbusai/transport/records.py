"""Dataclasses de la couche transport.

Cette couche ne connaît PAS Modbus : elle voit des octets, des instants et des
silences. Tout ce qui parle d'esclave, de code fonction ou de CRC vit dans
``modbusai.modbus``.

Conventions d'horodatage
------------------------
* ``t_*_ns`` : horloge monotone haute résolution (``time.perf_counter_ns()``),
  utilisée pour toutes les DURÉES (temps de réponse, silences, débit). Ne
  jamais la convertir en date : elle n'a pas d'origine définie.
* ``wall_time`` : horloge murale (``datetime.now()``) capturée une fois par
  trame, uniquement pour l'AFFICHAGE et les logs.

Limite physique : sous Windows avec un adaptateur USB/RS-485, l'OS remonte les
octets par paquets (latence typique 1 à 16 ms). On ne peut donc pas connaître
l'instant exact de chaque octet ; on conserve l'instant de chaque *bloc* lu
(``ByteChunk``). C'est la meilleure granularité disponible, et elle suffit au
futur module de diagnostic (motif d'arrivée, silences, trames tronquées).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime

USB_GAP_FLOOR_MS = 5.0  # plancher pratique du silence de fin de trame (voir SerialSettings.frame_gap_ms)


class Parity(str, enum.Enum):
    """Parité, valeurs alignées sur pyserial."""

    NONE = "N"
    EVEN = "E"
    ODD = "O"


class Direction(enum.Enum):
    """Sens d'une trame vue depuis l'outil."""

    TX = "TX"  # émise par l'outil (mode maître uniquement)
    RX = "RX"  # reçue sur le bus (réponse d'un esclave, ou tout trafic en mode passif)


class LinkState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    ERROR = "error"  # port disparu (câble USB débranché), erreur d'E/S


@dataclass(frozen=True, slots=True)
class SerialSettings:
    """Paramètres de la liaison série. Immuable : on ouvre une liaison avec un
    jeu de paramètres figé ; changer un paramètre = nouvelle instance."""

    port: str
    baudrate: int = 19200
    bytesize: int = 8  # 7 ou 8
    parity: Parity = Parity.NONE
    stopbits: float = 1.0  # 1, 1.5 ou 2
    response_timeout_ms: float = 1000.0
    inter_frame_delay_ms: float | None = None  # None -> T3.5 calculé selon la norme
    rts_toggle: bool = False  # pilotage RTS pour les adaptateurs RS-485 sans auto-direction
    dtr: bool = False

    @property
    def bits_per_char(self) -> float:
        """Start + données + parité éventuelle + stop."""
        return 1 + self.bytesize + (0 if self.parity is Parity.NONE else 1) + self.stopbits

    @property
    def char_time_ms(self) -> float:
        return self.bits_per_char / self.baudrate * 1000.0

    @property
    def t35_ms(self) -> float:
        """Silence inter-trames effectif.

        Norme Modbus sur ligne série : 3,5 caractères, avec plancher fixé à
        1,750 ms au-dessus de 19200 bauds. Surchargé par
        ``inter_frame_delay_ms`` si l'utilisateur l'a saisi.
        """
        if self.inter_frame_delay_ms is not None:
            return self.inter_frame_delay_ms
        if self.baudrate > 19200:
            return 1.75
        return 3.5 * self.char_time_ms

    @property
    def t15_ms(self) -> float:
        """Silence maximal toléré entre deux octets d'une même trame (1,5 car.,
        plancher 750 µs au-dessus de 19200 bauds)."""
        if self.baudrate > 19200:
            return 0.75
        return 1.5 * self.char_time_ms

    @property
    def frame_gap_ms(self) -> float:
        """Silence utilisé en pratique pour déclarer une trame terminée.

        Les adaptateurs USB/RS-485 remontent les octets par paquets (latence
        1 à 16 ms) : appliquer strictement T3.5 à 115200 bauds (1,75 ms)
        couperait une réponse en plusieurs trames. Sans saisie utilisateur, on
        prend donc max(T3.5, USB_GAP_FLOOR_MS). La valeur normative reste
        disponible via ``t35_ms`` pour le futur diagnostic.
        """
        if self.inter_frame_delay_ms is not None:
            return self.inter_frame_delay_ms
        return max(self.t35_ms, USB_GAP_FLOOR_MS)

    def summary(self) -> str:
        """Ex. : ``COM4 : 19200,8,None,One`` (barre de titre, façon Modbus Doctor)."""
        parity = {Parity.NONE: "None", Parity.EVEN: "Even", Parity.ODD: "Odd"}[self.parity]
        stop = {1.0: "One", 1.5: "OnePointFive", 2.0: "Two"}.get(self.stopbits, str(self.stopbits))
        return f"{self.port} : {self.baudrate},{self.bytesize},{parity},{stop}"


@dataclass(frozen=True, slots=True)
class ByteChunk:
    """Bloc d'octets tel que remonté par une lecture du port, avec l'instant
    (monotone) où la lecture est revenue. Granularité réelle de l'horodatage."""

    data: bytes
    t_ns: int


@dataclass(frozen=True, slots=True)
class RawFrame:
    """Suite d'octets délimitée par des silences sur le bus.

    C'est l'unité de base pour le maître (requête / réponse) ET pour le futur
    mode passif (chaque trame vue passer). Aucune interprétation Modbus ici :
    une trame peut être tronquée, bruitée ou avoir un CRC faux, c'est la
    couche ``modbus`` qui le dira.
    """

    direction: Direction
    data: bytes
    t_first_ns: int  # instant du premier bloc reçu (ou du début d'émission)
    t_last_ns: int  # instant du dernier bloc reçu (ou de la fin d'émission)
    wall_time: datetime  # horloge murale au début de la trame, pour les logs
    chunks: tuple[ByteChunk, ...] = ()  # détail des blocs (vide pour une trame TX)
    silence_before_ns: int | None = None  # silence depuis la trame précédente sur le bus, si connu

    @property
    def duration_ms(self) -> float:
        return (self.t_last_ns - self.t_first_ns) / 1_000_000

    @property
    def hex(self) -> str:
        """``01 03 00 00 00 01 84 0A``"""
        return self.data.hex(" ").upper()

    def __len__(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class PortInfo:
    """Port COM détecté (``serial.tools.list_ports``)."""

    device: str  # "COM4"
    description: str = ""  # "USB Serial Port (COM4)"
    hwid: str = ""  # VID:PID... utile pour reconnaître un adaptateur


class TransportError(Exception):
    """Erreur de la couche transport (port absent, E/S, émission interdite)."""


class TransmitNotAllowed(TransportError):
    """Levée si on tente d'émettre sur une liaison ouverte en mode passif."""


@dataclass(slots=True)
class LinkCounters:
    """Compteurs bruts tenus par la liaison depuis son ouverture. Volontairement
    minimalistes en phase 1 ; le module diagnostic fera ses propres stats à
    partir des enregistrements."""

    frames_tx: int = 0
    frames_rx: int = 0
    bytes_tx: int = 0
    bytes_rx: int = 0
    io_errors: int = 0
    opened_at: datetime | None = field(default=None)
