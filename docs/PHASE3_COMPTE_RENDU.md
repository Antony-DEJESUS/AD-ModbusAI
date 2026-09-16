# Phase 3 (v0.3.0) — compte rendu

Travail réalisé en autonomie le 16/09/2026 entre 16h05 et 17h UTC, à partir de
`docs/PHASE3_PLAN.md`. Tout est commité et poussé sur
`claude/wonderful-wozniak-1tzzzi`, tests verts (116), lint propre. Pour
récupérer : `git pull origin claude/wonderful-wozniak-1tzzzi`, puis
`.venv\Scripts\python -m pytest` et `.venv\Scripts\python main.py`.

## Ce qui est fait (les 14 points)

| # | Demande | Réalisé | Où le voir |
|---|---|---|---|
| 1 | Timer cyclique « deux minutes » | Campagnes bornées par une durée (120 s par défaut) ou un nombre de lectures, compte à rebours et progression ; les tests d'hypothèses durent aussi 2 min | Onglet DIAGNOSTIC, groupe « Cible et campagne » |
| 2 | RTU et TCP | Liste RTU / TCP dans le bandeau, dialogue à deux volets, maître TCP, serveur esclave TCP multi-clients | Bandeau, CONFIGURATION |
| 3 | Export des statistiques en txt | Rapport complet (liaison, stats par esclave, hypothèses et indices, tests exécutés, torture) en UTF-8 avec BOM | DIAGNOSTIC > EXPORTER TXT |
| 4 | Test préprogrammé de torture | Phases enchaînées : référence, rafale, trames longues, timeout serré, alternance d'esclaves si plusieurs connus, 9600 bauds si RTU au-dessus de 9600 ; lecture croisée et orientation | DIAGNOSTIC > TEST DE TORTURE |
| 5 | Diagnostic indépendant des autres onglets | L'onglet choisit sa cible et ouvre la liaison lui-même si elle est fermée | DIAGNOSTIC |
| 6 | Logo AD | Dans le bandeau (variante blanche en sombre), en icône de fenêtre et d'exécutable | Bandeau, barre des tâches |
| 7 | Mention cliquable → pop-up | « Fait avec Claude Code par Antony DE JESUS » en pied de fenêtre ouvre À propos : logo, version, règle de versionnage, historique (lu depuis CHANGELOG.md), mode d'emploi court | Pied de fenêtre |
| 8 | FR / EN, FR par défaut | Sélecteur dans le bandeau, mémorisé ; interface, analyse, rapport, libellés Modbus traduits ; test qui échoue si une clé manque | Bandeau |
| 9 | Style Apple, outil industriel | Feuille de style commune aux deux thèmes : coins arrondis, bordures discrètes, survols, police système (Segoe UI Variable sous Windows) | Partout |
| 10 | Blocages entre modes, testés | Espion et serveur esclave grisent les autres onglets ; maître connecté grise espion et esclave ; scan / campagne grisent tout sauf leur onglet ; raison en info-bulle ; tests unitaires et test sur fenêtre réelle | Onglets |
| 11 | Scan : choisir les paramètres de com | Trois modes : paramètres courants, personnalisés (vitesse, parité, stop), balayage d'une sélection de vitesses et de trames | SCAN RÉSEAU > Liaison du scan |
| 12 | TCP : ping et ncpa.cpl | PING système dans un thread (résultat affiché), bouton « Connexions réseau » (Windows uniquement) | CONFIGURATION, volet TCP |
| 13 | Légende des scores | Barre 0-49 / 50-74 / 75-100 avec explication au survol | DIAGNOSTIC, à côté de « Hypothèses classées » |
| 14 | Bouton aide sur tous les diagnostics | Catalogue des 10 hypothèses : déclenchement, causes classiques, comment confirmer ; généré depuis les règles (une seule source) | DIAGNOSTIC > AIDE |

## Ce que j'ai tranché seul

- **Espion en TCP** : impossible sans recopie de port sur le switch. Le bouton
  DÉMARRER ÉCOUTE est désactivé en TCP avec l'explication en info-bulle et dans
  le volet TCP de CONFIGURATION.
- **Serveur esclave en TCP** : fait (et non reporté). L'hôte du volet TCP sert
  d'adresse d'écoute ; vide = toutes les interfaces. Le port par défaut est 502
  (sous Windows, un port inférieur à 1024 peut demander des droits ; changer
  le port si le démarrage est refusé).
- **Défaut « CRC faux » en TCP** : il n'y a pas de CRC ; le serveur altère
  l'identifiant de transaction, ce que le maître voit comme une réponse
  incohérente. Le libellé du journal le dit.
- **Diagnostic autonome** : plutôt qu'un rôle à part, l'onglet utilise le
  worker maître (même port) et ouvre la liaison lui-même. Le scan et le maître
  restent disponibles quand rien ne tourne ; pendant une campagne, l'onglet
  Maître est désactivé.
- **Blocage en maître connecté** : les onglets Espion et Serveur esclave sont
  grisés tant qu'on est connecté (il faut DECONNEXION), conformément à
  « en mode serveur pas possible d'aller ailleurs et inversement ».
- **Changement de langue** : la fenêtre est recréée immédiatement si le port
  est libre ; sinon le sélecteur revient à la langue courante avec un message.
  Pas de QTranslator ni de fichiers .ts : un dictionnaire Python suffit pour
  deux langues et n'alourdit pas l'exécutable.
- **Textes de l'analyse** : traduits eux aussi (hypothèses, tests, torture,
  rapport). Le module `i18n` est sans Qt, donc utilisable par la couche
  analyse sans casser la séparation des couches. Le français reste la clé.
- **Sources du diagnostic** : par défaut « Maître, espion et tests » ; le scan
  est exclu pour que les adresses absentes ne génèrent pas d'hypothèses.
- **Torture** : durée totale 5 min par défaut, répartie à parts égales entre
  les phases ; la phase « 9600 bauds » suppose que l'esclave accepte cette
  vitesse (dit dans le libellé).
- **Style** : pas de bibliothèque tierce, une seule feuille QSS basée sur
  `palette()` pour rester lisible dans les deux thèmes.

## Vérifications faites

- 116 tests : RTU et TCP (enveloppe MBAP, liaison, serveur, injection de
  défauts, refus de connexion, coupure, deux clients), campagnes, torture,
  rapport, catalogue, rôles, blocages sur fenêtre réelle, couverture des
  traductions.
- Scénarios hors écran sur bus virtuel : maître RTU, scan avec identification,
  espion appariant un maître externe, serveur esclave RTU et TCP interrogés de
  l'extérieur, campagne minutée avec connexion automatique, test d'hypothèse,
  torture avec orientation, export, aide, bascule de langue, deux thèmes.
- Non vérifié ici (pas de matériel ni de Windows) : ping et ncpa.cpl sous
  Windows, construction PyInstaller avec l'icône, rendu de la police Segoe UI
  Variable, Modbus TCP vers un vrai équipement.

## À valider par Antony

1. Le comportement de blocage en maître connecté (déconnexion obligatoire
   avant espion / esclave) : c'est ma lecture de « inversement ».
2. La langue par défaut reste le français ; le passage en anglais recrée la
   fenêtre (connexion fermée).
3. Le port TCP par défaut du serveur esclave (502) et l'écoute sur toutes les
   interfaces quand l'hôte est vide.
4. Le mode d'emploi de la pop-up est volontairement court : dire quel niveau de
   détail est attendu pour la version complète.
5. Reconstruire l'exécutable (`pyinstaller packaging\modbusai.spec`) et
   vérifier l'icône et le logo dans le .exe.

## Reste à faire (non demandé, noté pour plus tard)

- Mode d'emploi complet dans la pop-up À propos.
- Exports JSON / PDF si besoin.
- Espion TCP si un jour une recopie de port est disponible.
