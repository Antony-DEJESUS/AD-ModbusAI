"""Mise en forme texte des résultats du serveur MCP.

Le lecteur est un modèle de langage, pas un écran : chaque bloc nomme ses
unités, rappelle la base d'adressage et dit en toutes lettres ce qu'un chiffre
signifie. Aucune décision ici, seulement de la présentation ; les verdicts
viennent de ``analysis``.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

from modbusai.analysis.diagnostic import SCORE_LEGEND, Hypothesis
from modbusai.analysis.observations import SlaveStats
from modbusai.analysis.scanner import ScanResult
from modbusai.analysis.sniffer import Transaction, function_name
from modbusai.analysis.stress import StressReport, phase_reading
from modbusai.modbus.codec import (
    DisplayMode,
    DisplayOptions,
    Radix,
    format_bits,
    format_registers,
)
from modbusai.modbus.exceptions import exception_label
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, FunctionCode
from modbusai.transport.records import LinkSettings, SerialSettings

BIT_FUNCTIONS = (FunctionCode.READ_COILS, FunctionCode.READ_DISCRETE_INPUTS)

_ORDERS = (("ABCD", False, False), ("CDAB", False, True), ("BADC", True, False), ("DCBA", True, True))
"""Les quatre ordres possibles d'une valeur multi-registres : neuf fois sur dix,
un flottant absurde n'est qu'un ordre de mots différent."""


def ms(value: float | None, unit: str = " ms") -> str:
    return "-" if value is None else f"{value:.1f}{unit}"


def link_line(settings: LinkSettings | None) -> str:
    if settings is None:
        return "Liaison : fermée"
    kind = "série (Modbus RTU)" if isinstance(settings, SerialSettings) else "réseau (Modbus TCP)"
    return f"Liaison : {settings.summary()} — {kind}, timeout {settings.response_timeout_ms:.0f} ms"


def status_label(record: ExchangeRecord) -> str:
    if record.status is ExchangeStatus.MODBUS_EXCEPTION and record.exception_code is not None:
        return f"EXCEPTION {record.exception_code:02X} ({exception_label(record.exception_code)})"
    return record.status.value.upper()


# ------------------------------------------------------------------ échanges
def record_block(record: ExchangeRecord, *, mode: str = "registres", order: str = "ABCD") -> str:
    """Un échange : verdict, temps, trames, puis les valeurs lues s'il y en a."""
    req = record.request
    lines = [
        f"Esclave {req.slave_id}, {function_name(int(req.function))}, "
        f"adresse {req.address} (base 0), {req.count} élément(s)",
        f"Statut : {status_label(record)}",
        f"Temps de réponse : {ms(record.response_time_ms)}   transaction : {ms(record.transaction_time_ms)}",
        f"TX : {record.tx_frame.hex}",
        f"RX : {record.rx_frame.hex if record.rx_frame is not None else '(rien reçu)'}",
    ]
    if record.error_message:
        lines.append(f"Détail : {record.error_message}")
    if record.values:
        lines.append("")
        lines.append(values_block(record, mode=mode, order=order))
    return "\n".join(lines)


def values_block(record: ExchangeRecord, *, mode: str = "registres", order: str = "ABCD") -> str:
    """Valeurs lues. Les bobines donnent des bits ; les registres sont rendus
    en décimal, hexadécimal et binaire, et les formats multi-registres sont
    montrés dans les quatre ordres pour lever le doute d'un coup."""
    values = list(record.values or ())
    start = record.request.address
    if record.request.function in BIT_FUNCTIONS:
        rows = format_bits(values, start)
        pairs = "   ".join(f"{r.label}={r.text}" for r in rows)
        return f"Bits (adresse=valeur, base 0) :\n{pairs}"

    lines = [f"{'Registre':>9} {'Base 1':>8} {'Décimal':>21} {'Hexa':>8} {'Binaire':>18}"]
    for index, reg in enumerate(values):
        address = start + index
        signed = reg - 0x10000 if reg >= 0x8000 else reg
        decimal = str(reg) if signed == reg else f"{reg} ({signed} signé)"
        hexa, binary = f"{reg:#06x}", f"{reg:016b}"
        lines.append(f"{address:>9} {_base1(record, address):>8} {decimal:>21} {hexa:>8} {binary:>18}")

    multi = _MODES.get(mode)
    if multi is not None and len(values) >= multi.words:
        lines.append("")
        lines.append(f"Interprétation en {multi.value}, dans les quatre ordres possibles :")
        lines.append("Retenez celui qui donne une valeur plausible ; c'est l'ordre de l'équipement.")
        for name, byte_swap, word_swap in _ORDERS:
            opts = DisplayOptions(mode=multi, radix=Radix.DEC, signed=True, byte_swap=byte_swap, word_swap=word_swap)
            texts = [r.text for r in format_registers(values, start, opts)]
            mark = " <- ordre demandé" if name == order.upper() else ""
            lines.append(f"  {name} : {'  '.join(texts)}{mark}")
    return "\n".join(lines)


_MODES = {
    "entier32": DisplayMode.WORD32,
    "flottant32": DisplayMode.FLOAT32,
    "entier64": DisplayMode.WORD64,
    "flottant64": DisplayMode.FLOAT64,
}


def _base1(record: ExchangeRecord, address: int) -> str:
    """Libellé constructeur (400001, 300001, 000001, 100001) de l'adresse."""
    prefix = {
        FunctionCode.READ_HOLDING_REGISTERS: 400001,
        FunctionCode.WRITE_SINGLE_REGISTER: 400001,
        FunctionCode.WRITE_MULTIPLE_REGISTERS: 400001,
        FunctionCode.READ_INPUT_REGISTERS: 300001,
        FunctionCode.READ_COILS: 1,
        FunctionCode.WRITE_SINGLE_COIL: 1,
        FunctionCode.WRITE_MULTIPLE_COILS: 1,
        FunctionCode.READ_DISCRETE_INPUTS: 100001,
    }.get(record.request.function)
    return "-" if prefix is None else str(prefix + address)


def float_from_pair(high: int, low: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", high, low))[0]


# ---------------------------------------------------------------------- scan
def scan_block(results: Sequence[ScanResult], probed: int) -> str:
    present = [r for r in results if r.present]
    lines = [
        f"{len(present)} équipement(s) présent(s) sur {probed} adresse(s) testée(s).",
        "Une exception Modbus compte comme présent : l'esclave répond, il refuse seulement la requête de test.",
        "",
        f"{'Esclave':>7} {'Statut':<22} {'ms':>7}  Détail / identification",
    ]
    for result in sorted(results, key=lambda r: r.slave_id):
        identity = result.identity_text
        detail = result.detail if identity == "-" else f"{result.detail} | {identity}"
        lines.append(
            f"{result.slave_id:>7} {result.status.value:<22} {ms(result.response_time_ms, ''):>7}  {detail}"
        )
        if not isinstance(result.settings, SerialSettings):
            continue
        if present and result.present and result.settings.summary() != results[0].settings.summary():
            lines.append(f"{'':>7} trouvé avec : {result.settings.summary()}")
    if not results:
        lines.append("  (aucune adresse testée)")
    return "\n".join(lines)


# -------------------------------------------------------------------- espion
def sniff_block(transactions: Sequence[Transaction], seconds: float) -> str:
    lines = [
        f"Écoute passive de {seconds:.0f} s : {len(transactions)} transaction(s) appariée(s).",
        "L'outil n'a rien émis. « SANS RÉPONSE » = la requête d'un autre maître est restée sans réponse.",
        "",
        f"{'Heure':<13} {'Esc':>4} {'FC':>3} {'Statut':<16} {'ms':>7}  Requête",
    ]
    for transaction in transactions:
        stamp = f"{transaction.timestamp:%H:%M:%S.%f}"[:-3]
        status = "SANS RÉPONSE" if transaction.response is None else transaction.status.value.upper()
        lines.append(
            f"{stamp:<13} {transaction.slave_id or 0:>4} {transaction.function or 0:>3} {status:<16} "
            f"{ms(transaction.response_time_ms, ''):>7}  {transaction.request.frame.hex}"
        )
    if not transactions:
        lines.append("  (rien vu passer : vérifiez vitesse et parité, et qu'un maître interroge bien ce bus)")
    return "\n".join(lines)


# -------------------------------------------------------- statistiques
def stats_block(stats: dict[int, SlaveStats]) -> str:
    if not stats:
        return "Aucune observation : lancez une lecture, un scan, une campagne ou une écoute."
    lines = [
        "Réussite = réponses exploitables (OK + exception Modbus) : une exception est une réponse valide.",
        f"{'Esclave':>7} {'Échanges':>9} {'Réussite':>9} {'Timeout':>8} {'CRC':>5} {'Excep.':>7} "
        f"{'Incoh.':>7} {'Liaison':>8} {'Moy':>8} {'P95':>8} {'Max':>8} {'Gigue':>7}",
    ]
    for st in sorted(stats.values(), key=lambda s: s.slave_id):
        ratio = st.answered / st.total if st.total else 0.0
        lines.append(
            f"{st.slave_id:>7} {st.total:>9} {100 * ratio:>8.1f}% {st.timeout:>8} {st.crc_error:>5} "
            f"{st.exception:>7} {st.bad_response:>7} {st.transport_error:>8} "
            f"{ms(st.rt_avg, ''):>8} {ms(st.rt_p95, ''):>8} {ms(st.rt_max, ''):>8} {ms(st.rt_jitter, ''):>7}"
        )
        if st.exceptions_by_code:
            codes = ", ".join(f"{c:02X} x{n} ({exception_label(c)})" for c, n in st.exceptions_by_code.most_common())
            lines.append(f"{'':>7} exceptions : {codes}")
    lines.append("Temps en ms : moyenne, 95e centile, maximum, gigue (écart-type).")
    return "\n".join(lines)


def hypotheses_block(hypotheses: Sequence[Hypothesis], *, with_tests: bool = True) -> str:
    if not hypotheses:
        return "Pas assez de données pour une hypothèse : il faut au moins quelques échanges."
    lines = [f"Score 0-100, vraisemblance : {', '.join(f'{lo}-{hi} {label}' for lo, hi, label, _ in SCORE_LEGEND)}."]
    for hypothesis in hypotheses:
        lines.append("")
        lines.append(f"[{hypothesis.score:>3}] {hypothesis.title} — {hypothesis.scope}")
        lines.append(f"       {hypothesis.summary}")
        for evidence in hypothesis.evidence:
            lines.append(f"       indice : {evidence}")
        if not with_tests:
            continue
        for test in hypothesis.tests:
            how = "exécutable par l'outil campagne" if test.runnable else "manuel, action sur le bus"
            lines.append(f"       test « {test.key} » : {test.title} ({how})")
            lines.append(f"              {test.description}")
    return "\n".join(lines)


def phases_block(report: StressReport) -> str:
    reference = next((r for r in report.results if r.phase.key == "ref"), None)
    lines = [
        "Chaque phase sollicite le réseau autrement : c'est la comparaison entre phases qui oriente,",
        "jamais le taux de défauts d'une phase prise isolément.",
    ]
    for index, result in enumerate(report.results, start=1):
        st = result.stats
        provoked = " [défauts provoqués, exclus des statistiques]" if result.phase.spec.source == "torture" else ""
        lines.append("")
        lines.append(f"Phase {index}/{len(report.results)} : {result.phase.title}{provoked}")
        lines.append(f"   But      : {result.phase.purpose}")
        lines.append(f"   Réglages : {result.phase.spec.describe()}")
        lines.append(
            f"   Résultat : {st.total} lectures, {100 * st.error_ratio:.1f} % de défauts "
            f"({st.timeout} timeouts, {st.crc_error} CRC, {st.bad_response} incohérentes, {st.exception} exceptions)"
        )
        lines.append(f"   Temps    : moyenne {ms(st.rt_avg)}, p95 {ms(st.rt_p95)}, max {ms(st.rt_max)}")
        reading = phase_reading(result, reference)
        if reading:
            lines.append(f"   Lecture  : {reading}")
    lines.append("")
    lines.append("Synthèse :")
    for conclusion in report.conclusions:
        lines.append(f"  {conclusion}")
    if report.orientation:
        lines.append(f"  => {report.orientation}")
    return "\n".join(lines)
