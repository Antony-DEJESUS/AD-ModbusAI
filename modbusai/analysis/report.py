"""Rapport texte du diagnostic : statistiques, hypothèses, tests, torture."""

from __future__ import annotations

from datetime import datetime

from modbusai import APP_TITLE
from modbusai.analysis.diagnostic import CampaignComparison, Hypothesis
from modbusai.analysis.observations import SlaveStats
from modbusai.analysis.stress import StressReport
from modbusai.transport.records import LinkSettings

_LINE = "-" * 78


def _fmt(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:.1f}{unit}"


def build_report(
    settings: LinkSettings | None,
    stats: dict[int, SlaveStats],
    hypotheses: list[Hypothesis],
    comparisons: list[CampaignComparison] = (),
    stress: StressReport | None = None,
    observations_count: int = 0,
    sources_label: str = "",
) -> str:
    lines: list[str] = []
    lines.append(f"{APP_TITLE} - rapport de diagnostic Modbus")
    lines.append(f"Date : {datetime.now():%d/%m/%Y %H:%M:%S}")
    lines.append(f"Liaison : {settings.summary() if settings is not None else '-'}")
    if sources_label:
        lines.append(f"Sources : {sources_label}")
    lines.append(f"Observations : {observations_count}")
    lines.append(_LINE)
    lines.append("STATISTIQUES PAR ESCLAVE")
    lines.append(
        f"{'Esclave':>7} {'Échanges':>9} {'Réussite':>9} {'Timeout':>8} {'CRC':>5} {'Excep.':>7} {'Incoh.':>7} {'Liaison':>8} {'Moy ms':>8} {'P95 ms':>8} {'Max ms':>8} {'Gigue':>7}"
    )
    for st in sorted(stats.values(), key=lambda s: s.slave_id):
        ratio = (st.ok + st.exception) / st.total if st.total else 0.0
        lines.append(
            f"{st.slave_id:>7} {st.total:>9} {100 * ratio:>8.1f}% {st.timeout:>8} {st.crc_error:>5} {st.exception:>7} {st.bad_response:>7} {st.transport_error:>8} "
            f"{_fmt(st.rt_avg):>8} {_fmt(st.rt_p95):>8} {_fmt(st.rt_max):>8} {_fmt(st.rt_jitter):>7}"
        )
        if st.exceptions_by_code:
            codes = ", ".join(f"{c:02X} x{n}" for c, n in st.exceptions_by_code.most_common())
            lines.append(f"{'':>7} exceptions : {codes}")
    if not stats:
        lines.append("  (aucune)")
    lines.append(_LINE)
    lines.append("HYPOTHÈSES CLASSÉES (score 0-100 : 0-49 peu probable, 50-74 probable, 75-100 très probable)")
    if not hypotheses:
        lines.append("  Pas assez de données.")
    for h in hypotheses:
        lines.append(f"[{h.score:3d}] {h.title} ({h.scope})")
        lines.append(f"      {h.summary}")
        for e in h.evidence:
            lines.append(f"      - {e}")
        for t in h.tests:
            lines.append(f"      test : {t.title} - {t.description}")
    if comparisons:
        lines.append(_LINE)
        lines.append("TESTS EXÉCUTÉS")
        for c in comparisons:
            b, r = c.baseline, c.result
            lines.append(f"* {c.test.title} (esclave {b.slave_id})")
            lines.append(
                f"    référence : {b.total} échanges, {100 * b.error_ratio:.0f} % de défauts, {_fmt(b.rt_avg, ' ms')}"
            )
            lines.append(
                f"    test      : {r.total} échanges, {100 * r.error_ratio:.0f} % de défauts, {_fmt(r.rt_avg, ' ms')}"
            )
            lines.append(f"    verdict   : {c.verdict()}")
    if stress is not None and stress.results:
        lines.append(_LINE)
        lines.append("TEST DE TORTURE")
        for r in stress.results:
            st = r.stats
            lines.append(
                f"* {r.phase.title:<22} {st.total:>5} lectures  défauts {100 * st.error_ratio:>5.1f} %  "
                f"moy {_fmt(st.rt_avg, ' ms'):>10}  max {_fmt(st.rt_max, ' ms'):>10}  (timeouts {st.timeout}, CRC {st.crc_error}, incoh. {st.bad_response}, excep. {st.exception})"
            )
        for c in stress.conclusions:
            lines.append(f"  {c}")
        if stress.orientation:
            lines.append(f"  => {stress.orientation}")
    lines.append(_LINE)
    return "\n".join(lines) + "\n"


def suggested_filename(prefix: str = "ModbusAI_diagnostic") -> str:
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M}.txt"
