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


def test_notes_survive_a_redirected_windows_console():
    """Le runner Windows redirige la sortie vers notes.md : en cp1252, le « Ω »
    d'un CHANGELOG faisait échouer la publication."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    proc = subprocess.run(
        [sys.executable, "tools/release_notes.py", "1.4.1"], capture_output=True, cwd=root, env=env, timeout=30
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "120 Ω" in proc.stdout.decode("utf-8")
