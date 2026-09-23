"""Service Modbus du serveur MCP : tient les liaisons, ordonnance les requêtes.

Équivalent sans Qt de ``ui/workers.py`` et ``ui/controllers.py`` : il ouvre les
ports, enchaîne les requêtes et accumule les observations. Aucune décision ici
non plus : classer une réponse, conclure, rédiger appartient à ``analysis``.

Une ressource, un rôle : l'arbitrage de ``modbusai.roles`` vaut pour le serveur
MCP comme pour la fenêtre. Un travail long (scan, campagne, torture, écoute)
tourne dans un fil et réserve la liaison du maître ; les outils qui en ont
besoin sont refusés pendant ce temps, en nommant ce qui occupe.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from modbusai.analysis.campaign import CampaignSpec, campaign_stats
from modbusai.analysis.diagnostic import CampaignComparison, Hypothesis, SuggestedTest, analyse
from modbusai.analysis.identification import DeviceIdentity, decode_device_id, decode_report_slave_id
from modbusai.analysis.observations import (
    DEFAULT_SOURCES,
    SOURCE_MASTER,
    SOURCE_SCAN,
    SlaveStats,
)
from modbusai.analysis.scanner import (
    ScanPlan,
    ScanResult,
    ScanStatus,
    identification_requests,
    merge_attempts,
)
from modbusai.analysis.session import SessionStore
from modbusai.analysis.sniffer import PassiveDecoder, Transaction
from modbusai.analysis.stress import PhaseResult, StressPhase, StressReport, evaluate
from modbusai.mcp.protocol import ToolError
from modbusai.modbus.master import ModbusMaster
from modbusai.modbus.records import ExchangeRecord, FunctionCode, Request
from modbusai.modbus.slave import DataStore, SlaveConfig, SlaveHandler
from modbusai.modbus.tcp_slave import make_tcp_frame_handler
from modbusai.roles import Occupancy, Role, can_start, port_key
from modbusai.transport.records import LinkSettings, SerialSettings, TcpSettings, TransportError
from modbusai.transport.serial_link import SerialLink
from modbusai.transport.tcp_link import TcpLink
from modbusai.transport.tcp_server import TcpServer

MAX_SNIFF_S = 300.0
"""Garde-fou : une écoute plus longue se pilote par plusieurs appels."""


def open_link_for(settings: LinkSettings, *, allow_tx: bool = True) -> SerialLink | TcpLink:
    if isinstance(settings, TcpSettings):
        return TcpLink(settings, allow_tx=allow_tx)
    return SerialLink(settings, allow_tx=allow_tx)


# ------------------------------------------------------------------ travaux
@dataclass(slots=True)
class JobProgress:
    """Ce qu'on peut dire d'un travail en cours sans l'interrompre."""

    kind: str
    label: str
    phase: str
    done: int
    expected: int | None
    elapsed_s: float
    running: bool
    cancelled: bool
    error: str


class Job:
    """Un travail long qui tient la liaison du maître le temps de s'exécuter."""

    def __init__(self, kind: str, label: str, expected: int | None = None) -> None:
        self.kind = kind
        self.label = label
        self.expected = expected
        self.started_at = datetime.now()
        self.done = 0
        self.phase = ""
        self.text = ""  # résultat rendu, disponible une fois terminé
        self.note = ""  # avertissement qui n'invalide pas le résultat
        self.error = ""
        self.cancelled = False
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    @property
    def elapsed_s(self) -> float:
        return (datetime.now() - self.started_at).total_seconds()

    def progress(self) -> JobProgress:
        return JobProgress(
            kind=self.kind,
            label=self.label,
            phase=self.phase,
            done=self.done,
            expected=self.expected,
            elapsed_s=self.elapsed_s,
            running=self.running,
            cancelled=self.cancelled,
            error=self.error,
        )

    def wait(self, seconds: float) -> bool:
        """Attend la fin, au plus ``seconds``. Renvoie True si le travail est fini."""
        if self.thread is None:
            return True
        self.thread.join(timeout=max(0.0, seconds))
        return not self.thread.is_alive()


# ------------------------------------------------------------ serveur esclave
class SlaveServer:
    """Simulateur d'équipement sur sa propre liaison, RTU ou TCP."""

    def __init__(self, settings: LinkSettings, store: DataStore, config: SlaveConfig) -> None:
        self.settings = settings
        self.handler = SlaveHandler(store, config)
        self.stop = threading.Event()
        self.error = ""
        self.clients: tuple[str, ...] = ()
        self.bound: LinkSettings = settings
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="modbusai-esclave", daemon=True)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    @property
    def counters(self):
        return self.handler.counters

    def start(self, timeout_s: float = 3.0) -> None:
        self._thread.start()
        self._ready.wait(timeout_s)
        if self.error:
            raise ToolError(self.error)

    def close(self, timeout_s: float = 3.0) -> None:
        self.stop.set()
        self._thread.join(timeout=timeout_s)

    def _run(self) -> None:
        try:
            if isinstance(self.settings, TcpSettings):
                self._serve_tcp()
            else:
                self._serve_rtu()
        except TransportError as exc:
            self.error = str(exc)
        finally:
            self._ready.set()

    def _serve_rtu(self) -> None:
        link = SerialLink(self.settings, allow_tx=True)
        link.open()
        self._ready.set()
        try:
            for frame in link.read_loop(self.stop):
                result = self.handler.handle(frame.data)
                if result.response is not None:
                    delay = self.handler.config.response_delay_ms
                    if delay > 0:
                        time.sleep(delay / 1000)
                    link.send(result.response)
        finally:
            link.close()

    def _serve_tcp(self) -> None:
        host = self.settings.host or "0.0.0.0"
        server = TcpServer(
            host,
            self.settings.port,
            make_tcp_frame_handler(self.handler, lambda result, client: None),
            response_delay_ms=self.handler.config.response_delay_ms,
            on_clients=self._note_clients,
        )
        server.open()
        self.bound = TcpSettings(host, server.bound_port)
        self._ready.set()
        try:
            server.serve(self.stop)
        finally:
            server.close()

    def _note_clients(self, clients) -> None:
        self.clients = tuple(clients)


# -------------------------------------------------------------------- service
class ModbusService:
    """État du serveur : liaison du maître, historique, travail en cours, esclave."""

    def __init__(self, *, allow_write: bool = False) -> None:
        self.allow_write = allow_write
        self.session = SessionStore()
        self.store = DataStore()
        self._lock = threading.RLock()
        self._link: SerialLink | TcpLink | None = None
        self._master: ModbusMaster | None = None
        self._settings: LinkSettings | None = None
        self._seq = 0
        self._busy = ""  # ce qui tient la liaison du maître
        self._job: Job | None = None
        self._slave: SlaveServer | None = None
        self.stress_report: StressReport | None = None
        self.skipped_phases: list[str] = []  # phases que l'adaptateur a refusé de régler
        self.comparisons: list[CampaignComparison] = []  # tests exécutés, comparés à leur référence

    # ------------------------------------------------------------- liaison
    @property
    def settings(self) -> LinkSettings | None:
        return self._settings

    @property
    def connected(self) -> bool:
        return self._link is not None and self._link.is_open

    @property
    def job(self) -> Job | None:
        return self._job

    @property
    def slave(self) -> SlaveServer | None:
        return self._slave

    def occupancies(self) -> list[Occupancy]:
        active: list[Occupancy] = []
        if self.connected:
            active.append(Occupancy(Role.MASTER, port_key(self._settings)))
        if self._slave is not None and self._slave.running:
            active.append(Occupancy(Role.SLAVE, port_key(self._slave.bound, listen=True)))
        return active

    def connect(self, settings: LinkSettings) -> LinkSettings:
        with self._lock:
            self._refuse_if_busy()
            others = [o for o in self.occupancies() if o.role is not Role.MASTER]
            allowed, reason = can_start(Role.MASTER, port_key(settings), others)
            if not allowed:
                raise ToolError(reason)
            self._open(settings)
            return settings

    def disconnect(self) -> bool:
        with self._lock:
            self._refuse_if_busy()
            was_open = self.connected
            self._close()
            return was_open

    def _open(self, settings: LinkSettings) -> None:
        self._close()
        link = open_link_for(settings, allow_tx=True)
        try:
            link.open()
        except TransportError as exc:
            raise ToolError(f"Ouverture impossible : {exc}") from exc
        self._link = link
        self._master = ModbusMaster(link, seq_start=self._seq)
        self._settings = settings

    def _close(self) -> None:
        if self._master is not None:
            self._seq = self._master.seq
        if self._link is not None:
            self._link.close()
        self._link = None
        self._master = None

    def _require_master(self) -> ModbusMaster:
        if self._master is None or not self.connected:
            raise ToolError("Liaison fermée : appelez d'abord l'outil « connect ».")
        return self._master

    def _refuse_if_busy(self) -> None:
        if self._busy:
            raise ToolError(
                f"{self._busy} occupe la liaison du maître. Attendez la fin (outil « job_status ») "
                "ou arrêtez le travail (outil « job_stop »)."
            )

    def require_write(self, what: str) -> None:
        if not self.allow_write:
            raise ToolError(
                f"{what} est interdit : le serveur tourne en lecture seule. "
                "Relancez-le avec l'option --ecriture pour l'autoriser."
            )

    # ------------------------------------------------------------- échanges
    def execute(self, request: Request, timeout_ms: float | None = None, source: str = SOURCE_MASTER) -> ExchangeRecord:
        with self._lock:
            self._refuse_if_busy()
            master = self._require_master()
            record = master.execute(request, timeout_ms)
            self.session.add_record(record, source=source)
            return record

    def identify(self, slave_id: int, timeout_ms: float | None = None) -> tuple[DeviceIdentity | None, str]:
        """FC43 puis FC17 : beaucoup d'équipements n'implémentent ni l'un ni l'autre."""
        identity: DeviceIdentity | None = None
        report_id = ""
        for request in identification_requests(slave_id):
            record = self._probe(request, timeout_ms, SOURCE_SCAN)
            if not record.ok or record.values is None:
                continue
            try:
                if request.function is FunctionCode.READ_DEVICE_ID:
                    identity = decode_device_id(bytes(record.values))
                else:
                    report_id = decode_report_slave_id(bytes(record.values))
            except (ValueError, IndexError):
                continue
        return identity, report_id

    def _probe(self, request: Request, timeout_ms: float | None, source: str) -> ExchangeRecord:
        """Requête interne d'un travail : la liaison est déjà réservée, on ne
        repasse donc pas par le contrôle « occupé » de ``execute``."""
        record = self._require_master().execute(request, timeout_ms)
        self.session.add_record(record, source=source)
        return record

    # ------------------------------------------------------------- travaux
    def start_job(self, job: Job, run: Callable[[Job], str]) -> Job:
        """Lance ``run`` dans un fil ; la liaison du maître lui est réservée."""
        with self._lock:
            self._refuse_if_busy()
            if job.kind != "sniff":  # l'écoute a sa propre liaison, sans droit d'émettre
                self._require_master()
            self._busy = job.label
            self._job = job

        def wrapper() -> None:
            original = self._settings
            try:
                job.text = run(job)
            except TransportError as exc:
                job.error = f"Liaison perdue : {exc}"
            except ToolError as exc:
                job.error = str(exc)
            except Exception as exc:  # le fil ne doit jamais tuer le serveur
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._lock:
                    # L'espion ferme la liaison, une campagne peut en changer les
                    # réglages : dans les deux cas on rend le bandeau tel qu'il était.
                    if original is not None and (not self.connected or self._settings != original):
                        try:
                            self._open(original)
                        except ToolError as exc:
                            if job.text:
                                job.note = f"Liaison non rouverte après le travail : {exc}"
                            else:
                                job.error = job.error or str(exc)
                    self._busy = ""

        job.thread = threading.Thread(target=wrapper, name=f"modbusai-{job.kind}", daemon=True)
        job.thread.start()
        return job

    def stop_job(self) -> Job | None:
        job = self._job
        if job is None or not job.running:
            return None
        job.cancelled = True
        job.stop.set()
        job.wait(5.0)
        return job

    # -------------------------------------------------------------- scan
    def run_scan(self, plan: ScanPlan, job: Job) -> tuple[list[ScanResult], list[str]]:
        """Parcourt variantes de liaison x adresses, puis identifie les présents.

        Une variante que l'adaptateur refuse (vitesse ou parité non gérée) est
        sautée et signalée : elle ne doit pas emporter tout le balayage.
        """
        results: list[ScanResult] = []
        skipped: list[str] = []
        for variant in plan.settings_variants():
            if job.stop.is_set():
                break
            try:
                with self._lock:
                    if self._settings != variant:
                        self._open(variant)
            except ToolError as exc:
                skipped.append(f"{variant.summary()} : {exc}")
                continue
            job.phase = variant.summary()
            for slave_id in plan.slaves:
                if job.stop.is_set():
                    break
                result = self._probe_slave(plan, slave_id, variant)
                job.done += 1
                if result.present and plan.identify:
                    result.identity, result.report_id = self.identify(slave_id, plan.timeout_ms)
                results.append(result)
        return results, skipped

    def _probe_slave(self, plan: ScanPlan, slave_id: int, variant: LinkSettings) -> ScanResult:
        """Une adresse : on réessaie tant que « absent », un timeout isolé ne
        doit pas masquer un esclave qui répond une fois sur deux."""
        attempts: list[ExchangeRecord] = []
        status, detail = ScanStatus.ABSENT, "aucune réponse"
        for _ in range(plan.retries + 1):
            attempts.append(self._probe(plan.probe_request(slave_id), plan.timeout_ms, SOURCE_SCAN))
            status, detail = merge_attempts(attempts)
            if status is not ScanStatus.ABSENT:
                break
        answered = next((r for r in attempts if r.response_time_ms is not None), None)
        return ScanResult(
            slave_id,
            variant,
            status,
            answered.response_time_ms if answered is not None else None,
            detail,
            attempts=len(attempts),
        )

    # ---------------------------------------------------------- campagne
    def run_campaign(self, spec: CampaignSpec, job: Job) -> SlaveStats:
        """Répète la requête au rythme demandé, jusqu'à la durée ou au compte.

        Les paramètres de liaison surchargés (timeout serré, vitesse réduite)
        sont appliqués le temps de la campagne ; ``start_job`` rétablit ensuite
        ceux du bandeau.
        """
        with self._lock:
            base = self._settings
            if base is None:
                raise ToolError("Liaison fermée.")
            wanted = spec.apply(base)
            if base != wanted:
                self._open(wanted)
        observations = []
        started = time.perf_counter()
        count = 0
        period = max(0.0, spec.period_ms / 1000)
        next_tick = started
        while not job.stop.is_set() and not spec.is_done(count, time.perf_counter() - started):
            record = self._require_master().execute(spec.request_at(count), spec.timeout_ms)
            observations.append(self.session.add_record(record, source=spec.source, label=spec.label))
            count += 1
            job.done = count
            # Échéance absolue : sous Windows chaque attente est arrondie au pas de
            # l'horloge (~15 ms) ; mesurée d'un pas à l'autre, l'erreur s'accumulait.
            next_tick = max(next_tick + period, time.perf_counter() - period)
            remaining = next_tick - time.perf_counter()
            if remaining > 0:
                job.stop.wait(remaining)
        return campaign_stats(spec, observations)

    def run_stress(self, phases: Sequence[StressPhase], job: Job) -> StressReport:
        """Enchaîne les phases du scénario ; chacune est une campagne."""
        results: list[PhaseResult] = []
        self.skipped_phases = []
        for index, phase in enumerate(phases, start=1):
            if job.stop.is_set():
                break
            job.phase = f"{index}/{len(phases)} {phase.title}"
            job.done = 0
            job.expected = phase.spec.expected_count()
            try:
                results.append(PhaseResult(phase, self.run_campaign(phase.spec, job)))
            except ToolError as exc:
                # Vitesse ou parité que l'adaptateur refuse : on saute la phase
                # et on le dit, plutôt que de perdre les phases suivantes.
                self.skipped_phases.append(f"{phase.title} : {exc}")
        report = evaluate(results)
        self.stress_report = report
        return report

    # ------------------------------------------------------------- espion
    def sniff_settings(self, settings: LinkSettings | None) -> SerialSettings:
        """Liaison de l'écoute : celle demandée, sinon celle du maître."""
        chosen = settings if settings is not None else self._settings
        if chosen is None:
            raise ToolError(
                "Aucune liaison : donnez le port et la vitesse du bus à écouter, ou connectez d'abord le maître."
            )
        if not isinstance(chosen, SerialSettings):
            raise ToolError(
                "L'espion n'existe qu'en Modbus RTU : en TCP il faudrait une recopie de port sur le commutateur."
            )
        return chosen

    def run_sniff(self, settings: SerialSettings, seconds: float, job: Job) -> list[Transaction]:
        """Écoute passive : le port est ouvert sans droit d'émettre.

        Si l'écoute vise le port déjà tenu par le maître, cette liaison est
        fermée d'abord et rouverte à la fin, comme le fait la fenêtre. Sur un
        autre port, le maître n'est pas touché : les deux cohabitent.
        """
        with self._lock:
            others = self.occupancies()
            if self.connected and port_key(self._settings) == port_key(settings):
                self._close()  # l'espion prend la place du maître sur ce port
            else:
                allowed, reason = can_start(Role.SNIFFER, port_key(settings), others)
                if not allowed:
                    raise ToolError(reason)
        decoder = PassiveDecoder(settings.response_timeout_ms)
        link = SerialLink(settings, allow_tx=False)
        link.open()
        deadline = time.perf_counter() + seconds
        transactions: list[Transaction] = []
        try:
            for frame in link.read_loop(job.stop):
                decoder.feed(frame)
                decoder.flush(time.perf_counter_ns())
                done = decoder.pop_completed()
                transactions.extend(done)
                job.done = len(transactions)
                if time.perf_counter() >= deadline:
                    break
        finally:
            decoder.flush(time.perf_counter_ns() + 10**12)
            transactions.extend(decoder.pop_completed())
            job.done = len(transactions)
            link.close()
        for transaction in transactions:
            self.session.add_transaction(transaction, settings)
        return transactions

    # --------------------------------------------------------- diagnostic
    def stats(self, sources: Sequence[str] | None = None) -> dict[int, SlaveStats]:
        return self.session.stats(sources or DEFAULT_SOURCES)

    def hypotheses(self, sources: Sequence[str] | None = None) -> list[Hypothesis]:
        chosen = sources or DEFAULT_SOURCES
        return analyse(self.stats(chosen), self.session.observations(chosen), self._settings)

    def find_test(self, key: str) -> tuple[Hypothesis, SuggestedTest]:
        """Le test suggéré portant cette clé, dans les hypothèses en cours."""
        runnable: list[str] = []
        for hypothesis in self.hypotheses():
            for test in hypothesis.tests:
                if test.runnable:
                    runnable.append(test.key)
                if test.key == key:
                    if not test.runnable:
                        raise ToolError(
                            f"Le test « {key} » ({test.title}) demande une action sur le bus, "
                            f"l'outil ne peut pas l'exécuter : {test.description}"
                        )
                    return hypothesis, test
        available = ", ".join(dict.fromkeys(runnable)) or "aucun"
        raise ToolError(
            f"Aucun test « {key} » dans les hypothèses en cours. Exécutables actuellement : {available}. "
            "Appelez « analyse » pour voir les hypothèses et leurs tests."
        )

    def clear(self) -> None:
        self.session.clear()
        self.stress_report = None
        self.comparisons.clear()

    # ---------------------------------------------------- serveur esclave
    def slave_start(self, settings: LinkSettings, config: SlaveConfig) -> SlaveServer:
        with self._lock:
            if self._slave is not None and self._slave.running:
                raise ToolError("Le serveur esclave tourne déjà : arrêtez-le d'abord (outil « slave_stop »).")
            others = [o for o in self.occupancies() if o.role is not Role.SLAVE]
            allowed, reason = can_start(Role.SLAVE, port_key(settings, listen=True), others)
            if not allowed:
                raise ToolError(reason)
            server = SlaveServer(settings, self.store, config)
            server.start()
            self._slave = server
            return server

    def slave_stop(self) -> bool:
        with self._lock:
            server = self._slave
            if server is None or not server.running:
                self._slave = None
                return False
            server.close()
            self._slave = None
            return True

    def shutdown(self) -> None:
        self.stop_job()
        self.slave_stop()
        with self._lock:
            self._close()


def _differs(current: LinkSettings | None, wanted: LinkSettings | None) -> bool:
    return current != wanted
