"""AD - ModbusAI : outil de diagnostic Modbus RTU / RS-485 et TCP.

Versionnage : X.Y.Z, phase 1 = 0.1.x. Le numéro est affiché dans la barre de
titre et embarqué dans l'exécutable (voir packaging/modbusai.spec).
"""

__version__ = "0.3.5"
APP_NAME = "AD - ModbusAI"
APP_TITLE = f"{APP_NAME} v{__version__}"
# Identifiant des réglages QSettings : figé, il ne suit pas le nom affiché
# (le renommer ferait perdre port, thème et langue enregistrés).
SETTINGS_NAME = "ModbusAI"
