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

from modbusai.analysis.campaign import CampaignSpec
from modbusai.analysis.observations import Observation, SlaveStats
from modbusai.modbus.exceptions import exception_label
from modbusai.modbus.records import Request
from modbusai.transport.records import LinkSettings, Parity, SerialSettings

MIN_SAMPLES = 5  # en dessous, on ne conclut pas

SCORE_LEGEND = (
    (0, 49, "peu probable", "#2ea043"),
    (50, 74, "probable", "#d29922"),
    (75, 100, "très probable", "#e5534b"),
)
SCORE_EXPLANATION = (
    "Le score (0 à 100) est une vraisemblance : il monte avec la part des échanges qui présentent la signature "
    "de l'hypothèse (timeouts, CRC, réponses incohérentes, temps de réponse) et avec le nombre d'observations. "
    "Il ne dit pas qu'une cause est certaine : les tests proposés servent à départager les hypothèses."
)


@dataclass(frozen=True, slots=True)
class HypothesisInfo:
    """Fiche d'une hypothèse : ce qui la déclenche, les causes physiques, comment la départager.
    Les règles d'analyse en tirent titre et résumé : une seule source de vérité."""

    key: str
    title: str
    summary: str
    trigger: str  # condition mesurée qui fait apparaître l'hypothèse
    causes: tuple[str, ...]  # causes physiques classiques sur chantier
    how_to_confirm: tuple[str, ...]  # tests et vérifications


CATALOGUE: dict[str, HypothesisInfo] = {
    "absent": HypothesisInfo(
        "absent",
        "Esclave absent, adresse ou câblage incorrect",
        "Rien ne répond à cette adresse : équipement hors tension, adresse différente, A/B inversés ou vitesse fausse.",
        "Au moins 5 requêtes, aucune réponse valide ni exception, plus de 90 % de timeouts.",
        (
            "équipement hors tension ou en défaut",
            "adresse esclave différente de celle attendue",
            "fils A et B inversés",
            "vitesse ou parité différente (l'esclave ne reconnaît pas la trame)",
            "bus coupé entre le maître et l'esclave",
        ),
        (
            "scanner les adresses (onglet Scan réseau)",
            "inverser A et B",
            "balayer vitesses et parités",
            "essayer FC03 puis FC04 sur le registre 0",
        ),
    ),
    "framing": HypothesisInfo(
        "framing",
        "Vitesse ou parité incorrecte",
        "L'équipement répond mais les octets sont mal interprétés : paramètres série différents de ceux de l'esclave.",
        "Plus de 30 % de réponses au CRC invalide et moins de 50 % de réussite.",
        (
            "vitesse différente entre maître et esclave",
            "parité ou bits de stop différents",
            "esclave en 7 bits de données",
        ),
        ("balayage des vitesses et parités (Scan réseau)", "campagne en 8E1", "campagne en 8N2"),
    ),
    "line": HypothesisInfo(
        "line",
        "Qualité de ligne : bruit, terminaisons, longueur",
        "Échanges majoritairement bons mais défauts aléatoires : typique d'un bus mal terminé, non polarisé, trop long ou perturbé.",
        "Plus de 50 % de réussite avec au moins 2 % de défauts intermittents (CRC, timeouts, incohérentes).",
        (
            "terminaisons 120 Ω absentes, doublées ou mal placées",
            "polarisation (pull-up / pull-down) absente",
            "bus trop long pour la vitesse",
            "blindage non relié ou relié aux deux extrémités",
            "câble non torsadé, cheminement près de variateurs",
            "connexion oxydée ou vis desserrée",
        ),
        (
            "vérifier terminaisons et polarisation",
            "campagne à 9600 bauds",
            "campagne à période lente",
            "test de torture : les trames longues souffrent plus que les courtes",
        ),
    ),
    "slow": HypothesisInfo(
        "slow",
        "Esclave lent, timeout trop court",
        "Les réponses réussies frôlent le délai configuré : les timeouts sont probablement des réponses arrivées trop tard.",
        "Des timeouts et un P95 du temps de réponse supérieur à 60 % du timeout.",
        (
            "équipement lent à répondre (passerelle, automate chargé)",
            "timeout de supervision trop court",
            "réponse retardée par une passerelle RTU/TCP",
        ),
        ("campagne avec timeout doublé", "test de torture : phase timeout serré"),
    ),
    "echo": HypothesisInfo(
        "echo",
        "Écho de l'adaptateur (direction RS-485)",
        "L'outil reçoit sa propre requête : l'adaptateur ne coupe pas la réception pendant l'émission.",
        "Réponses incohérentes qui sont l'écho exact de la requête émise.",
        ("adaptateur USB/RS-485 sans direction automatique", "RTS non piloté", "adaptateur 4 fils câblé en 2 fils"),
        ("activer le pilotage RTS dans CONFIGURATION", "changer d'adaptateur (CH340, FTDI avec TXDEN)"),
    ),
    "conflict": HypothesisInfo(
        "conflict",
        "Conflit d'adresse ou réponse d'un autre esclave",
        "Une réponse valide arrive mais ne correspond pas à la requête : deux équipements partagent probablement l'adresse.",
        "Réponses au CRC juste mais esclave, fonction ou longueur incohérents (hors écho).",
        (
            "deux esclaves à la même adresse",
            "équipement qui répond à toutes les adresses",
            "réponse tardive d'une requête précédente",
        ),
        (
            "écouter le bus (onglet Espion) : deux réponses à une même requête",
            "débrancher les esclaves un par un",
            "scanner les adresses",
        ),
    ),
    "exception": HypothesisInfo(
        "exception",
        "Adresse ou fonction refusée par l'esclave",
        "Pas un problème réseau : l'équipement répond mais refuse la requête (registre inexistant, fonction non supportée).",
        "Plus de 50 % d'exceptions Modbus (codes 01, 02, 03...).",
        (
            "adresse de registre hors table (base 0 / base 1)",
            "type de registre erroné (holding / input)",
            "longueur de lecture supérieure au maximum de l'équipement",
            "fonction non supportée",
        ),
        ("vérifier la table d'échange", "essayer FC04 / FC03 et longueur 1"),
    ),
    "fragment": HypothesisInfo(
        "fragment",
        "Délai inter-trames trop court (fragmentation USB)",
        "Des réponses arrivent en plusieurs morceaux séparés de plus que le silence configuré, et sont lues comme deux trames.",
        "Au moins deux réponses très courtes (moins de 7 octets) en CRC invalide ou incohérentes.",
        ("adaptateur USB à forte latence (16 ms)", "délai inter-trames réglé trop bas", "PC chargé"),
        ("campagne avec silence de fin de trame à 20 ms", "régler le délai inter-trames dans CONFIGURATION"),
    ),
    "transport": HypothesisInfo(
        "transport",
        "Adaptateur USB / port série instable",
        "Le port lui-même disparaît ou refuse d'émettre : le défaut est côté PC / adaptateur, pas sur le bus.",
        "Au moins une erreur de liaison (port disparu, écriture refusée) dans la session.",
        (
            "câble USB ou concentrateur défaillant",
            "pilote de l'adaptateur",
            "alimentation de l'adaptateur isolé",
            "mise en veille USB de Windows",
        ),
        (
            "changer de port USB et de câble",
            "vérifier l'alimentation de l'adaptateur",
            "désactiver la mise en veille sélective USB",
        ),
    ),
    "healthy": HypothesisInfo(
        "healthy",
        "Réseau sain sur la période observée",
        "Aucun défaut significatif ; prolonger l'observation (cyclique ou espion) si le problème est intermittent.",
        "Au moins 99 % d'échanges valides (OK ou exception) sur au moins 5 observations.",
        ("aucune", "défaut intermittent non capturé sur la période"),
        ("prolonger en cyclique ou en espion", "lancer le test de torture"),
    ),
}


@dataclass(frozen=True, slots=True)
class SuggestedTest:
    key: str
    title: str
    description: str
    runnable: bool = False
    count: int | None = None  # limite haute de lectures ; None = jusqu'à la durée
    period_ms: int = 200
    duration_s: float | None = 120.0  # « le test se fait pendant deux minutes »
    timeout_ms: float | None = None
    baudrate: int | None = None
    parity: Parity | None = None
    stopbits: float | None = None
    inter_frame_delay_ms: float | None = None

    def apply(self, settings: LinkSettings) -> LinkSettings:
        """Paramètres de liaison pour la campagne. En TCP seul le timeout s'applique."""
        changes: dict = {}
        if self.timeout_ms is not None:
            changes["response_timeout_ms"] = self.timeout_ms
        if not isinstance(settings, SerialSettings):
            return replace(settings, **changes) if changes else settings
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

    def to_campaign(self, request: Request) -> CampaignSpec:
        return CampaignSpec(
            request,
            period_ms=self.period_ms,
            duration_s=self.duration_s,
            max_count=self.count,
            timeout_ms=self.timeout_ms,
            baudrate=self.baudrate,
            parity=self.parity,
            stopbits=self.stopbits,
            inter_frame_delay_ms=self.inter_frame_delay_ms,
            label=self.title,
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
        CATALOGUE["absent"].title,
        _clamp(60 + 40 * st.timeout_ratio),
        CATALOGUE["absent"].summary,
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
        CATALOGUE["framing"].title,
        _clamp(50 + 50 * ratio),
        CATALOGUE["framing"].summary,
        st.slave_id,
        ev,
        tests,
    )


def _rule_line_quality(st: SlaveStats, settings: LinkSettings | None) -> Hypothesis | None:
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
    if isinstance(settings, SerialSettings) and settings.baudrate > 9600:
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
        CATALOGUE["line"].title,
        _clamp(score),
        CATALOGUE["line"].summary,
        st.slave_id,
        ev,
        tests,
    )


def _rule_slow_slave(st: SlaveStats, settings: LinkSettings | None) -> Hypothesis | None:
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
        CATALOGUE["slow"].title,
        _clamp(40 + 60 * min(1.0, p95 / settings.response_timeout_ms)),
        CATALOGUE["slow"].summary,
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
            CATALOGUE["echo"].title,
            _clamp(50 + 50 * st.bad_response / st.total),
            CATALOGUE["echo"].summary,
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
        CATALOGUE["conflict"].title,
        _clamp(40 + 60 * st.bad_response / st.total),
        CATALOGUE["conflict"].summary,
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
        CATALOGUE["exception"].title,
        _clamp(50 + 50 * st.exception_ratio),
        CATALOGUE["exception"].summary,
        st.slave_id,
        ev,
        tests,
    )


def _rule_fragmentation(
    st: SlaveStats, observations: list[Observation], settings: LinkSettings | None
) -> Hypothesis | None:
    if st.total < MIN_SAMPLES or not isinstance(settings, SerialSettings):
        return None  # la fragmentation USB n'a pas d'équivalent en TCP
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
        CATALOGUE["fragment"].title,
        _clamp(40 + 15 * len(truncated)),
        CATALOGUE["fragment"].summary,
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
        CATALOGUE["transport"].title,
        _clamp(40 + 20 * n),
        CATALOGUE["transport"].summary,
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
        CATALOGUE["healthy"].title,
        _clamp(60 + 40 * ok / total),
        CATALOGUE["healthy"].summary,
        None,
        ev,
        [],
    )


def analyse(
    stats: dict[int, SlaveStats], observations: Iterable[Observation], settings: LinkSettings | None
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
