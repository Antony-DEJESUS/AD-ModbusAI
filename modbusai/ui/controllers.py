"""Séquenceurs côté interface : enchaînent des requêtes une par une via le
worker maître, sans bloquer Qt. La décision (plan, classification, verdict)
vient de ``analysis`` ; ici on ne fait qu'ordonnancer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal

from modbusai.analysis.diagnostic import CampaignComparison, SuggestedTest
from modbusai.analysis.identification import decode_device_id, decode_report_slave_id
from modbusai.analysis.observations import Observation, SlaveStats, compute_stats
from modbusai.analysis.scanner import ScanPlan, ScanResult, ScanStatus, identification_requests, merge_attempts
from modbusai.analysis.session import SessionStore
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus, FunctionCode, Request
from modbusai.transport.records import SerialSettings
from modbusai.ui.workers import ExecuteJob


class ScanController(QObject):
    """Parcourt variantes de liaison × adresses ; identifie les présents."""

    execute_requested = Signal(object)  # ExecuteJob
    reopen_requested = Signal(object)  # SerialSettings
    progress = Signal(int, int, str)  # fait, total, libellé
    result_ready = Signal(object)  # ScanResult
    finished = Signal(bool)  # True si terminé normalement, False si annulé / erreur
    TAG = "scan"

    def __init__(self, session: SessionStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._plan: ScanPlan | None = None
        self._variants: list[SerialSettings] = []
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
    def on_connected(self, settings: SerialSettings) -> None:
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
    """Campagne de N lectures pour un test de diagnostic, avec paramètres surchargés."""

    execute_requested = Signal(object)
    reopen_requested = Signal(object)
    progress = Signal(int, int)
    finished = Signal(object)  # CampaignComparison | None
    TAG = "test"

    def __init__(self, session: SessionStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._active = False
        self._test: SuggestedTest | None = None
        self._baseline: SlaveStats | None = None
        self._request: Request | None = None
        self._base_settings: SerialSettings | None = None
        self._records: list[ExchangeRecord] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._send)
        self._waiting_reopen = False
        self._restoring = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, test: SuggestedTest, baseline: SlaveStats, request: Request, base_settings: SerialSettings) -> None:
        self._test, self._baseline, self._request, self._base_settings = test, baseline, request, base_settings
        self._records = []
        self._active = True
        self._restoring = False
        if test.changes_link:
            self._waiting_reopen = True
            self.reopen_requested.emit(test.apply(base_settings))
        else:
            self._send()

    def cancel(self) -> None:
        if self._active:
            self._active = False
            self._timer.stop()
            self._finish(None)

    def on_connected(self, settings: SerialSettings) -> None:
        if self._restoring:
            self._restoring = False
            return
        if self._active and self._waiting_reopen:
            self._waiting_reopen = False
            self._send()

    def on_link_error(self, message: str) -> None:
        if self._active and self._waiting_reopen:
            self._waiting_reopen = False
            self._active = False
            self._finish(None)

    def on_record(self, rec: ExchangeRecord, job: ExecuteJob) -> None:
        if not self._active or job.tag != self.TAG or self._test is None:
            return
        self.session.add_record(rec, source=self.TAG)
        self._records.append(rec)
        self.progress.emit(len(self._records), self._test.count)
        if rec.status is ExchangeStatus.TRANSPORT_ERROR or len(self._records) >= self._test.count:
            self._active = False
            slave_id = self._request.slave_id if self._request is not None else -1
            result = compute_stats(Observation.from_record(r, self.TAG) for r in self._records).get(
                slave_id, SlaveStats(slave_id)
            )
            self._finish(CampaignComparison(self._test, self._baseline, result) if self._baseline is not None else None)
            return
        self._timer.start(self._test.period_ms)

    def on_request_failed(self, message: str, job: ExecuteJob) -> None:
        if self._active and job.tag == self.TAG:
            self._active = False
            self._finish(None)

    def _send(self) -> None:
        if self._active and self._request is not None and self._test is not None:
            self.execute_requested.emit(ExecuteJob(self._request, self._test.timeout_ms, self.TAG))

    def _finish(self, comparison: CampaignComparison | None) -> None:
        if self._test is not None and self._test.changes_link and self._base_settings is not None:
            self._restoring = True
            self.reopen_requested.emit(self._base_settings)
        self.finished.emit(comparison)


def probe_request_for(slave_id: int, template: Request | None) -> Request:
    """Requête de campagne : celle du maître si elle vise cet esclave, sinon FC03 @0."""
    if template is not None and template.function in (1, 2, 3, 4):
        return replace(template, slave_id=slave_id)
    return Request(slave_id, FunctionCode.READ_HOLDING_REGISTERS, 0, 1)


ProbeProvider = Callable[[], Request | None]
