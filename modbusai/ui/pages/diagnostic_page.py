"""Onglet DIAGNOSTIC : cible et campagnes minutées, test de torture, statistiques,
hypothèses classées avec légende et aide, tests pour départager, export txt.

Autonome : il ne dépend pas de l'onglet Maître. Il utilise la liaison
courante (bandeau) et la fenêtre l'ouvre au besoin.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from modbusai.analysis.campaign import DEFAULT_DURATION_S, CampaignSpec
from modbusai.analysis.diagnostic import (
    CATALOGUE,
    SCORE_EXPLANATION,
    SCORE_LEGEND,
    CampaignComparison,
    Hypothesis,
    SuggestedTest,
    analyse,
)
from modbusai.analysis.observations import SlaveStats
from modbusai.analysis.report import build_report, suggested_filename
from modbusai.analysis.session import SessionStore
from modbusai.analysis.stress import StressPhase, StressReport, default_scenario
from modbusai.modbus.records import Request
from modbusai.transport.records import LinkSettings
from modbusai.ui.widgets.request_bar import RegisterType

# Par défaut, le scan est exclu : ses adresses absentes ne sont pas des pannes à expliquer.
SOURCES = (
    ("Maître, espion et tests", ["maitre", "espion", "test"]),
    ("Toutes les sources (avec scan)", None),
    ("Maître", ["maitre"]),
    ("Espion", ["espion"]),
    ("Scan", ["scan"]),
    ("Tests", ["test"]),
)


def _score_color(score: int) -> str:
    for lo, hi, _label, color in SCORE_LEGEND:
        if lo <= score <= hi:
            return color
    return SCORE_LEGEND[-1][3]


def _mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


class ScoreLegend(QWidget):
    """Barre de légende : trois plages colorées et l'explication du score."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Score :"))
        for lo, hi, label, color in SCORE_LEGEND:
            chip = QLabel(f" {lo}-{hi} {label} ")
            chip.setStyleSheet(f"background: {color}; color: white; border-radius: 4px; padding: 1px 4px;")
            layout.addWidget(chip)
        info = QLabel("?")
        info.setToolTip(SCORE_EXPLANATION)
        info.setStyleSheet("font-weight: bold;")
        layout.addWidget(info)
        layout.addStretch(1)
        self.setToolTip(SCORE_EXPLANATION)


class HypothesisHelpDialog(QDialog):
    """Catalogue de toutes les hypothèses connues, généré depuis les règles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aide : hypothèses du diagnostic")
        self.resize(760, 560)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(self.build_html())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(browser, 1)
        layout.addWidget(buttons)

    @staticmethod
    def build_html() -> str:
        parts = ["<h2>Comment lire le diagnostic</h2>", f"<p>{SCORE_EXPLANATION}</p>", "<ul>"]
        for lo, hi, label, color in SCORE_LEGEND:
            parts.append(f'<li><b style="color:{color}">{lo} à {hi}</b> : {label}</li>')
        parts.append("</ul><h2>Hypothèses possibles</h2>")
        for info in CATALOGUE.values():
            parts.append(f"<h3>{info.title}</h3><p><i>{info.summary}</i></p>")
            parts.append(f"<p><b>Déclenchement :</b> {info.trigger}</p>")
            parts.append(
                "<p><b>Causes classiques :</b></p><ul>" + "".join(f"<li>{c}</li>" for c in info.causes) + "</ul>"
            )
            parts.append(
                "<p><b>Pour confirmer :</b></p><ul>" + "".join(f"<li>{t}</li>" for t in info.how_to_confirm) + "</ul>"
            )
        return "".join(parts)


class DiagnosticPage(QWidget):
    campaign_requested = Signal(object)  # CampaignSpec
    stress_requested = Signal(object)  # list[StressPhase]
    cancel_requested = Signal()
    status_message = Signal(str)

    def __init__(self, session: SessionStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._settings: LinkSettings | None = None
        self._hypotheses: list[Hypothesis] = []
        self._stats: dict[int, SlaveStats] = {}
        self._running = False
        self._can_run = False
        self._pending_test: tuple[SuggestedTest, SlaveStats] | None = None
        self._comparisons: list[CampaignComparison] = []
        self._stress_report: StressReport | None = None
        self._stress_total = 0

        # ------------------------------------------------------ cible et campagne
        self.slave = QSpinBox()
        self.slave.setRange(1, 247)
        self.reg_type = QComboBox()
        for t in RegisterType:
            self.reg_type.addItem(t.label, t)
        self.reg_type.setCurrentIndex(list(RegisterType).index(RegisterType.HOLDING))
        self.address = QSpinBox()
        self.address.setRange(0, 65535)
        self.count = QSpinBox()
        self.count.setRange(1, 125)
        self.period = QSpinBox()
        self.period.setRange(10, 60000)
        self.period.setValue(200)
        self.period.setSuffix(" ms")
        self.by_duration = QRadioButton("Durée")
        self.by_count = QRadioButton("Nombre")
        self.by_duration.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.by_duration)
        group.addButton(self.by_count)
        self.duration = QSpinBox()
        self.duration.setRange(5, 86400)
        self.duration.setValue(int(DEFAULT_DURATION_S))
        self.duration.setSuffix(" s")
        self.max_count = QSpinBox()
        self.max_count.setRange(1, 1_000_000)
        self.max_count.setValue(100)
        self.stress_duration = QSpinBox()
        self.stress_duration.setRange(30, 86400)
        self.stress_duration.setValue(300)
        self.stress_duration.setSuffix(" s")

        self.run_btn = QPushButton("LANCER CAMPAGNE")
        self.stress_btn = QPushButton("TEST DE TORTURE")
        self.stress_btn.setToolTip(
            "Enchaîne référence, rafale, trames longues, timeout serré (et vitesse réduite en RTU)"
        )
        self.cancel_btn = QPushButton("ARRÊTER")
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.countdown = QLabel("Prêt.")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Esclave", self.slave)
        form.addRow("Type", self.reg_type)
        form.addRow("Registre", self.address)
        form.addRow("Longueur", self.count)
        form.addRow("Période", self.period)
        limit = QHBoxLayout()
        limit.addWidget(self.by_duration)
        limit.addWidget(self.duration)
        limit.addWidget(self.by_count)
        limit.addWidget(self.max_count)
        limit_w = QWidget()
        limit_w.setLayout(limit)
        form.addRow("Limite", limit_w)
        torture = QHBoxLayout()
        torture.addWidget(QLabel("Durée totale"))
        torture.addWidget(self.stress_duration)
        torture.addStretch(1)
        torture_w = QWidget()
        torture_w.setLayout(torture)
        form.addRow("Torture", torture_w)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.stress_btn)
        buttons.addWidget(self.cancel_btn)
        target_layout = QVBoxLayout()
        target_layout.addLayout(form)
        target_layout.addLayout(buttons)
        target_layout.addWidget(self.progress)
        target_layout.addWidget(self.countdown)
        target_layout.addStretch(1)
        self.target_box = QGroupBox("Cible et campagne")
        self.target_box.setLayout(target_layout)
        self.target_box.setMaximumWidth(420)

        # ------------------------------------------------------------- analyse
        self.analyse_btn = QPushButton("ANALYSER")
        self.clear_btn = QPushButton("EFFACER HISTORIQUE")
        self.export_btn = QPushButton("EXPORTER TXT")
        self.help_btn = QPushButton("AIDE")
        self.sources = QComboBox()
        for label, value in SOURCES:
            self.sources.addItem(label, value)
        self.count_label = QLabel("0 observation")

        top = QHBoxLayout()
        top.addWidget(self.analyse_btn)
        top.addWidget(self.clear_btn)
        top.addWidget(self.export_btn)
        top.addWidget(self.help_btn)
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
        self.stats_table.setMaximumHeight(160)

        self.legend = ScoreLegend()
        self.hyp_list = QListWidget()
        self.hyp_list.setMinimumWidth(300)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.tests_box = QVBoxLayout()
        self.tests_box.setAlignment(Qt.AlignmentFlag.AlignTop)
        tests_widget = QWidget()
        tests_widget.setLayout(self.tests_box)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Résultats des campagnes et du test de torture")

        right = QVBoxLayout()
        right.addWidget(QLabel("Indices"))
        right.addWidget(self.detail, 2)
        right.addWidget(QLabel("Tests pour départager"))
        right.addWidget(tests_widget, 2)
        right.addWidget(QLabel("Résultats"))
        right.addWidget(self.results, 2)
        right_w = QWidget()
        right_w.setLayout(right)

        middle = QSplitter(Qt.Orientation.Horizontal)
        middle.addWidget(self.hyp_list)
        middle.addWidget(right_w)
        middle.setStretchFactor(1, 2)
        middle.setChildrenCollapsible(False)

        analysis_layout = QVBoxLayout()
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.addLayout(top)
        analysis_layout.addWidget(QLabel("Statistiques par esclave"))
        analysis_layout.addWidget(self.stats_table)
        head = QHBoxLayout()
        head.addWidget(QLabel("Hypothèses classées"))
        head.addSpacing(12)
        head.addWidget(self.legend)
        analysis_layout.addLayout(head)
        analysis_layout.addWidget(middle, 1)
        analysis_w = QWidget()
        analysis_w.setLayout(analysis_layout)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.target_box)
        layout.addWidget(analysis_w, 1)

        # ------------------------------------------------------------- signaux
        self.run_btn.clicked.connect(self._launch_campaign)
        self.stress_btn.clicked.connect(self._launch_stress)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        self.analyse_btn.clicked.connect(self.refresh)
        self.clear_btn.clicked.connect(self._clear_history)
        self.export_btn.clicked.connect(self.export_txt)
        self.help_btn.clicked.connect(lambda: HypothesisHelpDialog(self).exec())
        self.sources.currentIndexChanged.connect(lambda _i: self.refresh())
        self.hyp_list.currentRowChanged.connect(self._show_hypothesis)
        self.reg_type.currentIndexChanged.connect(self._on_type_changed)
        self.by_duration.toggled.connect(lambda on: (self.duration.setEnabled(on), self.max_count.setEnabled(not on)))
        self.max_count.setEnabled(False)

    # ================================================================ cible
    def _on_type_changed(self) -> None:
        t: RegisterType = self.reg_type.currentData()
        self.count.setMaximum(2000 if t.is_bits else 125)

    def target_request(self) -> Request:
        t: RegisterType = self.reg_type.currentData()
        return Request(self.slave.value(), t.read_function, self.address.value(), self.count.value())

    def campaign_spec(self) -> CampaignSpec:
        if self.by_duration.isChecked():
            return CampaignSpec(
                self.target_request(), self.period.value(), float(self.duration.value()), None, label="Campagne"
            )
        return CampaignSpec(self.target_request(), self.period.value(), None, self.max_count.value(), label="Campagne")

    def set_target(self, request: Request) -> None:
        """Pré-remplit la cible (par exemple depuis le maître)."""
        self.slave.setValue(request.slave_id)
        for i in range(self.reg_type.count()):
            if self.reg_type.itemData(i).read_function == request.function:
                self.reg_type.setCurrentIndex(i)
        self.address.setValue(request.address)
        self.count.setValue(request.count)

    def _launch_campaign(self) -> None:
        self._pending_test = None
        self.campaign_requested.emit(self.campaign_spec())

    def _launch_stress(self) -> None:
        if self._settings is None:
            self.status_message.emit("Configurez la liaison avant le test de torture.")
            return
        others = tuple(s for s in self.session.stats().keys() if s != self.slave.value())
        phases = default_scenario(self.target_request(), self._settings, float(self.stress_duration.value()), others)
        self.stress_requested.emit(phases)

    # ================================================================ état
    def set_settings(self, settings: LinkSettings | None) -> None:
        self._settings = settings

    def set_can_run_tests(self, can_run: bool) -> None:
        """Vrai quand la liaison est libre pour une campagne (connectée ou connectable)."""
        self._can_run = can_run
        for b in (self.run_btn, self.stress_btn):
            b.setEnabled(can_run and not self._running)
        self._show_hypothesis(self.hyp_list.currentRow())

    def stats_for(self, slave_id: int) -> SlaveStats | None:
        return self._stats.get(slave_id)

    @property
    def running(self) -> bool:
        return self._running

    # ============================================================ campagnes
    def on_campaign_started(self, spec: CampaignSpec) -> None:
        self._running = True
        self.cancel_btn.setEnabled(True)
        self.run_btn.setEnabled(False)
        self.stress_btn.setEnabled(False)
        self.target_box.setEnabled(True)
        self.progress.setRange(0, spec.expected_count() or 0)
        self.progress.setValue(0)
        self.results.appendPlainText(f"▶ {spec.describe()}")
        self.status_message.emit(f"Campagne : {spec.describe()}")

    def on_stress_started(self, phases: list[StressPhase]) -> None:
        self._stress_total = len(phases)
        self._stress_report = None
        self.results.appendPlainText(f"▶ TEST DE TORTURE : {len(phases)} phases")

    def on_stress_phase(self, index: int, total: int, phase: StressPhase) -> None:
        self.results.appendPlainText(f"   phase {index + 1}/{total} : {phase.title} - {phase.purpose}")

    def on_progress(self, done: int, expected: int, elapsed: float, remaining: float) -> None:
        self.progress.setRange(0, max(expected, done, 1))
        self.progress.setValue(done)
        if remaining > 0 or expected == 0:
            self.countdown.setText(f"{done} lectures  |  écoulé {_mmss(elapsed)}  |  reste {_mmss(remaining)}")
        else:
            self.countdown.setText(f"{done} / {expected} lectures  |  écoulé {_mmss(elapsed)}")

    def on_campaign_finished(self, stats: SlaveStats | None) -> None:
        self._running = False
        self.cancel_btn.setEnabled(False)
        self.set_can_run_tests(self._can_run)
        if stats is None:
            self.results.appendPlainText("   interrompue avant toute lecture (liaison fermée ?)")
        else:
            valid = 100 * (stats.ok + stats.exception) / stats.total
            line = (
                f"   {stats.total} lectures : {valid:.1f} % valides, {stats.timeout} timeouts, "
                f"{stats.crc_error} CRC, {stats.bad_response} incohérentes"
            )
            if stats.rt_avg is not None:
                line += f", {stats.rt_avg:.1f} ms en moyenne (max {stats.rt_max:.1f})"
            self.results.appendPlainText(line)
            if self._pending_test is not None:
                test, baseline = self._pending_test
                comparison = CampaignComparison(test, baseline, stats)
                self._comparisons.append(comparison)
                self.results.appendPlainText(f"   ⇒ {comparison.verdict()}")
        self._pending_test = None
        self.countdown.setText("Terminé.")
        self.refresh()

    def on_stress_finished(self, report: StressReport | None) -> None:
        self._running = False
        self.cancel_btn.setEnabled(False)
        self.set_can_run_tests(self._can_run)
        self._stress_report = report
        if report is None:
            self.results.appendPlainText("   test de torture interrompu.")
        else:
            for r in report.results:
                st = r.stats
                self.results.appendPlainText(
                    f"   {r.phase.title:<20} {st.total:>4} lectures, défauts {100 * st.error_ratio:5.1f} %, "
                    f"moy {st.rt_avg or 0:.1f} ms"
                )
            for c in report.conclusions:
                self.results.appendPlainText(f"   {c}")
            self.results.appendPlainText(f"   ⇒ {report.orientation}")
        self.countdown.setText("Terminé.")
        self.refresh()

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
                "Pas assez de données. Lancez une campagne (à gauche), faites des lectures dans l'onglet Maître, "
                "écoutez le bus (Espion) ou scannez, puis cliquez sur ANALYSER."
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
        info = CATALOGUE.get(h.key)
        lines = [h.title.upper(), f"Portée : {h.scope}   Score : {h.score}/100", "", h.summary, ""]
        lines += [f"• {e}" for e in h.evidence]
        if info is not None:
            lines += ["", "Causes classiques : " + " ; ".join(info.causes)]
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
            dur = f"{test.duration_s:.0f} s" if test.duration_s else f"{test.count} lectures"
            btn.setToolTip(
                f"Campagne de {dur} toutes les {test.period_ms} ms"
                + (" avec la liaison modifiée" if test.changes_link else "")
            )
            btn.setEnabled(self._can_run and not self._running and hyp.slave_id is not None)
            btn.clicked.connect(lambda _c=False, t=test, h=hyp: self._launch_test(t, h))
            lay.addWidget(btn)
        else:
            manual = QLabel("manuel")
            manual.setStyleSheet("color: #8b949e;")
            lay.addWidget(manual)
        return w

    def _launch_test(self, test: SuggestedTest, hyp: Hypothesis) -> None:
        if hyp.slave_id is None:
            return
        baseline = self._stats.get(hyp.slave_id)
        if baseline is None:
            self.status_message.emit("Pas de statistiques de référence pour cet esclave.")
            return
        request = self.target_request()
        if request.slave_id != hyp.slave_id:
            request = Request(hyp.slave_id, request.function, request.address, request.count)
        spec = test.to_campaign(request)
        if self.by_duration.isChecked():
            spec = replace(spec, duration_s=float(self.duration.value()))
        else:
            spec = replace(spec, duration_s=None, max_count=self.max_count.value())
        self._pending_test = (test, baseline)
        self.campaign_requested.emit(spec)

    def _clear_tests(self) -> None:
        while self.tests_box.count():
            item = self.tests_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    # ================================================================ export
    def export_txt(self) -> str | None:
        sources = self.sources.currentData()
        observations = self.session.observations(sources)
        text = build_report(
            self._settings,
            self._stats,
            self._hypotheses,
            self._comparisons,
            self._stress_report,
            observations_count=len(observations),
            sources_label=self.sources.currentText(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter le diagnostic", suggested_filename(), "Fichier texte (*.txt)"
        )
        if not path:
            return None
        try:
            with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
                f.write(text)
        except OSError as exc:
            self.status_message.emit(f"Export impossible : {exc}")
            return None
        self.status_message.emit(f"Diagnostic exporté : {path}")
        return path

    def report_text(self) -> str:
        observations = self.session.observations(self.sources.currentData())
        return build_report(
            self._settings,
            self._stats,
            self._hypotheses,
            self._comparisons,
            self._stress_report,
            len(observations),
            self.sources.currentText(),
        )

    def _clear_history(self) -> None:
        self.session.clear()
        self.results.clear()
        self._comparisons.clear()
        self._stress_report = None
        self.refresh()
        self.status_message.emit("Historique de diagnostic effacé")
