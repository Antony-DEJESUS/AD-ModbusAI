"""Délégué d'édition qui n'écrase pas une saisie en cours.

Depuis Qt 6, tout ``dataChanged`` qui couvre la cellule en édition (surlignage
d'accès, relecture de la table, scrutation du maître) recopie la valeur du
modèle dans l'éditeur : pendant qu'un maître interroge, ce que l'on tape est
effacé toutes les 80 ms. Une fois la saisie commencée, l'éditeur est laissé tel
quel jusqu'à la validation ou l'abandon.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QLineEdit, QStyledItemDelegate, QWidget


class TypingDelegate(QStyledItemDelegate):
    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QLineEdit) and editor.isModified():
            return
        super().setEditorData(editor, index)
