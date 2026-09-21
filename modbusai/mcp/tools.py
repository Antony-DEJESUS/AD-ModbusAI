"""Catalogue des outils exposés au modèle : ce qu'ils font, ce qu'ils attendent.

Les identifiants (noms d'outils, noms d'arguments, valeurs d'énumération) sont
en anglais comme le reste du code ; les descriptions et les réponses sont en
français, langue de l'outil et de son rapport.

Un outil ne décide de rien : il compose une ``Request``, la confie au service,
et rend le résultat en texte. Les verdicts viennent de ``analysis``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from modbusai import APP_TITLE
from modbusai.analysis.campaign import CampaignSpec
from modbusai.analysis.diagnostic import CATALOGUE, SCORE_EXPLANATION, CampaignComparison, HypothesisInfo
from modbusai.analysis.observations import DEFAULT_SOURCES, SOURCE_TEST
from modbusai.analysis.report import build_report
from modbusai.analysis.scanner import ScanPlan
from modbusai.analysis.stress import default_scenario
from modbusai.mcp import render
from modbusai.mcp.protocol import Tool, ToolError, obj
from modbusai.mcp.service import MAX_SNIFF_S, Job, ModbusService
from modbusai.modbus.records import FunctionCode, Request
from modbusai.modbus.slave import TABLE_SIZE, SlaveConfig, Table
from modbusai.transport.ports import list_serial_ports
from modbusai.transport.records import LinkSettings, Parity, SerialSettings, TcpSettings

READ_FUNCTIONS = {
    "coil": FunctionCode.READ_COILS,
    "discrete_input": FunctionCode.READ_DISCRETE_INPUTS,
    "holding": FunctionCode.READ_HOLDING_REGISTERS,
    "input": FunctionCode.READ_INPUT_REGISTERS,
}
TABLES = {
    "coil": Table.COILS,
    "discrete_input": Table.DISCRETE_INPUTS,
    "holding": Table.HOLDING_REGISTERS,
    "input": Table.INPUT_REGISTERS,
}
FORMATS = ("registres", "entier32", "flottant32", "entier64", "flottant64")
MAX_SET_VALUES = 1000  # au-delà, c'est un remplissage : passer par l'application
ORDERS = ("ABCD", "CDAB", "BADC", "DCBA")

INSTRUCTIONS = f"""{APP_TITLE} : diagnostic Modbus RTU / RS-485 et Modbus TCP sur le bus réel.

Ordre de travail habituel : « connect » ouvre la liaison, puis « read », « scan »
ou « sniff » observent, puis « analyse » classe les hypothèses et « report »
produit le rapport complet.

Adresses : toujours en base 0, celle qui circule sur le bus. Une documentation
qui dit « 400001 » parle en base 1 : saisissez 0. L'outil rappelle les deux.

Un port ne sert qu'à un rôle à la fois. Un travail long (scan, campagne,
torture, écoute) tourne en fond : l'outil rend la main tout de suite et
« job_status » donne l'avancement. Pendant ce temps les autres outils du bus
sont refusés, avec le motif.

Les phases qui dégradent volontairement la liaison sont marquées « défauts
provoqués » : leurs échanges sont exclus des statistiques et des hypothèses,
sinon le test fabriquerait le défaut qu'il diagnostique.

{SCORE_EXPLANATION}"""


# ------------------------------------------------------------------ lecture des arguments
def _int(args: dict[str, Any], name: str, default: int | None = None, low: int | None = None, high: int | None = None) -> int:
    raw = args.get(name, default)
    if raw is None:
        raise ToolError(f"Argument « {name} » attendu.")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"Argument « {name} » : entier attendu, reçu {raw!r}.") from exc
    if low is not None and value < low:
        raise ToolError(f"Argument « {name} » : minimum {low}, reçu {value}.")
    if high is not None and value > high:
        raise ToolError(f"Argument « {name} » : maximum {high}, reçu {value}.")
    return value


def _float(args: dict[str, Any], name: str, default: float | None = None) -> float | None:
    raw = args.get(name, default)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"Argument « {name} » : nombre attendu, reçu {raw!r}.") from exc


def _bool(args: dict[str, Any], name: str, default: bool = False) -> bool:
    raw = args.get(name, default)
    return bool(raw)


def _choice(args: dict[str, Any], name: str, allowed: tuple[str, ...], default: str) -> str:
    raw = str(args.get(name, default))
    if raw not in allowed:
        raise ToolError(f"Argument « {name} » : attendu parmi {', '.join(allowed)}, reçu {raw!r}.")
    return raw


def _values(args: dict[str, Any], name: str = "values") -> tuple[int, ...]:
    raw = args.get(name)
    if raw is None:
        raise ToolError(f"Argument « {name} » attendu : liste d'entiers.")
    if isinstance(raw, int):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ToolError(f"Argument « {name} » : liste d'entiers non vide attendue.")
    try:
        return tuple(int(v) for v in raw)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"Argument « {name} » : entiers attendus, reçu {raw!r}.") from exc


def link_settings(args: dict[str, Any]) -> LinkSettings:
    """Paramètres de liaison depuis les arguments, série ou réseau."""
    transport = _choice(args, "transport", ("rtu", "tcp"), "rtu")
    if transport == "tcp":
        host = str(args.get("host", "")).strip()
        if not host:
            raise ToolError("Argument « host » attendu : adresse IP ou nom de la passerelle.")
        return TcpSettings(
            host=host,
            port=_int(args, "tcp_port", 502, 1, 65535),
            response_timeout_ms=_float(args, "timeout_ms", 1000.0) or 1000.0,
            connect_timeout_ms=_float(args, "connect_timeout_ms", 3000.0) or 3000.0,
        )
    port = str(args.get("port", "")).strip()
    if not port:
        raise ToolError("Argument « port » attendu : nom du port série (COM3, /dev/ttyUSB0).")
    return SerialSettings(
        port=port,
        baudrate=_int(args, "baudrate", 19200, 300, 1_000_000),
        bytesize=_int(args, "bytesize", 8, 7, 8),
        parity=Parity(_choice(args, "parity", ("N", "E", "O"), "N")),
        stopbits=_float(args, "stopbits", 1.0) or 1.0,
        response_timeout_ms=_float(args, "timeout_ms", 1000.0) or 1000.0,
        inter_frame_delay_ms=_float(args, "frame_gap_ms", None),
        rts_toggle=_bool(args, "rts_toggle"),
        dtr=_bool(args, "dtr"),
    )


LINK_PROPERTIES: dict[str, Any] = {
    "transport": {"type": "string", "enum": ["rtu", "tcp"], "default": "rtu", "description": "rtu = port série RS-485 ou RS-232 ; tcp = passerelle ou automate par le réseau."},
    "port": {"type": "string", "description": "Port série : COM3 sous Windows, /dev/ttyUSB0 sous Linux. Requis en rtu."},
    "baudrate": {"type": "integer", "default": 19200, "description": "Vitesse du bus. Tous les équipements d'un même bus ont la même."},
    "bytesize": {"type": "integer", "enum": [7, 8], "default": 8},
    "parity": {"type": "string", "enum": ["N", "E", "O"], "default": "N", "description": "N aucune, E paire, O impaire. Doit correspondre à l'esclave."},
    "stopbits": {"type": "number", "enum": [1, 1.5, 2], "default": 1},
    "timeout_ms": {"type": "number", "default": 1000, "description": "Attente d'une réponse avant de déclarer un timeout."},
    "frame_gap_ms": {"type": "number", "description": "Silence de fin de trame. Vide = T3.5 normatif avec plancher de 5 ms pour la latence USB. Montez à 10-20 ms si le journal montre des réponses coupées en deux."},
    "rts_toggle": {"type": "boolean", "default": False, "description": "Pilotage RTS pendant l'émission, pour un adaptateur RS-485 sans direction automatique."},
    "dtr": {"type": "boolean", "default": False},
    "host": {"type": "string", "description": "Adresse IP ou nom de la passerelle. Requis en tcp."},
    "tcp_port": {"type": "integer", "default": 502},
    "connect_timeout_ms": {"type": "number", "default": 3000},
}


def _request(args: dict[str, Any], default_count: int = 1) -> Request:
    kind = _choice(args, "type", tuple(READ_FUNCTIONS), "holding")
    limit = 2000 if kind in ("coil", "discrete_input") else 125
    return Request(
        slave_id=_int(args, "slave", None, 0, 247),
        function=READ_FUNCTIONS[kind],
        address=_int(args, "address", 0, 0, 65535),
        count=_int(args, "count", default_count, 1, limit),
    )


REQUEST_PROPERTIES: dict[str, Any] = {
    "slave": {"type": "integer", "minimum": 0, "maximum": 247, "description": "Adresse Modbus de l'équipement, 1 à 247. 0 = diffusion (écriture sans réponse)."},
    "type": {"type": "string", "enum": list(READ_FUNCTIONS), "default": "holding", "description": "coil = bobine FC01, discrete_input = entrée TOR FC02, holding = registre de maintien FC03, input = registre d'entrée FC04."},
    "address": {"type": "integer", "default": 0, "description": "Adresse du premier élément, EN BASE 0. Le registre documenté 400001 est l'adresse 0."},
    "count": {"type": "integer", "default": 1, "description": "Nombre d'éléments lus : 125 registres ou 2000 bits au maximum par requête."},
}


def _wait(args: dict[str, Any], default: float) -> float:
    value = _float(args, "wait_s", default) or 0.0
    return max(0.0, min(value, 120.0))


# ------------------------------------------------------------------ catalogue
def build_tools(service: ModbusService) -> list[Tool]:
    """Tous les outils disponibles. Ceux qui touchent au bus ou aux tables ne
    sont proposés que si le serveur a été lancé avec l'écriture autorisée :
    un outil absent vaut mieux qu'un outil qui refuse."""
    tools = [
        _list_ports(),
        _connect(service),
        _disconnect(service),
        _status(service),
        _read(service),
        _identify(service),
        _scan(service),
        _sniff(service),
        _campaign(service),
        _stress(service),
        _run_test(service),
        _job_status(service),
        _job_stop(service),
        _analyse(service),
        _report(service),
        _clear(service),
        _catalogue(),
        _slave_table(service),
    ]
    if service.allow_write:
        tools += [_write(service), _slave_start(service), _slave_stop(service), _slave_set(service)]
    return tools


def _tool(name: str, description: str, schema: dict[str, Any], handler: Callable[[dict[str, Any]], str], writes: bool = False) -> Tool:
    return Tool(name=name, description=description, schema=schema, handler=handler, writes=writes)


# ---------------------------------------------------------------- liaison
def _list_ports() -> Tool:
    def run(_: dict[str, Any]) -> str:
        ports = list_serial_ports()
        if not ports:
            return (
                "Aucun port série détecté. Vérifiez que l'adaptateur USB/RS-485 est branché et que "
                "son pilote est installé (CH340, CP2102, FTDI sont reconnus d'office par Windows 10 et 11)."
            )
        lines = [f"{len(ports)} port(s) série :", f"{'Port':<14} Description / identifiant matériel"]
        lines += [f"{p.device:<14} {p.description} {p.hwid}".rstrip() for p in ports]
        return "\n".join(lines)

    return _tool("list_ports", "Ports série présents sur la machine qui exécute ce serveur.", obj({}), run)


def _connect(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        settings = service.connect(link_settings(args))
        return f"Connecté.\n{render.link_line(settings)}"

    return _tool(
        "connect",
        "Ouvre la liaison du maître, en série (Modbus RTU) ou par le réseau (Modbus TCP). "
        "À appeler avant toute lecture. Une liaison déjà ouverte est refermée d'abord.",
        obj(LINK_PROPERTIES),
        run,
    )


def _disconnect(service: ModbusService) -> Tool:
    def run(_: dict[str, Any]) -> str:
        return "Liaison fermée." if service.disconnect() else "La liaison était déjà fermée."

    return _tool("disconnect", "Ferme la liaison du maître et libère le port.", obj({}), run)


def _status(service: ModbusService) -> Tool:
    def run(_: dict[str, Any]) -> str:
        lines = [render.link_line(service.settings if service.connected else None)]
        job = service.job
        if job is not None:
            state = "en cours" if job.running else ("interrompu" if job.cancelled else "terminé")
            lines.append(f"Travail « {job.label} » : {state}, {job.done} pas en {job.elapsed_s:.0f} s.")
        slave = service.slave
        if slave is not None and slave.running:
            lines.append(f"Serveur esclave : {_listen_line(slave)}")
        lines.append(f"Observations en mémoire : {len(service.session)}.")
        lines.append("Écriture autorisée." if service.allow_write else "Lecture seule (relancer avec --ecriture pour écrire).")
        return "\n".join(lines)

    return _tool("status", "État du serveur : liaison, travail en cours, serveur esclave, observations.", obj({}), run)


# ---------------------------------------------------------------- échanges
def _read(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        record = service.execute(_request(args), _float(args, "timeout_ms", None))
        return render.record_block(
            record,
            mode=_choice(args, "format", FORMATS, "registres"),
            order=_choice(args, "order", ORDERS, "ABCD"),
        )

    schema = obj(
        {
            **REQUEST_PROPERTIES,
            "format": {"type": "string", "enum": list(FORMATS), "default": "registres", "description": "Interprétation des registres. Un format multi-registres affiche les quatre ordres de mots : celui qui donne une valeur plausible est celui de l'équipement."},
            "order": {"type": "string", "enum": list(ORDERS), "default": "ABCD", "description": "Ordre supposé, simplement signalé dans la réponse. ABCD est l'ordre normal, CDAB l'inversion de mots la plus fréquente."},
            "timeout_ms": {"type": "number", "description": "Remplace le timeout de la liaison pour cette requête."},
        },
        required=("slave",),
    )
    return _tool(
        "read",
        "Lit des registres ou des bits sur l'équipement et rend la valeur, la trame émise et la trame reçue. "
        "Adresse en base 0. Un timeout n'est pas une erreur de l'esclave : c'est une absence de réponse, quelle qu'en soit la cause.",
        schema,
        run,
    )


def _write(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        service.require_write("L'écriture sur le bus")
        kind = _choice(args, "type", ("coil", "holding"), "holding")
        values = _values(args)
        if kind == "coil":
            function = FunctionCode.WRITE_SINGLE_COIL if len(values) == 1 else FunctionCode.WRITE_MULTIPLE_COILS
            values = tuple(1 if v else 0 for v in values)
        else:
            function = FunctionCode.WRITE_SINGLE_REGISTER if len(values) == 1 else FunctionCode.WRITE_MULTIPLE_REGISTERS
        request = Request(
            slave_id=_int(args, "slave", None, 0, 247),
            function=function,
            address=_int(args, "address", 0, 0, 65535),
            count=len(values),
            values=values,
        )
        record = service.execute(request, _float(args, "timeout_ms", None))
        return render.record_block(record)

    schema = obj(
        {
            "slave": REQUEST_PROPERTIES["slave"],
            "type": {"type": "string", "enum": ["coil", "holding"], "default": "holding", "description": "Seuls les bobines et les registres de maintien s'écrivent ; les entrées sont en lecture seule côté protocole."},
            "address": REQUEST_PROPERTIES["address"],
            "values": {"type": "array", "items": {"type": "integer"}, "description": "Valeurs à écrire. Une seule valeur utilise FC05 ou FC06, plusieurs utilisent FC15 ou FC16."},
            "timeout_ms": {"type": "number"},
        },
        required=("slave", "values"),
    )
    return _tool(
        "write",
        "Écrit sur l'équipement. ATTENTION : agit sur un automate réel, souvent en exploitation. "
        "Vérifiez l'adresse et la valeur avant, et relisez après.",
        schema,
        run,
        writes=True,
    )


def _identify(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        slave = _int(args, "slave", None, 1, 247)
        identity, report_id = service.identify(slave, _float(args, "timeout_ms", 500.0))
        if identity is None and not report_id:
            return (
                f"Esclave {slave} : ni FC43 ni FC17 n'ont répondu. C'est le cas le plus fréquent, "
                "beaucoup d'équipements n'implémentent aucune des deux : cela ne dit rien de leur santé."
            )
        lines = [f"Esclave {slave} :"]
        if identity is not None:
            lines.append(f"  FC43 : {identity.summary()}")
        if report_id:
            lines.append(f"  FC17 : {report_id}")
        return "\n".join(lines)

    return _tool(
        "identify",
        "Demande l'identification de l'équipement : FC43 (fabricant, produit, version) puis FC17 (identifiant et état).",
        obj({"slave": REQUEST_PROPERTIES["slave"], "timeout_ms": {"type": "number", "default": 500}}, ("slave",)),
        run,
    )


# ------------------------------------------------------------------ travaux
def _finish(job: Job, wait_s: float, running_hint: str) -> str:
    """Attend la fin du travail ; rend le résultat, sinon dit où en est."""
    if job.wait(wait_s):
        if job.error:
            raise ToolError(f"Travail « {job.label} » interrompu : {job.error}")
        prefix = "Travail interrompu avant la fin, résultat partiel :\n\n" if job.cancelled else ""
        suffix = f"\n\nAvertissement : {job.note}" if job.note else ""
        return prefix + job.text + suffix
    progress = job.progress()
    expected = f" sur {progress.expected} prévus" if progress.expected else ""
    phase = f" ({progress.phase})" if progress.phase else ""
    return (
        f"« {job.label} » tourne en fond{phase} : {progress.done} pas{expected} en {progress.elapsed_s:.0f} s.\n"
        f"{running_hint}\n"
        "Rappelez « job_status » pour l'avancement et le résultat, « job_stop » pour interrompre."
    )


def _scan(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        settings = service.settings
        if settings is None:
            raise ToolError("Liaison fermée : appelez d'abord l'outil « connect ».")
        first = _int(args, "first", 1, 0, 247)
        last = _int(args, "last", 32, 0, 247)
        if last < first:
            raise ToolError("« last » doit être supérieur ou égal à « first ».")
        kind = _choice(args, "type", tuple(READ_FUNCTIONS), "holding")
        plan = ScanPlan(
            first_slave=first,
            last_slave=last,
            function=READ_FUNCTIONS[kind],
            address=_int(args, "address", 0, 0, 65535),
            count=_int(args, "count", 1, 1, 125),
            timeout_ms=_float(args, "timeout_ms", 200.0) or 200.0,
            retries=_int(args, "retries", 1, 0, 5),
            identify=_bool(args, "identify", True),
            sweep_settings=_bool(args, "sweep"),
            base_settings=settings,
        )
        job = Job("scan", f"Scan {first}-{last}", expected=plan.total_probes)

        def work(current: Job) -> str:
            results, skipped = service.run_scan(plan, current)
            shown = results if _bool(args, "show_absent") else [r for r in results if r.present]
            text = render.scan_block(shown, current.done)
            if skipped:
                text += "\n\nRéglages que l'adaptateur a refusés, non testés :\n" + "\n".join(
                    f"  {line}" for line in skipped
                )
            return text

        service.start_job(job, work)
        estimate = plan.total_probes * plan.timeout_ms / 1000
        return _finish(job, _wait(args, 20.0), f"Durée maximale estimée : {estimate:.0f} s.")

    schema = obj(
        {
            "first": {"type": "integer", "default": 1, "description": "Première adresse testée."},
            "last": {"type": "integer", "default": 32, "description": "Dernière adresse testée. 247 balaie tout le bus, mais coûte adresses x essais x timeout."},
            "type": REQUEST_PROPERTIES["type"],
            "address": REQUEST_PROPERTIES["address"],
            "count": {"type": "integer", "default": 1},
            "timeout_ms": {"type": "number", "default": 200, "description": "150 à 300 ms suffisent sur un bus sain ; montez si les esclaves sont lents."},
            "retries": {"type": "integer", "default": 1, "description": "Essais supplémentaires avant de déclarer une adresse absente."},
            "identify": {"type": "boolean", "default": True, "description": "Demander FC43 puis FC17 sur chaque présent."},
            "sweep": {"type": "boolean", "default": False, "description": "Balayer aussi les vitesses et parités usuelles. Long, mais c'est la méthode quand on ignore les réglages de l'équipement."},
            "show_absent": {"type": "boolean", "default": False, "description": "Lister aussi les adresses sans réponse."},
            "wait_s": {"type": "number", "default": 20, "description": "Attente maximale avant de rendre la main. Au-delà, le scan continue en fond."},
        }
    )
    return _tool(
        "scan",
        "Cherche les équipements présents sur le bus en interrogeant une plage d'adresses, et identifie ceux qui répondent. "
        "Une adresse absente n'est pas une panne : c'est souvent une adresse simplement inutilisée.",
        schema,
        run,
    )


def _sniff(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        seconds = _float(args, "seconds", 10.0) or 10.0
        if not 1.0 <= seconds <= MAX_SNIFF_S:
            raise ToolError(f"« seconds » : entre 1 et {MAX_SNIFF_S:.0f}.")
        asked = link_settings(args) if str(args.get("port", "")).strip() else None
        settings = service.sniff_settings(asked)
        job = Job("sniff", f"Écoute {seconds:.0f} s sur {settings.port}")

        def work(current: Job) -> str:
            return render.sniff_block(service.run_sniff(settings, seconds, current), seconds)

        service.start_job(job, work)
        hint = (
            "Un autre port que celui du maître : les deux cohabitent."
            if service.settings is None or settings.port != getattr(service.settings, "port", None)
            else "La liaison du maître est fermée pendant l'écoute, puis rouverte."
        )
        return _finish(job, _wait(args, seconds + 3.0), hint)

    schema = obj(
        {
            "seconds": {"type": "number", "default": 10, "description": f"Durée d'écoute, 1 à {MAX_SNIFF_S:.0f} s."},
            "port": {"type": "string", "description": "Port série à écouter. Vide = celui du maître, qui est alors fermé le temps de l'écoute puis rouvert. Un second adaptateur branché en parallèle sur le bus permet d'écouter sans interrompre le maître."},
            "baudrate": LINK_PROPERTIES["baudrate"],
            "parity": LINK_PROPERTIES["parity"],
            "stopbits": LINK_PROPERTIES["stopbits"],
            "bytesize": LINK_PROPERTIES["bytesize"],
            "frame_gap_ms": LINK_PROPERTIES["frame_gap_ms"],
            "timeout_ms": {"type": "number", "default": 1000, "description": "Au-delà de ce délai sans réponse, une requête entendue est déclarée sans réponse."},
            "wait_s": {"type": "number", "description": "Attente maximale avant de rendre la main ; par défaut la durée d'écoute."},
        }
    )
    return _tool(
        "sniff",
        "Écoute passive du bus RS-485 : regarde le trafic d'un autre maître sans jamais émettre. "
        "Dit qui interroge qui, à quel rythme, et qui ne répond pas. Vitesse et parité doivent être "
        "celles du bus écouté, sinon les trames sortent en « invalide ». Modbus RTU uniquement.",
        schema,
        run,
    )


def _campaign(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        request = _request(args)
        spec = CampaignSpec(
            request,
            period_ms=_int(args, "period_ms", 200, 0, 60_000),
            duration_s=_float(args, "duration_s", 120.0),
            max_count=_int(args, "max_count", 0) or None,
            timeout_ms=_float(args, "timeout_ms", None),
            label=str(args.get("label") or "Campagne"),
            source=SOURCE_TEST,
        )
        job = Job("campaign", spec.label, expected=spec.expected_count())

        def work(current: Job) -> str:
            stats = service.run_campaign(spec, current)
            return (
                f"{spec.describe()}\n\n{render.stats_block({stats.slave_id: stats})}\n\n"
                "Appelez « analyse » pour les hypothèses tirées de cette campagne."
            )

        service.start_job(job, work)
        return _finish(job, _wait(args, 10.0), f"Durée prévue : {spec.duration_s or 0:.0f} s.")

    schema = obj(
        {
            **REQUEST_PROPERTIES,
            "period_ms": {"type": "integer", "default": 200, "description": "Rythme des lectures."},
            "duration_s": {"type": "number", "default": 120, "description": "Durée de la campagne. Deux minutes est le minimum utile pour voir passer un défaut intermittent."},
            "max_count": {"type": "integer", "description": "Arrêt après ce nombre de lectures, si atteint avant la durée."},
            "timeout_ms": {"type": "number"},
            "label": {"type": "string", "default": "Campagne", "description": "Nom de la campagne, repris dans le rapport et la trace."},
            "wait_s": {"type": "number", "default": 10},
        },
        required=("slave",),
    )
    return _tool(
        "campaign",
        "Répète une lecture pendant une durée donnée et compte les défauts : c'est la façon de voir un défaut intermittent "
        "qu'une lecture isolée ne montre jamais. Les échanges nourrissent « analyse » et « report ».",
        schema,
        run,
    )


def _stress(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        settings = service.settings
        if settings is None:
            raise ToolError("Liaison fermée : appelez d'abord l'outil « connect ».")
        request = _request(args)
        seen = tuple(s for s in service.stats() if s != request.slave_id)
        duration = _float(args, "duration_s", 300.0) or 300.0
        phases = default_scenario(request, settings, duration, seen)
        job = Job("stress", "Test de torture", expected=len(phases))

        def work(current: Job) -> str:
            text = render.phases_block(service.run_stress(phases, current))
            if service.skipped_phases:
                text += "\n\nPhases non exécutées, réglages refusés par l'adaptateur :\n" + "\n".join(
                    f"  {line}" for line in service.skipped_phases
                )
            return text

        service.start_job(job, work)
        names = ", ".join(p.title for p in phases)
        return _finish(job, _wait(args, 10.0), f"{len(phases)} phases sur {duration:.0f} s : {names}.")

    schema = obj(
        {
            **REQUEST_PROPERTIES,
            "duration_s": {"type": "number", "default": 300, "description": "Durée totale, répartie à parts égales entre les phases."},
            "wait_s": {"type": "number", "default": 10},
        },
        required=("slave",),
    )
    return _tool(
        "stress_test",
        "Enchaîne des phases qui sollicitent le réseau de façons différentes (rafale, trames longues, timeout serré, "
        "vitesse réduite) et compare : un bus qui tient la rafale mais perd les trames longues n'a pas le même problème "
        "qu'un bus qui tient les trames longues mais s'effondre en rafale.",
        schema,
        run,
    )


def _run_test(service: ModbusService) -> Tool:
    """Exécute un test suggéré et le compare à la situation de référence.

    C'est la boucle du diagnostic : une hypothèse propose un test, le test
    modifie un paramètre, et c'est l'écart avec la référence qui tranche.
    """

    def run(args: dict[str, Any]) -> str:
        key = str(args.get("test") or "").strip()
        if not key:
            raise ToolError("Argument « test » attendu : la clé d'un test proposé par « analyse ».")
        hypothesis, test = service.find_test(key)
        request = _request(args)
        baseline = service.stats().get(request.slave_id)
        if baseline is None or baseline.total == 0:
            raise ToolError(
                f"Aucune observation sur l'esclave {request.slave_id} : un test se compare à une référence, "
                "lancez d'abord une campagne."
            )
        spec = test.to_campaign(request)
        duration = _float(args, "duration_s", None)
        count = _int(args, "max_count", 0) or None
        if duration is not None or count is not None:
            # Un test dure deux minutes par défaut ; on peut l'écourter quand
            # le défaut est franc, la comparaison reste valable.
            spec = replace(spec, duration_s=duration, max_count=count)
        job = Job("test", test.title, expected=spec.expected_count())

        def work(current: Job) -> str:
            result = service.run_campaign(spec, current)
            comparison = CampaignComparison(test, baseline, result)
            service.comparisons.append(comparison)
            return (
                f"Hypothèse visée : {hypothesis.title} (score {hypothesis.score})\n"
                f"Test « {test.key} » : {test.title}\n"
                f"{test.description}\n"
                f"Réglages : {spec.describe()}\n\n"
                f"Référence : {baseline.total} échanges, {100 * baseline.error_ratio:.1f} % de défauts\n"
                f"Résultat  : {result.total} échanges, {100 * result.error_ratio:.1f} % de défauts\n\n"
                f"Verdict : {comparison.verdict()}"
            )

        service.start_job(job, work)
        return _finish(job, _wait(args, 15.0), f"Durée prévue : {spec.duration_s or 0:.0f} s.")

    schema = obj(
        {
            "test": {"type": "string", "description": "Clé du test, telle que « analyse » l'a donnée : par exemple timeout_x2, slow_baud, period, parity_even, stop2, gap20."},
            **REQUEST_PROPERTIES,
            "duration_s": {"type": "number", "description": "Écourte le test, qui dure deux minutes par défaut. Utile quand le défaut est franc."},
            "max_count": {"type": "integer", "description": "Arrête le test après ce nombre de lectures."},
            "wait_s": {"type": "number", "default": 15},
        },
        required=("test", "slave"),
    )
    return _tool(
        "run_test",
        "Exécute un test proposé par « analyse » : une campagne aux réglages modifiés (timeout doublé, 9600 bauds, "
        "parité paire, période lente...), comparée à la situation de référence. Le verdict dit si les défauts ont "
        "disparu, diminué, empiré ou n'ont pas bougé : c'est ce qui départage deux hypothèses. "
        "Les tests qui demandent une action physique sur le bus sont refusés en expliquant quoi faire.",
        schema,
        run,
    )


def _job_status(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        job = service.job
        if job is None:
            return "Aucun travail lancé depuis le démarrage du serveur."
        return _finish(job, _wait(args, 0.0), "")

    return _tool(
        "job_status",
        "Avancement du travail en cours (scan, campagne, torture, écoute), ou son résultat s'il est terminé. "
        "« wait_s » permet d'attendre la fin plutôt que de repasser plusieurs fois.",
        obj({"wait_s": {"type": "number", "default": 0, "description": "Attente maximale, en secondes, avant de rendre la main."}}),
        run,
    )


def _job_stop(service: ModbusService) -> Tool:
    def run(_: dict[str, Any]) -> str:
        job = service.stop_job()
        if job is None:
            return "Aucun travail en cours."
        return f"Travail « {job.label} » interrompu après {job.done} pas.\n\n{job.text or '(pas de résultat partiel)'}"

    return _tool("job_stop", "Interrompt le travail en cours et rend le résultat partiel.", obj({}), run)


# ---------------------------------------------------------------- diagnostic
def _sources(args: dict[str, Any]) -> tuple[str, ...]:
    raw = args.get("sources")
    if not raw:
        return tuple(DEFAULT_SOURCES)
    if isinstance(raw, str):
        raw = [raw]
    return tuple(str(s) for s in raw)


SOURCES_PROPERTY = {
    "type": "array",
    "items": {"type": "string", "enum": ["maitre", "espion", "test", "scan", "torture"]},
    "description": "Origines retenues. Par défaut maitre + espion + test : le scan et les phases à défauts provoqués sont exclus, leurs défauts ne sont pas ceux du bus.",
}


def _analyse(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        sources = _sources(args)
        stats = service.stats(sources)
        hypotheses = service.hypotheses(sources)
        return (
            f"Sources retenues : {', '.join(sources)}\n\n"
            f"{render.stats_block(stats)}\n\n"
            f"{render.hypotheses_block(hypotheses, with_tests=_bool(args, 'with_tests', True))}"
        )

    return _tool(
        "analyse",
        "Statistiques par esclave et hypothèses classées par vraisemblance, avec les indices qui les déclenchent "
        "et les tests qui permettent de les départager. À appeler après avoir observé (lecture, scan, campagne, écoute).",
        obj({"sources": SOURCES_PROPERTY, "with_tests": {"type": "boolean", "default": True}}),
        run,
    )


def _report(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        sources = _sources(args)
        observations = service.session.observations(sources)
        if not observations:
            raise ToolError("Aucune observation : lancez au moins une lecture, un scan, une campagne ou une écoute.")
        return build_report(
            service.settings,
            service.stats(sources),
            service.hypotheses(sources),
            comparisons=service.comparisons,
            stress=service.stress_report,
            observations=observations,
            sources_label=", ".join(sources),
            include_trace=_bool(args, "include_trace", True),
        )

    return _tool(
        "report",
        "Rapport de diagnostic complet en texte : statistiques, hypothèses, phases du test de torture et trace de "
        "toutes les trames. C'est le même fichier que l'export de l'application, conçu pour se suffire à lui-même.",
        obj(
            {
                "sources": SOURCES_PROPERTY,
                "include_trace": {"type": "boolean", "default": True, "description": "Inclure la trace trame par trame. La désactiver donne un rapport court."},
            }
        ),
        run,
    )


def _clear(service: ModbusService) -> Tool:
    def run(_: dict[str, Any]) -> str:
        count = len(service.session)
        service.clear()
        return f"{count} observation(s) effacée(s). Les statistiques et les hypothèses repartent de zéro."

    return _tool("clear_history", "Efface les observations accumulées et le dernier test de torture.", obj({}), run)


def _catalogue() -> Tool:
    def run(args: dict[str, Any]) -> str:
        key = str(args.get("hypothesis") or "").strip()
        if key:
            info = CATALOGUE.get(key)
            if info is None:
                raise ToolError(f"Hypothèse inconnue : {key}. Clés : {', '.join(CATALOGUE)}.")
            return _fiche(key, info)
        return "\n\n".join(_fiche(k, v) for k, v in CATALOGUE.items())

    return _tool(
        "catalogue",
        "Fiches des hypothèses de diagnostic : ce qui déclenche chacune, ses causes physiques classiques et comment "
        "la confirmer. Utile pour interpréter un rapport sans l'application.",
        obj({"hypothesis": {"type": "string", "enum": list(CATALOGUE), "description": "Une seule fiche. Vide = toutes."}}),
        run,
    )


def _fiche(key: str, info: HypothesisInfo) -> str:
    lines = [f"[{key}] {info.title}", f"  {info.summary}", f"  Déclenchement : {info.trigger}", "  Causes classiques :"]
    lines += [f"    - {c}" for c in info.causes]
    lines.append("  Pour confirmer :")
    lines += [f"    - {c}" for c in info.how_to_confirm]
    return "\n".join(lines)


# ------------------------------------------------------------ serveur esclave
def _listen_line(slave: Any) -> str:
    settings = slave.bound
    if isinstance(settings, TcpSettings):
        clients = ", ".join(slave.clients) if slave.clients else "aucun"
        return f"{settings.summary()} — maîtres connectés : {clients}"
    return settings.summary()


def _slave_start(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        service.require_write("Le serveur esclave")
        ids = args.get("slaves") or [1]
        if isinstance(ids, int):
            ids = [ids]
        config = SlaveConfig(
            slave_ids={int(i) for i in ids},
            response_delay_ms=_float(args, "response_delay_ms", 0.0) or 0.0,
            drop_ratio=_float(args, "drop_ratio", 0.0) or 0.0,
            corrupt_ratio=_float(args, "corrupt_ratio", 0.0) or 0.0,
            read_only=_bool(args, "read_only"),
        )
        server = service.slave_start(link_settings(args), config)
        served = ", ".join(str(i) for i in sorted(config.slave_ids))
        return (
            f"Serveur esclave démarré sur {_listen_line(server)}.\n"
            f"Adresses servies : {served}. Les tables sont à zéro ; « slave_set » les remplit.\n"
            "Il tourne en parallèle du maître, à condition d'utiliser un autre port."
        )

    schema = obj(
        {
            **LINK_PROPERTIES,
            "slaves": {"type": "array", "items": {"type": "integer"}, "default": [1], "description": "Adresses servies. Une requête vers une autre adresse est ignorée, comme le ferait un vrai bus."},
            "read_only": {"type": "boolean", "default": False, "description": "Refuser les écritures avec l'exception 04 : vérifie qu'une supervision n'écrit pas là où elle ne devrait pas."},
            "response_delay_ms": {"type": "number", "default": 0, "description": "Attente avant chaque réponse : simule un esclave lent pour régler les timeouts d'une supervision."},
            "drop_ratio": {"type": "number", "default": 0, "description": "Part des requêtes volontairement laissées sans réponse, 0 à 1 : simule des timeouts."},
            "corrupt_ratio": {"type": "number", "default": 0, "description": "Part des réponses émises avec un CRC faux, 0 à 1 : simule du bruit."},
        }
    )
    return _tool(
        "slave_start",
        "Démarre un simulateur d'équipement Modbus sur sa propre liaison, avec injection de défauts. "
        "Sert à tester une supervision sans matériel, ou à reproduire un défaut observé sur site.",
        schema,
        run,
        writes=True,
    )


def _slave_stop(service: ModbusService) -> Tool:
    def run(_: dict[str, Any]) -> str:
        service.require_write("Le serveur esclave")
        return "Serveur esclave arrêté." if service.slave_stop() else "Aucun serveur esclave en marche."

    return _tool("slave_stop", "Arrête le simulateur d'équipement et libère son port.", obj({}), run, writes=True)


def _slave_set(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        service.require_write("La modification des tables du simulateur")
        table = TABLES[_choice(args, "table", tuple(TABLES), "holding")]
        address = _int(args, "address", 0, 0, 65535)
        values = _values(args)
        if len(values) > MAX_SET_VALUES:
            raise ToolError(f"Argument « values » : {MAX_SET_VALUES} valeurs au plus par appel.")
        if address + len(values) > TABLE_SIZE:
            raise ToolError(f"Adresse {address} + {len(values)} valeurs dépasse la table ({TABLE_SIZE} éléments).")
        if table.is_bits:
            values = tuple(1 if v else 0 for v in values)
        elif any(not 0 <= v <= 0xFFFF for v in values):
            raise ToolError("Argument « values » : registres 0..65535 attendus.")
        service.store.set(table, address, list(values))
        shown = ", ".join(str(v) for v in values[:12]) + (" ..." if len(values) > 12 else "")
        return f"{table.label} : {len(values)} valeur(s) écrite(s) à partir de l'adresse {address} (base 0) : {shown}"

    schema = obj(
        {
            "table": {"type": "string", "enum": list(TABLES), "default": "holding", "description": "Table du simulateur à remplir."},
            "address": REQUEST_PROPERTIES["address"],
            "values": {"type": "array", "items": {"type": "integer"}, "description": "Valeurs écrites à partir de l'adresse."},
        },
        required=("values",),
    )
    return _tool(
        "slave_set",
        "Remplit les tables du simulateur : donne des valeurs plausibles à lire à une supervision en test.",
        schema,
        run,
        writes=True,
    )


def _slave_table(service: ModbusService) -> Tool:
    def run(args: dict[str, Any]) -> str:
        table = TABLES[_choice(args, "table", tuple(TABLES), "holding")]
        address = _int(args, "address", 0, 0, 65535)
        count = _int(args, "count", 10, 1, 250)
        values = service.store.get(table, address, count)
        lines = [f"{table.label}, adresses {address} à {address + count - 1} (base 0) :"]
        lines += [f"  {address + i:>6} = {v}" for i, v in enumerate(values)]
        counters = service.slave.counters if service.slave is not None else None
        if counters is not None:
            lines.append(
                f"Compteurs du serveur : {counters.requests} requêtes, {counters.responses} réponses, "
                f"{counters.writes} écritures, {counters.exceptions} exceptions, {counters.dropped} perdues."
            )
        return "\n".join(lines)

    schema = obj(
        {
            "table": {"type": "string", "enum": list(TABLES), "default": "holding"},
            "address": REQUEST_PROPERTIES["address"],
            "count": {"type": "integer", "default": 10, "maximum": 250},
        }
    )
    return _tool(
        "slave_table",
        "Relit les tables du simulateur : vérifie ce qu'un maître extérieur vient d'y écrire.",
        schema,
        run,
    )
