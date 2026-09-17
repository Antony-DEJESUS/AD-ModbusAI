"""Bandeau supérieur : la liaison du MAÎTRE.

Le serveur esclave a la sienne, dans son onglet : les deux rôles peuvent
tourner en parallèle sur deux ports. Les libellés le disent (« MAÎTRE » à
gauche du bouton CONFIGURER) pour qu'on ne cherche pas ici le port du serveur."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from modbusai import APP_NAME, __version__
from modbusai.i18n import LANGUAGES, tr
from modbusai.transport.records import LinkSettings
from modbusai.ui.iconography import set_icon
from modbusai.ui.palette import State, color
from modbusai.ui.resources import logo_pixmap


class ConnectionBar(QFrame):
    configure_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()
    about_requested = Signal()
    quit_requested = Signal()
    theme_toggled = Signal()
    protocol_changed = Signal(str)  # "RTU" ou "TCP"
    language_changed = Signal(str)  # "fr" ou "en"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")

        self.logo = QLabel()
        self.app_name = QLabel(APP_NAME)
        self.app_name.setObjectName("appName")
        self.app_tag = QLabel(f"{tr('DIAGNOSTIC MODBUS')}  ·  v{__version__}")
        self.app_tag.setObjectName("appTag")
        self.state_dot = QLabel("●")
        self.role_label = QLabel(tr("MAÎTRE"))
        self.role_label.setObjectName("appTag")
        self.role_label.setToolTip(
            tr("Ce bandeau ne règle que la liaison du maître ; le serveur esclave a la sienne, dans son onglet.")
        )
        self.config_btn = QPushButton(tr("CONFIGURER"))
        self.config_btn.setToolTip(tr("Port et paramètres de la liaison du maître"))
        set_icon(self.config_btn, "settings")
        self.protocol = QComboBox()
        self.protocol.addItem(tr("RTU"))
        self.protocol.addItem(tr("TCP"))
        self.protocol.setToolTip(tr("RTU : liaison série RS-485 / RS-232. TCP : Modbus TCP sur réseau IP."))
        self.summary = QLabel(tr("Aucun port"))
        self.summary.setObjectName("linkSummary")
        self.connect_btn = QPushButton(tr("CONNECTER"))
        self.connect_btn.setToolTip(tr("Ouvre la liaison du maître"))
        set_icon(self.connect_btn, "plug", on_accent=True)
        self.connect_btn.setProperty("variant", "primary")
        self.disconnect_btn = QPushButton(tr("DÉCONNECTER"))
        self.disconnect_btn.setEnabled(False)
        self._connected = False
        self.language = QComboBox()
        for code, label in LANGUAGES.items():
            self.language.addItem(label, code)
        self.language.setToolTip(tr("Langue"))
        self.theme_btn = QPushButton(tr("THÈME"))
        self.theme_btn.setToolTip(tr("Basculer clair / sombre"))
        set_icon(self.theme_btn, "theme")
        self.about_btn = QPushButton(tr("À PROPOS"))
        self.about_btn.setToolTip(tr("Logo, version, historique et mode d'emploi"))
        set_icon(self.about_btn, "info")
        self.quit_btn = QPushButton(tr("QUITTER"))
        self.quit_btn.setProperty("variant", "quiet")
        set_icon(self.quit_btn, "power")

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(0)
        identity.addWidget(self.app_name)
        identity.addWidget(self.app_tag)

        link = QHBoxLayout()
        link.setContentsMargins(0, 0, 0, 0)
        link.setSpacing(6)
        link.addWidget(self.state_dot)
        link.addWidget(self.summary)
        link_w = QWidget()
        link_w.setLayout(link)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(self.logo)
        layout.addLayout(identity)
        layout.addSpacing(6)
        layout.addWidget(_vsep())
        layout.addSpacing(6)
        layout.addWidget(self.role_label)
        layout.addWidget(self.config_btn)
        layout.addWidget(self.protocol)
        layout.addWidget(link_w)
        layout.addSpacing(6)
        layout.addWidget(self.connect_btn)
        layout.addWidget(self.disconnect_btn)
        layout.addStretch(1)
        layout.addWidget(self.language)
        layout.addWidget(self.theme_btn)
        layout.addWidget(self.about_btn)
        layout.addWidget(self.quit_btn)

        self.config_btn.clicked.connect(self.configure_requested)
        self.connect_btn.clicked.connect(self.connect_requested)
        self.disconnect_btn.clicked.connect(self.disconnect_requested)
        self.about_btn.clicked.connect(self.about_requested)
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
        self.logo.setPixmap(logo_pixmap(30, dark=(name == "sombre")))
        self._paint_state()

    def set_connected(self, connected: bool) -> None:
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.config_btn.setEnabled(not connected)
        self.protocol.setEnabled(not connected)
        self._connected = connected
        self._paint_state()

    def _paint_state(self) -> None:
        """Pastille de liaison : verte connectée, grise au repos (jamais de noir
        ni de blanc en dur, les deux thèmes doivent rester lisibles)."""
        tint = color(State.OK if self._connected else State.MUTED)
        self.state_dot.setStyleSheet(f"color: {tint}; font-size: 13pt;")
        self.summary.setStyleSheet(f"color: {tint if self._connected else 'palette(text)'};")


def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
