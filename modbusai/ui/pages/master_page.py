"""Onglet MAÎTRE : lecture / écriture façon Modbus Doctor (page de la phase 1)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from modbusai.modbus import codec
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, Request
from modbusai.ui.widgets.actions_panel import ActionsPanel
from modbusai.ui.widgets.exchange_panel import ExchangePanel
from modbusai.ui.widgets.log_console import LogPanel
from modbusai.ui.widgets.register_grid import RegisterGrid
from modbusai.ui.widgets.request_bar import RequestBar
from modbusai.ui.workers import ExecuteJob

TAG = "maitre"


class MasterPage(QWidget):
    execute_requested = Signal(object)  # ExecuteJob
    status_message = Signal(str)
    link_lost = Signal()  # erreur transport pendant un échange

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._busy = False
        self._last_values: tuple[int, ...] | None = None
        self._last_start = 0
        self._last_is_bits = False
        self._resume_cycle = False

        self.request_bar = RequestBar()
        self.actions = ActionsPanel()
        self.grid = RegisterGrid()
        self.exchange = ExchangePanel()
        self.log_panel = LogPanel()
        self.console = self.log_panel.console

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.request_bar)
        layout.addWidget(vertical, 1)

        self._cycle_timer = QTimer(self)
        self._cycle_timer.timeout.connect(self._cycle_tick)

        self.request_bar.changed.connect(self._on_request_changed)
        self.request_bar.radix_changed.connect(lambda _r: self._refresh_grid())
        self.actions.read_requested.connect(self._read)
        self.actions.write_requested.connect(self._write)
        self.actions.stop_cycle_requested.connect(self.stop_cycle)
        self.actions.display_changed.connect(self._refresh_grid)
        self.actions.cyclic.toggled.connect(lambda checked: None if checked else self.stop_cycle())
        self.exchange.clear_requested.connect(self._clear)
        self.log_panel.copied.connect(
            lambda n: self.status_message.emit(f"Journal copié dans le presse-papiers ({n} lignes)")
        )
        self._on_request_changed()

    # ============================================================== liaison
    @property
    def auto_reconnect(self) -> bool:
        return self.actions.auto_reconnect.isChecked()

    def on_connected(self, summary: str) -> None:
        self._connected = True
        self.console.log_info(f"Connexion {summary}")
        if self._resume_cycle and self.actions.cyclic.isChecked():
            self._start_cycle("Cycle repris")
        self._resume_cycle = False

    def on_disconnected(self, manual: bool) -> None:
        self._connected = False
        self._busy = False
        if manual:
            self._resume_cycle = False
        self.stop_cycle()
        self.console.log_info("Déconnexion")

    def log_info(self, text: str) -> None:
        self.console.log_info(text)

    def log_error(self, text: str) -> None:
        self.console.log_error(text)

    def set_interactive(self, enabled: bool) -> None:
        """Désactivé pendant qu'un scan ou une campagne utilise la liaison."""
        self.actions.setEnabled(enabled)
        self.request_bar.setEnabled(enabled)
        if not enabled:
            self.stop_cycle()

    # ============================================================= requêtes
    def _read(self) -> None:
        if not self._ensure_connected():
            return
        if self.actions.cyclic.isChecked() and not self._cycle_timer.isActive():
            self._start_cycle("Cycle démarré")
        self._send(self._read_request())

    def _write(self) -> None:
        if not self._ensure_connected():
            return
        rb = self.request_bar
        reg_type = rb.current_type
        count = rb.count.value()
        fc = reg_type.write_function(count)
        if fc is None:
            self.on_request_failed("Ce type de donnée n'est pas inscriptible")
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
            self.on_request_failed(f"Saisie invalide : {exc}")
            return
        self._send(Request(rb.slave.value(), fc, rb.register.value(), count, tuple(values)))

    def _read_request(self) -> Request:
        rb = self.request_bar
        return Request(rb.slave.value(), rb.current_type.read_function, rb.register.value(), rb.count.value())

    def _send(self, request: Request) -> None:
        self._busy = True
        self.execute_requested.emit(ExecuteJob(request, tag=TAG))

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        self.on_request_failed("Liaison fermée : cliquez sur CONNEXION")
        return False

    # ================================================================ cycle
    def _start_cycle(self, message: str) -> None:
        self._cycle_timer.start(self.actions.cycle_period_ms)
        self.actions.set_cycling(True)
        self.console.log_info(f"{message} ({self.actions.cycle_period_ms} ms)")

    def _cycle_tick(self) -> None:
        if self._connected and not self._busy:
            self._send(self._read_request())

    def stop_cycle(self) -> None:
        if self._cycle_timer.isActive():
            self._cycle_timer.stop()
            self.console.log_info("Cycle arrêté")
        self.actions.set_cycling(False)

    # ============================================================== retours
    def on_record(self, rec: ExchangeRecord) -> None:
        self._busy = False
        self.console.log_record(rec)
        self.exchange.show_record(rec)
        if rec.ok:
            if rec.values is not None and rec.request.function in (1, 2, 3, 4):
                self._last_values = rec.values
                self._last_start = rec.request.address
                self._last_is_bits = rec.request.function in (1, 2)
                self._refresh_grid()
            self.status_message.emit(f"Status : {rec.status.name}  -  {rec.response_time_ms:.1f} ms")
        else:
            self.grid.mark_stale(True)
            self.status_message.emit(f"Status : {rec.status.name}  -  {rec.error_message or ''}")
            if rec.status is ExchangeStatus.TRANSPORT_ERROR:
                self._resume_cycle = self._cycle_timer.isActive() and self.auto_reconnect
                self.stop_cycle()
                self.link_lost.emit()

    def on_request_failed(self, message: str) -> None:
        self._busy = False
        self.console.log_error(message)
        self.status_message.emit(f"Status : {message}")

    # =============================================================== grille
    def _display_options(self) -> codec.DisplayOptions:
        return self.actions.display_options(self.request_bar.current_radix)

    def _on_request_changed(self) -> None:
        reg_type = self.request_bar.current_type
        self.actions.set_bits_mode(reg_type.is_bits)
        self.actions.set_writable(reg_type.writable)
        self._last_values = None
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
        rows = (
            codec.format_bits(values, start)
            if reg_type.is_bits
            else codec.format_registers(values, start, self._display_options())
        )
        self.grid.show_rows(rows)
        self.grid.mark_stale(stale)

    def _clear(self) -> None:
        self.console.clear()
        self.exchange.clear()
        self._last_values = None
        self._refresh_grid()
