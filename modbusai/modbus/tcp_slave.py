"""Pont entre le serveur TCP (transport) et le ``SlaveHandler`` : décapsule le
MBAP, traite la PDU, ré-encapsule. Le résultat ``HandledRequest`` porte les
trames MBAP complètes pour le journal."""

from __future__ import annotations

from collections.abc import Callable

from modbusai.modbus.mbap import build_mbap, parse_mbap
from modbusai.modbus.slave import HandledRequest, SlaveHandler


def make_tcp_frame_handler(
    handler: SlaveHandler, on_handled: Callable[[HandledRequest, str], None] | None = None
) -> Callable[[bytes, str], bytes | None]:
    def handle(frame: bytes, client: str) -> bytes | None:
        try:
            mbap = parse_mbap(frame)
        except ValueError as exc:
            handler.counters.ignored += 1
            result = HandledRequest(frame, None, None, None, "invalide", str(exc))
            if on_handled:
                on_handled(result, client)
            return None
        core = handler.handle_pdu(mbap.unit_id, mbap.pdu)
        resp = None
        if core.response is not None:
            resp = build_mbap(mbap.transaction_id, mbap.unit_id, core.response)
        detail = core.detail
        if core.kind == "corrompue" and resp is not None:
            # Pas de CRC en TCP : on altère l'identifiant de transaction, le client
            # verra une réponse qui ne correspond à aucune requête en cours.
            resp = bytes([resp[0] ^ 0xFF, resp[1] ^ 0xFF]) + resp[2:]
            detail = "identifiant de transaction volontairement altéré"
        result = HandledRequest(frame, resp, core.slave_id, core.function, core.kind, detail, core.access)
        if on_handled:
            on_handled(result, client)
        return resp

    return handle
