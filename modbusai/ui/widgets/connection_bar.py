"""Bandeau supérieur : CONFIGURATION, protocole, résumé du port, CONNEXION / DECONNEXION, QUITTER."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from modbusai.i18n import LANGUAGES, tr
from modbusai.transport.records import LinkSettings
from modbusai.ui.resources import logo_pixmap


class ConnectionBar(QFrame):
    configure_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()
    quit_requested = Signal()
    theme_toggled = Signal()
    protocol_changed = Signal(str)  # "RTU" ou "TCP"
    language_changed = Signal(str)  # "fr" ou "en"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.logo = QLabel()
        self.logo.setToolTip("AD Automation")
        self.config_btn = QPushButton(tr("CONFIGURATION"))
        self.protocol = QComboBox()
        self.protocol.addItem(tr("RTU"))
        self.protocol.addItem(tr("TCP"))
        self.protocol.setToolTip(tr("RTU : liaison série RS-485 / RS-232. TCP : Modbus TCP sur réseau IP."))
        self.summary = QLabel(tr("Aucun port"))
        self.summary.setStyleSheet("font-weight: bold;")
        self.connect_btn = QPushButton(tr("CONNEXION"))
        self.disconnect_btn = QPushButton(tr("DECONNEXION"))
        self.disconnect_btn.setEnabled(False)
        self.language = QComboBox()
        for code, label in LANGUAGES.items():
            self.language.addItem(label, code)
        self.language.setToolTip(tr("Langue"))
        self.theme_btn = QPushButton(tr("THÈME"))
        self.theme_btn.setToolTip(tr("Basculer clair / sombre"))
        self.quit_btn = QPushButton(tr("QUITTER"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self.logo)
        layout.addWidget(self.config_btn)
        layout.addWidget(self.protocol)
        layout.addWidget(self.summary)
        layout.addWidget(_vsep())
        layout.addWidget(self.connect_btn)
        layout.addWidget(self.disconnect_btn)
        layout.addStretch(1)
        layout.addWidget(self.language)
        layout.addWidget(self.theme_btn)
        layout.addWidget(self.quit_btn)

        self.config_btn.clicked.connect(self.configure_requested)
        self.connect_btn.clicked.connect(self.connect_requested)
        self.disconnect_btn.clicked.connect(self.disconnect_requested)
        self.quit_btn.clicked.connect(self.quit_requested)
        self.theme_btn.clicked.connect(self.theme_toggled)
        self.protocol.currentTextChanged.connect(self.protocol_changed)
        self.language.currentIndexChanged.connect(lambda _i: self.language_changed.emit(self.language.currentData()))

    def show_settings(self, settings: LinkSettings) -> None:
        self.summary.setText(settings.summary())

    def set_language(self, code: str) -> None:
        idx = self.language.findData(code)
        if idx >= 0 and idx != self.language.currentIndex():
            self.language.blockSignals(True)
            self.language.setCurrentIndex(idx)
            self.language.blockSignals(False)

    def set_protocol(self, name: str) -> None:
        idx = self.protocol.findText(name)
        if idx >= 0 and idx != self.protocol.currentIndex():
            self.protocol.blockSignals(True)
            self.protocol.setCurrentIndex(idx)
            self.protocol.blockSignals(False)

    @property
    def current_protocol(self) -> str:
        return self.protocol.currentText()

    def set_theme(self, name: str) -> None:
        self.theme_btn.setText(tr("THÈME : SOMBRE") if name == "sombre" else tr("THÈME : CLAIR"))
        self.logo.setPixmap(logo_pixmap(28, dark=(name == "sombre")))

    def set_connected(self, connected: bool) -> None:
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.config_btn.setEnabled(not connected)
        self.protocol.setEnabled(not connected)
        # Couleur du thème quand déconnecté (thème sombre Windows compris), vert quand connecté
        self.summary.setStyleSheet("font-weight: bold; color: #2ea043;" if connected else "font-weight: bold;")


def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
