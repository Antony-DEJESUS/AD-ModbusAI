"""Le dictionnaire anglais couvre toutes les clés du code (statiques et énumérations)."""

import re
from pathlib import Path

from modbusai import i18n
from modbusai.i18n_en import EN


def static_keys() -> set[str]:
    keys: set[str] = set()
    for f in Path("modbusai").rglob("*.py"):
        if f.name in ("i18n.py", "i18n_en.py"):
            continue
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r'tr\(\s*"((?:[^"\\]|\\.)*)"', src):
            keys.add(m.group(1).replace('\\"', '"'))
        for m in re.finditer(r"tr\(\s*'((?:[^'\\]|\\.)*)'", src):
            keys.add(m.group(1))
    return keys


def dynamic_keys() -> set[str]:
    from modbusai.analysis.diagnostic import CATALOGUE, SCORE_EXPLANATION, SCORE_LEGEND
    from modbusai.analysis.scanner import ScanStatus
    from modbusai.analysis.sniffer import FrameKind
    from modbusai.modbus.codec import DisplayMode, Radix
    from modbusai.modbus.exceptions import EXCEPTION_LABELS
    from modbusai.modbus.slave import Table
    from modbusai.roles import Role, Tab

    keys = {e.value for e in DisplayMode} | {e.value for e in Radix} | {t.label for t in Table}
    keys |= (
        {e.value for e in ScanStatus} | {e.value for e in FrameKind} | {t.value for t in Tab} | {r.value for r in Role}
    )
    keys |= set(EXCEPTION_LABELS.values()) | {label for _lo, _hi, label, _c in SCORE_LEGEND} | {SCORE_EXPLANATION}
    keys |= {"réponse", "exception", "ignorée", "mauvais esclave", "perdue", "broadcast", "corrompue", "invalide"}
    for info in CATALOGUE.values():
        keys |= {info.title, info.summary, info.trigger, *info.causes, *info.how_to_confirm}
    return keys


def test_english_covers_all_keys():
    missing = sorted(k for k in static_keys() | dynamic_keys() if k not in EN and k not in ("rts", "usb"))
    assert not missing, f"{len(missing)} clé(s) sans traduction anglaise : {missing[:10]}"


def test_placeholders_preserved():
    for fr, en in EN.items():
        assert set(re.findall(r"\{p\d+", fr)) == set(re.findall(r"\{p\d+", en)), fr


def test_fallback_and_switch():
    assert i18n.set_language("en") == "en"
    assert i18n.tr("LECTURE") == "READ"
    assert i18n.tr("clé inconnue xyz") == "clé inconnue xyz"
    assert i18n.set_language("xx") == "fr"
    assert i18n.tr("LECTURE") == "LECTURE"
