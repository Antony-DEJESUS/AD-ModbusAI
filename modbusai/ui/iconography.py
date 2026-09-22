"""Jeu d'icônes dessiné à l'exécution.

Pas de fichiers d'images ni de dépendance : chaque icône est un tracé sur une
grille de 24 unités, à traits arrondis, dans la couleur du thème courant. Les
widgets qui en portent une sont enregistrés, ce qui permet de toutes les
repeindre quand on bascule clair / sombre (``refresh_all``).

Ajouter une icône = ajouter une fonction de tracé dans ``_PAINTERS``.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from modbusai.ui.palette import current

GRID = 24.0
STROKE = 2.0
DEFAULT_SIZE = 16

Painter = Callable[[QPainter, QPen], None]
_registry: list[list] = []  # [widget, nom, cible, posé sur l'accent, pastille]
_cache: dict[tuple[str, str, int], QIcon] = {}


# ------------------------------------------------------------------ tracés
def _line(painter: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(painter: QPainter, *points: tuple[float, float]) -> None:
    painter.drawPolyline([QPointF(x, y) for x, y in points])


def _play(painter: QPainter, pen: QPen) -> None:
    path = QPainterPath(QPointF(8, 5))
    path.lineTo(19, 12)
    path.lineTo(8, 19)
    path.closeSubpath()
    painter.fillPath(path, pen.color())


def _stop(painter: QPainter, pen: QPen) -> None:
    painter.fillPath(_rounded(6, 6, 12, 12, 2), pen.color())


def _rounded(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _write(painter: QPainter, pen: QPen) -> None:
    _poly(painter, (5, 19), (5, 15), (16, 4), (20, 8), (9, 19), (5, 19))
    _line(painter, 13, 7, 17, 11)


def _refresh(painter: QPainter, pen: QPen) -> None:
    painter.drawArc(QRectF(5, 5, 14, 14), 40 * 16, 280 * 16)
    _poly(painter, (18, 3), (19, 8), (14, 8))


def _export(painter: QPainter, pen: QPen) -> None:
    _line(painter, 12, 4, 12, 14)
    _poly(painter, (8, 10), (12, 14), (16, 10))
    _poly(painter, (5, 17), (5, 20), (19, 20), (19, 17))


def _manual(painter: QPainter, pen: QPen) -> None:
    _poly(painter, (14, 3), (6, 3), (6, 21), (18, 21), (18, 7), (14, 3), (14, 7), (18, 7))
    _line(painter, 9, 11, 15, 11)
    _line(painter, 9, 14, 15, 14)
    _line(painter, 9, 17, 13, 17)


def _help(painter: QPainter, pen: QPen) -> None:
    painter.drawEllipse(QRectF(4, 4, 16, 16))
    font = painter.font()
    font.setPointSizeF(12.0)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(4, 3, 16, 18), Qt.AlignmentFlag.AlignCenter, "?")


def _trash(painter: QPainter, pen: QPen) -> None:
    _line(painter, 4, 7, 20, 7)
    _poly(painter, (9, 7), (9, 4), (15, 4), (15, 7))
    _poly(painter, (6, 7), (7, 20), (17, 20), (18, 7))
    _line(painter, 10, 11, 10, 17)
    _line(painter, 14, 11, 14, 17)


def _copy(painter: QPainter, pen: QPen) -> None:
    painter.drawPath(_rounded(8, 4, 12, 13, 2))
    _poly(painter, (16, 20), (4, 20), (4, 8))


def _settings(painter: QPainter, pen: QPen) -> None:
    for y, cx in ((7.0, 15.0), (12.0, 9.0), (17.0, 16.0)):
        _line(painter, 4, y, 20, y)
        painter.setBrush(pen.color())
        painter.drawEllipse(QPointF(cx, y), 2.2, 2.2)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _info(painter: QPainter, pen: QPen) -> None:
    painter.drawEllipse(QRectF(4, 4, 16, 16))
    _line(painter, 12, 11, 12, 17)
    painter.setBrush(pen.color())
    painter.drawEllipse(QPointF(12, 7.8), 0.9, 0.9)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _theme(painter: QPainter, pen: QPen) -> None:
    painter.drawEllipse(QRectF(5, 5, 14, 14))
    path = QPainterPath(QPointF(12, 5))
    path.arcTo(QRectF(5, 5, 14, 14), 90, -180)
    path.closeSubpath()
    painter.fillPath(path, pen.color())


def _power(painter: QPainter, pen: QPen) -> None:
    painter.drawArc(QRectF(5, 5, 14, 14), 120 * 16, 300 * 16)  # ouverture en haut
    _line(painter, 12, 3, 12, 11)


def _plug(painter: QPainter, pen: QPen) -> None:
    _line(painter, 9, 3, 9, 8)
    _line(painter, 15, 3, 15, 8)
    painter.drawPath(_rounded(6, 8, 12, 7, 3))
    _line(painter, 12, 15, 12, 21)


def _exchange(painter: QPainter, pen: QPen) -> None:
    _line(painter, 4, 9, 19, 9)
    _poly(painter, (16, 6), (19, 9), (16, 12))
    _line(painter, 20, 15, 5, 15)
    _poly(painter, (8, 12), (5, 15), (8, 18))


def _eye(painter: QPainter, pen: QPen) -> None:
    path = QPainterPath(QPointF(3, 12))
    path.quadTo(12, 3, 21, 12)
    path.quadTo(12, 21, 3, 12)
    painter.drawPath(path)
    painter.drawEllipse(QPointF(12, 12), 3.0, 3.0)


def _search(painter: QPainter, pen: QPen) -> None:
    painter.drawEllipse(QRectF(4, 4, 12, 12))
    _line(painter, 15, 15, 20, 20)


def _pulse(painter: QPainter, pen: QPen) -> None:
    _poly(painter, (3, 13), (8, 13), (10, 7), (14, 18), (16, 13), (21, 13))


def _server(painter: QPainter, pen: QPen) -> None:
    painter.drawPath(_rounded(4, 4, 16, 7, 2))
    painter.drawPath(_rounded(4, 13, 16, 7, 2))
    painter.setBrush(pen.color())
    painter.drawEllipse(QPointF(8, 7.5), 1.0, 1.0)
    painter.drawEllipse(QPointF(8, 16.5), 1.0, 1.0)
    painter.setBrush(Qt.BrushStyle.NoBrush)


_PAINTERS: dict[str, Painter] = {
    "play": _play,
    "stop": _stop,
    "write": _write,
    "refresh": _refresh,
    "export": _export,
    "help": _help,
    "manual": _manual,
    "trash": _trash,
    "copy": _copy,
    "settings": _settings,
    "info": _info,
    "theme": _theme,
    "power": _power,
    "plug": _plug,
    "exchange": _exchange,
    "eye": _eye,
    "search": _search,
    "pulse": _pulse,
    "server": _server,
}


# -------------------------------------------------------------------- API
def icon(name: str, on_accent: bool = False, size: int = DEFAULT_SIZE, badge: bool = False) -> QIcon:
    """Icône du jeu, dans la couleur du texte — ou celle posée sur l'accent,
    pour un bouton principal dont le fond est terracotta.

    ``badge`` ajoute une pastille d'accent en bas à droite : c'est le signe
    qu'une activité tourne dans cet onglet."""
    painter_fn = _PAINTERS.get(name)
    if painter_fn is None:
        return QIcon()
    tokens = current()
    tint = tokens.on_accent if on_accent else tokens.text
    key = (name, tint, size, badge)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    ratio = 2.0
    pix = QPixmap(QSize(int(size * ratio), int(size * ratio)))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size * ratio / GRID, size * ratio / GRID)
    pen = QPen(QColor(tint))
    pen.setWidthF(STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter_fn(painter, pen)
    if badge:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(current().accent))
        painter.drawEllipse(QPointF(19, 19), 5.0, 5.0)
    painter.end()
    pix.setDevicePixelRatio(ratio)
    result = QIcon(pix)
    _cache[key] = result
    return result


def set_icon(widget: QWidget, name: str, on_accent: bool = False, size: int = DEFAULT_SIZE) -> None:
    """Pose une icône et retient le widget pour la repeindre au changement de thème."""
    widget.setIcon(icon(name, on_accent, size))
    if hasattr(widget, "setIconSize"):
        widget.setIconSize(QSize(size, size))
    _registry.append([weakref.ref(widget), name, "icon", on_accent, False])


def set_tab_icon(tabs: QWidget, index: int, name: str, size: int = DEFAULT_SIZE) -> None:
    tabs.setTabIcon(index, icon(name, False, size))
    tabs.setIconSize(QSize(size, size))
    _registry.append([weakref.ref(tabs), name, f"tab:{index}", False, False])


def set_tab_badge(tabs: QWidget, index: int, active: bool) -> None:
    """Pastille d'accent sur l'icône d'un onglet : une activité y tourne."""
    target = f"tab:{index}"
    for entry in _registry:
        if entry[0]() is tabs and entry[2] == target:
            if entry[4] == active:
                return
            entry[4] = active
            tabs.setTabIcon(index, icon(entry[1], False, DEFAULT_SIZE, active))
            return


def refresh_all() -> None:
    """Repeint toutes les icônes posées : appelée après un changement de thème."""
    _cache.clear()
    alive: list[list] = []
    for entry in _registry:
        ref, name, target, on_accent, badge = entry
        widget = ref()
        if widget is None:
            continue
        alive.append(entry)
        try:
            if target.startswith("tab:"):
                widget.setTabIcon(int(target[4:]), icon(name, False, DEFAULT_SIZE, badge))
            else:
                widget.setIcon(icon(name, on_accent))
        except RuntimeError:  # widget Qt déjà détruit
            continue
    _registry[:] = alive
