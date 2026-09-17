"""Petites icônes dessinées à l'exécution.

La feuille de style redéfinit le fond et la bordure des listes déroulantes et
des compteurs : sous Windows, le style natif cesse alors de dessiner ses
indicateurs et les flèches disparaissent. Plutôt que d'embarquer des images,
on trace un chevron dans la couleur du texte du thème courant et on enregistre
le PNG dans le dossier temporaire, seule forme que ``image: url(...)`` accepte.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

SIZE = 16
_cache: dict[tuple[str, str], str] = {}


def chevron(color: QColor, direction: str = "down") -> str:
    """Chemin du PNG (au format attendu par ``url()``), vide si le tracé échoue."""
    key = (color.name(), direction)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    path = Path(tempfile.gettempdir()) / f"modbusai_{direction}_{color.name().lstrip('#')}.png"
    if not path.exists() and not _draw(color, direction, path):
        _cache[key] = ""
        return ""
    _cache[key] = path.as_posix()
    return _cache[key]


def _draw(color: QColor, direction: str, path: Path) -> bool:
    try:
        pix = QPixmap(SIZE, SIZE)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color)
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        s = SIZE
        if direction == "up":
            points = ((0.26, 0.60), (0.50, 0.38), (0.74, 0.60))
        else:
            points = ((0.26, 0.40), (0.50, 0.62), (0.74, 0.40))
        painter.drawPolyline([QPointF(x * s, y * s) for x, y in points])
        painter.end()
        return bool(pix.save(str(path), "PNG"))
    except (OSError, RuntimeError):
        return False
