"""Erreurs de la couche Modbus et libellés des codes d'exception."""

from __future__ import annotations

from modbusai.i18n import tr

EXCEPTION_LABELS: dict[int, str] = {
    0x01: "Fonction illégale",
    0x02: "Adresse de donnée illégale",
    0x03: "Valeur de donnée illégale",
    0x04: "Défaut esclave",
    0x05: "Acquittement (traitement long)",
    0x06: "Esclave occupé",
    0x07: "Acquittement négatif",
    0x08: "Erreur de parité mémoire",
    0x0A: "Passerelle : chemin indisponible",
    0x0B: "Passerelle : équipement cible sans réponse",
}


def exception_label(code: int) -> str:
    label = EXCEPTION_LABELS.get(code)
    return tr(label) if label is not None else tr("Exception inconnue 0x{p0:02X}").format(p0=code)


class ModbusError(Exception):
    """Base des erreurs de décodage d'une réponse."""


class CrcError(ModbusError):
    def __init__(self, frame: bytes) -> None:
        super().__init__(f"CRC invalide sur {len(frame)} octets")
        self.frame = frame


class BadResponse(ModbusError):
    """Trame au CRC correct mais incohérente avec la requête."""


class ModbusException(ModbusError):
    """Réponse d'exception (code fonction | 0x80)."""

    def __init__(self, function: int, code: int) -> None:
        super().__init__(f"Exception {code:02X} : {exception_label(code)}")
        self.function = function
        self.code = code
