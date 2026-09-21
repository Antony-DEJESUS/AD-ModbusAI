"""Construit le mode d'emploi PDF depuis le code lui-même.

Les faits qui peuvent changer (version, catalogue d'hypothèses, phases de
torture, codes d'exception, statuts du scan) sont lus dans le paquet, jamais
recopiés : le manuel ne peut pas dire autre chose que le logiciel. Les captures
viennent de ``captures.py``.

    PYTHONPATH=. .venv/bin/python docs/manuel/build_manuel.py

Sortie : docs/AD-ModbusAI_Mode_d_emploi_v<version>.pdf (rendu par Chromium
sans interface, puis pied de page et numéros ajoutés avec PyMuPDF).
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from modbusai import APP_NAME, __version__
from modbusai.analysis.diagnostic import CATALOGUE, SCORE_EXPLANATION, SCORE_LEGEND
from modbusai.analysis.scanner import ScanStatus
from modbusai.analysis.stress import default_scenario
from modbusai.modbus.exceptions import EXCEPTION_LABELS
from modbusai.modbus.records import FunctionCode, Request
from modbusai.transport.records import SerialSettings

HERE = Path(__file__).parent
DOCS = HERE.parent
IMG = HERE / "img"
HTML_OUT = HERE / "manuel.html"
PDF_OUT = DOCS / f"AD-ModbusAI_Mode_d_emploi_v{__version__}.pdf"
AUTHOR = "Antony DE JESUS"

ACCENT = "#C2603E"
TEXT = "#241F1B"
MUTED = "#786F65"
BORDER = "#DFD8CB"
SOFT = "#F6E5DB"
CARD = "#FAF8F3"
OK = "#177A50"
WARN = "#8F6310"
ERROR = "#C43B31"

FUNCTION_NAMES = {
    "READ_COILS": ("Lecture de bobines", "1 Coil status"),
    "READ_DISCRETE_INPUTS": ("Lecture d'entrées discrètes", "2 Input status"),
    "READ_HOLDING_REGISTERS": ("Lecture de registres de maintien", "3 Holding registers"),
    "READ_INPUT_REGISTERS": ("Lecture de registres d'entrée", "4 Input registers"),
    "WRITE_SINGLE_COIL": ("Écriture d'une bobine", "écriture, 1 coil"),
    "WRITE_SINGLE_REGISTER": ("Écriture d'un registre", "écriture, 1 holding"),
    "WRITE_MULTIPLE_COILS": ("Écriture de plusieurs bobines", "écriture, n coils"),
    "WRITE_MULTIPLE_REGISTERS": ("Écriture de plusieurs registres", "écriture, n holdings"),
    "REPORT_SLAVE_ID": ("Identification de l'esclave", "scan : identification"),
    "READ_DEVICE_ID": ("Identification de l'équipement (objets fabricant, produit, version)", "scan : identification"),
}

SCAN_STATUS_MEANING = {
    "présent": "L'esclave a répondu correctement à la lecture de test.",
    "présent (exception)": "L'esclave a répondu par une exception Modbus : il existe, mais le registre lu n'est pas le bon (ou le type). Il est bien présent.",
    "réponse corrompue": "Une trame est revenue, mais son CRC est faux : bruit sur la ligne, ou mauvais réglage de vitesse / parité (l'esclave répond dans une autre langue).",
    "réponse incohérente": "CRC juste mais contenu inattendu : un autre esclave a répondu, ou deux esclaves partagent la même adresse.",
    "absent": "Aucun octet reçu dans le délai, sur tous les essais.",
    "erreur liaison": "Le port a disparu ou l'écriture a échoué pendant le test : problème d'adaptateur, pas d'esclave.",
}


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def img(name: str, caption: str, width: str = "100%") -> str:
    path = (IMG / f"{name}.png").resolve().as_uri()
    return f'<figure><img src="{path}" style="width:{width}" alt="{esc(caption)}"><figcaption>{esc(caption)}</figcaption></figure>'


def note(kind: str, title: str, body: str) -> str:
    return f'<div class="note {kind}"><div class="note-title">{esc(title)}</div><div>{body}</div></div>'


def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


# --------------------------------------------------------------------- style
CSS = f"""
@page {{ size: A4; margin: 18mm 17mm 20mm 17mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: "Segoe UI", Inter, "Noto Sans", "DejaVu Sans", Arial, sans-serif;
  font-size: 10.5pt; line-height: 1.45; color: {TEXT};
}}
h1, h2, h3, h4 {{ font-weight: 700; line-height: 1.2; margin: 0; }}
h1 {{ font-size: 22pt; color: {ACCENT}; margin: 0 0 10mm 0; padding-bottom: 3mm; border-bottom: 2px solid {ACCENT}; page-break-before: always; }}
h1 small {{ display: block; font-size: 10pt; color: {MUTED}; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 2mm; }}
h2 {{ font-size: 14pt; margin: 8mm 0 3mm 0; color: {TEXT}; page-break-after: avoid; }}
h3 {{ font-size: 11.5pt; margin: 6mm 0 2mm 0; color: {ACCENT}; page-break-after: avoid; }}
p {{ margin: 0 0 3mm 0; text-align: justify; hyphens: auto; }}
ul, ol {{ margin: 0 0 3mm 0; padding-left: 6mm; }}
li {{ margin-bottom: 1.2mm; }}
code, .mono {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; font-size: 9.2pt; background: {CARD}; border: 1px solid {BORDER}; border-radius: 3px; padding: 0 3px; }}
pre {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; font-size: 8.4pt; line-height: 1.35; background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 3mm 4mm; white-space: pre-wrap; margin: 0 0 4mm 0; }}
b, strong {{ font-weight: 700; }}
.k {{ font-weight: 700; letter-spacing: 0.3px; }}
figure {{ margin: 3mm 0 5mm 0; page-break-inside: avoid; }}
figure img {{ display: block; border: 1px solid {BORDER}; border-radius: 6px; }}
figcaption {{ font-size: 8.8pt; color: {MUTED}; margin-top: 1.5mm; }}
table {{ width: 100%; border-collapse: collapse; margin: 2mm 0 5mm 0; font-size: 9.4pt; page-break-inside: auto; }}
th {{ text-align: left; background: {CARD}; color: {MUTED}; font-size: 8.6pt; letter-spacing: 0.6px; text-transform: uppercase; padding: 2mm 2.5mm; border-bottom: 1.5px solid {BORDER}; }}
td {{ padding: 1.8mm 2.5mm; border-bottom: 1px solid {BORDER}; vertical-align: top; }}
tr {{ page-break-inside: avoid; }}
ul, ol {{ page-break-inside: avoid; }}
p {{ orphans: 3; widows: 3; }}
table.compact td {{ padding: 1.2mm 2mm; }}
.note {{ border: 1px solid {BORDER}; border-left: 4px solid {ACCENT}; background: {CARD}; border-radius: 6px; padding: 3mm 4mm; margin: 3mm 0 5mm 0; page-break-inside: avoid; }}
.note.astuce {{ border-left-color: {OK}; }}
.note.attention {{ border-left-color: {WARN}; }}
.note.danger {{ border-left-color: {ERROR}; }}
.note-title {{ font-weight: 700; font-size: 9pt; letter-spacing: 0.8px; text-transform: uppercase; color: {MUTED}; margin-bottom: 1.2mm; }}
.astuce .note-title {{ color: {OK}; }} .attention .note-title {{ color: {WARN}; }} .danger .note-title {{ color: {ERROR}; }}
.chip {{ display: inline-block; border: 1px solid; border-radius: 9px; padding: 0 6px; font-weight: 600; font-size: 8.8pt; }}
.cover {{ height: 250mm; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; page-break-after: always; }}
.cover img {{ width: 38mm; margin-bottom: 14mm; }}
.cover .name {{ font-size: 34pt; font-weight: 800; color: {TEXT}; letter-spacing: -0.5px; }}
.cover .sub {{ font-size: 15pt; color: {ACCENT}; font-weight: 700; margin-top: 2mm; letter-spacing: 1px; text-transform: uppercase; }}
.cover .meta {{ margin-top: 16mm; color: {MUTED}; font-size: 10.5pt; line-height: 1.7; }}
.cover .rule {{ width: 60mm; height: 3px; background: {ACCENT}; margin: 8mm 0; }}
.toc {{ page-break-after: always; }}
.toc h1 {{ page-break-before: auto; }}
.toc ol {{ list-style: none; padding: 0; columns: 1; }}
.toc li {{ margin: 0 0 1.6mm 0; font-size: 10.5pt; }}
.toc li.l2 {{ margin-left: 7mm; font-size: 9.6pt; color: {MUTED}; }}
.toc .num {{ display: inline-block; width: 9mm; color: {ACCENT}; font-weight: 700; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }}
.catalogue h3 {{ margin-top: 5mm; }}
.catalogue .fiche {{ border: 1px solid {BORDER}; border-radius: 6px; padding: 3mm 4mm; margin-bottom: 3.5mm; page-break-inside: avoid; }}
.catalogue .fiche p {{ margin-bottom: 1.5mm; }}
.catalogue .label {{ font-weight: 700; color: {MUTED}; font-size: 8.8pt; letter-spacing: 0.6px; text-transform: uppercase; }}
.muted {{ color: {MUTED}; }}
"""


# ------------------------------------------------------------------- contenu
def cover() -> str:
    mark = (DOCS.parent / "assets" / "mark-512.png").resolve().as_uri()
    return f"""
<div class="cover">
  <img src="{mark}" alt="AD">
  <div class="name">{esc(APP_NAME)}</div>
  <div class="sub">Mode d'emploi</div>
  <div class="rule"></div>
  <div class="meta">
    Outil de diagnostic Modbus RTU / RS-485 et Modbus TCP<br>
    Version {esc(__version__)} &nbsp;·&nbsp; {date.today():%d/%m/%Y}<br>
    Fait avec CC par {esc(AUTHOR)}
  </div>
</div>"""


SECTIONS: list[tuple[str, str]] = [
    ("1", "Présentation"),
    ("2", "Installation et premier lancement"),
    ("3", "Le bandeau : la liaison du maître"),
    ("4", "Onglet MAÎTRE"),
    ("5", "Onglet ESPION"),
    ("6", "Onglet SCAN RÉSEAU"),
    ("7", "Onglet DIAGNOSTIC"),
    ("8", "Onglet SERVEUR ESCLAVE"),
    ("9", "Un port, un rôle : l'arbitrage"),
    ("10", "Câblage RS-485 et bonnes pratiques"),
    ("11", "Dépannage"),
    ("12", "Serveur MCP : diagnostiquer avec un assistant"),
    ("13", "Annexes"),
]


def toc() -> str:
    items = "".join(
        f'<li><span class="num">{n}</span><a href="#s{n}" style="color:inherit;text-decoration:none">{esc(t)}</a></li>'
        for n, t in SECTIONS
    )
    return f'<div class="toc"><h1><small>AD - ModbusAI {esc(__version__)}</small>Sommaire</h1><ol>{items}</ol></div>'


def h1(n: str, title: str) -> str:
    return f'<h1 id="s{n}"><small>Chapitre {n}</small>{esc(title)}</h1>'


def s1_presentation() -> str:
    return (
        h1("1", "Présentation")
        + "<h2>1.1 Le constat</h2>"
        + "<p>Pour lire un registre, on sort Modbus Doctor. Pour simuler un esclave et tester une supervision, on cherche "
        "Mod_RSsim. Pour écouter un bus sans le perturber, encore un autre utilitaire. Et quand une liaison RS-485 "
        "décroche par intermittence, aucun des trois ne répond : ils affichent « timeout » et laissent deviner la "
        "cause — terminaison, longueur du bus, doublon d'adresse, esclave trop lent, adaptateur USB.</p>"
        "<p><b>AD - ModbusAI</b> regroupe ces usages dans un seul exécutable et y ajoute ce qui manquait : une mesure "
        "de la qualité de la liaison esclave par esclave, des hypothèses classées par vraisemblance avec les tests "
        "qui permettent de les départager, et un rapport texte complet — relisible par un collègue, ou par un "
        "assistant comme Claude Code à qui l'on confie le fichier.</p>"
        + "<h2>1.2 Les cinq onglets</h2>"
        + table(
            ["Onglet", "Rôle", "Équivalent connu"],
            [
                ["<span class='k'>MAÎTRE</span>", "Lecture et écriture de registres, lecture cyclique, formats 8 à 64 bits, journal détaillé.", "Modbus Doctor"],
                ["<span class='k'>ESPION</span>", "Écoute passive du bus RS-485, sans jamais émettre : requêtes et réponses appariées, temps par esclave.", "analyseur de trames"],
                ["<span class='k'>SCAN RÉSEAU</span>", "Recherche des esclaves présents, identification du matériel, balayage des vitesses et parités.", "—"],
                ["<span class='k'>DIAGNOSTIC</span>", "Campagnes minutées, test de torture, hypothèses classées, tests pour départager, export texte.", "—"],
                ["<span class='k'>SERVEUR ESCLAVE</span>", "Simulateur d'équipement avec injection de défauts, sur sa propre liaison.", "Mod_RSsim"],
            ],
        )
        + "<p>Le maître et le serveur esclave peuvent tourner <b>en même temps</b>, sur deux ports différents : "
        "l'outil sert alors de banc d'essai complet, ou simule l'équipement absent pendant qu'on interroge le vrai.</p>"
        + "<h2>1.3 Ce que l'outil ne fait pas</h2>"
        + "<ul>"
        "<li>Écouter un réseau Modbus <b>TCP</b> en espion : il faudrait une recopie de port sur le commutateur. Le bouton l'explique.</li>"
        "<li>Exporter en JSON ou en PDF : le rapport est en texte, lisible partout et par tout le monde.</li>"
        "<li>Rejouer des scénarios d'animation programmés côté serveur esclave (l'animation se limite à l'incrément).</li>"
        "<li>Autre langue que le français et l'anglais.</li>"
        "</ul>"
    )


def s2_installation() -> str:
    return (
        h1("2", "Installation et premier lancement")
        + "<h2>2.1 Un seul fichier</h2>"
        + f"<p>L'application tient dans un exécutable unique, <code>AD-ModbusAI_v{esc(__version__)}.exe</code>. "
        "Rien à installer, aucun droit administrateur : copiez-le où vous voulez (clé USB comprise) et lancez-le. "
        "Windows 10 et 11.</p>"
        + note(
            "attention",
            "Avertissement SmartScreen",
            "Au premier lancement, Windows affiche « Windows a protégé votre ordinateur » parce que l'exécutable "
            "n'est pas signé numériquement. Cliquez sur <b>Informations complémentaires</b>, puis <b>Exécuter quand "
            "même</b>. L'avertissement ne revient pas pour ce fichier.",
        )
        + "<h2>2.2 Pilote de l'adaptateur USB / RS-485</h2>"
        + "<p>L'outil parle à n'importe quel adaptateur vu comme un port COM par Windows. Les puces courantes "
        "(CH340, CP2102, FTDI) sont reconnues d'office par Windows 10 et 11 ; si le port n'apparaît pas dans la liste, "
        "installez le pilote du fabricant de la puce, puis cliquez sur <b>ACTUALISER</b> dans la configuration.</p>"
        + "<h2>2.3 Premier lancement</h2>"
        + "<p>La fenêtre <b>À propos</b> s'ouvre une fois au premier démarrage, et à la première ouverture de chaque "
        "nouvelle version : elle présente le logo, la règle de versionnage, l'historique des versions et un mode "
        "d'emploi court. Le bouton <b>À PROPOS</b> du bandeau la rouvre à tout moment.</p>"
        + img("a_propos", "La fenêtre À propos : version, historique et mode d'emploi court.", "70%")
        + "<h2>2.4 Réglages mémorisés</h2>"
        + "<p>Port, vitesse, parité, hôte TCP, thème, langue et liaison du serveur esclave sont conservés d'un "
        "lancement à l'autre, dans le registre Windows de l'utilisateur "
        "(<code>HKEY_CURRENT_USER\\Software\\ModbusAI\\ModbusAI</code>). Supprimer cette clé remet l'outil à zéro.</p>"
        + "<h2>2.5 Thème et langue</h2>"
        + "<p><b>THÈME</b> bascule entre clair et sombre. Les deux sont conçus pour rester lisibles en plein jour "
        "comme en local technique : mêmes couleurs d'état, contrastes vérifiés. La liste <b>Français / English</b> "
        "change la langue ; la fenêtre se recrée, il faut donc être déconnecté et sans activité en cours.</p>"
    )


def s3_bandeau() -> str:
    return (
        h1("3", "Le bandeau : la liaison du maître")
        + img("bandeau", "Le bandeau : marque, liaison du MAÎTRE, langue, thème, À propos, Quitter.")
        + "<p>Le bandeau règle <b>la liaison du maître</b>, celle qu'utilisent les onglets MAÎTRE, SCAN RÉSEAU et "
        "DIAGNOSTIC. L'étiquette <span class='k'>MAÎTRE</span> le rappelle : le serveur esclave a sa propre liaison, "
        "dans son onglet (chapitre 8).</p>"
        + "<h2>3.1 Protocole</h2>"
        + "<p>La liste <b>RTU / TCP</b> choisit le protocole. En RTU l'outil parle sur un port série (RS-485 ou RS-232 "
        "via un adaptateur) ; en TCP il se connecte à une passerelle ou un automate par le réseau.</p>"
        + "<h2>3.2 CONFIGURER — liaison série (RTU)</h2>"
        + img("config_rtu", "Configuration de la liaison série.", "60%")
        + table(
            ["Réglage", "Signification", "Valeur habituelle"],
            [
                ["SerialPortName", "Le port COM de l'adaptateur. La liste est saisissable : un port non détecté peut être tapé. <b>ACTUALISER</b> relit la liste.", "COM3, COM7…"],
                ["BaudRate", "Vitesse du bus. Tous les équipements d'un même bus ont la même.", "9600 ou 19200"],
                ["DataBits", "Bits de données par caractère.", "8 (7 n'existe qu'en ASCII)"],
                ["StopBits", "Bits de stop. Avec parité « None », la norme demande 2 stops ; en pratique presque tout le monde met 1.", "One"],
                ["Parity", "None, Even ou Odd. Doit correspondre à l'esclave.", "None ou Even"],
                ["DTR", "Active la ligne DTR à l'ouverture. Rarement utile ; certains adaptateurs isolés en tirent leur alimentation.", "décoché"],
                ["RTS", "Pilote RTS pendant l'émission (direction du RS-485). Nécessaire seulement avec un adaptateur sans direction automatique ; sinon il provoque l'écho.", "décoché"],
                ["TimeOut", "Délai d'attente d'une réponse avant de déclarer un timeout.", "1000 ms ; 300 ms pour un scan"],
                ["Délai inter-trames", "Silence qui délimite une trame RTU. <b>Auto</b> = T3.5 normatif, avec un plancher de 5 ms pour la latence USB. Une valeur imposée sert si des réponses arrivent coupées en deux.", "Auto"],
            ],
        )
        + note(
            "astuce",
            "Le silence de fin de trame",
            "Le RTU délimite ses trames par le silence : 3,5 caractères, soit 4 ms à 9600 bauds et 2 ms à 19200. Un "
            "adaptateur USB livre les octets par blocs, parfois espacés de plus que ça : sans le plancher de 5 ms, "
            "une réponse pourrait être coupée en deux. Si le journal montre des « réponses très courtes » ou des "
            "« CRC faux » sur un bus pourtant sain, montez ce délai à 10 ou 20 ms.",
        )
        + "<h2>3.3 CONFIGURER — liaison réseau (TCP)</h2>"
        + img("config_tcp", "Configuration de la liaison TCP : hôte, port, délais, ping.", "60%")
        + table(
            ["Réglage", "Signification", "Valeur habituelle"],
            [
                ["Hôte", "Adresse IP ou nom de la passerelle / de l'automate.", "192.168.1.10"],
                ["Port", "Port TCP du serveur Modbus.", "502"],
                ["TimeOut réponse", "Délai d'attente d'une réponse Modbus.", "1000 ms"],
                ["TimeOut connexion", "Délai d'établissement de la connexion TCP.", "3000 ms"],
                ["PING", "Envoie quatre pings système vers l'hôte, sans bloquer l'interface. Premier réflexe quand rien ne répond : l'équipement est-il seulement joignable ?", ""],
                ["Connexions réseau", "Ouvre le panneau Windows (ncpa.cpl) pour vérifier l'adresse IP de votre PC et le sous-réseau.", ""],
            ],
        )
        + "<h2>3.4 CONNECTER / DÉCONNECTER</h2>"
        + "<p><b>CONNECTER</b> ouvre la liaison ; la pastille devient verte et le résumé (port et paramètres, ou "
        "hôte et port) s'affiche en vert. <b>DÉCONNECTER</b> ferme la liaison et arrête toute activité en cours "
        "(cycle, scan, campagne). Si le port est déjà utilisé par un autre rôle de l'application, le message en bas "
        "de fenêtre dit lequel.</p>"
    )


def s4_maitre() -> str:
    return (
        h1("4", "Onglet MAÎTRE")
        + img("maitre", "L'onglet MAÎTRE après la lecture de huit registres : grille, dernier échange, journal.")
        + "<h2>4.1 La barre de requête</h2>"
        + table(
            ["Champ", "Rôle"],
            [
                ["N° Esclave", "Adresse Modbus de l'équipement, de 1 à 247. L'adresse 0 est la diffusion (écritures seulement, sans réponse)."],
                ["Register", "Adresse du premier registre, <b>en base 0</b> : c'est celle qui circule sur le bus."],
                ["Longueur", "Nombre de registres ou de bits lus (125 registres ou 2000 bits au plus par requête)."],
                ["Type", "<b>1 Coil status</b> (FC01), <b>2 Input status</b> (FC02), <b>3 Holding registers</b> (FC03), <b>4 Input registers</b> (FC04). Seuls les coils et les holding registers s'écrivent."],
                ["Adresse", "Rappel de l'adresse <b>en base 1</b>, telle que la documentent la plupart des constructeurs : 400001 pour le holding 0, 300001 pour l'input 0, 000001 pour le coil 0, 100001 pour l'entrée 0."],
                ["Mode", "DECIMAL, HEXADECIMAL ou BINAIRE pour la colonne Valeur."],
            ],
        )
        + note(
            "attention",
            "Base 0 ou base 1 ?",
            "La confusion la plus fréquente sur chantier. Une documentation qui dit « registre 40001 » ou "
            "« 400001 » parle en base 1 : saisissez <b>0</b> dans Register. Une documentation qui dit « adresse 0x0000 » "
            "ou « offset 0 » parle en base 0 : saisissez ce qu'elle dit. En cas de doute, lisez les deux et comparez "
            "avec la valeur attendue — la ligne <b>Adresse</b> vous montre toujours la correspondance.",
        )
        + "<h2>4.2 Lire, écrire, répéter</h2>"
        + "<ul>"
        "<li><b>LECTURE</b> envoie la requête et remplit la grille. Le journal reçoit une ligne, le panneau « Dernier échange » se met à jour.</li>"
        "<li><b>ECRITURE</b> envoie le contenu de la colonne Valeur : double-cliquez une cellule, tapez la nouvelle valeur, puis ECRITURE. L'outil choisit le code fonction (05 / 06 pour une valeur, 15 / 16 pour plusieurs).</li>"
        "<li><b>Cyclique</b> répète la lecture à la période affichée sur le bouton <b>Période</b> (cliquez dessus pour la changer). <b>ARRET CYCLE</b> l'interrompt.</li>"
        "<li><b>Reconnexion auto</b> rouvre le port après une coupure (câble USB débranché, adaptateur qui décroche) et reprend le cycle là où il était.</li>"
        "</ul>"
        + "<h2>4.3 Formats d'affichage</h2>"
        + "<p>Le <b>Mode d'affichage</b> interprète les registres 16 bits lus : <b>MOT 16 bits</b>, <b>OCTET 8 bits</b> "
        "(chaque registre sur deux lignes, H et L), <b>MOT 32 bits</b>, <b>FLOTTANT 32 bits</b>, <b>MOT 64 bits</b>, "
        "<b>FLOTTANT 64 bits</b>, <b>CHAMP DE BITS</b>. <b>Non signé</b> change l'interprétation des entiers. "
        "<b>Inversion Octets</b> et <b>Inversion Mots</b> couvrent les quatre ordres possibles d'une valeur "
        "multi-registres, qu'on nomme d'habitude ABCD, CDAB, BADC et DCBA ; la ligne sous la liste indique l'ordre "
        "courant.</p>"
        + note(
            "astuce",
            "Un flottant qui affiche n'importe quoi",
            "Neuf fois sur dix, c'est l'ordre des mots. Cochez <b>Inversion Mots</b> : si la valeur devient plausible "
            "(une température de 21,5 plutôt que 1,2e-38), vous avez trouvé. Les automates Schneider et la plupart "
            "des passerelles sont en CDAB ; beaucoup de compteurs d'énergie en ABCD.",
        )
        + "<h2>4.4 La grille</h2>"
        + "<p>Quatre colonnes : <b>N° Registre</b>, <b>Valeur</b> (éditable, dans le format choisi), <b>Hexa</b> et "
        "<b>Binaire</b> — les mêmes bits sous trois formes, sans changer de mode, ce qui suffit pour lire un mot "
        "d'état. Quand la requête change (autre esclave, autre registre) sans nouvelle lecture, les valeurs se "
        "grisent : elles ne correspondent plus à ce qui est affiché en haut.</p>"
        + "<h2>4.5 Dernier échange et journal</h2>"
        + "<p>Le panneau de droite détaille le dernier échange : résultat, temps de réponse (fin d'émission → premier "
        "octet reçu), temps de transaction (début d'émission → dernier octet), trames émise et reçue en hexadécimal, "
        "nombre d'octets et de blocs reçus, message d'erreur.</p>"
        "<p>Le <b>journal</b> garde une ligne par échange, en colonnes fixes : heure, numéro, esclave, fonction, "
        "statut, temps, puis les trames. <b>COPIER</b> met tout dans le presse-papiers, <b>EFFACER JOURNAL</b> le vide.</p>"
        + table(
            ["Statut", "Ce que ça veut dire"],
            [
                [f"<span class='chip' style='color:{OK};border-color:{OK}'>OK</span>", "Réponse valide, CRC juste, cohérente avec la requête."],
                [f"<span class='chip' style='color:{WARN};border-color:{WARN}'>TIMEOUT</span>", "Aucun octet reçu dans le délai. Esclave absent, mauvaise adresse, A/B inversés, mauvaise vitesse, ou esclave trop lent pour le TimeOut choisi."],
                [f"<span class='chip' style='color:{ERROR};border-color:{ERROR}'>ERREUR CRC</span>", "Une trame est revenue mais son CRC est faux : bruit, collision, mauvaise vitesse ou parité."],
                [f"<span class='chip' style='color:{ERROR};border-color:{ERROR}'>EXCEPTION</span>", "L'esclave a répondu par un code d'exception (annexe 13.2). Il existe et communique : c'est la requête qui ne lui convient pas."],
                [f"<span class='chip' style='color:{ERROR};border-color:{ERROR}'>REPONSE INCOHERENTE</span>", "CRC juste, mais mauvais esclave, mauvaise fonction ou mauvaise longueur : souvent un doublon d'adresse."],
                ["<span class='chip' style='color:#7B54BE;border-color:#7B54BE'>ERREUR LIAISON</span>", "Le port a disparu ou refuse l'écriture : adaptateur débranché, pilote, concentrateur USB."],
            ],
        )
    )


def s5_espion() -> str:
    return (
        h1("5", "Onglet ESPION")
        + img("espion", "L'espion écoute un maître tiers dialoguer avec deux esclaves ; l'esclave 9, absent, apparaît « SANS RÉPONSE ».")
        + "<h2>5.1 Principe</h2>"
        + "<p>L'espion ouvre le port <b>en écoute seule</b> : l'émission est interdite au niveau du transport, RTS et "
        "DTR restent bas. On peut donc se brancher en parallèle du maître existant — la GTB, l'automate — sans rien "
        "perturber, et regarder ce qui circule : qui interroge qui, à quel rythme, qui répond, en combien de temps, "
        "et qui ne répond pas.</p>"
        + note(
            "astuce",
            "Branchement",
            "Deux fils : A sur A, B sur B, sur n'importe quel bornier du bus. <b>Ne pas ajouter de terminaison</b> sur "
            "l'adaptateur espion : le bus en a déjà deux, une troisième le charge inutilement. Sur un adaptateur à "
            "terminaison intégrée par cavalier, retirez-la.",
        )
        + "<h2>5.2 Ce qu'on voit</h2>"
        + "<ul>"
        "<li>Le tableau du haut liste les <b>transactions</b> : une requête et la réponse qui lui correspond, appariées par l'outil, avec l'heure, l'esclave, la fonction décodée, le détail (adresse, longueur, valeurs), les deux trames en hexadécimal, le temps de réponse et le résultat (OK, exception, SANS RÉPONSE, RÉPONSE CORROMPUE).</li>"
        "<li><b>Trames brutes</b> affiche à la place chaque trame telle qu'elle est arrivée, avec le silence qui l'a précédée — utile quand le décodeur ne reconnaît pas ce qui passe (protocole propriétaire, vitesse fausse).</li>"
        "<li>Le tableau du bas donne les <b>statistiques par esclave</b> : requêtes, réponses, exceptions, timeouts, CRC, taux de réussite, temps moyen et min / max.</li>"
        "<li>Les compteurs en haut à droite résument la session et listent les <b>esclaves vus</b>.</li>"
        "</ul>"
        + "<h2>5.3 Réglages et limites</h2>"
        + "<p>L'espion utilise la liaison du bandeau : vitesse, parité et délai inter-trames doivent être ceux du bus "
        "écouté. Si les trames sortent en « invalide », c'est presque toujours la vitesse. Quand une requête et sa "
        "réponse arrivent dans le même bloc USB, l'outil les sépare lui-même.</p>"
        "<p>Deux limites : l'espion n'existe qu'en <b>RTU</b> (en TCP il faudrait une recopie de port sur le "
        "commutateur), et il ne voit que ce qui passe — un esclave jamais interrogé n'apparaîtra pas.</p>"
        "<p>Depuis un maître connecté sur le même port, <b>DÉMARRER ÉCOUTE</b> ferme d'abord la liaison maître, puis "
        "ouvre le port en écoute une fois la fermeture confirmée. Tout ce que voit l'espion alimente aussi le "
        "diagnostic (source « Espion »).</p>"
    )


def s6_scan() -> str:
    rows = [[f"<b>{esc(s)}</b>", esc(SCAN_STATUS_MEANING.get(s, ""))] for s in (st.value for st in ScanStatus)]
    return (
        h1("6", "Onglet SCAN RÉSEAU")
        + img("scan", "Scan des adresses 1 à 15 : deux esclaves présents et identifiés, les absents masqués.")
        + "<h2>6.1 Paramètres</h2>"
        + "<ul>"
        "<li><b>Esclaves de … à …</b> : la plage d'adresses testées (1 à 247).</li>"
        "<li><b>Type lu, Registre, Longueur</b> : la requête de test envoyée à chaque adresse. Par défaut le holding 0, longueur 1 : presque tous les équipements y répondent, au pire par une exception — ce qui prouve tout aussi bien leur présence.</li>"
        "<li><b>Timeout par essai</b> et <b>Essais supplémentaires</b> : un scan complet coûte (adresses absentes × essais × timeout). 150 à 300 ms suffisent sur un bus sain ; montez si les esclaves sont lents.</li>"
        "<li><b>Identifier les équipements</b> : après chaque présence, l'outil demande l'identification (FC43 : fabricant, produit, version ; FC17 : identifiant et état). Beaucoup d'équipements n'implémentent ni l'un ni l'autre, la colonne reste alors vide.</li>"
        "</ul>"
        + "<h2>6.2 Liaison du scan</h2>"
        + "<ul>"
        "<li><b>Paramètres courants</b> : ceux du bandeau.</li>"
        "<li><b>Paramètres personnalisés</b> : une autre vitesse, parité ou stop, sans toucher au bandeau.</li>"
        "<li><b>Balayer plusieurs paramètres</b> : chaque combinaison cochée (vitesses × trames 8N1 / 8E1 / 8O1 / 8N2) est essayée sur toute la plage. Long, mais c'est la méthode quand on ne connaît pas les réglages d'un équipement : celui qui répond proprement dit dans quelle configuration il est.</li>"
        "</ul>"
        + "<h2>6.3 Lire les résultats</h2>"
        + table(["Statut", "Signification"], rows)
        + "<p><b>Afficher les adresses absentes</b> montre aussi les lignes sans réponse ; <b>COPIER</b> exporte le "
        "tableau. Les résultats du scan alimentent le diagnostic sous la source « Scan », exclue par défaut : une "
        "adresse absente n'est pas une panne à expliquer.</p>"
    )


def s7_diagnostic() -> str:
    phases = default_scenario(
        Request(1, FunctionCode.READ_HOLDING_REGISTERS, 0, 1), SerialSettings("COM3", baudrate=19200), 300, (2,)
    )
    phase_rows = []
    for p in phases:
        flag = " <span class='muted'>(défauts provoqués)</span>" if p.spec.source == "torture" else ""
        settings = p.spec.describe().split(", ", 2)[2] if p.spec.describe().count(", ") >= 2 else p.spec.describe()
        phase_rows.append([f"<b>{esc(p.title)}</b>{flag}", esc(p.purpose), esc(settings)])
    legend = " ".join(
        f"<span class='chip' style='color:{c};border-color:{c}'>{lo}–{hi} {esc(label)}</span>"
        for (lo, hi, label, level), c in zip(SCORE_LEGEND, (OK, WARN, ERROR), strict=False)
    )
    fiches = []
    for info in CATALOGUE.values():
        causes = "".join(f"<li>{esc(c)}</li>" for c in info.causes)
        confirm = "".join(f"<li>{esc(t)}</li>" for t in info.how_to_confirm)
        fiches.append(
            f"<div class='fiche'><h3>{esc(info.title)}</h3><p><i>{esc(info.summary)}</i></p>"
            f"<p><span class='label'>Déclenchement</span><br>{esc(info.trigger)}</p>"
            f"<p><span class='label'>Causes classiques</span></p><ul>{causes}</ul>"
            f"<p><span class='label'>Pour confirmer</span></p><ul>{confirm}</ul></div>"
        )
    report_sample = """AD - ModbusAI v1.0.0 - rapport de diagnostic Modbus
Date : 17/09/2026 08:54:34
Liaison : COM3 : 19200,8,None,One
Sources : Maître, espion et tests
Observations : 505
------------------------------------------------------------------------------
STATISTIQUES PAR ESCLAVE
Esclave  Échanges  Réussite  Timeout   CRC  Excep.  Incoh.  Liaison   Moy ms   P95 ms   Max ms   Gigue
     36       505    100.0%        0     0       0       0        0     23.0     26.1     28.1     1.1
------------------------------------------------------------------------------
HYPOTHÈSES CLASSÉES (score 0-100 : 0-49 peu probable, 50-74 probable, 75-100 très probable)
[100] Réseau sain sur la période observée (réseau)
      Aucun défaut significatif ; prolonger l'observation si le problème est intermittent.
------------------------------------------------------------------------------
TEST DE TORTURE
Phase 3/5 : Trames longues   [défauts provoqués]
   But      : Lecture de 125 éléments : révèle une ligne bruitée.
   Réglages : Trames longues, esclave 36, FC04 @0 x125, période 200 ms, 60 s
   Résultat : 264 lectures, 0.0 % de défauts (0 timeouts, 0 CRC, 0 incohérentes, 264 exceptions)
   Lecture  : L'esclave refuse cette longueur et répond une exception : c'est la limite
              de sa table, pas un défaut réseau. [...]
------------------------------------------------------------------------------
TRAMES ÉCHANGÉES (505 lignes)
    N° Heure        Source   Phase               Esc  FC Statut              ms  TX / RX
     1 08:40:00.000 test     Référence            36   4 OK                22.9  TX 24 04 00 00 00 01 31 C6  RX 24 04 02 00 FA 3D 8F
"""
    return (
        h1("7", "Onglet DIAGNOSTIC")
        + "<p>C'est le cœur de l'outil, et ce qui le distingue des utilitaires classiques. L'onglet est "
        "<b>autonome</b> : il utilise la liaison du bandeau et l'ouvre lui-même si elle est fermée.</p>"
        + img("diagnostic", "Après une campagne de six secondes : statistiques, hypothèse « Réseau sain », indices et résultats.")
        + "<h2>7.1 Cible et campagne</h2>"
        + "<p>À gauche, la <b>cible</b> : esclave, type de registre, adresse, longueur. La <b>période</b> est le "
        "rythme des lectures (200 ms par défaut). La <b>limite</b> est une durée (deux minutes par défaut — le temps "
        "qu'il faut pour voir passer un défaut intermittent) ou un nombre de lectures. <b>LANCER CAMPAGNE</b> "
        "démarre ; la barre de progression et le compte à rebours suivent ; <b>ARRÊTER</b> interrompt. Pendant la "
        "campagne, l'onglet porte une pastille et les onglets qui partagent la liaison sont verrouillés.</p>"
        + "<h2>7.2 Le test de torture</h2>"
        + "<p><b>TEST DE TORTURE</b> enchaîne plusieurs phases qui sollicitent le réseau de façons différentes, sur la "
        "durée totale choisie, répartie à parts égales. C'est la <b>comparaison</b> entre phases qui oriente : un "
        "bus qui tient la rafale mais perd des trames longues n'a pas le même problème qu'un bus qui tient les "
        "trames longues mais s'effondre en rafale.</p>"
        + table(["Phase", "Ce qu'elle cherche", "Réglages (exemple, 300 s, esclave 1)"], phase_rows)
        + note(
            "attention",
            "Défauts provoqués",
            "Trois phases dégradent volontairement la liaison ou la requête : trames longues (l'esclave peut "
            "refuser 125 registres), timeout serré (50 ms), vitesse réduite (9600 bauds, alors que l'esclave est "
            "réglé autrement). Leurs échanges sont marqués <b>défauts provoqués</b> : ils apparaissent dans le rapport "
            "et dans la trace, mais <b>n'entrent ni dans les statistiques ni dans les hypothèses</b>. Sans cela, le test "
            "fabriquerait lui-même le défaut qu'il diagnostique — et vous chercheriez une terminaison qui n'a rien "
            "fait. La phase « Alternance d'esclaves » n'apparaît que si d'autres esclaves ont déjà été vus.",
        )
        + "<p>À la fin, la zone <b>Résultats</b> donne les chiffres de chaque phase, une lecture en clair de chacune, "
        "puis une <b>orientation</b> : esclave surchargé, qualité de ligne, esclave lent, bus multi-esclaves fragile, "
        "ou réseau sain.</p>"
        + "<h2>7.3 ANALYSER</h2>"
        + "<p><b>ANALYSER</b> relit toutes les observations retenues par la liste <b>Sources</b> — par défaut le maître, "
        "l'espion et les tests normaux ; le scan et les phases à défauts provoqués sont exclus — et produit :</p>"
        + "<ul>"
        "<li>les <b>statistiques par esclave</b> : échanges, réussite (OK + exceptions, car une exception est une réponse valide), timeouts, CRC, exceptions, réponses incohérentes, erreurs de liaison, temps moyen, P95, maximum et gigue ;</li>"
        "<li>les <b>hypothèses classées</b>, chacune avec un score de 0 à 100 ;</li>"
        "<li>pour l'hypothèse sélectionnée, les <b>indices</b> qui l'ont déclenchée et les <b>tests pour départager</b>.</li>"
        "</ul>"
        + f"<p>Le score est une vraisemblance : {legend}. {esc(SCORE_EXPLANATION)}</p>"
        + "<p>Certains tests s'exécutent d'un clic (<b>LANCER</b>) : ce sont des campagnes avec la liaison modifiée — "
        "timeout doublé, 9600 bauds, parité Even, période lente… Le résultat est comparé à la référence et un "
        "verdict s'affiche : défauts disparus, réduits, inchangés ou aggravés. Les tests marqués <b>manuel</b> demandent "
        "une action sur le bus (inverser A et B, débrancher un esclave).</p>"
        + "<h2>7.4 Catalogue des hypothèses</h2>"
        + "<p>Le bouton <b>AIDE</b> affiche ce catalogue dans l'application. Chaque fiche dit ce qui déclenche "
        "l'hypothèse, ses causes classiques et comment la confirmer.</p>"
        + img("aide_hypotheses", "Le catalogue des hypothèses, généré depuis les règles du diagnostic.", "75%")
        + "<div class='catalogue'>"
        + "".join(fiches)
        + "</div>"
        + "<h2>7.5 EXPORTER TXT</h2>"
        + "<p>Le rapport texte se suffit à lui-même : on doit pouvoir le lire sans l'application, et le confier à "
        "quelqu'un qui n'était pas là — ou à Claude Code. Il contient, dans l'ordre : l'en-tête (version, date, "
        "liaison, sources), les statistiques par esclave, les hypothèses classées avec leurs indices et leurs tests, "
        "les tests exécutés, le test de torture <b>phase par phase</b> (but, réglages, chiffres, lecture), et la "
        "<b>trace de toutes les trames</b> — heure, source, phase, esclave, fonction, statut, temps, TX et RX. La case "
        "<b>Trames dans l'export</b> permet de s'en passer si seul le résumé compte.</p>"
        + f"<pre>{esc(report_sample)}</pre>"
        + note(
            "astuce",
            "Relecture par Claude Code",
            "Collez le fichier dans une conversation avec Claude Code et demandez, par exemple : « Voici le rapport "
            "de diagnostic d'un bus RS-485 qui décroche par intermittence. Analyse la trace des trames : y a-t-il un "
            "motif dans les timeouts (heure, esclave, longueur des trames, position dans le cycle) ? Que me conseilles-tu "
            "de vérifier en premier sur le bus ? » La trace complète lui donne ce que les statistiques agrégées "
            "gomment : la chronologie exacte.",
        )
        + "<p><b>EFFACER HISTORIQUE</b> vide toutes les observations de la session, les comparaisons de tests et le "
        "dernier rapport de torture. Le fichier UTF-8 avec BOM s'ouvre correctement dans le Bloc-notes.</p>"
    )


def s8_esclave() -> str:
    return (
        h1("8", "Onglet SERVEUR ESCLAVE")
        + img("esclave", "Le serveur sert les esclaves 7 et 12 ; les registres qu'un maître vient de lire sont éclairés en vert.")
        + "<h2>8.1 Sa propre liaison</h2>"
        + "<p>Le serveur ne dépend pas du bandeau : le groupe <span class='k'>LIAISON</span> choisit son protocole "
        "(RTU ou TCP) et <b>CONFIGURER</b> ouvre le même dialogue que pour le maître, avec ses propres réglages, "
        "mémorisés séparément. C'est ce qui permet de faire tourner <b>le maître et le serveur en même temps</b>, à "
        "condition qu'ils ne visent pas le même port (chapitre 9).</p>"
        + "<h2>8.2 Réglages du serveur</h2>"
        + table(
            ["Réglage", "Rôle"],
            [
                ["ESCLAVES", "Les adresses servies, par exemple <code>1-5, 10</code>. Une requête vers une autre adresse est ignorée, comme le ferait un vrai bus."],
                ["Lecture seule", "Toute écriture reçoit l'exception 04 (défaut esclave). Utile pour vérifier qu'une supervision n'écrit pas là où elle ne devrait pas."],
                ["Délai", "Attente avant chaque réponse : simule un esclave lent pour régler les timeouts d'une supervision."],
                ["Pertes", "Part des requêtes volontairement laissées sans réponse : simule des timeouts."],
                ["CRC faux", "Part des réponses émises avec un CRC volontairement faux : simule du bruit. En TCP, où il n'y a pas de CRC, c'est l'identifiant de transaction qui est altéré."],
            ],
        )
        + "<h2>8.3 Les tables</h2>"
        + "<p>Quatre tables de 65 536 éléments, comme le protocole : bobines (0xxxx), entrées discrètes (1xxxx), "
        "registres d'entrée (3xxxx), registres de maintien (4xxxx). La grille les affiche par lignes de dix, en "
        "base 1 dans les en-têtes (400001-400010). Choisissez le <b>Format</b> (décimal signé ou non, hexadécimal, "
        "binaire), le <b>Début</b> et le nombre de <b>Lignes</b>. Une cellule se modifie par double-clic. "
        "<b>REMPLIR la plage visible</b> met la <b>Valeur</b> partout dans la zone affichée, <b>RAZ table</b> remet toute "
        "la table à zéro, l'<b>animation</b> incrémente la plage visible à la période choisie pour donner de la vie "
        "à une supervision en test.</p>"
        + "<p>Ce qu'un maître vient de <b>lire ou d'écrire s'éclaire en vert</b> pendant deux secondes, puis s'éteint "
        "progressivement : on voit d'un coup d'œil ce que la GTB interroge réellement, et à quel rythme.</p>"
        + "<h2>8.4 Écoute, maîtres connectés, journal</h2>"
        + "<p>En TCP, la ligne <b>Écoute</b> ne dit pas « 0.0.0.0:502 » mais « toutes les interfaces, port 502 — "
        "joignable sur 192.168.x.y:502 » : l'adresse à donner au superviseur. <b>Maîtres connectés</b> compte les "
        "clients TCP et donne leurs adresses ; chaque connexion et déconnexion est journalisée. En RTU, le maître "
        "n'est pas identifiable, le bus ne porte aucune notion de connexion.</p>"
        "<p>Les compteurs (requêtes, réponses, écritures, exceptions, ignorées, perdues, corrompues) se colorent quand "
        "ils ne sont pas nuls. Le journal a ses propres colonnes : heure, maître, esclave, fonction, traitement, "
        "trames. Le serveur répond aussi aux identifications FC43 (fabricant ModbusAI) et FC17.</p>"
        + note(
            "astuce",
            "Se répondre à soi-même",
            "Deux adaptateurs USB/RS-485 reliés A-A et B-B, le maître sur l'un, le serveur sur l'autre : vous avez un "
            "bus complet sur votre bureau pour préparer une table d'échange ou reproduire un défaut. En TCP c'est "
            "encore plus simple : serveur sur le port 502, maître vers 127.0.0.1.",
        )
    )


def s9_arbitrage() -> str:
    return (
        h1("9", "Un port, un rôle : l'arbitrage")
        + "<p>Trois rôles peuvent tenir un port : le <b>maître</b> (onglets MAÎTRE, SCAN RÉSEAU, DIAGNOSTIC), "
        "l'<b>espion</b> et le <b>serveur esclave</b>. La règle est simple : <b>une ressource ne sert qu'à un rôle à la "
        "fois</b>, mais rien n'interdit plusieurs rôles sur des ressources différentes. Un port série est une "
        "ressource ; en TCP, se connecter à 192.168.1.10:502 et écouter sur le port 502 sont deux ressources "
        "distinctes.</p>"
        + table(
            ["Situation", "Comportement"],
            [
                ["Démarrer le serveur sur le port du maître connecté", "Refusé : « COM3 est déjà utilisé par maître : choisissez un autre port. »"],
                ["Démarrer le serveur sur un autre port", "Accepté : maître et serveur tournent ensemble, chacun avec sa pastille sur son onglet."],
                ["Démarrer l'écoute depuis un maître connecté", "L'espion utilise le port du bandeau : la liaison maître est fermée automatiquement, le port rendu, puis l'écoute démarre."],
                ["Scan, campagne ou torture en cours", "Les autres onglets qui partagent la liaison maître sont verrouillés (infobulle explicative) ; ESPION et SERVEUR ESCLAVE restent accessibles."],
                ["Changer de langue", "Demande d'être déconnecté et sans activité : la fenêtre se recrée."],
            ],
        )
        + "<p>Les onglets où quelque chose tourne portent une <b>pastille terracotta</b> sur leur icône, visible depuis "
        "n'importe quel onglet.</p>"
    )


def s10_cablage() -> str:
    return (
        h1("10", "Câblage RS-485 et bonnes pratiques")
        + "<p>Ce chapitre ne remplace pas les règles de l'art, mais rassemble ce que le diagnostic vérifie le plus "
        "souvent — et ce que ses hypothèses vous demanderont de contrôler.</p>"
        + "<h2>10.1 Les fils</h2>"
        + "<ul>"
        "<li><b>A et B</b> (aussi notés D− / D+, ou − / +) : deux fils d'une paire torsadée, en bus linéaire, sans étoile ni longue dérivation. Les noms varient d'un constructeur à l'autre : quand rien ne répond, <b>inverser A et B</b> est le premier essai, et il ne casse rien.</li>"
        "<li>Un <b>commun</b> (0 V de référence) est recommandé dès que les équipements sont alimentés séparément ; sans lui, les potentiels dérivent et les CRC faux apparaissent par temps humide.</li>"
        "<li><b>Blindage</b> relié à la terre d'un seul côté : des deux côtés, il devient une boucle de courant.</li>"
        "</ul>"
        + "<h2>10.2 Terminaisons et polarisation</h2>"
        + "<ul>"
        "<li><b>120 Ω aux deux extrémités du bus, et nulle part ailleurs.</b> Une terminaison au milieu ou une troisième sur un équipement intermédiaire charge le bus et fait tomber les niveaux. Beaucoup d'équipements ont une terminaison par cavalier ou par commutateur : vérifiez qu'une seule paire est active.</li>"
        "<li>La <b>polarisation</b> (pull-up sur B, pull-down sur A, typiquement 680 Ω) fixe l'état du bus quand personne ne parle. Elle est souvent intégrée au maître ou à l'adaptateur ; sans elle, on voit des trames « invalides » au repos et des débuts de réponse corrompus.</li>"
        "</ul>"
        + "<h2>10.3 Longueur, vitesse, nombre</h2>"
        + "<p>Le RS-485 tolère 1 200 m à 9600 bauds ; réduire la vitesse est le premier remède à un bus trop long ou "
        "trop perturbé — c'est ce que teste la phase « Vitesse réduite ». Trente-deux équipements par segment sans "
        "répéteur, moins si certains sont à charge unitaire élevée.</p>"
        + "<h2>10.4 L'adaptateur USB</h2>"
        + "<ul>"
        "<li>Préférez un adaptateur à <b>direction automatique</b> (CH340 avec commutation intégrée, FTDI avec TXDEN) : il n'a pas besoin du réglage RTS, et il ne renvoie pas l'écho de ce qu'il émet. L'hypothèse « écho » du diagnostic détecte ce cas.</li>"
        "<li>Un adaptateur <b>isolé</b> protège votre PC et supprime bien des CRC faux dus aux différences de potentiel.</li>"
        "<li>Évitez les concentrateurs USB non alimentés : ils provoquent les « erreurs de liaison » (port qui disparaît). La reconnexion automatique du maître les rattrape, mais ce n'est pas une solution.</li>"
        "</ul>"
    )


def s11_depannage() -> str:
    return (
        h1("11", "Dépannage")
        + table(
            ["Symptôme", "Cause probable", "Que faire"],
            [
                ["Windows refuse de lancer l'exécutable", "SmartScreen : fichier non signé", "Informations complémentaires → Exécuter quand même."],
                ["Le port COM n'apparaît pas, ou reconnexion en boucle", "Pilote de l'adaptateur absent, câble USB défectueux, adaptateur qui décroche", "Gestionnaire de périphériques ; installer le pilote de la puce ; ACTUALISER ; changer de port USB et de câble, éviter les concentrateurs."],
                ["Timeout sur toutes les requêtes", "A/B inversés, mauvaise vitesse ou parité, mauvaise adresse, esclave hors tension", "Inverser A et B ; SCAN RÉSEAU avec balayage sur la seule adresse attendue ; vérifier l'alimentation."],
                ["Timeouts intermittents", "Terminaison, polarisation, longueur, bruit, esclave lent", "DIAGNOSTIC : campagne de deux minutes, puis test de torture ; suivre l'orientation."],
                ["CRC faux fréquents", "Vitesse ou parité fausse, bruit, potentiels différents", "Vérifier les réglages ; commun et blindage ; adaptateur isolé ; réduire la vitesse."],
                ["Réponses incohérentes", "Deux esclaves à la même adresse", "ESPION : deux réponses à une requête ; débrancher les esclaves un par un."],
                ["Une valeur flottante est absurde", "Ordre des mots", "Inversion Mots ; puis Inversion Octets."],
                ["Exception 02 à chaque lecture", "Registre inexistant ou mauvais type", "Base 0 / base 1 ; essayer 3 Holding puis 4 Input ; longueur 1."],
                ["Exception 01", "Fonction non supportée", "Certains équipements n'acceptent que FC03 ou FC04, jamais les écritures multiples."],
                ["« COM3 est déjà utilisé par maître »", "Deux rôles visent le même port", "Choisir un autre port pour le serveur, ou déconnecter le maître."],
                ["« Serveur TCP : socket d'écoute invalide » ou écoute impossible", "Port 502 déjà pris (autre serveur, ancienne instance)", "Changer de port, ou fermer le programme qui l'occupe."],
                ["Le diagnostic dit « qualité de ligne » alors que le bus est neuf", "Défauts provoqués comptés ? Impossible depuis la 0.3.1 ; sinon, un vrai défaut", "Vérifier la source sélectionnée ; lancer une campagne longue à période lente."],
                ["L'espion ne voit que des trames « invalides »", "Vitesse ou parité différente du bus", "Régler la liaison du bandeau sur celle du bus ; augmenter le délai inter-trames."],
            ],
        )
    )


def s12_mcp() -> str:
    """Chapitre engendré depuis le catalogue réel : la liste ne peut pas mentir."""
    from modbusai.mcp.service import ModbusService
    from modbusai.mcp.tools import build_tools

    families = [
        ("Liaison", ("list_ports", "connect", "disconnect", "status")),
        ("Échanges", ("read", "write", "identify")),
        ("Observation", ("scan", "sniff", "campaign", "stress_test", "job_status", "job_stop")),
        ("Diagnostic", ("analyse", "run_test", "report", "clear_history", "catalogue")),
        ("Serveur esclave", ("slave_start", "slave_stop", "slave_set", "slave_table")),
    ]
    catalogue = {t.name: t for t in build_tools(ModbusService(allow_write=True))}
    rows = []
    for family, names in families:
        for name in names:
            tool = catalogue[name]
            summary = tool.description.split(".")[0] + "."
            mark = " <b>(écriture)</b>" if tool.writes else ""
            # La famille est répétée sur chaque ligne : le tableau peut changer
            # de page, une cellule vide en haut d'une page ne dirait plus rien.
            rows.append([esc(family), f"<code>{esc(name)}</code>{mark}", esc(summary)])

    guards = [
        ["Lecture seule par défaut", "Sans <code>--ecriture</code>, les outils qui écrivent ne sont pas proposés à l'assistant. Un outil absent vaut mieux qu'un outil qui refuse."],
        ["Écoute locale par défaut", "En HTTP, le serveur se lie à 127.0.0.1 tant qu'on ne demande pas autre chose, et signale une écoute exposée sans jeton."],
        ["Jeton partagé", "<code>--jeton</code> exige un en-tête <code>Authorization: Bearer</code> à chaque requête."],
        ["Origine refusée", "Une requête portant un en-tête <code>Origin</code> étranger est rejetée : parade au détournement DNS depuis un navigateur."],
        ["Un port, un rôle", "Le serveur obéit au même arbitrage que la fenêtre (chapitre 9) : il refuse un port déjà tenu, en nommant ce qui l'occupe."],
    ]

    return (
        h1("12", "Serveur MCP : diagnostiquer avec un assistant")
        + "<p>Le rapport texte du chapitre 7 se relit avec un assistant, mais il faut l'exporter, le coller, puis "
        "revenir dans l'application pour exécuter le test proposé. Le <b>serveur MCP</b> supprime ces allers-retours : "
        "l'assistant appelle lui-même les outils du bus. Il lit un registre, scanne les adresses, lance une campagne, "
        "lit les hypothèses, puis enchaîne le test qui les départage, sans quitter la conversation.</p>"
        + "<p>C'est un programme distinct de l'application, et facultatif. Il ne remplace pas la fenêtre : il l'ouvre "
        "à un autre opérateur.</p>"
        + "<h2>12.1 Où l'installer</h2>"
        + "<p>Le serveur tourne sur <b>la machine branchée au bus</b> : celle qui porte l'adaptateur USB / RS-485, ou "
        "celle qui atteint la passerelle Modbus TCP. Il tient dans un second exécutable, "
        "<code>AD-ModbusAI-MCP_v" + esc(__version__) + ".exe</code>, livré à côté de l'application. Deux fichiers "
        "et non un seul parce qu'un exécutable fenêtré n'a, sous Windows, ni entrée ni sortie standard — or c'est "
        "précisément par là que le protocole dialogue.</p>"
        + "<h2>12.2 Mode local</h2>"
        + "<p>Le cas le plus simple, et le plus sûr : le client lance le serveur lui-même, lui parle par des tubes, et "
        "l'arrête en fin de session. Rien n'écoute sur le réseau. Avec Claude Code :</p>"
        + "<pre>claude mcp add modbusai -- \"C:\\Outils\\AD-ModbusAI-MCP_v" + esc(__version__) + ".exe\"</pre>"
        + "<p>Ajoutez <code>--ecriture</code> à la fin de la ligne pour autoriser l'écriture sur le bus et le serveur "
        "esclave simulé. Vérification : demandez « quels ports série vois-tu ? ».</p>"
        + "<h2>12.3 Mode à distance</h2>"
        + "<p>Le poste reste sur site, branché au bus ; vous diagnostiquez depuis le bureau. Le serveur écoute alors "
        "en HTTP, <b>sur son adresse de réseau privé uniquement</b> — Tailscale, VPN d'entreprise, réseau d'atelier :</p>"
        + "<pre>AD-ModbusAI-MCP_v" + esc(__version__) + ".exe --http 100.87.1.4:8765 --jeton MonJetonLong</pre>"
        + "<p>Puis, depuis la machine distante :</p>"
        + "<pre>claude mcp add --transport http modbusai http://100.87.1.4:8765/mcp \\\n"
        "  --header \"Authorization: Bearer MonJetonLong\"</pre>"
        + note(
            "attention",
            "Ce serveur parle à des automates",
            "Ne l'exposez jamais sur l'internet ouvert. Le réseau qui le porte doit être privé, et l'assistant doit "
            "tourner sur une machine de ce réseau : une session dans un navigateur s'exécute dans le nuage et ne "
            "voit pas votre réseau privé.",
        )
        + "<h2>12.4 Les garde-fous</h2>"
        + table(["Garde-fou", "Ce qu'il fait"], guards)
        + "<h2>12.5 Les outils</h2>"
        + "<p>Adresses en base 0, comme partout ailleurs. Les outils marqués « écriture » n'apparaissent que si le "
        "serveur a été lancé avec <code>--ecriture</code>.</p>"
        + table(["Famille", "Outil", "Ce qu'il fait"], rows, "compact")
        + "<h2>12.6 Les travaux longs</h2>"
        + "<p>Un scan, une campagne, un test de torture ou une écoute durent des minutes. Ces outils rendent la main "
        "tout de suite et le travail se poursuit en fond ; l'argument <code>wait_s</code> permet d'attendre la fin "
        "quand elle est proche. Pendant ce temps, les autres outils du bus sont refusés en nommant ce qui occupe la "
        "liaison, et <code>job_stop</code> interrompt en rendant le résultat partiel.</p>"
        + "<h2>12.7 Une session type</h2>"
        + "<ol>"
        + "<li><code>connect</code> avec le port et la vitesse du bus.</li>"
        + "<li><code>scan</code> sur 1 à 32 pour savoir qui répond.</li>"
        + "<li><code>read</code> sur l'esclave visé ; format <code>flottant32</code> si la valeur affichée est absurde, "
        "les quatre ordres de mots sont alors montrés côte à côte.</li>"
        + "<li><code>campaign</code> de deux minutes sur le registre suspect.</li>"
        + "<li><code>analyse</code> : les hypothèses arrivent classées, avec leurs tests.</li>"
        + "<li><code>run_test</code> avec la clé du test proposé : l'outil relance une campagne aux réglages modifiés "
        "et donne le verdict, défauts disparus, réduits, inchangés ou aggravés. Un test qui demande une action "
        "sur le bus est refusé en disant quoi faire.</li>"
        + "<li><code>report</code> pour garder la trace, à archiver avec le compte rendu d'intervention.</li>"
        + "</ol>"
        + note(
            "astuce",
            "Ce que l'assistant sait déjà",
            "Le serveur lui donne ses consignes à la connexion : adresses en base 0, une exception Modbus est une "
            "réponse valide et non une panne, un port ne sert qu'à un rôle à la fois, et les phases à défauts "
            "provoqués sortent des statistiques. Ces règles viennent du code, pas d'une copie : elles ne peuvent pas "
            "diverger de ce manuel.",
        )
    )


def s13_annexes() -> str:
    fn_rows = []
    for f in FunctionCode:
        label, usage = FUNCTION_NAMES.get(f.name, (f.name, ""))
        fn_rows.append([f"<b>{int(f):02d}</b> (0x{int(f):02X})", esc(label), esc(usage)])
    exc_rows = [[f"<b>{k:02X}</b>", esc(v)] for k, v in EXCEPTION_LABELS.items()]
    glossary = [
        ["ADU / PDU", "La trame complète (adresse + PDU + CRC en RTU, en-tête MBAP + PDU en TCP) et sa partie utile (code fonction + données)."],
        ["Base 0 / base 1", "Adresse telle qu'elle circule sur le bus (0) ou telle que la documentent les constructeurs (400001). L'outil affiche les deux."],
        ["CRC16", "Contrôle d'intégrité des trames RTU, polynôme 0xA001. Un CRC faux = trame altérée entre l'émetteur et vous."],
        ["Gigue", "Écart-type des temps de réponse : un esclave régulier a une gigue faible ; une gigue forte signe une charge variable ou des retransmissions."],
        ["MBAP", "En-tête Modbus TCP : identifiant de transaction, protocole, longueur, identifiant d'unité. Pas de CRC : TCP s'en charge."],
        ["P95", "Temps de réponse en dessous duquel tombent 95 % des échanges : plus parlant que le maximum, qu'un seul incident suffit à gonfler."],
        ["T1.5 / T3.5", "Silences normatifs du RTU : au-delà de 1,5 caractère la trame est considérée coupée, au-delà de 3,5 elle est finie. À 19200 bauds : 0,86 ms et 2 ms."],
        ["Temps de réponse", "Fin d'émission de la requête → premier octet de la réponse. Le temps de transaction va du premier octet émis au dernier reçu."],
        ["Timeout", "Délai au bout duquel le maître renonce à attendre. Un timeout n'est pas une erreur de l'esclave : c'est une absence de réponse, quelle qu'en soit la cause."],
    ]
    return (
        h1("13", "Annexes")
        + "<h2>13.1 Codes fonction</h2>"
        + table(["Code", "Fonction", "Où dans l'outil"], fn_rows, "compact")
        + "<h2>13.2 Codes d'exception</h2>"
        + "<p>Une exception est une <b>réponse valide</b> : l'esclave existe, communique, et refuse la requête. Le "
        "diagnostic la compte comme telle.</p>"
        + table(["Code", "Signification"], exc_rows, "compact")
        + "<h2>13.3 Glossaire</h2>"
        + table(["Terme", "Définition"], glossary, "compact")
        + "<h2>13.4 Règle de versionnage</h2>"
        + "<p>Numéro X.Y.Z. Les versions 0.1 à 0.3 ont porté les trois phases de développement ; la 1.0.0 est la "
        "première version complète, validée sur chantier. Ensuite : X change pour une rupture (architecture ou format "
        "des données), Y pour une nouvelle fonction, Z pour une correction. L'historique complet est dans "
        "l'À propos, onglet Historique.</p>"
        + f"<p class='muted'>AD - ModbusAI {esc(__version__)} — fait avec CC par {esc(AUTHOR)}.</p>"
    )


def build_html() -> str:
    body = (
        cover()
        + toc()
        + s1_presentation()
        + s2_installation()
        + s3_bandeau()
        + s4_maitre()
        + s5_espion()
        + s6_scan()
        + s7_diagnostic()
        + s8_esclave()
        + s9_arbitrage()
        + s10_cablage()
        + s11_depannage()
        + s12_mcp()
        + s13_annexes()
    )
    return f"<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'><title>{esc(APP_NAME)} — Mode d'emploi</title><style>{CSS}</style></head><body>{body}</body></html>"


# --------------------------------------------------------------------- rendu
def find_chromium() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"), reverse=True):
        return str(candidate)
    return None


def render_pdf(html_path: Path, pdf_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        raise SystemExit("Chromium introuvable : ouvrez manuel.html dans un navigateur et imprimez en PDF.")
    subprocess.run(
        [
            chromium,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )


def stamp_footer(pdf_path: Path) -> int:
    """Pied de page et numéros : Chromium ne les pose pas en ligne de commande."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    total = doc.page_count
    for index, page in enumerate(doc):
        if index == 0:
            continue  # pas sur la couverture
        rect = page.rect
        y = rect.height - 30
        page.insert_text((48, y), f"{APP_NAME} {__version__} — Mode d'emploi", fontsize=8, color=(0.47, 0.44, 0.40))
        label = f"{index + 1} / {total}"
        width = pymupdf.get_text_length(label, fontsize=8)
        page.insert_text((rect.width - 48 - width, y), label, fontsize=8, color=(0.47, 0.44, 0.40))
    doc.set_metadata(
        {
            "title": f"{APP_NAME} — Mode d'emploi {__version__}",
            "author": AUTHOR,
            "subject": "Outil de diagnostic Modbus RTU / RS-485 et TCP",
            "creator": "docs/manuel/build_manuel.py",
        }
    )
    tmp = pdf_path.with_suffix(".tmp.pdf")
    doc.save(str(tmp), garbage=3, deflate=True)
    doc.close()
    tmp.replace(pdf_path)
    return total


def main() -> None:
    missing = [n for n in ("maitre", "espion", "scan", "diagnostic", "esclave", "bandeau") if not (IMG / f"{n}.png").exists()]
    if missing:
        raise SystemExit(f"Captures manquantes {missing} : lancez d'abord docs/manuel/captures.py")
    HTML_OUT.write_text(build_html(), encoding="utf-8")
    render_pdf(HTML_OUT, PDF_OUT)
    pages = stamp_footer(PDF_OUT)
    print(f"{PDF_OUT.relative_to(DOCS.parent)} : {pages} pages, {PDF_OUT.stat().st_size / 1e6:.1f} Mo")


if __name__ == "__main__":
    sys.exit(main())
