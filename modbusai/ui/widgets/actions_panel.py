"""Panneau gauche : LECTURE / ECRITURE, reconnexion auto, cyclique, options d'affichage."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modbusai.i18n import tr
from modbusai.modbus.codec import DisplayMode, DisplayOptions, Radix
from modbusai.ui.metrics import text_width
from modbusai.ui.widgets.labels import section


class ActionsPanel(QFrame):
    read_requested = Signal()
    write_requested = Signal()
    stop_cycle_requested = Signal()
    display_changed = Signal()  # inversion, signe, mode d'affichage

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")  # carte de la charte (ui/style.py)
        # Largeur tirée des plus longs libellés du panneau : tient à 125 % comme
        # à 150 % d'échelle, où une valeur en pixels ferait tronquer les textes.
        self.setFixedWidth(text_width(self, "Reconnexion auto", "Période : 1000 ms", "Inversion Octets", extra=52))

        self.read_btn = QPushButton(tr("LECTURE"))
        self.read_btn.setProperty("variant", "primary")
        self.write_btn = QPushButton(tr("ECRITURE"))
        for b in (self.read_btn, self.write_btn):
            b.setMinimumHeight(30)

        self.auto_reconnect = QCheckBox(tr("Reconnexion auto"))
        self.cyclic = QCheckBox(tr("Cyclique"))
        self.cycle_btn = QPushButton()
        self.cycle_btn.setProperty("variant", "quiet")
        self.cycle_btn.setToolTip(tr("Période du cycle (ms)"))
        self.stop_cycle_btn = QPushButton(tr("ARRET CYCLE"))
        self.stop_cycle_btn.setEnabled(False)
        self.cycle_period_ms = 1000
        self.cycle_btn.setText(tr("Période : {p0} ms").format(p0=self.cycle_period_ms))

        self.byte_swap = QCheckBox(tr("Inversion Octets"))
        self.word_swap = QCheckBox(tr("Inversion Mots"))
        self.unsigned = QCheckBox(tr("Non signé"))
        self.display_mode = QComboBox()
        for m in DisplayMode:
            self.display_mode.addItem(tr(m.value), m)
        self.display_mode.setCurrentIndex(list(DisplayMode).index(DisplayMode.WORD16))
        self.order_label = QLabel()
        self.order_label.setProperty("variant", "muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.read_btn)
        layout.addWidget(self.write_btn)
        layout.addWidget(_hsep())
        layout.addWidget(self.auto_reconnect)
        layout.addWidget(self.cyclic)
        layout.addWidget(self.cycle_btn)
        layout.addWidget(self.stop_cycle_btn)
        layout.addWidget(_hsep())
        layout.addWidget(self.byte_swap)
        layout.addWidget(self.word_swap)
        layout.addWidget(self.unsigned)
        layout.addSpacing(6)
        layout.addWidget(section(tr("Mode d'affichage")))
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
        self.word_swap.setEnabled(mode.is_multiword)
        opts = self.display_options(Radix.DEC)
        self.order_label.setText(
            tr("Ordre {p0} bits : {p1}").format(p0=16 * mode.words, p1=opts.order_label) if mode.is_multiword else ""
        )
        self.display_changed.emit()

    def _ask_period(self) -> None:
        value, ok = QInputDialog.getInt(
            self, tr("Cycle"), tr("Période du cycle (ms) :"), self.cycle_period_ms, 20, 600000, 100
        )
        if ok:
            self.cycle_period_ms = value
            self._show_period()

    def _show_period(self) -> None:
        """La période est lisible sur le bouton : un bouton vide n'apprend rien."""
        self.cycle_btn.setText(tr("Période : {p0} ms").format(p0=self.cycle_period_ms))
        self._fit_width()

    def showEvent(self, event) -> None:  # noqa: N802 (API Qt)
        super().showEvent(event)
        self._fit_width()

    def _fit_width(self) -> None:
        if not hasattr(self, "display_mode"):  # appelé avant la fin de la construction
            return
        """Largeur calée sur le plus large des contrôles, police et feuille de
        style comprises : rien à réajuster à 125 ou 150 % d'échelle Windows."""
        widest = max(
            w.sizeHint().width()
            for w in (
                self.read_btn,
                self.write_btn,
                self.cycle_btn,
                self.stop_cycle_btn,
                self.auto_reconnect,
                self.cyclic,
                self.byte_swap,
                self.word_swap,
                self.unsigned,
                self.display_mode,
            )
        )
        margins = self.layout().contentsMargins()
        self.setFixedWidth(widest + margins.left() + margins.right() + 4)


def _hsep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep
