"""Onglet ESCLAVE : serveur esclave RTU façon Mod_RSsim (table par blocs de 10, voyants, journal)."""

from __future__ import annotations

import enum
import time
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor
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
from modbusai.transport.netinfo import is_wildcard, local_ipv4_addresses
from modbusai.transport.records import LinkSettings, Parity, SerialSettings, TcpSettings
from modbusai.ui.iconography import set_icon
from modbusai.ui.metrics import line_height, text_width, use_tabular_figures
from modbusai.ui.palette import State, color
from modbusai.ui.style import PAGE_MARGINS
from modbusai.ui.widgets.labels import section
from modbusai.ui.widgets.log_console import SLAVE_COLUMNS, LogPanel
from modbusai.ui.widgets.stat_tiles import StatTiles

COLUMNS = 10
READ_FLASH_S = 2.0
"""Une cellule simplement lue par le maître s'éclaire d'une teinte discrète :
sous une supervision qui interroge en boucle, tout le tableau serait sinon
allumé en permanence et les vrais événements se perdraient dedans."""

CHANGE_FLASH_S = 5.0
"""Une valeur qui CHANGE s'éclaire en vert franc, plus longtemps : c'est le
signal qu'on cherche en phase de test, il doit survivre au temps qu'on met à
regarder ailleurs."""


def listen_description(settings: LinkSettings) -> str:
    """Adresse d'écoute en clair : 0.0.0.0 ne dit pas au technicien quelle
    adresse donner au superviseur, on ajoute les adresses de la machine."""
    if not isinstance(settings, TcpSettings):
        return settings.summary()
    if not is_wildcard(settings.host):
        return f"{settings.host}:{settings.port}"
    text = tr("toutes les interfaces, port {p0}").format(p0=settings.port)
    addresses = local_ipv4_addresses()
    if addresses:
        joignable = ", ".join(f"{ip}:{settings.port}" for ip in addresses)
        text += tr(" - joignable sur {p0}").format(p0=joignable)
    return text


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
        # (table, adresse) -> (instant de fin d'animation, la valeur a changé)
        self._touched: dict[tuple[Table, int], tuple[float, bool]] = {}
        self._snapshot: list[int] = []  # valeurs de la plage visible, pour repérer ce qui change
        self._snapshot_key: tuple[Table, int, int] | None = None
        self.hide_zero_rows = False
        self._rows_map: list[int] | None = None  # décalages de ligne affichés quand on filtre

    # ------------------------------------------------------- animation
    def touch(self, table: Table, address: int, count: int, changed: bool = False) -> None:
        """Marque une zone lue par un maître, ou dont la valeur vient de changer.

        Un changement l'emporte toujours sur une simple lecture : une écriture
        touche la même zone que la lecture qui la suit, et c'est le changement
        qu'il faut voir.
        """
        end = time.monotonic() + (CHANGE_FLASH_S if changed else READ_FLASH_S)
        for addr in range(address, min(address + count, TABLE_SIZE)):
            previous = self._touched.get((table, addr))
            if previous is not None and previous[1] and not changed:
                continue  # ne pas rabaisser un changement en cours au rang de lecture
            self._touched[(table, addr)] = (end, changed)

    def flashing(self) -> bool:
        return bool(self._touched)

    def tick_flashes(self) -> None:
        """Rafraîchit les lignes animées et oublie celles qui sont éteintes."""
        now = time.monotonic()
        expired = [key for key, (end, _) in self._touched.items() if end <= now]
        for key in expired:
            del self._touched[key]
        rows = set()
        for table, addr in list(self._touched) + expired:
            if table is not self.table:
                continue
            row = self._row_of(addr)
            if row is not None:
                rows.add(row)
        for row in rows:
            if 0 <= row < self.rowCount():
                self.dataChanged.emit(
                    self.index(row, 0), self.index(row, COLUMNS - 1), [Qt.ItemDataRole.BackgroundRole]
                )

    def _flash_color(self, table: Table, address: int) -> QColor | None:
        touched = self._touched.get((table, address))
        if touched is None:
            return None
        end, changed = touched
        span = CHANGE_FLASH_S if changed else READ_FLASH_S
        remaining = end - time.monotonic()
        if remaining <= 0:
            return None
        tint = QColor(color(State.OK if changed else State.MUTED))
        peak = 0.60 if changed else 0.26  # une lecture reste discrète, un changement saute aux yeux
        tint.setAlphaF(min(1.0, 0.10 + (peak - 0.10) * (remaining / span)))  # s'estompe en douceur
        return tint

    # ------------------------------------------------------------- config
    def configure(self, table: Table, start: int, rows: int, fmt: CellFormat, hide_zero_rows: bool = False) -> None:
        self.beginResetModel()
        self.table, self.start, self.rows, self.fmt = table, start, rows, fmt
        self.hide_zero_rows = hide_zero_rows
        self._resync(rebuild_rows=True)
        self.endResetModel()

    def refresh_if_changed(self) -> None:
        """Compare la plage visible à sa photo précédente : ce qui a bougé
        s'éclaire. Fonctionne quelle que soit l'origine du changement, écriture
        d'un maître, remplissage ou animation."""
        if self.store.version == self._seen_version:
            return
        self._seen_version = self.store.version
        start, count = self.visible_range()
        values = self.store.get(self.table, start, count)
        if self._snapshot_key == (self.table, start, count):
            for offset, (before, now) in enumerate(zip(self._snapshot, values, strict=False)):
                if before != now:
                    self.touch(self.table, start + offset, 1, changed=True)
        self._snapshot_key = (self.table, start, count)
        self._snapshot = values
        if self.hide_zero_rows and self._rebuild_rows():
            return  # les lignes visibles ont changé : le modèle a été réinitialisé
        top, bottom = self.index(0, 0), self.index(max(0, self.rowCount() - 1), COLUMNS - 1)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    def visible_range(self) -> tuple[int, int]:
        count = min(self.rows * COLUMNS, TABLE_SIZE - self.start)
        return self.start, count

    # ------------------------------------------------- lignes tout à zéro
    def set_hide_zero_rows(self, hide: bool) -> None:
        if hide == self.hide_zero_rows:
            return
        self.beginResetModel()
        self.hide_zero_rows = hide
        self._resync(rebuild_rows=True)
        self.endResetModel()

    def _resync(self, rebuild_rows: bool = False) -> None:
        """Reprend la photo de la plage visible sans rien éclairer : après un
        changement de plage ou une saisie, il n'y a pas de « changement » à
        signaler, seulement une nouvelle référence."""
        start, count = self.visible_range()
        self._snapshot = self.store.get(self.table, start, count)
        self._snapshot_key = (self.table, start, count)
        self._seen_version = self.store.version
        if rebuild_rows:
            self._rows_map = self._zero_free_rows() if self.hide_zero_rows else None

    def _zero_free_rows(self) -> list[int]:
        """Décalages des lignes qui portent au moins une valeur non nulle."""
        start, count = self.visible_range()
        values = self.store.get(self.table, start, count)
        return [
            row
            for row in range((count + COLUMNS - 1) // COLUMNS)
            if any(values[row * COLUMNS : (row + 1) * COLUMNS])
        ]

    def _rebuild_rows(self) -> bool:
        """Recalcule les lignes visibles ; True si elles ont changé (le modèle
        a alors été réinitialisé, l'appelant n'a plus rien à émettre)."""
        wanted = self._zero_free_rows()
        if wanted == self._rows_map:
            return False
        self.beginResetModel()
        self._rows_map = wanted
        self.endResetModel()
        return True

    def _row_offset(self, row: int) -> int:
        """Ligne affichée -> décalage réel dans la plage."""
        if self._rows_map is None:
            return row
        return self._rows_map[row] if 0 <= row < len(self._rows_map) else -1

    def _row_of(self, address: int) -> int | None:
        """Adresse -> ligne affichée, ou None si elle n'est pas à l'écran."""
        start, count = self.visible_range()
        if not start <= address < start + count:
            return None
        offset = (address - start) // COLUMNS
        if self._rows_map is None:
            return offset
        try:
            return self._rows_map.index(offset)
        except ValueError:
            return None

    # ---------------------------------------------------------- Qt model
    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        if self._rows_map is not None:
            return len(self._rows_map)
        return max(0, min(self.rows, (TABLE_SIZE - self.start + COLUMNS - 1) // COLUMNS))

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else COLUMNS

    def _address(self, index: QModelIndex) -> int:
        offset = self._row_offset(index.row())
        return TABLE_SIZE if offset < 0 else self.start + offset * COLUMNS + index.column()

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
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._flash_color(self.table, addr)
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
        self._resync()  # la valeur vient de l'opérateur : inutile de la lui signaler
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return f"+{section}"
        offset = self._row_offset(section)
        if offset < 0:
            return None
        first = self.start + offset * COLUMNS
        last = min(first + COLUMNS - 1, TABLE_SIZE - 1)
        p = self.table.prefix
        return f"{p}{first + 1:05d}-{p}{last + 1:05d}"


class Led(QLabel):
    """Voyant : allumé un court instant à chaque événement."""

    def __init__(self, text: str, state: State, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._color = color(state)
        self._state = state
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._off)
        self._off()

    def set_state(self, state: State) -> None:
        self._state = state
        self._color = color(state)
        self._off()

    def blink(self, ms: int = 150) -> None:
        self.setStyleSheet(
            f"color: {self._color}; border: 1px solid {self._color}; border-radius: 9px;"
            " padding: 1px 8px; font-weight: 700;"
        )
        self._timer.start(ms)

    def _off(self) -> None:
        off = color(State.MUTED)
        self.setStyleSheet(f"color: {off}; border: 1px solid {off}; border-radius: 9px; padding: 1px 8px;")


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
    start_requested = Signal(object, object)  # SlaveConfig, LinkSettings
    stop_requested = Signal()
    status_message = Signal(str)
    link_changed = Signal()  # la liaison du serveur a changé : la fenêtre réarbitre les ports

    def __init__(self, store: DataStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._serving = False
        self._tcp = False
        self._clients: tuple[str, ...] = ()
        self.model = RegisterTableModel(store, self)
        # Liaison propre au serveur : il peut tourner en même temps que le maître,
        # sur un autre port (deux adaptateurs, ou un câble croisé entre deux COM).
        self._serial, self._tcp_settings, self._protocol = self._load_link()

        self.link_protocol = QComboBox()
        self.link_protocol.addItems(["RTU", "TCP"])
        self.link_protocol.setCurrentText(self._protocol)
        self.link_protocol.setToolTip(tr("Protocole servi par le serveur esclave"))
        self.link_btn = QPushButton(tr("CONFIGURER"))
        self.link_btn.setToolTip(tr("Port et paramètres du serveur esclave, indépendants de ceux du maître"))
        self.link_summary = QLabel()
        self.link_summary.setProperty("variant", "muted")

        # ---------------------------------------------------------- serveur
        self.slave_ids = QLineEdit("1")
        self.slave_ids.setMaximumWidth(text_width(self, "1-5, 10, 20", extra=28))
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
        self.start_btn.setProperty("variant", "primary")
        self.stop_btn = QPushButton(tr("ARRÊTER"))
        self.stop_btn.setEnabled(False)
        set_icon(self.link_btn, "settings")
        set_icon(self.start_btn, "play", on_accent=True)
        set_icon(self.stop_btn, "stop")
        self.rx_led = Led(tr("RX"), State.OK)
        self.tx_led = Led(tr("TX"), State.ERROR)
        self.tiles = StatTiles(
            (
                ("requests", "REQUÊTES", None),
                ("responses", "RÉPONSES", None),
                ("writes", "ÉCRITURES", None),
                ("exceptions", "EXCEPTIONS", State.WARN),
                ("ignored", "IGNORÉES", State.WARN),
                ("dropped", "PERDUES", State.ERROR),
                ("corrupted", "CORROMPUES", State.ERROR),
            )
        )
        self.link_label = QLabel(tr("Serveur arrêté"))
        self.masters_label = QLabel(tr("Maîtres connectés : -"))
        self.masters_label.setToolTip(tr("Maîtres actuellement connectés au serveur (Modbus TCP)"))

        # Deux bandeaux groupés plutôt qu'une seule ligne de treize contrôles :
        # ce qu'on sert, par quelle liaison, puis ce qu'on simule.
        server_row = QHBoxLayout()
        server_row.setSpacing(8)
        server_row.addWidget(section(tr("ESCLAVES")))
        server_row.addWidget(self.slave_ids)
        server_row.addWidget(self.read_only)
        server_row.addWidget(_vsep())
        server_row.addWidget(section(tr("LIAISON")))
        server_row.addWidget(self.link_protocol)
        server_row.addWidget(self.link_btn)
        server_row.addWidget(self.link_summary)
        server_row.addStretch(1)
        server_row.addWidget(self.start_btn)
        server_row.addWidget(self.stop_btn)
        server_row.addSpacing(8)
        server_row.addWidget(self.rx_led)
        server_row.addWidget(self.tx_led)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(section(tr("DÉFAUTS SIMULÉS")))
        for label, w in (("Délai", self.delay), ("Pertes", self.drop), ("CRC faux", self.corrupt)):
            caption = QLabel(tr(label))
            caption.setProperty("variant", "muted")
            status_row.addWidget(caption)
            status_row.addWidget(w)
        status_row.addWidget(_vsep())
        status_row.addWidget(self.link_label, 1)
        status_row.addWidget(self.masters_label)

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
        self.hide_zeros = QCheckBox(tr("Masquer les lignes à zéro"))
        self.hide_zeros.setToolTip(
            tr("N'affiche que les lignes portant au moins une valeur non nulle : on voit d'un coup ce qui est écrit.")
        )
        self.fill_value = QSpinBox()
        self.fill_value.setRange(0, 65535)
        self.fill_btn = QPushButton(tr("REMPLIR la plage visible"))
        self.zero_btn = QPushButton(tr("RAZ table"))
        set_icon(self.zero_btn, "trash")
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
        table_row.addWidget(self.hide_zeros)
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
        self.view.verticalHeader().setDefaultSectionSize(line_height(self.view, extra=8))
        self.view.setAlternatingRowColors(False)
        use_tabular_figures(self.view)

        self.log_panel = LogPanel(SLAVE_COLUMNS)
        self.log_enabled = QCheckBox(tr("Journaliser les requêtes"))
        self.log_enabled.setChecked(True)
        log_head = QHBoxLayout()
        log_head.addWidget(self.tiles, 1)
        log_head.addWidget(self.log_enabled)

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
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.addLayout(server_row)
        layout.addLayout(status_row)
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
        self.hide_zeros.toggled.connect(self._on_hide_zeros)
        self.fill_btn.clicked.connect(self._fill)
        self.zero_btn.clicked.connect(self._zero)
        self.animation.currentIndexChanged.connect(lambda _i: self._update_animation())
        self.anim_period.valueChanged.connect(lambda _v: self._update_animation())
        self.log_panel.copied.connect(
            lambda n: self.status_message.emit(tr("Journal esclave copié ({p0} lignes)").format(p0=n))
        )

        self.link_btn.clicked.connect(self._configure_link)
        self.link_protocol.currentTextChanged.connect(self._on_protocol_changed)
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._tick_flashes)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start(300)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate)
        self._reconfigure()
        self._show_link()

    def _tick_flashes(self) -> None:
        self.model.tick_flashes()
        if not self.model.flashing():
            self._flash_timer.stop()

    def _refresh_table(self) -> None:
        """Le modèle repère lui-même ce qui a changé : il faut alors que
        l'animation tourne, même si aucune requête n'est passée par la page."""
        self.model.refresh_if_changed()
        self._ensure_flashing()

    def _ensure_flashing(self) -> None:
        if self.model.flashing() and not self._flash_timer.isActive():
            self._flash_timer.start(80)

    def _on_hide_zeros(self, hide: bool) -> None:
        self.model.set_hide_zero_rows(hide)

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
        self.start_requested.emit(cfg, self.link_settings())

    # ============================================================== liaison
    def _on_protocol_changed(self, name: str) -> None:
        self._protocol = name if name in ("RTU", "TCP") else "RTU"
        self._save_link()
        self._show_link()
        self.link_changed.emit()

    def link_settings(self) -> LinkSettings:
        return self._tcp_settings if self._protocol == "TCP" else self._serial

    def _configure_link(self) -> None:
        from modbusai.ui.widgets.config_dialog import ConfigDialog

        dialog = ConfigDialog(self._protocol, self._serial, self._tcp_settings, self)
        dialog.setWindowTitle(tr("Liaison du serveur esclave"))
        if dialog.exec():
            self._serial = dialog.serial_settings()
            self._tcp_settings = dialog.tcp_settings()
            self._save_link()
            self._show_link()
            self.link_changed.emit()

    def _show_link(self) -> None:
        settings = self.link_settings()
        if isinstance(settings, TcpSettings):
            text = tr("TCP, port {p0}").format(p0=settings.port)
        else:
            text = settings.summary() if settings.port else tr("port à choisir")
        self.link_summary.setText(text)

    def _load_link(self) -> tuple[SerialSettings, TcpSettings, str]:
        qs = QSettings()
        serial = SerialSettings(
            port=str(qs.value("slave/port", "")),
            baudrate=int(qs.value("slave/baudrate", 19200)),
            bytesize=int(qs.value("slave/bytesize", 8)),
            parity=Parity(str(qs.value("slave/parity", "N"))),
            stopbits=float(qs.value("slave/stopbits", 1.0)),
        )
        tcp = TcpSettings(host=str(qs.value("slave/host", "")), port=int(qs.value("slave/tcp_port", 502)))
        protocol = str(qs.value("slave/protocol", "RTU"))
        return serial, tcp, protocol if protocol in ("RTU", "TCP") else "RTU"

    def _save_link(self) -> None:
        qs = QSettings()
        qs.setValue("slave/protocol", self._protocol)
        qs.setValue("slave/port", self._serial.port)
        qs.setValue("slave/baudrate", self._serial.baudrate)
        qs.setValue("slave/bytesize", self._serial.bytesize)
        qs.setValue("slave/parity", str(self._serial.parity.value))
        qs.setValue("slave/stopbits", self._serial.stopbits)
        qs.setValue("slave/host", self._tcp_settings.host)
        qs.setValue("slave/tcp_port", self._tcp_settings.port)

    def on_started(self, settings: LinkSettings) -> None:
        self._serving = True
        self._tcp = isinstance(settings, TcpSettings)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        for w in (
            self.slave_ids,
            self.delay,
            self.drop,
            self.corrupt,
            self.read_only,
            self.link_btn,
            self.link_protocol,
        ):
            w.setEnabled(False)
        where = listen_description(settings)
        self._show_link()
        self.link_label.setText(tr("Écoute : {p0}").format(p0=where))
        self.on_clients(())
        self.log_panel.console.log_info(
            tr("Serveur esclave démarré - écoute {p0} - adresses servies {p1}").format(
                p0=where, p1=self.slave_ids.text()
            )
        )
        self.status_message.emit(tr("Serveur esclave actif - écoute {p0}").format(p0=where))

    def on_stopped(self) -> None:
        self._serving = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        for w in (
            self.slave_ids,
            self.delay,
            self.drop,
            self.corrupt,
            self.read_only,
            self.link_btn,
            self.link_protocol,
        ):
            w.setEnabled(True)
        self.link_label.setText(tr("Serveur arrêté"))
        self.masters_label.setText(tr("Maîtres connectés : -"))
        self._clients = ()
        self.log_panel.console.log_info(tr("Serveur esclave arrêté"))

    def _link_widgets(self) -> tuple[QWidget, ...]:
        """Réglages figés pendant que le serveur tourne."""
        return (
            self.slave_ids,
            self.delay,
            self.drop,
            self.corrupt,
            self.read_only,
            self.link_btn,
            self.link_protocol,
        )

    def set_available(self, available: bool, reason: str = "") -> None:
        self.start_btn.setEnabled(available and not self._serving)
        self.start_btn.setToolTip("" if available else reason)

    @property
    def serving(self) -> bool:
        return self._serving

    def repaint_state_colors(self) -> None:
        """Après un changement de thème : voyants et tuiles reprennent les
        nuances du thème courant (elles sont posées en code, pas en QSS)."""
        for led, state in ((self.rx_led, State.OK), (self.tx_led, State.ERROR)):
            led.set_state(state)
        self.tiles.repaint()

    # ====================================================== maîtres connectés
    def on_clients(self, clients: tuple[str, ...]) -> None:
        """Liste des maîtres connectés (Modbus TCP). En RTU, le maître n'est pas
        identifiable : le bus ne porte aucune notion de connexion."""
        clients = tuple(clients)
        if not self._tcp:
            self.masters_label.setText(tr("Maître : non identifiable sur un bus RTU"))
            self._clients = clients
            return
        for name in clients:
            if name not in self._clients:
                self.log_panel.console.log_info(tr("Maître connecté : {p0}").format(p0=name))
        for name in self._clients:
            if name not in clients:
                self.log_panel.console.log_info(tr("Maître déconnecté : {p0}").format(p0=name))
        self._clients = clients
        if clients:
            self.masters_label.setText(
                tr("Maîtres connectés : {p0} ({p1})").format(p0=len(clients), p1=", ".join(clients))
            )
        else:
            self.masters_label.setText(tr("Maîtres connectés : 0 (en attente)"))

    # ============================================================= trafic
    def on_handled(self, result: HandledRequest, counters, client: str = "") -> None:
        self.rx_led.blink()
        if result.access is not None:
            # Ce que le maître vient de lire ou d'écrire s'éclaire en vert
            self.model.touch(result.access.table, result.access.address, result.access.count)
            if not self._flash_timer.isActive():
                self._flash_timer.start(80)
        if result.response is not None:
            self.tx_led.blink()
        self.tiles.set_values(
            {
                "requests": counters.requests,
                "responses": counters.responses,
                "writes": counters.writes,
                "exceptions": counters.exceptions,
                "ignored": counters.ignored,
                "dropped": counters.dropped,
                "corrupted": counters.corrupted,
            }
        )
        if not self.log_enabled.isChecked():
            return
        served = result.kind in ("réponse", "broadcast")
        self.log_panel.console.log_cells(
            (
                datetime.now().strftime("%H:%M:%S.%f")[:-3],
                client or tr("bus RTU"),
                "-" if result.slave_id is None else str(result.slave_id),
                "" if result.function is None else f"{result.function:02X}",
                tr(result.kind),
                f"RX {result.request.hex(' ').upper()}  "
                f"TX {result.response.hex(' ').upper() if result.response is not None else '-'}",
            ),
            state=State.OK if served else State.WARN,
            highlight=4,
            detail=result.detail,
        )

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


def _vsep() -> QFrame:
    """Trait vertical de séparation entre deux groupes de réglages."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.VLine)
    return sep
