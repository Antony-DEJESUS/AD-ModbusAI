from datetime import datetime, timedelta

from modbusai.analysis.diagnostic import CampaignComparison, SuggestedTest, analyse
from modbusai.analysis.identification import decode_device_id
from modbusai.analysis.observations import Observation, compute_stats
from modbusai.analysis.scanner import ScanPlan, ScanStatus, classify, merge_attempts
from modbusai.analysis.session import SessionStore
from modbusai.analysis.sniffer import FrameKind, PassiveDecoder, split_merged
from modbusai.modbus.crc import append_crc
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import Direction, Parity, RawFrame, SerialSettings

MS = 1_000_000
T0 = datetime(2026, 1, 1, 12, 0, 0)
SETTINGS = SerialSettings("COM3", response_timeout_ms=1000)


def frame(hex_str: str, t_ms: float, chunks: int = 1) -> RawFrame:
    data = bytes.fromhex(hex_str.replace(" ", ""))
    t = int(t_ms * MS)
    return RawFrame(
        Direction.RX, data, t, t + 2 * MS, T0 + timedelta(milliseconds=t_ms), chunks=(), silence_before_ns=None
    )


def obs(slave, status, rt=None, code=None, n=1, rx_len=7, echo=False):
    return [
        Observation(T0 + timedelta(seconds=i), slave, 3, status, rt, "maitre", code, None, 1, rx_len, echo, SETTINGS)
        for i in range(n)
    ]


# ------------------------------------------------------------------ sniffer
def test_sniffer_pairs_request_and_response():
    d = PassiveDecoder(response_timeout_ms=500)
    req = frame("01 03 00 00 00 02 C4 0B", 0)
    resp = RawFrame(Direction.RX, append_crc(bytes.fromhex("0103040001000A")), 20 * MS, 22 * MS, T0)
    kinds = [sf.kind for sf in d.feed(req)] + [sf.kind for sf in d.feed(resp)]
    assert kinds == [FrameKind.REQUEST, FrameKind.RESPONSE]
    (tr,) = d.pop_completed()
    assert tr.status is ExchangeStatus.OK
    assert tr.slave_id == 1 and tr.function == 3
    assert tr.response_time_ms == 18.0
    assert d.counters.requests == 1 and d.counters.responses == 1 and 1 in d.counters.slaves_seen


def test_sniffer_timeout_exception_and_invalid():
    d = PassiveDecoder(response_timeout_ms=100)
    d.feed(frame("01 03 00 00 00 01 84 0A", 0))
    d.feed(frame("02 03 00 00 00 01 84 39", 300))  # nouvelle requête : la première est en timeout
    (tr1,) = d.pop_completed()
    assert tr1.status is ExchangeStatus.TIMEOUT and tr1.slave_id == 1
    exc = RawFrame(Direction.RX, append_crc(bytes.fromhex("028302")), 310 * MS, 311 * MS, T0)
    (sf,) = d.feed(exc)
    assert sf.kind is FrameKind.EXCEPTION
    (tr2,) = d.pop_completed()
    assert tr2.status is ExchangeStatus.MODBUS_EXCEPTION and tr2.exception_code == 2
    # trame bruitée pendant l'attente : réponse corrompue
    d.feed(frame("01 03 00 00 00 01 84 0A", 400))
    (sf,) = d.feed(frame("01 03 02 00 FA 39 00", 410))
    assert sf.kind is FrameKind.INVALID
    (tr3,) = d.pop_completed()
    assert tr3.status is ExchangeStatus.CRC_ERROR
    assert d.counters.invalid == 1
    # flush après silence
    d.feed(frame("01 03 00 00 00 01 84 0A", 500))
    d.flush(int(550 * MS))
    assert d.pop_completed() == []
    d.flush(int(700 * MS))
    (tr4,) = d.pop_completed()
    assert tr4.status is ExchangeStatus.TIMEOUT


def test_sniffer_broadcast_write_ack_and_orphan():
    d = PassiveDecoder()
    (sf,) = d.feed(RawFrame(Direction.RX, append_crc(bytes.fromhex("000600010003")), 0, 1, T0))
    assert sf.kind is FrameKind.BROADCAST and d.pending is None
    d.feed(RawFrame(Direction.RX, append_crc(bytes.fromhex("010600010003")), 10 * MS, 11 * MS, T0))
    (sf,) = d.feed(RawFrame(Direction.RX, append_crc(bytes.fromhex("010600010003")), 20 * MS, 21 * MS, T0))
    assert sf.kind is FrameKind.RESPONSE  # écho = acquittement, résolu grâce à l'état
    (tr,) = d.pop_completed()
    assert tr.status is ExchangeStatus.OK
    (sf,) = d.feed(RawFrame(Direction.RX, append_crc(bytes.fromhex("0103020064")), 50 * MS, 51 * MS, T0))
    assert sf.kind is FrameKind.RESPONSE and "sans requête" in sf.detail


def test_split_merged_frames():
    req = append_crc(bytes.fromhex("010300000001"))
    resp = append_crc(bytes.fromhex("0103020064"))
    merged = RawFrame(Direction.RX, req + resp, 0, 15 * MS, T0)
    parts = split_merged(merged)
    assert [p.data for p in parts] == [req, resp]
    assert parts[0].t_last_ns == parts[1].t_first_ns
    d = PassiveDecoder()
    kinds = [sf.kind for sf in d.feed(merged)]
    assert kinds == [FrameKind.REQUEST, FrameKind.RESPONSE]
    assert d.pop_completed()[0].status is ExchangeStatus.OK
    # trame réellement invalide : pas de découpage
    assert len(split_merged(RawFrame(Direction.RX, b"\x01\x02\x03\x04\x05\x06\x07\x08\x09", 0, 1, T0))) == 1


# ------------------------------------------------------------------ stats
def test_stats_and_percentiles():
    observations = (
        obs(1, ExchangeStatus.OK, 10.0, n=8)
        + obs(1, ExchangeStatus.TIMEOUT, n=2)
        + obs(2, ExchangeStatus.MODBUS_EXCEPTION, 5.0, code=2, n=3)
    )
    stats = compute_stats(observations)
    s1, s2 = stats[1], stats[2]
    assert s1.total == 10 and s1.ok == 8 and s1.timeout == 2
    assert s1.ok_ratio == 0.8 and s1.error_ratio == 0.2
    assert s1.rt_avg == 10.0 and s1.rt_p95 == 10.0 and s1.rt_jitter == 0.0
    assert s2.answered == 3 and s2.exceptions_by_code[2] == 3 and s2.error_ratio == 0.0


# --------------------------------------------------------------- diagnostic
def test_hypothesis_absent():
    stats = compute_stats(obs(5, ExchangeStatus.TIMEOUT, n=10))
    hyps = analyse(stats, [], SETTINGS)
    assert hyps[0].key == "absent" and hyps[0].slave_id == 5 and hyps[0].score >= 90
    assert any(t.key == "scan_addr" for t in hyps[0].tests)


def test_hypothesis_framing_vs_line():
    stats = compute_stats(obs(1, ExchangeStatus.CRC_ERROR, n=8) + obs(1, ExchangeStatus.OK, 10.0, n=2))
    keys = [h.key for h in analyse(stats, [], SETTINGS)]
    assert keys[0] == "framing"
    stats = compute_stats(
        obs(1, ExchangeStatus.OK, 10.0, n=95)
        + obs(1, ExchangeStatus.CRC_ERROR, n=3)
        + obs(1, ExchangeStatus.TIMEOUT, n=2)
    )
    hyps = analyse(stats, [], SETTINGS)
    assert hyps[0].key == "line"
    assert any(t.runnable and t.key == "slow_baud" for t in hyps[0].tests)


def test_hypothesis_slow_slave_and_echo_and_exception():
    stats = compute_stats(obs(1, ExchangeStatus.OK, 800.0, n=8) + obs(1, ExchangeStatus.TIMEOUT, n=2))
    hyps = analyse(stats, [], SETTINGS)
    slow = next(h for h in hyps if h.key == "slow")
    assert slow.tests[0].timeout_ms == 2000.0 and slow.tests[0].apply(SETTINGS).response_timeout_ms == 2000.0
    stats = compute_stats(obs(1, ExchangeStatus.BAD_RESPONSE, n=6, echo=True))
    assert analyse(stats, [], SETTINGS)[0].key == "echo"
    stats = compute_stats(obs(1, ExchangeStatus.BAD_RESPONSE, n=6))
    assert analyse(stats, [], SETTINGS)[0].key == "conflict"
    stats = compute_stats(obs(1, ExchangeStatus.MODBUS_EXCEPTION, 12.0, code=2, n=6))
    hyps = analyse(stats, [], SETTINGS)
    assert hyps[0].key == "exception"


def test_hypothesis_fragmentation_and_healthy_and_transport():
    fragmented = obs(1, ExchangeStatus.OK, 10.0, n=10) + obs(1, ExchangeStatus.CRC_ERROR, n=3, rx_len=4)
    stats = compute_stats(fragmented)
    keys = [h.key for h in analyse(stats, fragmented, SETTINGS)]
    assert "fragment" in keys
    healthy = obs(1, ExchangeStatus.OK, 10.0, n=50) + obs(2, ExchangeStatus.OK, 12.0, n=50)
    hyps = analyse(compute_stats(healthy), healthy, SETTINGS)
    assert hyps[0].key == "healthy" and hyps[0].slave_id is None
    trans = obs(1, ExchangeStatus.OK, 10.0, n=10) + obs(1, ExchangeStatus.TRANSPORT_ERROR, n=2)
    assert any(h.key == "transport" for h in analyse(compute_stats(trans), trans, SETTINGS))


def test_campaign_comparison_and_test_apply():
    base = compute_stats(obs(1, ExchangeStatus.OK, 10.0, n=8) + obs(1, ExchangeStatus.CRC_ERROR, n=2))[1]
    good = compute_stats(obs(1, ExchangeStatus.OK, 10.0, n=10))[1]
    t = SuggestedTest("x", "t", "d", runnable=True, baudrate=9600, parity=Parity.EVEN)
    assert "confirmée" in CampaignComparison(t, base, good).verdict()
    assert "peu probable" in CampaignComparison(t, base, base).verdict()
    s = t.apply(SETTINGS)
    assert s.baudrate == 9600 and s.parity is Parity.EVEN and t.changes_link


# ------------------------------------------------------------------ scanner
def rec(slave, status, rx_hex=None, code=None, rt=5.0):
    tx = RawFrame(Direction.TX, bytes.fromhex("010300000001840A"), 0, 1 * MS, T0)
    rx = None if rx_hex is None else RawFrame(Direction.RX, bytes.fromhex(rx_hex), 6 * MS, 7 * MS, T0)
    return ExchangeRecord(
        1,
        T0,
        Request(slave, FunctionCode.READ_HOLDING_REGISTERS, 0, 1),
        SETTINGS,
        tx,
        rx,
        status,
        rt if rx else None,
        code,
        "err",
    )


def test_scan_classify_and_merge():
    assert classify(rec(1, ExchangeStatus.OK, "0103020000B844"))[0] is ScanStatus.PRESENT
    assert classify(rec(1, ExchangeStatus.MODBUS_EXCEPTION, "018302C0F1", 2))[0] is ScanStatus.PRESENT_EXCEPTION
    assert classify(rec(1, ExchangeStatus.CRC_ERROR, "0103020000B845"))[0] is ScanStatus.NOISY
    echo = classify(rec(1, ExchangeStatus.BAD_RESPONSE, "010300000001840A"))
    assert echo[0] is ScanStatus.CONFLICT and "écho" in echo[1]
    assert classify(rec(1, ExchangeStatus.TIMEOUT))[0] is ScanStatus.ABSENT
    assert (
        merge_attempts([rec(1, ExchangeStatus.TIMEOUT), rec(1, ExchangeStatus.OK, "0103020000B844")])[0]
        is ScanStatus.PRESENT
    )
    assert merge_attempts([])[0] is ScanStatus.ABSENT


def test_scan_plan_variants():
    plan = ScanPlan(1, 10, base_settings=SETTINGS)
    assert plan.settings_variants() == [SETTINGS] and plan.total_probes == 10
    sweep = ScanPlan(1, 10, sweep_settings=True, base_settings=SETTINGS)
    variants = sweep.settings_variants()
    assert variants[0] == SETTINGS and len(variants) > 10 and len(set(variants)) == len(variants)
    assert plan.probe_request(3).slave_id == 3


def test_identification_decode():
    body = (
        bytes.fromhex("0E 01 01 00 00 03 00 09")
        + b"Schneider"
        + bytes.fromhex("01 05")
        + b"TC903"
        + bytes.fromhex("02 03")
        + b"1.2"
    )
    ident = decode_device_id(body)
    assert ident.vendor == "Schneider" and ident.product == "TC903" and ident.revision == "1.2"
    assert ident.summary() == "Schneider / TC903 / 1.2"


def test_session_store():
    store = SessionStore()
    store.add_record(rec(1, ExchangeStatus.OK, "0103020000B844"))
    store.add_record(rec(2, ExchangeStatus.TIMEOUT), source="scan")
    assert len(store) == 2
    assert set(store.stats()) == {1, 2}
    assert set(store.stats(sources=["maitre"])) == {1}
    store.clear()
    assert len(store) == 0


def test_catalogue_covers_all_hypotheses():
    from modbusai.analysis.diagnostic import CATALOGUE, SCORE_LEGEND

    produced = set()
    scenarios = [
        obs(1, ExchangeStatus.TIMEOUT, n=10),
        obs(1, ExchangeStatus.CRC_ERROR, n=8) + obs(1, ExchangeStatus.OK, 10.0, n=2),
        obs(1, ExchangeStatus.OK, 10.0, n=95)
        + obs(1, ExchangeStatus.CRC_ERROR, n=3)
        + obs(1, ExchangeStatus.TIMEOUT, n=2),
        obs(1, ExchangeStatus.OK, 800.0, n=8) + obs(1, ExchangeStatus.TIMEOUT, n=2),
        obs(1, ExchangeStatus.BAD_RESPONSE, n=6, echo=True),
        obs(1, ExchangeStatus.BAD_RESPONSE, n=6),
        obs(1, ExchangeStatus.MODBUS_EXCEPTION, 12.0, code=2, n=6),
        obs(1, ExchangeStatus.OK, 10.0, n=10) + obs(1, ExchangeStatus.CRC_ERROR, n=3, rx_len=4),
        obs(1, ExchangeStatus.OK, 10.0, n=10) + obs(1, ExchangeStatus.TRANSPORT_ERROR, n=2),
        obs(1, ExchangeStatus.OK, 10.0, n=50),
    ]
    for sc in scenarios:
        for h in analyse(compute_stats(sc), sc, SETTINGS):
            produced.add(h.key)
            assert h.key in CATALOGUE and h.title == CATALOGUE[h.key].title
    assert produced == set(CATALOGUE)
    assert SCORE_LEGEND[0][0] == 0 and SCORE_LEGEND[-1][1] == 100
