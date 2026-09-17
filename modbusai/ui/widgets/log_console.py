"""Console de log : une ligne par échange (horodatage, TX, RX, temps, erreur), et son bandeau."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from modbusai.i18n import tr
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus
from modbusai.ui.palette import State, color
from modbusai.ui.widgets.labels import section

_STATUS_STYLE = {
    ExchangeStatus.OK: ("OK", State.OK),
    ExchangeStatus.TIMEOUT: ("TIMEOUT", State.WARN),
    ExchangeStatus.CRC_ERROR: ("ERREUR CRC", State.ERROR),
    ExchangeStatus.MODBUS_EXCEPTION: ("EXCEPTION", State.ERROR),
    ExchangeStatus.BAD_RESPONSE: ("REPONSE INCOHERENTE", State.ERROR),
    ExchangeStatus.TRANSPORT_ERROR: ("ERREUR LIAISON", State.SPECIAL),
}


class LogConsole(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setPlaceholderText(tr("Console : horodatage, trame émise, trame reçue, temps de réponse, erreur"))

    def log_record(self, rec: ExchangeRecord) -> None:
        label, state = _STATUS_STYLE[rec.status]
        label, tint = tr(label), color(state)
        ts = rec.timestamp.strftime("%H:%M:%S.%f")[:-3]
        rx = rec.rx_frame.hex if rec.rx_frame is not None else "-"
        ms = f"{rec.response_time_ms:7.1f} ms" if rec.response_time_ms is not None else "      -    "
        head = f"{ts}  #{rec.seq:<5d} Esc {rec.slave_id:<3d} FC{int(rec.function):02d}"
        line = f"{escape(head)}  TX {escape(rec.tx_frame.hex)}  RX {escape(rx)}  {ms}  "
        tail = f'<span style="color:{tint};font-weight:700">{label}</span>'
        if rec.error_message:
            tail += f'  <span style="color:{tint}">{escape(rec.error_message)}</span>'
        self.appendHtml(f'<span style="white-space:pre">{line}</span>{tail}')

    def log_info(self, text: str) -> None:
        self.appendHtml(f'<span style="color:{color(State.MUTED)}">{escape(text)}</span>')

    def log_error(self, text: str) -> None:
        self.appendHtml(f'<span style="color:{color(State.ERROR)}">{escape(text)}</span>')


class LogPanel(QWidget):
    """Console de log avec son bandeau : titre, COPIER (presse-papiers), EFFACER JOURNAL."""

    copied = Signal(int)  # nombre de lignes copiées

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.console = LogConsole()
        self.copy_btn = QPushButton(tr("COPIER"))
        self.copy_btn.setToolTip(tr("Copier tout le journal dans le presse-papiers"))
        self.clear_btn = QPushButton(tr("EFFACER JOURNAL"))
        self.clear_btn.setToolTip(tr("Vider la console (la grille et le dernier échange sont conservés)"))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(section(tr("Journal")))
        header.addStretch(1)
        header.addWidget(self.copy_btn)
        header.addWidget(self.clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addWidget(self.console, 1)

        self.copy_btn.clicked.connect(self._copy_all)
        self.clear_btn.clicked.connect(self.console.clear)

    def _copy_all(self) -> None:
        text = self.console.toPlainText()
        QApplication.clipboard().setText(text)
        self.copied.emit(len(text.splitlines()) if text else 0)
