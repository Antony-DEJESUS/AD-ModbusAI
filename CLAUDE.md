# ModbusAI - guide du projet

Outil de diagnostic Modbus RTU / RS-485 (Python 3.11+, Windows cible, PySide6,
pyserial). Phase 1 livrée : page lecture / écriture façon Modbus Doctor. Phases
suivantes prévues : mode espion (passif), scan d'adresses, campagnes de test et
statistiques, moteur de diagnostic, exports. Le projet se construit sur la
séparation en trois couches décrite ci-dessous : ne pas la contourner.

## Arborescence

```
main.py                        point d'entrée (python main.py / PyInstaller)
modbusai/__init__.py           __version__, APP_NAME, APP_TITLE (source unique de la version)
modbusai/app.py                QApplication, style Fusion, QSettings
modbusai/transport/            couche 1 : octets et instants, ignore Modbus
    records.py                 SerialSettings, ByteChunk, RawFrame, PortInfo, LinkCounters, erreurs
    ports.py                   list_serial_ports()
    framing.py                 RtuFramer : ByteChunk -> RawFrame par silence
    serial_link.py             SerialLink : open/close/send/receive/read_loop
modbusai/modbus/               couche 2 : trames Modbus, ignore le port série et Qt
    records.py                 FunctionCode, Request, ExchangeStatus, ExchangeRecord
    crc.py                     crc16, append_crc, check_crc
    exceptions.py              libellés des codes d'exception, CrcError, BadResponse, ModbusException
    pdu.py                     build_adu, parse_response, validate_request, longueurs max
    codec.py                   registres <-> affichage (DisplayMode, Radix, WordOrder, DisplayOptions)
    master.py                  RtuMaster.execute(Request) -> ExchangeRecord
modbusai/ui/                   couche 3 : Qt uniquement
    main_window.py             disposition, câblage widgets <-> worker, cycle, reconnexion
    workers.py                 ModbusWorker dans un QThread (commandes par signaux)
    widgets/                   connection_bar, request_bar, actions_panel, register_grid,
                               exchange_panel, log_console, config_dialog
tests/                         pytest ; fake_slave.py = esclave simulé sur pseudo-terminal
packaging/modbusai.spec        PyInstaller, exécutable unique nommé ModbusAI_v<version>
docs/                          propositions et notes de conception
```

## Règles de dépendance (vérifiables au grep)

- `transport` n'importe rien du projet et rien de Qt.
- `modbus` importe uniquement `transport.records`. Jamais `serial`, jamais Qt.
- `ui` importe `modbus` et `transport`. Aucune logique métier dans `ui` :
  composer une `Request` à partir des champs et afficher un `ExchangeRecord`,
  c'est de la présentation ; calculer un CRC, décoder une trame, convertir un
  float, c'est `modbus`.
- Le port série n'est touché que dans le thread du `ModbusWorker`. La fenêtre
  lui parle par les signaux `_cmd_open`, `_cmd_close`, `_cmd_execute`.

## Concepts clés

- **RawFrame** : suite d'octets délimitée par un silence, avec `t_first_ns`,
  `t_last_ns` (horloge monotone `perf_counter_ns`), `wall_time` pour les logs
  et les `ByteChunk` reçus. Une trame bruitée ou tronquée est une RawFrame
  valide : l'interprétation appartient à `modbus`.
- **ExchangeRecord** : un par requête, quelle que soit l'issue. Statuts :
  `OK`, `TIMEOUT`, `CRC_ERROR`, `MODBUS_EXCEPTION` (+ `exception_code`),
  `BAD_RESPONSE` (CRC juste mais esclave / FC / longueur incohérents),
  `TRANSPORT_ERROR`. Embarque un instantané des `SerialSettings`. C'est la
  matière première du futur module diagnostic : ne pas retirer de champ.
- **Temps** : `response_time_ms` = fin d'émission -> premier bloc reçu ;
  `transaction_time_ms` = début d'émission -> dernier bloc reçu.
- **Silence de fin de trame** : `SerialSettings.t35_ms` est la valeur
  normative ; `frame_gap_ms` est la valeur utilisée (saisie utilisateur, sinon
  max(T3.5, 5 ms) pour absorber la latence des adaptateurs USB).
- **Mode passif** (non implémenté) : `SerialLink(allow_tx=False)` interdit
  `send()` et ne pilote jamais RTS / DTR ; `read_loop()` fournit les trames en
  continu. Toute évolution du transport doit conserver ces deux propriétés.
- **Adresses** : le protocole est en base 0 partout dans le code. Seul le
  libellé « Adresse : 400001 » de la barre de requête est en base 1 préfixée.

## Conventions

- Français pour l'interface, les docstrings et les commentaires ; identifiants
  en anglais.
- Dataclasses `frozen=True, slots=True` pour tout ce qui décrit un état ou un
  enregistrement. Enums pour les listes fermées.
- Pas de `print` : la couche `ui` affiche, les couches basses renvoient ou
  lèvent. `TransportError` pour le transport, `ModbusError` et ses dérivés pour
  le décodage, `ValueError` pour une saisie hors bornes.
- pymodbus n'est pas utilisé par l'application : la pile RTU est en propre.
  Il sert d'oracle dans les tests (CRC, encodage des PDU). Ne pas l'importer
  hors de `tests/`.
- Version : modifier uniquement `__version__` dans `modbusai/__init__.py` et
  ajouter une entrée dans `CHANGELOG.md`. Phase N = 0.N.x.
- Lint : `ruff check .` (config dans `pyproject.toml`, ligne 120).

## Commandes

```
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
python main.py                           lancer l'application
python -m pytest                         tests (pty Linux uniquement pour test_serial_link_pty)
ruff check .                             lint
pyinstaller packaging/modbusai.spec      exécutable unique dans dist/
```

Sans matériel : `tests/fake_slave.py` fournit un esclave simulé sur pseudo-
terminal (Linux). Pour un test manuel de l'interface hors Windows,
`QT_QPA_PLATFORM=offscreen` permet de lancer la fenêtre et de la capturer.

## Hors périmètre phase 1 (ne pas ajouter sans demande)

Mode espion, scan d'adresses, campagnes / statistiques, moteur de diagnostic,
exports JSON / PDF, Modbus TCP, interface anglaise.
