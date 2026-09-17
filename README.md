# AD - ModbusAI

Outil de diagnostic Modbus RTU / RS-485 et Modbus TCP pour le chantier (GTB,
industriel), en français ou en anglais. Cinq onglets, un seul port à la fois :
un port ne sert qu'à un rôle à la fois, mais maître et serveur esclave peuvent
tourner en parallèle sur deux ports différents.

| Onglet | Rôle |
|---|---|
| MAÎTRE | lecture / écriture façon Modbus Doctor, cyclique, reconnexion auto, formats 8 à 64 bits et flottants |
| ESPION | écoute passive du bus RS-485 (aucune émission) : requêtes, réponses, temps, trames brutes, stats par esclave |
| SCAN RÉSEAU | recherche des esclaves présents, identification FC43 / FC17, liaison au choix ou balayage des vitesses et parités |
| DIAGNOSTIC | campagnes minutées, test de torture expliqué phase par phase, statistiques, hypothèses classées avec légende et aide, tests pour départager, export txt avec toutes les trames |
| SERVEUR ESCLAVE | simulateur d'esclave façon Mod_RSsim (RTU ou TCP) sur sa propre liaison, injection de défauts, maîtres connectés, cellules lues ou écrites éclairées en vert |

Au premier démarrage (et à la première ouverture de chaque version), la pop-up
À propos présente l'outil et son historique ; le bouton À PROPOS la rouvre.

Habillage : charte AD (gris chauds et terracotta), thème sombre et
thème clair, définie une seule fois dans `modbusai/ui/palette.py`.

Version : barre de titre et pop-up À propos (`modbusai/__init__.py`), historique dans `CHANGELOG.md`.

## Lancer depuis les sources

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Construire l'exécutable unique

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller packaging\modbusai.spec
```

Résultat : `dist\AD-ModbusAI_v<version>.exe`, sans installateur, avec le logo AD
en icône.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

Sous Windows, les tests sur pseudo-terminal et bus virtuel sont ignorés ; les
autres (CRC, trames RTU et TCP, codec, framer, maître simulé, analyse,
diagnostic, torture, rapport, serveur esclave, rôles, traductions) tournent
partout.

## Utilisation rapide

1. Bandeau : choisir RTU ou TCP, puis `CONFIGURATION` (port COM, vitesse,
   parité, DTR / RTS, timeout, délai inter-trames ; ou hôte, port, PING,
   connexions réseau Windows). `CONNEXION` ouvre la liaison en maître.
2. MAÎTRE : esclave, registre (base 0), longueur, type ; `LECTURE` remplit la
   grille, `ECRITURE` envoie les valeurs modifiées. `Cyclique` + `…` (période).
3. DIAGNOSTIC : choisir la cible, `LANCER CAMPAGNE` (durée ou nombre) ou
   `TEST DE TORTURE` ; la liaison s'ouvre toute seule si besoin. `ANALYSER`
   classe les hypothèses (légende des scores à côté du titre), `LANCER` sur un
   test exécute une campagne comparée à la référence, `EXPORTER TXT` enregistre
   le rapport, `AIDE` décrit toutes les hypothèses.
4. ESPION et SERVEUR ESCLAVE ont leur propre bouton de démarrage : ils prennent
   le port et grisent les autres onglets jusqu'à l'arrêt.
5. `THÈME` bascule clair / sombre ; la liste Français / English change la
   langue (port libre requis).

Architecture et conventions : voir `CLAUDE.md`. Plan et compte rendu de la
phase 3 : `docs/PHASE3_PLAN.md`, `docs/PHASE3_COMPTE_RENDU.md`.
