# AD - ModbusAI

Outil de diagnostic Modbus RTU / RS-485 et Modbus TCP pour le chantier (GTB,
industriel), en français ou en anglais. Cinq onglets, et une règle : une
ressource ne sert qu'à un rôle à la fois, mais maître et serveur esclave
tournent en parallèle sur deux ports différents.

| Onglet | Rôle |
|---|---|
| MAÎTRE | lecture / écriture façon Modbus Doctor, cyclique, reconnexion auto, formats 8 à 64 bits et flottants |
| ESPION | écoute passive du bus RS-485 (aucune émission) : requêtes, réponses, temps, trames brutes, stats par esclave |
| SCAN RÉSEAU | recherche des esclaves présents, identification FC43 / FC17, liaison au choix ou balayage des vitesses et parités |
| DIAGNOSTIC | campagnes minutées, test de torture expliqué phase par phase, statistiques, hypothèses classées avec légende et aide, tests pour départager, export txt avec toutes les trames |
| SERVEUR ESCLAVE | simulateur d'esclave façon Mod_RSsim (RTU ou TCP) sur sa propre liaison, injection de défauts, maîtres connectés, cellules lues ou écrites éclairées en vert |

Depuis la 1.1.0, un **serveur MCP** livré à côté expose le bus comme un jeu
d'outils qu'un assistant appelle lui-même : il lit un registre, scanne les
adresses, lance une campagne, lit les hypothèses, puis enchaîne le test qui les
départage, sans quitter la conversation. En local, ou à distance par un réseau
privé de type Tailscale. Mise en service : [`docs/mcp.md`](docs/mcp.md).

Au premier démarrage (et à la première ouverture de chaque version), la pop-up
À propos présente l'outil et son historique ; le bouton À PROPOS la rouvre.

Habillage : charte AD (gris chauds et terracotta), thème sombre et
thème clair, définie une seule fois dans `modbusai/ui/palette.py`.

Version 1.1.0. Les trois phases de l'application sont livrées et validées sur
chantier ; le serveur MCP s'y ajoute. Mode d'emploi complet en PDF dans
[`docs/`](docs/).

Version : barre de titre et pop-up À propos (`modbusai/__init__.py`), historique dans `CHANGELOG.md`.

## Lancer depuis les sources

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Construire les exécutables

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller packaging\modbusai.spec
```

Résultat, sans installateur et avec le logo AD en icône :

| Fichier | Rôle |
|---|---|
| `dist\AD-ModbusAI_v<version>.exe` | l'application, fenêtrée |
| `dist\AD-ModbusAI-MCP_v<version>.exe` | le serveur MCP, en console |

Deux fichiers parce qu'un exécutable fenêtré n'a, sous Windows, ni entrée ni
sortie standard : c'est précisément par là que le protocole MCP dialogue. Le
serveur n'embarque aucune bibliothèque graphique et pèse donc bien moins.

## Lancer le serveur MCP

```powershell
.venv\Scripts\python -m modbusai.mcp              # entrée standard, lecture seule
.venv\Scripts\python -m modbusai.mcp --ecriture   # écriture autorisée
.venv\Scripts\python -m modbusai.mcp --http 100.87.1.4:8765 --jeton MonJeton
```

Puis, côté client : `claude mcp add modbusai -- <chemin de l'exécutable>`.

## Publier une version

Tout est automatique à partir du tag : la CI vérifie que le tag porte bien la
version de `modbusai/__init__.py`, joue lint et tests, construit les deux
exécutables Windows, vérifie que le serveur MCP répond, puis crée la release
avec les exécutables, le mode d'emploi PDF et la section du CHANGELOG en corps.

```powershell
git tag v1.1.0
git push origin v1.1.0
```

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
4. ESPION et SERVEUR ESCLAVE ont leur propre bouton de démarrage. Une
   ressource ne sert qu'à un rôle à la fois, mais deux rôles tournent en
   parallèle sur deux ports différents ; seuls les onglets qui partagent la
   liaison du maître se verrouillent pendant un scan, une campagne ou une
   torture.
5. `THÈME` bascule clair / sombre ; la liste Français / English change la
   langue (port libre requis).

Architecture et conventions : voir `CLAUDE.md`. Plan et compte rendu de la
phase 3 : `docs/PHASE3_PLAN.md`, `docs/PHASE3_COMPTE_RENDU.md`.
