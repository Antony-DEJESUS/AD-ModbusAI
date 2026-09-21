# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller : deux exécutables uniques, nommés avec la version.

Depuis la racine du dépôt :
    pyinstaller packaging/modbusai.spec

Résultat :
    dist/AD-ModbusAI_v<version>.exe       l'application, fenêtrée, avec le logo AD
    dist/AD-ModbusAI-MCP_v<version>.exe   le serveur MCP, en console

Pourquoi deux fichiers. Un exécutable fenêtré n'a sous Windows ni entrée ni
sortie standard : le serveur MCP, qui dialogue précisément par là, ne peut pas
vivre dans le même binaire. Le séparer a un second mérite : le serveur n'embarque
aucune bibliothèque graphique, il pèse donc le tiers de l'application.
"""

import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
_init = (ROOT / "modbusai" / "__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__ = "([^"]+)"', _init).group(1)

COMMON = dict(
    pathex=[str(ROOT)],
    binaries=[],
    hiddenimports=["serial.tools.list_ports"],
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)

# ------------------------------------------------------- application fenêtrée
app = Analysis(
    [str(ROOT / "main.py")],
    # Logo, icône et historique lus à l'exécution via modbusai.ui.resources
    datas=[
        (str(ROOT / "assets" / "*.png"), "assets"),
        (str(ROOT / "assets" / "modbusai.ico"), "assets"),
        (str(ROOT / "CHANGELOG.md"), "."),
    ],
    # pymodbus ne sert qu'aux tests (oracle) : inutile dans l'exécutable.
    excludes=["pymodbus", "pytest", "tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    **COMMON,
)
app_exe = EXE(
    PYZ(app.pure),
    app.scripts,
    app.binaries,
    app.datas,
    [],
    name=f"AD-ModbusAI_v{VERSION}",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "modbusai.ico"),
)

# ------------------------------------------------------------- serveur MCP
mcp = Analysis(
    [str(ROOT / "modbusai" / "mcp" / "__main__.py")],
    datas=[],
    # La couche MCP n'importe pas Qt : on l'exclut en entier, et le test
    # tests/test_mcp.py garantit que cela reste vrai.
    excludes=["pymodbus", "pytest", "tkinter", "PySide6", "shiboken6"],
    **COMMON,
)
mcp_exe = EXE(
    PYZ(mcp.pure),
    mcp.scripts,
    mcp.binaries,
    mcp.datas,
    [],
    name=f"AD-ModbusAI-MCP_v{VERSION}",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # le dialogue MCP passe par l'entrée et la sortie standard
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "modbusai.ico"),
)
