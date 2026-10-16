"""Prueba rápida de las 5 tools sin levantar MCP. Uso:
    LA_COSECHA_DB=ruta/a/la_cosecha_practica.db python probar_tools.py
"""
import json
import sqlite3

import server as s


def mostrar(titulo, r, max_chars=1800):
    txt = json.dumps(r, ensure_ascii=False, indent=2, default=str)
    print(f"\n=== {titulo} ===\n{txt[:max_chars]}{'...' if len(txt) > max_chars else ''}")


con = sqlite3.connect(s.DB_PATH)
sku, desc = con.execute("SELECT p.sku, p.descripcion FROM productos p JOIN pedido_detalle d ON d.sku = p.sku "
                        "GROUP BY p.sku ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
palabra = desc.split()[0].lower()
cli = con.execute("SELECT cliente_id FROM clientes WHERE estatus_credito <> 'bloqueado' LIMIT 1").fetchone()[0]

mostrar("1. busca_cliente (producto + zona)", s.busca_cliente(producto=palabra, ubicacion="LEO", limite=3))
mostrar("1b. busca_cliente (contexto libre + tipo)", s.busca_cliente(consulta=f"necesita {palabra} para cocina", tipo="restaurante", limite=3))
mostrar("2. checa_inventario por_caducar", s.checa_inventario(modo="por_caducar", dias_horizonte=15, limite=3))
mostrar("2b. checa_inventario mas_antiguo", s.checa_inventario(producto=palabra, modo="mas_antiguo", limite=3))
mostrar("2c. checa_inventario existencias", s.checa_inventario(producto=palabra, cedis="QRO", limite=3))
mostrar("3. calcula_precio", s.calcula_precio(producto=palabra, cantidad=10, cliente_id=cli, descuento_pct=10, margen_minimo_pct=20, limite=1))
mostrar("4. oportunidades_rotacion", s.oportunidades_rotacion(max_productos=2, clientes_por_producto=3, margen_minimo_pct=15), 2600)

# 5. HITL: paso 1 no escribe; paso 2 sin token falla; paso 2 con token escribe una sola vez
op = s.oportunidades_rotacion(max_productos=1, clientes_por_producto=1)["oportunidades"][0]
c = op["candidatos"][0]
datos = dict(cliente_id=c["cliente_id"], sku=op["sku"], cantidad=c["cantidad_sugerida"],
             tipo_oportunidad="rotacion_caducidad", justificacion="Lote por caducar; el cliente ya lo compra.",
             margen_estimado_mxn=c["margen_potencial_mxn"] or 0)
p1 = s.registra_oportunidad(**datos)
mostrar("5a. registra_oportunidad paso 1 (no escribe)", p1)
mostrar("5b. token falso", s.registra_oportunidad(**datos, token="falso", aprobado_por="Ana"))
mostrar("5c. sin aprobador", s.registra_oportunidad(**datos, token=p1["token"]))
mostrar("5d. aprobada", s.registra_oportunidad(**datos, token=p1["token"], aprobado_por="Ana"))
mostrar("5e. mismo token otra vez", s.registra_oportunidad(**datos, token=p1["token"], aprobado_por="Ana"))
print("\nFilas en bitácora:", sqlite3.connect(s.LOG_DB_PATH).execute("SELECT COUNT(*) FROM oportunidades_agente").fetchone()[0])
