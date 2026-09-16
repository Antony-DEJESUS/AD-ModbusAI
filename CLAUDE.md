# ModbusAI - guide du projet

Outil de diagnostic Modbus RTU / RS-485 (Python 3.11+, Windows cible, PySide6,
pyserial). Phase 1 : page lecture / écriture façon Modbus Doctor. Phase 2 :
onglets Espion (écoute passive), Scan réseau, Diagnostic (hypothèses et
tests) et Serveur esclave (simulateur façon Mod_RSsim), thème clair / sombre,
formats 64 bits. Le projet repose sur la séparation en couches ci-dessous :
ne pas la contourner.

## Arborescence

```
main.py                        point d'entrée (python main.py / PyInstaller)
modbusai/__init__.py           __version__, APP_NAME, APP_TITLE (source unique de la version)
modbusai/app.py                QApplication, QSettings
modbusai/transport/            couche 1 : octets et instants, ignore Modbus
    records.py                 SerialSettings, ByteChunk, RawFrame, PortInfo, LinkCounters, erreurs
    ports.py                   list_serial_ports()
    framing.py                 RtuFramer : ByteChunk -> RawFrame par silence
    serial_link.py             SerialLink : open/close/send/receive/read_loop, allow_tx
modbusai/modbus/               couche 2 : trames Modbus, ignore le port série et Qt
    records.py                 FunctionCode (01..06, 15, 16, 17, 43), Request, ExchangeStatus, ExchangeRecord
    crc.py                     crc16, append_crc, check_crc
    exceptions.py              libellés des codes d'exception, CrcError, BadResponse, ModbusException
    pdu.py                     build_adu, parse_response, validate_request, longueurs max
    codec.py                   registres <-> affichage (DisplayMode 8/16/32/64 bits, Radix, WordOrder)
    master.py                  RtuMaster.execute(Request, timeout_ms=None) -> ExchangeRecord
    slave.py                   DataStore (4 tables), SlaveConfig, SlaveHandler.handle(adu) -> HandledRequest
modbusai/analysis/             couche 2 bis : exploitation des enregistrements, ignore série et Qt
    observations.py            Observation (toutes sources), SlaveStats, compute_stats
    sniffer.py                 PassiveDecoder : RawFrame -> SniffedFrame / Transaction, split_merged
    scanner.py                 ScanPlan, ScanResult, classify, merge_attempts, variantes de liaison
    identification.py          décodage FC43 (DeviceIdentity) et FC17
    diagnostic.py              Hypothesis, SuggestedTest, analyse(), CampaignComparison
    session.py                 SessionStore : historique des observations
modbusai/ui/                   couche 3 : Qt uniquement
    main_window.py             bandeau, thème, onglets, arbitrage du port (Role MASTER / SNIFFER / SLAVE)
    workers.py                 ModbusWorker (maître, QObject dans un QThread), SnifferWorker, SlaveWorker
    controllers.py             ScanController, CampaignController : séquencent des ExecuteJob via le worker
    theme.py                   palettes clair / sombre, apply_theme, system_theme
    pages/                     master_page, sniffer_page, scan_page, diagnostic_page, slave_page
    widgets/                   connection_bar, request_bar, actions_panel, register_grid,
                               exchange_panel, log_console (LogConsole + LogPanel), config_dialog
tests/                         pytest ; fake_slave.py (esclave sur pty), virtual_bus.py (bus RS-485 virtuel)
packaging/modbusai.spec        PyInstaller, exécutable unique nommé ModbusAI_v<version>
docs/                          propositions et notes de conception
```

## Règles de dépendance (vérifiables au grep)

- `transport` n'importe rien du projet et rien de Qt.
- `modbus` importe uniquement `transport.records`. Jamais `serial`, jamais Qt.
- `analysis` importe `modbus` et `transport.records`. Jamais `serial`, jamais Qt.
  Tout ce qui décide (classer une trame, un résultat de scan, une hypothèse,
  un verdict de test) est ici et se teste sans matériel.
- `ui` importe les trois couches. Aucune logique métier dans `ui` : composer
  une `Request`, ordonnancer des requêtes (controllers), afficher. Le port
  série n'est touché que dans les threads de `ui/workers.py`.
- Un seul rôle occupe le port à la fois (`main_window.Role`). Le worker maître
  sert les onglets Maître, Scan et Diagnostic ; l'espion et le serveur esclave
  ont leur propre QThread et ferment la liaison maître au démarrage.

## Concepts clés

- **RawFrame** : suite d'octets délimitée par un silence, avec `t_first_ns`,
  `t_last_ns` (horloge monotone `perf_counter_ns`), `wall_time` pour les logs
  et les `ByteChunk` reçus. Une trame bruitée ou tronquée est une RawFrame
  valide : l'interprétation appartient à `modbus` / `analysis`.
- **ExchangeRecord** : un par requête du maître, quelle que soit l'issue.
  Statuts : `OK`, `TIMEOUT`, `CRC_ERROR`, `MODBUS_EXCEPTION` (+ code),
  `BAD_RESPONSE` (CRC juste mais esclave / FC / longueur incohérents),
  `TRANSPORT_ERROR`. Embarque un instantané des `SerialSettings`.
- **Observation** : réduction commune d'un ExchangeRecord (sources `maitre`,
  `scan`, `test`) ou d'une Transaction espion (`espion`) ; `SessionStore` les
  accumule, `compute_stats` en tire des `SlaveStats`, `analyse` des hypothèses.
- **ExecuteJob** : requête + timeout optionnel + `tag` (source). La fenêtre
  route les retours du worker par tag : `maitre` vers la page, `scan` / `test`
  vers le contrôleur concerné.
- **Temps** : `response_time_ms` = fin d'émission -> premier bloc reçu ;
  `transaction_time_ms` = début d'émission -> dernier bloc reçu.
- **Silence de fin de trame** : `SerialSettings.t35_ms` est normatif ;
  `frame_gap_ms` est la valeur utilisée (saisie utilisateur, sinon
  max(T3.5, 5 ms) pour la latence USB). Le décodeur passif recolle par
  `split_merged` une requête et sa réponse arrivées dans le même bloc.
- **Mode passif** : `SerialLink(allow_tx=False)` interdit `send()` et force
  RTS / DTR bas ; `read_loop()` fournit les trames en continu (SnifferWorker).
- **Adresses** : protocole en base 0 partout dans le code. Seuls les libellés
  « 400001 » (barre de requête, en-têtes du serveur esclave) sont en base 1.
- **Request pour FC43** : `address` = code de lecture (1 basique), `count` =
  identifiant d'objet de départ. FC17 n'a pas de paramètre.

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
- Couleurs : ne jamais coder du noir ou du blanc en dur dans un widget (les
  deux thèmes doivent rester lisibles) ; les couleurs d'état (#2ea043 vert,
  #d29922 orange, #e5534b rouge, #a371f7 violet, #8b949e gris) sont communes.
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

Sans matériel (Linux) : `tests/fake_slave.py` (esclave sur un pty) et
`tests/virtual_bus.py` (N pty reliés par un relais, chaque point en mode brut)
permettent de faire dialoguer maître, serveur esclave et espion dans le même
processus. Dans ce cas, prévoir `inter_frame_delay_ms` >= 20 et
`sys.setswitchinterval(0.0005)` : les pauses du GIL entre threads Python
coupent sinon les réponses au seuil de 5 ms. `QT_QPA_PLATFORM=offscreen`
permet de lancer la fenêtre et de la capturer.

## Hors périmètre (ne pas ajouter sans demande)

Modbus TCP, exports JSON / PDF, interface anglaise, scripts d'animation type
« training PLC » du serveur esclave.
