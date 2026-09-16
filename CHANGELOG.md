# Changelog

Numérotation X.Y.Z : X = changement majeur d'architecture, Y = nouvelle phase
fonctionnelle (phase 1 = 0.1, phase 2 = 0.2…), Z = corrections. La version est
définie une seule fois dans `modbusai/__init__.py` et reprise par la barre de
titre et le nom de l'exécutable.

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
