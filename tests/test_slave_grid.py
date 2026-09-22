"""Grille du serveur esclave : ce qui change s'éclaire, les lignes vides se masquent.

Le modèle se teste sans fenêtre ni port : il ne dépend que du DataStore.
"""

from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PySide6", reason="Qt requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modbusai.modbus.slave import DataStore, Table  # noqa: E402
from modbusai.ui.pages.slave_page import (  # noqa: E402
    CHANGE_FLASH_S,
    COLUMNS,
    READ_FLASH_S,
    CellFormat,
    RegisterTableModel,
)

HOLDING = Table.HOLDING_REGISTERS


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def model(app):
    store = DataStore()
    grid = RegisterTableModel(store)
    grid.configure(HOLDING, 0, 5, CellFormat.DEC_SIGNED)
    return grid


def test_a_changed_value_lights_up_green_for_longer_than_a_read(model):
    """Un changement doit survivre au temps qu'on met à regarder ailleurs."""
    model.store.set(HOLDING, 3, [42])
    model.refresh_if_changed()
    end, changed = model._touched[(HOLDING, 3)]
    assert changed
    assert end - time.monotonic() > READ_FLASH_S  # plus long qu'une simple lecture
    assert end - time.monotonic() <= CHANGE_FLASH_S

    model.touch(HOLDING, 10, 1)  # lecture seule
    end_read, changed_read = model._touched[(HOLDING, 10)]
    assert not changed_read
    assert end_read - time.monotonic() <= READ_FLASH_S


def test_a_read_never_downgrades_a_change_in_progress(model):
    """Une écriture est suivie de lectures : le vert ne doit pas être écrasé."""
    model.store.set(HOLDING, 0, [7])
    model.refresh_if_changed()
    model.touch(HOLDING, 0, COLUMNS)  # le maître relit la zone juste après
    assert model._touched[(HOLDING, 0)][1] is True


def test_an_unchanged_value_does_not_light_up(model):
    model.store.set(HOLDING, 0, [5])
    model.refresh_if_changed()
    model._touched.clear()
    model.store.set(HOLDING, 0, [5])  # même valeur réécrite
    model.refresh_if_changed()
    assert not model._touched


def test_an_operator_edit_does_not_light_up(model):
    """La valeur vient de l'opérateur : inutile de la lui signaler."""
    model.setData(model.index(0, 0), "1234")
    model.refresh_if_changed()
    assert not model._touched


def test_hiding_zero_rows_keeps_only_the_rows_that_carry_something(model):
    model.store.set(HOLDING, 0, [0] * 50)
    model.store.set(HOLDING, 12, [7])  # ligne 1
    model.store.set(HOLDING, 44, [9])  # ligne 4
    model.set_hide_zero_rows(True)
    assert model.rowCount() == 2
    # les adresses affichées restent celles des lignes retenues
    assert model._address(model.index(0, 2)) == 12
    assert model._address(model.index(1, 4)) == 44
    # l'en-tête suit la ligne retenue : la première affichée est celle des adresses 10 à 19
    assert model.headerData(0, Qt.Orientation.Vertical) == "400011-400020"
    assert model.headerData(1, Qt.Orientation.Vertical) == "400041-400050"

    model.set_hide_zero_rows(False)
    assert model.rowCount() == 5
    assert model._address(model.index(1, 2)) == 12


def test_a_value_becoming_non_zero_makes_its_row_appear(model):
    model.store.set(HOLDING, 0, [0] * 50)
    model.set_hide_zero_rows(True)
    assert model.rowCount() == 0

    model.store.set(HOLDING, 25, [3])
    model.refresh_if_changed()
    assert model.rowCount() == 1
    assert model._address(model.index(0, 5)) == 25


def test_the_flash_map_follows_the_filtered_rows(model):
    """Avec le filtre, la ligne éclairée n'est plus la ligne d'origine."""
    model.store.set(HOLDING, 0, [0] * 50)
    model.store.set(HOLDING, 30, [1])
    model.set_hide_zero_rows(True)
    assert model._row_of(30) == 0  # seule ligne affichée
    assert model._row_of(5) is None  # ligne masquée
    assert model._row_of(90_000) is None  # hors plage
