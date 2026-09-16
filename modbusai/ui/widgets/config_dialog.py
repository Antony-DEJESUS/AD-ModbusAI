"""Popup CONFIGURATION : paramètres de la liaison série (façon Modbus Doctor)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modbusai.transport.ports import list_serial_ports
from modbusai.transport.records import Parity, SerialSettings

BAUDRATES = (1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200)
_PARITY_LABELS = {Parity.NONE: "None", Parity.EVEN: "Even", Parity.ODD: "Odd"}
_STOP_LABELS = {1.0: "One", 1.5: "OnePointFive", 2.0: "Two"}


class ConfigDialog(QDialog):
    def __init__(self, current: SerialSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuration de la liaison")
        self.setModal(True)

        self.port = QComboBox()
        self.port.setEditable(True)  # permet de saisir un COM non détecté
        refresh = QPushButton("↻")
        refresh.setFixedWidth(28)
        refresh.setToolTip("Rafraîchir la liste des ports")
        refresh.clicked.connect(self._refresh_ports)
        port_row = QHBoxLayout()
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.addWidget(self.port, 1)
        port_row.addWidget(refresh)
        port_widget = QWidget()
        port_widget.setLayout(port_row)

        self.baudrate = QComboBox()
        self.baudrate.setEditable(True)
        for b in BAUDRATES:
            self.baudrate.addItem(str(b), b)

        self.databits = QComboBox()
        for d in (7, 8):
            self.databits.addItem(str(d), d)

        self.stopbits = QComboBox()
        for v, label in _STOP_LABELS.items():
            self.stopbits.addItem(label, v)

        self.parity = QComboBox()
        for p, label in _PARITY_LABELS.items():
            self.parity.addItem(label, p)

        self.dtr = QCheckBox("Activer DTR")
        self.rts = QCheckBox("Piloter RTS pendant l'émission (direction RS-485)")

        self.timeout = QSpinBox()
        self.timeout.setRange(20, 60000)
        self.timeout.setSingleStep(50)
        self.timeout.setSuffix(" ms")

        self.inter_frame = QDoubleSpinBox()
        self.inter_frame.setRange(0.0, 1000.0)
        self.inter_frame.setDecimals(2)
        self.inter_frame.setSingleStep(0.5)
        self.inter_frame.setSuffix(" ms")
        self.inter_frame.setSpecialValueText("Auto (T3.5, plancher 5 ms)")
        self.inter_frame.setToolTip(
            "Silence déclarant la fin d'une trame. 0 = automatique : 3,5 caractères selon la norme, "
            "avec un plancher de 5 ms pour absorber la latence des adaptateurs USB."
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("SerialPortName", port_widget)
        form.addRow("BaudRate", self.baudrate)
        form.addRow("DataBits", self.databits)
        form.addRow("StopBits", self.stopbits)
        form.addRow("Parity", self.parity)
        form.addRow("DTR", self.dtr)
        form.addRow("RTS", self.rts)
        form.addRow("TimeOut", self.timeout)
        form.addRow("Délai inter-trames", self.inter_frame)

        close_btn = QPushButton("FERMER")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(close_btn)

        self._refresh_ports()
        self._load(current)

    # ---------------------------------------------------------------- data
    def _refresh_ports(self) -> None:
        current = self.port.currentText()
        self.port.clear()
        for p in list_serial_ports():
            label = f"{p.device}  -  {p.description}" if p.description else p.device
            self.port.addItem(label, p.device)
        if current:
            self._select_port(current)

    def _select_port(self, device: str) -> None:
        for i in range(self.port.count()):
            if self.port.itemData(i) == device:
                self.port.setCurrentIndex(i)
                return
        self.port.setEditText(device)

    def _load(self, s: SerialSettings) -> None:
        if s.port:
            self._select_port(s.port)
        idx = self.baudrate.findData(s.baudrate)
        if idx >= 0:
            self.baudrate.setCurrentIndex(idx)
        else:
            self.baudrate.setEditText(str(s.baudrate))
        self.databits.setCurrentIndex(max(0, self.databits.findData(s.bytesize)))
        self.stopbits.setCurrentIndex(max(0, self.stopbits.findData(float(s.stopbits))))
        self.parity.setCurrentIndex(max(0, self.parity.findData(s.parity)))
        self.dtr.setChecked(s.dtr)
        self.rts.setChecked(s.rts_toggle)
        self.timeout.setValue(int(s.response_timeout_ms))
        self.inter_frame.setValue(s.inter_frame_delay_ms or 0.0)

    def settings(self) -> SerialSettings:
        port = self.port.currentData() if self.port.currentIndex() >= 0 and self.port.currentData() else ""
        text = self.port.currentText().strip()
        if not port or (text and not text.startswith(port)):
            port = text.split()[0] if text else ""
        try:
            baud = int(self.baudrate.currentText().strip())
        except ValueError:
            baud = 19200
        inter = self.inter_frame.value()
        return SerialSettings(
            port=port,
            baudrate=baud,
            bytesize=self.databits.currentData(),
            parity=self.parity.currentData(),
            stopbits=self.stopbits.currentData(),
            response_timeout_ms=float(self.timeout.value()),
            inter_frame_delay_ms=inter if inter > 0 else None,
            rts_toggle=self.rts.isChecked(),
            dtr=self.dtr.isChecked(),
        )
