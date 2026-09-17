"""Charte graphique : jetons complets, contraste suffisant, aucune couleur en dur.

La lisibilité des deux thèmes est une exigence du projet (chantier, écran de
portable en plein jour comme en local technique) : on la vérifie au lieu de
l'espérer.
"""

import re
from pathlib import Path

import pytest

from modbusai.ui.palette import DARK, LIGHT, State, Tokens, color, current, use
from modbusai.ui.style import build_qss

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("tokens", [DARK, LIGHT], ids=lambda t: t.name)
def test_tokens_are_complete_hex(tokens: Tokens):
    for field in Tokens.__slots__:
        value = getattr(tokens, field)
        if field == "name":
            continue
        assert HEX.fullmatch(value), f"{tokens.name}.{field} = {value!r}"


@pytest.mark.parametrize("tokens", [DARK, LIGHT], ids=lambda t: t.name)
def test_readable_on_both_themes(tokens: Tokens):
    """Texte, accent et couleurs d'état doivent rester lisibles sur leur fond."""
    assert contrast(tokens.text, tokens.window) >= 7.0
    assert contrast(tokens.text, tokens.surface) >= 7.0
    assert contrast(tokens.on_accent, tokens.accent) >= 4.0  # libellé d'un bouton principal
    for background in (tokens.window, tokens.surface, tokens.card):
        for state in State:
            assert contrast(tokens.state(state), background) >= 4.0, (tokens.name, state, background)


def test_accent_is_the_claude_terracotta():
    assert DARK.accent == "#D97757"  # terracotta de référence
    assert contrast(LIGHT.accent, LIGHT.window) >= 3.5  # plus foncé sur fond crème


def test_use_switches_the_current_theme():
    assert use("sombre") is DARK and current() is DARK
    assert color(State.OK) == DARK.ok
    assert use("clair") is LIGHT and color(State.ERROR) == LIGHT.error
    assert use("inconnu") is LIGHT


def test_stylesheet_only_uses_the_charte():
    """Toute couleur de la feuille de style vient des jetons du thème."""
    for tokens in (DARK, LIGHT):
        qss = build_qss(tokens)
        allowed = {getattr(tokens, f).upper() for f in Tokens.__slots__ if f != "name"}
        assert {m.upper() for m in HEX.findall(qss)} <= allowed
        assert tokens.accent in qss


def test_no_hardcoded_colour_in_widgets():
    """Une couleur écrite dans un widget casse l'un des deux thèmes tôt ou tard."""
    offenders = []
    for path in Path("modbusai/ui").rglob("*.py"):
        if path.name == "palette.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if HEX.search(line):
                offenders.append(f"{path}:{number}: {line.strip()}")
    assert not offenders, offenders
