# Changelog

Numérotation X.Y.Z : X = changement majeur d'architecture, Y = nouvelle phase
fonctionnelle (phase 1 = 0.1, phase 2 = 0.2…), Z = corrections. La version est
définie une seule fois dans `modbusai/__init__.py` et reprise par la barre de
titre et le nom de l'exécutable.

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
