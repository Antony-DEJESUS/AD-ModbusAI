"""Pop-up À propos : logo AD Automation, version, règle de versionnage,
historique des versions (CHANGELOG) et mode d'emploi."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from modbusai import APP_NAME, APP_TITLE, __version__
from modbusai.i18n import tr
from modbusai.ui.resources import changelog_text, logo_pixmap

AUTHOR = "Antony DE JESUS"
COMPANY = "AD Automation"


def versioning_html() -> str:
    return "".join(
        [
            f"<h3>{tr('Règle de versionnage')}</h3>",
            f"<p>{tr('Numéro X.Y.Z, défini une seule fois dans le code et repris par la barre de titre et le nom de l’exécutable.')}</p>",
            "<ul>",
            f"<li><b>X</b> : {tr('changement majeur d’architecture ou de format des données.')}</li>",
            f"<li><b>Y</b> : {tr('nouvelle phase fonctionnelle (phase 1 = 0.1, phase 2 = 0.2, phase 3 = 0.3).')}</li>",
            f"<li><b>Z</b> : {tr('corrections et petites améliorations sans changement de périmètre.')}</li>",
            "</ul>",
            f"<p>{tr('Version installée :')} <b>{__version__}</b></p>",
        ]
    )


def manual_html() -> str:
    sections = [
        (
            tr("Bandeau"),
            tr(
                "Choisir le protocole (RTU série ou TCP), régler la liaison dans CONFIGURATION, puis CONNEXION. Le bouton THÈME bascule clair / sombre, la liste FR / EN change la langue."
            ),
        ),
        (
            tr("MAÎTRE"),
            tr(
                "Lecture et écriture façon Modbus Doctor : esclave, registre, longueur, type. LECTURE remplit la grille, une valeur modifiée dans la grille puis ECRITURE l’envoie. Cyclique répète la lecture à la période choisie ; Reconnexion auto rouvre le port après une coupure."
            ),
        ),
        (
            tr("ESPION"),
            tr(
                "Écoute passive du bus RS-485 sans jamais émettre : requêtes et réponses appariées, temps de réponse, trames brutes et statistiques par esclave. Indisponible en TCP."
            ),
        ),
        (
            tr("SCAN RÉSEAU"),
            tr(
                "Recherche des esclaves présents sur une plage d’adresses, avec identification FC43 / FC17. La liaison du scan peut être celle du bandeau, des paramètres personnalisés ou un balayage de plusieurs vitesses et parités."
            ),
        ),
        (
            tr("DIAGNOSTIC"),
            tr(
                "Choisir une cible et lancer une campagne minutée (deux minutes par défaut) ou le test de torture. ANALYSER classe les hypothèses avec un score ; chaque hypothèse propose des tests, dont certains s’exécutent d’un clic. EXPORTER TXT enregistre le rapport, AIDE décrit toutes les hypothèses."
            ),
        ),
        (
            tr("SERVEUR ESCLAVE"),
            tr(
                "Simulateur d’esclave façon Mod_RSsim : tables éditables par blocs de 10, adresses servies, voyants RX / TX, journal, animation et injection de défauts (délai, pertes, CRC faux) pour tester une supervision ou le diagnostic lui-même."
            ),
        ),
        (
            tr("Blocages"),
            tr(
                "Un seul rôle occupe le port à la fois : en espion ou en serveur esclave, les autres onglets sont grisés jusqu’à l’arrêt ; en maître connecté, il faut se déconnecter pour changer de rôle."
            ),
        ),
    ]
    html = [
        f"<h3>{tr('Mode d’emploi')}</h3>",
        f"<p><i>{tr('Version courte ; le mode d’emploi complet viendra dans une prochaine version.')}</i></p>",
    ]
    for title, text in sections:
        html.append(f"<p><b>{title}</b><br>{text}</p>")
    return "".join(html)


def changelog_html() -> str:
    text = changelog_text()
    if not text:
        return f"<p>{tr('Historique indisponible.')}</p>"
    out = []
    for line in text.splitlines():
        if line.startswith("## "):
            out.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("# "):
            continue
        elif line.startswith("- "):
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            out.append(f"{line} ")
    return "".join(out)


class AboutDialog(QDialog):
    def __init__(self, dark: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("À propos de {p0}").format(p0=APP_NAME))
        self.resize(720, 560)

        logo = QLabel()
        logo.setPixmap(logo_pixmap(128, dark=dark))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel(f"<b style='font-size:16pt'>{APP_TITLE}</b>")
        subtitle = QLabel(tr("Outil de diagnostic Modbus RTU / RS-485 et TCP"))
        credit = QLabel(tr("Fait avec Claude Code par {p0} - {p1}").format(p0=AUTHOR, p1=COMPANY))
        header_text = QVBoxLayout()
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_text.addWidget(credit)
        header_text.addStretch(1)
        header = QHBoxLayout()
        header.addWidget(logo)
        header.addSpacing(12)
        header.addLayout(header_text, 1)

        tabs = QTabWidget()
        for name, html in (
            (tr("Version"), versioning_html()),
            (tr("Historique"), changelog_html()),
            (tr("Mode d’emploi"), manual_html()),
        ):
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(html)
            tabs.addTab(browser, name)

        close_btn = QPushButton(tr("Fermer"))
        close_btn.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(tabs, 1)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
