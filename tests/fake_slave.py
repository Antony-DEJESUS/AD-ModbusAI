"""Esclave Modbus RTU simulé sur le côté maître d'un pseudo-terminal (Linux).

Sert aux tests d'intégration de ``SerialLink`` + ``RtuMaster`` sans matériel.
Répond aux FC 01/03/05/06/15/16 sur une petite table, avec un délai réglable et
des modes de panne (silence, CRC faux, exception).
"""

from __future__ import annotations

import os
import pty
import select
import threading
import time

from modbusai.modbus.crc import append_crc, check_crc


class FakeSlave:
    def __init__(self, slave_id: int = 1, delay_ms: float = 20.0) -> None:
        self.slave_id = slave_id
        self.delay_ms = delay_ms
        self.holding: dict[int, int] = {i: i * 10 for i in range(20)}
        self.coils: dict[int, int] = {i: i % 2 for i in range(20)}
        self.mode = "normal"  # normal | silent | bad_crc | exception | truncated
        self.requests: list[bytes] = []
        self._master_fd, self._slave_fd = pty.openpty()
        self.port = os.ttyname(self._slave_fd)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> FakeSlave:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        os.close(self._master_fd)
        os.close(self._slave_fd)

    # -------------------------------------------------------------- boucle
    def _loop(self) -> None:
        buf = b""
        last = None
        while not self._stop.is_set():
            r, _, _ = select.select([self._master_fd], [], [], 0.005)
            now = time.perf_counter()
            if r:
                try:
                    buf += os.read(self._master_fd, 256)
                except OSError:
                    return
                last = now
                continue
            if buf and last is not None and now - last >= 0.01:  # silence 10 ms = fin de trame
                self._handle(buf)
                buf = b""

    def _handle(self, frame: bytes) -> None:
        self.requests.append(frame)
        if not check_crc(frame) or frame[0] != self.slave_id:
            return
        fc = frame[1]
        addr = int.from_bytes(frame[2:4], "big")
        arg = int.from_bytes(frame[4:6], "big")
        if self.mode == "silent":
            return
        if self.mode == "exception" or not self._in_range(fc, addr, arg):
            pdu = bytes([fc | 0x80, 0x02])
        elif fc == 0x03:
            pdu = bytes([fc, 2 * arg]) + b"".join(self.holding.get(addr + i, 0).to_bytes(2, "big") for i in range(arg))
        elif fc == 0x01:
            bits = [self.coils.get(addr + i, 0) for i in range(arg)]
            out = bytearray((arg + 7) // 8)
            for i, b in enumerate(bits):
                if b:
                    out[i // 8] |= 1 << (i % 8)
            pdu = bytes([fc, len(out)]) + bytes(out)
        elif fc == 0x06:
            self.holding[addr] = arg
            pdu = frame[1:6]
        elif fc == 0x05:
            self.coils[addr] = 1 if arg == 0xFF00 else 0
            pdu = frame[1:6]
        elif fc == 0x10:
            data = frame[7 : 7 + frame[6]]
            for i in range(arg):
                self.holding[addr + i] = int.from_bytes(data[2 * i : 2 * i + 2], "big")
            pdu = frame[1:6]
        elif fc == 0x0F:
            data = frame[7 : 7 + frame[6]]
            for i in range(arg):
                self.coils[addr + i] = (data[i // 8] >> (i % 8)) & 1
            pdu = frame[1:6]
        else:
            pdu = bytes([fc | 0x80, 0x01])
        resp = append_crc(bytes([self.slave_id]) + pdu)
        if self.mode == "bad_crc":
            resp = resp[:-1] + bytes([resp[-1] ^ 0xFF])
        elif self.mode == "truncated":
            resp = resp[:-3]
        time.sleep(self.delay_ms / 1000)
        os.write(self._master_fd, resp)

    def _in_range(self, fc: int, addr: int, arg: int) -> bool:
        table = self.holding if fc in (0x03, 0x06, 0x10) else self.coils
        count = 1 if fc in (0x05, 0x06) else arg
        return all((addr + i) in table for i in range(count))
