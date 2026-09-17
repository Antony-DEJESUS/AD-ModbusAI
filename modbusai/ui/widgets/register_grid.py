"""Grille N° Registre / Valeur. Les valeurs sont éditables pour préparer une écriture."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from modbusai.i18n import tr
from modbusai.modbus.codec import DisplayRow
from modbusai.ui.metrics import text_width, use_tabular_figures
from modbusai.ui.palette import State, color


class RegisterGrid(QTableWidget):
    """Registre, valeur (éditable), et les mêmes bits en hexadécimal et en binaire.

    Une seule colonne « Valeur » étirée sur toute la largeur gaspillait l'espace
    et obligeait à rebasculer le format pour lire un mot d'état. Les colonnes
    annexes sont remplies quand la page fournit les registres bruts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels([tr("N° Registre"), tr("Valeur"), tr("Hexa"), tr("Binaire")])
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.setMinimumWidth(text_width(self, "400001   -32768", extra=48))
        use_tabular_figures(self)

    def show_rows(self, rows: Sequence[DisplayRow], extras: Sequence[tuple[str, str]] = ()) -> None:
        """``extras`` : (hexadécimal, binaire) par ligne ; vide = colonnes laissées vides."""
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            label = QTableWidgetItem(row.label)
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            label.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QTableWidgetItem(row.text)
            value.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(i, 0, label)
            self.setItem(i, 1, value)
            hexa, binary = extras[i] if i < len(extras) else ("", "")
            for col, text in ((2, hexa), (3, binary)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor(color(State.MUTED)))
                self.setItem(i, col, item)

    def value_texts(self) -> list[str]:
        out = []
        for i in range(self.rowCount()):
            item = self.item(i, 1)
            out.append(item.text() if item is not None else "")
        return out

    def mark_stale(self, stale: bool) -> None:
        """Grise les valeurs quand elles ne reflètent plus une lecture réussie.
        Sinon, retour à la couleur du thème (lisible en clair comme en sombre)."""
        for i in range(self.rowCount()):
            item = self.item(i, 1)
            if item is None:
                continue
            if stale:
                item.setForeground(QColor(color(State.MUTED)))
            else:
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
