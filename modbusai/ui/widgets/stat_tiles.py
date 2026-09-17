"""Rangée de compteurs : un nombre lisible, un libellé discret.

Une ligne de texte du genre « Requêtes 2 | réponses 2 | exceptions 0 | … » ne
se lit pas en diagonale. Ici chaque compteur est une tuile : valeur en chiffres
tabulaires, libellé en petites capitales, et couleur seulement quand la valeur
sort de l'ordinaire (une exception, une trame perdue).
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from modbusai.i18n import tr
from modbusai.ui.metrics import use_tabular_figures
from modbusai.ui.palette import State, color


class StatTiles(QWidget):
    def __init__(self, keys: tuple[tuple[str, str, State | None], ...], parent: QWidget | None = None) -> None:
        """``keys`` : (identifiant, libellé, état quand la valeur n'est pas nulle)."""
        super().__init__(parent)
        self._values: dict[str, QLabel] = {}
        self._states: dict[str, State | None] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for key, label, state in keys:
            value = QLabel("0")
            value.setStyleSheet("font-size: 12pt; font-weight: 700;")
            use_tabular_figures(value)
            caption = QLabel(tr(label))
            caption.setProperty("variant", "muted")
            caption.setStyleSheet("font-size: 8pt; letter-spacing: 0.6px;")
            tile = QVBoxLayout()
            tile.setContentsMargins(0, 0, 0, 0)
            tile.setSpacing(0)
            tile.addWidget(value)
            tile.addWidget(caption)
            holder = QWidget()
            holder.setLayout(tile)
            layout.addWidget(holder)
            self._values[key] = value
            self._states[key] = state
        layout.addStretch(1)

    def set_values(self, values: dict[str, int]) -> None:
        for key, label in self._values.items():
            count = values.get(key, 0)
            label.setText(str(count))
            state = self._states[key]
            tint = color(state) if (state is not None and count) else "palette(text)"
            label.setStyleSheet(f"font-size: 12pt; font-weight: 700; color: {tint};")

    def reset(self) -> None:
        self.set_values({})
