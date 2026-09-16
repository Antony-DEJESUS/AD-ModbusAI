"""Grille N° Registre / Valeur. Les valeurs sont éditables pour préparer une écriture."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from modbusai.modbus.codec import DisplayRow


class RegisterGrid(QTableWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["N° Registre", "Valeur"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.setAlternatingRowColors(True)
        self.setMinimumWidth(220)

    def show_rows(self, rows: Sequence[DisplayRow]) -> None:
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            label = QTableWidgetItem(row.label)
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            label.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QTableWidgetItem(row.text)
            value.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(i, 0, label)
            self.setItem(i, 1, value)

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
                item.setForeground(Qt.GlobalColor.gray)
            else:
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
