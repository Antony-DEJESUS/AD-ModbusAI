"""Threads d'accès au port série. Trois rôles exclusifs, un seul actif à la fois :

* ``ModbusWorker`` : maître (lecture / écriture, scan, campagnes de test) ;
* ``SnifferWorker`` : écoute passive, émission interdite ;
* ``SlaveWorker`` : serveur esclave, répond aux requêtes reçues.

La fenêtre leur parle par signaux (connexions en file, thread-safe). Toute la
logique métier reste dans ``modbus``, ``transport`` et ``analysis``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal, Slot

from modbusai.analysis.sniffer import PassiveDecoder
from modbusai.modbus.master import RtuMaster
from modbusai.modbus.records import Request
from modbusai.modbus.slave import DataStore, SlaveConfig, SlaveHandler
from modbusai.transport.records import SerialSettings, TransportError
from modbusai.transport.serial_link import SerialLink


@dataclass(frozen=True, slots=True)
class ExecuteJob:
    request: Request
    timeout_ms: float | None = None
    tag: str = "maitre"  # source de l'observation : maitre, scan, test


# ================================================================== maître
class ModbusWorker(QObject):
    connected = Signal(object)  # SerialSettings effectivement ouverts
    disconnected = Signal()
    link_error = Signal(str)  # ouverture impossible
    record_ready = Signal(object, object)  # ExchangeRecord, ExecuteJob
    request_failed = Signal(str, object)  # message, ExecuteJob

    def __init__(self) -> None:
        super().__init__()
        self._link: SerialLink | None = None
        self._master: RtuMaster | None = None
        self._seq = 0  # numérotation des échanges, conservée d'une connexion à l'autre

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
        self._master = RtuMaster(link, seq_start=self._seq)
        self.connected.emit(settings)

    @Slot()
    def close_link(self) -> None:
        was_open = self.is_open
        self._close_quietly()
        if was_open:
            self.disconnected.emit()

    @Slot(object)
    def execute(self, job: ExecuteJob) -> None:
        if self._master is None or not self.is_open:
            self.request_failed.emit("Liaison fermée : connectez-vous d'abord", job)
            return
        try:
            record = self._master.execute(job.request, job.timeout_ms)
        except ValueError as exc:
            self.request_failed.emit(str(exc), job)
            return
        self.record_ready.emit(record, job)

    def _close_quietly(self) -> None:
        if self._master is not None:
            self._seq = self._master.seq
        if self._link is not None:
            self._link.close()
        self._link = None
        self._master = None


# ================================================================== espion
class SnifferWorker(QThread):
    """Écoute passive : ouvre la liaison sans émission et publie chaque trame
    classée et chaque transaction appariée."""

    started_listening = Signal(object)  # SerialSettings
    stopped = Signal()
    link_error = Signal(str)
    frames_ready = Signal(object)  # list[SniffedFrame]
    transactions_ready = Signal(object)  # list[Transaction]

    def __init__(self, settings: SerialSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._stop = threading.Event()
        self.decoder = PassiveDecoder(settings.response_timeout_ms)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        link = SerialLink(self.settings, allow_tx=False)
        try:
            link.open()
        except TransportError as exc:
            self.link_error.emit(str(exc))
            return
        self.started_listening.emit(self.settings)
        try:
            last_flush = time.perf_counter_ns()
            for frame in link.read_loop(self._stop):
                sniffed = self.decoder.feed(frame)
                if sniffed:
                    self.frames_ready.emit(sniffed)
                now = time.perf_counter_ns()
                if now - last_flush > 50_000_000:
                    self.decoder.flush(now)
                    last_flush = now
                done = self.decoder.pop_completed()
                if done:
                    self.transactions_ready.emit(done)
        except TransportError as exc:
            self.link_error.emit(str(exc))
        finally:
            self.decoder.flush(time.perf_counter_ns() + 10**12)
            done = self.decoder.pop_completed()
            if done:
                self.transactions_ready.emit(done)
            link.close()
            self.stopped.emit()


# ================================================================= esclave
class SlaveWorker(QThread):
    """Serveur esclave : lit les trames, laisse ``SlaveHandler`` décider, émet la réponse."""

    started_serving = Signal(object)  # SerialSettings
    stopped = Signal()
    link_error = Signal(str)
    handled = Signal(object)  # HandledRequest
    store_changed = Signal()  # une écriture a modifié la table

    def __init__(
        self, settings: SerialSettings, store: DataStore, config: SlaveConfig, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.handler = SlaveHandler(store, config)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        link = SerialLink(self.settings, allow_tx=True)
        try:
            link.open()
        except TransportError as exc:
            self.link_error.emit(str(exc))
            return
        self.started_serving.emit(self.settings)
        store = self.handler.store
        try:
            for frame in link.read_loop(self._stop):
                version = store.version
                result = self.handler.handle(frame.data)
                if result.response is not None:
                    delay = self.handler.config.response_delay_ms
                    if delay > 0:
                        time.sleep(delay / 1000)
                    link.send(result.response)
                self.handled.emit(result)
                if store.version != version:
                    self.store_changed.emit()
        except TransportError as exc:
            self.link_error.emit(str(exc))
        finally:
            link.close()
            self.stopped.emit()
