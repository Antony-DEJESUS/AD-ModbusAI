"""Arbitrage des ports : plusieurs rôles cohabitent tant qu'ils visent des ports différents."""

from modbusai.transport.records import SerialSettings, TcpSettings
from modbusai.ui.roles import Occupancy, Role, Tab, can_start, port_key, tab_states


def enabled(states):
    return {t for t, s in states.items() if s.enabled}


def test_no_activity_leaves_every_tab_open():
    assert enabled(tab_states()) == set(Tab)


def test_only_a_running_master_activity_locks_tabs():
    """Un scan occupe la liaison maître : les onglets qui la partagent attendent,
    l'espion et le serveur esclave ont la leur et restent accessibles."""
    st = tab_states(busy_tab=Tab.SCAN)
    assert enabled(st) == {Tab.SCAN, Tab.SNIFFER, Tab.SLAVE}
    assert "SCAN" in st[Tab.DIAGNOSTIC].reason
    assert enabled(tab_states(busy_tab=Tab.DIAGNOSTIC)) == {Tab.DIAGNOSTIC, Tab.SNIFFER, Tab.SLAVE}


def test_port_key_identifies_the_resource():
    assert port_key(SerialSettings("com3")) == "COM3"
    assert port_key(SerialSettings("COM3")) == port_key(SerialSettings("COM3"), listen=True)
    # Écouter sur 502 et interroger un esclave distant sur 502 ne se gênent pas
    assert port_key(TcpSettings("192.168.1.10", 502)) != port_key(TcpSettings("", 502), listen=True)
    assert port_key(TcpSettings("", 502), listen=True) == port_key(TcpSettings("0.0.0.0", 502), listen=True)
    assert port_key(None) == ""


def test_master_and_slave_coexist_on_different_ports():
    master = Occupancy(Role.MASTER, port_key(SerialSettings("COM3")))
    ok, reason = can_start(Role.SLAVE, port_key(SerialSettings("COM7"), listen=True), [master])
    assert ok and reason == ""


def test_same_port_is_refused_with_the_culprit():
    master = Occupancy(Role.MASTER, port_key(SerialSettings("COM3")))
    ok, reason = can_start(Role.SLAVE, port_key(SerialSettings("COM3"), listen=True), [master])
    assert not ok and "COM3" in reason and "maître" in reason


def test_a_role_cannot_start_twice():
    slave = Occupancy(Role.SLAVE, "COM7")
    ok, reason = can_start(Role.SLAVE, "COM9", [slave])
    assert not ok and "déjà actif" in reason


def test_master_over_tcp_and_tcp_server_coexist():
    master = Occupancy(Role.MASTER, port_key(TcpSettings("192.168.1.10", 502)))
    ok, _ = can_start(Role.SLAVE, port_key(TcpSettings("", 502), listen=True), [master])
    assert ok
