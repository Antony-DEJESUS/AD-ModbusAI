"""Création de l'application Qt."""

from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from modbusai import APP_NAME, __version__
from modbusai.ui.main_window import MainWindow


def run(argv: list[str] | None = None) -> int:
    QCoreApplication.setOrganizationName(APP_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
