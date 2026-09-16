# ModbusAI

Outil de diagnostic Modbus RTU / RS-485 pour le chantier (GTB, industriel).
Phase 1 : lecture / écriture de registres façon Modbus Doctor, avec une couche
transport qui horodate et conserve chaque trame brute pour les phases suivantes
(diagnostic de la qualité de liaison, mode espion).

## Lancer depuis les sources

```bat
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Construire l'exécutable unique

```bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller packaging\modbusai.spec
```

Résultat : `dist\ModbusAI_v0.1.0.exe`, sans installateur.

## Tests

```bat
.venv\Scripts\python -m pytest
```

Les tests d'intégration sur pseudo-terminal ne tournent que sous Linux ; les
autres (CRC, trames, codec, framer, maître sur liaison simulée) tournent partout.

## Utilisation

1. `CONFIGURATION` : port COM (détection automatique), vitesse, parité, bits de
   données et de stop, DTR / RTS, timeout, délai inter-trames (0 = automatique).
2. `CONNEXION`.
3. Renseigner esclave, registre (base 0), longueur, type ; l'adresse au format
   Modbus Doctor (`400001`) s'affiche à côté.
4. `LECTURE` remplit la grille. Modifier une valeur dans la grille puis
   `ECRITURE` envoie FC 05 / 06 (longueur 1) ou FC 15 / 16.
5. `Cyclique` + `…` (période) puis `LECTURE` lance la lecture périodique ;
   `ARRET CYCLE` l'arrête.

La console du bas trace chaque échange : heure, trame émise, trame reçue, temps
de réponse, résultat (OK, timeout, CRC, exception Modbus, réponse incohérente).

Architecture et conventions : voir `CLAUDE.md`.
