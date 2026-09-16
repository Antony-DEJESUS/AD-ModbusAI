# ModbusAI

Outil de diagnostic Modbus RTU / RS-485 pour le chantier (GTB, industriel).
Cinq onglets, un seul port série :

| Onglet | Rôle |
|---|---|
| MAÎTRE | lecture / écriture façon Modbus Doctor, cyclique, reconnexion auto, formats 8 à 64 bits et flottants |
| ESPION | écoute passive du bus (aucune émission) : requêtes, réponses, temps, trames brutes, stats par esclave |
| SCAN RÉSEAU | recherche des esclaves présents, identification FC43 / FC17, balayage des vitesses et parités |
| DIAGNOSTIC | statistiques par esclave, hypothèses de panne classées, tests pour les départager |
| SERVEUR ESCLAVE | simulateur d'esclave façon Mod_RSsim, avec injection de défauts |

Version : voir la barre de titre (`modbusai/__init__.py`) et `CHANGELOG.md`.

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

Résultat : `dist\ModbusAI_v<version>.exe`, sans installateur.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

Sous Windows, les tests sur pseudo-terminal et bus virtuel sont ignorés ; les
autres (CRC, trames, codec, framer, maître simulé, analyse, serveur esclave)
tournent partout.

## Utilisation rapide

1. `CONFIGURATION` : port COM (détection automatique), vitesse, parité, bits,
   DTR / RTS, timeout, délai inter-trames (0 = automatique).
2. `CONNEXION` ouvre le port en maître. Les onglets Maître, Scan réseau et
   Diagnostic utilisent cette liaison.
3. `ESPION` et `SERVEUR ESCLAVE` ont leur propre bouton de démarrage : ils
   prennent le port (la liaison maître est fermée) et le rendent à l'arrêt.
   Cliquer ensuite sur `CONNEXION` pour repasser en maître.
4. Diagnostic : faire des lectures (idéalement en cyclique), écouter le bus ou
   scanner, puis `ANALYSER`. Chaque hypothèse liste ses indices et des tests ;
   `LANCER` exécute une campagne de lectures avec les paramètres modifiés et
   compare le taux de défauts à la référence.
5. `THÈME` bascule clair / sombre.

Architecture et conventions : voir `CLAUDE.md`.
