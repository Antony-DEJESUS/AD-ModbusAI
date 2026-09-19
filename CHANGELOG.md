# Changelog

Numérotation X.Y.Z : X = changement majeur d'architecture, Y = nouvelle phase
fonctionnelle (phase 1 = 0.1, phase 2 = 0.2…), Z = corrections. La version est
définie une seule fois dans `modbusai/__init__.py` et reprise par la barre de
titre et le nom de l'exécutable.

## 1.0.1 - Mode d'emploi et corrections d'affichage

- **Mode d'emploi complet** en PDF (`docs/AD-ModbusAI_Mode_d_emploi_v1.0.1.pdf`),
  32 pages : installation, chaque onglet, arbitrage des ports, câblage RS-485,
  dépannage, catalogue des hypothèses et annexes. Il est engendré depuis le
  code par `docs/manuel/build_manuel.py` (captures d'écran sur bus virtuel par
  `docs/manuel/captures.py`), donc toujours aligné sur les règles réelles.
- Correction : l'hypothèse sélectionnée dans l'onglet Diagnostic était
  invisible (texte clair sur fond clair) ; elle est maintenant surlignée avec
  un filet d'accent.
- Correction : la zone des paramètres du scan se dimensionne d'après son texte
  le plus large au lieu d'une largeur fixe.

## 1.0.0 - Première version complète

Les trois phases sont livrées et validées sur chantier (TC903 Schneider,
adaptateur CH340, 19200 8N1). Ce que fait l'outil :

- **Maître** RTU et TCP : lecture / écriture façon Modbus Doctor, cyclique,
  reconnexion automatique, formats 8 à 64 bits et flottants, valeur, hexa et
  binaire côte à côte, journal en colonnes.
- **Espion** : écoute passive du bus RS-485, sans jamais émettre.
- **Scan réseau** : recherche des esclaves, identification FC43 / FC17,
  balayage des vitesses et parités.
- **Diagnostic autonome** : campagnes minutées, test de torture expliqué phase
  par phase, hypothèses classées avec score et légende, tests pour départager,
  export texte qui se suffit à lui-même (statistiques, hypothèses, phases,
  trace de toutes les trames).
- **Serveur esclave** : simulateur façon Mod_RSsim sur sa propre liaison, donc
  utilisable en même temps que le maître sur un autre port ; injection de
  défauts, maîtres connectés, cellules lues ou écrites éclairées en vert.
- Français / anglais, thème clair / sombre, charte AD (gris chauds et
  terracotta), exécutable unique sans installateur.

Ajouts de cette version :

- Pastille d'accent sur l'onglet où une activité tourne (campagne, scan, écoute,
  serveur) : on la voit même en regardant ailleurs.
- Pendant une campagne ou un scan, ARRÊTER devient l'action saillante.
- La colonne du diagnostic se dimensionne sur ses boutons, icônes comprises.
- La version de `pyproject.toml` avait dérivé de celle du paquet sans que rien
  ne le signale : les deux sont réalignées et un test les tient ensemble.

## 0.3.5 - Icônes et journal en colonnes

- Jeu d'icônes dessiné à l'exécution (`ui/iconography.py`) : dix-huit tracés sur
  une grille de 24, sans fichier ni dépendance, dans la couleur du thème. Posées
  sur les onglets et sur les boutons d'action ; les icônes des boutons
  principaux prennent la couleur du texte posé sur l'accent. Tout se repeint au
  changement de thème, voyants et tuiles compris.
- Journal en colonnes fixes (heure, n°, esclave, fonction, statut, temps, puis
  les trames) avec un en-tête qui les nomme. Le serveur esclave a ses propres
  colonnes (heure, maître, esclave, fonction, traitement, trames) : on lit une
  console en balayant une colonne, pas en lisant des phrases.
- Correction au passage : la feuille de style globale imposait sa police à la
  console, dont la chasse fixe posée en code était ignorée depuis la 0.3.2. La
  police à chasse fixe vient maintenant de la feuille de style elle-même.

## 0.3.4 - Marque AD, lisibilité à toutes les échelles, moins d'ambiguïté

- Marque : le monogramme porte de nouveau les lettres « AD » dans l'interface
  (bandeau, À propos). L'icône d'application, elle, garde le A seul sur fond
  terracotta : à 16 pixels dans la barre des tâches, les lettres deviennent une
  tache. `tools/make_logo.py --accent "#3E7CB1"` régénère marque et icône pour
  un autre outil de la gamme : chaque outil, sa couleur.
- L'À propos s'ouvre au premier démarrage, et une seule fois par version
  (l'onglet Historique dit alors ce qui a changé). Un bouton À PROPOS est ajouté
  au bandeau, à côté de THÈME.
- Fin de l'ambiguïté entre les deux liaisons : le bandeau est étiqueté MAÎTRE et
  ses boutons deviennent CONFIGURER / CONNECTER / DÉCONNECTER ; l'onglet du
  serveur esclave a son propre groupe LIAISON avec un bouton CONFIGURER. On voit
  d'un coup d'œil quel réglage appartient à quel rôle.
- Largeurs calculées d'après le texte et non en pixels (`ui/metrics.py`) : plus
  de libellé tronqué à 125 ou 150 % d'échelle Windows. Le panneau d'actions du
  maître se cale tout seul sur son plus large contrôle.
- Chiffres tabulaires dans les tableaux, les compteurs et le journal : les
  colonnes ne dansent plus pendant un cycle.
- Compteurs du serveur esclave en tuiles (valeur en gros, libellé discret,
  couleur seulement quand ce n'est pas zéro) au lieu d'une ligne de texte, et
  bandeau du serveur regroupé en ESCLAVES / LIAISON / DÉFAUTS SIMULÉS.
- Grille du maître : colonnes Valeur, Hexa et Binaire côte à côte, au lieu d'une
  seule valeur étirée sur toute la largeur.
- États vides explicites dans le diagnostic, et la grille grise ses valeurs
  périmées avec la couleur de la charte plutôt qu'un gris Qt en dur.

## 0.3.3 - AD - ModbusAI : marque, maître et esclave en parallèle, cellules animées

- Le logiciel s'appelle « AD - ModbusAI » ; l'exécutable devient
  `AD-ModbusAI_v<version>.exe` et le rapport `AD-ModbusAI_diagnostic_*.txt`.
  Les réglages enregistrés (port, thème, langue) sont conservés.
- Marque : le logo se réduit au A seul, l'icône de l'application est ce A clair
  sur carré terracotta. L'artwork d'origine part dans `assets/source/`, hors
  exécutable. Plus aucune mention de société dans l'interface, et la mention du
  pied de fenêtre devient « Fait avec CC par Antony DE JESUS ».
- **Maître et serveur esclave en même temps**, sur deux ports différents : le
  serveur a sa propre liaison (bouton LIAISON dans son onglet, protocole RTU ou
  TCP, réglages mémorisés). L'arbitrage se fait désormais par port et non plus
  par rôle : deux rôles cohabitent tant qu'ils ne visent pas la même ressource,
  et le refus nomme le port et le rôle qui l'occupe. Une activité longue (scan,
  campagne, torture) ne verrouille plus que les onglets qui partagent la liaison
  maître.
- Serveur esclave : les cellules lues ou écrites par un maître s'éclairent en
  vert pendant deux secondes, avec une extinction progressive ; on voit d'un
  coup d'œil ce que la supervision interroge vraiment.
- Thème sombre éclairci (gris chaud #2E2C2A) et marges intérieures des onglets :
  plus rien ne colle au trait du bandeau.

## 0.3.2 - Charte graphique AD : gris foncé et terracotta

- Charte unique dans `modbusai/ui/palette.py` : gris chauds et terracotta
  (#D97757 en sombre, #C2603E sur fond crème en clair). La palette Qt, la
  feuille de style et les couleurs d'état en découlent ; plus aucune couleur
  n'est écrite dans un widget, un test le vérifie.
- L'accent terracotta est réservé à ce qui engage : bouton principal de chaque
  onglet, onglet actif, focus, sélection, coche, progression.
- Thème clair repensé en crème (#F5F2EC) plutôt qu'en gris Windows, thème
  sombre en gris chaud (#232221) : même identité dans les deux modes.
- Couleurs d'état (vert, ambre, rouge, violet) déclinées par thème et testées
  en contraste : au moins 4:1 sur chaque fond, dans les deux thèmes.
- Habillage : coins arrondis et cartes, onglets soulignés à l'accent, bandeau
  d'en-tête avec logo, nom, version et pastille d'état de liaison, cases à
  cocher et boutons radio dessinés, barres de défilement fines, hiérarchie de
  titres de section.
- Détails d'ergonomie : la période du cycle s'affiche sur son bouton, le bouton
  de rafraîchissement des ports est libellé (le glyphe ↻ manque à certaines
  polices), l'en-tête « Incohérentes » ne déborde plus du tableau.

## 0.3.1 - Retours de chantier : flèches, bascule de rôle, trace des trames

- Flèches des listes déroulantes et des compteurs de nouveau visibles : la
  feuille de style masquait les indicateurs natifs, ils sont maintenant
  dessinés à l'exécution dans la couleur du thème (`ui/icons.py`).
- Bascule directe depuis un maître connecté vers l'espion ou le serveur
  esclave : les onglets ne sont plus grisés, la liaison maître est fermée
  automatiquement et le rôle démarre une fois le port rendu.
- Les phases de torture qui provoquent volontairement des défauts (trames
  longues, timeout serré, vitesse réduite) sont marquées comme telles : leurs
  échanges n'entrent plus dans les statistiques ni dans les hypothèses. Une
  campagne de test qui modifie la liaison est traitée de même. Corrige le
  diagnostic « qualité de ligne » qui revenait après chaque torture alors que
  les timeouts venaient de la phase 9600 bauds.
- Le test de torture explique chaque phase dans le rapport : but, réglages,
  chiffres et lecture en clair, dont « aucune réponse à 9600 bauds : l'esclave
  n'est pas réglé sur cette vitesse, phase non concluante ».
- L'export txt contient toutes les trames échangées (horodatage, source,
  campagne ou phase, esclave, fonction, statut, temps de réponse, TX et RX) ;
  case « Trames dans l'export » pour s'en passer.
- Serveur esclave : nombre et adresses des maîtres connectés, adresse d'écoute
  lisible (0.0.0.0 devient « toutes les interfaces, joignable sur 192.168.x.y »)
  et journal préfixé par le maître à l'origine de chaque trame.

## 0.3.0 - Phase 3 : TCP, diagnostic autonome, torture, export, FR/EN, habillage

- Modbus TCP en plus du RTU : choix du protocole dans le bandeau, dialogue de
  configuration à deux volets (série / réseau), maître et serveur esclave TCP
  (plusieurs clients), enveloppe MBAP, PING système et accès aux « Connexions
  réseau » Windows (ncpa.cpl). L'espion reste RTU (une recopie de port serait
  nécessaire en TCP) et le bouton l'explique.
- Onglet Diagnostic autonome : il choisit sa cible (esclave, type, registre,
  longueur, période) et lance ses campagnes sans passer par l'onglet Maître ;
  la liaison est ouverte automatiquement si besoin.
- Campagnes minutées : durée (deux minutes par défaut) ou nombre de lectures,
  compte à rebours et progression ; les tests d'hypothèses durent aussi deux
  minutes par défaut.
- Test de torture : phases enchaînées (référence, rafale, trames longues,
  timeout serré, alternance d'esclaves, vitesse réduite) puis lecture croisée
  et orientation (surcharge, ligne, esclave lent, bus fragile, sain).
- Export du diagnostic en texte (statistiques, hypothèses, tests exécutés,
  torture), UTF-8 avec BOM pour le Bloc-notes.
- Légende des scores de diagnostic et bouton AIDE : catalogue de toutes les
  hypothèses (déclenchement, causes classiques, comment confirmer), généré
  depuis les règles elles-mêmes.
- Scan réseau : liaison au choix (paramètres courants, personnalisés, ou
  balayage d'une sélection de vitesses et de trames 8N1 / 8E1 / 8O1 / 8N2).
- Blocages entre onglets : espion et serveur esclave verrouillent les autres
  onglets, le maître connecté verrouille espion et esclave, une activité
  longue verrouille son onglet seul ; raison en info-bulle, table testée.
- Interface français / anglais (sélecteur dans le bandeau, mémorisé, fenêtre
  recréée à la volée), analyse et rapport traduits ; test garantissant que
  toute clé du code a sa traduction.
- Habillage : feuille de style commune aux deux thèmes (coins arrondis,
  bordures discrètes, police système), logo AD Automation dans le bandeau et
  en icône, pop-up À propos (logo, version, règle de versionnage, historique,
  mode d'emploi court) ouverte par la mention « Fait avec Claude Code par
  Antony DE JESUS ».
- Couche modbus : `ModbusMaster` générique (enveloppe RTU ou TCP), `SlaveHandler`
  au niveau PDU ; couche transport : `TcpLink`, `TcpServer`, `TcpSettings`.

## 0.2.0 - Phase 2 : onglets Espion, Scan réseau, Diagnostic, Serveur esclave

- Fenêtre à onglets : MAÎTRE (page de la phase 1), ESPION, SCAN RÉSEAU,
  DIAGNOSTIC, SERVEUR ESCLAVE. Un seul rôle occupe le port à la fois ; le
  bandeau de connexion reste commun.
- Affichage 64 bits : entier signé / non signé et flottant double, ordres
  ABCDEFGH / GHEFCDAB / BADCFEHG / HGFEDCBA (inversions d'octets et de mots).
- Thème clair / sombre (bouton THÈME, mémorisé ; thème système par défaut).
- Espion : écoute passive sans émission, classification des trames (requête,
  réponse, exception, diffusion, invalide), appariement requête / réponse avec
  temps de réponse, découpage des trames collées, trames brutes, statistiques
  par esclave.
- Scan réseau : plage d'adresses, code fonction, timeout et essais, verdict
  par adresse (présent, présent avec exception, réponse corrompue, réponse
  incohérente ou écho, absent), identification FC43 puis FC17, balayage
  optionnel des vitesses et parités courantes, copie des résultats.
- Diagnostic : historique de session toutes sources, statistiques par esclave
  (réussite, timeouts, CRC, exceptions, temps moyen / P95 / max / gigue),
  hypothèses classées (absent ou câblage, vitesse / parité, qualité de ligne,
  esclave lent, écho adaptateur, conflit d'adresse, adresse refusée,
  fragmentation USB, adaptateur instable, réseau sain) avec indices, et tests
  pour les départager dont des campagnes exécutables comparées à la référence.
- Serveur esclave RTU façon Mod_RSsim : quatre tables de 65536 valeurs
  éditables par blocs de 10, formats décimal / hexa / binaire, adresses
  servies, voyants RX / TX, journal, remplissage et animation, injection de
  défauts (délai, pertes, CRC faux, lecture seule), FC 01 à 06, 15, 16, 17, 43.
- Couche modbus : FC17 et FC43, délai de réponse surchargeable par requête,
  numérotation des échanges continue après reconnexion.
- Robustesse : toute erreur d'ouverture de port devient une TransportError ;
  reprise automatique du cycle après reconnexion ; boutons COPIER et EFFACER
  JOURNAL.
- Tests : bus RS-485 virtuel (pseudo-terminaux reliés) faisant dialoguer
  maître, serveur esclave et espion dans le même processus.

## 0.1.0 - Phase 1 : lecture / écriture façon Modbus Doctor

- Page principale reproduisant l'organisation de Modbus Doctor : configuration
  liaison, connexion / déconnexion, esclave, registre, longueur, type, adresse,
  mode ; LECTURE / ECRITURE ; reconnexion auto ; cyclique ; inversions ; signé /
  non signé ; modes d'affichage bits / octet / 16 / 32 / flottant.
- Couche transport : liaison série pyserial avec réception horodatée par blocs,
  découpage de trames par silence, garde-fou pour le futur mode passif.
- Couche Modbus : CRC16, FC 01/02/03/04/05/06/15/16, codes d'exception, codec
  d'affichage, maître RTU produisant un `ExchangeRecord` par requête.
- Console de log : horodatage, TX / RX hexa, temps de réponse, résultat.
- Tests unitaires et d'intégration (pseudo-terminal Linux, pymodbus en oracle).
- Packaging PyInstaller (exécutable unique).
