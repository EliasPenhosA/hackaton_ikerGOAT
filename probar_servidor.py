"""Se conecta a servidor_mcp.py como lo haría cualquier cliente, muestra el menú y prueba una herramienta.

Uso:  python probar_servidor.py clientes
      (cuando agreguen sus herramientas, cambien la llamada de prueba de abajo)
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVIDOR = Path(__file__).resolve().parent / "servidor_mcp.py"


async def main(consulta: str):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVIDOR)])
    async with stdio_client(params) as (leer, escribir):
        async with ClientSession(leer, escribir) as sesion:
            info = await sesion.initialize()
            servidor = getattr(info, "server_info", None) or getattr(info, "serverInfo", None)  # SDK 2.x / 1.x
            print(f"✅ Conectado a '{servidor.name}'\n")
            print("Menú de herramientas (lo único que ve el modelo):")
            for t in (await sesion.list_tools()).tools:
                linea = (t.description or "(sin descripción)").strip().splitlines()[0]
                esquema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                params_ = ", ".join(esquema.get("properties", {}))
                print(f"  • {t.name}({params_})\n      {linea}")
            print(f"\nPrueba: describir_tabla(tabla={consulta!r})")
            r = await sesion.call_tool("describir_tabla", {"tabla": consulta})
            print(r.content[0].text[:800])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "clientes"))
