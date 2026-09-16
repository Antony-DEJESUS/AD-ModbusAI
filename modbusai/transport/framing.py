"""Découpage d'un flux d'octets horodatés en trames RTU, par détection de silence.

Utilisé par ``SerialLink.receive()`` en mode maître et, plus tard, par le mode
passif : le framer ne sait pas s'il y a eu une requête avant, il ne voit que des
blocs d'octets et des instants.
"""

from __future__ import annotations

from datetime import datetime

from modbusai.transport.records import ByteChunk, Direction, RawFrame


class RtuFramer:
    """Regroupe des ``ByteChunk`` en ``RawFrame`` : deux blocs séparés d'un
    silence >= ``gap_ns`` appartiennent à deux trames différentes."""

    def __init__(self, gap_ns: int) -> None:
        if gap_ns <= 0:
            raise ValueError("gap_ns doit être strictement positif")
        self.gap_ns = gap_ns
        self._pending: list[ByteChunk] = []
        self._pending_wall: datetime | None = None
        self._last_frame_end_ns: int | None = None

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    def feed(self, chunk: ByteChunk, wall_time: datetime | None = None) -> list[RawFrame]:
        """Ajoute un bloc ; renvoie les trames closes par son arrivée (0 ou 1)."""
        if not chunk.data:
            return []
        closed: list[RawFrame] = []
        if self._pending and chunk.t_ns - self._pending[-1].t_ns >= self.gap_ns:
            closed.append(self._close())
        if not self._pending:
            self._pending_wall = wall_time or datetime.now()
        self._pending.append(chunk)
        return closed

    def flush(self, now_ns: int | None = None) -> RawFrame | None:
        """Clôt la trame en cours si le silence est acquis (ou inconditionnellement
        si ``now_ns`` est None). Renvoie None s'il n'y a rien à clore."""
        if not self._pending:
            return None
        if now_ns is not None and now_ns - self._pending[-1].t_ns < self.gap_ns:
            return None
        return self._close()

    def reset(self) -> None:
        self._pending.clear()
        self._pending_wall = None
        self._last_frame_end_ns = None

    def _close(self) -> RawFrame:
        chunks = tuple(self._pending)
        first_ns = chunks[0].t_ns
        silence = None if self._last_frame_end_ns is None else first_ns - self._last_frame_end_ns
        frame = RawFrame(
            direction=Direction.RX,
            data=b"".join(c.data for c in chunks),
            t_first_ns=first_ns,
            t_last_ns=chunks[-1].t_ns,
            wall_time=self._pending_wall or datetime.now(),
            chunks=chunks,
            silence_before_ns=silence,
        )
        self._last_frame_end_ns = chunks[-1].t_ns
        self._pending.clear()
        self._pending_wall = None
        return frame
