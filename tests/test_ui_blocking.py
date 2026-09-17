"""Arbitrage des rôles sur la fenêtre réelle (hors écran).

Le point important : maître et serveur esclave doivent pouvoir tourner en même
temps sur deux ports différents, et se refuser sur le même port.
"""

import os

import pytest

pytest.importorskip("pty", reason="bus virtuel Linux requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from modbusai.modbus.slave import SlaveConfig, Table  # noqa: E402
from modbusai.transport.records import SerialSettings  # noqa: E402
from modbusai.ui.roles import Tab  # noqa: E402
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


def test_master_and_slave_run_together_on_two_ports(app):
    """Le serveur répond au maître de l'application elle-même : deux rôles, deux ports."""
    from modbusai.ui.main_window import MainWindow

    with VirtualBus(2) as bus:
        w = MainWindow()
        w._serial_settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=20)
        w.slave_page._serial = SerialSettings(bus.ports[1], inter_frame_delay_ms=20)
        w.slave_page._protocol = "RTU"
        try:
            w.store.set(Table.HOLDING_REGISTERS, 0, [1234])
            w.slave_page.start_requested.emit(SlaveConfig(slave_ids={7}), w.slave_page.link_settings())
            assert wait_until(app, lambda: w.slave_page.serving)
            # Le serveur tourne : le maître peut se connecter malgré tout
            w.connection_bar.connect_requested.emit()
            assert wait_until(app, lambda: w._connected)
            assert enabled_tabs(w) == set(Tab)

            w.master_page.request_bar.slave.setValue(7)
            w.master_page.request_bar.count.setValue(1)
            w.master_page.actions.read_requested.emit()
            assert wait_until(app, lambda: w.session.observations(["maitre"]))
            observation = w.session.observations(["maitre"])[-1]
            assert observation.status.value == "ok", observation.error
            assert w.master_page._last_values == (1234,)
            assert w.slave_page.model._touched  # la cellule lue s'anime en vert
        finally:
            w.close()
            app.processEvents()


def test_same_port_for_master_and_slave_is_refused(app):
    from modbusai.ui.main_window import MainWindow

    with VirtualBus(2) as bus:
        w = MainWindow()
        w._serial_settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=20)
        w.slave_page._serial = SerialSettings(bus.ports[0], inter_frame_delay_ms=20)
        w.slave_page._protocol = "RTU"
        try:
            w.connection_bar.connect_requested.emit()
            assert wait_until(app, lambda: w._connected)
            w.slave_page.start_requested.emit(SlaveConfig(slave_ids={1}), w.slave_page.link_settings())
            app.processEvents()
            assert not w.slave_page.serving
            assert "déjà utilisé" in w.status_label.text()
        finally:
            w.close()
            app.processEvents()


def test_long_activity_locks_only_the_master_tabs(app):
    from modbusai.ui.main_window import MainWindow

    with VirtualBus(2) as bus:
        w = MainWindow()
        w._serial_settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=20)
        try:
            w.connection_bar.connect_requested.emit()
            assert wait_until(app, lambda: w._connected)
            assert enabled_tabs(w) == set(Tab)
            w.scan_page.start_requested.emit(None)
            assert wait_until(app, lambda: w.scan_ctl.active)
            assert enabled_tabs(w) == {Tab.SCAN, Tab.SNIFFER, Tab.SLAVE}
            w.scan_ctl.cancel()
            assert wait_until(app, lambda: not w.scan_ctl.active)
            assert enabled_tabs(w) == set(Tab)
        finally:
            w.close()
            app.processEvents()


def test_sniffer_takes_over_the_master_port(app):
    """Même port que le maître : l'écoute ferme la liaison maître d'elle-même."""
    from modbusai.ui.main_window import MainWindow
    from modbusai.ui.roles import Role

    with VirtualBus(2) as bus:
        w = MainWindow()
        w._serial_settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=20)
        try:
            w.connection_bar.connect_requested.emit()
            assert wait_until(app, lambda: w._connected)
            w.sniffer_page.start_requested.emit()
            assert wait_until(app, lambda: w.sniffer_page.listening)
            assert not w._connected
            assert [o.role for o in w._occupancies()] == [Role.SNIFFER]
            w.sniffer_page.stop_requested.emit()
            assert wait_until(app, lambda: not w.sniffer_page.listening)
        finally:
            w.close()
            app.processEvents()
