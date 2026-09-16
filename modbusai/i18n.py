"""Internationalisation minimale, sans Qt.

Le français est la langue source : chaque texte affiché est écrit en français
dans le code et passé à ``tr()``. En anglais, ``tr`` cherche la traduction
dans ``i18n_en.EN`` ; une clé absente retombe sur le français. Les textes
dynamiques utilisent des gabarits : ``tr("Connecté : {summary}").format(...)``.

Module feuille : utilisable par toutes les couches (l'analyse produit des
textes lisibles, elle a donc besoin de la langue courante).
"""

from __future__ import annotations

LANGUAGES = {"fr": "Français", "en": "English"}
DEFAULT_LANGUAGE = "fr"
_current = DEFAULT_LANGUAGE
_missing: set[str] = set()


def set_language(lang: str) -> str:
    global _current
    _current = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
    return _current


def current_language() -> str:
    return _current


def tr(text: str) -> str:
    if _current == "fr" or not text:
        return text
    from modbusai.i18n_en import EN  # import différé : le dictionnaire est volumineux

    translated = EN.get(text)
    if translated is None:
        _missing.add(text)
        return text
    return translated


def missing_keys() -> set[str]:
    """Clés demandées sans traduction (pour les tests et la maintenance)."""
    return set(_missing)
