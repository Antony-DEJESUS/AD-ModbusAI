"""Grille de l'onglet MAÎTRE : ce qui change s'éclaire, les zéros se masquent.

Le point qui compte pour la sécurité : masquer une ligne ne doit pas la retirer
de la grille. L'écriture relit toutes les lignes pour composer les valeurs
envoyées ; en supprimer décalerait ce qui part dans l'automate.
"""

from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PySide6", reason="Qt requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modbusai.modbus.codec import DisplayMode, DisplayOptions, format_bits, format_registers  # noqa: E402
from modbusai.ui import highlights  # noqa: E402
from modbusai.ui.highlights import Highlight  # noqa: E402
from modbusai.ui.pages.master_page import _rows_covering, _zero_rows  # noqa: E402
from modbusai.ui.widgets.register_grid import RegisterGrid  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def charte():
    """Chaque test part des réglages d'origine : les surlignages sont persistés."""
    highlights.reset_all()
    yield
    highlights.reset_all()


@pytest.fixture
def grid(app):
    return RegisterGrid()


def lit(grid, row: int, col: int = 1) -> bool:
    """Une cellule sans fond rend un pinceau « aucun » : c'est son style qui dit
    s'il y a une couleur, pas l'alpha de sa couleur par défaut."""
    return grid.item(row, col).background().style() != Qt.BrushStyle.NoBrush


def rows_16bits(values, start=0):
    return format_registers(values, start, DisplayOptions(mode=DisplayMode.WORD16))


# ------------------------------------------------------------- correspondance
def test_a_changed_register_lights_its_row():
    rows = rows_16bits([10, 20, 30, 40])
    assert _rows_covering(rows, 0, {2}) == {2}
    assert _rows_covering(rows, 0, {0, 3}) == {0, 3}
    assert _rows_covering(rows, 0, set()) == set()


def test_a_32_bit_row_lights_when_either_of_its_registers_moves():
    """Une ligne couvre deux registres en mot 32 bits : un seul suffit."""
    rows = format_registers([1, 2, 3, 4], 0, DisplayOptions(mode=DisplayMode.FLOAT32))
    assert len(rows) == 2
    assert _rows_covering(rows, 0, {1}) == {0}  # poids faible du premier couple
    assert _rows_covering(rows, 0, {3}) == {1}


def test_the_offsets_are_read_from_the_start_address():
    rows = rows_16bits([1, 2, 3], start=100)
    assert _rows_covering(rows, 100, {1}) == {1}


def test_zero_rows_are_flagged_per_covered_register():
    rows = rows_16bits([0, 5, 0])
    assert _zero_rows(rows, [0, 5, 0], 0) == [True, False, True]
    # en 32 bits, une ligne n'est nulle que si ses deux registres le sont
    rows32 = format_registers([0, 0, 0, 7], 0, DisplayOptions(mode=DisplayMode.FLOAT32))
    assert _zero_rows(rows32, [0, 0, 0, 7], 0) == [True, False]


def test_bits_are_handled_like_registers():
    rows = format_bits([0, 1, 0], 0)
    assert _zero_rows(rows, [0, 1, 0], 0) == [True, False, True]
    assert _rows_covering(rows, 0, {1}) == {1}


# ------------------------------------------------------------------- grille
def test_hidden_rows_stay_in_the_grid_so_a_write_sends_the_right_values(grid):
    """Le piège : filtrer l'affichage ne doit pas changer ce qui est écrit."""
    values = [0, 1234, 0, 56]
    grid.show_rows(rows_16bits(values), zeros=_zero_rows(rows_16bits(values), values, 0))
    grid.set_hide_zeros(True)

    assert grid.rowCount() == 4  # toutes les lignes sont là
    assert [grid.isRowHidden(i) for i in range(4)] == [True, False, True, False]
    assert grid.value_texts() == ["0", "1234", "0", "56"]  # l'écriture voit tout

    grid.set_hide_zeros(False)
    assert not any(grid.isRowHidden(i) for i in range(4))


def test_the_filter_survives_the_next_read(grid):
    """La grille est reconstruite à chaque lecture : le filtre doit tenir."""
    values = [0, 7]
    grid.show_rows(rows_16bits(values), zeros=_zero_rows(rows_16bits(values), values, 0))
    grid.set_hide_zeros(True)
    assert grid.isRowHidden(0)

    values = [0, 8]  # nouvelle lecture, le zéro est toujours là
    grid.show_rows(rows_16bits(values), zeros=_zero_rows(rows_16bits(values), values, 0))
    assert grid.isRowHidden(0) and not grid.isRowHidden(1)

    values = [9, 8]  # la valeur cesse d'être nulle : la ligne réapparaît
    grid.show_rows(rows_16bits(values), zeros=_zero_rows(rows_16bits(values), values, 0))
    assert not grid.isRowHidden(0)


def test_a_flash_colours_the_whole_row_and_fades(grid):
    grid.show_rows(rows_16bits([1, 2]))
    grid.flash({1})
    assert all(lit(grid, 1, col) for col in range(grid.columnCount()))  # toute la ligne
    assert not lit(grid, 0)  # ligne non concernée
    assert grid._flash_until[1] - time.monotonic() > highlights.seconds(Highlight.MASTER_CHANGE) - 1


def test_a_flash_survives_the_next_read(grid):
    """En lecture cyclique la grille est refaite sans cesse : le vert doit rester."""
    grid.show_rows(rows_16bits([1, 2]))
    grid.flash({0})
    grid.show_rows(rows_16bits([3, 2]))
    assert lit(grid, 0)


def test_changing_the_request_clears_the_flashes(grid):
    grid.show_rows(rows_16bits([1, 2]))
    grid.flash({0, 1})
    grid.clear_flashes()
    assert not grid._flash_until
    assert not lit(grid, 0) and not lit(grid, 1)


# --------------------------------------------------- surlignages configurables
def test_a_disabled_highlight_never_lights_anything(grid):
    highlights.set_enabled(Highlight.MASTER_CHANGE, False)
    grid.show_rows(rows_16bits([1, 2]))
    grid.flash({0, 1})
    assert not grid._flash_until
    assert not lit(grid, 0)


def test_turning_a_highlight_off_clears_what_was_lit(grid):
    grid.show_rows(rows_16bits([1, 2]))
    grid.flash({0})
    assert lit(grid, 0)
    highlights.set_enabled(Highlight.MASTER_CHANGE, False)
    grid.refresh_highlights()
    assert not lit(grid, 0)


def test_a_chosen_colour_replaces_the_charte_one(grid):
    from PySide6.QtGui import QColor

    assert not highlights.is_custom(Highlight.MASTER_CHANGE)
    charte = highlights.base_color(Highlight.MASTER_CHANGE)
    highlights.set_color(Highlight.MASTER_CHANGE, QColor(200, 30, 90))
    assert highlights.is_custom(Highlight.MASTER_CHANGE)
    assert highlights.base_color(Highlight.MASTER_CHANGE).name() == QColor(200, 30, 90).name()

    grid.show_rows(rows_16bits([1]))
    grid.flash({0})
    shown = grid.item(0, 1).background().color()
    assert (shown.red(), shown.green(), shown.blue()) == (200, 30, 90)

    highlights.set_color(Highlight.MASTER_CHANGE, None)  # retour à la charte
    assert not highlights.is_custom(Highlight.MASTER_CHANGE)
    assert highlights.base_color(Highlight.MASTER_CHANGE).name() == charte.name()


def test_the_duration_is_the_configured_one(grid):
    highlights.set_seconds(Highlight.MASTER_CHANGE, 12.0)
    grid.show_rows(rows_16bits([1]))
    grid.flash({0})
    assert grid._flash_until[0] - time.monotonic() > 11
