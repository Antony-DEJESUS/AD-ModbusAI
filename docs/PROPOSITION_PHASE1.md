# Proposition phase 1 — arborescence et couche transport

Document validé (pile RTU en propre, paquet `modbusai`, interface FR seule en
phase 1). Écarts entre cette proposition et le code livré :

- pas de `ui/models/` ni de `ui/i18n.py` : la grille est un `QTableWidget`
  alimenté directement, et l'interface est en français uniquement ;
- le panneau droit (`ui/widgets/exchange_panel.py`) affiche le détail du
  dernier échange à la place du logo de Modbus Doctor ; la console de log
  occupe toute la largeur en bas ;
- `SerialSettings.frame_gap_ms` s'ajoute à `t35_ms` (silence pratique vs
  normatif, voir CLAUDE.md) ;
- `ExchangeRecord.transaction_time_ms` s'ajoute à `response_time_ms`.

L'arborescence à jour est dans `CLAUDE.md`.

## 1. Arborescence

```
AD-ModbusAI/
├── CLAUDE.md                     architecture, conventions (livré en phase 1)
├── README.md
├── requirements.txt              PySide6, pyserial, pymodbus
├── requirements-dev.txt          + pytest, ruff, pyinstaller
├── main.py                       point d'entrée (utilisé par PyInstaller)
├── packaging/modbusai.spec       fichier PyInstaller (exécutable unique)
├── docs/
├── tests/
│   ├── test_crc.py
│   ├── test_pdu.py               encodage requêtes / décodage réponses FC 01..16
│   ├── test_codec.py             int16/uint16/int32/float32, ordres ABCD/CDAB/BADC/DCBA
│   └── test_framing.py           découpage de trames par silence
└── modbusai/
    ├── __init__.py
    ├── app.py                    QApplication + câblage des couches
    ├── transport/                ── couche 1 : octets et instants, zéro Modbus
    │   ├── records.py            SerialSettings, ByteChunk, RawFrame, PortInfo, LinkCounters
    │   ├── ports.py              détection des ports COM (serial.tools.list_ports)
    │   ├── framing.py            RtuFramer : flux d'octets horodatés -> RawFrame (silence ≥ T3.5)
    │   └── serial_link.py        SerialLink : open/close, send(), receive(), read_loop()
    ├── modbus/                   ── couche 2 : trames Modbus, aucun accès série ni Qt
    │   ├── records.py            FunctionCode, Request, ExchangeStatus, ExchangeRecord
    │   ├── crc.py                CRC16 Modbus (table précalculée)
    │   ├── exceptions.py         codes d'exception 01..0B + libellés FR/EN
    │   ├── pdu.py                build_request(Request) -> bytes ; parse_response(bytes) -> valeurs
    │   ├── codec.py              registres 16 bits <-> affichage (déc/hex/bin/signé/float, ordre des mots)
    │   └── master.py             RtuMaster : Request -> ExchangeRecord (orchestre transport + pdu)
    └── ui/                       ── couche 3 : Qt uniquement
        ├── main_window.py        fenêtre principale, disposition Modbus Doctor
        ├── widgets/
        │   ├── connection_bar.py  bandeau haut : config, RTU, résumé port, connexion/déconnexion, quitter
        │   ├── config_popup.py    popup BaudRate/DataBits/StopBits/Parity/Port/DTR/RTS/TimeOut/délai inter-trames
        │   ├── request_bar.py     N° esclave, registre, longueur, type (FC), adresse 4xxxxx, mode
        │   ├── actions_panel.py   LECTURE, ECRITURE, reconnexion auto, cyclique, inversions, non signé, mode d'affichage
        │   ├── register_grid.py   grille N° registre / valeur (édition -> écriture)
        │   └── log_console.py     console bas : horodatage, TX hexa, RX hexa, ms, erreur
        ├── models/
        │   └── register_model.py  QAbstractTableModel alimenté par les ExchangeRecord
        ├── workers.py            exécution des requêtes hors du thread Qt (QThread + signaux)
        └── i18n.py               libellés FR/EN (les deux drapeaux de Modbus Doctor)
```

Règle de dépendance, vérifiable par simple `grep` : `transport` n'importe rien du
projet ; `modbus` importe `transport.records` seulement ; `ui` importe
`modbus` et `transport` mais aucune des deux n'importe `ui` ni Qt.

## 2. Choix techniques à valider

### 2.1 pymodbus : utilisé pour vérifier, pas pour communiquer

Pour horodater chaque bloc d'octets, conserver les trames brutes (y compris
fausses) et préparer le mode passif, il faut posséder la boucle série. Le client
série de pymodbus la masque et son API interne (framers, PDU) change à chaque
version mineure.

Proposition : la pile RTU (CRC, PDU FC 01/02/03/04/05/06/15/16, découpage par
silence) est écrite dans le projet, soit environ 300 lignes couvertes par des
tests. pymodbus reste dans `requirements.txt` et sert d'**oracle dans les tests**
(comparaison des trames encodées et du CRC) et de solution de repli si un
équipement exotique pose problème plus tard.

Alternative si tu préfères : utiliser `pymodbus.pdu` pour encoder/décoder et ne
garder en propre que transport + framing. Je déconseille à cause de
l'instabilité d'API, mais c'est ton appel.

### 2.2 Découpage des trames par silence, dès le mode maître

Le maître pourrait se contenter de lire `N` octets attendus. On lit au contraire
jusqu'à un silence ≥ T3.5 (ou timeout). Avantages : on voit les octets
surnuméraires, les échos, les réponses tronquées ; et le même `RtuFramer` sert
tel quel au futur sniffer. Coût : chaque lecture dure au minimum T3.5 de plus
(1,8 ms à 19200 bauds), négligeable.

### 2.3 Mode passif préparé, non implémenté

`SerialLink` s'ouvre avec `allow_tx: bool`. En mode passif (`False`), `send()`
lève `TransmitNotAllowed`, RTS/DTR ne sont jamais pilotés, et `read_loop()`
produit des `RawFrame` en continu sans attendre de requête. Rien de cela n'est
codé en phase 1 au-delà du garde-fou et de la séparation framer / liaison.

### 2.4 Threads

Le port série est lu dans un `QThread` dédié (`ui/workers.py`) ; l'UI reçoit des
`ExchangeRecord` par signaux Qt. La couche transport et la couche modbus ignorent
totalement Qt : elles sont bloquantes et synchrones, c'est le worker qui les
isole.

### 2.5 Horodatage

`time.perf_counter_ns()` (monotone) pour toutes les durées ; `datetime.now()`
capturé une fois par trame pour l'affichage. Précision réelle limitée par l'OS
et l'adaptateur USB (1 à 16 ms par bloc), d'où la conservation des `ByteChunk`
plutôt qu'un faux horodatage par octet.

## 3. Dataclasses de la couche transport (`modbusai/transport/records.py`)

| Type | Rôle | Champs principaux |
|---|---|---|
| `Parity` (Enum) | parité, valeurs pyserial | `NONE="N"`, `EVEN="E"`, `ODD="O"` |
| `Direction` (Enum) | sens d'une trame | `TX`, `RX` |
| `LinkState` (Enum) | état de la liaison | `CLOSED`, `OPEN`, `ERROR` |
| `SerialSettings` (frozen) | paramètres liaison | `port`, `baudrate`, `bytesize`, `parity`, `stopbits`, `response_timeout_ms`, `inter_frame_delay_ms` (None = T3.5 normatif), `rts_toggle`, `dtr` ; propriétés `char_time_ms`, `t35_ms`, `t15_ms`, `summary()` |
| `ByteChunk` (frozen) | bloc lu en une fois | `data: bytes`, `t_ns: int` |
| `RawFrame` (frozen) | trame délimitée par silences | `direction`, `data`, `t_first_ns`, `t_last_ns`, `wall_time`, `chunks`, `silence_before_ns` ; propriétés `duration_ms`, `hex` |
| `PortInfo` (frozen) | port COM détecté | `device`, `description`, `hwid` |
| `LinkCounters` | compteurs bruts depuis l'ouverture | `frames_tx/rx`, `bytes_tx/rx`, `io_errors`, `opened_at` |
| `TransportError`, `TransmitNotAllowed` | exceptions | |

Contrat de `SerialLink` (implémenté en phase 1, signature figée maintenant) :

```python
class SerialLink:
    def __init__(self, settings: SerialSettings, *, allow_tx: bool = True): ...
    def open(self) -> None
    def close(self) -> None
    @property
    def state(self) -> LinkState
    def send(self, data: bytes) -> RawFrame                 # lève TransmitNotAllowed en passif
    def receive(self, timeout_ms: float) -> RawFrame | None  # None = rien reçu (timeout)
    def read_loop(self, stop: threading.Event) -> Iterator[RawFrame]  # base du futur sniffer
```

## 4. Enregistrement d'échange (`modbusai/modbus/records.py`)

| Type | Champs |
|---|---|
| `FunctionCode` (IntEnum) | `0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0F, 0x10` |
| `Request` (frozen) | `slave_id`, `function`, `address` (base 0), `count`, `values` |
| `ExchangeStatus` (Enum) | `OK`, `TIMEOUT`, `CRC_ERROR`, `MODBUS_EXCEPTION`, `BAD_RESPONSE`, `TRANSPORT_ERROR` |
| `ExchangeRecord` (frozen) | `seq`, `timestamp`, `request`, `settings` (instantané), `tx_frame`, `rx_frame`, `status`, `response_time_ms` (fin TX → premier octet RX), `exception_code`, `error_message`, `values` |

`BAD_RESPONSE` couvre le cas « CRC juste mais réponse incohérente » (mauvais
esclave, mauvais code fonction, longueur fausse) : distinct de `CRC_ERROR`, car
la cause probable n'est pas la même (adressage en double vs bruit / bauds).

L'instantané `settings` dans chaque enregistrement permettra au diagnostic de
comparer des campagnes faites à des vitesses ou timeouts différents.

## 5. Correspondance avec Modbus Doctor (pour l'UI, phase suivante)

| Modbus Doctor | Comportement reproduit |
|---|---|
| Type `1 Coil status … 4 Input registers` | choix du FC de lecture 01..04 ; l'écriture choisit 05/06 si longueur 1, 15/16 sinon |
| `Adresse : 400001` | affichage 1-based préfixé (0/1/3/4 selon type), le protocole reste base 0 |
| `Mode DECIMAL` | décimal / hexadécimal / binaire |
| `Mode d'affichage` | champ de bits / octet 8 bits / mot 16 bits / mot 32 bits / flottant |
| `Inversion Octets` / `Inversion Mots` | ordre des mots ABCD / CDAB / BADC / DCBA (mots activé seulement en 32 bits et flottant) |
| `Non signé` | signé / non signé |
| `Cyclique` + `…` | lecture périodique, intervalle en ms |
| `Reconnexion auto` | réouverture du port si erreur transport |
| `MODE ESPION` | bouton présent mais désactivé (phase ultérieure) |
| `Status :` | console de log : horodatage, TX hexa, RX hexa, ms, erreur |

## 6. Points sur lesquels j'attends ta validation

1. Pile RTU en propre avec pymodbus en oracle de test (2.1), ou pymodbus pour les PDU ?
2. Nom du paquet `modbusai` (aligné sur le dépôt) : OK ?
3. `response_time_ms` mesuré de la fin d'émission au premier octet reçu : c'est
   la définition la plus utile pour caractériser un esclave. Alternative : début
   d'émission → dernier octet reçu (temps de transaction). Je peux stocker les
   deux si tu veux.
4. Interface FR/EN via `i18n.py` comme Modbus Doctor, ou FR seul en phase 1 ?
