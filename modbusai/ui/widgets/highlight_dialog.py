"""Configuration des surlignages : activer, changer la couleur, régler la durée.

Une ligne par fait signalé. Le bouton de couleur montre la teinte courante ;
« Rétablir la charte » rend la main aux couleurs AD, qui restent la référence.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modbusai.i18n import tr
from modbusai.ui import highlights
from modbusai.ui.highlights import Highlight, HighlightSpec
from modbusai.ui.iconography import set_icon
from modbusai.ui.metrics import text_width
from modbusai.ui.widgets.labels import muted, section


class ColorButton(QPushButton):
    """Pastille cliquable : affiche la teinte, ouvre le sélecteur du système."""

    picked = Signal(object)  # QColor, ou None pour revenir à la charte

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(text_width(self, "Couleur", extra=36))
        self._color = QColor()
        self.clicked.connect(self._choose)

    def show_color(self, value: QColor, custom: bool) -> None:
        self._color = QColor(value)
        self.setText(tr("Couleur") if custom else tr("Charte"))
        # La teinte vient des réglages, pas d'une constante : la règle « aucune
        # couleur écrite dans un widget » reste tenue.
        self.setStyleSheet(
            f"background: {value.name()}; color: {_readable_on(value).name()};"
            " border-radius: 4px; padding: 2px 8px; font-weight: 600;"
        )

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, tr("Couleur du surlignage"))
        if chosen.isValid():
            self.picked.emit(chosen)


def _readable_on(background: QColor) -> QColor:
    """Noir ou blanc, selon ce qui se lit sur ce fond (luminance perçue)."""
    luminance = 0.299 * background.redF() + 0.587 * background.greenF() + 0.114 * background.blueF()
    return QColor(0, 0, 0) if luminance > 0.55 else QColor(255, 255, 255)


class HighlightDialog(QDialog):
    """Une ligne par surlignage ; les changements s'appliquent immédiatement."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Couleurs des surlignages"))
        self.setModal(True)
        self._rows: dict[Highlight, tuple[QCheckBox, ColorButton, QDoubleSpinBox | None]] = {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        headers = (tr("Actif"), tr("Signal"), tr("Couleur"), tr("Durée"))
        for column, title in enumerate(headers):
            grid.addWidget(section(title), 0, column)

        for row, entry in enumerate(highlights.catalogue(), start=1):
            self._add_row(grid, row, entry)

        reset_btn = QPushButton(tr("Rétablir la charte"))
        set_icon(reset_btn, "refresh")
        reset_btn.clicked.connect(self._reset_all)
        close_btn = QPushButton(tr("Fermer"))
        close_btn.setProperty("variant", "primary")
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        intro = tr("Un surlignage désigne un fait, pas une couleur : coupez-le ou changez sa teinte.")
        layout.addWidget(muted(intro))
        layout.addLayout(grid)
        layout.addSpacing(8)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ lignes
    def _add_row(self, grid: QGridLayout, row: int, entry: HighlightSpec) -> None:
        active = QCheckBox()
        active.toggled.connect(lambda on, key=entry.key: self._on_enabled(key, on))

        title = QLabel(entry.label)
        title.setToolTip(entry.description)

        swatch = ColorButton()
        swatch.picked.connect(lambda value, key=entry.key: self._on_color(key, value))

        duration: QDoubleSpinBox | None = None
        if entry.animated:
            duration = QDoubleSpinBox()
            duration.setRange(0.5, 60.0)
            duration.setSingleStep(0.5)
            duration.setDecimals(1)
            duration.setSuffix(tr(" s"))
            duration.valueChanged.connect(lambda value, key=entry.key: self._on_seconds(key, value))

        grid.addWidget(active, row, 0)
        grid.addWidget(title, row, 1)
        grid.addWidget(swatch, row, 2)
        grid.addWidget(duration or muted(tr("permanent")), row, 3)
        self._rows[entry.key] = (active, swatch, duration)
        self._load(entry.key)

    def _load(self, key: Highlight) -> None:
        active, swatch, duration = self._rows[key]
        for widget in (active, swatch, duration):
            if widget is not None:
                widget.blockSignals(True)
        active.setChecked(highlights.enabled(key))
        swatch.show_color(highlights.base_color(key), highlights.is_custom(key))
        swatch.setEnabled(active.isChecked())
        if duration is not None:
            duration.setValue(highlights.seconds(key))
            duration.setEnabled(active.isChecked())
        for widget in (active, swatch, duration):
            if widget is not None:
                widget.blockSignals(False)

    # ------------------------------------------------------------- changements
    def _on_enabled(self, key: Highlight, value: bool) -> None:
        highlights.set_enabled(key, value)
        self._load(key)
        self.changed.emit()

    def _on_color(self, key: Highlight, value: QColor | None) -> None:
        highlights.set_color(key, value)
        self._load(key)
        self.changed.emit()

    def _on_seconds(self, key: Highlight, value: float) -> None:
        highlights.set_seconds(key, value)
        self.changed.emit()

    def _reset_all(self) -> None:
        highlights.reset_all()
        for key in self._rows:
            self._load(key)
        self.changed.emit()
