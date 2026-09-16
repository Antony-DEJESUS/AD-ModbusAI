"""Onglet ESPION : écoute passive du bus, transactions appariées, trames brutes, stats par esclave."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modbusai.analysis.session import SessionStore
from modbusai.analysis.sniffer import BusCounters, FrameKind, SniffedFrame, Transaction, function_name
from modbusai.modbus.records import ExchangeStatus
from modbusai.transport.records import LinkSettings

MAX_ROWS = 3000
_STATUS_COLOR = {
    ExchangeStatus.OK: "#2ea043",
    ExchangeStatus.TIMEOUT: "#d29922",
    ExchangeStatus.CRC_ERROR: "#e5534b",
    ExchangeStatus.MODBUS_EXCEPTION: "#e5534b",
}
_KIND_COLOR = {FrameKind.INVALID: "#e5534b", FrameKind.UNKNOWN: "#d29922", FrameKind.BROADCAST: "#a371f7"}


def _item(text: str, color: str | None = None, center: bool = False) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        it.setForeground(QColor(color))
    if center:
        it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return it


class SnifferPage(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    status_message = Signal(str)

    def __init__(self, session: SessionStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._listening = False

        self.start_btn = QPushButton("DÉMARRER ÉCOUTE")
        self.stop_btn = QPushButton("ARRÊTER")
        self.stop_btn.setEnabled(False)
        self.clear_btn = QPushButton("EFFACER")
        self.autoscroll = QCheckBox("Défilement auto")
        self.autoscroll.setChecked(True)
        self.show_frames = QCheckBox("Trames brutes")
        self.show_frames.setChecked(False)
        self.counters_label = QLabel("Écoute arrêtée")
        self.hint = QLabel(
            "Écoute seule : l'outil n'émet jamais. Branché en parallèle du maître existant, "
            "il voit requêtes et réponses."
        )
        self.hint.setStyleSheet("color: #8b949e;")

        top = QHBoxLayout()
        top.addWidget(self.start_btn)
        top.addWidget(self.stop_btn)
        top.addWidget(self.clear_btn)
        top.addSpacing(12)
        top.addWidget(self.autoscroll)
        top.addWidget(self.show_frames)
        top.addStretch(1)
        top.addWidget(self.counters_label)

        self.transactions = QTableWidget(0, 8)
        self.transactions.setHorizontalHeaderLabels(
            ["Heure", "Esclave", "Fonction", "Détail", "Requête", "Réponse", "Temps (ms)", "Résultat"]
        )
        self._setup_table(self.transactions, stretch_col=5)

        self.frames = QTableWidget(0, 7)
        self.frames.setHorizontalHeaderLabels(
            ["Heure", "Type", "Esclave", "FC", "Détail", "Hexa", "Silence avant (ms)"]
        )
        self._setup_table(self.frames, stretch_col=5)
        self.frames.setVisible(False)

        self.stats = QTableWidget(0, 9)
        self.stats.setHorizontalHeaderLabels(
            [
                "Esclave",
                "Requêtes",
                "OK",
                "Exceptions",
                "Timeouts",
                "CRC",
                "Réussite",
                "Temps moyen (ms)",
                "Min / Max (ms)",
            ]
        )
        self._setup_table(self.stats, stretch_col=None)
        self.stats.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.transactions)
        splitter.addWidget(self.frames)
        splitter.addWidget(self.stats)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        splitter.setChildrenCollapsible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.hint)
        layout.addWidget(splitter, 1)

        self.start_btn.clicked.connect(self.start_requested)
        self.stop_btn.clicked.connect(self.stop_requested)
        self.clear_btn.clicked.connect(self.clear)
        self.show_frames.toggled.connect(self.frames.setVisible)

    @staticmethod
    def _setup_table(table: QTableWidget, stretch_col: int | None) -> None:
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        if stretch_col is not None:
            header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)

    # ================================================================ état
    @property
    def listening(self) -> bool:
        return self._listening

    def on_started(self, settings: LinkSettings) -> None:
        self._listening = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.counters_label.setText(f"Écoute sur {settings.summary()}")
        self.status_message.emit(f"Mode espion actif sur {settings.summary()} (écoute seule)")

    def on_stopped(self) -> None:
        self._listening = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.counters_label.setText(self.counters_label.text().replace("Écoute sur", "Écoute arrêtée -"))

    def set_available(self, available: bool, reason: str = "") -> None:
        """Faux quand le maître ou le serveur esclave occupe le port, ou en TCP."""
        self.start_btn.setEnabled(available and not self._listening)
        self.start_btn.setToolTip(reason)

    # ============================================================== données
    def on_frames(self, frames: list[SniffedFrame], counters: BusCounters) -> None:
        if self.show_frames.isChecked():
            for sf in frames:
                self._append_frame(sf)
        self.counters_label.setText(
            f"Trames {counters.frames}  |  requêtes {counters.requests}  |  réponses {counters.responses}  |  "
            f"exceptions {counters.exceptions}  |  invalides {counters.invalid}  |  esclaves vus : "
            + (", ".join(str(s) for s in sorted(counters.slaves_seen)) or "-")
        )

    def on_transactions(self, transactions: list[Transaction]) -> None:
        for tr in transactions:
            self._append_transaction(tr)
        self.refresh_stats()

    def _append_frame(self, sf: SniffedFrame) -> None:
        t = self.frames
        if t.rowCount() >= MAX_ROWS:
            t.removeRow(0)
        row = t.rowCount()
        t.insertRow(row)
        color = _KIND_COLOR.get(sf.kind)
        silence = "" if sf.frame.silence_before_ns is None else f"{sf.frame.silence_before_ns / 1e6:.1f}"
        cells = [
            sf.wall_time.strftime("%H:%M:%S.%f")[:-3],
            sf.kind.value,
            "" if sf.slave_id is None else str(sf.slave_id),
            "" if sf.function is None else f"{sf.function:02X}",
            sf.detail,
            sf.frame.hex,
            silence,
        ]
        for col, text in enumerate(cells):
            t.setItem(row, col, _item(text, color, center=col in (2, 3, 6)))
        if self.autoscroll.isChecked():
            t.scrollToBottom()

    def _append_transaction(self, tr: Transaction) -> None:
        t = self.transactions
        if t.rowCount() >= MAX_ROWS:
            t.removeRow(0)
        row = t.rowCount()
        t.insertRow(row)
        color = _STATUS_COLOR.get(tr.status)
        resp = tr.response
        status_text = {
            ExchangeStatus.OK: "OK",
            ExchangeStatus.TIMEOUT: "SANS RÉPONSE",
            ExchangeStatus.CRC_ERROR: "RÉPONSE CORROMPUE",
            ExchangeStatus.MODBUS_EXCEPTION: f"EXCEPTION {tr.exception_code:02X}"
            if tr.exception_code is not None
            else "EXCEPTION",
        }.get(tr.status, tr.status.name)
        cells = [
            tr.timestamp.strftime("%H:%M:%S.%f")[:-3],
            str(tr.slave_id),
            function_name(tr.function),
            tr.request.detail
            + (f" -> {resp.detail}" if resp is not None and resp.kind is not FrameKind.INVALID else ""),
            tr.request.frame.hex,
            resp.frame.hex if resp is not None else "-",
            f"{tr.response_time_ms:.1f}" if tr.response_time_ms is not None else "-",
            status_text,
        ]
        for col, text in enumerate(cells):
            t.setItem(row, col, _item(text, color if col == 7 else None, center=col in (1, 6)))
        if self.autoscroll.isChecked():
            t.scrollToBottom()

    def refresh_stats(self) -> None:
        stats = self.session.stats(sources=["espion"])
        self.stats.setRowCount(len(stats))
        for row, st in enumerate(sorted(stats.values(), key=lambda s: s.slave_id)):
            ok_color = "#2ea043" if st.ok_ratio >= 0.99 else ("#d29922" if st.ok_ratio >= 0.9 else "#e5534b")
            cells = [
                str(st.slave_id),
                str(st.total),
                str(st.ok),
                str(st.exception),
                str(st.timeout),
                str(st.crc_error),
                f"{100 * (st.ok + st.exception) / st.total:.1f} %" if st.total else "-",
                f"{st.rt_avg:.1f}" if st.rt_avg is not None else "-",
                f"{st.rt_min:.1f} / {st.rt_max:.1f}" if st.rt_min is not None else "-",
            ]
            for col, text in enumerate(cells):
                self.stats.setItem(row, col, _item(text, ok_color if col == 6 else None, center=True))

    def clear(self) -> None:
        self.transactions.setRowCount(0)
        self.frames.setRowCount(0)
        self.stats.setRowCount(0)
