"""Onglet DIAGNOSTIC : statistiques par esclave, hypothèses classées, tests pour les départager."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modbusai.analysis.diagnostic import CampaignComparison, Hypothesis, SuggestedTest, analyse
from modbusai.analysis.observations import SlaveStats
from modbusai.analysis.session import SessionStore
from modbusai.transport.records import SerialSettings

SOURCES = (
    ("Toutes les sources", None),
    ("Maître", ["maitre"]),
    ("Espion", ["espion"]),
    ("Scan", ["scan"]),
    ("Tests", ["test"]),
)


def _score_color(score: int) -> str:
    if score >= 75:
        return "#e5534b"
    if score >= 50:
        return "#d29922"
    return "#2ea043"


class DiagnosticPage(QWidget):
    run_test_requested = Signal(object, object)  # SuggestedTest, Hypothesis
    cancel_test_requested = Signal()
    status_message = Signal(str)

    def __init__(self, session: SessionStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._settings: SerialSettings | None = None
        self._hypotheses: list[Hypothesis] = []
        self._stats: dict[int, SlaveStats] = {}
        self._test_running = False
        self._can_run = False

        self.analyse_btn = QPushButton("ANALYSER")
        self.clear_btn = QPushButton("EFFACER HISTORIQUE")
        self.sources = QComboBox()
        for label, value in SOURCES:
            self.sources.addItem(label, value)
        self.count_label = QLabel("0 observation")

        top = QHBoxLayout()
        top.addWidget(self.analyse_btn)
        top.addWidget(self.clear_btn)
        top.addSpacing(12)
        top.addWidget(QLabel("Sources"))
        top.addWidget(self.sources)
        top.addStretch(1)
        top.addWidget(self.count_label)

        self.stats_table = QTableWidget(0, 12)
        self.stats_table.setHorizontalHeaderLabels(
            [
                "Esclave",
                "Échanges",
                "Réussite",
                "Timeouts",
                "CRC",
                "Exceptions",
                "Incohérentes",
                "Liaison",
                "Moy (ms)",
                "P95 (ms)",
                "Max (ms)",
                "Gigue (ms)",
            ]
        )
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stats_table.setMaximumHeight(180)

        self.hyp_list = QListWidget()
        self.hyp_list.setMinimumWidth(320)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.tests_box = QVBoxLayout()
        self.tests_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        tests_widget = QWidget()
        tests_widget.setLayout(self.tests_box)
        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.cancel_test_btn = QPushButton("ANNULER LE TEST")
        self.cancel_test_btn.setVisible(False)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Résultats des tests exécutés")
        self.results.setMaximumHeight(140)

        right = QVBoxLayout()
        right.addWidget(QLabel("Indices"))
        right.addWidget(self.detail, 2)
        right.addWidget(QLabel("Tests pour départager"))
        right.addWidget(tests_widget, 2)
        right.addWidget(self.test_progress)
        right.addWidget(self.cancel_test_btn)
        right.addWidget(self.results, 1)
        right_w = QWidget()
        right_w.setLayout(right)

        middle = QSplitter(Qt.Orientation.Horizontal)
        middle.addWidget(self.hyp_list)
        middle.addWidget(right_w)
        middle.setStretchFactor(1, 2)
        middle.setChildrenCollapsible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(QLabel("Statistiques par esclave"))
        layout.addWidget(self.stats_table)
        layout.addWidget(QLabel("Hypothèses classées (score de vraisemblance)"))
        layout.addWidget(middle, 1)

        self.analyse_btn.clicked.connect(self.refresh)
        self.clear_btn.clicked.connect(self._clear_history)
        self.sources.currentIndexChanged.connect(lambda _i: self.refresh())
        self.hyp_list.currentRowChanged.connect(self._show_hypothesis)
        self.cancel_test_btn.clicked.connect(self.cancel_test_requested)

    # ================================================================ état
    def set_settings(self, settings: SerialSettings | None) -> None:
        self._settings = settings

    def set_can_run_tests(self, can_run: bool) -> None:
        self._can_run = can_run
        self._show_hypothesis(self.hyp_list.currentRow())

    def stats_for(self, slave_id: int) -> SlaveStats | None:
        return self._stats.get(slave_id)

    # ============================================================= analyse
    def refresh(self) -> None:
        sources = self.sources.currentData()
        observations = self.session.observations(sources)
        self._stats = self.session.stats(sources)
        self.count_label.setText(f"{len(observations)} observation(s)")
        self._fill_stats()
        self._hypotheses = analyse(self._stats, observations, self._settings)
        self.hyp_list.clear()
        for h in self._hypotheses:
            item = QListWidgetItem(f"{h.score:3d}   {h.title}   [{h.scope}]")
            item.setForeground(QColor(_score_color(h.score)))
            self.hyp_list.addItem(item)
        if self._hypotheses:
            self.hyp_list.setCurrentRow(0)
        else:
            self.detail.setPlainText(
                "Pas assez de données. Faites des lectures (onglet Maître, idéalement en cyclique), "
                "écoutez le bus (Espion) ou lancez un scan, puis cliquez sur ANALYSER."
            )
            self._clear_tests()

    def _fill_stats(self) -> None:
        t = self.stats_table
        t.setRowCount(len(self._stats))
        for row, st in enumerate(sorted(self._stats.values(), key=lambda s: s.slave_id)):
            ratio = (st.ok + st.exception) / st.total if st.total else 0.0
            color = "#2ea043" if ratio >= 0.99 else ("#d29922" if ratio >= 0.9 else "#e5534b")
            cells = [
                str(st.slave_id),
                str(st.total),
                f"{100 * ratio:.1f} %",
                str(st.timeout),
                str(st.crc_error),
                str(st.exception),
                str(st.bad_response),
                str(st.transport_error),
                f"{st.rt_avg:.1f}" if st.rt_avg is not None else "-",
                f"{st.rt_p95:.1f}" if st.rt_p95 is not None else "-",
                f"{st.rt_max:.1f}" if st.rt_max is not None else "-",
                f"{st.rt_jitter:.1f}" if st.rt_jitter is not None else "-",
            ]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 2:
                    it.setForeground(QColor(color))
                t.setItem(row, col, it)

    def _show_hypothesis(self, row: int) -> None:
        self._clear_tests()
        if row < 0 or row >= len(self._hypotheses):
            return
        h = self._hypotheses[row]
        lines = [h.title.upper(), f"Portée : {h.scope}   Score : {h.score}/100", "", h.summary, ""]
        lines += [f"• {e}" for e in h.evidence]
        self.detail.setPlainText("\n".join(lines))
        if not h.tests:
            self.tests_box.addWidget(QLabel("Aucun test complémentaire : prolonger l'observation."))
        for test in h.tests:
            self.tests_box.addWidget(self._test_row(test, h))

    def _test_row(self, test: SuggestedTest, hyp: Hypothesis) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        text = QLabel(f"<b>{test.title}</b><br>{test.description}")
        text.setWordWrap(True)
        lay.addWidget(text, 1)
        if test.runnable:
            btn = QPushButton("LANCER")
            btn.setToolTip(
                f"{test.count} lectures toutes les {test.period_ms} ms"
                + (" avec la liaison modifiée" if test.changes_link else "")
            )
            btn.setEnabled(self._can_run and not self._test_running and hyp.slave_id is not None)
            btn.clicked.connect(lambda _c=False, t=test, h=hyp: self.run_test_requested.emit(t, h))
            lay.addWidget(btn)
        else:
            manual = QLabel("manuel")
            manual.setStyleSheet("color: #8b949e;")
            lay.addWidget(manual)
        return w

    def _clear_tests(self) -> None:
        while self.tests_box.count():
            item = self.tests_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    # ================================================================ tests
    def on_test_started(self, test: SuggestedTest, hyp: Hypothesis) -> None:
        self._test_running = True
        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, test.count)
        self.test_progress.setValue(0)
        self.cancel_test_btn.setVisible(True)
        self.results.appendPlainText(
            f"▶ {test.title} (esclave {hyp.slave_id}) : {test.count} lectures / {test.period_ms} ms…"
        )
        self._show_hypothesis(self.hyp_list.currentRow())

    def on_test_progress(self, done: int, total: int) -> None:
        self.test_progress.setRange(0, total)
        self.test_progress.setValue(done)

    def on_test_finished(self, comparison: CampaignComparison | None) -> None:
        self._test_running = False
        self.test_progress.setVisible(False)
        self.cancel_test_btn.setVisible(False)
        if comparison is None:
            self.results.appendPlainText("   test interrompu ou impossible (liaison fermée ?)")
        else:
            r, b = comparison.result, comparison.baseline
            self.results.appendPlainText(
                f"   référence : {b.total} échanges, {100 * b.error_ratio:.0f} % de défauts, {b.rt_avg or 0:.1f} ms\n"
                f"   test      : {r.total} échanges, {100 * r.error_ratio:.0f} % de défauts, {r.rt_avg or 0:.1f} ms\n"
                f"   ⇒ {comparison.verdict()}"
            )
        self.refresh()

    def _clear_history(self) -> None:
        self.session.clear()
        self.results.clear()
        self.refresh()
        self.status_message.emit("Historique de diagnostic effacé")
