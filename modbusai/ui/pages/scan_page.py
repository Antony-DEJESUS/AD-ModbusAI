"""Onglet SCAN RÉSEAU : recherche des esclaves présents, identification, balayage des paramètres."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modbusai.analysis.scanner import ScanPlan, ScanResult, ScanStatus
from modbusai.modbus.records import FunctionCode
from modbusai.transport.records import SerialSettings

_STATUS_COLOR = {
    ScanStatus.PRESENT: "#2ea043",
    ScanStatus.PRESENT_EXCEPTION: "#2ea043",
    ScanStatus.NOISY: "#d29922",
    ScanStatus.CONFLICT: "#e5534b",
    ScanStatus.ERROR: "#a371f7",
    ScanStatus.ABSENT: "#8b949e",
}


class ScanPage(QWidget):
    start_requested = Signal(object)  # ScanPlan
    cancel_requested = Signal()
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: list[ScanResult] = []
        self._running = False

        self.first = QSpinBox()
        self.first.setRange(1, 247)
        self.first.setValue(1)
        self.last = QSpinBox()
        self.last.setRange(1, 247)
        self.last.setValue(247)
        self.function = QComboBox()
        for fc, label in (
            (FunctionCode.READ_HOLDING_REGISTERS, "3 Holding registers"),
            (FunctionCode.READ_INPUT_REGISTERS, "4 Input registers"),
            (FunctionCode.READ_COILS, "1 Coil status"),
            (FunctionCode.READ_DISCRETE_INPUTS, "2 Input status"),
        ):
            self.function.addItem(label, fc)
        self.address = QSpinBox()
        self.address.setRange(0, 65535)
        self.count = QSpinBox()
        self.count.setRange(1, 125)
        self.count.setValue(1)
        self.timeout = QSpinBox()
        self.timeout.setRange(20, 5000)
        self.timeout.setValue(200)
        self.timeout.setSuffix(" ms")
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setValue(1)
        self.identify = QCheckBox("Identifier les équipements (FC43, FC17)")
        self.identify.setChecked(True)
        self.sweep = QCheckBox("Balayer vitesses et parités (long)")
        self.show_absent = QCheckBox("Afficher les adresses absentes")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        rng = QHBoxLayout()
        rng.addWidget(self.first)
        rng.addWidget(QLabel("à"))
        rng.addWidget(self.last)
        rng.addStretch(1)
        rng_w = QWidget()
        rng_w.setLayout(rng)
        form.addRow("Esclaves de", rng_w)
        form.addRow("Type lu", self.function)
        form.addRow("Registre", self.address)
        form.addRow("Longueur", self.count)
        form.addRow("Timeout par essai", self.timeout)
        form.addRow("Essais supplémentaires", self.retries)
        form.addRow("", self.identify)
        form.addRow("", self.sweep)
        params = QGroupBox("Paramètres du scan")
        params.setLayout(form)
        params.setMaximumWidth(440)

        self.start_btn = QPushButton("LANCER SCAN")
        self.cancel_btn = QPushButton("ARRÊTER")
        self.cancel_btn.setEnabled(False)
        self.clear_btn = QPushButton("EFFACER")
        self.copy_btn = QPushButton("COPIER")
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress_label = QLabel("Prêt. Le scan utilise la liaison du maître : connectez-vous d'abord.")
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: bold;")

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addWidget(self.copy_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.show_absent)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Esclave", "Statut", "Temps (ms)", "Liaison", "Détail", "Identification"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        right = QVBoxLayout()
        right.addLayout(buttons)
        right.addWidget(self.progress)
        right.addWidget(self.progress_label)
        right.addWidget(self.table, 1)
        right.addWidget(self.summary)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(params)
        layout.addLayout(right, 1)

        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        self.clear_btn.clicked.connect(self.clear)
        self.copy_btn.clicked.connect(self._copy)
        self.show_absent.toggled.connect(lambda _c: self._rebuild())
        self.first.valueChanged.connect(lambda v: self.last.setMinimum(v))

    # ================================================================ plan
    def plan(self, settings: SerialSettings) -> ScanPlan:
        return ScanPlan(
            first_slave=self.first.value(),
            last_slave=self.last.value(),
            function=self.function.currentData(),
            address=self.address.value(),
            count=self.count.value(),
            timeout_ms=float(self.timeout.value()),
            retries=self.retries.value(),
            identify=self.identify.isChecked(),
            sweep_settings=self.sweep.isChecked(),
            base_settings=settings,
        )

    def _start(self) -> None:
        self.start_requested.emit(None)  # la fenêtre complète le plan avec les paramètres courants

    # ================================================================ état
    def on_started(self, plan: ScanPlan) -> None:
        self._running = True
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, plan.total_probes)
        self.progress.setValue(0)
        self.summary.setText("")
        variants = len(plan.settings_variants())
        self.status_message.emit(f"Scan en cours : {len(plan.slaves)} adresses × {variants} jeu(x) de paramètres")

    def on_progress(self, done: int, total: int, label: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress_label.setText(label)

    def on_result(self, result: ScanResult) -> None:
        self._results.append(result)
        if result.status is not ScanStatus.ABSENT or self.show_absent.isChecked():
            self._append(result)
        self._update_summary()

    def on_finished(self, ok: bool) -> None:
        self._running = False
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_label.setText("Scan terminé." if ok else "Scan interrompu.")
        self._update_summary()
        self.status_message.emit(self.summary.text() or ("Scan terminé" if ok else "Scan interrompu"))

    def set_available(self, available: bool) -> None:
        self.start_btn.setEnabled(available and not self._running)

    # ============================================================== table
    def _append(self, r: ScanResult) -> None:
        t = self.table
        row = t.rowCount()
        t.insertRow(row)
        color = _STATUS_COLOR[r.status]
        cells = [
            str(r.slave_id),
            r.status.value,
            f"{r.response_time_ms:.1f}" if r.response_time_ms is not None else "-",
            r.settings.summary(),
            r.detail,
            r.identity_text,
        ]
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it.setToolTip(text)
            if col == 1:
                it.setForeground(QColor(color))
            if col in (0, 2):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setItem(row, col, it)
        t.scrollToBottom()

    def _rebuild(self) -> None:
        self.table.setRowCount(0)
        for r in self._results:
            if r.status is not ScanStatus.ABSENT or self.show_absent.isChecked():
                self._append(r)

    def _update_summary(self) -> None:
        present = [r for r in self._results if r.present]
        noisy = [r for r in self._results if r.status in (ScanStatus.NOISY, ScanStatus.CONFLICT)]
        text = f"{len(present)} équipement(s) trouvé(s)"
        if present:
            text += " : " + ", ".join(f"esclave {r.slave_id} ({r.settings.baudrate})" for r in present[:12])
            if len(present) > 12:
                text += "…"
        if noisy:
            text += f"  |  {len(noisy)} réponse(s) corrompue(s) ou incohérente(s) à examiner"
        self.summary.setText(text)

    def _copy(self) -> None:
        lines = ["Esclave\tStatut\tTemps (ms)\tLiaison\tDétail\tIdentification"]
        for r in self._results:
            if r.status is ScanStatus.ABSENT and not self.show_absent.isChecked():
                continue
            rt = f"{r.response_time_ms:.1f}" if r.response_time_ms is not None else "-"
            lines.append(f"{r.slave_id}\t{r.status.value}\t{rt}\t{r.settings.summary()}\t{r.detail}\t{r.identity_text}")
        QApplication.clipboard().setText("\n".join(lines))
        self.status_message.emit(f"Résultats du scan copiés ({len(lines) - 1} lignes)")

    def clear(self) -> None:
        self._results.clear()
        self.table.setRowCount(0)
        self.summary.setText("")
        self.progress.setValue(0)
