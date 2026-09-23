"""Lancement du serveur MCP : ``python -m modbusai.mcp`` ou ``ModbusAI.exe --mcp``.

Deux transports pour deux usages :

* sans option, le serveur parle par l'entrée standard. C'est le mode local :
  Claude Code le lance lui-même sur le poste branché au bus, rien à ouvrir ;
* avec ``--http``, il écoute sur une adresse. C'est le mode à distance, prévu
  pour un réseau privé de type Tailscale : le poste reste sur site, on
  diagnostique depuis le bureau.

Lecture seule par défaut : écrire dans un automate en exploitation se décide au
lancement, pas au fil de la conversation.
"""

from __future__ import annotations

import argparse
import sys

from modbusai import APP_NAME, __version__
from modbusai.i18n import set_language
from modbusai.mcp import http as http_transport
from modbusai.mcp import stdio as stdio_transport
from modbusai.mcp.protocol import Dispatcher
from modbusai.mcp.service import ModbusService
from modbusai.mcp.tools import INSTRUCTIONS, build_tools

SERVER_NAME = "modbusai"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modbusai-mcp",
        description=f"{APP_NAME} : serveur MCP de diagnostic Modbus RTU / RS-485 et TCP.",
    )
    parser.add_argument(
        "--ecriture",
        action="store_true",
        help="autorise l'écriture sur le bus et le serveur esclave simulé (interdits par défaut)",
    )
    parser.add_argument(
        "--http",
        metavar="ADRESSE[:PORT]",
        help="écoute en HTTP au lieu de l'entrée standard. 127.0.0.1:8765 pour un essai local, "
        "l'adresse Tailscale de la machine pour un accès distant. Port par défaut : 8765",
    )
    parser.add_argument("--chemin", default=http_transport.DEFAULT_PATH, help="chemin du point d'entrée HTTP")
    parser.add_argument("--jeton", default="", help="jeton partagé exigé dans l'en-tête Authorization: Bearer")
    parser.add_argument("--langue", choices=("fr", "en"), default="fr", help="langue des libellés renvoyés")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser


def build_dispatcher(service: ModbusService) -> Dispatcher:
    dispatcher = Dispatcher(name=SERVER_NAME, version=__version__, instructions=INSTRUCTIONS)
    dispatcher.extend(build_tools(service))
    return dispatcher


def split_address(value: str, default_port: int = 8765) -> tuple[str, int]:
    """``100.87.1.4:8765``, ``100.87.1.4`` ou ``:8765`` -> (hôte, port)."""
    host, _, port = value.rpartition(":")
    if not _:  # pas de deux-points : tout est l'hôte
        return value or "127.0.0.1", default_port
    try:
        return host or "127.0.0.1", int(port)
    except ValueError as exc:
        raise SystemExit(f"Adresse d'écoute illisible : {value}") from exc


def force_utf8_streams() -> None:
    """Les tubes de Windows suivent la page de code du poste (cp1252), pas UTF-8 :
    les accents partaient illisibles, ceux du client arrivaient déformés, et le
    premier caractère hors cp1252 (le « Ω » d'une hypothèse) faisait tomber le
    serveur. MCP parle UTF-8 : on l'impose, avec des fins de ligne « \\n »."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # absent si un appelant a remplacé le flux
            reconfigure(encoding="utf-8", errors="replace", newline="\n")


def main(argv: list[str] | None = None) -> int:
    force_utf8_streams()
    args = build_parser().parse_args(argv)
    set_language(args.langue)
    service = ModbusService(allow_write=args.ecriture)
    dispatcher = build_dispatcher(service)
    mode = "écriture autorisée" if args.ecriture else "lecture seule"
    try:
        if not args.http:
            print(f"{APP_NAME} {__version__} : serveur MCP sur l'entrée standard, {mode}.", file=sys.stderr)
            return stdio_transport.serve(dispatcher)
        host, port = split_address(args.http)
        if args.jeton == "" and host not in ("127.0.0.1", "localhost", "::1"):
            print(
                "Attention : écoute sur une adresse non locale sans jeton. "
                "Le réseau doit être privé (Tailscale, VPN) ; --jeton ajoute une barrière.",
                file=sys.stderr,
            )
        httpd = http_transport.serve(dispatcher, host, port, args.chemin, args.jeton)
        bound = httpd.server_address
        print(
            f"{APP_NAME} {__version__} : serveur MCP sur http://{bound[0]}:{bound[1]}{args.chemin}, {mode}.",
            file=sys.stderr,
        )
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        service.shutdown()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
