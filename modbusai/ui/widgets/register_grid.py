"""Grille N° Registre / Valeur. Les valeurs sont éditables pour préparer une écriture."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from modbusai.i18n import tr
from modbusai.modbus.codec import DisplayRow
from modbusai.ui import highlights
from modbusai.ui.highlights import Highlight
from modbusai.ui.metrics import text_width, use_tabular_figures
from modbusai.ui.palette import State, color

_FLASH_TICK_MS = 80


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
        self.hide_zeros = False
        self._zeros: list[bool] = []  # une valeur nulle par ligne affichée
        self._flash_until: dict[int, float] = {}  # ligne -> instant de fin d'éclairage
        self._span = highlights.seconds(Highlight.MASTER_CHANGE)
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._tick_flashes)

    # ------------------------------------------------------------ animation
    def flash(self, rows: Iterable[int]) -> None:
        """Éclaire les lignes dont la valeur vient de changer, si l'utilisateur
        n'a pas coupé ce surlignage."""
        if not highlights.enabled(Highlight.MASTER_CHANGE):
            return
        self._span = highlights.seconds(Highlight.MASTER_CHANGE)
        end = time.monotonic() + self._span
        for row in rows:
            self._flash_until[row] = end
        if self._flash_until and not self._flash_timer.isActive():
            self._flash_timer.start(_FLASH_TICK_MS)
        self._paint_flashes()

    def refresh_highlights(self) -> None:
        """Les réglages ont changé : reprendre la durée et repeindre. Un
        surlignage coupé éteint ce qui restait allumé."""
        self._span = highlights.seconds(Highlight.MASTER_CHANGE)
        if not highlights.enabled(Highlight.MASTER_CHANGE):
            self.clear_flashes()
            return
        self._paint_flashes()

    def clear_flashes(self) -> None:
        """La requête a changé : les lignes ne désignent plus les mêmes registres."""
        self._flash_until.clear()
        self._flash_timer.stop()
        self._paint_flashes()

    def _tick_flashes(self) -> None:
        now = time.monotonic()
        for row in [r for r, end in self._flash_until.items() if end <= now]:
            del self._flash_until[row]
        self._paint_flashes()
        if not self._flash_until:
            self._flash_timer.stop()

    def _paint_flashes(self) -> None:
        now = time.monotonic()
        for row in range(self.rowCount()):
            end = self._flash_until.get(row)
            tint = None
            if end is not None and end > now and self._span > 0:
                tint = highlights.tint(Highlight.MASTER_CHANGE, (end - now) / self._span)
            for col in range(self.columnCount()):
                item = self.item(row, col)
                if item is not None:
                    item.setData(Qt.ItemDataRole.BackgroundRole, tint)

    # ------------------------------------------------------ valeurs nulles
    def set_hide_zeros(self, hide: bool) -> None:
        self.hide_zeros = hide
        self._apply_zero_filter()

    def _apply_zero_filter(self) -> None:
        """Masque les lignes nulles SANS les retirer : l'écriture relit toutes
        les lignes de la grille, en supprimer décalerait les valeurs envoyées."""
        for row in range(self.rowCount()):
            zero = self._zeros[row] if row < len(self._zeros) else False
            self.setRowHidden(row, self.hide_zeros and zero)

    def show_rows(
        self,
        rows: Sequence[DisplayRow],
        extras: Sequence[tuple[str, str]] = (),
        zeros: Sequence[bool] = (),
    ) -> None:
        """``extras`` : (hexadécimal, binaire) par ligne ; vide = colonnes laissées vides.
        ``zeros`` : lignes dont tous les registres couverts valent zéro."""
        self._zeros = list(zeros)
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
        # Les cellules viennent d'être recréées : le filtre et l'éclairage en
        # cours doivent être réappliqués, sinon ils disparaissent à chaque lecture.
        self._apply_zero_filter()
        self._paint_flashes()

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
            faded = highlights.foreground(Highlight.MASTER_STALE) if stale else None
            if faded is not None:
                item.setForeground(faded)
            else:
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
