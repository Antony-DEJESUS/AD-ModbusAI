"""Fenêtre principale : bandeau de connexion, thème, onglets, arbitrage du port série.

Un seul rôle occupe le port à la fois : maître (onglets Maître, Scan,
Diagnostic), espion ou serveur esclave. La fenêtre possède le worker maître
et lance / arrête les threads espion et esclave à la demande des pages.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modbusai import APP_TITLE, __version__
from modbusai.analysis.campaign import CampaignSpec
from modbusai.analysis.session import SessionStore
from modbusai.i18n import current_language, set_language, tr
from modbusai.modbus.records import ExchangeRecord, ExchangeStatus
from modbusai.modbus.slave import DataStore, SlaveConfig
from modbusai.transport.records import LinkSettings, Parity, SerialSettings, TcpSettings
from modbusai.ui.controllers import CampaignController, ScanController, StressController
from modbusai.ui.iconography import refresh_all as refresh_icons
from modbusai.ui.iconography import set_tab_icon
from modbusai.ui.pages.diagnostic_page import DiagnosticPage
from modbusai.ui.pages.master_page import MasterPage
from modbusai.ui.pages.scan_page import ScanPage
from modbusai.ui.pages.slave_page import SlavePage
from modbusai.ui.pages.sniffer_page import SnifferPage
from modbusai.ui.resources import app_icon
from modbusai.ui.roles import Occupancy, Role, Tab, can_start, port_key, tab_states
from modbusai.ui.theme import THEMES, apply_theme, system_theme
from modbusai.ui.widgets.about_dialog import AUTHOR, AboutDialog
from modbusai.ui.widgets.config_dialog import ConfigDialog
from modbusai.ui.widgets.connection_bar import ConnectionBar
from modbusai.ui.workers import ExecuteJob, ModbusWorker, SlaveWorker, SnifferWorker, TcpSlaveWorker

RECONNECT_DELAY_MS = 1500
PORT_RELEASE_DELAY_MS = 400  # temps laissé au système pour rendre le port avant qu'un autre rôle l'ouvre


class MainWindow(QMainWindow):
    _cmd_open = Signal(object)
    _cmd_close = Signal()
    _cmd_execute = Signal(object)
    relaunch_requested = Signal()  # changement de langue : l'application recrée la fenêtre

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 760)

        self._serial_settings, self._tcp_settings, self._protocol = self._load_settings()
        self._connected = False
        self._manual_disconnect = False
        self._reconnect_pending = False
        self._pending_after_disconnect = None  # action à lancer une fois le port rendu
        self._sniffer: SnifferWorker | None = None
        self._slave: SlaveWorker | None = None
        self.session = SessionStore()
        self.store = DataStore()

        # ------------------------------------------------------------ widgets
        self.connection_bar = ConnectionBar()
        self.master_page = MasterPage()
        self.sniffer_page = SnifferPage(self.session)
        self.scan_page = ScanPage()
        self.diagnostic_page = DiagnosticPage(self.session)
        self.slave_page = SlavePage(self.store)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self._tab_index: dict[Tab, int] = {}
        for tab, page, glyph in (
            (Tab.MASTER, self.master_page, "exchange"),
            (Tab.SNIFFER, self.sniffer_page, "eye"),
            (Tab.SCAN, self.scan_page, "search"),
            (Tab.DIAGNOSTIC, self.diagnostic_page, "pulse"),
            (Tab.SLAVE, self.slave_page, "server"),
        ):
            index = self.tabs.addTab(page, tr(tab.value))
            set_tab_icon(self.tabs, index, glyph)
            self._tab_index[tab] = index
        self.status_label = QLabel(tr("Status : déconnecté"))
        self.status_label.setProperty("variant", "muted")
        credit = tr("Fait avec CC par {p0}").format(p0=AUTHOR)
        self.credit_label = QLabel(f"<a href='about' style='color: inherit; text-decoration: none;'>{credit}</a>")
        self.credit_label.setObjectName("credit")
        self.credit_label.setToolTip(tr("À propos : logo, version, historique, mode d'emploi"))
        self.credit_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.credit_label.linkActivated.connect(lambda _href: self._show_about())
        self.setWindowIcon(app_icon())

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(self.connection_bar)
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(4, 0, 4, 0)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.credit_label)
        layout.addLayout(footer)
        self.setCentralWidget(central)

        # ------------------------------------------------------------- worker
        self._thread = QThread(self)
        self._worker = ModbusWorker()
        self._worker.moveToThread(self._thread)
        self._cmd_open.connect(self._worker.open_link)
        self._cmd_close.connect(self._worker.close_link)
        self._cmd_execute.connect(self._worker.execute)
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.link_error.connect(self._on_link_error)
        self._worker.record_ready.connect(self._on_record)
        self._worker.request_failed.connect(self._on_request_failed)
        self._thread.start()

        self.scan_ctl = ScanController(self.session, self)
        self.campaign_ctl = CampaignController(self.session, self)
        self.stress_ctl = StressController(self.campaign_ctl, self)
        self._pending_after_connect = None  # action à lancer dès que la liaison est ouverte
        for ctl in (self.scan_ctl, self.campaign_ctl):
            ctl.execute_requested.connect(self._cmd_execute)
            ctl.reopen_requested.connect(self._reopen_for_controller)
            self._worker.connected.connect(ctl.on_connected)
            self._worker.link_error.connect(ctl.on_link_error)
            self._worker.record_ready.connect(ctl.on_record)
            self._worker.request_failed.connect(ctl.on_request_failed)

        # ------------------------------------------------------------ signaux
        self.connection_bar.configure_requested.connect(self._configure)
        self.connection_bar.connect_requested.connect(self._connect)
        self.connection_bar.disconnect_requested.connect(self._disconnect)
        self.connection_bar.about_requested.connect(self._show_about)
        self.connection_bar.quit_requested.connect(self.close)
        self.connection_bar.theme_toggled.connect(self._toggle_theme)
        self.connection_bar.protocol_changed.connect(self._on_protocol_changed)
        self.connection_bar.language_changed.connect(self._on_language_changed)
        self.connection_bar.set_language(current_language())

        self.master_page.execute_requested.connect(self._cmd_execute)
        self.master_page.status_message.connect(self._set_status)
        self.master_page.link_lost.connect(self._on_link_lost)

        self.sniffer_page.start_requested.connect(self._start_sniffer)
        self.sniffer_page.stop_requested.connect(self._stop_sniffer)
        self.sniffer_page.status_message.connect(self._set_status)

        self.scan_page.start_requested.connect(self._start_scan)
        self.scan_page.cancel_requested.connect(self.scan_ctl.cancel)
        self.scan_page.status_message.connect(self._set_status)
        self.scan_ctl.progress.connect(self.scan_page.on_progress)
        self.scan_ctl.result_ready.connect(self.scan_page.on_result)
        self.scan_ctl.finished.connect(self._on_scan_finished)

        self.diagnostic_page.campaign_requested.connect(self._start_campaign)
        self.diagnostic_page.stress_requested.connect(self._start_stress)
        self.diagnostic_page.cancel_requested.connect(self._cancel_diagnostic)
        self.diagnostic_page.status_message.connect(self._set_status)
        self.campaign_ctl.progress.connect(self.diagnostic_page.on_progress)
        self.campaign_ctl.finished.connect(self._on_campaign_finished)
        self.stress_ctl.phase_started.connect(self.diagnostic_page.on_stress_phase)
        self.stress_ctl.finished.connect(self._on_stress_finished)

        self.slave_page.start_requested.connect(self._start_slave)
        self.slave_page.link_changed.connect(self._update_availability)
        self.slave_page.stop_requested.connect(self._stop_slave)
        self.slave_page.status_message.connect(self._set_status)

        self.tabs.currentChanged.connect(lambda _i: self._update_availability())

        self.connection_bar.set_protocol(self._protocol)
        self.connection_bar.show_settings(self._settings)
        self.diagnostic_page.set_settings(self._settings)
        self._apply_saved_theme()
        self._update_availability()

    @property
    def _settings(self) -> LinkSettings:
        return self._tcp_settings if self._protocol == "TCP" else self._serial_settings

    @property
    def _is_tcp(self) -> bool:
        return self._protocol == "TCP"

    def _on_protocol_changed(self, name: str) -> None:
        if name not in ("RTU", "TCP") or name == self._protocol:
            return
        self._protocol = name
        self.connection_bar.show_settings(self._settings)
        self.diagnostic_page.set_settings(self._settings)
        self._save_settings()
        self._update_availability()

    def _on_language_changed(self, lang: str) -> None:
        if lang == current_language():
            return
        if self._occupancies() or self._busy_tab() is not None:
            self.connection_bar.set_language(current_language())
            self._set_status(tr("Déconnectez-vous et arrêtez les activités avant de changer de langue."))
            return
        set_language(lang)
        QSettings().setValue("ui/language", lang)
        self.relaunch_requested.emit()

    def _show_about(self) -> None:
        AboutDialog(dark=(self._theme == "sombre"), parent=self).exec()

    def show_about_on_first_run(self) -> None:
        """Premier démarrage, et premier démarrage de chaque nouvelle version :
        la pop-up présente l'outil et son historique. Appelée par ``app.run``."""
        qs = QSettings()
        if str(qs.value("ui/about_seen_version", "")) == __version__:
            return
        qs.setValue("ui/about_seen_version", __version__)
        self._show_about()

    # ================================================================ thème
    def _apply_saved_theme(self) -> None:
        app = QApplication.instance()
        saved = str(QSettings().value("ui/theme", "")) or system_theme(app)
        self._theme = apply_theme(app, saved)
        self.connection_bar.set_theme(self._theme)
        self._repaint_state_colors()

    def _repaint_state_colors(self) -> None:
        """Les couleurs posées en code (icônes, voyants, tuiles) ne suivent pas la
        feuille de style : on les repeint après un changement de thème."""
        refresh_icons()
        self.slave_page.repaint_state_colors()
        self.diagnostic_page.refresh()

    def _toggle_theme(self) -> None:
        app = QApplication.instance()
        nxt = THEMES[(THEMES.index(self._theme) + 1) % len(THEMES)]
        self._theme = apply_theme(app, nxt)
        self.connection_bar.set_theme(self._theme)
        self._repaint_state_colors()
        QSettings().setValue("ui/theme", self._theme)

    # ============================================================== liaison
    def _configure(self) -> None:
        dlg = ConfigDialog(self._protocol, self._serial_settings, self._tcp_settings, self)
        if dlg.exec():
            self._serial_settings = dlg.serial_settings()
            self._tcp_settings = dlg.tcp_settings()
            self.connection_bar.show_settings(self._settings)
            self.diagnostic_page.set_settings(self._settings)
            self._save_settings()

    def _connect(self) -> None:
        if not self._target_defined():
            return
        allowed, reason = can_start(Role.MASTER, port_key(self._settings), self._occupancies())
        if not allowed:
            self._set_status(reason)
            return
        self._manual_disconnect = False
        self._set_status(tr("Ouverture de {p0}…").format(p0=self._settings.summary()))
        self._cmd_open.emit(self._settings)

    def _target_defined(self) -> bool:
        if self._is_tcp and not self._tcp_settings.host:
            QMessageBox.warning(self, APP_TITLE, tr("Renseignez l'hôte dans CONFIGURATION."))
            return False
        if not self._is_tcp and not self._serial_settings.port:
            QMessageBox.warning(self, APP_TITLE, tr("Choisissez un port dans CONFIGURATION."))
            return False
        return True

    def _disconnect(self) -> None:
        self._manual_disconnect = True
        self._reconnect_pending = False
        self.scan_ctl.cancel()
        self.stress_ctl.cancel()
        self.campaign_ctl.cancel()
        self._cmd_close.emit()

    def _reopen_for_controller(self, settings: SerialSettings) -> None:
        self._cmd_open.emit(settings)

    def _on_connected(self, settings: SerialSettings) -> None:
        self._connected = True
        self._reconnect_pending = False
        self.connection_bar.set_connected(True)
        self.connection_bar.show_settings(settings)
        detail = f"timeout {settings.response_timeout_ms:g} ms"
        if isinstance(settings, SerialSettings):
            detail += f", silence fin de trame {settings.frame_gap_ms:.2f} ms"
        self._set_status(tr("Connecté : {p0} ({p1})").format(p0=settings.summary(), p1=detail))
        self.master_page.on_connected(settings.summary())
        self._update_availability()
        pending, self._pending_after_connect = self._pending_after_connect, None
        if pending is not None:
            QTimer.singleShot(0, pending)

    def _on_disconnected(self) -> None:
        self._connected = False
        self.connection_bar.set_connected(False)
        self.connection_bar.show_settings(self._settings)
        self._set_status(tr("Status : déconnecté"))
        self.master_page.on_disconnected(manual=self._manual_disconnect)
        self._update_availability()
        self._run_pending_after_disconnect()

    def _on_link_error(self, message: str) -> None:
        self._pending_after_connect = None
        self._connected = False
        self.connection_bar.set_connected(False)
        self._set_status(message)
        self.master_page.log_error(message)
        self._update_availability()
        if self._pending_after_disconnect is not None:
            self._run_pending_after_disconnect()
            return
        self._maybe_schedule_reconnect()

    def _on_link_lost(self) -> None:
        """Erreur transport pendant un échange maître : fermer et tenter la reconnexion."""
        self._connected = False
        self.connection_bar.set_connected(False)
        self._cmd_close.emit()
        self._maybe_schedule_reconnect()

    def _release_master_then(self, action) -> None:
        """Ferme la liaison maître, puis exécute ``action`` : un seul rôle tient le
        port et Windows ne le rend pas instantanément."""
        self._manual_disconnect = True
        self._reconnect_pending = False
        self._pending_after_disconnect = action
        self.scan_ctl.cancel()
        self.stress_ctl.cancel()
        self.campaign_ctl.cancel()
        self._set_status(tr("Fermeture de la liaison maître pour libérer le port…"))
        self._cmd_close.emit()

    def _run_pending_after_disconnect(self) -> None:
        pending, self._pending_after_disconnect = self._pending_after_disconnect, None
        if pending is not None:
            QTimer.singleShot(PORT_RELEASE_DELAY_MS, pending)

    def _maybe_schedule_reconnect(self) -> None:
        if not self.master_page.auto_reconnect or self._reconnect_pending or self._manual_disconnect:
            return
        self._reconnect_pending = True
        self._set_status(tr("Reconnexion automatique dans {p0:.1f} s…").format(p0=RECONNECT_DELAY_MS / 1000))
        QTimer.singleShot(RECONNECT_DELAY_MS, self._try_reconnect)

    def _try_reconnect(self) -> None:
        if not self._reconnect_pending:
            return
        self._reconnect_pending = False
        if not self._connected:
            self._cmd_open.emit(self._settings)

    # ============================================================== retours
    def _on_record(self, rec: ExchangeRecord, job: ExecuteJob) -> None:
        if job.tag == "maitre":
            self.session.add_record(rec, source="maitre")
            self.master_page.on_record(rec)
        elif rec.status is ExchangeStatus.TRANSPORT_ERROR:
            self._on_link_lost()

    def _on_request_failed(self, message: str, job: ExecuteJob) -> None:
        if job.tag == "maitre":
            self.master_page.on_request_failed(message)

    # ================================================================= scan
    def _start_scan(self, _plan) -> None:
        if not self._connected:
            self._set_status(tr("Le scan utilise la liaison du maître : cliquez d'abord sur CONNECTER."))
            return
        if self.campaign_ctl.active:
            self._set_status(tr("Un test de diagnostic est en cours."))
            return
        plan = self.scan_page.plan(self._settings)
        self.scan_page.on_started(plan)
        self.master_page.set_interactive(False)
        self.scan_ctl.start(plan)
        self._update_availability()

    def _on_scan_finished(self, ok: bool) -> None:
        self.scan_page.on_finished(ok)
        self.master_page.set_interactive(True)
        self.master_page.log_info(
            f"Scan réseau {'terminé' if ok else 'interrompu'} : {len(self.scan_ctl.results)} adresse(s) testée(s)"
        )
        self._update_availability()

    # ============================================================ campagnes
    def _ensure_master_link(self, then) -> bool:
        """Exécute ``then`` tout de suite si la liaison maître est ouverte, sinon
        l'ouvre d'abord (le diagnostic ne dépend pas de l'onglet Maître)."""
        if self._connected:
            return True
        allowed, reason = can_start(Role.MASTER, port_key(self._settings), self._occupancies())
        if not allowed:
            self._set_status(reason)
            return False
        if not self._target_defined():
            return False
        self._pending_after_connect = then
        self._manual_disconnect = False
        self._set_status(tr("Ouverture de {p0} pour le diagnostic…").format(p0=self._settings.summary()))
        self._cmd_open.emit(self._settings)
        return False

    def _start_campaign(self, spec: CampaignSpec) -> None:
        if self.scan_ctl.active or self.campaign_ctl.active or self.stress_ctl.active:
            self._set_status(tr("Un scan ou une campagne est déjà en cours."))
            return
        if not self._ensure_master_link(lambda: self._start_campaign(spec)):
            return
        self.diagnostic_page.on_campaign_started(spec)
        self.master_page.set_interactive(False)
        self.campaign_ctl.start(spec, self._settings)
        self._update_availability()

    def _start_stress(self, phases) -> None:
        if self.scan_ctl.active or self.campaign_ctl.active or self.stress_ctl.active:
            self._set_status(tr("Un scan ou une campagne est déjà en cours."))
            return
        if not self._ensure_master_link(lambda: self._start_stress(phases)):
            return
        self.diagnostic_page.on_stress_started(phases)
        self.master_page.set_interactive(False)
        self.stress_ctl.start(phases, self._settings)
        self._update_availability()

    def _cancel_diagnostic(self) -> None:
        if self.stress_ctl.active:
            self.stress_ctl.cancel()
        else:
            self.campaign_ctl.cancel()

    def _on_campaign_finished(self, stats) -> None:
        if self.stress_ctl.active:
            return  # le contrôleur de torture enchaîne les phases
        self.diagnostic_page.on_campaign_finished(stats)
        self.master_page.set_interactive(True)
        self._update_availability()

    def _on_stress_finished(self, report) -> None:
        self.diagnostic_page.on_stress_finished(report)
        self.master_page.set_interactive(True)
        self._update_availability()

    # =============================================================== espion
    def _start_sniffer(self) -> None:
        if self._is_tcp:
            self._set_status(tr("Le mode espion n'existe qu'en RTU : passez le protocole sur RTU."))
            return
        if not self._target_defined():
            return
        port = port_key(self._serial_settings)
        if self._connected and port == port_key(self._settings):
            # L'espion écoute le port du bandeau : on rend la liaison maître d'abord.
            self._release_master_then(self._start_sniffer)
            return
        allowed, reason = can_start(Role.SNIFFER, port, self._occupancies())
        if not allowed:
            self._set_status(reason)
            return
        self._sniffer = SnifferWorker(self._serial_settings, self)
        s = self._sniffer
        s.started_listening.connect(self.sniffer_page.on_started)
        s.link_error.connect(self._on_passive_error)
        s.frames_ready.connect(lambda frames: self.sniffer_page.on_frames(frames, s.decoder.counters))
        s.transactions_ready.connect(self._on_transactions)
        s.stopped.connect(self._on_sniffer_stopped)
        s.start()
        self._update_availability()

    def _stop_sniffer(self) -> None:
        if self._sniffer is not None:
            self._sniffer.stop()

    def _on_transactions(self, transactions) -> None:
        for transaction in transactions:
            self.session.add_transaction(transaction, self._settings)
        self.sniffer_page.on_transactions(transactions)

    def _on_sniffer_stopped(self) -> None:
        if self._sniffer is not None:
            self._sniffer.wait(2000)
            self._sniffer = None
        self.sniffer_page.on_stopped()
        self._set_status(tr("Écoute arrêtée."))
        self._update_availability()

    def _on_passive_error(self, message: str) -> None:
        self._set_status(message)
        self.sniffer_page.status_message.emit(message)

    # ============================================================== esclave
    def _start_slave(self, config: SlaveConfig, settings: LinkSettings) -> None:
        """Le serveur esclave a sa propre liaison : il peut tourner en même temps
        que le maître, à condition de ne pas viser le même port."""
        if isinstance(settings, SerialSettings) and not settings.port:
            QMessageBox.warning(self, APP_TITLE, tr("Choisissez le port du serveur esclave (bouton LIAISON)."))
            return
        allowed, reason = can_start(Role.SLAVE, port_key(settings, listen=True), self._occupancies())
        if not allowed:
            self._set_status(reason)
            self.slave_page.log_panel.console.log_error(reason)
            return
        if isinstance(settings, TcpSettings):
            # En serveur, l'hôte configuré est l'adresse d'écoute ; vide = toutes les interfaces
            self._slave = TcpSlaveWorker(TcpSettings(settings.host, settings.port), self.store, config, self)
        else:
            self._slave = SlaveWorker(settings, self.store, config, self)
        w = self._slave
        w.started_serving.connect(self.slave_page.on_started)
        w.link_error.connect(self._on_slave_error)
        w.handled.connect(lambda result, client: self.slave_page.on_handled(result, w.handler.counters, client))
        if isinstance(w, TcpSlaveWorker):
            w.clients_changed.connect(self.slave_page.on_clients)
        w.store_changed.connect(self.slave_page.on_store_changed)
        w.stopped.connect(self._on_slave_stopped)
        w.start()
        self._update_availability()

    def _stop_slave(self) -> None:
        if self._slave is not None:
            self._slave.stop()

    def _on_slave_stopped(self) -> None:
        if self._slave is not None:
            self._slave.wait(2000)
            self._slave = None
        self.slave_page.on_stopped()
        self._set_status(tr("Serveur esclave arrêté."))
        self._update_availability()

    def _on_slave_error(self, message: str) -> None:
        self._set_status(message)
        self.slave_page.log_panel.console.log_error(message)

    # ========================================================== disponibilité
    def _busy_tab(self) -> Tab | None:
        if self.scan_ctl.active:
            return Tab.SCAN
        if self.campaign_ctl.active or self.stress_ctl.active:
            return Tab.DIAGNOSTIC
        return None

    def _occupancies(self) -> tuple[Occupancy, ...]:
        """Rôles actifs et ressource que chacun tient (port série ou point TCP)."""
        active: list[Occupancy] = []
        if self._connected:
            active.append(Occupancy(Role.MASTER, port_key(self._settings)))
        if self._sniffer is not None:
            active.append(Occupancy(Role.SNIFFER, port_key(self._serial_settings)))
        if self._slave is not None:
            active.append(Occupancy(Role.SLAVE, port_key(self._slave.settings, listen=True)))
        return tuple(active)

    def _update_availability(self) -> None:
        busy = self._busy_tab() is not None
        active = self._occupancies()
        master_ok = self._connected and not busy
        # Seule une activité longue verrouille des onglets ; les rôles, eux, se
        # partagent la fenêtre tant qu'ils ne visent pas le même port.
        states = tab_states(self._busy_tab())
        for tab, idx in self._tab_index.items():
            st = states[tab]
            self.tabs.setTabEnabled(idx, st.enabled)
            self.tabs.setTabToolTip(idx, st.reason)
        self.scan_page.set_tcp(self._is_tcp)
        sniffer_ok, sniffer_reason = can_start(Role.SNIFFER, port_key(self._serial_settings), active)
        if self._is_tcp:
            sniffer_ok, sniffer_reason = False, tr("Écoute passive disponible en RTU uniquement")
        elif self._connected and port_key(self._serial_settings) == port_key(self._settings):
            # Même port que le maître : autorisé, la liaison maître sera rendue
            sniffer_ok, sniffer_reason = not busy, tr("La liaison maître sera fermée pour libérer le port.")
        self.sniffer_page.set_available(sniffer_ok and self._sniffer is None, sniffer_reason)
        slave_ok, slave_reason = can_start(Role.SLAVE, port_key(self.slave_page.link_settings(), listen=True), active)
        self.slave_page.set_available(slave_ok, slave_reason)
        self.scan_page.set_available(master_ok)
        self.diagnostic_page.set_can_run_tests(
            not busy and (self._connected or can_start(Role.MASTER, port_key(self._settings), active)[0])
        )
        self.connection_bar.connect_btn.setEnabled(
            not self._connected and can_start(Role.MASTER, port_key(self._settings), active)[0]
        )
        self.connection_bar.config_btn.setEnabled(not self._connected)

    # ============================================================ utilitaires
    def _set_status(self, text: str) -> None:
        self.status_label.setText(text if text.startswith("Status") else f"Status : {text}")

    def _load_settings(self) -> tuple[SerialSettings, TcpSettings, str]:
        qs = QSettings()
        inter = qs.value("serial/inter_frame_delay_ms", None)
        serial = SerialSettings(
            port=str(qs.value("serial/port", "")),
            baudrate=int(qs.value("serial/baudrate", 19200)),
            bytesize=int(qs.value("serial/bytesize", 8)),
            parity=Parity(str(qs.value("serial/parity", "N"))),
            stopbits=float(qs.value("serial/stopbits", 1.0)),
            response_timeout_ms=float(qs.value("serial/timeout_ms", 1000.0)),
            inter_frame_delay_ms=float(inter) if inter not in (None, "", "None") else None,
            rts_toggle=str(qs.value("serial/rts", "false")).lower() == "true",
            dtr=str(qs.value("serial/dtr", "false")).lower() == "true",
        )
        tcp = TcpSettings(
            host=str(qs.value("tcp/host", "")),
            port=int(qs.value("tcp/port", 502)),
            response_timeout_ms=float(qs.value("tcp/timeout_ms", 1000.0)),
            connect_timeout_ms=float(qs.value("tcp/connect_timeout_ms", 3000.0)),
        )
        protocol = str(qs.value("link/protocol", "RTU"))
        return serial, tcp, protocol if protocol in ("RTU", "TCP") else "RTU"

    def _save_settings(self) -> None:
        s = self._serial_settings
        t = self._tcp_settings
        qs = QSettings()
        qs.setValue("link/protocol", self._protocol)
        qs.setValue("serial/port", s.port)
        qs.setValue("serial/baudrate", s.baudrate)
        qs.setValue("serial/bytesize", s.bytesize)
        qs.setValue("serial/parity", str(s.parity.value))
        qs.setValue("serial/stopbits", s.stopbits)
        qs.setValue("serial/timeout_ms", s.response_timeout_ms)
        qs.setValue("serial/inter_frame_delay_ms", "" if s.inter_frame_delay_ms is None else s.inter_frame_delay_ms)
        qs.setValue("serial/rts", "true" if s.rts_toggle else "false")
        qs.setValue("serial/dtr", "true" if s.dtr else "false")
        qs.setValue("tcp/host", t.host)
        qs.setValue("tcp/port", t.port)
        qs.setValue("tcp/timeout_ms", t.response_timeout_ms)
        qs.setValue("tcp/connect_timeout_ms", t.connect_timeout_ms)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.scan_ctl.cancel()
        self.stress_ctl.cancel()
        self.campaign_ctl.cancel()
        for t in (self._sniffer, self._slave):
            if t is not None:
                t.stop()
                t.wait(2000)
        self._cmd_close.emit()
        self._thread.quit()
        if not self._thread.wait(3000):
            self._thread.terminate()
        QApplication.processEvents()
        super().closeEvent(event)
