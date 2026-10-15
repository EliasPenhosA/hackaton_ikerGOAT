"""Conexión a la base de La Cosecha del Bajío (SQLite).

Dentro del agente:      from .db import consultar, ejecutar
Desde un script suelto: from agente.db import consultar, ejecutar

La ruta sale de LA_COSECHA_DB en agente/.env. Si es relativa, se toma desde la carpeta del kit.
"""

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = AGENT_DIR.parent
load_dotenv(AGENT_DIR / ".env")

_ruta = Path(os.getenv("LA_COSECHA_DB", "la_cosecha_practica.db"))
DB_PATH = _ruta if _ruta.is_absolute() else PROJECT_DIR / _ruta


def consultar(sql: str, params: tuple = ()) -> list[dict]:
    """Ejecuta una consulta de sólo lectura y regresa una lista de diccionarios."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"No encuentro la base en {DB_PATH}. Revisa LA_COSECHA_DB en agente/.env")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def ejecutar(sql: str, params: tuple = ()) -> int:
    """Ejecuta un INSERT, UPDATE o DELETE y regresa cuántas filas cambió.
    Hagan una copia de la base antes de usarla."""
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur.rowcount
    finally:
        con.close()


if __name__ == "__main__":
    print(DB_PATH)
    print(consultar("SELECT COUNT(*) AS clientes FROM clientes"))
    print(consultar("SELECT p.pedido_id, p.fecha, d.sku, pr.descripcion, d.cantidad FROM pedidos p JOIN pedido_detalle d USING(pedido_id) JOIN productos pr USING(sku) WHERE p.cliente_id = 'C10007' ORDER BY p.fecha DESC LIMIT 20;"))
    print(consultar("SELECT * FROM proveedores"))