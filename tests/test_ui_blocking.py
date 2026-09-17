"""Blocages entre onglets, vérifiés sur la fenêtre réelle (hors écran)."""

import os

import pytest

pytest.importorskip("pty", reason="bus virtuel Linux requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modbusai.modbus.slave import SlaveConfig  # noqa: E402
from modbusai.transport.records import SerialSettings  # noqa: E402
from modbusai.ui.roles import Role, Tab  # noqa: E402
from tests.virtual_bus import VirtualBus  # noqa: E402


@pytest.fixture(scope="module")
def app():
    QCoreApplication.setOrganizationName("ModbusAI-test")
    QCoreApplication.setApplicationName("ModbusAI-test-blocking")
    return QApplication.instance() or QApplication([])


def wait_until(app, cond, timeout_ms=5000):
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while not cond():
        app.processEvents()
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


def enabled_tabs(w):
    return {t for t, i in w._tab_index.items() if w.tabs.isTabEnabled(i)}


def test_tabs_follow_roles(app):
    from modbusai.ui.main_window import MainWindow

    with VirtualBus(2) as bus:
        w = MainWindow()
        w._serial_settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=20)
        try:
            assert enabled_tabs(w) == set(Tab)
            # maître connecté : tous les onglets restent atteignables
            w.connection_bar.connect_requested.emit()
            assert wait_until(app, lambda: w._connected)
            assert enabled_tabs(w) == set(Tab)
            assert "libérer le port" in w.tabs.tabToolTip(w._tab_index[Tab.SLAVE])
            # bascule directe vers le serveur esclave : la liaison maître est fermée seule
            w.slave_page.start_requested.emit(SlaveConfig(slave_ids={1}))
            assert wait_until(app, lambda: w.slave_page.serving)
            assert not w._connected and w._role is Role.SLAVE
            assert enabled_tabs(w) == {Tab.SLAVE}
            w.slave_page.stop_requested.emit()
            assert wait_until(app, lambda: not w.slave_page.serving and w._role is Role.IDLE)
            # bascule directe vers l'espion depuis un maître connecté
            w.connection_bar.connect_requested.emit()
            assert wait_until(app, lambda: w._connected)
            w.sniffer_page.start_requested.emit()
            assert wait_until(app, lambda: w.sniffer_page.listening)
            assert not w._connected and w._role is Role.SNIFFER
            w.sniffer_page.stop_requested.emit()
            assert wait_until(app, lambda: not w.sniffer_page.listening and w._role is Role.IDLE)
            assert enabled_tabs(w) == set(Tab)
            # serveur esclave : tout le reste verrouillé, et CONNEXION refusée
            w.slave_page.start_requested.emit(SlaveConfig(slave_ids={1}))
            assert wait_until(app, lambda: w.slave_page.serving)
            assert enabled_tabs(w) == {Tab.SLAVE}
            w.connection_bar.connect_requested.emit()
            app.processEvents()
            assert not w._connected and "occupé" in w.status_label.text()
            w.slave_page.stop_requested.emit()
            assert wait_until(app, lambda: not w.slave_page.serving and w._role is Role.IDLE)
            assert enabled_tabs(w) == set(Tab)
            # espion : tout le reste verrouillé
            w.sniffer_page.start_requested.emit()
            assert wait_until(app, lambda: w.sniffer_page.listening)
            assert enabled_tabs(w) == {Tab.SNIFFER}
            w.sniffer_page.stop_requested.emit()
            assert wait_until(app, lambda: not w.sniffer_page.listening and w._role is Role.IDLE)
            assert enabled_tabs(w) == set(Tab)
        finally:
            w.close()
            app.processEvents()
