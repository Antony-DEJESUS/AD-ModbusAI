"""Bandeau supérieur : CONFIGURATION, protocole, résumé du port, CONNEXION / DECONNEXION, QUITTER."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from modbusai.transport.records import SerialSettings


class ConnectionBar(QFrame):
    configure_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.config_btn = QPushButton("CONFIGURATION")
        self.protocol = QComboBox()
        self.protocol.addItem("RTU")
        self.protocol.setToolTip("Seul le mode RTU est disponible en phase 1")
        self.protocol.setEnabled(False)
        self.summary = QLabel("Aucun port")
        self.summary.setStyleSheet("font-weight: bold;")
        self.connect_btn = QPushButton("CONNEXION")
        self.disconnect_btn = QPushButton("DECONNEXION")
        self.disconnect_btn.setEnabled(False)
        self.quit_btn = QPushButton("QUITTER")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self.config_btn)
        layout.addWidget(self.protocol)
        layout.addWidget(self.summary)
        layout.addWidget(_vsep())
        layout.addWidget(self.connect_btn)
        layout.addWidget(self.disconnect_btn)
        layout.addStretch(1)
        layout.addWidget(self.quit_btn)

        self.config_btn.clicked.connect(self.configure_requested)
        self.connect_btn.clicked.connect(self.connect_requested)
        self.disconnect_btn.clicked.connect(self.disconnect_requested)
        self.quit_btn.clicked.connect(self.quit_requested)

    def show_settings(self, settings: SerialSettings) -> None:
        self.summary.setText(settings.summary() if settings.port else "Aucun port")

    def set_connected(self, connected: bool) -> None:
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.config_btn.setEnabled(not connected)
        # Couleur du thème quand déconnecté (thème sombre Windows compris), vert quand connecté
        self.summary.setStyleSheet("font-weight: bold; color: #2ea043;" if connected else "font-weight: bold;")


def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
