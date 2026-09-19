"""Feuille de style commune aux deux thèmes.

Toutes les couleurs viennent de la charte (``ui/palette.py``) : jamais de
valeur écrite en dur ici ni dans un widget. L'esprit : surfaces sobres en gris
chaud, coins arrondis, bordures discrètes, et le terracotta réservé à ce qui
engage — bouton principal, onglet actif, focus, sélection, progression.
"""

from __future__ import annotations

import platform

from modbusai.ui.palette import Tokens, current

RADIUS = 8
CARD_RADIUS = 12
PAGE_MARGINS = (12, 12, 12, 12)  # marges intérieures d'un onglet : rien ne colle au trait du bandeau


def base_font_family() -> str:
    system = platform.system()
    if system == "Windows":
        return '"Segoe UI Variable Text", "Segoe UI", Inter, Arial'
    if system == "Darwin":
        return '"SF Pro Text", "Helvetica Neue", Inter, Arial'
    return 'Inter, "Noto Sans", "DejaVu Sans", Arial'


def mono_font_family() -> str:
    system = platform.system()
    if system == "Windows":
        return '"Cascadia Mono", Consolas, "Courier New"'
    if system == "Darwin":
        return '"SF Mono", Menlo, Monaco'
    return '"JetBrains Mono", "DejaVu Sans Mono", monospace'


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


def _check_image(icons: dict[str, str] | None) -> str:
    mark = (icons or {}).get("check", "")
    return f"image: url({mark});" if mark else ""


def build_qss(tokens: Tokens | None = None, arrows: dict[str, str] | None = None) -> str:
    t = tokens or current()
    r, cr = RADIUS, CARD_RADIUS
    return f"""
    QWidget {{ font-family: {base_font_family()}; font-size: 10pt; color: {t.text}; }}
    QMainWindow, QDialog {{ background: {t.window}; }}
    QToolTip {{
        background: {t.elevated}; color: {t.text}; border: 1px solid {t.border};
        border-radius: {r}px; padding: 6px 8px;
    }}

    /* ---------------------------------------------------------- boutons */
    QPushButton {{
        background: {t.elevated}; color: {t.text};
        border: 1px solid {t.border}; border-radius: {r}px;
        padding: 6px 14px; min-height: 18px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {t.hover}; border-color: {t.border_strong}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:focus {{ border-color: {t.accent}; }}
    QPushButton:disabled {{ background: {t.window}; color: {t.muted}; border-color: {t.border}; }}
    QPushButton[variant="primary"] {{
        background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent};
    }}
    QPushButton[variant="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
    QPushButton[variant="primary"]:pressed {{ background: {t.accent_pressed}; border-color: {t.accent_pressed}; }}
    QPushButton[variant="primary"]:disabled {{
        background: {t.window}; color: {t.muted}; border-color: {t.border};
    }}
    QPushButton[variant="danger"] {{ color: {t.error}; border-color: {t.error}; }}
    QPushButton[variant="danger"]:hover {{ background: {t.hover}; border-color: {t.error}; }}
    QPushButton[variant="quiet"] {{ background: transparent; border-color: transparent; color: {t.muted}; }}
    QPushButton[variant="quiet"]:hover {{ background: {t.hover}; color: {t.text}; }}

    /* ----------------------------------------------------------- saisie */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser, QTextEdit {{
        background: {t.surface}; color: {t.text};
        border: 1px solid {t.border}; border-radius: {r}px; padding: 4px 8px;
        selection-background-color: {t.accent}; selection-color: {t.on_accent};
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {t.border_strong}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {t.accent}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        background: {t.window}; color: {t.muted};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }}
{_arrow_rules(arrows)}
    QComboBox QAbstractItemView {{
        background: {t.elevated}; color: {t.text};
        border: 1px solid {t.border}; border-radius: {r}px; padding: 4px;
        selection-background-color: {t.accent}; selection-color: {t.on_accent};
    }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 16px; border: none; background: transparent;
    }}

    /* ------------------------------------------------------------ cartes */
    QGroupBox {{
        background: {t.card}; border: 1px solid {t.border}; border-radius: {cr}px;
        margin-top: 16px; padding: 14px 10px 10px 10px; font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px;
        color: {t.muted}; font-size: 9pt; letter-spacing: 1px;
    }}
    QFrame#card {{ background: {t.card}; border: 1px solid {t.border}; border-radius: {cr}px; }}
    QFrame[frameShape="4"], QFrame[frameShape="5"] {{ border: none; background: {t.border}; max-height: 1px; }}
    QFrame[frameShape="5"] {{ max-width: 1px; max-height: 16777215px; }}

    /* ------------------------------------------------------------ onglets */
    QTabWidget::pane {{
        border: 1px solid {t.border}; border-radius: {cr}px; top: -1px; background: {t.window};
    }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent; color: {t.muted};
        border: none; border-bottom: 2px solid transparent;
        padding: 9px 18px; margin-right: 4px; font-weight: 700; letter-spacing: 0.5px;
    }}
    QTabBar::tab:hover:!selected {{ color: {t.text}; }}
    QTabBar::tab:selected {{ color: {t.accent}; border-bottom: 2px solid {t.accent}; }}
    QTabBar::tab:disabled {{ color: {t.border_strong}; }}

    /* ------------------------------------------------------------ tables */
    QTableView, QTableWidget, QListWidget, QTreeView {{
        background: {t.surface}; alternate-background-color: {t.surface_alt};
        border: 1px solid {t.border}; border-radius: {r}px; gridline-color: {t.border};
        selection-background-color: {t.accent}; selection-color: {t.on_accent};
    }}
    QListWidget::item {{ padding: 5px 6px; border-radius: {r - 2}px; }}
    QListWidget::item:hover:!selected {{ background: {t.hover}; }}
    QListWidget::item:selected {{
        background: {t.accent_soft}; color: {t.text}; border-left: 3px solid {t.accent};
    }}
    QHeaderView {{ background: {t.window}; }}
    QHeaderView::section {{
        background: {t.window}; color: {t.muted};
        border: none; border-bottom: 1px solid {t.border}; border-right: 1px solid {t.border};
        padding: 7px 8px; font-weight: 700; font-size: 9pt; letter-spacing: 0.4px;
    }}
    QTableCornerButton::section {{ background: {t.window}; border: none; border-bottom: 1px solid {t.border}; }}

    /* -------------------------------------------------------- progression */
    QProgressBar {{
        border: none; border-radius: 5px; background: {t.hover};
        text-align: center; height: 10px; color: {t.muted}; font-size: 8pt;
    }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 5px; }}

    /* ------------------------------------------------------------ cases */
    QCheckBox, QRadioButton {{ spacing: 7px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QCheckBox::indicator {{ border: 1px solid {t.border_strong}; border-radius: 5px; background: {t.surface}; }}
    QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
    QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; {_check_image(arrows)} }}
    QCheckBox::indicator:disabled {{ background: {t.window}; border-color: {t.border}; }}
    QRadioButton::indicator {{ border: 1px solid {t.border_strong}; border-radius: 8px; background: {t.surface}; }}
    QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
    QRadioButton::indicator:checked {{
        border: 1px solid {t.accent};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {t.accent}, stop:0.5 {t.accent}, stop:0.55 {t.surface}, stop:1 {t.surface});
    }}

    /* ------------------------------------------------------ ascenseurs */
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.border_strong}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t.border_strong}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* ------------------------------------------------------------ divers */
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: {t.border}; }}
    QLabel[variant="muted"] {{ color: {t.muted}; }}
    QLabel[variant="section"] {{ color: {t.muted}; font-weight: 700; font-size: 9pt; letter-spacing: 0.6px; }}
    QLabel#appName {{ font-size: 12pt; font-weight: 800; letter-spacing: 0.3px; }}
    QLabel#appTag {{ color: {t.muted}; font-size: 8pt; letter-spacing: 1.2px; }}
    QPlainTextEdit#logConsole, QLabel#logColumns {{ font-family: {mono_font_family()}; }}
    QLabel#logColumns {{ color: {t.muted}; }}
    QLabel#credit {{ color: {t.muted}; }}
    QLabel#credit:hover {{ color: {t.accent}; }}
    QFrame#topBar {{ background: {t.card}; border: 1px solid {t.border}; border-radius: {cr}px; }}
    QLabel#linkSummary {{ font-weight: 700; }}
    """
