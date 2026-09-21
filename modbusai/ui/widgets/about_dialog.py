"""Pop-up À propos : logo, version, règle de versionnage,
historique des versions (CHANGELOG) et mode d'emploi."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from modbusai import APP_NAME, APP_TITLE, __version__
from modbusai.i18n import tr
from modbusai.ui.resources import changelog_text, logo_pixmap

AUTHOR = "Antony DE JESUS"


def versioning_html() -> str:
    return "".join(
        [
            f"<h3>{tr('Règle de versionnage')}</h3>",
            f"<p>{tr('Numéro X.Y.Z, défini une seule fois dans le code et repris par la barre de titre et le nom de l’exécutable.')}</p>",
            "<ul>",
            f"<li><b>X</b> : {tr('rupture : architecture ou format des données.')}</li>",
            f"<li><b>Y</b> : {tr('nouvelle fonction.')}</li>",
            f"<li><b>Z</b> : {tr('corrections et petites améliorations sans changement de périmètre.')}</li>",
            "</ul>",
            f"<p>{tr('Les versions 0.1 à 0.3 ont porté les trois phases de développement ; la 1.0.0 est la première version complète, validée sur chantier.')}</p>",
            f"<p>{tr('Version installée :')} <b>{__version__}</b></p>",
        ]
    )


def manual_html() -> str:
    sections = [
        (
            tr("Bandeau"),
            tr(
                "Le bandeau règle la liaison du MAÎTRE : protocole (RTU série ou TCP), CONFIGURER, puis CONNECTER. Le serveur esclave a sa propre liaison dans son onglet, sur un autre port : les deux peuvent tourner en même temps. Le bouton THÈME bascule clair / sombre, la liste FR / EN change la langue."
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
                "Une ressource ne sert qu’à un rôle à la fois, mais deux rôles tournent en parallèle sur deux ports différents. Pendant un scan, une campagne ou une torture, seuls les onglets qui partagent la liaison du maître sont verrouillés ; ESPION et SERVEUR ESCLAVE restent accessibles. Lancer l’écoute sur le port du maître ferme d’abord cette liaison."
            ),
        ),
        (
            tr("SERVEUR MCP"),
            tr(
                "Un second exécutable, AD-ModbusAI-MCP, expose le bus comme un jeu d’outils qu’un assistant appelle lui-même : lire, scanner, écouter, lancer une campagne, analyser, produire le rapport. En local il se lance par le client ; avec --http il écoute sur un réseau privé (Tailscale, VPN). Lecture seule tant qu’on ne passe pas --ecriture."
            ),
        ),
    ]
    html = [
        f"<h3>{tr('Mode d’emploi')}</h3>",
        f"<p><i>{tr('Version courte ; le mode d’emploi complet est le PDF livré avec l’outil.')}</i></p>",
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
        credit = QLabel(tr("Fait avec CC par {p0}").format(p0=AUTHOR))
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
