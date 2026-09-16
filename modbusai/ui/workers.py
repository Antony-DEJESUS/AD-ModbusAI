"""Exécution des échanges Modbus hors du thread Qt.

``ModbusWorker`` vit dans un ``QThread`` ; la fenêtre lui envoie des commandes
par signaux (connexions en file, donc thread-safe) et reçoit des
``ExchangeRecord`` en retour. Toute la logique métier reste dans ``modbus`` et
``transport`` : le worker ne fait que les appeler.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from modbusai.modbus.master import RtuMaster
from modbusai.modbus.records import Request
from modbusai.transport.records import SerialSettings, TransportError
from modbusai.transport.serial_link import SerialLink


class ModbusWorker(QObject):
    connected = Signal(object)  # SerialSettings effectivement ouverts
    disconnected = Signal()
    link_error = Signal(str)  # ouverture impossible
    record_ready = Signal(object)  # ExchangeRecord
    request_failed = Signal(str)  # requête refusée avant émission (hors bornes, liaison fermée)

    def __init__(self) -> None:
        super().__init__()
        self._link: SerialLink | None = None
        self._master: RtuMaster | None = None

    @property
    def is_open(self) -> bool:
        return self._link is not None and self._link.is_open

    @Slot(object)
    def open_link(self, settings: SerialSettings) -> None:
        self._close_quietly()
        link = SerialLink(settings, allow_tx=True)
        try:
            link.open()
        except TransportError as exc:
            self.link_error.emit(str(exc))
            return
        self._link = link
        self._master = RtuMaster(link)
        self.connected.emit(settings)

    @Slot()
    def close_link(self) -> None:
        was_open = self.is_open
        self._close_quietly()
        if was_open:
            self.disconnected.emit()

    @Slot(object)
    def execute(self, request: Request) -> None:
        if self._master is None or not self.is_open:
            self.request_failed.emit("Liaison fermée : connectez-vous d'abord")
            return
        try:
            record = self._master.execute(request)
        except ValueError as exc:
            self.request_failed.emit(str(exc))
            return
        self.record_ready.emit(record)

    def _close_quietly(self) -> None:
        if self._link is not None:
            self._link.close()
        self._link = None
        self._master = None
