# Phase 3 (v0.3.0) — cahier des charges et décisions

Liste demandée par Antony le 16/09/2026, à réaliser en autonomie. Ce fichier est
la référence : si la session repart d'un conteneur neuf, tout repartir d'ici.

## Demande d'origine (verbatim)

1. Ajout d'un timer cyclique pour dire que le test se fait pendant deux minutes.
2. Possibilité de faire du RTU et du TCP.
3. Export des statistiques de lecture en txt.
4. Test préprogrammé qui torture le réseau pour identifier le souci.
5. Sûrement revoir la logique : l'onglet diagnostic sert pour faire tous les
   tests cycliques et n'est donc pas dépendant des autres onglets.
6. Mettre le logo AD.
7. Mettre une écriture « Fait avec CC par Antony DE JESUS », cliquable, qui
   renvoie vers une pop-up avec le logo AD, l'explication du versionning et
   dans le futur le mode d'emploi.
8. Faire une version anglais / français. Par défaut FR.
9. Graphiquement le rendre joli, dans les styles Apple, même si ça reste un
   outil industriel.
10. Faire des blocages : en mode serveur, pas possible d'aller ailleurs, et
    inversement. Tester les blocages.
11. Dans scan réseau, pouvoir choisir les paramètres de com, voire tous les
    paramètres.
12. Possibilité en TCP de faire un ping et un bouton qui appelle le réseau
    type « ncpa.cpl ».
13. Expliquer avec une légende les scores de diagnostic.
14. Sur tous les diagnostics de la base, un bouton aide qui ouvre une pop-up et
    retrace toutes les probabilités possibles.

## Ordre d'exécution retenu

Du plus structurant au plus cosmétique, pour que chaque étape soit commitée et
testée même si le temps manque :

1. TCP (2, 12) — touche la couche transport, donc à faire avant tout le reste.
2. Diagnostic autonome + campagnes par durée (5, 1, 4) — nouvelle logique.
3. Scan réseau paramétrable (11).
4. Export txt (3).
5. Blocages de rôle + tests (10).
6. Internationalisation FR/EN (8).
7. Habillage graphique, logo, pop-up À propos, légende, aide (9, 6, 7, 13, 14).

## Décisions prises seul (à valider par Antony)

### TCP (point 2)

- Nouveau `transport/tcp_link.py` exposant la même interface que `SerialLink`
  (`open/close/send/receive/read_loop`, `state`, `counters`, `allow_tx`), donc
  `RtuMaster`, `analysis` et l'interface ne changent pas.
- Encapsulation MBAP dans `modbus/mbap.py` : identifiant de transaction,
  protocole 0, longueur, identifiant d'unité. Le CRC RTU est remplacé par la
  longueur MBAP ; `ExchangeStatus.CRC_ERROR` devient inatteignable en TCP, une
  trame mal formée donne `BAD_RESPONSE`.
- `SerialSettings` reste pour la liaison série. Nouveau `TcpSettings`
  (hôte, port 502, unit id par défaut, timeout, temps de connexion) et un
  `LinkSettings = SerialSettings | TcpSettings` avec `summary()` commun.
- Le protocole est choisi par la liste déroulante existante du bandeau
  (aujourd'hui figée sur RTU) : RTU, TCP. Le dialogue de configuration
  affiche les champs série ou réseau selon le choix.
- Mode espion en TCP : écoute impossible sans matériel dédié (port mirroring).
  Le bouton est donc désactivé en TCP avec une info-bulle qui l'explique,
  plutôt que de laisser croire que ça marche.
- Serveur esclave en TCP : un serveur TCP acceptant plusieurs connexions, sur
  le port choisi. C'est la partie la plus lourde ; si le temps manque, elle est
  reportée et le serveur reste RTU (dit explicitement dans le compte rendu).

### Ping et accès réseau Windows (point 12)

- Ping par `subprocess` sur la commande système (`ping -n 4` sous Windows,
  `ping -c 4` ailleurs), sortie affichée dans une pop-up, jamais bloquante
  pour l'interface (QThread).
- Bouton « Connexions réseau » lançant `ncpa.cpl` via `os.startfile` sous
  Windows ; sur les autres systèmes, le bouton est désactivé avec une
  info-bulle. Aucune commande construite à partir d'une saisie utilisateur.

### Diagnostic autonome (point 5)

- L'onglet Diagnostic possède sa propre cible (protocole, paramètres, esclave,
  fonction, registre, longueur, période, durée) et lance ses campagnes sans
  dépendre de l'onglet Maître. Il prend le port comme un rôle à part entière
  (`Role.DIAGNOSTIC`), au même titre que maître, espion et esclave.
- Les statistiques restent alimentées par toutes les sources (maître, espion,
  scan, test) : l'analyse ne change pas, seule l'origine des campagnes change.

### Campagnes par durée (point 1)

- Une campagne se définit par une durée (par défaut 2 minutes) ou par un nombre
  de lectures, au choix. Barre de progression et compte à rebours affichés.
- `SuggestedTest` gagne `duration_s` ; `count` devient une limite haute.

### Test de torture (point 4)

- Nouveau module `analysis/stress.py` : un scénario est une suite de phases,
  chacune avec ses paramètres (période, longueur de lecture, timeout, vitesse,
  parité, esclaves visés). Scénario par défaut « torture réseau » :
  1. référence : période lente, lecture courte ;
  2. rafale : période minimale, lecture courte ;
  3. trames longues : lecture de 125 registres ;
  4. tous esclaves en alternance (si plusieurs connus) ;
  5. timeout serré, puis retour au timeout normal ;
  6. si la vitesse est supérieure à 9600, une phase à vitesse réduite.
- Chaque phase produit ses propres `SlaveStats` ; le rapport compare les phases
  entre elles et conclut (par exemple : « dégradation nette en rafale, pas en
  trames longues » oriente vers la charge de l'esclave plutôt que la ligne).
- Durée totale par défaut : 5 minutes, ajustable.

### Export (point 3)

- `analysis/report.py` produit un rapport texte : entête (date, outil et
  version, liaison), statistiques par esclave, phases de torture le cas
  échéant, hypothèses classées avec indices, résultats des tests exécutés.
- Bouton « EXPORTER TXT » sur l'onglet Diagnostic, boîte de dialogue de
  sauvegarde, nom proposé `ModbusAI_diagnostic_AAAAMMJJ_HHMM.txt`, encodage
  UTF-8 avec BOM pour que le Bloc-notes Windows affiche correctement les
  accents.

### Blocages de rôle (point 10)

- Machine d'état explicite dans `ui/roles.py` : un seul rôle actif, transitions
  autorisées décrites dans une table testable sans interface.
- Quand un rôle occupe le port, les onglets des autres rôles sont désactivés
  (onglet grisé, pas seulement le bouton) avec une info-bulle disant quoi
  arrêter. Le bandeau CONNEXION est désactivé de la même façon.
- Tests unitaires sur la table de transitions, plus un test d'interface qui
  vérifie l'état activé/désactivé des onglets pour chaque rôle.

### Internationalisation (point 8)

- `ui/i18n.py` avec un dictionnaire français/anglais et une fonction `tr()`.
  Pas de QTranslator ni de fichiers .ts : la chaîne de compilation
  (pyside6-lupdate, lrelease) alourdirait le packaging pour deux langues.
- Le français est la source, l'anglais la traduction. Une clé absente retombe
  sur le français plutôt que d'afficher la clé.
- Sélecteur dans le bandeau (FR / EN), mémorisé dans QSettings, appliqué sans
  redémarrage via une méthode `retranslate()` par page.
- Test : vérifier qu'aucune clé anglaise ne manque.

### Habillage (points 9, 6, 7, 13, 14)

- Feuille de style QSS commune aux deux thèmes : coins arrondis 6 px, marges
  aérées, bordures discrètes, survol des boutons, tableaux sans quadrillage
  lourd, en-têtes sobres, police système (Segoe UI Variable sous Windows).
  Les couleurs continuent de venir de la palette (aucun noir ni blanc en dur).
- Logo AD dans le bandeau (variante blanche en thème sombre) et dans la
  pop-up À propos ; icône de fenêtre et icône de l'exécutable.
- Ligne « Fait avec Claude Code par Antony DE JESUS » cliquable en bas à
  droite, ouvrant la pop-up À propos : logo, version, règle de versionnage
  (X.Y.Z, phase N = 0.N.x), historique des versions repris du CHANGELOG, et un
  onglet « Mode d'emploi » aujourd'hui réduit à l'essentiel, prévu pour être
  étoffé.
- Légende des scores de diagnostic : barre de couleur avec seuils (0-49 peu
  probable, 50-74 probable, 75-100 très probable) et explication de ce que
  mesure le score.
- Bouton « AIDE » sur l'onglet Diagnostic ouvrant un catalogue de toutes les
  hypothèses de la base : pour chacune, ce qui la déclenche, les indices
  typiques, les causes physiques et les tests recommandés. Alimenté par les
  règles elles-mêmes (une seule source de vérité), pas par du texte recopié.

## Contraintes à respecter

- Couches : `transport` et `modbus` restent sans Qt ; `analysis` reste testable
  sans matériel ; `ui` ne contient pas de logique métier. Le TCP ne doit rien
  casser de cette séparation.
- Aucun noir ni blanc codé en dur dans les widgets.
- Chaque étape : `ruff format`, `ruff check`, `pytest` verts, commit séparé,
  push sur `claude/wonderful-wozniak-1tzzzi`.
- Version 0.3.0 dans `modbusai/__init__.py` et entrée dans `CHANGELOG.md`.
- Mise à jour de `CLAUDE.md` (architecture) et `README.md` (usage).
- Compte rendu final dans `docs/PHASE3_COMPTE_RENDU.md` : fait, choix tranchés,
  reste à faire, points à valider.

## Non fait volontairement (sauf demande)

- Exports PDF ou JSON (seul le txt est demandé).
- Sniffer TCP (nécessite un matériel de recopie de port).
- Mode d'emploi complet (structure posée, contenu à étoffer plus tard).
