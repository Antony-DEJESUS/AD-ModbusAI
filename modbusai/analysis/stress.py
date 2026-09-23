"""Test de torture : une suite de phases qui sollicitent le réseau de façons
différentes, puis une lecture croisée des résultats pour orienter le
diagnostic (charge de l'esclave, ligne, timeout, trames longues...)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from modbusai.analysis.campaign import CampaignSpec
from modbusai.analysis.observations import SOURCE_DEGRADED, SlaveStats
from modbusai.i18n import tr
from modbusai.modbus.records import FunctionCode, Request
from modbusai.transport.records import LinkSettings, SerialSettings

_READ_FCS = (
    FunctionCode.READ_COILS,
    FunctionCode.READ_DISCRETE_INPUTS,
    FunctionCode.READ_HOLDING_REGISTERS,
    FunctionCode.READ_INPUT_REGISTERS,
)


MIN_PHASE_S = 10.0
"""Durée plancher d'une phase : en deçà, trop peu de lectures pour comparer."""


def responsive_slaves(stats: dict[int, SlaveStats], exclude: int) -> tuple[int, ...]:
    """Esclaves à alterner : ceux qui ont déjà répondu. Un absent ne ferait que
    des timeouts, qu'on prendrait à tort pour une faiblesse du bus ; l'adresse 0
    (diffusion) ne se lit pas."""
    return tuple(sorted(s for s, st in stats.items() if s != exclude and 1 <= s <= 247 and st.answered > 0))


def scenario_duration_s(phases: list[StressPhase]) -> float:
    """Durée réelle du scénario, plancher par phase compris."""
    return sum(p.spec.duration_s or 0.0 for p in phases)


@dataclass(frozen=True, slots=True)
class StressPhase:
    key: str
    title: str
    purpose: str
    spec: CampaignSpec


@dataclass(slots=True)
class PhaseResult:
    phase: StressPhase
    stats: SlaveStats

    @property
    def error_ratio(self) -> float:
        return self.stats.error_ratio

    @property
    def rt_avg(self) -> float | None:
        return self.stats.rt_avg


@dataclass(slots=True)
class StressReport:
    results: list[PhaseResult] = field(default_factory=list)
    conclusions: list[str] = field(default_factory=list)
    orientation: str = ""


def default_scenario(
    base: Request, settings: LinkSettings, total_duration_s: float = 300.0, other_slaves: tuple[int, ...] = ()
) -> list[StressPhase]:
    """Scénario « torture réseau » : chaque phase reçoit une part de la durée totale."""
    req = (
        base
        if base.function in _READ_FCS
        else replace(base, function=FunctionCode.READ_HOLDING_REGISTERS, count=1, values=())
    )
    long_count = 2000 if req.function in (FunctionCode.READ_COILS, FunctionCode.READ_DISCRETE_INPUTS) else 125
    phases: list[StressPhase] = [
        StressPhase(
            "ref",
            tr("Référence"),
            tr("Rythme lent, lecture courte : point de comparaison."),
            CampaignSpec(req, period_ms=500, label=tr("Référence")),
        ),
        StressPhase(
            "burst",
            tr("Rafale"),
            tr("Période minimale : révèle un esclave surchargé (temps de réponse qui grimpe, timeouts)."),
            CampaignSpec(req, period_ms=20, label=tr("Rafale")),
        ),
        StressPhase(
            "long",
            tr("Trames longues"),
            tr(
                "Lecture de {p0} éléments : révèle une ligne bruitée (les longues trames ont plus de chances d'être corrompues)."
            ).format(p0=long_count),
            CampaignSpec(
                replace(req, count=long_count),
                period_ms=200,
                label=tr("Trames longues"),
                source=SOURCE_DEGRADED,
            ),
        ),
        StressPhase(
            "tight",
            tr("Timeout serré"),
            tr("Timeout à 50 ms : mesure la part des réponses lentes."),
            CampaignSpec(req, period_ms=200, timeout_ms=50.0, label=tr("Timeout serré"), source=SOURCE_DEGRADED),
        ),
    ]
    if other_slaves:
        phases.append(
            StressPhase(
                "multi",
                tr("Alternance d'esclaves"),
                tr(
                    "Interroge tour à tour tous les esclaves connus : un bus qui souffre quand plusieurs répondent signe un conflit ou une polarisation faible."
                ),
                CampaignSpec(req, period_ms=100, label=tr("Alternance"), rotation=other_slaves),
            )
        )
    if isinstance(settings, SerialSettings) and settings.baudrate > 9600:
        phases.append(
            StressPhase(
                "slow",
                tr("Vitesse réduite"),
                tr(
                    "9600 bauds : si les défauts disparaissent, la ligne (longueur, terminaisons) est en cause. L'esclave doit accepter 9600."
                ),
                CampaignSpec(req, period_ms=200, baudrate=9600, label=tr("9600 bauds"), source=SOURCE_DEGRADED),
            )
        )
    share = max(MIN_PHASE_S, total_duration_s / len(phases))
    return [replace(p, spec=replace(p.spec, duration_s=share, max_count=None)) for p in phases]


def phase_reading(result: PhaseResult, ref: PhaseResult | None = None) -> str:
    """Ce que les chiffres d'une phase veulent dire, en clair : une phase qui
    dégrade volontairement la liaison produit des défauts qui ne sont pas ceux
    du bus, il faut le dire plutôt que de laisser lire un taux brut."""
    st = result.stats
    if st.total == 0:
        return tr("Aucune lecture : phase non concluante.")
    ref_err = ref.error_ratio if ref is not None and ref.stats.total else 0.0
    worse = result.error_ratio - ref_err
    key = result.phase.key
    if key == "ref":
        if result.error_ratio < 0.02:
            return tr("Comportement nominal : ces chiffres servent de référence aux autres phases.")
        return tr("Des défauts apparaissent déjà au rythme lent : le problème n'a pas besoin d'être provoqué.")
    if key == "burst":
        if worse > 0.05 or (result.rt_avg or 0) > 1.5 * (ref.rt_avg or 1 if ref else 1):
            return tr("Se dégrade à cadence maximale : esclave ou passerelle qui ne suit pas. Espacer les lectures.")
        return tr("Tient la cadence maximale sans perte : ni l'esclave ni la passerelle ne saturent.")
    if key == "long":
        if st.exception_ratio > 0.8:
            return tr(
                "L'esclave refuse cette longueur et répond une exception : c'est la limite de sa table, pas un défaut réseau. Ces exceptions sont provoquées par le test, elles sont exclues des statistiques générales et des hypothèses."
            )
        if worse > 0.05 and (st.crc_error + st.bad_response) > 0:
            return tr(
                "Les trames longues sont corrompues plus souvent que les courtes : signature d'une ligne bruitée, mal terminée ou trop longue."
            )
        return tr("Les trames longues passent aussi bien que les courtes : la ligne transmet proprement.")
    if key == "tight":
        if st.answered == 0:
            return tr(
                "Aucune réponse sous 50 ms : timeout volontairement serré par le test. Retenir seulement que le temps de réponse de cet esclave dépasse 50 ms."
            )
        if st.timeout_ratio > 0.5:
            return tr("Plus d'une réponse sur deux dépasse 50 ms : prévoir un timeout confortable en supervision.")
        return tr("La quasi-totalité des réponses arrive en moins de 50 ms : marge confortable.")
    if key == "multi":
        if worse > 0.05:
            return tr(
                "Le bus souffre quand plusieurs esclaves répondent : polarisation, terminaison ou adresse en double."
            )
        return tr("L'alternance entre esclaves ne dégrade rien : le bus supporte plusieurs interlocuteurs.")
    if key == "slow":
        if st.answered == 0:
            return tr(
                "Aucune réponse à 9600 bauds : l'esclave n'est pas réglé sur cette vitesse. Phase non concluante — ces timeouts sont provoqués par le test, pas par le bus, et sont exclus des statistiques générales. Pour que ce test serve, régler l'esclave sur 9600 des deux côtés."
            )
        if ref_err > 0.05 and result.error_ratio < ref_err * 0.5:
            return tr("Nettement mieux à vitesse réduite : la ligne est en cause (longueur, terminaisons, bruit).")
        return tr("Pas mieux à vitesse réduite : le défaut, s'il existe, n'est pas lié à la vitesse.")
    return ""


def evaluate(results: list[PhaseResult]) -> StressReport:
    """Compare les phases entre elles et formule une orientation."""
    report = StressReport(results=list(results))
    by_key = {r.phase.key: r for r in results}
    ref = by_key.get("ref")
    if ref is None or ref.stats.total == 0:
        report.conclusions.append(tr("Phase de référence absente ou vide : pas de comparaison possible."))
        return report
    concl = report.conclusions
    ref_err = ref.error_ratio
    concl.append(
        f"Référence : {ref.stats.total} lectures, {100 * ref_err:.0f} % de défauts, {ref.rt_avg or 0:.1f} ms en moyenne."
    )
    scores: dict[str, float] = {}

    burst = by_key.get("burst")
    if burst and burst.stats.total:
        worse = burst.error_ratio - ref_err
        slower = (burst.rt_avg or 0) - (ref.rt_avg or 0)
        concl.append(
            tr("Rafale : {p0:.0f} % de défauts, {p1:.1f} ms en moyenne.").format(
                p0=100 * burst.error_ratio, p1=burst.rt_avg or 0
            )
        )
        if worse > 0.05 or slower > 0.5 * (ref.rt_avg or 1):
            scores["charge"] = worse * 100 + (slower / max(ref.rt_avg or 1, 1)) * 20
            concl.append(tr("  -> se dégrade en rafale : l'esclave ou la passerelle peine à suivre la cadence."))
        else:
            concl.append(tr("  -> tient la cadence : pas de surcharge de l'esclave."))

    longp = by_key.get("long")
    if longp and longp.stats.total:
        worse = longp.error_ratio - ref_err
        concl.append(
            f"Trames longues : {100 * longp.error_ratio:.0f} % de défauts (CRC {longp.stats.crc_error}, incohérentes {longp.stats.bad_response}, exceptions {longp.stats.exception})."
        )
        if longp.stats.exception_ratio > 0.8:
            concl.append(
                "  -> refusées par l'esclave (exception) : pas un défaut réseau, longueur maximale limitée par l'équipement."
            )
        elif worse > 0.05 and (longp.stats.crc_error + longp.stats.bad_response) > 0:
            scores["ligne"] = worse * 100 + 10
            concl.append(
                "  -> corrompues plus souvent que les courtes : signature d'une ligne bruitée ou mal terminée."
            )
        else:
            concl.append(tr("  -> pas plus de défauts que les courtes : la ligne transmet proprement."))

    tight = by_key.get("tight")
    if tight and tight.stats.total:
        concl.append(
            tr("Timeout serré (50 ms) : {p0:.0f} % de réponses au-delà de 50 ms.").format(
                p0=100 * tight.stats.timeout_ratio
            )
        )
        if tight.stats.timeout_ratio > 0.5:
            scores["lent"] = tight.stats.timeout_ratio * 60
            concl.append(tr("  -> esclave lent : prévoir un timeout confortable dans la supervision."))

    multi = by_key.get("multi")
    if multi and multi.stats.total:
        worse = multi.error_ratio - ref_err
        concl.append(tr("Alternance : {p0:.0f} % de défauts.").format(p0=100 * multi.error_ratio))
        if worse > 0.05:
            scores["bus"] = worse * 100
            concl.append(
                "  -> se dégrade quand plusieurs esclaves parlent : polarisation, terminaison ou conflit d'adresse."
            )

    slow = by_key.get("slow")
    if slow and slow.stats.total:
        concl.append(tr("9600 bauds : {p0:.0f} % de défauts.").format(p0=100 * slow.error_ratio))
        if slow.stats.answered == 0:
            concl.append(
                tr(
                    "  -> aucune réponse : l'esclave n'est pas réglé sur 9600 bauds. Phase non concluante, ces timeouts ne viennent pas du bus."
                )
            )
        elif ref_err > 0.05 and slow.error_ratio < ref_err * 0.5:
            scores["ligne"] = scores.get("ligne", 0) + 40
            concl.append(
                "  -> nettement mieux à vitesse réduite : la ligne est en cause (longueur, terminaisons, bruit)."
            )
        elif slow.error_ratio >= ref_err and ref_err > 0.05:
            concl.append(tr("  -> pas mieux à vitesse réduite : le défaut n'est pas lié à la vitesse."))

    if not scores:
        report.orientation = (
            "Aucune phase ne dégrade le réseau : sur cette période, le bus et l'esclave sont sains."
            if ref_err < 0.02
            else "Défauts présents mais indépendants de la sollicitation : chercher côté câblage, alimentation ou adresse en double (voir hypothèses)."
        )
    else:
        best = max(scores, key=scores.get)
        report.orientation = {
            "charge": tr(
                "Orientation : esclave ou passerelle surchargé. Réduire la cadence de scrutation ou regrouper les lectures."
            ),
            "ligne": tr(
                "Orientation : qualité de ligne. Vérifier terminaisons 120 Ω, polarisation, longueur, blindage ; réduire la vitesse si possible."
            ),
            "lent": tr("Orientation : esclave lent. Augmenter le timeout de la supervision."),
            "bus": tr(
                "Orientation : bus multi-esclaves fragile. Vérifier polarisation, terminaisons et unicité des adresses."
            ),
        }[best]
    return report
