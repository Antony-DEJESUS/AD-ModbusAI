from modbusai.ui.roles import Role, Tab, can_start, tab_states


def enabled(states):
    return {t for t, s in states.items() if s.enabled}


def test_idle_all_tabs_enabled():
    assert enabled(tab_states(Role.IDLE, False)) == set(Tab)


def test_slave_locks_everything_else():
    st = tab_states(Role.SLAVE, False)
    assert enabled(st) == {Tab.SLAVE}
    assert "serveur esclave" in st[Tab.MASTER].reason


def test_sniffer_locks_everything_else():
    st = tab_states(Role.SNIFFER, False)
    assert enabled(st) == {Tab.SNIFFER}
    assert "ESPION" in st[Tab.SLAVE].reason


def test_master_connected_locks_sniffer_and_slave():
    st = tab_states(Role.MASTER, True)
    assert enabled(st) == {Tab.MASTER, Tab.SCAN, Tab.DIAGNOSTIC}
    assert "DECONNEXION" in st[Tab.SLAVE].reason


def test_busy_tab_locks_others():
    st = tab_states(Role.MASTER, True, busy_tab=Tab.SCAN)
    assert enabled(st) == {Tab.SCAN}
    st = tab_states(Role.MASTER, True, busy_tab=Tab.DIAGNOSTIC)
    assert enabled(st) == {Tab.DIAGNOSTIC}


def test_can_start():
    assert can_start(Role.IDLE, False, Role.MASTER, False) == (True, "")
    assert can_start(Role.IDLE, False, Role.SLAVE, False)[0]
    assert not can_start(Role.MASTER, True, Role.SLAVE, False)[0]
    assert not can_start(Role.SLAVE, False, Role.MASTER, False)[0]
    assert not can_start(Role.SNIFFER, False, Role.SLAVE, False)[0]
    assert not can_start(Role.IDLE, False, Role.SLAVE, True)[0]
