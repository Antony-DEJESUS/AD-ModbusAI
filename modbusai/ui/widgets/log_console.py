"""Console de log : une ligne par échange, en colonnes fixes.

Les colonnes sont alignées parce qu'on lit une console en balayant une colonne,
pas en lisant des phrases : l'heure, le numéro, l'esclave, la fonction, le
statut et le temps occupent toujours la même place, et les trames — seules de
longueur variable — viennent en dernier. Un en-tête discret les nomme.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modbusai.i18n import tr
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus
from modbusai.ui.iconography import set_icon
from modbusai.ui.metrics import mono_font
from modbusai.ui.palette import State, color
from modbusai.ui.widgets.labels import section

_STATUS_STYLE = {
    ExchangeStatus.OK: ("OK", State.OK),
    ExchangeStatus.TIMEOUT: ("TIMEOUT", State.WARN),
    ExchangeStatus.CRC_ERROR: ("ERREUR CRC", State.ERROR),
    ExchangeStatus.MODBUS_EXCEPTION: ("EXCEPTION", State.ERROR),
    ExchangeStatus.BAD_RESPONSE: ("REPONSE INCOHERENTE", State.ERROR),
    ExchangeStatus.TRANSPORT_ERROR: ("ERREUR LIAISON", State.SPECIAL),
}


# Largeurs des colonnes, en caractères (police à chasse fixe). La dernière,
# de longueur variable, vient toujours en fin de ligne.
MASTER_COLUMNS = (
    ("Heure", 12),
    ("N°", 6),
    ("Esc", 4),
    ("FC", 4),
    ("Statut", 12),
    ("ms", 8),
    ("Trames", 0),
)
SLAVE_COLUMNS = (
    ("Heure", 12),
    ("Maître", 21),
    ("Esc", 4),
    ("FC", 4),
    ("Traitement", 12),
    ("Trames", 0),
)
Columns = tuple[tuple[str, int], ...]
_SEP = "  "


def header_line(columns: Columns = MASTER_COLUMNS) -> str:
    """En-tête, dans les mêmes largeurs que les lignes."""
    return _SEP.join(title.ljust(width) if width else title for title, width in columns)


def _cells(columns: Columns, *values: str) -> str:
    widths = [width for _title, width in columns]
    return _SEP.join(value.ljust(width) if width else value for value, width in zip(values, widths, strict=False))


class LogConsole(QPlainTextEdit):
    def __init__(self, columns: Columns = MASTER_COLUMNS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.columns = columns
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setObjectName("logConsole")  # la feuille de style lui donne la chasse fixe
        self.setFont(mono_font())
        self.setPlaceholderText(tr("Console : horodatage, trame émise, trame reçue, temps de réponse, erreur"))

    def log_record(self, rec: ExchangeRecord) -> None:
        label, state = _STATUS_STYLE[rec.status]
        self.log_cells(
            (
                rec.timestamp.strftime("%H:%M:%S.%f")[:-3],
                f"#{rec.seq}",
                str(rec.slave_id),
                f"{int(rec.function):02d}",
                tr(label),
                f"{rec.response_time_ms:.1f}" if rec.response_time_ms is not None else "-",
                f"TX {rec.tx_frame.hex}  RX {rec.rx_frame.hex if rec.rx_frame is not None else '-'}",
            ),
            state=state,
            highlight=4,
            detail=rec.error_message or "",
        )

    def log_cells(
        self, values: Sequence[str], state: State | None = None, highlight: int = -1, detail: str = ""
    ) -> None:
        """Une ligne alignée sur les colonnes. ``highlight`` : indice de la colonne
        colorée selon ``state`` (le statut), sans casser l'alignement."""
        tint = color(state) if state is not None else ""
        parts: list[str] = []
        for index, (value, (_title, width)) in enumerate(zip(values, self.columns, strict=False)):
            cell = escape(value.ljust(width) if width else value)
            if index == highlight and tint:
                parts.append(f'<span style="white-space:pre;color:{tint};font-weight:700">{cell}</span>')
            else:
                parts.append(f'<span style="white-space:pre">{cell}</span>')
        line = f'<span style="white-space:pre">{_SEP}</span>'.join(parts)
        if detail:
            line += f'<span style="color:{tint or color(State.MUTED)}">{_SEP}{escape(detail)}</span>'
        self.appendHtml(line)

    def log_info(self, text: str) -> None:
        self.appendHtml(f'<span style="color:{color(State.MUTED)}">{escape(text)}</span>')

    def log_error(self, text: str) -> None:
        self.appendHtml(f'<span style="color:{color(State.ERROR)}">{escape(text)}</span>')


class LogPanel(QWidget):
    """Console de log avec son bandeau : titre, COPIER (presse-papiers), EFFACER JOURNAL."""

    copied = Signal(int)  # nombre de lignes copiées

    def __init__(self, columns: Columns = MASTER_COLUMNS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.console = LogConsole(columns)
        self.copy_btn = QPushButton(tr("COPIER"))
        self.copy_btn.setToolTip(tr("Copier tout le journal dans le presse-papiers"))
        self.clear_btn = QPushButton(tr("EFFACER JOURNAL"))
        set_icon(self.copy_btn, "copy")
        set_icon(self.clear_btn, "trash")
        self.clear_btn.setToolTip(tr("Vider la console (la grille et le dernier échange sont conservés)"))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(section(tr("Journal")))
        header.addStretch(1)
        header.addWidget(self.copy_btn)
        header.addWidget(self.clear_btn)

        # Nom des colonnes : même police que la console (pas de feuille de style
        # locale ici, elle reprendrait la police globale et casserait l'alignement)
        self.columns = QLabel(header_line(columns))
        self.columns.setObjectName("logColumns")  # même police que la console
        columns_row = QHBoxLayout()
        columns_row.setContentsMargins(9, 0, 0, 0)
        columns_row.addWidget(self.columns)
        columns_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addLayout(columns_row)
        layout.addWidget(self.console, 1)

        self.copy_btn.clicked.connect(self._copy_all)
        self.clear_btn.clicked.connect(self.console.clear)

    def _copy_all(self) -> None:
        text = self.console.toPlainText()
        QApplication.clipboard().setText(text)
        self.copied.emit(len(text.splitlines()) if text else 0)
