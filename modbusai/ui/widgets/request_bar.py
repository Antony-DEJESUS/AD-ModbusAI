"""Bandeau de requête : N° esclave, registre, longueur, type (code fonction), adresse, mode."""

from __future__ import annotations

import enum

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QSpinBox, QWidget

from modbusai.i18n import tr
from modbusai.modbus.codec import Radix
from modbusai.modbus.pdu import MAX_READ_BITS, MAX_READ_REGISTERS
from modbusai.modbus.records import FunctionCode


class RegisterType(enum.Enum):
    """Les quatre « Type » de Modbus Doctor, avec le FC de lecture, les FC
    d'écriture (simple / multiple) et le préfixe d'adresse affiché."""

    COIL = (
        "1 Coil status",
        FunctionCode.READ_COILS,
        FunctionCode.WRITE_SINGLE_COIL,
        FunctionCode.WRITE_MULTIPLE_COILS,
        "0",
    )
    INPUT_STATUS = ("2 Input status", FunctionCode.READ_DISCRETE_INPUTS, None, None, "1")
    HOLDING = (
        "3 Holding registers",
        FunctionCode.READ_HOLDING_REGISTERS,
        FunctionCode.WRITE_SINGLE_REGISTER,
        FunctionCode.WRITE_MULTIPLE_REGISTERS,
        "4",
    )
    INPUT_REGISTER = ("4 Input registers", FunctionCode.READ_INPUT_REGISTERS, None, None, "3")

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def read_function(self) -> FunctionCode:
        return self.value[1]

    def write_function(self, count: int) -> FunctionCode | None:
        return self.value[2] if count == 1 else self.value[3]

    @property
    def address_prefix(self) -> str:
        return self.value[4]

    @property
    def is_bits(self) -> bool:
        return self in (RegisterType.COIL, RegisterType.INPUT_STATUS)

    @property
    def writable(self) -> bool:
        return self.value[2] is not None


class RequestBar(QFrame):
    changed = Signal()  # un champ a changé (esclave, registre, longueur, type)
    radix_changed = Signal(object)  # Radix

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")  # carte de la charte (ui/style.py)

        self.slave = QSpinBox()
        self.slave.setRange(0, 247)
        self.slave.setValue(1)
        self.register = QSpinBox()
        self.register.setRange(0, 65535)
        self.count = QSpinBox()
        self.count.setRange(1, MAX_READ_REGISTERS)
        self.count.setValue(1)
        self.reg_type = QComboBox()
        for t in RegisterType:
            self.reg_type.addItem(tr(t.label), t)
        self.reg_type.setCurrentIndex(list(RegisterType).index(RegisterType.HOLDING))
        self.address = QLabel()
        self.address.setStyleSheet("font-weight: bold;")
        self.radix = QComboBox()
        for r in Radix:
            self.radix.addItem(tr(r.value), r)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        fields = (
            ("N° Esclave", self.slave),
            ("Register", self.register),
            ("Longueur", self.count),
            ("Type", self.reg_type),
        )
        for label, w in fields:
            layout.addWidget(QLabel(label))
            layout.addWidget(w)
        layout.addWidget(QLabel(tr("Adresse :")))
        layout.addWidget(self.address)
        layout.addWidget(QLabel(tr("Mode")))
        layout.addWidget(self.radix)
        layout.addStretch(1)

        self.slave.valueChanged.connect(self.changed)
        self.register.valueChanged.connect(self._update_address)
        self.register.valueChanged.connect(self.changed)
        self.count.valueChanged.connect(self.changed)
        self.reg_type.currentIndexChanged.connect(self._on_type_changed)
        self.radix.currentIndexChanged.connect(lambda _i: self.radix_changed.emit(self.radix.currentData()))
        self._update_address()

    # --------------------------------------------------------------- lecture
    @property
    def current_type(self) -> RegisterType:
        return self.reg_type.currentData()

    @property
    def current_radix(self) -> Radix:
        return self.radix.currentData()

    def _on_type_changed(self) -> None:
        t = self.current_type
        self.count.setMaximum(MAX_READ_BITS if t.is_bits else MAX_READ_REGISTERS)
        self._update_address()
        self.changed.emit()

    def _update_address(self) -> None:
        # Convention Modbus Doctor : préfixe de type + adresse 1-based sur 5 chiffres (400001 = holding 0)
        self.address.setText(f"{self.current_type.address_prefix}{self.register.value() + 1:05d}")
