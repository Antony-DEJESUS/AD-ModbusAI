"""Popup CONFIGURATION : paramètres de la liaison série (façon Modbus Doctor) ou TCP."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modbusai.i18n import tr
from modbusai.transport.ports import list_serial_ports
from modbusai.transport.records import LinkSettings, Parity, SerialSettings, TcpSettings
from modbusai.ui.network_tools import PingWorker, network_connections_available, open_network_connections

BAUDRATES = (1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200)
_PARITY_LABELS = {Parity.NONE: "None", Parity.EVEN: "Even", Parity.ODD: "Odd"}
_STOP_LABELS = {1.0: "One", 1.5: "OnePointFive", 2.0: "Two"}


class SerialForm(QWidget):
    """Volet série : paramètres du port COM (façon Modbus Doctor)."""

    def __init__(self, current: SerialSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.port = QComboBox()
        self.port.setEditable(True)  # permet de saisir un COM non détecté
        refresh = QPushButton("↻")
        refresh.setFixedWidth(28)
        refresh.setToolTip(tr("Rafraîchir la liste des ports"))
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

        self.dtr = QCheckBox(tr("Activer DTR"))
        self.rts = QCheckBox(tr("Piloter RTS pendant l'émission (direction RS-485)"))

        self.timeout = QSpinBox()
        self.timeout.setRange(20, 60000)
        self.timeout.setSingleStep(50)
        self.timeout.setSuffix(" ms")

        self.inter_frame = QDoubleSpinBox()
        self.inter_frame.setRange(0.0, 1000.0)
        self.inter_frame.setDecimals(2)
        self.inter_frame.setSingleStep(0.5)
        self.inter_frame.setSuffix(" ms")
        self.inter_frame.setSpecialValueText(tr("Auto (T3.5, plancher 5 ms)"))
        self.inter_frame.setToolTip(
            "Silence déclarant la fin d'une trame. 0 = automatique : 3,5 caractères selon la norme, "
            "avec un plancher de 5 ms pour absorber la latence des adaptateurs USB."
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow(tr("SerialPortName"), port_widget)
        form.addRow(tr("BaudRate"), self.baudrate)
        form.addRow(tr("DataBits"), self.databits)
        form.addRow(tr("StopBits"), self.stopbits)
        form.addRow(tr("Parity"), self.parity)
        form.addRow(tr("DTR"), self.dtr)
        form.addRow(tr("RTS"), self.rts)
        form.addRow(tr("TimeOut"), self.timeout)
        form.addRow(tr("Délai inter-trames"), self.inter_frame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)

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
            parity=Parity(self.parity.currentData()),
            stopbits=self.stopbits.currentData(),
            response_timeout_ms=float(self.timeout.value()),
            inter_frame_delay_ms=inter if inter > 0 else None,
            rts_toggle=self.rts.isChecked(),
            dtr=self.dtr.isChecked(),
        )


class TcpForm(QWidget):
    """Volet réseau : hôte, port, délais, ping et accès aux connexions réseau Windows."""

    def __init__(self, current: TcpSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ping: PingWorker | None = None
        self.host = QLineEdit(current.host)
        self.host.setPlaceholderText(tr("192.168.1.10 ou nom d'hôte"))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(current.port)
        self.timeout = QSpinBox()
        self.timeout.setRange(20, 60000)
        self.timeout.setSingleStep(50)
        self.timeout.setSuffix(" ms")
        self.timeout.setValue(int(current.response_timeout_ms))
        self.connect_timeout = QSpinBox()
        self.connect_timeout.setRange(200, 60000)
        self.connect_timeout.setSingleStep(500)
        self.connect_timeout.setSuffix(" ms")
        self.connect_timeout.setValue(int(current.connect_timeout_ms))

        self.ping_btn = QPushButton(tr("PING"))
        self.ping_btn.setToolTip(tr("Envoie 4 pings système vers l'hôte, sans bloquer l'interface"))
        self.net_btn = QPushButton(tr("Connexions réseau"))
        self.net_btn.setToolTip(tr("Ouvre le panneau Windows « Connexions réseau » (ncpa.cpl)"))
        self.net_btn.setEnabled(network_connections_available())
        if not network_connections_available():
            self.net_btn.setToolTip(tr("Disponible uniquement sous Windows"))
        self.ping_output = QPlainTextEdit()
        self.ping_output.setReadOnly(True)
        self.ping_output.setMaximumHeight(120)
        self.ping_output.setPlaceholderText(tr("Résultat du ping"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow(tr("Hôte"), self.host)
        form.addRow(tr("Port"), self.port)
        form.addRow(tr("TimeOut réponse"), self.timeout)
        form.addRow(tr("TimeOut connexion"), self.connect_timeout)
        tools = QHBoxLayout()
        tools.addWidget(self.ping_btn)
        tools.addWidget(self.net_btn)
        tools.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addLayout(tools)
        layout.addWidget(self.ping_output)
        self.hint = QLabel(
            "Note : le mode espion n'est pas disponible en TCP (il faut une recopie de port sur le switch)."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(self.hint)

        self.ping_btn.clicked.connect(self._ping_host)
        self.net_btn.clicked.connect(self._open_network)

    def _ping_host(self) -> None:
        if self._ping is not None and self._ping.isRunning():
            return
        self.ping_output.setPlainText(tr("Ping vers {p0}…").format(p0=self.host.text().strip()))
        self.ping_btn.setEnabled(False)
        self._ping = PingWorker(self.host.text(), parent=self)
        self._ping.finished_with.connect(self._on_ping_done)
        self._ping.start()

    def _on_ping_done(self, output: str, ok: bool) -> None:
        self.ping_output.setPlainText(output)
        self.ping_btn.setEnabled(True)

    def _open_network(self) -> None:
        err = open_network_connections()
        if err:
            self.ping_output.setPlainText(err)

    def settings(self) -> TcpSettings:
        return TcpSettings(
            host=self.host.text().strip(),
            port=self.port.value(),
            response_timeout_ms=float(self.timeout.value()),
            connect_timeout_ms=float(self.connect_timeout.value()),
        )


class ConfigDialog(QDialog):
    """Dialogue à deux volets ; ``protocol`` = "RTU" ou "TCP" (choisi dans le bandeau)."""

    def __init__(self, protocol: str, serial: SerialSettings, tcp: TcpSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Configuration de la liaison"))
        self.setModal(True)
        self.protocol = protocol
        self.serial_form = SerialForm(serial)
        self.tcp_form = TcpForm(tcp)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.serial_form)
        self.stack.addWidget(self.tcp_form)
        self.stack.setCurrentIndex(1 if protocol == "TCP" else 0)
        title = QLabel(tr("Liaison Modbus TCP") if protocol == "TCP" else "Liaison série (Modbus RTU)")
        title.setStyleSheet("font-weight: bold;")
        close_btn = QPushButton(tr("FERMER"))
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.stack)
        layout.addWidget(close_btn)

    def settings(self) -> LinkSettings:
        return self.tcp_form.settings() if self.protocol == "TCP" else self.serial_form.settings()

    def serial_settings(self) -> SerialSettings:
        return self.serial_form.settings()

    def tcp_settings(self) -> TcpSettings:
        return self.tcp_form.settings()
