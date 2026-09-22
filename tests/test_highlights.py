"""Surlignages configurables : réglages persistants, retour à la charte.

La règle du projet reste tenue : la charte AD fournit les couleurs par défaut,
l'utilisateur ne fait que s'y substituer, et « Rétablir la charte » revient à
la source unique.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modbusai.ui import highlights  # noqa: E402
from modbusai.ui.highlights import Highlight  # noqa: E402
from modbusai.ui.palette import color  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def charte(app):
    highlights.reset_all()
    yield
    highlights.reset_all()


def test_every_highlight_has_a_usable_card():
    entries = highlights.catalogue()
    assert {e.key for e in entries} == set(Highlight)
    for entry in entries:
        assert entry.label.strip() and entry.description.strip()
        assert entry.animated == (entry.seconds is not None)


def test_defaults_come_from_the_house_style():
    for entry in highlights.catalogue():
        assert highlights.enabled(entry.key)
        assert not highlights.is_custom(entry.key)
        assert highlights.base_color(entry.key).name() == QColor(color(entry.state)).name()
        assert highlights.seconds(entry.key) == (entry.seconds or 0.0)


def test_a_chosen_colour_survives_and_can_be_given_back():
    key = Highlight.MASTER_CHANGE
    charte_color = highlights.base_color(key).name()
    highlights.set_color(key, QColor("#123456"))
    assert highlights.is_custom(key)
    assert highlights.base_color(key).name() == "#123456"
    highlights.set_color(key, None)
    assert not highlights.is_custom(key)
    assert highlights.base_color(key).name() == charte_color


def test_an_unreadable_stored_colour_falls_back_instead_of_crashing():
    key = Highlight.SLAVE_ACCESS
    QSettings().setValue("highlights/esclave_acces/color", "pas une couleur")
    assert highlights.base_color(key).name() == QColor(color(highlights.spec(key).state)).name()


def test_a_disabled_highlight_yields_no_colour_at_all():
    key = Highlight.MASTER_CHANGE
    assert highlights.tint(key, 1.0) is not None
    highlights.set_enabled(key, False)
    assert highlights.tint(key, 1.0) is None
    assert highlights.foreground(key) is None


def test_the_duration_is_kept_within_sane_bounds():
    key = Highlight.MASTER_CHANGE
    highlights.set_seconds(key, 12.5)
    assert highlights.seconds(key) == 12.5
    highlights.set_seconds(key, 0.0)  # trop court pour être vu
    assert highlights.seconds(key) == 0.5
    highlights.set_seconds(key, 9999.0)  # un surlignage n'est pas un état permanent
    assert highlights.seconds(key) == 60.0


def test_a_permanent_marking_has_no_duration():
    assert highlights.seconds(Highlight.MASTER_STALE) == 0.0


def test_the_tint_fades_with_the_remaining_time():
    key = Highlight.MASTER_CHANGE
    fresh = highlights.tint(key, 1.0)
    old = highlights.tint(key, 0.1)
    assert fresh is not None and old is not None
    assert fresh.alpha() > old.alpha()
    assert fresh.name() == old.name()  # même teinte, seule l'opacité change


def test_reset_gives_everything_back():
    highlights.set_enabled(Highlight.MASTER_CHANGE, False)
    highlights.set_color(Highlight.MASTER_CHANGE, QColor("#abcdef"))
    highlights.set_seconds(Highlight.MASTER_CHANGE, 30.0)
    highlights.reset(Highlight.MASTER_CHANGE)
    assert highlights.enabled(Highlight.MASTER_CHANGE)
    assert not highlights.is_custom(Highlight.MASTER_CHANGE)
    assert highlights.seconds(Highlight.MASTER_CHANGE) == 5.0
