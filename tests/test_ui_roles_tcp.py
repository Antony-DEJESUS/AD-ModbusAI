"""Maître et serveur esclave en même temps, sur la fenêtre réelle, en Modbus TCP.

Même preuve que ``test_ui_blocking`` mais sans pseudo-terminal : elle tourne
aussi sous Windows. Le serveur écoute sur un port local, le maître de la même
fenêtre s'y connecte et lit la valeur posée : deux rôles, deux ressources, deux
threads, un seul processus.
"""

import os
import socket
import time

import pytest

pytest.importorskip("PySide6", reason="Qt requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from modbusai.modbus.slave import SlaveConfig, Table  # noqa: E402
from modbusai.roles import Tab  # noqa: E402
from modbusai.transport.records import TcpSettings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(app, cond, timeout_ms=5000):
    deadline = time.monotonic() + timeout_ms / 1000
    while not cond():
        app.processEvents()
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


def test_master_and_slave_run_together_over_tcp(app):
    from modbusai.ui.main_window import MainWindow

    port = free_port()
    w = MainWindow()
    w._protocol = "TCP"
    w._tcp_settings = TcpSettings("127.0.0.1", port, response_timeout_ms=1000)
    w.slave_page._protocol = "TCP"
    w.slave_page._tcp_settings = TcpSettings("127.0.0.1", port)
    try:
        w.store.set(Table.HOLDING_REGISTERS, 0, [4321])
        w.slave_page.start_requested.emit(SlaveConfig(slave_ids={3}), w.slave_page.link_settings())
        assert wait_until(app, lambda: w.slave_page.serving)

        # Le serveur tourne : le maître se connecte quand même, et vers lui
        w.connection_bar.connect_requested.emit()
        assert wait_until(app, lambda: w._connected), w.status_label.text()
        assert w._slave is not None and w.slave_page.serving
        assert enabled_tabs(w) == set(Tab)

        w.master_page.request_bar.slave.setValue(3)
        w.master_page.request_bar.count.setValue(1)
        w.master_page.actions.read_requested.emit()
        assert wait_until(app, lambda: w.session.observations(["maitre"]))
        observation = w.session.observations(["maitre"])[-1]
        assert observation.status.value == "ok", observation.error
        assert w.master_page._last_values == (4321,)
    finally:
        w.close()
        app.processEvents()


def enabled_tabs(w):
    return {t for t, i in w._tab_index.items() if w.tabs.isTabEnabled(i)}
