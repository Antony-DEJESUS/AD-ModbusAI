"""Serveur MCP : protocole, garde-fous, et bout en bout sur bus virtuel.

Le point important : ce que l'assistant appelle doit produire exactement ce que
l'application produirait, sans matériel. Le bus virtuel relie ici le maître du
serveur MCP à son propre serveur esclave, donc deux rôles sur deux ports, comme
sur un vrai banc.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from modbusai.mcp.cli import build_dispatcher, split_address
from modbusai.mcp.http import serve as serve_http
from modbusai.mcp.protocol import METHOD_NOT_FOUND, Dispatcher, ToolError
from modbusai.mcp.service import ModbusService
from modbusai.mcp.tools import build_tools
from modbusai.modbus.slave import SlaveConfig, Table
from modbusai.transport.records import SerialSettings

pty = pytest.importorskip("pty", reason="bus virtuel Linux requis")
from tests.virtual_bus import VirtualBus  # noqa: E402

BUS_GAP_MS = 20  # les pauses du GIL couperaient les réponses au seuil de 5 ms


@pytest.fixture(autouse=True)
def fast_switching():
    """Sans cela, le relais du bus virtuel rend la main trop tard."""
    previous = sys.getswitchinterval()
    sys.setswitchinterval(0.0005)
    yield
    sys.setswitchinterval(previous)


# ------------------------------------------------------------------ protocole
def call(dispatcher: Dispatcher, name: str, **arguments) -> tuple[str, bool]:
    """Appelle un outil comme le ferait un client, et rend (texte, erreur)."""
    answer = dispatcher.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    assert answer is not None and "result" in answer, answer
    result = answer["result"]
    return result["content"][0]["text"], result["isError"]


def test_handshake_announces_tools_and_negotiates_version():
    dispatcher = build_dispatcher(ModbusService())
    answer = dispatcher.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
    )
    result = answer["result"]
    assert result["protocolVersion"] == "2024-11-05"  # on parle la version du client
    assert result["serverInfo"]["name"] == "modbusai"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert "base 0" in result["instructions"]

    unknown = dispatcher.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1"}})
    assert unknown["result"]["protocolVersion"] == "2025-06-18"  # sinon la plus récente


def test_notification_expects_no_answer_and_unknown_method_is_refused():
    dispatcher = build_dispatcher(ModbusService())
    assert dispatcher.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    refused = dispatcher.handle({"jsonrpc": "2.0", "id": 9, "method": "resources/subscribe"})
    assert refused["error"]["code"] == METHOD_NOT_FOUND


def test_every_tool_declares_a_usable_schema():
    for tool in build_tools(ModbusService(allow_write=True)):
        entry = tool.describe()
        assert entry["description"].strip(), tool.name
        assert entry["inputSchema"]["type"] == "object", tool.name
        for name, spec in entry["inputSchema"]["properties"].items():
            assert "type" in spec, f"{tool.name}.{name}"


def test_write_tools_are_absent_in_read_only():
    read_only = {t.name for t in build_tools(ModbusService())}
    writable = {t.name for t in build_tools(ModbusService(allow_write=True))}
    assert writable - read_only == {"write", "slave_start", "slave_stop", "slave_set"}
    assert not any(t.writes for t in build_tools(ModbusService()))
    with pytest.raises(ToolError, match="lecture seule"):
        ModbusService().require_write("L'écriture")


def test_tool_error_is_reported_to_the_model_not_to_the_transport():
    """Une erreur d'outil doit rester lisible par le modèle : isError, pas un
    objet error JSON-RPC qui ferait échouer l'appel côté client."""
    dispatcher = build_dispatcher(ModbusService())
    text, failed = call(dispatcher, "read", slave=1)
    assert failed and "connect" in text
    assert "error" not in dispatcher.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read", "arguments": {"slave": 1}}}
    )


def test_arguments_are_validated_with_a_readable_message():
    dispatcher = build_dispatcher(ModbusService())
    text, failed = call(dispatcher, "read", slave=999)
    assert failed and "maximum 247" in text
    text, failed = call(dispatcher, "read", slave="douze")
    assert failed and "entier attendu" in text
    text, failed = call(dispatcher, "read", slave=1, type="bobine")
    assert failed and "attendu parmi" in text


def test_split_address_accepts_the_usual_forms():
    assert split_address("100.87.1.4:9000") == ("100.87.1.4", 9000)
    assert split_address("100.87.1.4") == ("100.87.1.4", 8765)
    assert split_address(":9000") == ("127.0.0.1", 9000)


# ------------------------------------------------------- bout en bout sur bus
def connected_pair(bus: VirtualBus, slave_ids: set[int], values: list[int]) -> ModbusService:
    """Maître sur le premier port, serveur esclave simulé sur le second."""
    service = ModbusService(allow_write=True)
    service.store.set(Table.HOLDING_REGISTERS, 0, values)
    service.slave_start(
        SerialSettings(bus.ports[1], inter_frame_delay_ms=BUS_GAP_MS),
        SlaveConfig(slave_ids=slave_ids),
    )
    service.connect(SerialSettings(bus.ports[0], inter_frame_delay_ms=BUS_GAP_MS, response_timeout_ms=500))
    return service


def test_read_goes_through_the_bus_and_reports_both_frames():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1234, 0x4048, 0xF5C3])
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(dispatcher, "read", slave=7, address=0, count=1)
            assert not failed, text
            assert "OK" in text and "1234" in text
            assert "TX :" in text and "RX :" in text
            assert "400001" in text  # la base 1 est rappelée à côté de la base 0
        finally:
            service.shutdown()


def test_float_read_shows_the_four_word_orders():
    """Le piège le plus fréquent : un flottant absurde n'est qu'un ordre de mots."""
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [0x4048, 0xF5C3])  # 3.14 en ABCD
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(dispatcher, "read", slave=7, address=0, count=2, format="flottant32")
            assert not failed, text
            assert "3.14" in text
            for order in ("ABCD", "CDAB", "BADC", "DCBA"):
                assert order in text
        finally:
            service.shutdown()


def test_write_then_read_back():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [0])
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(dispatcher, "write", slave=7, address=5, values=[4242])
            assert not failed, text
            assert service.store.get(Table.HOLDING_REGISTERS, 5, 1) == [4242]
            text, failed = call(dispatcher, "slave_table", table="holding", address=5, count=1)
            assert not failed and "4242" in text
            text, failed = call(dispatcher, "read", slave=7, address=5, count=1)
            assert not failed and "4242" in text
        finally:
            service.shutdown()


def test_scan_finds_the_served_addresses_and_ignores_the_others():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7, 12}, [1])
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(
                dispatcher, "scan", first=5, last=13, timeout_ms=300, retries=0, identify=False, wait_s=60
            )
            assert not failed, text
            assert "présent" in text
            found = {int(line.split()[0]) for line in text.splitlines() if line.strip()[:2].strip().isdigit()}
            assert {7, 12} <= found
        finally:
            service.shutdown()


def test_campaign_feeds_the_analysis_and_the_report():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [77])
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(
                dispatcher, "campaign", slave=7, period_ms=0, duration_s=None, max_count=12, wait_s=60
            )
            assert not failed, text
            assert "Réussite" in text

            text, failed = call(dispatcher, "analyse")
            assert not failed, text
            assert "Score 0-100" in text

            text, failed = call(dispatcher, "report", include_trace=True)
            assert not failed, text
            assert "rapport de diagnostic Modbus" in text
            assert "TRAMES ÉCHANGÉES" in text

            text, _ = call(dispatcher, "clear_history")
            assert "0" not in text.split()[0]  # le nombre effacé est annoncé
            assert len(service.session) == 0
        finally:
            service.shutdown()


def test_a_running_job_reserves_the_bus_and_can_be_stopped():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(dispatcher, "campaign", slave=7, period_ms=100, duration_s=30, wait_s=0)
            assert not failed and "tourne en fond" in text

            refused, failed = call(dispatcher, "read", slave=7)
            assert failed and "job_stop" in refused

            text, failed = call(dispatcher, "job_stop")
            assert not failed and "interrompu" in text
            assert service.job is not None and not service.job.running

            text, failed = call(dispatcher, "read", slave=7)  # la liaison est rendue
            assert not failed, text
        finally:
            service.shutdown()


def test_campaign_restores_the_link_settings_it_changed():
    """Une phase à timeout serré ne doit pas laisser la liaison dégradée."""
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        before = service.settings
        try:
            text, failed = call(
                dispatcher, "campaign", slave=7, period_ms=0, max_count=3, duration_s=None, timeout_ms=50, wait_s=60
            )
            assert not failed, text
            assert service.settings == before
        finally:
            service.shutdown()


def test_sniffer_sees_a_third_party_master_without_emitting():
    """Trois points : un maître extérieur, un esclave, et l'espion du serveur MCP."""
    with VirtualBus(3) as bus:
        service = ModbusService(allow_write=True)
        service.store.set(Table.HOLDING_REGISTERS, 0, [555])
        service.slave_start(
            SerialSettings(bus.ports[1], inter_frame_delay_ms=BUS_GAP_MS), SlaveConfig(slave_ids={9})
        )
        service.connect(SerialSettings(bus.ports[2], inter_frame_delay_ms=BUS_GAP_MS, response_timeout_ms=500))
        dispatcher = build_dispatcher(service)

        from modbusai.modbus.master import ModbusMaster
        from modbusai.modbus.records import FunctionCode, Request
        from modbusai.transport.serial_link import SerialLink

        stop = threading.Event()

        def outside_master() -> None:
            link = SerialLink(SerialSettings(bus.ports[0], inter_frame_delay_ms=BUS_GAP_MS, response_timeout_ms=500))
            link.open()
            master = ModbusMaster(link)
            try:
                while not stop.is_set():
                    master.execute(Request(9, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
                    stop.wait(0.05)
            finally:
                link.close()

        traffic = threading.Thread(target=outside_master, daemon=True)
        traffic.start()
        try:
            text, failed = call(dispatcher, "sniff", seconds=2, wait_s=30)
            assert not failed, text
            assert "transaction(s) appariée(s)" in text
            assert service.session.observations(["espion"])
            assert service.connected  # la liaison du maître est rouverte après l'écoute
        finally:
            stop.set()
            traffic.join(timeout=2)
            service.shutdown()


def test_master_and_slave_refuse_to_share_a_port():
    with VirtualBus(1) as bus:
        service = ModbusService(allow_write=True)
        settings = SerialSettings(bus.ports[0], inter_frame_delay_ms=BUS_GAP_MS)
        service.slave_start(settings, SlaveConfig(slave_ids={1}))
        try:
            with pytest.raises(ToolError, match="déjà utilisé"):
                service.connect(settings)
        finally:
            service.shutdown()


# ----------------------------------------------------------------- transport
def http_server(dispatcher: Dispatcher, token: str = ""):
    httpd = serve_http(dispatcher, "127.0.0.1", 0, "/mcp", token)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/mcp"


def post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, dict | None]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


def test_http_transport_answers_the_handshake():
    httpd, url = http_server(build_dispatcher(ModbusService()))
    try:
        status, answer = post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert status == 200
        assert answer["result"]["serverInfo"]["name"] == "modbusai"
        status, answer = post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert status == 202 and answer is None  # une notification n'attend rien
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_transport_guards_the_port():
    httpd, url = http_server(build_dispatcher(ModbusService()), token="secret")
    handshake = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    try:
        assert post(url, handshake)[0] == 401  # sans jeton
        assert post(url, handshake, {"Authorization": "Bearer faux"})[0] == 401
        assert post(url, handshake, {"Authorization": "Bearer secret"})[0] == 200
        assert post(url, handshake, {"Authorization": "Bearer secret", "Origin": "https://ailleurs"})[0] == 403
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(url, timeout=5)  # GET : pas de flux ouvert par le serveur
        assert refused.value.code == 405
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------------------- cas limites
def test_shutdown_stops_a_running_job_and_closes_the_links():
    """Le client ferme le tube au milieu d'une campagne : rien ne doit rester
    ouvert, ni le port du maître ni celui du serveur esclave."""
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        text, failed = call(dispatcher, "campaign", slave=7, period_ms=100, duration_s=60, wait_s=0)
        assert not failed and "tourne en fond" in text
        service.shutdown()
        assert not service.connected
        assert service.job is not None and not service.job.running
        assert service.slave is None


def test_a_transport_error_during_a_job_is_reported_not_swallowed():
    """Le câble USB est débranché pendant la campagne : le travail doit le dire."""
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        try:
            call(dispatcher, "campaign", slave=7, period_ms=50, duration_s=30, wait_s=0)
            time.sleep(0.2)
            service._link.close()  # le port disparaît sous les pieds du travail
            deadline = time.monotonic() + 10
            while service.job.running and time.monotonic() < deadline:
                time.sleep(0.05)
            text, failed = call(dispatcher, "job_status", wait_s=5)
            assert failed and ("Liaison" in text or "fermée" in text), text
        finally:
            service.shutdown()


def test_two_jobs_at_once_are_refused():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        try:
            call(dispatcher, "campaign", slave=7, period_ms=100, duration_s=30, wait_s=0)
            text, failed = call(dispatcher, "scan", first=1, last=3, wait_s=0)
            assert failed and "job_stop" in text
        finally:
            service.shutdown()


def test_concurrent_calls_do_not_interleave_on_the_port():
    """Deux clients HTTP en même temps : les échanges se suivent, aucun ne rate."""
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [4242])
        httpd, url = http_server(build_dispatcher(service))
        answers: list[str] = []
        lock = threading.Lock()

        def reader() -> None:
            _, answer = post(
                url,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "read", "arguments": {"slave": 7, "address": 0, "count": 1}},
                },
            )
            with lock:
                answers.append(answer["result"]["content"][0]["text"])

        try:
            threads = [threading.Thread(target=reader) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            assert len(answers) == 6
            assert all("4242" in text for text in answers), answers
        finally:
            httpd.shutdown()
            httpd.server_close()
            service.shutdown()


def test_sweeping_the_settings_restores_the_original_link():
    """Le scan change vitesse et parité : il doit rendre la liaison du bandeau.

    Un pseudo-terminal refuse la plupart des vitesses, comme le ferait un
    adaptateur limité : ces variantes doivent être sautées et nommées, jamais
    emporter le balayage entier.
    """
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        before = service.settings
        try:
            text, failed = call(
                dispatcher, "scan", first=7, last=7, timeout_ms=60, retries=0, identify=False, sweep=True, wait_s=90
            )
            assert not failed, text
            assert "présent" in text  # l'esclave reste trouvé avec les réglages qui passent
            assert "refusés" in text  # et les variantes impossibles sont dites
            assert service.settings == before
            assert service.connected
        finally:
            service.shutdown()


def test_writing_a_coil_goes_through_and_reads_back():
    """Les bobines passent par FC05 ou FC15 selon le nombre de valeurs."""
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [0])
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(dispatcher, "write", slave=7, type="coil", address=3, values=[1])
            assert not failed, text
            assert service.store.get(Table.COILS, 3, 1) == [1]

            text, failed = call(dispatcher, "write", slave=7, type="coil", address=8, values=[1, 0, 1])
            assert not failed, text
            assert service.store.get(Table.COILS, 8, 3) == [1, 0, 1]

            text, failed = call(dispatcher, "read", slave=7, type="coil", address=8, count=3)
            assert not failed, text
            assert "8=1" in text and "9=0" in text and "10=1" in text
        finally:
            service.shutdown()


def test_out_of_range_writes_are_refused_with_a_readable_message():
    service = ModbusService(allow_write=True)
    dispatcher = build_dispatcher(service)
    text, failed = call(dispatcher, "slave_set", table="holding", address=65535, values=[1, 2, 3])
    assert failed and "dépasse la table" in text
    text, failed = call(dispatcher, "slave_set", table="holding", address=0, values=[70000])
    assert failed and "0..65535" in text
    text, failed = call(dispatcher, "slave_set", table="holding", address=0, values=list(range(1001)))
    assert failed and "au plus par appel" in text


def test_sniffing_on_its_own_port_leaves_the_master_connected():
    """Un second adaptateur en parallèle : on écoute sans interrompre le maître.

    Quatre points : un maître extérieur qui fait le trafic, l'esclave qui lui
    répond, la liaison maître du serveur MCP, et l'adaptateur d'écoute.
    """
    with VirtualBus(4) as bus:
        service = ModbusService(allow_write=True)
        service.store.set(Table.HOLDING_REGISTERS, 0, [321])
        service.slave_start(
            SerialSettings(bus.ports[1], inter_frame_delay_ms=BUS_GAP_MS), SlaveConfig(slave_ids={9})
        )
        master_link = SerialSettings(bus.ports[2], inter_frame_delay_ms=BUS_GAP_MS, response_timeout_ms=500)
        service.connect(master_link)
        dispatcher = build_dispatcher(service)

        from modbusai.modbus.master import ModbusMaster
        from modbusai.modbus.records import FunctionCode, Request
        from modbusai.transport.serial_link import SerialLink

        stop = threading.Event()

        def outside_master() -> None:
            link = SerialLink(SerialSettings(bus.ports[0], inter_frame_delay_ms=BUS_GAP_MS, response_timeout_ms=500))
            link.open()
            master = ModbusMaster(link)
            try:
                while not stop.is_set():
                    master.execute(Request(9, FunctionCode.READ_HOLDING_REGISTERS, 0, 1))
                    stop.wait(0.05)
            finally:
                link.close()

        traffic = threading.Thread(target=outside_master, daemon=True)
        traffic.start()
        try:
            text, failed = call(dispatcher, "sniff", seconds=2, port=bus.ports[3], wait_s=30)
            assert not failed, text
            assert "cohabitent" not in text  # le résultat est là, pas l'avertissement
            assert service.session.observations(["espion"])
            assert service.connected
            assert service.settings == master_link  # la liaison du maître n'a pas bougé
        finally:
            stop.set()
            traffic.join(timeout=2)
            service.shutdown()


def test_sniffing_without_any_link_says_what_is_missing():
    dispatcher = build_dispatcher(ModbusService())
    text, failed = call(dispatcher, "sniff", seconds=2)
    assert failed and "port" in text and "vitesse" in text


def test_a_suggested_test_runs_and_is_compared_to_the_reference():
    """La boucle complète : campagne, hypothèses, test qui départage, verdict."""
    with VirtualBus(2) as bus:
        service = ModbusService(allow_write=True)
        service.store.set(Table.HOLDING_REGISTERS, 0, [1])
        # Un esclave qui perd une requête sur trois : de quoi faire naître une hypothèse.
        service.slave_start(
            SerialSettings(bus.ports[1], inter_frame_delay_ms=BUS_GAP_MS),
            SlaveConfig(slave_ids={7}, drop_ratio=0.33),
        )
        service.connect(SerialSettings(bus.ports[0], inter_frame_delay_ms=BUS_GAP_MS, response_timeout_ms=300))
        dispatcher = build_dispatcher(service)
        try:
            text, failed = call(dispatcher, "campaign", slave=7, period_ms=0, max_count=30, duration_s=None, wait_s=60)
            assert not failed, text

            text, failed = call(dispatcher, "analyse")
            assert not failed, text
            keys = [line.split("«")[1].split("»")[0].strip() for line in text.splitlines() if "test «" in line]
            assert keys, text

            runnable = [k for k in keys if k in ("timeout_x2", "period", "slow_baud", "parity_even", "stop2", "gap20")]
            assert runnable, keys
            text, failed = call(
                dispatcher, "run_test", test=runnable[0], slave=7, max_count=20, duration_s=None, wait_s=90
            )
            assert not failed, text
            assert "Référence" in text and "Verdict" in text
            assert len(service.comparisons) == 1

            report, failed = call(dispatcher, "report", include_trace=False)
            assert not failed, report
            assert service.comparisons[0].test.title in report  # le test figure au rapport
        finally:
            service.shutdown()


def test_an_unknown_or_manual_test_is_refused_with_guidance():
    with VirtualBus(2) as bus:
        service = connected_pair(bus, {7}, [1])
        dispatcher = build_dispatcher(service)
        try:
            call(dispatcher, "campaign", slave=7, period_ms=0, max_count=8, duration_s=None, wait_s=60)
            text, failed = call(dispatcher, "run_test", test="inexistant", slave=7, wait_s=5)
            assert failed and "analyse" in text
        finally:
            service.shutdown()
