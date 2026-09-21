# AD - ModbusAI - guide du projet

Outil de diagnostic Modbus RTU / RS-485 et Modbus TCP (Python 3.11+, Windows
cible, PySide6, pyserial). Phase 1 : page lecture / écriture façon Modbus
Doctor. Phase 2 : onglets Espion, Scan réseau, Diagnostic, Serveur esclave,
thème clair / sombre, 64 bits. Phase 3 : Modbus TCP, diagnostic autonome avec
campagnes minutées et test de torture, export txt, blocages entre onglets,
français / anglais, charte graphique AD. Phase 4 : serveur MCP, le bus exposé
comme un jeu d'outils pour un assistant, en local ou par un réseau privé. Le
projet repose sur la séparation en couches ci-dessous : ne pas la contourner.

## Arborescence

```
main.py                        point d'entrée (python main.py / PyInstaller)
modbusai/__init__.py           __version__, APP_NAME, APP_TITLE (source unique de la version)
modbusai/app.py                QApplication, langue au démarrage, recréation de la fenêtre
modbusai/i18n.py               tr(), set_language : module feuille sans Qt, le français est la clé
modbusai/i18n_en.py            dictionnaire français -> anglais
modbusai/roles.py              Role, Tab, port_key(), Occupancy, can_start(), tab_states() : arbitrage des ports
modbusai/transport/            couche 1 : octets et instants, ignore Modbus
    records.py                 SerialSettings, TcpSettings, LinkSettings, ByteChunk, RawFrame, erreurs
    ports.py                   list_serial_ports()
    framing.py                 RtuFramer : ByteChunk -> RawFrame par silence
    serial_link.py             SerialLink : open/close/send/receive/read_loop, allow_tx
    tcp_link.py                TcpLink : même interface, délimitation par la longueur MBAP
    tcp_server.py              TcpServer multi-clients, rappel (trame, client) -> réponse, liste des clients
    netinfo.py                 adresses IPv4 de la machine (0.0.0.0 -> « joignable sur … »)
modbusai/modbus/               couche 2 : trames Modbus, ignore le port série et Qt
    records.py                 FunctionCode (01..06, 15, 16, 17, 43), Request, ExchangeStatus, ExchangeRecord
    crc.py                     crc16, append_crc, check_crc
    mbap.py                    enveloppe Modbus TCP : build_mbap, parse_mbap, frame_length
    exceptions.py              libellés des codes d'exception, CrcError, BadResponse, ModbusException
    pdu.py                     build_pdu, build_adu, parse_response (RTU), parse_response_pdu (commun)
    codec.py                   registres <-> affichage (DisplayMode 8/16/32/64 bits, Radix, WordOrder)
    master.py                  ModbusMaster(link, framing RTU ou TCP).execute(Request, timeout_ms) ; RtuMaster = alias
    slave.py                   DataStore (4 tables), SlaveConfig, SlaveHandler.handle (RTU) / handle_pdu (commun)
    tcp_slave.py               pont TcpServer <-> SlaveHandler (MBAP)
modbusai/analysis/             couche 2 bis : exploitation des enregistrements, ignore série et Qt
    observations.py            Observation (source, libellé, trames TX/RX), SlaveStats, compute_stats, vocabulaire des sources
    sniffer.py                 PassiveDecoder : RawFrame -> SniffedFrame / Transaction, split_merged
    scanner.py                 ScanPlan (liaison, balayage sélectif), ScanResult, classify, merge_attempts
    identification.py          décodage FC43 (DeviceIdentity) et FC17
    campaign.py                CampaignSpec : période, durée et / ou nombre, surcharges de liaison
    stress.py                  scénario de torture (phases), phase_reading(), evaluate() -> StressReport
    diagnostic.py              CATALOGUE (fiches d'hypothèses), Hypothesis, SuggestedTest, analyse(), légende
    report.py                  rapport texte exportable (statistiques, hypothèses, phases détaillées, trace des trames)
    session.py                 SessionStore : historique des observations
modbusai/mcp/                  couche 3 bis : le bus en outils MCP, sans Qt
    protocol.py                JSON-RPC 2.0 et poignée de main MCP, sans transport ni Modbus
    service.py                 liaisons, travaux en fond, serveur esclave : workers + controllers sans Qt
    tools.py                   catalogue des outils (nom, description, schéma) et consignes du serveur
    render.py                  mise en forme texte des résultats, pour un lecteur qui n'a pas d'écran
    stdio.py                   transport entrée / sortie standard (mode local)
    http.py                    transport HTTP (mode distant : Tailscale, VPN)
    cli.py                     options de lancement, --ecriture, --http, --jeton
modbusai/ui/                   couche 3 : Qt uniquement
    main_window.py             bandeau (liaison du MAÎTRE), thème, langue, onglets, arbitrage des ports, campagnes
    workers.py                 ModbusWorker (maître RTU/TCP), SnifferWorker, SlaveWorker, TcpSlaveWorker
    controllers.py             ScanController, CampaignController (durée), StressController (phases)
    palette.py                 charte AD : jetons de couleur des deux thèmes, couleurs d'état (State)
    theme.py                   palette Qt construite depuis la charte, application du thème
    style.py                   feuille de style engendrée depuis les jetons (cartes, onglets, accent)
    icons.py                   chevrons et coche de la feuille de style, dessinés à l'exécution
    iconography.py             jeu d'icônes (tracés 24x24), set_icon / set_tab_icon, refresh_all au changement de thème
    metrics.py                 largeurs et hauteurs tirées du texte, police à chiffres tabulaires
    widgets/labels.py          section() et muted() : étiquettes typées par la feuille de style
    widgets/stat_tiles.py      rangée de compteurs : valeur lisible, libellé discret, couleur si non nul
    resources.py               logo, icône, CHANGELOG (compatible PyInstaller)
    network_tools.py           ping système dans un thread, ouverture de ncpa.cpl (Windows)
    pages/                     master_page, sniffer_page, scan_page, diagnostic_page, slave_page
    widgets/                   connection_bar, request_bar, actions_panel, register_grid, exchange_panel,
                               log_console (colonnes fixes + en-tête), config_dialog, about_dialog
assets/                        marque mark-*.png (A + « AD »), icône .ico (A sur fond d'accent) ; source/ = artwork d'origine, non embarqué
tools/make_logo.py             régénère marque et icône, --accent donne sa couleur à chaque outil de la gamme
tests/                         pytest ; fake_slave.py (esclave sur pty), virtual_bus.py (bus RS-485 virtuel)
packaging/modbusai.spec        PyInstaller : AD-ModbusAI_v<version> (fenêtré) et AD-ModbusAI-MCP_v<version> (console)
docs/                          propositions, plan, compte rendu de phase, mode d'emploi PDF, mcp.md (mise en service)
docs/manuel/                   captures.py (captures sur bus virtuel) et build_manuel.py (HTML -> PDF via Chromium)
```

## Règles de dépendance (vérifiables au grep)

- `transport` n'importe rien du projet et rien de Qt.
- `modbus` importe uniquement `transport.records`. Jamais `serial`, jamais Qt.
- `analysis` importe `modbus` et `transport.records`. Jamais `serial`, jamais Qt.
  Tout ce qui décide (classer une trame, un résultat de scan, une hypothèse,
  un verdict de test) est ici et se teste sans matériel.
- `ui` importe les trois couches. Aucune logique métier dans `ui` : composer
  une `Request`, ordonnancer des requêtes (controllers), afficher. Le port
  (série ou socket) n'est touché que dans les threads de `ui/workers.py`.
- `mcp` est un second client des trois couches, au même rang que `ui` et sans
  Qt : `tests/test_mcp.py` et l'exclusion PySide6 du spec garantissent qu'aucun
  import graphique n'y entre. Même règle qu'en `ui` : composer, ordonnancer,
  mettre en forme, jamais décider. La pile JSON-RPC est écrite en propre comme
  la pile RTU, pour n'ajouter aucune dépendance. Un outil qui échoue renvoie un
  résultat `isError` que le modèle lit ; seule une faute de protocole (méthode
  inconnue, paramètres illisibles) donne un objet `error` JSON-RPC.
- `i18n` est un module feuille sans Qt, importable par toutes les couches :
  les textes lisibles sont écrits en français et passés à `tr()`, l'anglais
  vient de `i18n_en.EN` (une clé absente retombe sur le français). Les
  gabarits dynamiques utilisent `tr("... {p0} ...").format(p0=...)`. Le test
  `test_i18n` échoue si une clé du code n'a pas sa traduction.
- **Un port, un rôle** (`roles.py`, hors `ui` car le serveur MCP l'applique
  aussi) : l'arbitrage porte sur la ressource, pas
  sur le rôle. `port_key(settings, listen=)` donne la clé (port série, ou point
  TCP distingué entre connexion et écoute) ; `can_start(role, port, active)`
  refuse en nommant le port et le rôle qui l'occupe. Maître et serveur esclave
  tournent donc en parallèle sur deux ports différents : le serveur a sa propre
  liaison (`SlavePage.link_settings()`, réglages `slave/*` dans QSettings). Le
  worker maître sert les onglets Maître, Scan et Diagnostic ; l'espion et le
  serveur ont leur propre QThread. `tab_states(busy_tab)` ne verrouille que les
  onglets qui partagent la liaison maître pendant une activité longue. L'espion
  utilise la liaison du bandeau : s'il vise le port du maître, la fenêtre ferme
  cette liaison d'abord (`_release_master_then`) et n'ouvre le port qu'une fois
  la fermeture confirmée.

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
  `scan`, `test`, `torture`) ou d'une Transaction espion (`espion`), avec le
  libellé de la campagne ou de la phase et les trames TX / RX pour l'export ;
  `SessionStore` les accumule, `compute_stats` en tire des `SlaveStats`,
  `analyse` des hypothèses.
- **Défauts provoqués** : une phase ou une campagne qui dégrade volontairement
  la liaison ou la requête (vitesse réduite, timeout serré, trames hors
  gabarit) porte la source `torture` (`SOURCE_DEGRADED`). Ces échanges restent
  visibles et exportés mais sortent des statistiques et des hypothèses : sinon
  le test fabrique lui-même le défaut qu'il diagnostique. `DEFAULT_SOURCES` =
  maître + espion + tests normaux.
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
- **RTU ou TCP** : `LinkSettings = SerialSettings | TcpSettings`. `ModbusMaster`
  choisit l'enveloppe (CRC ou MBAP) d'après le type de paramètres ; les
  enregistrements, l'analyse et les pages ne voient pas la différence. En TCP
  il n'y a ni CRC (une trame incohérente donne `BAD_RESPONSE`), ni vitesse, ni
  parité : les règles et le scan testent `isinstance(settings, SerialSettings)`.
- **Campagne** : `CampaignSpec` (période, durée et / ou nombre, surcharges) ;
  `CampaignController` l'exécute, `StressController` enchaîne les phases d'un
  scénario `stress.default_scenario` et `stress.evaluate` conclut.
- **Rapport** : `build_report` écrit les statistiques, les hypothèses, les
  tests exécutés, puis chaque phase de torture (but, réglages, chiffres et
  `phase_reading` en clair) et enfin la trace de toutes les trames. Le fichier
  doit se suffire à lui-même : il est relu sans l'application, éventuellement
  par un assistant.
- **Serveur MCP** : `ModbusService` tient la liaison du maître, l'historique et
  le serveur esclave ; un travail long (scan, campagne, torture, écoute) tourne
  dans un fil, réserve la liaison et se suit par `job_status`. Les outils qui
  écrivent (bus ou tables du simulateur) ne sont pas proposés sans `--ecriture` :
  un outil absent vaut mieux qu'un outil qui refuse. En HTTP, l'écoute est liée
  à 127.0.0.1 par défaut, un jeton peut être exigé et un en-tête `Origin`
  étranger est refusé. Ajouter un outil = une entrée dans `tools.py` (schéma
  JSON et gestionnaire) plus son rendu dans `render.py`.
- **Marque** : `assets/mark-*.png` (le A et les lettres « AD ») pour l'interface,
  `modbusai.ico` (le A seul sur fond d'accent) pour la barre des tâches, où les
  lettres seraient illisibles. `tools/make_logo.py --accent` les régénère : la
  gamme d'outils partage la marque et se distingue par la couleur.
- **Charte graphique** : `ui/palette.py` décrit les deux thèmes par des jetons
  (fond, surfaces, cartes, bordures, texte, accent, états). `ui/theme.py` en
  fait une `QPalette`, `ui/style.py` la feuille de style, `ui/icons.py` les
  indicateurs (chevrons, coche) que la feuille de style empêche Qt de dessiner.
- **Zone touchée** : `SlaveHandler` renseigne `HandledRequest.access` (table,
  adresse, nombre, lecture ou écriture) ; l'onglet Serveur esclave s'en sert
  pour éclairer en vert les cellules que le maître vient de lire ou d'écrire.
- **Catalogue d'hypothèses** : `diagnostic.CATALOGUE` est la source unique des
  titres, résumés, déclencheurs, causes et confirmations ; les règles y
  puisent, l'aide et le rapport aussi. Ajouter une règle = ajouter sa fiche.

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
- Dimensions : **aucune largeur ni hauteur en pixels dans un widget**. Windows
  à 125 ou 150 % agrandit la police, pas les constantes : passer par
  `ui/metrics.py` (`text_width`, `line_height`) ou par `sizeHint()` des
  contrôles. Les tableaux, compteurs et consoles utilisent les chiffres
  tabulaires (`use_tabular_figures`, `mono_font`).
- Couleurs : **aucune couleur écrite dans un widget**, `tests/test_style.py`
  refuse tout `#rrggbb` hors de `ui/palette.py`. La charte AD est
  la source unique : gris chauds et terracotta, thème sombre et thème clair
  (crème). L'accent (`t.accent`) ne sert qu'à ce qui engage : bouton principal
  (`setProperty("variant", "primary")`), onglet actif, focus, sélection,
  progression. Une mesure se qualifie avec `palette.color(State.OK / WARN /
  ERROR / SPECIAL / MUTED)`, dont la nuance dépend du thème ; le contraste
  minimal (4:1 sur chaque fond) est vérifié par test. Les couches basses ne
  connaissent pas les couleurs : `SCORE_LEGEND` donne un niveau (`ok`, `warn`,
  `error`), l'interface le traduit en couleur.
- Icônes : jamais d'image embarquée ni de glyphe Unicode dans un libellé (toutes
  les polices ne les ont pas) ; `iconography.set_icon(widget, "nom")` pose une
  icône du jeu, `on_accent=True` pour un bouton principal. Ajouter une icône =
  ajouter un tracé dans `_PAINTERS`.
- Journal : les lignes passent par `LogConsole.log_cells`, qui aligne sur les
  colonnes déclarées (`MASTER_COLUMNS`, `SLAVE_COLUMNS`) ; la colonne mise en
  évidence est colorée sans casser l'alignement. La police à chasse fixe vient
  de la feuille de style (`#logConsole`) : la régler par `setFont` ne suffit
  pas, le QSS global reprend la main.
- Textes : tout libellé visible passe par `tr()` et a son entrée dans
  `i18n_en.py`. Les énumérations gardent leur valeur française et sont
  traduites au point d'affichage (`tr(e.value)`).
- Version : modifier `__version__` dans `modbusai/__init__.py` **et** `version`
  dans `pyproject.toml` (un test vérifie qu'ils s'accordent), puis ajouter une
  entrée dans `CHANGELOG.md`. Les phases 1 à 3 ont porté les versions 0.1 à
  0.3 ; depuis la 1.0.0 : X = rupture (architecture ou format des données),
  Y = nouvelle fonction, Z = correction.
- Lint : `ruff check .` (config dans `pyproject.toml`, ligne 120).

## Commandes

```
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
python main.py                           lancer l'application
python -m modbusai.mcp                   serveur MCP sur l'entrée standard (--ecriture, --http, --jeton)
python -m pytest                         tests (pty / bus virtuel Linux uniquement pour quelques modules)
ruff check .                             lint
pyinstaller packaging/modbusai.spec      les deux exécutables dans dist/
```

Sans matériel (Linux) : `tests/fake_slave.py` (esclave sur un pty) et
`tests/virtual_bus.py` (N pty reliés par un relais, chaque point en mode brut)
permettent de faire dialoguer maître, serveur esclave et espion dans le même
processus. Dans ce cas, prévoir `inter_frame_delay_ms` >= 20 et
`sys.setswitchinterval(0.0005)` : les pauses du GIL entre threads Python
coupent sinon les réponses au seuil de 5 ms. `QT_QPA_PLATFORM=offscreen`
permet de lancer la fenêtre et de la capturer.

## Hors périmètre (ne pas ajouter sans demande)

Exports JSON / PDF, espion en Modbus TCP (recopie de port nécessaire), scripts
d'animation type « training PLC » du serveur esclave, autres langues que
français / anglais.
