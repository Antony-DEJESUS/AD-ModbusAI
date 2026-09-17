# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller : exécutable unique, sans console, nommé avec la version.

Depuis la racine du dépôt :
    pyinstaller packaging/modbusai.spec
Résultat : dist/AD-ModbusAI_v<version>.exe (Windows), avec le logo AD en icône.
"""

import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
_init = (ROOT / "modbusai" / "__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__ = "([^"]+)"', _init).group(1)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # Logo, icône et historique lus à l'exécution via modbusai.ui.resources
    datas=[
        (str(ROOT / "assets" / "*.png"), "assets"),
        (str(ROOT / "assets" / "modbusai.ico"), "assets"),
        (str(ROOT / "CHANGELOG.md"), "."),
    ],
    hiddenimports=["serial.tools.list_ports"],
    hookspath=[],
    runtime_hooks=[],
    # pymodbus ne sert qu'aux tests (oracle) : inutile dans l'exécutable.
    excludes=["pymodbus", "pytest", "tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"AD-ModbusAI_v{VERSION}",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "modbusai.ico"),
)
