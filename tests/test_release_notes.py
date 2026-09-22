"""Publication : le tag, la version du paquet et le CHANGELOG doivent s'accorder.

Un tag qui ne correspond pas livrerait un exécutable mal nommé ; une version
sans section de CHANGELOG livrerait une release sans notes.
"""

from __future__ import annotations

import pytest

from modbusai import __version__
from tools.release_notes import check, package_version, section


def test_the_package_version_is_the_one_read_from_the_source():
    assert package_version() == __version__


def test_the_current_version_has_its_changelog_section():
    body = section(__version__)
    assert body.strip(), "section vide"
    assert not body.startswith("## ")  # le titre n'est pas repris dans le corps


def test_a_tag_that_does_not_match_stops_the_release():
    check(f"v{__version__}")  # ne lève pas
    check(__version__)  # le préfixe v est toléré
    with pytest.raises(SystemExit, match="ne s'accordent pas"):
        check("v0.0.1")


def test_an_unknown_version_is_refused():
    with pytest.raises(SystemExit, match="Aucune section"):
        section("42.0.0")
