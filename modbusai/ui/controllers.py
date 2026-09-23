"""Séquenceurs côté interface : enchaînent des requêtes une par une via le
worker maître, sans bloquer Qt. La décision (plan, classification, verdict)
vient de ``analysis`` ; ici on ne fait qu'ordonnancer."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal

from modbusai.analysis.campaign import CampaignSpec, campaign_stats
from modbusai.analysis.identification import decode_device_id, decode_report_slave_id
from modbusai.analysis.observations import Observation, SlaveStats
from modbusai.analysis.scanner import ScanPlan, ScanResult, ScanStatus, identification_requests, merge_attempts
from modbusai.analysis.session import SessionStore
from modbusai.analysis.stress import PhaseResult, StressPhase, evaluate
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import LinkSettings
from modbusai.ui.workers import ExecuteJob


class ScanController(QObject):
    """Parcourt variantes de liaison × adresses ; identifie les présents."""

    execute_requested = Signal(object)  # ExecuteJob
    reopen_requested = Signal(object)  # LinkSettings
    progress = Signal(int, int, str)  # fait, total, libellé
    result_ready = Signal(object)  # ScanResult
    finished = Signal(bool)  # True si terminé normalement, False si annulé / erreur
    TAG = "scan"

    def __init__(self, session: SessionStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._plan: ScanPlan | None = None
        self._variants: list[LinkSettings] = []
        self._variant_idx = 0
        self._slave_idx = 0
        self._attempts: list[ExchangeRecord] = []
        self._ident_pending: list[Request] = []
        self._current: ScanResult | None = None
        self._done = 0
        self._active = False
        self._waiting_reopen = False
        self.results: list[ScanResult] = []

    @property
    def active(self) -> bool:
        return self._active

    # ---------------------------------------------------------------- API
    def start(self, plan: ScanPlan) -> None:
        self._plan = plan
        self._variants = plan.settings_variants()
        self._variant_idx = 0
        self._slave_idx = 0
        self._done = 0
        self._attempts = []
        self._ident_pending = []
        self._current = None
        self.results = []
        self._active = True
        self._open_variant()

    def cancel(self) -> None:
        if not self._active:
            return
        self._active = False
        self._restore_and_finish(False)

    # ------------------------------------------------------------ retours
    def on_connected(self, settings: LinkSettings) -> None:
        if not self._active or not self._waiting_reopen:
            return
        self._waiting_reopen = False
        self._probe()

    def on_link_error(self, message: str) -> None:
        if self._active and self._waiting_reopen:
            self._waiting_reopen = False
            self._active = False
            self.finished.emit(False)

    def on_record(self, rec: ExchangeRecord, job: ExecuteJob) -> None:
        if not self._active or job.tag != self.TAG or self._plan is None:
            return
        self.session.add_record(rec, source=self.TAG)
        if (
            self._ident_pending is not None
            and self._current is not None
            and rec.request.function
            in (
                FunctionCode.READ_DEVICE_ID,
                FunctionCode.REPORT_SLAVE_ID,
            )
        ):
            self._apply_identification(rec)
            self._next_identification()
            return
        if rec.status is ExchangeStatus.TRANSPORT_ERROR:
            self._active = False
            self.finished.emit(False)
            return
        self._attempts.append(rec)
        status, _detail = merge_attempts(self._attempts)
        need_more = status is ScanStatus.ABSENT and len(self._attempts) <= self._plan.retries
        if need_more:
            self._probe()
            return
        self._conclude_slave()

    def on_request_failed(self, message: str, job: ExecuteJob) -> None:
        if self._active and job.tag == self.TAG:
            self._active = False
            self.finished.emit(False)

    # ------------------------------------------------------------ interne
    def _open_variant(self) -> None:
        assert self._plan is not None
        if self._variant_idx >= len(self._variants):
            self._restore_and_finish(True)
            return
        settings = self._variants[self._variant_idx]
        self._slave_idx = 0
        self._waiting_reopen = True
        self.progress.emit(self._done, self._plan.total_probes, f"Ouverture {settings.summary()}")
        self.reopen_requested.emit(settings)

    def _probe(self) -> None:
        assert self._plan is not None
        slaves = list(self._plan.slaves)
        if self._slave_idx >= len(slaves):
            self._variant_idx += 1
            self._open_variant()
            return
        slave = slaves[self._slave_idx]
        settings = self._variants[self._variant_idx]
        self.progress.emit(self._done, self._plan.total_probes, f"{settings.summary()}  -  esclave {slave}")
        self.execute_requested.emit(ExecuteJob(self._plan.probe_request(slave), self._plan.timeout_ms, self.TAG))

    def _conclude_slave(self) -> None:
        assert self._plan is not None
        settings = self._variants[self._variant_idx]
        slave = list(self._plan.slaves)[self._slave_idx]
        status, detail = merge_attempts(self._attempts)
        rt = next((r.response_time_ms for r in self._attempts if r.response_time_ms is not None), None)
        result = ScanResult(
            slave, settings, status, rt, detail, attempts=len(self._attempts), records=list(self._attempts)
        )
        self._attempts = []
        self._done += 1
        if result.present and self._plan.identify:
            self._current = result
            self._ident_pending = list(identification_requests(slave))
            self._next_identification()
            return
        self._publish(result)

    def _next_identification(self) -> None:
        assert self._plan is not None
        if self._ident_pending:
            req = self._ident_pending.pop(0)
            self.execute_requested.emit(ExecuteJob(req, self._plan.timeout_ms, self.TAG))
            return
        result, self._current = self._current, None
        if result is not None:
            self._publish(result)

    def _apply_identification(self, rec: ExchangeRecord) -> None:
        assert self._current is not None
        if not rec.ok or rec.values is None:
            return
        try:
            if rec.request.function is FunctionCode.READ_DEVICE_ID:
                self._current.identity = decode_device_id(bytes(rec.values))
            else:
                self._current.report_id = decode_report_slave_id(bytes(rec.values))
        except ValueError:
            pass

    def _publish(self, result: ScanResult) -> None:
        self.results.append(result)
        self.result_ready.emit(result)
        self._slave_idx += 1
        # Laisser respirer la boucle d'événements entre deux esclaves
        QTimer.singleShot(0, self._probe)

    def _restore_and_finish(self, ok: bool) -> None:
        base = self._plan.base_settings if self._plan is not None else None
        self._active = False
        if (
            base is not None
            and self._variant_idx > 0
            and base != self._variants[min(self._variant_idx, len(self._variants) - 1)]
        ):
            self.reopen_requested.emit(base)
        self.finished.emit(ok)


class CampaignController(QObject):
    """Campagne de lectures (durée et / ou nombre) avec paramètres de liaison surchargés."""

    execute_requested = Signal(object)
    reopen_requested = Signal(object)
    progress = Signal(int, int, float, float)  # lectures faites, attendues, écoulé s, restant s
    finished = Signal(object)  # SlaveStats de la campagne, ou None si interrompue avant toute lecture
    TAG = "test"

    def __init__(self, session: SessionStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._active = False
        self._spec: CampaignSpec | None = None
        self._base_settings: LinkSettings | None = None
        self._records: list[ExchangeRecord] = []
        self._started_ns = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._send)
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._emit_progress)
        self._waiting_reopen = False
        self._restoring = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def spec(self) -> CampaignSpec | None:
        return self._spec

    def start(self, spec: CampaignSpec, base_settings: LinkSettings) -> None:
        self._spec, self._base_settings = spec, base_settings
        self._records = []
        self._active = True
        self._restoring = False
        self._started_ns = time.perf_counter_ns()
        self._tick.start()
        if spec.changes_link:
            self._waiting_reopen = True
            self.reopen_requested.emit(spec.apply(base_settings))
        else:
            self._send()

    def cancel(self) -> None:
        if self._active:
            self._active = False
            self._timer.stop()
            self._finish()

    def on_connected(self, settings: LinkSettings) -> None:
        if self._restoring:
            self._restoring = False
            return
        if self._active and self._waiting_reopen:
            self._waiting_reopen = False
            self._started_ns = time.perf_counter_ns()
            self._send()

    def on_link_error(self, message: str) -> None:
        if self._active and self._waiting_reopen:
            self._waiting_reopen = False
            self._active = False
            self._finish()

    def on_record(self, rec: ExchangeRecord, job: ExecuteJob) -> None:
        if not self._active or job.tag != self.TAG or self._spec is None:
            return
        # La source distingue les échanges d'une phase qui provoque volontairement
        # des défauts ; le libellé retient de quelle campagne / phase ils viennent.
        self.session.add_record(rec, source=self._spec.source, label=self._spec.label)
        self._records.append(rec)
        self._emit_progress()
        if rec.status is ExchangeStatus.TRANSPORT_ERROR or self._spec.is_done(len(self._records), self._elapsed_s()):
            self._active = False
            self._finish()
            return
        self._timer.start(self._spec.period_ms)

    def on_request_failed(self, message: str, job: ExecuteJob) -> None:
        if self._active and job.tag == self.TAG:
            self._active = False
            self._finish()

    def _elapsed_s(self) -> float:
        return (time.perf_counter_ns() - self._started_ns) / 1e9

    def _emit_progress(self) -> None:
        if self._spec is None:
            return
        elapsed = self._elapsed_s()
        remaining = max(0.0, (self._spec.duration_s or 0.0) - elapsed) if self._spec.duration_s else 0.0
        self.progress.emit(len(self._records), self._spec.expected_count() or 0, elapsed, remaining)

    def _send(self) -> None:
        if self._active and self._spec is not None:
            request = self._spec.request_at(len(self._records))
            self.execute_requested.emit(ExecuteJob(request, self._spec.timeout_ms, self.TAG))

    def _finish(self) -> None:
        self._tick.stop()
        self._timer.stop()
        result: SlaveStats | None = None
        if self._records and self._spec is not None:
            result = campaign_stats(
                self._spec, (Observation.from_record(r, self._spec.source, self._spec.label) for r in self._records)
            )
        if self._spec is not None and self._spec.changes_link and self._base_settings is not None:
            self._restoring = True
            self.reopen_requested.emit(self._base_settings)
        self.finished.emit(result)


class StressController(QObject):
    """Enchaîne les phases d'un scénario de torture sur un CampaignController."""

    phase_started = Signal(int, int, object)  # index, total, StressPhase
    progress = Signal(int, int, float, float)
    finished = Signal(object)  # StressReport | None

    def __init__(self, campaign: CampaignController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.campaign = campaign
        self._phases: list[StressPhase] = []
        self._results: list[PhaseResult] = []
        self._index = -1
        self._active = False
        self._settings: LinkSettings | None = None
        campaign.progress.connect(self._on_progress)
        campaign.finished.connect(self._on_phase_finished)

    @property
    def active(self) -> bool:
        return self._active

    def start(self, phases: list[StressPhase], base_settings: LinkSettings) -> None:
        self._phases = list(phases)
        self._results = []
        self._index = -1
        self._settings = base_settings
        self._active = True
        self._next()

    def cancel(self) -> None:
        if self._active:
            self._active = False
            self.campaign.cancel()

    def _next(self) -> None:
        self._index += 1
        if not self._active or self._index >= len(self._phases) or self._settings is None:
            self._active = False
            self.finished.emit(evaluate(self._results) if self._results else None)
            return
        phase = self._phases[self._index]
        self.phase_started.emit(self._index, len(self._phases), phase)
        self.campaign.start(phase.spec, self._settings)

    def _on_progress(self, done: int, expected: int, elapsed: float, remaining: float) -> None:
        if self._active:
            self.progress.emit(done, expected, elapsed, remaining)

    def _on_phase_finished(self, stats) -> None:
        if not self._active and self._index < 0:
            return
        if 0 <= self._index < len(self._phases) and stats is not None:
            self._results.append(PhaseResult(self._phases[self._index], stats))
        if self._active:
            QTimer.singleShot(300, self._next)  # laisser la liaison se rétablir entre deux phases
        else:
            self.finished.emit(evaluate(self._results) if self._results else None)


def probe_request_for(slave_id: int, template: Request | None) -> Request:
    """Requête de campagne : celle du maître si elle vise cet esclave, sinon FC03 @0."""
    if template is not None and template.function in (1, 2, 3, 4):
        return replace(template, slave_id=slave_id)
    return Request(slave_id, FunctionCode.READ_HOLDING_REGISTERS, 0, 1)


ProbeProvider = Callable[[], Request | None]
