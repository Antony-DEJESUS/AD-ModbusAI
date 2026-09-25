"""Un maître interroge le serveur esclave pendant qu'on édite une case : la
saisie ne doit pas être effacée par les rafraîchissements, et la validation
doit arriver dans la table."""

import os
import time

import pytest

pytest.importorskip("PySide6", reason="Qt requis")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from modbusai.modbus.slave import Access, DataStore, HandledRequest, SlaveCounters, Table  # noqa: E402
from modbusai.ui.pages.slave_page import SlavePage  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump(app, seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_typing_survives_master_traffic(app):
    store = DataStore()
    page = SlavePage(store)
    page.show()
    index = page.model.index(0, 3)  # 400004
    page.view.setCurrentIndex(index)
    page.view.edit(index)
    _pump(app)
    editor = next(w for w in page.view.viewport().findChildren(QLineEdit) if w.isVisible())
    editor.selectAll()
    QTest.keyClicks(editor, "777")
    for i in range(5):  # le maître lit la ligne éditée et écrit ailleurs
        store.set(Table.HOLDING_REGISTERS, 50, [i])
        page.on_store_changed()
        access = Access(Table.HOLDING_REGISTERS, 0, 10, False)
        page.on_handled(HandledRequest(b"", b"", 1, 3, "réponse", "", access), SlaveCounters())
        _pump(app)
    assert editor.text() == "777"
    QTest.keyClick(editor, Qt.Key.Key_Return)
    _pump(app)
    assert store.get(Table.HOLDING_REGISTERS, 3)[0] == 777
    page.close()
