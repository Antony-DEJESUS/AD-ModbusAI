"""Feuille de style commune aux deux thèmes : coins arrondis, marges aérées,
bordures discrètes. Les couleurs viennent de la palette (``palette(...)``),
jamais codées en dur, pour rester lisible en clair comme en sombre."""

from __future__ import annotations

import platform

RADIUS = 6


def _arrow_rules(arrows: dict[str, str] | None) -> str:
    """Indicateurs des listes déroulantes et des compteurs : la feuille de style
    remplace le fond natif, il faut redessiner les flèches nous-mêmes."""
    arrows = arrows or {}
    down, up, off = arrows.get("down", ""), arrows.get("up", ""), arrows.get("down_disabled", "")
    if not down or not up:
        return ""
    rules = [
        f"    QComboBox::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}",
        "    QComboBox::down-arrow:on { top: 1px; }",
        f"    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({up}); width: 11px; height: 11px; }}",
        f"    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({down}); width: 11px; height: 11px; }}",
    ]
    if off:
        rules.append(f"    QComboBox::down-arrow:disabled {{ image: url({off}); }}")
        rules.append(
            f"    QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled,"
            f" QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: url({off}); }}"
        )
    return "\n".join(rules)


def base_font_family() -> str:
    system = platform.system()
    if system == "Windows":
        return '"Segoe UI Variable", "Segoe UI", Arial'
    if system == "Darwin":
        return '"SF Pro Text", "Helvetica Neue", Arial'
    return '"Inter", "Noto Sans", "DejaVu Sans", Arial'


def build_qss(arrows: dict[str, str] | None = None) -> str:
    """``arrows`` : chemins des chevrons (``down``, ``up``, ``down_disabled``),
    dessinés par ``ui.icons`` dans la couleur du thème. Absents, on laisse le
    style natif faire ce qu'il peut."""
    r = RADIUS
    return f"""
    QWidget {{ font-family: {base_font_family()}; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: palette(window); }}

    QPushButton {{
        background: palette(button); color: palette(button-text);
        border: 1px solid palette(mid); border-radius: {r}px; padding: 5px 12px; min-height: 18px;
    }}
    QPushButton:hover {{ background: palette(midlight); border-color: palette(dark); }}
    QPushButton:pressed {{ background: palette(mid); }}
    QPushButton:disabled {{ color: palette(mid); border-color: palette(midlight); background: palette(window); }}
    QPushButton:default {{ border: 1px solid palette(highlight); }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser, QTextEdit {{
        background: palette(base); color: palette(text);
        border: 1px solid palette(mid); border-radius: {r}px; padding: 3px 6px;
        selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
        border: 1px solid palette(highlight);
    }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: palette(mid); }}
    QComboBox::drop-down {{ border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }}
{_arrow_rules(arrows)}
    QComboBox QAbstractItemView {{
        background: palette(base); border: 1px solid palette(mid); border-radius: {r}px;
        selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
    }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 16px; border: none; background: transparent;
    }}

    QGroupBox {{
        border: 1px solid palette(mid); border-radius: {r + 2}px; margin-top: 14px; padding: 10px 6px 6px 6px;
        font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px; }}

    QFrame[frameShape="6"], QFrame[frameShape="1"] {{ border: 1px solid palette(mid); border-radius: {r + 2}px; }}

    QTabWidget::pane {{ border: 1px solid palette(mid); border-radius: {r + 2}px; top: -1px; background: palette(window); }}
    QTabBar::tab {{
        background: palette(window); color: palette(text); border: 1px solid transparent;
        border-top-left-radius: {r}px; border-top-right-radius: {r}px; padding: 7px 16px; margin-right: 2px; font-weight: 600;
    }}
    QTabBar::tab:selected {{ background: palette(base); border-color: palette(mid); border-bottom-color: palette(base); }}
    QTabBar::tab:hover:!selected {{ background: palette(midlight); }}
    QTabBar::tab:disabled {{ color: palette(mid); }}

    QTableView, QTableWidget, QListWidget {{
        background: palette(base); alternate-background-color: palette(alternate-base);
        border: 1px solid palette(mid); border-radius: {r}px; gridline-color: palette(midlight);
        selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
    }}
    QHeaderView::section {{
        background: palette(window); color: palette(text); border: none; border-bottom: 1px solid palette(mid);
        border-right: 1px solid palette(midlight); padding: 5px 6px; font-weight: 600;
    }}
    QTableCornerButton::section {{ background: palette(window); border: none; }}

    QProgressBar {{ border: 1px solid palette(mid); border-radius: {r}px; background: palette(base); text-align: center; height: 16px; }}
    QProgressBar::chunk {{ background: palette(highlight); border-radius: {r - 1}px; }}

    QCheckBox, QRadioButton {{ spacing: 6px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: palette(mid); border-radius: 4px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: palette(dark); }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: palette(mid); border-radius: 4px; min-width: 24px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QSplitter::handle {{ background: transparent; }}
    QToolTip {{ background: palette(tool-tip-base); color: palette(tool-tip-text); border: 1px solid palette(mid); border-radius: 4px; padding: 4px; }}
    QLabel#credit {{ color: palette(mid); }}
    QLabel#credit:hover {{ color: palette(highlight); }}
    """
