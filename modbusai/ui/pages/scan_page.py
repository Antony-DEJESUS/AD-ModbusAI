"""Onglet SCAN RÉSEAU : recherche des esclaves présents, identification, balayage des paramètres."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modbusai.analysis.scanner import COMMON_BAUDRATES, ScanPlan, ScanResult, ScanStatus
from modbusai.i18n import tr
from modbusai.modbus.records import FunctionCode
from modbusai.transport.records import LinkSettings, Parity, SerialSettings
from modbusai.ui.iconography import set_icon
from modbusai.ui.metrics import text_width, use_tabular_figures
from modbusai.ui.palette import State, color
from modbusai.ui.style import PAGE_MARGINS
from modbusai.ui.widgets.config_dialog import BAUDRATES
from modbusai.ui.widgets.labels import set_variant

_STATUS_STATE = {
    ScanStatus.PRESENT: State.OK,
    ScanStatus.PRESENT_EXCEPTION: State.OK,
    ScanStatus.NOISY: State.WARN,
    ScanStatus.CONFLICT: State.ERROR,
    ScanStatus.ERROR: State.SPECIAL,
    ScanStatus.ABSENT: State.MUTED,
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
        self.identify = QCheckBox(tr("Identifier les équipements (FC43, FC17)"))
        self.identify.setChecked(True)
        self.show_absent = QCheckBox(tr("Afficher les adresses absentes"))

        # ---- liaison utilisée par le scan
        self.link_current = QRadioButton(tr("Paramètres courants (bandeau)"))
        self.link_custom = QRadioButton(tr("Paramètres personnalisés"))
        self.link_sweep = QRadioButton(tr("Balayer plusieurs paramètres (long)"))
        self.link_current.setChecked(True)
        link_group = QButtonGroup(self)
        for r in (self.link_current, self.link_custom, self.link_sweep):
            link_group.addButton(r)
        self.custom_baud = QComboBox()
        for b in BAUDRATES:
            self.custom_baud.addItem(str(b), b)
        self.custom_baud.setCurrentIndex(BAUDRATES.index(19200))
        self.custom_parity = QComboBox()
        for parity, label in ((Parity.NONE, "None"), (Parity.EVEN, "Even"), (Parity.ODD, "Odd")):
            self.custom_parity.addItem(label, parity)
        self.custom_stop = QComboBox()
        for v, label in ((1.0, "1"), (2.0, "2")):
            self.custom_stop.addItem(label, v)
        custom_row = QHBoxLayout()
        custom_row.setContentsMargins(20, 0, 0, 0)
        for label, w in (("Vitesse", self.custom_baud), ("Parité", self.custom_parity), ("Stop", self.custom_stop)):
            custom_row.addWidget(QLabel(label))
            custom_row.addWidget(w)
        custom_row.addStretch(1)
        self.custom_widget = QWidget()
        self.custom_widget.setLayout(custom_row)
        self.sweep_bauds = {b: QCheckBox(str(b)) for b in BAUDRATES}
        for b in COMMON_BAUDRATES:
            self.sweep_bauds[b].setChecked(True)
        self.sweep_framings = {
            (Parity.NONE, 1.0): QCheckBox(tr("8N1")),
            (Parity.EVEN, 1.0): QCheckBox(tr("8E1")),
            (Parity.ODD, 1.0): QCheckBox(tr("8O1")),
            (Parity.NONE, 2.0): QCheckBox(tr("8N2")),
        }
        for cb in self.sweep_framings.values():
            cb.setChecked(True)
        sweep_layout = QVBoxLayout()
        sweep_layout.setContentsMargins(20, 0, 0, 0)
        bauds_row = QGridLayout()
        for i, cb in enumerate(self.sweep_bauds.values()):
            bauds_row.addWidget(cb, i // 3, i % 3)
        fr_row = QHBoxLayout()
        for cb in self.sweep_framings.values():
            fr_row.addWidget(cb)
        fr_row.addStretch(1)
        sweep_layout.addLayout(bauds_row)
        sweep_layout.addLayout(fr_row)
        self.sweep_widget = QWidget()
        self.sweep_widget.setLayout(sweep_layout)
        self.link_hint = QLabel("")
        self.link_hint.setProperty("variant", "muted")
        self.link_hint.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        rng = QHBoxLayout()
        rng.addWidget(self.first)
        rng.addWidget(QLabel(tr("à")))
        rng.addWidget(self.last)
        rng.addStretch(1)
        rng_w = QWidget()
        rng_w.setLayout(rng)
        form.addRow(tr("Esclaves de"), rng_w)
        form.addRow(tr("Type lu"), self.function)
        form.addRow(tr("Registre"), self.address)
        form.addRow(tr("Longueur"), self.count)
        form.addRow(tr("Timeout par essai"), self.timeout)
        form.addRow(tr("Essais supplémentaires"), self.retries)
        form.addRow("", self.identify)
        link_layout = QVBoxLayout()
        link_layout.addWidget(self.link_current)
        link_layout.addWidget(self.link_custom)
        link_layout.addWidget(self.custom_widget)
        link_layout.addWidget(self.link_sweep)
        link_layout.addWidget(self.sweep_widget)
        link_layout.addWidget(self.link_hint)
        self.link_box = QGroupBox(tr("Liaison du scan"))
        self.link_box.setLayout(link_layout)
        params_layout = QVBoxLayout()
        params_layout.addLayout(form)
        params_layout.addWidget(self.link_box)
        params_layout.addStretch(1)
        params = QGroupBox(tr("Paramètres du scan"))
        params.setLayout(params_layout)
        params.setMinimumWidth(text_width(self, "Vitesses   9600  19200  38400  57600", extra=60))
        params.setMaximumWidth(text_width(self, "Vitesses   9600  19200  38400  57600", extra=140))

        self.start_btn = QPushButton(tr("LANCER SCAN"))
        self.start_btn.setProperty("variant", "primary")
        self.cancel_btn = QPushButton(tr("ARRÊTER"))
        self.cancel_btn.setEnabled(False)
        self.clear_btn = QPushButton(tr("EFFACER"))
        self.copy_btn = QPushButton(tr("COPIER"))
        set_icon(self.start_btn, "play", on_accent=True)
        set_icon(self.cancel_btn, "stop")
        set_icon(self.clear_btn, "trash")
        set_icon(self.copy_btn, "copy")
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress_label = QLabel(tr("Prêt. Le scan utilise la liaison du maître : connectez-vous d'abord."))
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
        self.table.setHorizontalHeaderLabels(
            [tr("Esclave"), tr("Statut"), tr("Temps (ms)"), tr("Liaison"), tr("Détail"), tr("Identification")]
        )
        self.table.verticalHeader().setVisible(False)
        use_tabular_figures(self.table)
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
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.addWidget(params)
        layout.addLayout(right, 1)

        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        self.clear_btn.clicked.connect(self.clear)
        self.copy_btn.clicked.connect(self._copy)
        self.show_absent.toggled.connect(lambda _c: self._rebuild())
        self.first.valueChanged.connect(lambda v: self.last.setMinimum(v))
        for r in (self.link_current, self.link_custom, self.link_sweep):
            r.toggled.connect(lambda _c: self._update_link_widgets())
        self._tcp = False
        self._update_link_widgets()

    # ============================================================== liaison
    def set_tcp(self, tcp: bool) -> None:
        """En TCP, il n'y a ni vitesse ni parité : seuls les paramètres courants s'appliquent."""
        self._tcp = tcp
        if tcp:
            self.link_current.setChecked(True)
        for w in (self.link_custom, self.link_sweep):
            w.setEnabled(not tcp)
            w.setToolTip("Sans objet en Modbus TCP" if tcp else "")
        self._update_link_widgets()

    def _update_link_widgets(self) -> None:
        self.custom_widget.setEnabled(self.link_custom.isChecked() and not self._tcp)
        self.sweep_widget.setEnabled(self.link_sweep.isChecked() and not self._tcp)
        if self.link_sweep.isChecked() and not self._tcp:
            n = self._selected_bauds_count() * self._selected_framings_count()
            self.link_hint.setText(
                tr("{p0} combinaison(s) : chaque adresse est testée avec chacune, le scan sera long.").format(p0=n)
            )
        elif self.link_custom.isChecked():
            self.link_hint.setText(
                "Le port du bandeau est conservé ; vitesse, parité et stop sont remplacés pour la durée du scan."
            )
        else:
            self.link_hint.setText("")

    def _selected_bauds_count(self) -> int:
        return sum(1 for cb in self.sweep_bauds.values() if cb.isChecked())

    def _selected_framings_count(self) -> int:
        return sum(1 for cb in self.sweep_framings.values() if cb.isChecked())

    def scan_settings(self, current: LinkSettings) -> LinkSettings:
        """Paramètres de base du scan selon le choix de liaison."""
        if self.link_custom.isChecked() and isinstance(current, SerialSettings):
            return replace(
                current,
                baudrate=self.custom_baud.currentData(),
                parity=self.custom_parity.currentData(),
                stopbits=self.custom_stop.currentData(),
                bytesize=8,
            )
        return current

    # ================================================================ plan
    def plan(self, settings: LinkSettings) -> ScanPlan:
        return ScanPlan(
            first_slave=self.first.value(),
            last_slave=self.last.value(),
            function=self.function.currentData(),
            address=self.address.value(),
            count=self.count.value(),
            timeout_ms=float(self.timeout.value()),
            retries=self.retries.value(),
            identify=self.identify.isChecked(),
            sweep_settings=self.link_sweep.isChecked() and not self._tcp,
            base_settings=self.scan_settings(settings),
            sweep_baudrates=tuple(b for b, cb in self.sweep_bauds.items() if cb.isChecked()),
            sweep_framings=tuple(k for k, cb in self.sweep_framings.items() if cb.isChecked()),
        )

    def _start(self) -> None:
        self.start_requested.emit(None)  # la fenêtre complète le plan avec les paramètres courants

    # ================================================================ état
    def on_started(self, plan: ScanPlan) -> None:
        self._running = True
        set_variant(self.cancel_btn, "danger")  # pendant le scan, ARRÊTER est l'action saillante
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, plan.total_probes)
        self.progress.setValue(0)
        self.summary.setText("")
        variants = len(plan.settings_variants())
        self.status_message.emit(
            tr("Scan en cours : {p0} adresses × {p1} jeu(x) de paramètres").format(p0=len(plan.slaves), p1=variants)
        )

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
        set_variant(self.cancel_btn, "")
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
        tint = color(_STATUS_STATE[r.status])
        cells = [
            str(r.slave_id),
            tr(r.status.value),
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
                it.setForeground(QColor(tint))
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
            text += " : " + ", ".join(f"esclave {r.slave_id} ({r.settings.summary()})" for r in present[:12])
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
            lines.append(
                f"{r.slave_id}\t{tr(r.status.value)}\t{rt}\t{r.settings.summary()}\t{r.detail}\t{r.identity_text}"
            )
        QApplication.clipboard().setText("\n".join(lines))
        self.status_message.emit(tr("Résultats du scan copiés ({p0} lignes)").format(p0=len(lines) - 1))

    def clear(self) -> None:
        self._results.clear()
        self.table.setRowCount(0)
        self.summary.setText("")
        self.progress.setValue(0)
