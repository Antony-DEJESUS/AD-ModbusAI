"""Panneau droit : MODE ESPION (désactivé en phase 1), EFFACER, détail du dernier échange."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from modbusai.modbus.records import ExchangeRecord


class ExchangePanel(QFrame):
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(300)

        self.spy_btn = QPushButton("MODE ESPION")
        self.spy_btn.setEnabled(False)
        self.spy_btn.setToolTip("Mode passif (écoute du bus) : phase ultérieure")
        self.clear_btn = QPushButton("EFFACER")
        self.clear_btn.clicked.connect(self.clear_requested)

        buttons = QHBoxLayout()
        buttons.addWidget(self.spy_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)

        self.status = QLabel("-")
        self.status.setStyleSheet("font-weight: bold;")
        self.response_time = QLabel("-")
        self.transaction_time = QLabel("-")
        self.tx = _wrap_label()
        self.rx = _wrap_label()
        self.rx_detail = QLabel("-")
        self.error = _wrap_label()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Résultat", self.status)
        form.addRow("Temps de réponse", self.response_time)
        form.addRow("Transaction", self.transaction_time)
        form.addRow("Trame émise", self.tx)
        form.addRow("Trame reçue", self.rx)
        form.addRow("Réception", self.rx_detail)
        form.addRow("Erreur", self.error)
        box = QGroupBox("Dernier échange")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(buttons)
        layout.addWidget(box)
        layout.addStretch(1)

    def show_record(self, rec: ExchangeRecord) -> None:
        self.status.setText(rec.status.name)
        self.status.setStyleSheet("font-weight: bold; color: %s;" % ("#2ea043" if rec.ok else "#e5534b"))
        self.response_time.setText(f"{rec.response_time_ms:.1f} ms" if rec.response_time_ms is not None else "-")
        tt = rec.transaction_time_ms
        self.transaction_time.setText(f"{tt:.1f} ms" if tt is not None else "-")
        self.tx.setText(rec.tx_frame.hex)
        if rec.rx_frame is not None:
            self.rx.setText(rec.rx_frame.hex)
            self.rx_detail.setText(
                f"{len(rec.rx_frame)} octets en {len(rec.rx_frame.chunks)} bloc(s), {rec.rx_frame.duration_ms:.1f} ms"
            )
        else:
            self.rx.setText("-")
            self.rx_detail.setText("-")
        self.error.setText(rec.error_message or "-")

    def clear(self) -> None:
        for w in (self.status, self.response_time, self.transaction_time, self.tx, self.rx, self.rx_detail, self.error):
            w.setText("-")
        self.status.setStyleSheet("font-weight: bold;")


def _wrap_label() -> QLabel:
    lbl = QLabel("-")
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setStyleSheet("font-family: monospace;")
    return lbl
