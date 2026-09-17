from dataclasses import replace
from datetime import datetime, timedelta

from modbusai.analysis.campaign import CampaignSpec
from modbusai.analysis.diagnostic import SuggestedTest, analyse
from modbusai.analysis.observations import DEFAULT_SOURCES, Observation, compute_stats
from modbusai.analysis.report import build_report, suggested_filename
from modbusai.analysis.stress import PhaseResult, default_scenario, evaluate, phase_reading
from modbusai.modbus.records import ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import Parity, SerialSettings, TcpSettings

T0 = datetime(2026, 1, 1, 12, 0, 0)
REQ = Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 2)
SERIAL = SerialSettings("COM3", baudrate=19200)


def obs(status, rt=None, n=1, slave=1):
    return [
        Observation(T0 + timedelta(seconds=i), slave, 3, status, rt, "test", None, None, 1, 7, False, SERIAL)
        for i in range(n)
    ]


def stats(observations):
    return compute_stats(observations)[observations[0].slave_id]


def test_campaign_spec_limits_and_apply():
    spec = CampaignSpec(REQ, period_ms=100, duration_s=2.0, max_count=None)
    assert not spec.is_done(5, 1.0) and spec.is_done(5, 2.0)
    assert spec.expected_count() == 20
    spec2 = CampaignSpec(REQ, period_ms=100, duration_s=None, max_count=7)
    assert spec2.is_done(7, 0.1) and spec2.expected_count() == 7
    both = CampaignSpec(REQ, period_ms=100, duration_s=60, max_count=3)
    assert both.is_done(3, 1.0)
    spec3 = CampaignSpec(REQ, baudrate=9600, parity=Parity.EVEN, timeout_ms=500)
    s = spec3.apply(SERIAL)
    assert (s.baudrate, s.parity, s.response_timeout_ms) == (9600, Parity.EVEN, 500)
    t = spec3.apply(TcpSettings("10.0.0.1"))
    assert t.response_timeout_ms == 500 and t.host == "10.0.0.1"
    assert "9600 bauds" in spec3.describe() and "esclave 1" in spec3.describe()


def test_suggested_test_to_campaign_defaults_to_two_minutes():
    t = SuggestedTest("x", "Timeout x2", "d", runnable=True, timeout_ms=2000)
    spec = t.to_campaign(REQ)
    assert spec.duration_s == 120.0 and spec.max_count is None and spec.timeout_ms == 2000
    assert spec.label == "Timeout x2"
    hyps = analyse(compute_stats(obs(ExchangeStatus.TIMEOUT, n=10)), [], SERIAL)
    assert all(t.duration_s == 120.0 for h in hyps for t in h.tests)


def test_default_scenario_phases_and_duration_split():
    phases = default_scenario(REQ, SERIAL, total_duration_s=300, other_slaves=(2, 3))
    keys = [p.key for p in phases]
    assert keys == ["ref", "burst", "long", "tight", "multi", "slow"]
    assert all(abs(p.spec.duration_s - 50) < 1e-6 for p in phases)
    assert phases[2].spec.request.count == 125
    assert phases[5].spec.baudrate == 9600
    tcp_phases = default_scenario(REQ, TcpSettings("10.0.0.1"), total_duration_s=60)
    assert [p.key for p in tcp_phases] == ["ref", "burst", "long", "tight"]
    assert all(p.spec.duration_s == 15 for p in tcp_phases)
    # une écriture comme base devient une lecture
    w = default_scenario(Request(1, FunctionCode.WRITE_SINGLE_REGISTER, 0, values=(1,)), SERIAL)
    assert w[0].spec.request.function is FunctionCode.READ_HOLDING_REGISTERS


def phase_result(phases, key, observations):
    phase = next(p for p in phases if p.key == key)
    return PhaseResult(phase, stats(observations))


def test_evaluate_orients_toward_load():
    phases = default_scenario(REQ, SERIAL)
    results = [
        phase_result(phases, "ref", obs(ExchangeStatus.OK, 20.0, n=50)),
        phase_result(phases, "burst", obs(ExchangeStatus.OK, 60.0, n=40) + obs(ExchangeStatus.TIMEOUT, n=10)),
        phase_result(phases, "long", obs(ExchangeStatus.OK, 30.0, n=50)),
        phase_result(phases, "tight", obs(ExchangeStatus.OK, 20.0, n=45) + obs(ExchangeStatus.TIMEOUT, n=5)),
    ]
    report = evaluate(results)
    assert "surchargé" in report.orientation
    assert any("rafale" in c for c in report.conclusions)


def test_evaluate_orients_toward_line_and_healthy():
    phases = default_scenario(REQ, SERIAL)
    results = [
        phase_result(phases, "ref", obs(ExchangeStatus.OK, 20.0, n=47) + obs(ExchangeStatus.CRC_ERROR, n=3)),
        phase_result(phases, "burst", obs(ExchangeStatus.OK, 21.0, n=48) + obs(ExchangeStatus.CRC_ERROR, n=2)),
        phase_result(phases, "long", obs(ExchangeStatus.OK, 60.0, n=35) + obs(ExchangeStatus.CRC_ERROR, n=15)),
        phase_result(phases, "tight", obs(ExchangeStatus.OK, 20.0, n=50)),
        phase_result(phases, "slow", obs(ExchangeStatus.OK, 40.0, n=50)),
    ]
    report = evaluate(results)
    assert "Qualité de ligne" in report.orientation or "ligne" in report.orientation
    healthy = evaluate(
        [phase_result(phases, k, obs(ExchangeStatus.OK, 20.0, n=50)) for k in ("ref", "burst", "long", "tight")]
    )
    assert "sains" in healthy.orientation
    assert "pas de comparaison" in evaluate([]).conclusions[0]


def test_report_text():
    observations = obs(ExchangeStatus.OK, 20.0, n=8) + obs(ExchangeStatus.TIMEOUT, n=2)
    st = compute_stats(observations)
    hyps = analyse(st, [], SERIAL)
    phases = default_scenario(REQ, SERIAL)
    stress = evaluate(
        [phase_result(phases, k, obs(ExchangeStatus.OK, 20.0, n=10)) for k in ("ref", "burst", "long", "tight")]
    )
    text = build_report(SERIAL, st, hyps, [], stress, observations, sources_label="test")
    assert "STATISTIQUES PAR ESCLAVE" in text and "HYPOTHÈSES" in text and "TEST DE TORTURE" in text
    assert "COM3 : 19200,8,None,One" in text and "Référence" in text
    assert "Observations : 10" in text
    # chaque phase est explicitée : but, réglages, chiffres, lecture
    assert "Phase 1/4 : Référence" in text and "But      :" in text and "Lecture  :" in text
    assert "[défauts provoqués]" in text  # trames longues et timeout serré
    assert suggested_filename().startswith("AD-ModbusAI_diagnostic_") and suggested_filename().endswith(".txt")


def test_report_traces_every_frame():
    """L'export porte toutes les trames, avec la phase d'où elles viennent."""
    observations = [
        replace(o, label="Rafale", tx_hex="24 04 00 00 00 01 31 C6", rx_hex="24 04 02 00 FA 3D 8F")
        for o in obs(ExchangeStatus.OK, 22.9, n=3)
    ] + [replace(o, label="9600 bauds", source="torture") for o in obs(ExchangeStatus.TIMEOUT, n=2)]
    text = build_report(SERIAL, compute_stats(observations), [], observations=observations)
    assert "TRAMES ÉCHANGÉES (5 lignes)" in text
    assert text.count("24 04 00 00 00 01 31 C6") == 3
    assert "Rafale" in text and "9600 bauds" in text and "TIMEOUT" in text
    trimmed = build_report(SERIAL, {}, [], observations=observations, max_trace=2)
    assert "TRAMES ÉCHANGÉES (2 lignes)" in trimmed and "3 trames plus anciennes" in trimmed
    assert "TRAMES" not in build_report(SERIAL, {}, [], observations=observations, include_trace=False)


def test_provoked_phases_are_kept_out_of_general_statistics():
    """Le 9600 bauds et les trames longues provoquent leurs propres défauts :
    ils ne doivent pas ressortir en hypothèse « qualité de ligne »."""
    phases = {p.key: p for p in default_scenario(REQ, SERIAL)}
    assert phases["ref"].spec.source == "test" and phases["burst"].spec.source == "test"
    assert phases["long"].spec.source == "torture"
    assert phases["tight"].spec.source == "torture"
    assert phases["slow"].spec.source == "torture"
    assert "torture" not in DEFAULT_SOURCES


def test_reduced_speed_without_answer_is_not_a_bus_fault():
    """L'esclave reste à 19200 : les timeouts de la phase 9600 viennent du test,
    pas du bus, et le rapport doit le dire."""
    phases = default_scenario(REQ, SERIAL)
    ref = phase_result(phases, "ref", obs(ExchangeStatus.OK, 22.0, n=50))
    slow = phase_result(phases, "slow", obs(ExchangeStatus.TIMEOUT, n=42))
    reading = phase_reading(slow, ref)
    assert "n'est pas réglé sur cette vitesse" in reading and "non" in reading
    report = evaluate([ref, slow])
    assert any("pas réglé sur 9600" in c for c in report.conclusions)
    assert "sains" in report.orientation


def test_long_frames_refused_are_explained():
    phases = default_scenario(REQ, SERIAL)
    ref = phase_result(phases, "ref", obs(ExchangeStatus.OK, 22.0, n=50))
    longp = phase_result(phases, "long", obs(ExchangeStatus.MODBUS_EXCEPTION, 12.5, n=218))
    assert "limite de sa table" in phase_reading(longp, ref)
