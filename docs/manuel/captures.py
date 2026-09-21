"""Captures d'écran du mode d'emploi, prises sur l'application réelle.

Tout se joue sur le bus RS-485 virtuel (Linux) : le serveur esclave de
l'application sur un port, le maître de l'application sur un autre, et pour la
scène de l'espion un maître externe sur un troisième. Thème clair, format
1280 x 800, pour l'impression.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python docs/manuel/captures.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.setswitchinterval(0.0005)

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QCoreApplication.setOrganizationName("ModbusAI-manuel")
QCoreApplication.setApplicationName("captures")
app = QApplication([])

from modbusai.modbus.master import RtuMaster  # noqa: E402
from modbusai.modbus.records import FunctionCode, Request  # noqa: E402
from modbusai.modbus.slave import SlaveConfig, Table  # noqa: E402
from modbusai.roles import Tab  # noqa: E402
from modbusai.transport.records import SerialSettings, TcpSettings  # noqa: E402
from modbusai.transport.serial_link import SerialLink  # noqa: E402
from modbusai.ui.main_window import MainWindow  # noqa: E402
from modbusai.ui.pages.diagnostic_page import HypothesisHelpDialog  # noqa: E402
from modbusai.ui.theme import apply_theme  # noqa: E402
from modbusai.ui.widgets.about_dialog import AboutDialog  # noqa: E402
from modbusai.ui.widgets.config_dialog import ConfigDialog  # noqa: E402
from tests.virtual_bus import VirtualBus  # noqa: E402

OUT = Path(__file__).parent / "img"
OUT.mkdir(exist_ok=True)
SIZE = (1280, 800)


def pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_until(cond, timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.monotonic() > end:
            return False
    return True


def shot(widget, name: str, crop: tuple[int, int, int, int] | None = None) -> None:
    app.processEvents()
    pix = widget.grab()
    if crop is not None:
        x, y, w, h = crop
        pix = pix.copy(x, y, w, h)
    pix.save(str(OUT / f"{name}.png"))
    print("  ", name)


class ExternalMaster(threading.Thread):
    """Un maître tiers qui interroge l'esclave : ce que l'espion doit voir."""

    def __init__(self, port: str) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.stop = threading.Event()

    def run(self) -> None:
        link = SerialLink(SerialSettings(self.port, inter_frame_delay_ms=20, response_timeout_ms=300))
        link.open()
        master = RtuMaster(link)
        try:
            n = 0
            while not self.stop.is_set():
                slave = 7 if n % 3 else 12
                master.execute(Request(slave, FunctionCode.READ_HOLDING_REGISTERS, 0, 4))
                if n % 5 == 4:
                    master.execute(Request(7, FunctionCode.WRITE_SINGLE_REGISTER, 3, values=(n,)))
                if n % 7 == 6:
                    master.execute(Request(9, FunctionCode.READ_HOLDING_REGISTERS, 0, 1), timeout_ms=150)
                n += 1
                time.sleep(0.2)
        finally:
            link.close()


def main() -> None:
    with VirtualBus(3) as bus:
        w = MainWindow()
        w.resize(*SIZE)
        w._theme = apply_theme(app, "clair")
        w.connection_bar.set_theme(w._theme)
        w._serial_settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=20, response_timeout_ms=300)
        w.slave_page._serial = SerialSettings(bus.ports[1], inter_frame_delay_ms=20)
        w.slave_page._show_link()
        w.show()
        pump(0.3)

        # ---- serveur esclave : deux adresses, une table remplie
        for i in range(40):
            w.store.set(Table.HOLDING_REGISTERS, i, [(1000 + 37 * i) % 65536])
        w.store.set(Table.COILS, 0, [1, 0, 1, 1, 0, 0, 1, 0])
        w.slave_page.slave_ids.setText("7, 12")
        w.slave_page.start_requested.emit(SlaveConfig(slave_ids={7, 12}), w.slave_page.link_settings())
        assert wait_until(lambda: w.slave_page.serving)

        # ---- maître : connexion et lecture
        w.connection_bar.connect_requested.emit()
        assert wait_until(lambda: w._connected)
        w.tabs.setCurrentIndex(w._tab_index[Tab.MASTER])
        rb = w.master_page.request_bar
        rb.slave.setValue(7)
        rb.register.setValue(0)
        rb.count.setValue(8)
        w.master_page.actions.read_requested.emit()
        assert wait_until(lambda: w.master_page._last_values is not None)
        pump(0.3)
        shot(w, "maitre")
        shot(w, "bandeau", (0, 0, SIZE[0], 62))

        # ---- esclave : cellules éclairées par la lecture
        w.tabs.setCurrentIndex(w._tab_index[Tab.SLAVE])
        w.master_page.actions.read_requested.emit()
        pump(0.5)
        shot(w, "esclave")

        # ---- scan : 1 à 15, deux présents
        w.tabs.setCurrentIndex(w._tab_index[Tab.SCAN])
        sp = w.scan_page
        sp.first.setValue(1)
        sp.last.setValue(15)
        sp.timeout.setValue(150)
        sp.retries.setValue(0)
        sp.identify.setChecked(True)
        sp.start_requested.emit(None)
        assert wait_until(lambda: w.scan_ctl.active, 5)
        assert wait_until(lambda: not w.scan_ctl.active, 60)
        pump(0.3)
        shot(w, "scan")

        # ---- diagnostic : campagne courte puis analyse
        w.tabs.setCurrentIndex(w._tab_index[Tab.DIAGNOSTIC])
        dp = w.diagnostic_page
        dp.slave.setValue(7)
        dp.duration.setValue(6)
        dp.run_btn.click()
        assert wait_until(lambda: w.campaign_ctl.active, 5)
        pump(1.5)
        shot(w, "diagnostic_en_cours")
        assert wait_until(lambda: not w.campaign_ctl.active, 30)
        pump(0.3)
        dp.refresh()
        pump(0.3)
        shot(w, "diagnostic")
        help_dlg = HypothesisHelpDialog(w)
        help_dlg.resize(820, 620)
        help_dlg.show()
        pump(0.3)
        shot(help_dlg, "aide_hypotheses")
        help_dlg.close()

        # ---- espion : un maître tiers dialogue avec le serveur, on écoute
        w.connection_bar.disconnect_requested.emit()
        assert wait_until(lambda: not w._connected)
        pump(0.5)
        third = ExternalMaster(bus.ports[2])
        third.start()
        w.tabs.setCurrentIndex(w._tab_index[Tab.SNIFFER])
        w.sniffer_page.start_requested.emit()
        assert wait_until(lambda: w.sniffer_page.listening, 10)
        pump(4.0)
        shot(w, "espion")
        third.stop.set()
        third.join(2)
        w.sniffer_page.stop_requested.emit()
        assert wait_until(lambda: not w.sniffer_page.listening, 10)

        # ---- dialogues
        for proto, name in (("RTU", "config_rtu"), ("TCP", "config_tcp")):
            dlg = ConfigDialog(proto, SerialSettings("COM3"), TcpSettings("192.168.1.10"), w)
            dlg.show()
            pump(0.3)
            shot(dlg, name)
            dlg.close()
        about = AboutDialog(dark=False, parent=w)
        about.show()
        pump(0.3)
        shot(about, "a_propos")
        about.close()

        w.slave_page.stop_requested.emit()
        wait_until(lambda: not w.slave_page.serving, 10)
        w.close()
        app.processEvents()
    print("captures écrites dans", OUT)


if __name__ == "__main__":
    main()
