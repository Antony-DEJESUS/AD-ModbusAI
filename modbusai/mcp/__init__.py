"""Serveur MCP : le bus Modbus vu comme des outils, pour un assistant.

Le Model Context Protocol permet à un assistant (Claude Code, Claude Desktop)
d'appeler des outils plutôt que de lire un rapport collé à la main : lire un
registre, scanner le bus, lancer une campagne, puis enchaîner le test qui
départage les hypothèses. La boucle de diagnostic que le fichier texte
simulait devient réelle.

Cette couche est un client des trois autres, au même titre que ``ui`` : elle
compose des requêtes, ordonnance des travaux et met en forme. Elle ne décide
de rien et n'importe pas Qt.
"""

from modbusai.mcp.protocol import Dispatcher, Tool, ToolError
from modbusai.mcp.service import ModbusService

__all__ = ["Dispatcher", "ModbusService", "Tool", "ToolError"]
