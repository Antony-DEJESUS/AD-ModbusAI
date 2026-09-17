"""Rapport texte du diagnostic : statistiques, hypothèses, tests, torture et
trace complète des trames.

Le fichier est destiné autant à l'utilisateur qu'à une relecture assistée :
chaque section dit en clair ce qu'elle contient, et le test de torture explique
phase par phase ce qui a été provoqué et ce qu'il faut en conclure.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from modbusai import APP_TITLE
from modbusai.analysis.diagnostic import CampaignComparison, Hypothesis
from modbusai.analysis.observations import SOURCE_DEGRADED, Observation, SlaveStats
from modbusai.analysis.stress import StressReport, phase_reading
from modbusai.i18n import tr
from modbusai.modbus.exceptions import exception_label
from modbusai.transport.records import LinkSettings

_LINE = "-" * 78
MAX_TRACE_LINES = 200_000  # garde-fou : au-delà, seules les dernières trames sont écrites


def _fmt(value: float | None, unit: str = "") -> str:
    return "-" if value is None else f"{value:.1f}{unit}"


def _status_label(obs: Observation) -> str:
    if obs.exception_code is not None:
        return f"EXCEPTION {obs.exception_code:02X}"
    return obs.status.value.upper()


def _stats_block(stats: dict[int, SlaveStats]) -> list[str]:
    lines = [tr("STATISTIQUES PAR ESCLAVE")]
    lines.append(tr("Réussite = réponses exploitables (OK + exception Modbus) ; une exception est une réponse valide."))
    lines.append(
        f"{'Esclave':>7} {'Échanges':>9} {'Réussite':>9} {'Timeout':>8} {'CRC':>5} {'Excep.':>7} {'Incoh.':>7} {'Liaison':>8} {'Moy ms':>8} {'P95 ms':>8} {'Max ms':>8} {'Gigue':>7}"
    )
    for st in sorted(stats.values(), key=lambda s: s.slave_id):
        ratio = st.answered / st.total if st.total else 0.0
        lines.append(
            f"{st.slave_id:>7} {st.total:>9} {100 * ratio:>8.1f}% {st.timeout:>8} {st.crc_error:>5} {st.exception:>7} {st.bad_response:>7} {st.transport_error:>8} "
            f"{_fmt(st.rt_avg):>8} {_fmt(st.rt_p95):>8} {_fmt(st.rt_max):>8} {_fmt(st.rt_jitter):>7}"
        )
        if st.exceptions_by_code:
            codes = ", ".join(f"{c:02X} x{n} ({exception_label(c)})" for c, n in st.exceptions_by_code.most_common())
            lines.append(tr("{p0:>7} exceptions : {p1}").format(p0="", p1=codes))
    if not stats:
        lines.append(tr("  (aucune)"))
    return lines


def _stress_block(stress: StressReport) -> list[str]:
    """Une phase par bloc : but, réglages, chiffres, puis lecture en clair."""
    lines = [tr("TEST DE TORTURE")]
    lines.append(
        tr(
            "Chaque phase sollicite le réseau autrement ; c'est la comparaison entre phases qui oriente, pas le taux de défauts d'une phase prise isolément."
        )
    )
    lines.append(
        tr(
            "Les phases marquées « défauts provoqués » modifient volontairement la liaison ou la requête : leurs échanges sont exclus des statistiques et des hypothèses ci-dessus."
        )
    )
    ref = next((r for r in stress.results if r.phase.key == "ref"), None)
    total = len(stress.results)
    for index, r in enumerate(stress.results, start=1):
        st = r.stats
        provoked = r.phase.spec.source == SOURCE_DEGRADED
        lines.append("")
        lines.append(
            tr("Phase {p0}/{p1} : {p2}{p3}").format(
                p0=index,
                p1=total,
                p2=r.phase.title,
                p3=tr("   [défauts provoqués]") if provoked else "",
            )
        )
        lines.append(tr("   But      : {p0}").format(p0=r.phase.purpose))
        lines.append(tr("   Réglages : {p0}").format(p0=r.phase.spec.describe()))
        lines.append(
            tr(
                "   Résultat : {p0} lectures, {p1:.1f} % de défauts ({p2} timeouts, {p3} CRC, {p4} incohérentes, {p5} exceptions)"
            ).format(
                p0=st.total,
                p1=100 * st.error_ratio,
                p2=st.timeout,
                p3=st.crc_error,
                p4=st.bad_response,
                p5=st.exception,
            )
        )
        lines.append(
            tr("   Temps    : moyenne {p0}, p95 {p1}, max {p2}, gigue {p3}").format(
                p0=_fmt(st.rt_avg, " ms"),
                p1=_fmt(st.rt_p95, " ms"),
                p2=_fmt(st.rt_max, " ms"),
                p3=_fmt(st.rt_jitter, " ms"),
            )
        )
        reading = phase_reading(r, ref)
        if reading:
            lines.append(tr("   Lecture  : {p0}").format(p0=reading))
    lines.append("")
    lines.append(tr("Synthèse du test de torture :"))
    for c in stress.conclusions:
        lines.append(f"  {c}")
    if stress.orientation:
        lines.append(f"  => {stress.orientation}")
    return lines


def _trace_block(observations: Sequence[Observation], max_trace: int) -> list[str]:
    kept = list(observations)
    skipped = 0
    if len(kept) > max_trace:
        skipped = len(kept) - max_trace
        kept = kept[-max_trace:]
    lines = [tr("TRAMES ÉCHANGÉES ({p0} lignes)").format(p0=len(kept))]
    lines.append(
        tr(
            "Colonnes : n°, heure, source, campagne ou phase, esclave, code fonction, statut, temps de réponse en ms, trame émise (TX), trame reçue (RX). Une trame reçue vide = aucune réponse."
        )
    )
    if skipped:
        lines.append(tr("({p0} trames plus anciennes non écrites : limite de l'export.)").format(p0=skipped))
    lines.append(
        f"{'N°':>6} {'Heure':<12} {'Source':<8} {'Phase':<18} {'Esc':>4} {'FC':>3} {'Statut':<14} {'ms':>7}  TX / RX"
    )
    for index, obs in enumerate(kept, start=1):
        rt = "-" if obs.response_time_ms is None else f"{obs.response_time_ms:.1f}"
        stamp = f"{obs.timestamp:%H:%M:%S.%f}"[:-3]
        lines.append(
            f"{index:>6} {stamp:<12} {obs.source:<8} {(obs.label or '-')[:18]:<18} {obs.slave_id:>4} "
            f"{obs.function:>3} {_status_label(obs):<14} {rt:>7}  TX {obs.tx_hex or '-'}  RX {obs.rx_hex or '-'}"
        )
        if obs.error:
            lines.append(f"{'':>6} {tr('détail')} : {obs.error}")
    if not kept:
        lines.append(tr("  (aucune trame enregistrée)"))
    return lines


def build_report(
    settings: LinkSettings | None,
    stats: dict[int, SlaveStats],
    hypotheses: list[Hypothesis],
    comparisons: Sequence[CampaignComparison] = (),
    stress: StressReport | None = None,
    observations: Sequence[Observation] = (),
    sources_label: str = "",
    *,
    include_trace: bool = True,
    max_trace: int = MAX_TRACE_LINES,
) -> str:
    lines: list[str] = []
    lines.append(tr("{p0} - rapport de diagnostic Modbus").format(p0=APP_TITLE))
    lines.append(tr("Date : {p0:%d/%m/%Y %H:%M:%S}").format(p0=datetime.now()))
    lines.append(tr("Liaison : {p0}").format(p0=settings.summary() if settings is not None else "-"))
    if sources_label:
        lines.append(tr("Sources : {p0}").format(p0=sources_label))
    lines.append(tr("Observations : {p0}").format(p0=len(observations)))
    lines.append(_LINE)
    lines += _stats_block(stats)
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
        lines += _stress_block(stress)
    if include_trace:
        lines.append(_LINE)
        lines += _trace_block(observations, max_trace)
    lines.append(_LINE)
    return "\n".join(lines) + "\n"


def suggested_filename(prefix: str = "ModbusAI_diagnostic") -> str:
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M}.txt"
