"""Servidor MCP de La Cosecha del Bajío (plantilla).

Expone herramientas a cualquier cliente MCP: su agente de ADK, Claude Desktop, VS Code…
Igual que en el Lab 7: no reescriban las herramientas, impórtenlas y regístrenlas.

Prueba:   python probar_servidor.py clientes
Ojo:      un servidor stdio habla por la salida estándar; un print() rompe la conexión.
          Para depurar, impriman en sys.stderr.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # para importar el paquete agente/

from agente.agent import describir_tabla  # noqa: E402

try:  # SDK de MCP 2.x
    from mcp.server import MCPServer as _Server
except ImportError:  # SDK de MCP 1.x
    from mcp.server.fastmcp import FastMCP as _Server

# TODO: expliquen en las instrucciones qué contiene este servidor, para un cliente que no sabe nada
# de La Cosecha (qué datos hay, de qué fecha son, cómo citar, qué no debe hacer).
servidor = _Server(
    name="la-cosecha",
    instructions=(
        "Documentos internos y datos de Distribuidora La Cosecha del Bajío (distribuidora de alimentos, "
        "León, Gto.). Fecha de corte de los datos: 30 de septiembre de 2026. "
        "TODO: completen la descripción."
    ),
)

servidor.add_tool(describir_tabla)  # ejemplo

# TODO: registren aquí sus propias herramientas, p. ej.
# from agente.agent import facturas_abiertas
# servidor.add_tool(facturas_abiertas)

if __name__ == "__main__":
    servidor.run()  # stdio por defecto
