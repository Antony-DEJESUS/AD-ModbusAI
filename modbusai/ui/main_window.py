"""Fenêtre principale : disposition Modbus Doctor, câblage des widgets et du worker.

Aucune logique Modbus ici : la fenêtre compose des ``Request`` à partir des
champs, envoie au worker, et présente les ``ExchangeRecord`` reçus.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modbusai import APP_TITLE
from modbusai.modbus import codec
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, Request
from modbusai.transport.records import Parity, SerialSettings
from modbusai.ui.widgets.actions_panel import ActionsPanel
from modbusai.ui.widgets.config_dialog import ConfigDialog
from modbusai.ui.widgets.connection_bar import ConnectionBar
from modbusai.ui.widgets.exchange_panel import ExchangePanel
from modbusai.ui.widgets.log_console import LogPanel
from modbusai.ui.widgets.register_grid import RegisterGrid
from modbusai.ui.widgets.request_bar import RequestBar
from modbusai.ui.workers import ModbusWorker

RECONNECT_DELAY_MS = 1500


class MainWindow(QMainWindow):
    # Commandes vers le worker (connexions en file : exécutées dans son thread)
    _cmd_open = Signal(object)
    _cmd_close = Signal()
    _cmd_execute = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1000, 640)

        self._settings = self._load_settings()
        self._connected = False
        self._busy = False
        self._last_values: tuple[int, ...] | None = None  # dernière lecture réussie (brute)
        self._last_start = 0
        self._last_is_bits = False
        self._reconnect_pending = False
        self._resume_cycle = False  # cycle interrompu par une panne de liaison, à reprendre après reconnexion

        # ------------------------------------------------------------ widgets
        self.connection_bar = ConnectionBar()
        self.request_bar = RequestBar()
        self.actions = ActionsPanel()
        self.grid = RegisterGrid()
        self.exchange = ExchangePanel()
        self.log_panel = LogPanel()
        self.console = self.log_panel.console
        self.status_label = QLabel("Status : déconnecté")

        middle = QSplitter(Qt.Orientation.Horizontal)
        middle.addWidget(self.actions)
        middle.addWidget(self.grid)
        middle.addWidget(self.exchange)
        middle.setStretchFactor(1, 2)
        middle.setStretchFactor(2, 1)
        middle.setChildrenCollapsible(False)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(middle)
        vertical.addWidget(self.log_panel)
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 1)
        vertical.setChildrenCollapsible(False)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(self.connection_bar)
        layout.addWidget(self.request_bar)
        layout.addWidget(vertical, 1)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label)
        layout.addLayout(status_row)
        self.setCentralWidget(central)

        # ------------------------------------------------------------- worker
        self._thread = QThread(self)
        self._worker = ModbusWorker()
        self._worker.moveToThread(self._thread)
        self._cmd_open.connect(self._worker.open_link)
        self._cmd_close.connect(self._worker.close_link)
        self._cmd_execute.connect(self._worker.execute)
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.link_error.connect(self._on_link_error)
        self._worker.record_ready.connect(self._on_record)
        self._worker.request_failed.connect(self._on_request_failed)
        self._thread.start()

        self._cycle_timer = QTimer(self)
        self._cycle_timer.timeout.connect(self._cycle_tick)

        # ------------------------------------------------------------ signaux
        self.connection_bar.configure_requested.connect(self._configure)
        self.connection_bar.connect_requested.connect(self._connect)
        self.connection_bar.disconnect_requested.connect(self._disconnect)
        self.connection_bar.quit_requested.connect(self.close)
        self.request_bar.changed.connect(self._on_request_changed)
        self.request_bar.radix_changed.connect(lambda _r: self._refresh_grid())
        self.actions.read_requested.connect(self._read)
        self.actions.write_requested.connect(self._write)
        self.actions.stop_cycle_requested.connect(self._stop_cycle)
        self.actions.display_changed.connect(self._refresh_grid)
        self.actions.cyclic.toggled.connect(self._on_cyclic_toggled)
        self.exchange.clear_requested.connect(self._clear)
        self.log_panel.copied.connect(lambda n: self._set_status(f"Journal copié dans le presse-papiers ({n} lignes)"))

        self.connection_bar.show_settings(self._settings)
        self._on_request_changed()

    # ================================================================ liaison
    def _configure(self) -> None:
        dlg = ConfigDialog(self._settings, self)
        if dlg.exec():
            self._settings = dlg.settings()
            self.connection_bar.show_settings(self._settings)
            self._save_settings()

    def _connect(self) -> None:
        if not self._settings.port:
            QMessageBox.warning(self, APP_TITLE, "Choisissez un port dans CONFIGURATION.")
            return
        self._set_status(f"Ouverture de {self._settings.port}…")
        self._cmd_open.emit(self._settings)

    def _disconnect(self) -> None:
        self._reconnect_pending = False
        self._resume_cycle = False
        self._stop_cycle()
        self._cmd_close.emit()

    def _on_connected(self, settings: SerialSettings) -> None:
        self._connected = True
        self._reconnect_pending = False
        self.connection_bar.set_connected(True)
        self._set_status(
            f"Connecté : {settings.summary()} (timeout {settings.response_timeout_ms:g} ms, "
            f"silence fin de trame {settings.frame_gap_ms:.2f} ms)"
        )
        self.console.log_info(f"Connexion {settings.summary()}")
        if self._resume_cycle and self.actions.cyclic.isChecked():
            self._start_cycle("Cycle repris")
        self._resume_cycle = False

    def _on_disconnected(self) -> None:
        self._connected = False
        self._busy = False
        self.connection_bar.set_connected(False)
        self._set_status("Status : déconnecté")
        self.console.log_info("Déconnexion")

    def _on_link_error(self, message: str) -> None:
        self._connected = False
        self.connection_bar.set_connected(False)
        self._set_status(message)
        self.console.log_error(message)
        self._maybe_schedule_reconnect()

    def _maybe_schedule_reconnect(self) -> None:
        if not self.actions.auto_reconnect.isChecked() or self._reconnect_pending:
            return
        self._reconnect_pending = True
        self._set_status(f"Reconnexion automatique dans {RECONNECT_DELAY_MS / 1000:.1f} s…")
        QTimer.singleShot(RECONNECT_DELAY_MS, self._try_reconnect)

    def _try_reconnect(self) -> None:
        if not self._reconnect_pending:
            return
        self._reconnect_pending = False
        if not self._connected:
            self._cmd_open.emit(self._settings)

    # =============================================================== requêtes
    def _read(self) -> None:
        if not self._ensure_connected():
            return
        if self.actions.cyclic.isChecked() and not self._cycle_timer.isActive():
            self._start_cycle("Cycle démarré")
        self._send(self._read_request())

    def _start_cycle(self, message: str) -> None:
        self._cycle_timer.start(self.actions.cycle_period_ms)
        self.actions.set_cycling(True)
        self.console.log_info(f"{message} ({self.actions.cycle_period_ms} ms)")

    def _write(self) -> None:
        if not self._ensure_connected():
            return
        rb = self.request_bar
        reg_type = rb.current_type
        count = rb.count.value()
        fc = reg_type.write_function(count)
        if fc is None:
            self._on_request_failed("Ce type de donnée n'est pas inscriptible")
            return
        try:
            texts = self.grid.value_texts()
            if reg_type.is_bits:
                values = codec.parse_bits(texts)
                if len(values) != count:
                    raise ValueError(f"{count} valeur(s) attendue(s), {len(values)} saisie(s)")
            else:
                values = codec.parse_rows(texts, count, self._display_options())
        except ValueError as exc:
            self._on_request_failed(f"Saisie invalide : {exc}")
            return
        self._send(Request(rb.slave.value(), fc, rb.register.value(), count, tuple(values)))

    def _read_request(self) -> Request:
        rb = self.request_bar
        return Request(rb.slave.value(), rb.current_type.read_function, rb.register.value(), rb.count.value())

    def _send(self, request: Request) -> None:
        self._busy = True
        self._cmd_execute.emit(request)

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        self._on_request_failed("Liaison fermée : cliquez sur CONNEXION")
        return False

    def _cycle_tick(self) -> None:
        if not self._connected:
            return
        if self._busy:  # la requête précédente n'est pas terminée : on saute ce tick
            return
        self._send(self._read_request())

    def _stop_cycle(self) -> None:
        if self._cycle_timer.isActive():
            self._cycle_timer.stop()
            self.console.log_info("Cycle arrêté")
        self.actions.set_cycling(False)

    def _on_cyclic_toggled(self, checked: bool) -> None:
        if not checked:
            self._stop_cycle()

    # ================================================================ retours
    def _on_record(self, rec: ExchangeRecord) -> None:
        self._busy = False
        self.console.log_record(rec)
        self.exchange.show_record(rec)
        if rec.ok:
            if rec.values is not None and rec.request.function in (1, 2, 3, 4):
                self._last_values = rec.values
                self._last_start = rec.request.address
                self._last_is_bits = rec.request.function in (1, 2)
                self._refresh_grid()
            self._set_status(f"Status : {rec.status.name}  -  {rec.response_time_ms:.1f} ms")
        else:
            self.grid.mark_stale(True)
            self._set_status(f"Status : {rec.status.name}  -  {rec.error_message or ''}")
            if rec.status is ExchangeStatus.TRANSPORT_ERROR:
                self._connected = False
                self.connection_bar.set_connected(False)
                self._resume_cycle = self._cycle_timer.isActive() and self.actions.auto_reconnect.isChecked()
                self._stop_cycle()
                self._cmd_close.emit()
                self._maybe_schedule_reconnect()

    def _on_request_failed(self, message: str) -> None:
        self._busy = False
        self.console.log_error(message)
        self._set_status(f"Status : {message}")

    # ================================================================== grille
    def _display_options(self) -> codec.DisplayOptions:
        return self.actions.display_options(self.request_bar.current_radix)

    def _on_request_changed(self) -> None:
        reg_type = self.request_bar.current_type
        self.actions.set_bits_mode(reg_type.is_bits)
        self.actions.set_writable(reg_type.writable)
        self._last_values = None  # la grille ne correspond plus à une lecture
        self._refresh_grid()

    def _refresh_grid(self) -> None:
        rb = self.request_bar
        reg_type = rb.current_type
        count = rb.count.value()
        start = rb.register.value()
        if self._last_values is not None and self._last_is_bits == reg_type.is_bits:
            values, start, stale = self._last_values, self._last_start, False
        else:
            values, stale = (0,) * count, True
        if reg_type.is_bits:
            rows = codec.format_bits(values, start)
        else:
            rows = codec.format_registers(values, start, self._display_options())
        self.grid.show_rows(rows)
        self.grid.mark_stale(stale)

    def _clear(self) -> None:
        self.console.clear()
        self.exchange.clear()
        self._last_values = None
        self._refresh_grid()

    # ============================================================== utilitaires
    def _set_status(self, text: str) -> None:
        self.status_label.setText(text if text.startswith("Status") else f"Status : {text}")

    def _load_settings(self) -> SerialSettings:
        qs = QSettings()
        inter = qs.value("serial/inter_frame_delay_ms", None)
        return SerialSettings(
            port=str(qs.value("serial/port", "")),
            baudrate=int(qs.value("serial/baudrate", 19200)),
            bytesize=int(qs.value("serial/bytesize", 8)),
            parity=Parity(str(qs.value("serial/parity", "N"))),
            stopbits=float(qs.value("serial/stopbits", 1.0)),
            response_timeout_ms=float(qs.value("serial/timeout_ms", 1000.0)),
            inter_frame_delay_ms=float(inter) if inter not in (None, "", "None") else None,
            rts_toggle=str(qs.value("serial/rts", "false")).lower() == "true",
            dtr=str(qs.value("serial/dtr", "false")).lower() == "true",
        )

    def _save_settings(self) -> None:
        s = self._settings
        qs = QSettings()
        qs.setValue("serial/port", s.port)
        qs.setValue("serial/baudrate", s.baudrate)
        qs.setValue("serial/bytesize", s.bytesize)
        qs.setValue("serial/parity", str(s.parity.value))
        qs.setValue("serial/stopbits", s.stopbits)
        qs.setValue("serial/timeout_ms", s.response_timeout_ms)
        qs.setValue("serial/inter_frame_delay_ms", "" if s.inter_frame_delay_ms is None else s.inter_frame_delay_ms)
        qs.setValue("serial/rts", "true" if s.rts_toggle else "false")
        qs.setValue("serial/dtr", "true" if s.dtr else "false")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cycle_timer.stop()
        self._cmd_close.emit()
        self._thread.quit()
        if not self._thread.wait(3000):
            self._thread.terminate()
        QApplication.processEvents()
        super().closeEvent(event)
