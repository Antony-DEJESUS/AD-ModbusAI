"""Point d'entrée : ``python main.py`` ou exécutable PyInstaller."""

import sys

from modbusai.app import run

if __name__ == "__main__":
    sys.exit(run())
