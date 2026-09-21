"""Transport « entrée standard » : le client lance le serveur et lui parle par
des tubes. C'est le mode local, celui de Claude Code sur le poste branché au bus.

Règle absolue : la sortie standard ne porte QUE des messages JSON-RPC, un par
ligne. Tout le reste — journal, avertissements, traces — part sur la sortie
d'erreur, sinon le client ne sait plus lire le flux.
"""

from __future__ import annotations

import json
import sys
from typing import TextIO

from modbusai.mcp.protocol import Dispatcher, encode, parse_error


def serve(dispatcher: Dispatcher, source: TextIO | None = None, sink: TextIO | None = None) -> int:
    """Boucle de lecture jusqu'à la fermeture du tube par le client."""
    source = source or sys.stdin
    sink = sink or sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(sink, parse_error())
            continue
        answer = dispatcher.handle(message)
        if answer is not None:
            _write(sink, answer)
    return 0


def _write(sink: TextIO, message: object) -> None:
    sink.write(encode(message) + "\n")
    sink.flush()
