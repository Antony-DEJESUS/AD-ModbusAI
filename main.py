"""Point d'entrée de l'application : ``python main.py`` ou exécutable PyInstaller.

Le serveur MCP a le sien, ``python -m modbusai.mcp`` (exécutable dédié
``AD-ModbusAI-MCP``) : un exécutable fenêtré n'a sous Windows ni entrée ni
sortie standard, or c'est par là que le protocole MCP dialogue.
"""

import sys

from modbusai.app import run

if __name__ == "__main__":
    sys.exit(run())
