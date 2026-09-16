"""Rapport texte du diagnostic : statistiques, hypothèses, tests, torture."""

from __future__ import annotations

from datetime import datetime

from modbusai import APP_TITLE
from modbusai.analysis.diagnostic import CampaignComparison, Hypothesis
from modbusai.analysis.observations import SlaveStats
from modbusai.analysis.stress import StressReport
from modbusai.i18n import tr
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
    lines.append(tr("{p0} - rapport de diagnostic Modbus").format(p0=APP_TITLE))
    lines.append(tr("Date : {p0:%d/%m/%Y %H:%M:%S}").format(p0=datetime.now()))
    lines.append(tr("Liaison : {p0}").format(p0=settings.summary() if settings is not None else "-"))
    if sources_label:
        lines.append(tr("Sources : {p0}").format(p0=sources_label))
    lines.append(tr("Observations : {p0}").format(p0=observations_count))
    lines.append(_LINE)
    lines.append(tr("STATISTIQUES PAR ESCLAVE"))
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
            lines.append(tr("{p0:>7} exceptions : {p1}").format(p0="", p1=codes))
    if not stats:
        lines.append(tr("  (aucune)"))
    lines.append(_LINE)
    lines.append(tr("HYPOTHÈSES CLASSÉES (score 0-100 : 0-49 peu probable, 50-74 probable, 75-100 très probable)"))
    if not hypotheses:
        lines.append(tr("  Pas assez de données."))
    for h in hypotheses:
        lines.append(f"[{h.score:3d}] {h.title} ({h.scope})")
        lines.append(f"      {h.summary}")
        for e in h.evidence:
            lines.append(f"      - {e}")
        for t in h.tests:
            lines.append(tr("      test : {p0} - {p1}").format(p0=t.title, p1=t.description))
    if comparisons:
        lines.append(_LINE)
        lines.append(tr("TESTS EXÉCUTÉS"))
        for c in comparisons:
            b, r = c.baseline, c.result
            lines.append(tr("* {p0} (esclave {p1})").format(p0=c.test.title, p1=b.slave_id))
            lines.append(
                f"    référence : {b.total} échanges, {100 * b.error_ratio:.0f} % de défauts, {_fmt(b.rt_avg, ' ms')}"
            )
            lines.append(
                f"    test      : {r.total} échanges, {100 * r.error_ratio:.0f} % de défauts, {_fmt(r.rt_avg, ' ms')}"
            )
            lines.append(tr("    verdict   : {p0}").format(p0=c.verdict()))
    if stress is not None and stress.results:
        lines.append(_LINE)
        lines.append(tr("TEST DE TORTURE"))
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
