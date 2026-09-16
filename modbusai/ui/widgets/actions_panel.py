"""Panneau gauche : LECTURE / ECRITURE, reconnexion auto, cyclique, options d'affichage."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modbusai.modbus.codec import DisplayMode, DisplayOptions, Radix


class ActionsPanel(QFrame):
    read_requested = Signal()
    write_requested = Signal()
    stop_cycle_requested = Signal()
    display_changed = Signal()  # inversion, signe, mode d'affichage

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(170)

        self.read_btn = QPushButton("LECTURE")
        self.write_btn = QPushButton("ECRITURE")
        for b in (self.read_btn, self.write_btn):
            b.setMinimumHeight(30)

        self.auto_reconnect = QCheckBox("Reconnexion auto")
        self.cyclic = QCheckBox("Cyclique")
        self.cycle_btn = QPushButton("…")
        self.cycle_btn.setFixedWidth(28)
        self.cycle_btn.setToolTip("Période du cycle (ms)")
        self.stop_cycle_btn = QPushButton("ARRET CYCLE")
        self.stop_cycle_btn.setEnabled(False)
        self.cycle_period_ms = 1000

        self.byte_swap = QCheckBox("Inversion Octets")
        self.word_swap = QCheckBox("Inversion Mots")
        self.unsigned = QCheckBox("Non signé")
        self.display_mode = QComboBox()
        for m in DisplayMode:
            self.display_mode.addItem(m.value, m)
        self.display_mode.setCurrentIndex(list(DisplayMode).index(DisplayMode.WORD16))
        self.order_label = QLabel()
        self.order_label.setStyleSheet("color: #555;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.read_btn)
        layout.addWidget(self.write_btn)
        layout.addWidget(_hsep())
        layout.addWidget(self.auto_reconnect)
        cyc = QHBoxLayout()
        cyc.addWidget(self.cyclic)
        cyc.addStretch(1)
        cyc.addWidget(self.cycle_btn)
        layout.addLayout(cyc)
        layout.addWidget(self.stop_cycle_btn)
        layout.addWidget(_hsep())
        layout.addWidget(self.byte_swap)
        layout.addWidget(self.word_swap)
        layout.addWidget(self.unsigned)
        layout.addSpacing(6)
        layout.addWidget(QLabel("Mode d'affichage"))
        layout.addWidget(self.display_mode)
        layout.addWidget(self.order_label)
        layout.addStretch(1)

        self.read_btn.clicked.connect(self.read_requested)
        self.write_btn.clicked.connect(self.write_requested)
        self.stop_cycle_btn.clicked.connect(self.stop_cycle_requested)
        self.cycle_btn.clicked.connect(self._ask_period)
        for w in (self.byte_swap, self.word_swap, self.unsigned):
            w.toggled.connect(self._on_display_changed)
        self.display_mode.currentIndexChanged.connect(self._on_display_changed)
        self._on_display_changed()

    # --------------------------------------------------------------- options
    def display_options(self, radix: Radix) -> DisplayOptions:
        return DisplayOptions(
            mode=self.display_mode.currentData(),
            radix=radix,
            signed=not self.unsigned.isChecked(),
            byte_swap=self.byte_swap.isChecked(),
            word_swap=self.word_swap.isChecked(),
        )

    def set_bits_mode(self, bits: bool) -> None:
        """En bobines / entrées TOR, les options de format n'ont pas de sens."""
        for w in (self.byte_swap, self.word_swap, self.unsigned, self.display_mode):
            w.setEnabled(not bits)
        if not bits:
            self._on_display_changed()

    def set_writable(self, writable: bool) -> None:
        self.write_btn.setEnabled(writable)

    def set_cycling(self, cycling: bool) -> None:
        self.stop_cycle_btn.setEnabled(cycling)
        self.read_btn.setEnabled(not cycling)

    def _on_display_changed(self) -> None:
        mode: DisplayMode = self.display_mode.currentData()
        self.word_swap.setEnabled(mode.is_32bit)
        opts = self.display_options(Radix.DEC)
        self.order_label.setText(f"Ordre 32 bits : {opts.word_order.name}" if mode.is_32bit else "")
        self.display_changed.emit()

    def _ask_period(self) -> None:
        value, ok = QInputDialog.getInt(self, "Cycle", "Période du cycle (ms) :", self.cycle_period_ms, 20, 600000, 100)
        if ok:
            self.cycle_period_ms = value


def _hsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
