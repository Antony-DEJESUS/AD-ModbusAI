"""Moteur d'hypothèses : à partir des statistiques par esclave, classer les
causes probables et proposer des tests pour les départager.

Chaque règle produit une ``Hypothesis`` avec un score 0..100, ses indices et
des ``SuggestedTest``. Un test « exécutable » décrit une campagne de lectures
(nombre, période, paramètres liaison surchargés) que l'interface peut lancer
et comparer à la situation courante.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from modbusai.analysis.observations import Observation, SlaveStats
from modbusai.modbus.exceptions import exception_label
from modbusai.transport.records import Parity, SerialSettings

MIN_SAMPLES = 5  # en dessous, on ne conclut pas


@dataclass(frozen=True, slots=True)
class SuggestedTest:
    key: str
    title: str
    description: str
    runnable: bool = False
    count: int = 30  # nombre de lectures de la campagne
    period_ms: int = 200
    timeout_ms: float | None = None
    baudrate: int | None = None
    parity: Parity | None = None
    stopbits: float | None = None
    inter_frame_delay_ms: float | None = None

    def apply(self, settings: SerialSettings) -> SerialSettings:
        """Paramètres de liaison pour la campagne."""
        changes: dict = {}
        if self.timeout_ms is not None:
            changes["response_timeout_ms"] = self.timeout_ms
        if self.baudrate is not None:
            changes["baudrate"] = self.baudrate
        if self.parity is not None:
            changes["parity"] = self.parity
        if self.stopbits is not None:
            changes["stopbits"] = self.stopbits
        if self.inter_frame_delay_ms is not None:
            changes["inter_frame_delay_ms"] = self.inter_frame_delay_ms
        return replace(settings, **changes) if changes else settings

    @property
    def changes_link(self) -> bool:
        return any(
            v is not None
            for v in (self.timeout_ms, self.baudrate, self.parity, self.stopbits, self.inter_frame_delay_ms)
        )


@dataclass(slots=True)
class Hypothesis:
    key: str
    title: str
    score: int  # 0..100
    summary: str
    slave_id: int | None = None
    evidence: list[str] = field(default_factory=list)
    tests: list[SuggestedTest] = field(default_factory=list)

    @property
    def scope(self) -> str:
        return f"esclave {self.slave_id}" if self.slave_id is not None else "réseau"


def _pct(x: float) -> str:
    return f"{100 * x:.0f} %"


def _clamp(x: float) -> int:
    return int(max(0, min(100, round(x))))


# ------------------------------------------------------------------ règles
def _rule_absent(st: SlaveStats) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or st.answered > 0:
        return None
    if st.timeout_ratio < 0.9:
        return None
    ev = [f"{st.timeout}/{st.total} requêtes sans réponse", "aucune réponse valide ni exception"]
    tests = [
        SuggestedTest(
            "scan_addr",
            "Scanner les adresses",
            "Onglet Scan réseau : l'équipement répond peut-être à une autre adresse.",
        ),
        SuggestedTest(
            "wiring", "Inverser A et B", "Cause la plus fréquente sur chantier ; refaire une lecture après inversion."
        ),
        SuggestedTest(
            "scan_baud",
            "Balayer vitesses et parités",
            "Onglet Scan réseau avec le balayage activé, sur cette seule adresse.",
        ),
        SuggestedTest(
            "fc03",
            "Essayer un autre code fonction",
            "Certains équipements ne répondent qu'en FC03 ou FC04 ; lire le registre 0 dans chaque type.",
        ),
    ]
    return Hypothesis(
        "absent",
        "Esclave absent, adresse ou câblage incorrect",
        _clamp(60 + 40 * st.timeout_ratio),
        "Rien ne répond à cette adresse : équipement hors tension, adresse différente, A/B inversés ou vitesse fausse.",
        st.slave_id,
        ev,
        tests,
    )


def _rule_framing(st: SlaveStats) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or st.crc_error == 0:
        return None
    ratio = st.crc_ratio
    if ratio < 0.3 or st.ok_ratio > 0.5:
        return None
    ev = [f"{st.crc_error}/{st.total} réponses au CRC invalide", f"{st.ok} réponses correctes seulement"]
    tests = [
        SuggestedTest(
            "scan_baud",
            "Balayer vitesses et parités",
            "Onglet Scan réseau avec le balayage activé : si une combinaison répond proprement, c'est la bonne.",
        ),
        SuggestedTest(
            "parity_even",
            "Campagne en parité Even",
            "30 lectures en 8E1 aux mêmes vitesse et adresse.",
            runnable=True,
            parity=Parity.EVEN,
            stopbits=1.0,
        ),
        SuggestedTest(
            "stop2",
            "Campagne en 8N2",
            "30 lectures avec 2 bits de stop.",
            runnable=True,
            parity=Parity.NONE,
            stopbits=2.0,
        ),
    ]
    return Hypothesis(
        "framing",
        "Vitesse ou parité incorrecte",
        _clamp(50 + 50 * ratio),
        "L'équipement répond mais les octets sont mal interprétés : paramètres série différents de ceux de l'esclave.",
        st.slave_id,
        ev,
        tests,
    )


def _rule_line_quality(st: SlaveStats, settings: SerialSettings | None) -> Hypothesis | None:
    if st.total < MIN_SAMPLES * 2 or st.ok == 0:
        return None
    intermittent = (st.crc_error + st.bad_response + st.timeout) / st.total
    if intermittent < 0.02 or st.ok_ratio < 0.5:
        return None
    ev = [
        f"{_pct(st.ok_ratio)} de réussite, défauts intermittents : {st.crc_error} CRC, {st.timeout} timeouts, {st.bad_response} incohérentes"
    ]
    if st.rt_jitter is not None and st.rt_avg:
        ev.append(f"temps de réponse {st.rt_avg:.1f} ms en moyenne, gigue {st.rt_jitter:.1f} ms")
    tests = [
        SuggestedTest(
            "termination",
            "Vérifier terminaisons et polarisation",
            "120 Ω aux deux extrémités seulement, pas de dérivation longue, blindage relié d'un seul côté.",
        ),
    ]
    if settings is not None and settings.baudrate > 9600:
        tests.append(
            SuggestedTest(
                "slow_baud",
                "Campagne à 9600 bauds",
                "Si les défauts disparaissent à vitesse réduite, la ligne est en cause (longueur, terminaisons, bruit). L'esclave doit être réglé sur 9600 pour ce test.",
                runnable=True,
                baudrate=9600,
            )
        )
    tests.append(
        SuggestedTest(
            "period",
            "Campagne à période lente (1 s)",
            "Écarte une surcharge de l'esclave : si les défauts persistent à 1 s, c'est la ligne.",
            runnable=True,
            period_ms=1000,
            count=30,
        )
    )
    score = 30 + 200 * intermittent
    if st.crc_error > 0:
        score += 15
    return Hypothesis(
        "line",
        "Qualité de ligne : bruit, terminaisons, longueur",
        _clamp(score),
        "Échanges majoritairement bons mais défauts aléatoires : typique d'un bus mal terminé, non polarisé, trop long ou perturbé.",
        st.slave_id,
        ev,
        tests,
    )


def _rule_slow_slave(st: SlaveStats, settings: SerialSettings | None) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or st.timeout == 0 or not st.response_times or settings is None:
        return None
    p95 = st.rt_p95 or 0.0
    if p95 < 0.6 * settings.response_timeout_ms:
        return None
    ev = [
        f"P95 du temps de réponse {p95:.0f} ms pour un timeout de {settings.response_timeout_ms:.0f} ms",
        f"{st.timeout} timeouts sur {st.total}",
    ]
    tests = [
        SuggestedTest(
            "timeout_x2",
            "Campagne avec timeout doublé",
            "Si les timeouts disparaissent, l'esclave est simplement lent.",
            runnable=True,
            timeout_ms=2 * settings.response_timeout_ms,
        ),
    ]
    return Hypothesis(
        "slow",
        "Esclave lent, timeout trop court",
        _clamp(40 + 60 * min(1.0, p95 / settings.response_timeout_ms)),
        "Les réponses réussies frôlent le délai configuré : les timeouts sont probablement des réponses arrivées trop tard.",
        st.slave_id,
        ev,
        tests,
    )


def _rule_conflict(st: SlaveStats) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or st.bad_response == 0:
        return None
    if st.echo >= st.bad_response * 0.8:
        ev = [f"{st.echo} réponses identiques à la requête émise"]
        tests = [
            SuggestedTest(
                "rts",
                "Activer le pilotage RTS",
                "CONFIGURATION > RTS : l'adaptateur renvoie l'écho de l'émission, il n'a pas de direction automatique.",
            ),
            SuggestedTest(
                "adapter",
                "Changer d'adaptateur USB/RS-485",
                "Un adaptateur à direction automatique (CH340, FTDI avec TXDEN) supprime l'écho.",
            ),
        ]
        return Hypothesis(
            "echo",
            "Écho de l'adaptateur (direction RS-485)",
            _clamp(50 + 50 * st.bad_response / st.total),
            "L'outil reçoit sa propre requête : l'adaptateur ne coupe pas la réception pendant l'émission.",
            st.slave_id,
            ev,
            tests,
        )
    ev = [f"{st.bad_response} réponses au CRC juste mais incohérentes (autre esclave, autre fonction ou longueur)"]
    if st.crc_error:
        ev.append(f"{st.crc_error} réponses corrompues, compatibles avec des collisions")
    tests = [
        SuggestedTest(
            "sniff",
            "Écouter le bus (onglet Espion)",
            "Deux réponses à une même requête ou des collisions systématiques signent un doublon d'adresse.",
        ),
        SuggestedTest(
            "unplug", "Débrancher les esclaves un par un", "La réponse redevient cohérente quand le doublon est retiré."
        ),
    ]
    return Hypothesis(
        "conflict",
        "Conflit d'adresse ou réponse d'un autre esclave",
        _clamp(40 + 60 * st.bad_response / st.total),
        "Une réponse valide arrive mais ne correspond pas à la requête : deux équipements partagent probablement l'adresse.",
        st.slave_id,
        ev,
        tests,
    )


def _rule_exceptions(st: SlaveStats) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or st.exception_ratio < 0.5:
        return None
    codes = ", ".join(f"{code:02X} ({exception_label(code)}) ×{n}" for code, n in st.exceptions_by_code.most_common())
    ev = [
        f"{st.exception}/{st.total} exceptions Modbus : {codes}",
        "la liaison est saine : l'esclave répond dans les temps",
    ]
    tests = [
        SuggestedTest(
            "mapping",
            "Vérifier la table d'échange",
            "Adresse de départ (base 0 ou 1 ?), type de registre (holding / input) et longueur autorisée.",
        ),
        SuggestedTest(
            "fc_alt",
            "Essayer FC04 / FC03 et longueur 1",
            "Certains équipements refusent les lectures multiples ou n'exposent qu'un type de registres.",
        ),
    ]
    return Hypothesis(
        "exception",
        "Adresse ou fonction refusée par l'esclave",
        _clamp(50 + 50 * st.exception_ratio),
        "Pas un problème réseau : l'équipement répond mais refuse la requête (registre inexistant, fonction non supportée).",
        st.slave_id,
        ev,
        tests,
    )


def _rule_fragmentation(
    st: SlaveStats, observations: list[Observation], settings: SerialSettings | None
) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or settings is None:
        return None
    truncated = [
        o
        for o in observations
        if o.slave_id == st.slave_id and o.status.name in ("CRC_ERROR", "BAD_RESPONSE") and 0 < o.rx_length < 5 + 2
    ]
    if len(truncated) < 2:
        return None
    ev = [
        f"{len(truncated)} réponses très courtes ({', '.join(str(o.rx_length) for o in truncated[:5])} octets) : trames coupées en deux",
        f"silence de fin de trame actuel : {settings.frame_gap_ms:.1f} ms",
    ]
    tests = [
        SuggestedTest(
            "gap20",
            "Campagne avec silence de fin de trame 20 ms",
            "Si les erreurs disparaissent, l'adaptateur USB fragmente les réponses ; garder cette valeur.",
            runnable=True,
            inter_frame_delay_ms=20.0,
        ),
    ]
    return Hypothesis(
        "fragment",
        "Délai inter-trames trop court (fragmentation USB)",
        _clamp(40 + 15 * len(truncated)),
        "Des réponses arrivent en plusieurs morceaux séparés de plus que le silence configuré, et sont lues comme deux trames.",
        st.slave_id,
        ev,
        tests,
    )


def _rule_transport(stats: dict[int, SlaveStats]) -> Hypothesis | None:
    n = sum(st.transport_error for st in stats.values())
    if n == 0:
        return None
    total = sum(st.total for st in stats.values())
    ev = [f"{n} erreur(s) de liaison série sur {total} requêtes (port disparu, écriture refusée)"]
    tests = [
        SuggestedTest(
            "usb",
            "Changer de port USB et de câble",
            "Un concentrateur USB ou un câble abîmé provoque des déconnexions de l'adaptateur.",
        ),
        SuggestedTest(
            "power",
            "Vérifier l'alimentation de l'adaptateur",
            "Les adaptateurs isolés alimentés par le bus décrochent si la tension chute.",
        ),
    ]
    return Hypothesis(
        "transport",
        "Adaptateur USB / port série instable",
        _clamp(40 + 20 * n),
        "Le port lui-même disparaît ou refuse d'émettre : le défaut est côté PC / adaptateur, pas sur le bus.",
        None,
        ev,
        tests,
    )


def _rule_healthy(stats: dict[int, SlaveStats]) -> Hypothesis | None:
    if not stats:
        return None
    total = sum(st.total for st in stats.values())
    if total < MIN_SAMPLES:
        return None
    ok = sum(st.ok + st.exception for st in stats.values())
    if ok / total < 0.99:
        return None
    ev = [f"{ok}/{total} échanges valides sur {len(stats)} esclave(s)"]
    for st in stats.values():
        if st.rt_avg is not None:
            ev.append(f"esclave {st.slave_id} : {st.rt_avg:.1f} ms en moyenne, max {st.rt_max:.1f} ms")
    return Hypothesis(
        "healthy",
        "Réseau sain sur la période observée",
        _clamp(60 + 40 * ok / total),
        "Aucun défaut significatif ; prolonger l'observation (cyclique ou espion) si le problème est intermittent.",
        None,
        ev,
        [],
    )


def analyse(
    stats: dict[int, SlaveStats], observations: Iterable[Observation], settings: SerialSettings | None
) -> list[Hypothesis]:
    obs = list(observations)
    hyps: list[Hypothesis] = []
    for st in stats.values():
        for h in (
            _rule_absent(st),
            _rule_framing(st),
            _rule_line_quality(st, settings),
            _rule_slow_slave(st, settings),
            _rule_conflict(st),
            _rule_exceptions(st),
            _rule_fragmentation(st, obs, settings),
        ):
            if h is not None:
                hyps.append(h)
    for h in (_rule_transport(stats), _rule_healthy(stats)):
        if h is not None:
            hyps.append(h)
    hyps.sort(key=lambda h: h.score, reverse=True)
    return hyps


@dataclass(slots=True)
class CampaignComparison:
    """Résultat d'un test exécuté, comparé à la situation de référence."""

    test: SuggestedTest
    baseline: SlaveStats
    result: SlaveStats

    def verdict(self) -> str:
        b, r = self.baseline, self.result
        if r.total == 0:
            return "aucune mesure"
        if r.error_ratio == 0 and b.error_ratio > 0:
            return "défauts disparus : hypothèse confirmée"
        if r.error_ratio < b.error_ratio * 0.5:
            return f"défauts réduits ({_pct(b.error_ratio)} -> {_pct(r.error_ratio)}) : hypothèse probable"
        if r.error_ratio > b.error_ratio * 1.5 and r.error_ratio > 0.05:
            return f"défauts aggravés ({_pct(b.error_ratio)} -> {_pct(r.error_ratio)}) : hypothèse écartée"
        return f"pas de changement notable ({_pct(b.error_ratio)} -> {_pct(r.error_ratio)}) : hypothèse peu probable"
