"""Serveur MCP en Modbus TCP : tourne partout, Windows compris.

``test_mcp`` passe par le bus virtuel (Linux). Ici le maître du serveur MCP
interroge son propre serveur esclave par une socket locale, et le transport
entrée / sortie standard est lancé comme le lance Claude Code : un processus
fils relié par des tubes.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from modbusai.analysis.diagnostic import analyse
from modbusai.analysis.observations import Observation, compute_stats
from modbusai.mcp.cli import build_dispatcher
from modbusai.mcp.service import ModbusService
from modbusai.modbus.records import ExchangeStatus, FunctionCode
from modbusai.transport.records import TcpSettings

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.ident = 0

    def call(self, name: str, **arguments) -> tuple[bool, str]:
        self.ident += 1
        params = {"name": name, "arguments": arguments}
        answer = self.dispatcher.handle({"jsonrpc": "2.0", "id": self.ident, "method": "tools/call", "params": params})
        result = answer["result"]
        return bool(result.get("isError")), "\n".join(c["text"] for c in result["content"])


@pytest.fixture
def bench():
    """Serveur esclave (adresse 1) et maître du même service, reliés en TCP local."""
    service = ModbusService(allow_write=True)
    client = Client(build_dispatcher(service))
    port = free_port()
    target = {"transport": "tcp", "host": "127.0.0.1", "tcp_port": port}
    assert not client.call("slave_start", slaves=[1], **target)[0]
    assert not client.call("connect", timeout_ms=500, **target)[0]
    yield client
    client.call("disconnect")
    client.call("slave_stop")


def test_broadcast_write_is_not_a_timeout(bench):
    failed, text = bench.call("write", slave=0, address=40, values=[777])
    assert not failed
    assert "Statut : OK" in text and "Diffusion" in text
    assert "= 777" in bench.call("slave_table", address=40, count=1)[1]
    # et elle ne laisse pas un faux « esclave 0 absent » dans les statistiques
    assert "Timeout" not in text


def test_broadcast_read_is_refused_before_any_job(bench):
    for tool in ("read", "campaign"):
        failed, text = bench.call(tool, slave=0)
        assert failed and "diffusion" in text


def test_coil_accepts_only_zero_or_one(bench):
    failed, text = bench.call("write", slave=1, type="coil", values=[2])
    assert failed and "0 ou 1" in text


def test_multi_register_formats_explain_leftovers(bench):
    bench.call("slave_set", values=[16456, 62915, 65535])
    text = bench.call("read", slave=1, count=3, format="flottant32")[1]
    assert "ABCD : 3.14 <- ordre demandé" in text
    assert "1 registre(s) en fin de lecture non interprété(s)" in text
    text = bench.call("read", slave=1, count=1, format="flottant64")[1]
    assert "Pas d'interprétation" in text and "count=4" in text


def test_identification_gives_the_real_version(bench):
    from modbusai import __version__

    text = bench.call("identify", slave=1)[1]
    assert __version__ in text and "RTU" not in text


def test_line_hypothesis_over_tcp_points_behind_the_gateway():
    settings = TcpSettings("127.0.0.1", 502, response_timeout_ms=300)
    observations = []
    for i in range(40):
        status = ExchangeStatus.TIMEOUT if i % 4 == 0 else ExchangeStatus.OK
        observations.append(
            Observation(
                timestamp=datetime.now(),
                source="maitre",
                slave_id=1,
                function=FunctionCode.READ_HOLDING_REGISTERS,
                status=status,
                response_time_ms=None if status is ExchangeStatus.TIMEOUT else 40.0,
            )
        )
    hypotheses = analyse(compute_stats(observations), observations, settings)
    line = next(h for h in hypotheses if h.key == "line")
    assert any("passerelle" in e for e in line.evidence)


def test_stdio_speaks_utf8_even_on_a_cp1252_console():
    """Sous Windows, les tubes suivaient la page de code du poste : accents
    illisibles, et le « Ω » de la fiche « line » faisait tomber le serveur."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONPATH"] = str(ROOT)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "catalogue", "arguments": {"hypothesis": "line"}},
        },
    ]
    stdin = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "modbusai.mcp"], input=stdin, capture_output=True, env=env, cwd=ROOT, timeout=30
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    lines = proc.stdout.decode("utf-8").splitlines()  # UnicodeDecodeError si ce n'est pas de l'UTF-8
    assert len(lines) == 2 and not proc.stdout.endswith(b"\r\n")
    text = json.loads(lines[1])["result"]["content"][0]["text"]
    assert "Ω" in text and "é" in text


def test_sniff_on_its_own_port_does_not_need_the_master():
    """L'écoute a sa propre liaison : sans maître connecté, elle tente d'ouvrir
    le port demandé au lieu de réclamer « connect »."""
    service = ModbusService(allow_write=True)
    client = Client(build_dispatcher(service))
    try:
        failed, text = client.call("sniff", port="COM99", seconds=1, wait_s=5)
        assert "connect" not in text
        assert "COM99" in text
    finally:
        service.shutdown()


@pytest.mark.parametrize(
    "bad",
    [{"slaves": [300]}, {"slaves": [0]}, {"drop_ratio": 1.5}, {"corrupt_ratio": -0.1}, {"response_delay_ms": -5}],
)
def test_simulator_refuses_out_of_range_settings(bad):
    service = ModbusService(allow_write=True)
    client = Client(build_dispatcher(service))
    try:
        failed, _ = client.call("slave_start", transport="tcp", host="127.0.0.1", tcp_port=free_port(), **bad)
        assert failed
    finally:
        service.shutdown()


def test_simulator_recalls_the_injected_faults():
    service = ModbusService(allow_write=True)
    client = Client(build_dispatcher(service))
    try:
        _, text = client.call(
            "slave_start", transport="tcp", host="127.0.0.1", tcp_port=free_port(), drop_ratio=0.3, read_only=True
        )
        assert "Défauts injectés : 30% des requêtes sans réponse" in text and "exception 04" in text
    finally:
        service.shutdown()


def test_rotating_campaign_polls_every_slave_on_the_simulator():
    """Bout en bout : la campagne tournante interroge réellement chaque esclave."""
    from modbusai.analysis.campaign import CampaignSpec
    from modbusai.mcp.service import Job
    from modbusai.modbus.records import Request

    service = ModbusService(allow_write=True)
    client = Client(build_dispatcher(service))
    port = free_port()
    target = {"transport": "tcp", "host": "127.0.0.1", "tcp_port": port}
    try:
        client.call("slave_start", slaves=[1, 2, 3], **target)
        client.call("connect", **target)
        spec = CampaignSpec(
            Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1), period_ms=0, max_count=6, rotation=(2, 3)
        )
        st = service.run_campaign(spec, Job("campaign", "t"))
        assert st.total == 6 and st.ok == 6
        assert sorted(o.slave_id for o in service.session.observations()) == [1, 1, 2, 2, 3, 3]
    finally:
        service.shutdown()
