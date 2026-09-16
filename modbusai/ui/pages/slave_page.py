"""Onglet ESCLAVE : serveur esclave RTU façon Mod_RSsim (table par blocs de 10, voyants, journal)."""

from __future__ import annotations

import enum

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from modbusai.i18n import tr
from modbusai.modbus.codec import Radix, format_int, parse_int
from modbusai.modbus.slave import TABLE_SIZE, DataStore, HandledRequest, SlaveConfig, Table
from modbusai.transport.records import LinkSettings
from modbusai.ui.widgets.log_console import LogPanel

COLUMNS = 10


class CellFormat(enum.Enum):
    DEC_SIGNED = ("décimal +/-", Radix.DEC, True)
    DEC_UNSIGNED = ("décimal", Radix.DEC, False)
    HEX = ("hexadécimal", Radix.HEX, False)
    BIN = ("binaire", Radix.BIN, False)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def radix(self) -> Radix:
        return self.value[1]

    @property
    def signed(self) -> bool:
        return self.value[2]


class RegisterTableModel(QAbstractTableModel):
    def __init__(self, store: DataStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.table = Table.HOLDING_REGISTERS
        self.start = 0
        self.rows = 100
        self.fmt = CellFormat.DEC_SIGNED
        self._seen_version = -1

    # ------------------------------------------------------------- config
    def configure(self, table: Table, start: int, rows: int, fmt: CellFormat) -> None:
        self.beginResetModel()
        self.table, self.start, self.rows, self.fmt = table, start, rows, fmt
        self.endResetModel()

    def refresh_if_changed(self) -> None:
        if self.store.version != self._seen_version:
            self._seen_version = self.store.version
            top, bottom = self.index(0, 0), self.index(self.rowCount() - 1, COLUMNS - 1)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    def visible_range(self) -> tuple[int, int]:
        count = min(self.rows * COLUMNS, TABLE_SIZE - self.start)
        return self.start, count

    # ---------------------------------------------------------- Qt model
    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return (
            0
            if parent is not None and parent.isValid()
            else max(0, min(self.rows, (TABLE_SIZE - self.start + COLUMNS - 1) // COLUMNS))
        )

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else COLUMNS

    def _address(self, index: QModelIndex) -> int:
        return self.start + index.row() * COLUMNS + index.column()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        addr = self._address(index)
        if addr >= TABLE_SIZE:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            value = self.store.get(self.table, addr)[0]
            if self.table.is_bits:
                return "1" if value else "0"
            return format_int(value, 16, self.fmt.radix, self.fmt.signed)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        addr = self._address(index)
        try:
            if self.table.is_bits:
                v = 1 if str(value).strip().lower() in ("1", "on", "true", "vrai") else 0
            else:
                v = parse_int(str(value), 16, self.fmt.radix, self.fmt.signed)
        except ValueError:
            return False
        self.store.set(self.table, addr, [v])
        self._seen_version = self.store.version
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return f"+{section}"
        first = self.start + section * COLUMNS
        last = min(first + COLUMNS - 1, TABLE_SIZE - 1)
        p = self.table.prefix
        return f"{p}{first + 1:05d}-{p}{last + 1:05d}"


class Led(QLabel):
    """Voyant rond : allumé un court instant à chaque événement."""

    def __init__(self, text: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._color = color
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._off)
        self._off()

    def blink(self, ms: int = 150) -> None:
        self.setStyleSheet(f"font-weight: bold; color: {self._color};")
        self._timer.start(ms)

    def _off(self) -> None:
        self.setStyleSheet("font-weight: bold; color: #555;")


def parse_slave_ids(text: str) -> set[int]:
    """« 1-5, 10, 20 » -> {1,2,3,4,5,10,20}. Lève ValueError si vide ou hors 1..247."""
    ids: set[int] = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            ids.update(range(lo, hi + 1))
        else:
            ids.add(int(part))
    if not ids or any(not 1 <= i <= 247 for i in ids):
        raise ValueError("Adresses esclaves : valeurs entre 1 et 247, ex. « 1-5, 10 »")
    return ids


class SlavePage(QWidget):
    start_requested = Signal(object)  # SlaveConfig
    stop_requested = Signal()
    status_message = Signal(str)

    def __init__(self, store: DataStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._serving = False
        self.model = RegisterTableModel(store, self)

        # ---------------------------------------------------------- serveur
        self.slave_ids = QLineEdit("1")
        self.slave_ids.setMaximumWidth(140)
        self.slave_ids.setToolTip(tr("Adresses servies, ex. « 1-5, 10 »"))
        self.delay = QSpinBox()
        self.delay.setRange(0, 5000)
        self.delay.setSuffix(" ms")
        self.delay.setToolTip(tr("Délai avant chaque réponse (simule un esclave lent)"))
        self.drop = QSpinBox()
        self.drop.setRange(0, 100)
        self.drop.setSuffix(" %")
        self.drop.setToolTip(tr("Part des requêtes volontairement ignorées (simule des timeouts)"))
        self.corrupt = QSpinBox()
        self.corrupt.setRange(0, 100)
        self.corrupt.setSuffix(" %")
        self.corrupt.setToolTip(tr("Part des réponses au CRC volontairement faux (simule du bruit)"))
        self.read_only = QCheckBox(tr("Lecture seule"))
        self.start_btn = QPushButton(tr("DÉMARRER SERVEUR"))
        self.stop_btn = QPushButton(tr("ARRÊTER"))
        self.stop_btn.setEnabled(False)
        self.rx_led = Led(tr("RX"), "#2ea043")
        self.tx_led = Led(tr("TX"), "#e5534b")
        self.counters_label = QLabel(tr("Serveur arrêté"))

        server_row = QHBoxLayout()
        for label, w in (
            ("Esclaves", self.slave_ids),
            ("Délai", self.delay),
            ("Pertes", self.drop),
            ("CRC faux", self.corrupt),
        ):
            server_row.addWidget(QLabel(label))
            server_row.addWidget(w)
        server_row.addWidget(self.read_only)
        server_row.addSpacing(12)
        server_row.addWidget(self.start_btn)
        server_row.addWidget(self.stop_btn)
        server_row.addSpacing(12)
        server_row.addWidget(self.rx_led)
        server_row.addWidget(self.tx_led)
        server_row.addStretch(1)
        server_row.addWidget(self.counters_label)

        # ------------------------------------------------------------ table
        self.table_kind = QComboBox()
        for t in Table:
            self.table_kind.addItem(tr(t.label), t)
        self.table_kind.setCurrentIndex(list(Table).index(Table.HOLDING_REGISTERS))
        self.fmt = QComboBox()
        for f in CellFormat:
            self.fmt.addItem(tr(f.label), f)
        self.start = QSpinBox()
        self.start.setRange(0, TABLE_SIZE - COLUMNS)
        self.start.setSingleStep(COLUMNS)
        self.rows = QSpinBox()
        self.rows.setRange(1, TABLE_SIZE // COLUMNS)
        self.rows.setValue(100)
        self.fill_value = QSpinBox()
        self.fill_value.setRange(0, 65535)
        self.fill_btn = QPushButton(tr("REMPLIR la plage visible"))
        self.zero_btn = QPushButton(tr("RAZ table"))
        self.animation = QComboBox()
        self.animation.addItem(tr("Aucune animation"), "none")
        self.animation.addItem(tr("Incrémenter la plage visible"), "inc")
        self.animation.addItem(tr("Incrémenter de 10"), "inc10")
        self.anim_period = QSpinBox()
        self.anim_period.setRange(100, 60000)
        self.anim_period.setValue(1000)
        self.anim_period.setSuffix(" ms")

        table_row = QHBoxLayout()
        for label, w in (
            ("Table", self.table_kind),
            ("Format", self.fmt),
            ("Début", self.start),
            ("Lignes", self.rows),
        ):
            table_row.addWidget(QLabel(label))
            table_row.addWidget(w)
        table_row.addSpacing(12)
        table_row.addWidget(QLabel(tr("Valeur")))
        table_row.addWidget(self.fill_value)
        table_row.addWidget(self.fill_btn)
        table_row.addWidget(self.zero_btn)
        table_row.addSpacing(12)
        table_row.addWidget(self.animation)
        table_row.addWidget(self.anim_period)
        table_row.addStretch(1)

        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.view.verticalHeader().setDefaultSectionSize(22)
        self.view.setAlternatingRowColors(False)

        self.log_panel = LogPanel()
        self.log_enabled = QCheckBox(tr("Journaliser les requêtes"))
        self.log_enabled.setChecked(True)
        log_head = QHBoxLayout()
        log_head.addWidget(self.log_enabled)
        log_head.addStretch(1)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addLayout(log_head)
        bl.addWidget(self.log_panel)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.view)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(server_row)
        layout.addWidget(sep)
        layout.addLayout(table_row)
        layout.addWidget(splitter, 1)

        # ---------------------------------------------------------- signaux
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self.stop_requested)
        for w in (self.table_kind, self.fmt):
            w.currentIndexChanged.connect(lambda _i: self._reconfigure())
        self.start.valueChanged.connect(lambda _v: self._reconfigure())
        self.rows.valueChanged.connect(lambda _v: self._reconfigure())
        self.fill_btn.clicked.connect(self._fill)
        self.zero_btn.clicked.connect(self._zero)
        self.animation.currentIndexChanged.connect(lambda _i: self._update_animation())
        self.anim_period.valueChanged.connect(lambda _v: self._update_animation())
        self.log_panel.copied.connect(
            lambda n: self.status_message.emit(tr("Journal esclave copié ({p0} lignes)").format(p0=n))
        )

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.model.refresh_if_changed)
        self._refresh_timer.start(300)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate)
        self._reconfigure()

    # ============================================================== config
    def config(self) -> SlaveConfig:
        return SlaveConfig(
            slave_ids=parse_slave_ids(self.slave_ids.text()),
            response_delay_ms=float(self.delay.value()),
            drop_ratio=self.drop.value() / 100,
            corrupt_ratio=self.corrupt.value() / 100,
            read_only=self.read_only.isChecked(),
        )

    def _start(self) -> None:
        try:
            cfg = self.config()
        except ValueError as exc:
            self.status_message.emit(str(exc))
            self.log_panel.console.log_error(str(exc))
            return
        self.start_requested.emit(cfg)

    def on_started(self, settings: LinkSettings) -> None:
        self._serving = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        for w in (self.slave_ids, self.delay, self.drop, self.corrupt, self.read_only):
            w.setEnabled(False)
        self.counters_label.setText(tr("Serveur actif sur {p0}").format(p0=settings.summary()))
        self.log_panel.console.log_info(
            f"Serveur esclave démarré sur {settings.summary()} - adresses {self.slave_ids.text()}"
        )
        self.status_message.emit(tr("Serveur esclave actif sur {p0}").format(p0=settings.summary()))

    def on_stopped(self) -> None:
        self._serving = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for w in (self.slave_ids, self.delay, self.drop, self.corrupt, self.read_only):
            w.setEnabled(True)
        self.counters_label.setText(tr("Serveur arrêté"))
        self.log_panel.console.log_info(tr("Serveur esclave arrêté"))

    def set_available(self, available: bool) -> None:
        self.start_btn.setEnabled(available and not self._serving)

    @property
    def serving(self) -> bool:
        return self._serving

    # ============================================================= trafic
    def on_handled(self, result: HandledRequest, counters) -> None:
        self.rx_led.blink()
        if result.response is not None:
            self.tx_led.blink()
        self.counters_label.setText(
            f"Requêtes {counters.requests}  |  réponses {counters.responses}  |  exceptions {counters.exceptions}  |  "
            f"écritures {counters.writes}  |  ignorées {counters.ignored}  |  perdues {counters.dropped}  |  "
            f"corrompues {counters.corrupted}"
        )
        if not self.log_enabled.isChecked():
            return
        console = self.log_panel.console
        req = result.request.hex(" ").upper()
        resp = result.response.hex(" ").upper() if result.response is not None else "-"
        who = f"Esc {result.slave_id}" if result.slave_id is not None else "?"
        fc = f"FC{result.function:02X}" if result.function is not None else ""
        line = f"{who:<8}{fc:<6} RX {req}  TX {resp}  {tr(result.kind)}" + (
            f" ({result.detail})" if result.detail else ""
        )
        if result.kind in ("réponse", "broadcast"):
            console.log_info(line)
        else:
            console.log_error(line)

    def on_store_changed(self) -> None:
        self.model.refresh_if_changed()

    # ============================================================== table
    def _reconfigure(self) -> None:
        self.model.configure(
            self.table_kind.currentData(), self.start.value(), self.rows.value(), self.fmt.currentData()
        )
        self.fill_value.setMaximum(1 if self.table_kind.currentData().is_bits else 65535)

    def _fill(self) -> None:
        start, count = self.model.visible_range()
        self.store.fill(self.model.table, self.fill_value.value(), start, count)
        self.model.refresh_if_changed()

    def _zero(self) -> None:
        self.store.fill(self.model.table, 0)
        self.model.refresh_if_changed()

    def _update_animation(self) -> None:
        if self.animation.currentData() == "none":
            self._anim_timer.stop()
        else:
            self._anim_timer.start(self.anim_period.value())

    def _animate(self) -> None:
        start, count = self.model.visible_range()
        step = 10 if self.animation.currentData() == "inc10" else 1
        self.store.increment(self.model.table, start, count, step)
        self.model.refresh_if_changed()
