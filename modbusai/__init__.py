"""AD - ModbusAI : outil de diagnostic Modbus RTU / RS-485 et TCP.

Versionnage : X.Y.Z. Les versions 0.1 à 0.3 ont porté les trois phases de
développement ; la 1.0.0 est la première version complète, validée sur
chantier. Ensuite : X = rupture (architecture ou format des données),
Y = nouvelle fonction, Z = correction. Le numéro est affiché dans la barre de
titre et embarqué dans l'exécutable (voir packaging/modbusai.spec).
"""

__version__ = "1.5.0"
APP_NAME = "AD - ModbusAI"
APP_TITLE = f"{APP_NAME} v{__version__}"
# Identifiant des réglages QSettings : figé, il ne suit pas le nom affiché
# (le renommer ferait perdre port, thème et langue enregistrés).
SETTINGS_NAME = "ModbusAI"
