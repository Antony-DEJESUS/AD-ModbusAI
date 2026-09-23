"""Réglages Qt des tests : un nom d'application et un dossier jetable.

Sans nom d'organisation, ``QSettings()`` n'écrit rien sous Windows (statut
``AccessError``) alors qu'il écrit sous Linux : les tests des surlignages
passaient en CI et échouaient sur le poste. Le format INI dans un dossier
temporaire garde aussi les vrais réglages de l'application (registre) à
l'abri des tests.
"""

from __future__ import annotations

import tempfile


def pytest_configure(config):
    try:
        from PySide6.QtCore import QCoreApplication, QSettings
    except ImportError:  # tests des couches basses sans Qt
        return
    folder = tempfile.mkdtemp(prefix="modbusai-tests-")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder)
    QCoreApplication.setOrganizationName("ModbusAI-test")
    QCoreApplication.setApplicationName("ModbusAI-test")
