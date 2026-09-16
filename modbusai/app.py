"""Création de l'application Qt : langue, fenêtre, relance après changement de langue."""

from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from modbusai import APP_NAME, __version__
from modbusai.i18n import set_language


class _WindowHolder:
    """Garde la fenêtre courante et la recrée quand la langue change."""

    def __init__(self) -> None:
        self.window = None

    def create(self) -> None:
        from modbusai.ui.main_window import MainWindow  # import après la langue

        old = self.window
        self.window = MainWindow()
        self.window.relaunch_requested.connect(self.create)
        self.window.show()
        if old is not None:
            old.close()


def run(argv: list[str] | None = None) -> int:
    QCoreApplication.setOrganizationName(APP_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(argv if argv is not None else sys.argv)
    set_language(str(QSettings().value("ui/language", "fr")))
    holder = _WindowHolder()
    holder.create()
    return app.exec()
