"""Console de log : une ligne par échange (horodatage, TX, RX, temps, erreur)."""

from __future__ import annotations

from html import escape

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from modbusai.modbus.records import ExchangeRecord, ExchangeStatus

_STATUS_STYLE = {
    ExchangeStatus.OK: ("OK", "#2ea043"),
    ExchangeStatus.TIMEOUT: ("TIMEOUT", "#d29922"),
    ExchangeStatus.CRC_ERROR: ("ERREUR CRC", "#e5534b"),
    ExchangeStatus.MODBUS_EXCEPTION: ("EXCEPTION", "#e5534b"),
    ExchangeStatus.BAD_RESPONSE: ("REPONSE INCOHERENTE", "#e5534b"),
    ExchangeStatus.TRANSPORT_ERROR: ("ERREUR LIAISON", "#a371f7"),
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
        self.setPlaceholderText("Console : horodatage, trame émise, trame reçue, temps de réponse, erreur")

    def log_record(self, rec: ExchangeRecord) -> None:
        label, color = _STATUS_STYLE[rec.status]
        ts = rec.timestamp.strftime("%H:%M:%S.%f")[:-3]
        rx = rec.rx_frame.hex if rec.rx_frame is not None else "-"
        ms = f"{rec.response_time_ms:7.1f} ms" if rec.response_time_ms is not None else "      -    "
        head = f"{ts}  #{rec.seq:<5d} Esc {rec.slave_id:<3d} FC{int(rec.function):02d}"
        line = f"{escape(head)}  TX {escape(rec.tx_frame.hex)}  RX {escape(rx)}  {ms}  "
        tail = f'<span style="color:{color};font-weight:bold">{label}</span>'
        if rec.error_message:
            tail += f'  <span style="color:{color}">{escape(rec.error_message)}</span>'
        self.appendHtml(f'<span style="white-space:pre">{line}</span>{tail}')

    def log_info(self, text: str) -> None:
        self.appendHtml(f'<span style="color:#8b949e">{escape(text)}</span>')

    def log_error(self, text: str) -> None:
        self.appendHtml(f'<span style="color:#e5534b">{escape(text)}</span>')
