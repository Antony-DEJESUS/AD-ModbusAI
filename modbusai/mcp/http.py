"""Transport HTTP (Streamable HTTP) : le serveur écoute, le client vient à lui.

C'est le mode à distance : le poste branché au bus reste sur site, on
diagnostique depuis le bureau. Le réseau qui porte cela doit être privé —
Tailscale, VPN, réseau d'atelier — jamais l'internet ouvert : ce serveur parle
à des automates.

Trois garde-fous, parce qu'un port ouvert sur un bus Modbus n'est pas anodin :

* l'écoute est liée à ``127.0.0.1`` par défaut ; exposer sur une autre adresse
  est un choix explicite (``--http 100.x.y.z:8765``) ;
* un jeton partagé peut être exigé (``--jeton``), vérifié dans l'en-tête
  ``Authorization: Bearer`` ;
* une requête portant un en-tête ``Origin`` étranger est refusée : c'est la
  parade au détournement DNS depuis un navigateur.
"""

from __future__ import annotations

import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from modbusai.mcp.protocol import Dispatcher, encode

DEFAULT_PATH = "/mcp"
MAX_BODY = 4 * 1024 * 1024  # un message MCP n'a aucune raison d'être plus gros
LOCAL_ORIGINS = ("http://localhost", "http://127.0.0.1", "https://localhost", "https://127.0.0.1")


class McpHandler(BaseHTTPRequestHandler):
    """Un point d'entrée, une méthode : POST porte tout le protocole."""

    server_version = "ModbusAI-MCP"
    protocol_version = "HTTP/1.1"
    dispatcher: Dispatcher
    endpoint: str = DEFAULT_PATH
    token: str = ""

    def do_POST(self) -> None:  # noqa: N802 - nom imposé par http.server
        if not self._accepted():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._fail(400, "Corps de requête absent ou trop gros")
            return
        try:
            message = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._fail(400, "JSON illisible")
            return
        answer = self.dispatcher.handle(message)
        if answer is None:  # notification ou réponse : rien à renvoyer
            self._send(202, b"")
            return
        self._send(200, encode(answer).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        """Pas de flux ouvert par le serveur : tout tient dans la réponse au POST."""
        self._fail(405, "Ce serveur ne tient pas de flux SSE : envoyez vos messages en POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._fail(405, "Ce serveur ne gère pas de session à fermer")

    # ------------------------------------------------------------- garde-fous
    def _accepted(self) -> bool:
        if self.path.split("?")[0].rstrip("/") not in (self.endpoint.rstrip("/"), ""):
            self._fail(404, f"Point d'entrée inconnu : utilisez {self.endpoint}")
            return False
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(LOCAL_ORIGINS):
            self._fail(403, "En-tête Origin refusé : ce serveur n'est pas destiné à un navigateur")
            return False
        if self.token:
            header = self.headers.get("Authorization", "")
            given = header[7:] if header.lower().startswith("bearer ") else ""
            if not secrets.compare_digest(given, self.token):
                self._fail(401, "Jeton absent ou incorrect")
                return False
        return True

    def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _fail(self, code: int, message: str) -> None:
        self._send(code, message.encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:
        """Journal sur la sortie d'erreur, jamais sur la sortie standard."""
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


def serve(
    dispatcher: Dispatcher,
    host: str = "127.0.0.1",
    port: int = 8765,
    endpoint: str = DEFAULT_PATH,
    token: str = "",
) -> ThreadingHTTPServer:
    """Ouvre l'écoute et rend le serveur ; l'appelant décide quand le servir."""
    handler = type(
        "BoundMcpHandler",
        (McpHandler,),
        {"dispatcher": dispatcher, "endpoint": endpoint, "token": token},
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd
