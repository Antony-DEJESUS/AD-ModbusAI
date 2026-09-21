# Serveur MCP : brancher un assistant sur le bus

Le serveur MCP expose le bus Modbus comme un jeu d'outils qu'un assistant
appelle lui-même. Au lieu d'exporter un rapport et de le coller dans une
conversation, l'assistant lit un registre, scanne les adresses, lance une
campagne, lit les hypothèses, puis enchaîne le test qui les départage. C'est la
boucle de diagnostic du logiciel, sans l'écran.

L'application et le serveur restent deux programmes distincts. Rien n'oblige à
utiliser les deux, et le serveur ne remplace pas la fenêtre : il l'ouvre à un
autre opérateur.

## Ce qu'il faut sur la machine

Le serveur tourne sur **la machine branchée au bus** : celle qui a l'adaptateur
USB / RS-485, ou celle qui atteint la passerelle Modbus TCP. Deux façons de le
lancer :

```
AD-ModbusAI-MCP_v1.1.0.exe            l'exécutable, rien à installer
python -m modbusai.mcp                depuis les sources
```

Sans option, il attend un client sur son entrée standard et n'ouvre aucun port.

## Mode local : Claude Code sur le poste de chantier

C'est le cas le plus simple. Claude Code lance le serveur lui-même, lui parle
par des tubes, et l'arrête en fin de session. Rien n'écoute sur le réseau.

```
claude mcp add modbusai -- "C:\\Outils\\AD-ModbusAI-MCP_v1.1.0.exe"
```

Pour autoriser l'écriture sur le bus et le serveur esclave simulé :

```
claude mcp add modbusai -- "C:\\Outils\\AD-ModbusAI-MCP_v1.1.0.exe" --ecriture
```

Vérification : `claude mcp list` doit montrer `modbusai` connecté. Demandez
ensuite « quels ports série vois-tu ? » : l'assistant appelle `list_ports`.

## Mode à distance : Tailscale

Le poste reste sur site, branché au bus ; vous diagnostiquez depuis le bureau.
Le serveur écoute alors en HTTP, **sur son adresse Tailscale uniquement** :

```
AD-ModbusAI-MCP_v1.1.0.exe --http 100.87.1.4:8765 --jeton MonJetonLong
```

Depuis la machine distante, elle aussi sur le tailnet :

```
claude mcp add --transport http modbusai http://100.87.1.4:8765/mcp \
  --header "Authorization: Bearer MonJetonLong"
```

Au premier lancement, Windows demande d'autoriser l'écoute dans son pare-feu :
acceptez pour les réseaux privés, refusez pour les réseaux publics.

L'adresse `100.x.y.z` se lit avec `tailscale ip -4` sur le poste de chantier.
Les règles d'accès de Tailscale décident qui peut atteindre ce port ; le jeton
est une seconde barrière, utile quand plusieurs personnes partagent le tailnet.

Ce mode ne fonctionne qu'avec un Claude Code ou un Claude Desktop **installé
sur une machine du tailnet**. Une session dans le navigateur tourne dans le
nuage et ne voit pas votre réseau privé ; l'exposer publiquement pour y remédier
serait une mauvaise idée, ce serveur parle à des automates.

## Les garde-fous

| Garde-fou | Ce qu'il fait |
|---|---|
| Lecture seule par défaut | Sans `--ecriture`, les outils `write`, `slave_start`, `slave_stop` et `slave_set` ne sont pas proposés à l'assistant. Un outil absent vaut mieux qu'un outil qui refuse. |
| Écoute locale par défaut | `--http` sans adresse écoute sur 127.0.0.1. Exposer sur une autre adresse est un choix explicite, et le serveur le signale s'il n'y a pas de jeton. |
| Jeton partagé | `--jeton` exige un en-tête `Authorization: Bearer`. |
| Origine refusée | Une requête portant un en-tête `Origin` étranger est rejetée : c'est la parade au détournement DNS depuis un navigateur. |
| Un port, un rôle | Le serveur MCP obéit au même arbitrage que la fenêtre : il refuse d'ouvrir un port déjà tenu, en nommant ce qui l'occupe. |

## Les outils

| Outil | Ce qu'il fait |
|---|---|
| `list_ports` | Ports série présents sur la machine. |
| `connect`, `disconnect`, `status` | Liaison du maître, en RTU ou en TCP. |
| `read` | Lit registres ou bits. Un format multi-registres affiche les quatre ordres de mots. |
| `write` | Écrit une ou plusieurs valeurs. Soumis à `--ecriture`. |
| `identify` | FC43 puis FC17 sur un esclave. |
| `scan` | Cherche les équipements sur une plage d'adresses, avec balayage des vitesses en option. |
| `sniff` | Écoute passive du bus, sans jamais émettre. Sur son propre port avec un second adaptateur, le maître reste connecté. RTU uniquement. |
| `campaign` | Répète une lecture pendant une durée : c'est ainsi qu'on voit un défaut intermittent. |
| `stress_test` | Enchaîne les phases de torture et les compare. |
| `job_status`, `job_stop` | Avancement et arrêt du travail en cours. |
| `analyse` | Statistiques par esclave et hypothèses classées, avec les tests qui départagent. |
| `run_test` | Exécute un test proposé et le compare à la référence : défauts disparus, réduits, inchangés ou aggravés. |
| `report` | Le rapport texte complet, celui qu'exporte l'application. |
| `clear_history` | Efface les observations. |
| `catalogue` | Les fiches d'hypothèses : déclencheur, causes, confirmations. |
| `slave_start`, `slave_stop`, `slave_set`, `slave_table` | Simulateur d'équipement et ses tables. |

## Écouter sans interrompre le maître

Par défaut, `sniff` reprend le port du maître : cette liaison est fermée le
temps de l'écoute, puis rouverte. Avec un second adaptateur USB / RS-485
branché en parallèle sur le bus, donnez son port à `sniff` : les deux rôles
cohabitent alors, le maître continue d'interroger pendant que l'espion regarde
passer tout le trafic, y compris celui de la GTB.

## Les travaux longs

Un scan, une campagne, un test de torture ou une écoute durent des minutes. Ces
outils rendent la main tout de suite et le travail continue en fond ; `wait_s`
permet d'attendre la fin quand elle est proche. Pendant ce temps, les autres
outils du bus sont refusés en nommant ce qui occupe la liaison, et `job_stop`
interrompt en rendant le résultat partiel.

## Ce que l'assistant doit savoir

Le serveur lui donne ses consignes à la connexion : les adresses sont en base 0,
une exception Modbus est une réponse valide et non une panne, un port ne sert
qu'à un rôle à la fois, et les phases à défauts provoqués sont exclues des
statistiques. Ces règles sont les mêmes que dans le mode d'emploi ; elles
viennent du code, pas d'une copie.

## Une session type

1. `connect` avec le port et la vitesse du bus.
2. `scan` sur 1 à 32 pour savoir qui répond.
3. `read` sur l'esclave visé pour vérifier une valeur, format `flottant32` si la
   valeur affichée est absurde.
4. `campaign` de deux minutes sur le registre suspect.
5. `analyse` : les hypothèses arrivent classées, avec leurs tests.
6. `run_test` avec la clé du test proposé : une campagne aux réglages modifiés,
   comparée à la référence, et un verdict. Un test qui demande une action sur
   le bus (inverser A et B, débrancher un esclave) est refusé en disant quoi
   faire.
7. `report` pour garder la trace, à archiver avec le compte rendu d'intervention.
