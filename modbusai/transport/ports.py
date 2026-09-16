"""Détection des ports série disponibles."""

from __future__ import annotations

from serial.tools import list_ports

from modbusai.transport.records import PortInfo


def list_serial_ports() -> list[PortInfo]:
    """Ports COM présents, triés par nom (COM1, COM2, ... COM10)."""
    ports = [
        PortInfo(device=p.device, description=p.description or "", hwid=p.hwid or "")
        for p in list_ports.comports()
    ]
    return sorted(ports, key=_port_sort_key)


def _port_sort_key(p: PortInfo) -> tuple[str, int]:
    digits = "".join(ch for ch in p.device if ch.isdigit())
    return (p.device.rstrip("0123456789"), int(digits) if digits else 0)
