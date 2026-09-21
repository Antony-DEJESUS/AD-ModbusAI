"""Protocole MCP : JSON-RPC 2.0 et poignée de main, sans transport ni Modbus.

Le Model Context Protocol fait dialoguer un client (Claude Code, Claude
Desktop) et un serveur par messages JSON-RPC 2.0. Ce module ne sait ni d'où
viennent les messages (entrée standard, HTTP) ni ce que font les outils : il
valide, aiguille et met en forme. La pile est écrite en propre, comme la pile
RTU : l'exécutable reste un seul fichier, sans dépendance supplémentaire.

Deux familles d'erreurs, à ne pas confondre :

* erreur de protocole (méthode inconnue, paramètres illisibles) -> objet
  ``error`` JSON-RPC : c'est le client qui s'est trompé ;
* erreur d'exécution d'un outil (port fermé, esclave muet) -> résultat
  ``isError`` : le modèle doit la lire et en tenir compte, pas la subir.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
"""Révisions comprises, de la plus récente à la plus ancienne."""

LATEST_VERSION = PROTOCOL_VERSIONS[0]

# Codes JSON-RPC 2.0 normalisés.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ToolError(Exception):
    """Échec d'exécution d'un outil : remonté au modèle, pas au transport."""


@dataclass(frozen=True, slots=True)
class Tool:
    """Un outil exposé au modèle : ce qu'il fait, ce qu'il attend, qui l'exécute."""

    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]
    title: str = ""
    writes: bool = False  # touche au bus ou aux tables : soumis à --ecriture

    def describe(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.schema,
        }
        if self.title:
            entry["title"] = self.title
        return entry


def obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    """Schéma JSON d'un objet d'arguments, forme attendue par ``inputSchema``."""
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


@dataclass(slots=True)
class Dispatcher:
    """Aiguillage des messages : poignée de main, catalogue, appels d'outils."""

    name: str
    version: str
    instructions: str = ""
    tools: dict[str, Tool] = field(default_factory=dict)
    negotiated_version: str = LATEST_VERSION
    initialized: bool = False

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def extend(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.add(tool)

    # ------------------------------------------------------------ aiguillage
    def handle(self, message: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Traite un message décodé. Renvoie la réponse, ou None pour une
        notification (qui n'en attend pas)."""
        if isinstance(message, list):  # lot : supprimé en 2025-06-18, toléré avant
            answers = [a for a in (self.handle(m) for m in message) if a is not None]
            return answers or None
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "Message JSON-RPC attendu")

        msg_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(msg_id, INVALID_REQUEST, "Champ « method » manquant")
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(msg_id, INVALID_PARAMS, "Champ « params » : objet attendu")

        is_notification = "id" not in message
        try:
            result = self._route(method, params)
        except ToolError as exc:  # pragma: no cover - les outils renvoient isError
            return None if is_notification else _error(msg_id, INTERNAL_ERROR, str(exc))
        except _Rejected as exc:
            return None if is_notification else _error(msg_id, exc.code, exc.message)
        except Exception as exc:  # garde-fou : le serveur ne meurt pas sur un outil
            return None if is_notification else _error(msg_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _route(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method in ("notifications/initialized", "notifications/cancelled"):
            self.initialized = self.initialized or method.endswith("initialized")
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.describe() for t in self.tools.values()]}
        if method == "tools/call":
            return self._call(params)
        if method in ("resources/list", "resources/templates/list"):
            return {"resources": [], "resourceTemplates": []}
        if method == "prompts/list":
            return {"prompts": []}
        raise _Rejected(METHOD_NOT_FOUND, f"Méthode inconnue : {method}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        self.negotiated_version = asked if asked in PROTOCOL_VERSIONS else LATEST_VERSION
        info: dict[str, Any] = {
            "protocolVersion": self.negotiated_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }
        if self.instructions:
            info["instructions"] = self.instructions
        return info

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise _Rejected(INVALID_PARAMS, "Champ « name » manquant")
        tool = self.tools.get(name)
        if tool is None:
            raise _Rejected(INVALID_PARAMS, f"Outil inconnu : {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise _Rejected(INVALID_PARAMS, "Champ « arguments » : objet attendu")
        try:
            text = tool.handler(arguments)
        except ToolError as exc:
            return _content(str(exc), is_error=True)
        except ValueError as exc:  # saisie hors bornes : la couche modbus lève ValueError
            return _content(f"Requête invalide : {exc}", is_error=True)
        except Exception as exc:
            return _content(f"Échec de l'outil {name} : {type(exc).__name__}: {exc}", is_error=True)
        return _content(text)


class _Rejected(Exception):
    """Refus de protocole : converti en objet ``error`` JSON-RPC."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _content(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def parse_error() -> dict[str, Any]:
    return _error(None, PARSE_ERROR, "JSON illisible")


def encode(message: Any) -> str:
    """Une ligne JSON sans espace superflu, telle que l'attend le transport."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))
