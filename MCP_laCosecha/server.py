"""
Servidor MCP de La Cosecha del Bajío (FastMCP, transporte stdio).

Tools:
  1. busca_cliente          - recupera el/los clientes más adecuados (retrieval estilo RAG: BM25 + filtros + evidencia de compra)
  2. checa_inventario       - existencias, lotes próximos a caducar o lotes que llevan más tiempo en almacén
  3. calcula_precio         - precio vigente consultado en vivo a la base + precios realmente cobrados + simulación de margen
  4. oportunidades_rotacion - cruza inventario por caducar con clientes que lo comprarían (recompra / venta cruzada)
  5. registra_oportunidad   - escribe la oportunidad aprobada/rechazada; NO escribe sin token + nombre de quien aprueba (HITL)

Variables de entorno (todas opcionales):
  LA_COSECHA_DB            ruta de la base (default: la_cosecha_practica.db)
  LA_COSECHA_FECHA_CORTE   fecha "de hoy" del caso, AAAA-MM-DD. Si no se define se usa la fecha más reciente de `pedidos`.
                           Con la base real: 2026-09-30.
  LA_COSECHA_LOG_DB        archivo donde se guardan las oportunidades (default: oportunidades_agente.db junto a este script).
                           Es un archivo aparte: la base de La Cosecha siempre se abre en modo sólo lectura.
  LA_COSECHA_SECRET        llave para firmar los tokens de aprobación (default: aleatoria por proceso)

Conexión desde ADK (stdio) con aprobación humana real (HITL):
  from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
  from mcp import StdioServerParameters

  def pide_aprobacion(token: str = "", **kwargs) -> bool:
      return bool(token)   # `token` sólo viaja en el paso 2 de registra_oportunidad, que es el que escribe

  McpToolset(
      connection_params=StdioConnectionParams(server_params=StdioServerParameters(
          command="python", args=["mcp_la_cosecha/server.py"],
          env={"LA_COSECHA_DB": "...", "LA_COSECHA_FECHA_CORTE": "2026-09-30"})),
      require_confirmation=pide_aprobacion)   # confirmación de ADK (experimental, requiere ADK >= 1.14)

Sin ese require_confirmation el modelo podría llamar los dos pasos seguidos: el token sólo evita datos alterados,
la aprobación humana la impone ADK.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # mcp 1.x (lo que suele traer google-adk)
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp 2.x renombró FastMCP a MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP

mcp = FastMCP("la-cosecha")

DB_PATH = os.environ.get("LA_COSECHA_DB", "la_cosecha_practica.db")
LOG_DB_PATH = os.environ.get("LA_COSECHA_LOG_DB", str(Path(__file__).with_name("oportunidades_agente.db")))
_SECRET = (os.environ.get("LA_COSECHA_SECRET") or secrets.token_hex(16)).encode()

CEDIS_VALIDOS = {"LEO", "QRO", "AGS"}
TIPOS_CLIENTE = {"tiendita", "restaurante_hotel", "institucional", "cadena"}
ALIAS_CEDIS = {"leon": "LEO", "queretaro": "QRO", "aguascalientes": "AGS"}
STOP = {"de", "la", "el", "los", "las", "para", "con", "en", "y", "que", "un", "una", "por", "del", "al",
        "cliente", "clientes", "quiero", "busco", "buscar", "mejor", "mas", "adecuado", "producto", "productos"}


# ───────────────────────────── utilidades ─────────────────────────────

def _fold(s: Any) -> str:
    """Minúsculas y sin acentos, para comparar 'León' con 'leon'."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


def _tokens(texto: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", _fold(texto)) if len(t) >= 2 and t not in STOP]


def _conn() -> sqlite3.Connection:
    p = Path(DB_PATH)
    if not p.is_file():
        raise FileNotFoundError(f"No encuentro la base en '{DB_PATH}'. Define LA_COSECHA_DB.")
    conn = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)  # sólo lectura
    conn.row_factory = sqlite3.Row
    conn.create_function("fold", 1, _fold)
    return conn


def _fecha_corte(conn: sqlite3.Connection) -> str:
    f = os.environ.get("LA_COSECHA_FECHA_CORTE")
    if f:
        return f
    r = conn.execute("SELECT MAX(fecha) AS f FROM pedidos").fetchone()
    return (r["f"] if r and r["f"] else "2026-09-30")


def _margen_pct(precio: float | None, costo: float | None) -> float | None:
    if precio and costo is not None and precio > 0:
        return round((precio - costo) / precio * 100, 1)
    return None


def _descuento_max_pct(precio: float | None, costo: float | None, margen_min_pct: float) -> float | None:
    """Mayor descuento sobre lista que todavía respeta el margen mínimo."""
    if not precio or costo is None or margen_min_pct <= 0 or margen_min_pct >= 100:
        return None
    return round(max(0.0, 1 - costo / ((1 - margen_min_pct / 100) * precio)) * 100, 1)


def _riesgo(dias_para_caducar: int | None) -> str:
    if dias_para_caducar is None:
        return "sin_fecha"
    if dias_para_caducar < 0:
        return "vencido"
    if dias_para_caducar <= 7:
        return "critico"
    if dias_para_caducar <= 15:
        return "alto"
    if dias_para_caducar <= 30:
        return "medio"
    return "normal"


def _validar_cedis(cedis: str) -> tuple[str | None, str | None]:
    c = (cedis or "").strip().upper()
    if not c:
        return None, None
    if c not in CEDIS_VALIDOS:
        return None, f"CEDIS inválido '{cedis}'. Usa LEO, QRO o AGS."
    return c, None


def _producto_publico(p: dict) -> dict:
    """Datos de producto que se pueden mostrar. El costo unitario es confidencial y nunca sale."""
    pub = {k: p.get(k) for k in ("sku", "descripcion", "categoria", "subcategoria", "marca",
                                 "presentacion", "unidad_venta", "piezas_por_unidad", "precio_lista")}
    pub["activo"] = bool(p.get("activo", 1))
    return pub


def _buscar_productos(conn: sqlite3.Connection, texto: str, limite: int = 10, solo_activos: bool = True) -> list[dict]:
    """Resuelve un SKU exacto o texto libre ('mayonesa', 'aceite 1 litro') a productos."""
    texto = (texto or "").strip()
    if not texto:
        return []
    exacto = conn.execute("SELECT * FROM productos WHERE upper(sku) = upper(?)", (texto,)).fetchall()
    if exacto:
        return [dict(r) for r in exacto]
    toks = _tokens(texto)
    if not toks:
        return []
    campo = ("fold(coalesce(descripcion,'')||' '||coalesce(categoria,'')||' '||"
             "coalesce(subcategoria,'')||' '||coalesce(marca,''))")
    activo = " AND coalesce(activo,1) = 1" if solo_activos else ""
    pats = [f"%{t}%" for t in toks]
    rows = conn.execute(
        f"SELECT * FROM productos WHERE {' AND '.join([campo + ' LIKE ?'] * len(toks))}{activo} "
        f"ORDER BY sku LIMIT ?", pats + [limite]).fetchall()
    if not rows and len(toks) > 1:  # ningún producto cumple todas las palabras → los que cumplan más
        score = " + ".join([f"({campo} LIKE ?)" for _ in toks])
        rows = conn.execute(
            f"SELECT *, ({score}) AS _s FROM productos WHERE ({score}) > 0{activo} "
            f"ORDER BY _s DESC, sku LIMIT ?", pats + pats + [limite]).fetchall()
    return [dict(r) for r in rows]


# ───────────────── índice de clientes (para busca_cliente) ─────────────────

_PERFILES: dict[str, Any] = {"clave": None, "data": None}


def _cargar_perfiles(conn: sqlite3.Connection) -> dict:
    """Perfil por cliente: ficha + lo que compra + texto indexado (BM25). Se cachea mientras la base no cambie."""
    clave = (DB_PATH, os.path.getmtime(DB_PATH))
    if _PERFILES["clave"] == clave:
        return _PERFILES["data"]

    clientes = {}
    for r in conn.execute("""SELECT cliente_id, nombre, tipo, contacto, telefono_whatsapp, cedis, ciudad, colonia,
                                    estatus_credito, condicion_pago, linea_credito FROM clientes"""):
        c = dict(r)
        c["_ciudad"], c["_colonia"] = _fold(c["ciudad"]), _fold(c["colonia"])
        clientes[c["cliente_id"]] = c

    totales = {r["cliente_id"]: dict(r) for r in conn.execute(
        "SELECT cliente_id, COUNT(*) AS pedidos, SUM(total) AS importe, MAX(fecha) AS ultima FROM pedidos GROUP BY cliente_id")}

    compras: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in conn.execute("""
        SELECT p.cliente_id, d.sku, pr.descripcion, pr.categoria, pr.subcategoria,
               COUNT(DISTINCT p.pedido_id) AS n_pedidos, SUM(d.cantidad) AS qty,
               SUM(d.importe) AS importe, MAX(p.fecha) AS ultima
        FROM pedidos p JOIN pedido_detalle d ON d.pedido_id = p.pedido_id
        JOIN productos pr ON pr.sku = d.sku GROUP BY p.cliente_id, d.sku"""):
        compras[r["cliente_id"]][r["sku"]] = dict(r)

    tf: dict[str, Counter] = {}
    df: Counter = Counter()
    for cid, c in clientes.items():
        toks = _tokens(" ".join(str(c[k] or "") for k in ("nombre", "tipo", "ciudad", "colonia", "cedis")))
        vistos = set()
        for v in compras.get(cid, {}).values():
            for campo in ("categoria", "subcategoria", "descripcion"):
                if v[campo] and (campo, v[campo]) not in vistos:
                    vistos.add((campo, v[campo]))
                    toks += _tokens(v[campo])
        tf[cid] = Counter(toks)
        df.update(tf[cid].keys())
    n = max(len(clientes), 1)
    avgdl = sum(sum(t.values()) for t in tf.values()) / n or 1.0

    data = {"clientes": clientes, "totales": totales, "compras": compras, "tf": tf, "df": df, "N": n, "avgdl": avgdl}
    _PERFILES.update(clave=clave, data=data)
    return data


def _bm25(q: list[str], tf: Counter, df: Counter, n: int, avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    dl = sum(tf.values()) or 1
    s = 0.0
    for t in set(q):
        f = tf.get(t, 0)
        if f:
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / avgdl))
    return s


def _filtro_ubicacion(clientes: dict, ubicacion: str, notas: list[str]) -> set[str] | None:
    u = _fold(ubicacion).strip()
    if not u:
        return None
    if u.upper() in CEDIS_VALIDOS:
        return {i for i, c in clientes.items() if c["cedis"] == u.upper()}
    m = {i for i, c in clientes.items() if u in c["_ciudad"] or u in c["_colonia"]}
    if m:
        return m
    if u in ALIAS_CEDIS:
        return {i for i, c in clientes.items() if c["cedis"] == ALIAS_CEDIS[u]}
    notas.append(f"No encontré clientes en '{ubicacion}' (ciudad, colonia o CEDIS); ignoré ese filtro.")
    return None


# ─────────────────────────────── TOOL 1 ───────────────────────────────

@mcp.tool()
def busca_cliente(consulta: str = "", producto: str = "", ubicacion: str = "", tipo: str = "",
                  excluir_bloqueados: bool = True, limite: int = 10) -> dict:
    """Encuentra los clientes más adecuados según contexto, ubicación y/o tipo de producto.

    Funciona como recuperación (RAG) sobre perfiles de cliente: indexa nombre, tipo, zona y lo que cada
    cliente ha comprado, y ordena por relevancia con evidencia de compra real. Cada resultado trae las
    razones por las que se recomienda.

    Args:
        consulta: contexto en lenguaje natural ("restaurantes que usan mucho aceite y lácteos").
        producto: SKU o texto del producto de interés ("mayonesa"). Premia a quien ya lo compra o compra su subcategoría.
        ubicacion: CEDIS (LEO, QRO, AGS), ciudad o colonia. Es un filtro duro.
        tipo: tiendita, restaurante_hotel, institucional o cadena. Es un filtro duro.
        excluir_bloqueados: True (default) deja fuera clientes con crédito bloqueado.
        limite: máximo de clientes a regresar (1-25).
    """
    notas: list[str] = []
    limite = max(1, min(int(limite), 25))
    if not any((consulta.strip(), producto.strip(), ubicacion.strip(), tipo.strip())):
        return {"error": "Indica al menos un criterio: consulta, producto, ubicacion o tipo."}

    tipo_f = _fold(tipo).strip().replace(" ", "_")
    if tipo_f:
        match = [t for t in TIPOS_CLIENTE if tipo_f in t]
        if len(match) != 1:
            return {"error": f"Tipo '{tipo}' no válido. Opciones: {sorted(TIPOS_CLIENTE)}."}
        tipo_f = match[0]

    with closing(_conn()) as conn:
        corte = _fecha_corte(conn)
        P = _cargar_perfiles(conn)
        clientes, compras = P["clientes"], P["compras"]

        prods = _buscar_productos(conn, producto, 40, solo_activos=False) if producto.strip() else []
        if producto.strip() and not prods:
            notas.append(f"No encontré productos que coincidan con '{producto}'.")
        skus = {p["sku"] for p in prods}
        subcats = {p["subcategoria"] for p in prods if p["subcategoria"]}

    candidatos = set(clientes)
    ub = _filtro_ubicacion(clientes, ubicacion, notas)
    if ub is not None:
        candidatos &= ub
    if tipo_f:
        candidatos = {i for i in candidatos if clientes[i]["tipo"] == tipo_f}
    if excluir_bloqueados:
        candidatos = {i for i in candidatos if clientes[i]["estatus_credito"] != "bloqueado"}
    if not candidatos:
        return {"fecha_corte": corte, "n_candidatos": 0, "resultados": [], "notas": notas + ["Ningún cliente cumple los filtros."]}

    q = _tokens(f"{consulta} {producto}")
    bm = {i: _bm25(q, P["tf"][i], P["df"], P["N"], P["avgdl"]) for i in candidatos} if q else {}
    maxbm = max(bm.values(), default=0) or 1.0

    ranking = []
    for cid in candidatos:
        c, razones, score = clientes[cid], [], 0.0
        if q and bm[cid] > 0:
            score += 5 * bm[cid] / maxbm
            coinciden = sorted(t for t in set(q) if P["tf"][cid].get(t))
            razones.append(f"Su perfil coincide con: {', '.join(coinciden)}")
        if skus:
            hits = [v for s, v in compras[cid].items() if s in skus]
            if hits:
                qty = sum(h["qty"] or 0 for h in hits)
                mejor = max(hits, key=lambda h: h["qty"] or 0)
                score += 4 + min(2.0, math.log1p(qty))
                extra = f" y {len(hits) - 1} producto(s) más que coinciden" if len(hits) > 1 else ""
                razones.append(f"Ya compra {mejor['descripcion']}: {mejor['qty']:g} u. en {mejor['n_pedidos']} pedido(s), "
                               f"última {max(h['ultima'] for h in hits)}{extra}")
            elif subcats and any(v["subcategoria"] in subcats for v in compras[cid].values()):
                score += 1.5
                razones.append("Compra productos de la misma subcategoría")
        t = P["totales"].get(cid)
        if not q and not skus:  # sólo filtros: ordenar por tamaño de cuenta
            score += math.log1p((t or {}).get("importe") or 0)
            razones.append("Ordenado por importe comprado en el periodo")
        if ub is not None:
            razones.append(f"Zona: {c['ciudad']}/{c['colonia']} (CEDIS {c['cedis']})")
        if tipo_f:
            razones.append(f"Tipo: {c['tipo']}")
        top = sorted(compras[cid].values(), key=lambda v: v["importe"] or 0, reverse=True)[:3]
        ranking.append((score, cid, razones, t, top))
    ranking.sort(key=lambda x: (-x[0], x[1]))

    resultados = []
    for score, cid, razones, t, top in ranking[:limite]:
        c = clientes[cid]
        resultados.append({
            "cliente_id": cid, "nombre": c["nombre"], "tipo": c["tipo"], "cedis": c["cedis"],
            "ciudad": c["ciudad"], "colonia": c["colonia"], "contacto": c["contacto"],
            "telefono_whatsapp": c["telefono_whatsapp"], "estatus_credito": c["estatus_credito"],
            "score": round(score, 2), "razones": razones,
            "evidencia": {"pedidos_periodo": (t or {}).get("pedidos", 0),
                          "importe_periodo": round((t or {}).get("importe") or 0, 2),
                          "ultima_compra": (t or {}).get("ultima"),
                          "productos_principales": [f"{v['descripcion']} ({v['qty']:g} u.)" for v in top]},
        })
    return {"fecha_corte": corte, "n_candidatos": len(candidatos), "resultados": resultados, "notas": notas}


# ─────────────────────────────── TOOL 2 ───────────────────────────────

@mcp.tool()
def checa_inventario(producto: str = "", cedis: str = "", categoria: str = "", modo: str = "existencias",
                     dias_horizonte: int = 15, solo_refrigerados: bool = False, limite: int = 20) -> dict:
    """Consulta el inventario por lotes.

    Args:
        producto: SKU o texto del producto (opcional).
        cedis: LEO, QRO o AGS (opcional; vacío = todos).
        categoria: filtra por categoría o subcategoría (opcional).
        modo: 'existencias' (cuánto hay por SKU y CEDIS), 'por_caducar' (lotes que caducan dentro de
              dias_horizonte, incluye ya vencidos) o 'mas_antiguo' (lotes que llevan más tiempo en almacén).
        dias_horizonte: ventana para 'por_caducar' (default 15).
        solo_refrigerados: sólo productos refrigerados.
        limite: máximo de filas a regresar (1-100). El resumen siempre cubre todo lo filtrado.
    """
    modo = _fold(modo).strip()
    if modo not in {"existencias", "por_caducar", "mas_antiguo"}:
        return {"error": "modo debe ser 'existencias', 'por_caducar' o 'mas_antiguo'."}
    ced, err = _validar_cedis(cedis)
    if err:
        return {"error": err}
    limite = max(1, min(int(limite), 100))

    with closing(_conn()) as conn:
        corte = _fecha_corte(conn)
        where, params = ["l.cantidad > 0"], {"corte": corte}
        if ced:
            where.append("l.cedis = :cedis"); params["cedis"] = ced
        if producto.strip():
            prods = _buscar_productos(conn, producto, 50, solo_activos=False)
            if not prods:
                return {"fecha_corte": corte, "resultados": [], "nota": f"No encontré productos que coincidan con '{producto}'."}
            nombres = {}
            for i, p in enumerate(prods):
                nombres[f"s{i}"] = p["sku"]
            where.append("l.sku IN (" + ",".join(f":{k}" for k in nombres) + ")")
            params.update(nombres)
        if categoria.strip():
            where.append("(fold(pr.categoria) LIKE :cat OR fold(pr.subcategoria) LIKE :cat)")
            params["cat"] = f"%{_fold(categoria).strip()}%"
        if solo_refrigerados:
            where.append("pr.refrigerado = 1")

        rows = [dict(r) for r in conn.execute(f"""
            SELECT l.lote_id, l.sku, pr.descripcion, pr.categoria, pr.unidad_venta, pr.precio_lista,
                   pr.costo_unitario, pr.vida_util_dias, pr.refrigerado, l.cedis, l.ubicacion, l.cantidad,
                   l.fecha_entrada, l.fecha_caducidad,
                   CAST(julianday(:corte) - julianday(l.fecha_entrada) AS INTEGER) AS dias_en_almacen,
                   CAST(julianday(l.fecha_caducidad) - julianday(:corte) AS INTEGER) AS dias_para_caducar
            FROM inventario_lotes l JOIN productos pr ON pr.sku = l.sku
            WHERE {' AND '.join(where)}""", params)]

    for r in rows:
        r["riesgo"] = _riesgo(r["dias_para_caducar"])
        r["valor_precio_lista"] = round((r["cantidad"] or 0) * (r["precio_lista"] or 0), 2)
        r["margen_pct"] = _margen_pct(r["precio_lista"], r["costo_unitario"])
        vu = r["vida_util_dias"]
        r["pct_vida_util_restante"] = (max(0, min(100, round(100 * r["dias_para_caducar"] / vu))) if vu and r["dias_para_caducar"] is not None else None)

    resumen_base = {"lotes": len(rows), "unidades": round(sum(r["cantidad"] for r in rows), 2),
                    "valor_precio_lista": round(sum(r["valor_precio_lista"] for r in rows), 2)}

    if modo == "existencias":
        agg: dict[tuple, dict] = {}
        for r in rows:
            a = agg.setdefault((r["sku"], r["cedis"]), {
                "sku": r["sku"], "descripcion": r["descripcion"], "categoria": r["categoria"], "cedis": r["cedis"],
                "unidad_venta": r["unidad_venta"], "existencia": 0, "lotes": 0, "valor_precio_lista": 0.0,
                "caduca_primero": r["fecha_caducidad"], "entrada_mas_antigua": r["fecha_entrada"],
                "margen_pct": r["margen_pct"]})
            a["existencia"] += r["cantidad"]; a["lotes"] += 1; a["valor_precio_lista"] += r["valor_precio_lista"]
            a["caduca_primero"] = min(a["caduca_primero"], r["fecha_caducidad"])
            a["entrada_mas_antigua"] = min(a["entrada_mas_antigua"], r["fecha_entrada"])
        filas = sorted(agg.values(), key=lambda a: -a["valor_precio_lista"])
        for a in filas:
            a["existencia"] = round(a["existencia"], 2); a["valor_precio_lista"] = round(a["valor_precio_lista"], 2)
        return {"fecha_corte": corte, "modo": modo, "resumen": {**resumen_base, "combinaciones_sku_cedis": len(filas)},
                "resultados": filas[:limite]}

    if modo == "por_caducar":
        sel = [r for r in rows if r["dias_para_caducar"] is not None and r["dias_para_caducar"] <= int(dias_horizonte)]
        sel.sort(key=lambda r: (r["dias_para_caducar"], -r["valor_precio_lista"]))
    else:  # mas_antiguo
        sel = sorted(rows, key=lambda r: (r["fecha_entrada"] or "9999", r["fecha_caducidad"] or "9999"))

    por_riesgo = Counter(r["riesgo"] for r in sel)
    resumen = {"lotes": len(sel), "unidades": round(sum(r["cantidad"] for r in sel), 2),
               "valor_precio_lista": round(sum(r["valor_precio_lista"] for r in sel), 2),
               "lotes_por_riesgo": dict(por_riesgo)}
    if modo == "por_caducar":
        resumen["horizonte_dias"] = int(dias_horizonte)
    salida = [{k: v for k, v in r.items() if k not in ("costo_unitario", "precio_lista", "vida_util_dias", "refrigerado")} for r in sel[:limite]]
    return {"fecha_corte": corte, "modo": modo, "resumen": resumen, "resultados": salida}


# ─────────────────────────────── TOOL 3 ───────────────────────────────

@mcp.tool()
def calcula_precio(producto: str, cantidad: float = 1, cliente_id: str = "", descuento_pct: float = 0.0,
                   margen_minimo_pct: float = 0.0, limite: int = 5) -> dict:
    """Precio vigente de un producto, consultado en vivo a la base (no hay precios en caché).

    Regresa el precio de lista (MXN sin IVA), lo que realmente se ha cobrado en pedidos recientes
    (último, promedio, mín/máx, tendencia de los últimos 7 días), el último precio de un cliente
    específico y una simulación de total y margen con el descuento indicado.

    Args:
        producto: SKU o texto ("aceite 1 litro").
        cantidad: unidades de venta para cotizar (default 1).
        cliente_id: si se indica, trae lo que ese cliente pagó la última vez.
        descuento_pct: descuento a simular sobre lista (0-100).
        margen_minimo_pct: si > 0, avisa si el descuento rompe ese margen y da el descuento máximo permitido.
        limite: máximo de productos coincidentes (1-10).
    """
    if cantidad <= 0:
        return {"error": "cantidad debe ser mayor a 0."}
    if not 0 <= descuento_pct < 100:
        return {"error": "descuento_pct debe estar entre 0 y 100."}
    limite = max(1, min(int(limite), 10))

    with closing(_conn()) as conn:
        corte = _fecha_corte(conn)
        prods = _buscar_productos(conn, producto, limite)
        if not prods:
            return {"fecha_corte": corte, "resultados": [], "nota": f"No encontré productos activos que coincidan con '{producto}'."}
        hace7 = conn.execute("SELECT date(?, '-7 days') AS f", (corte,)).fetchone()["f"]
        resultados = []
        for p in prods:
            lista, costo = p["precio_lista"], p["costo_unitario"]
            h = conn.execute("""
                SELECT COUNT(*) AS n, SUM(d.cantidad) AS qty, SUM(d.importe) AS importe,
                       AVG(d.precio_unitario) AS pu_prom, MIN(d.precio_unitario) AS pu_min, MAX(d.precio_unitario) AS pu_max,
                       AVG(d.descuento_pct) AS desc_prom, MAX(pe.fecha) AS ultima
                FROM pedido_detalle d JOIN pedidos pe ON pe.pedido_id = d.pedido_id WHERE d.sku = ?""", (p["sku"],)).fetchone()
            ult = conn.execute("""
                SELECT d.precio_unitario, d.descuento_pct, pe.fecha FROM pedido_detalle d
                JOIN pedidos pe ON pe.pedido_id = d.pedido_id WHERE d.sku = ?
                ORDER BY pe.fecha DESC, d.pedido_id DESC LIMIT 1""", (p["sku"],)).fetchone()
            rec = conn.execute("""
                SELECT AVG(CASE WHEN pe.fecha >= ? THEN d.precio_unitario END) AS ult7,
                       AVG(CASE WHEN pe.fecha <  ? THEN d.precio_unitario END) AS antes
                FROM pedido_detalle d JOIN pedidos pe ON pe.pedido_id = d.pedido_id WHERE d.sku = ?""", (hace7, hace7, p["sku"])).fetchone()

            realizado = None
            if h["n"]:
                realizado = {
                    "renglones": h["n"], "ultimo_precio_unitario": ult["precio_unitario"], "fecha_ultimo": ult["fecha"],
                    "precio_unitario_promedio": round(h["pu_prom"], 2), "precio_unitario_min": h["pu_min"],
                    "precio_unitario_max": h["pu_max"], "descuento_promedio_pct": round(h["desc_prom"] or 0, 1),
                    "precio_neto_promedio": round(h["importe"] / h["qty"], 2) if h["qty"] else None}
                if rec["ult7"] and rec["antes"]:
                    realizado["variacion_ultimos_7d_pct"] = round((rec["ult7"] / rec["antes"] - 1) * 100, 1)
                if ult["precio_unitario"] and lista and abs(ult["precio_unitario"] - lista) / lista > 0.005:
                    realizado["alerta"] = "El último precio cobrado difiere del precio de lista; confirma cuál aplica."

            del_cliente = None
            if cliente_id.strip():
                cu = conn.execute("""
                    SELECT d.precio_unitario, d.descuento_pct, d.cantidad, pe.fecha FROM pedido_detalle d
                    JOIN pedidos pe ON pe.pedido_id = d.pedido_id WHERE d.sku = ? AND pe.cliente_id = ?
                    ORDER BY pe.fecha DESC LIMIT 1""", (p["sku"], cliente_id.strip())).fetchone()
                del_cliente = dict(cu) if cu else {"nota": "Ese cliente no ha comprado este SKU en el periodo."}

            final = round(lista * (1 - descuento_pct / 100), 2) if lista is not None else None
            sim = {"cantidad": cantidad, "descuento_pct": descuento_pct, "precio_unitario": final,
                   "subtotal_sin_iva": round(final * cantidad, 2) if final is not None else None,
                   "margen_resultante_pct": _margen_pct(final, costo), "nota_iva": "Precios sin IVA."}
            if margen_minimo_pct > 0:
                m = sim["margen_resultante_pct"]
                sim["descuento_maximo_pct"] = _descuento_max_pct(lista, costo, margen_minimo_pct)
                if m is not None and m < margen_minimo_pct:
                    sim["alerta_margen"] = f"El margen resultante ({m}%) queda debajo del mínimo ({margen_minimo_pct}%)."

            pz = p.get("piezas_por_unidad")
            resultados.append({**_producto_publico(p),
                               "precio_por_pieza": round(lista / pz, 2) if lista and pz else None,
                               "margen_lista_pct": _margen_pct(lista, costo),
                               "precios_cobrados": realizado, "ultimo_precio_del_cliente": del_cliente, "simulacion": sim})
    return {"fecha_corte": corte, "consultado_en": datetime.now().isoformat(timespec="seconds"),
            "n_productos": len(resultados), "resultados": resultados}


# ─────────────────────────────── TOOL 4 ───────────────────────────────

@mcp.tool()
def oportunidades_rotacion(cedis: str = "", dias_horizonte: int = 15, max_productos: int = 5,
                           clientes_por_producto: int = 5, margen_minimo_pct: float = 0.0) -> dict:
    """Convierte inventario próximo a caducar en una lista priorizada de a quién ofrecérselo.

    Para cada producto en riesgo (por valor) busca, en el mismo CEDIS, clientes con crédito no bloqueado:
      - 'recompra': ya compraron ese SKU;
      - 'venta_cruzada': compran su subcategoría pero no ese SKU.
    Sugiere una cantidad (su pedido típico) sin rebasar el stock en riesgo, y estima el margen potencial
    a precio de lista. Marca a clientes con facturas vencidas (riesgo de cobranza). No ofrece descuentos:
    si pasas margen_minimo_pct, indica el descuento máximo que aún respeta ese margen.

    Args:
        cedis: LEO, QRO o AGS (vacío = todos).
        dias_horizonte: ventana de caducidad a considerar (default 15).
        max_productos: cuántos productos en riesgo analizar (1-20).
        clientes_por_producto: candidatos por producto (1-10).
        margen_minimo_pct: margen mínimo aceptable para calcular el descuento máximo (opcional).
    """
    ced, err = _validar_cedis(cedis)
    if err:
        return {"error": err}
    max_productos = max(1, min(int(max_productos), 20))
    clientes_por_producto = max(1, min(int(clientes_por_producto), 10))
    dias = max(1, int(dias_horizonte))

    with closing(_conn()) as conn:
        corte = _fecha_corte(conn)
        filtro = " AND l.cedis = :cedis" if ced else ""
        params: dict[str, Any] = {"corte": corte, "dias": f"+{dias} days"}
        if ced:
            params["cedis"] = ced

        grupos = [dict(r) for r in conn.execute(f"""
            SELECT l.sku, l.cedis, SUM(l.cantidad) AS cantidad, MIN(l.fecha_caducidad) AS caduca_primero,
                   pr.descripcion, pr.categoria, pr.subcategoria, pr.unidad_venta, pr.precio_lista, pr.costo_unitario
            FROM inventario_lotes l JOIN productos pr ON pr.sku = l.sku
            WHERE l.cantidad > 0 AND coalesce(pr.activo,1) = 1
              AND l.fecha_caducidad >= :corte AND l.fecha_caducidad <= date(:corte, :dias){filtro}
            GROUP BY l.sku, l.cedis""", params)]
        grupos.sort(key=lambda g: -(g["cantidad"] * (g["precio_lista"] or 0)))
        total_grupos = len(grupos)
        grupos = grupos[:max_productos]

        venc = conn.execute(f"""
            SELECT COUNT(*) AS lotes, COALESCE(SUM(l.cantidad * pr.precio_lista),0) AS valor
            FROM inventario_lotes l JOIN productos pr ON pr.sku = l.sku
            WHERE l.cantidad > 0 AND l.fecha_caducidad < :corte{filtro}""", {k: v for k, v in params.items() if k in ("corte", "cedis")}).fetchone()

        vencidas = {r["cliente_id"]: r["s"] for r in conn.execute(
            "SELECT cliente_id, SUM(saldo) AS s FROM facturas WHERE estatus = 'vencida' AND saldo > 0 GROUP BY cliente_id")}

        salida, margen_total, valor_total = [], 0.0, 0.0
        for g in grupos:
            stock = g["cantidad"]
            lista, costo = g["precio_lista"], g["costo_unitario"]
            mu = (lista - costo) if (lista is not None and costo is not None) else None
            base = """
                SELECT c.cliente_id, c.nombre, c.tipo, c.estatus_credito, COUNT(DISTINCT p.pedido_id) AS n_pedidos,
                       SUM(d.cantidad) AS qty, MAX(p.fecha) AS ultima
                FROM pedidos p JOIN pedido_detalle d ON d.pedido_id = p.pedido_id
                JOIN productos pr ON pr.sku = d.sku JOIN clientes c ON c.cliente_id = p.cliente_id
                WHERE c.cedis = ? AND c.estatus_credito <> 'bloqueado' AND """
            recompra = conn.execute(base + "d.sku = ? GROUP BY c.cliente_id ORDER BY n_pedidos DESC, qty DESC LIMIT ?",
                                    (g["cedis"], g["sku"], clientes_por_producto)).fetchall()
            cands = [("recompra", dict(r)) for r in recompra]
            if len(cands) < clientes_por_producto:
                col = "subcategoria" if g["subcategoria"] else "categoria"
                cruz = conn.execute(
                    base + f"""pr.{col} = ? AND d.sku <> ? AND c.cliente_id NOT IN (
                        SELECT p2.cliente_id FROM pedidos p2 JOIN pedido_detalle d2 ON d2.pedido_id = p2.pedido_id WHERE d2.sku = ?)
                        GROUP BY c.cliente_id ORDER BY n_pedidos DESC, qty DESC LIMIT ?""",
                    (g["cedis"], g[col], g["sku"], g["sku"], clientes_por_producto - len(cands))).fetchall()
                cands += [("venta_cruzada", dict(r)) for r in cruz]

            restante, lista_c = stock, []
            for tipo_op, r in cands:
                if restante <= 0:
                    break
                sugerida = min(restante, max(1, math.ceil((r["qty"] or 1) / max(r["n_pedidos"], 1))))
                restante -= sugerida
                item = {"cliente_id": r["cliente_id"], "nombre": r["nombre"], "tipo_cliente": r["tipo"],
                        "tipo_oportunidad": tipo_op, "pedidos_periodo": r["n_pedidos"], "ultima_compra_categoria": r["ultima"],
                        "cantidad_sugerida": sugerida,
                        "margen_potencial_mxn": round(sugerida * mu, 2) if mu is not None else None}
                if r["cliente_id"] in vencidas:
                    item["riesgo_cobranza"] = f"Tiene facturas vencidas por {vencidas[r['cliente_id']]:,.2f} MXN"
                    item["recomendacion"] = "Validar con Cobranza antes de ofrecer"
                lista_c.append(item)
                if mu is not None:
                    margen_total += sugerida * mu

            valor_total += stock * (lista or 0)
            salida.append({
                "sku": g["sku"], "descripcion": g["descripcion"], "cedis": g["cedis"], "unidad_venta": g["unidad_venta"],
                "stock_en_riesgo": stock, "caduca_primero": g["caduca_primero"],
                "dias_para_caducar_min": int((datetime.fromisoformat(g["caduca_primero"]) - datetime.fromisoformat(corte)).days),
                "valor_en_riesgo_precio_lista": round(stock * (lista or 0), 2), "margen_lista_pct": _margen_pct(lista, costo),
                "descuento_maximo_pct": _descuento_max_pct(lista, costo, margen_minimo_pct),
                "stock_cubierto_por_sugerencias": stock - restante, "candidatos": lista_c,
                **({"nota": "Sin clientes elegibles en este CEDIS."} if not lista_c else {})})

    return {"fecha_corte": corte, "horizonte_dias": dias,
            "resumen": {"productos_en_riesgo_total": total_grupos, "productos_analizados": len(salida),
                        "valor_en_riesgo_analizado_precio_lista": round(valor_total, 2),
                        "margen_potencial_total_mxn": round(margen_total, 2),
                        "lotes_ya_vencidos": venc["lotes"], "valor_ya_vencido_precio_lista": round(venc["valor"], 2)},
            "oportunidades": salida}


# ─────────────────────────────── TOOL 5 ───────────────────────────────

def _firma(cliente_id: str, sku: str, cantidad: float, tipo_oportunidad: str) -> str:
    payload = f"{cliente_id}|{sku}|{cantidad:g}|{tipo_oportunidad}".encode()
    return hmac.new(_SECRET, payload, hashlib.sha256).hexdigest()[:16]


@mcp.tool()
def registra_oportunidad(cliente_id: str, sku: str, cantidad: float, tipo_oportunidad: str, justificacion: str,
                         margen_estimado_mxn: float = 0.0, token: str = "", aprobado_por: str = "",
                         decision: str = "aprobar", motivo_rechazo: str = "") -> dict:
    """Registra una oportunidad comercial, SÓLO con aprobación humana (dos pasos).

    Paso 1 (sin token): valida cliente, producto y stock, NO escribe nada y regresa un resumen con un token.
    Muestra ese resumen a la persona y pídele que apruebe o rechace de forma explícita.
    Paso 2 (con token + aprobado_por): escribe el registro. decision='aprobar' o 'rechazar' (con motivo_rechazo);
    ambas se guardan para tener trazabilidad. NUNCA llames el paso 2 sin que la persona lo haya decidido.

    Args:
        cliente_id: cliente al que se le ofrecería.
        sku: producto a ofrecer.
        cantidad: unidades de venta.
        tipo_oportunidad: 'recompra', 'venta_cruzada' o 'rotacion_caducidad'.
        justificacion: evidencia y razón comercial.
        margen_estimado_mxn: margen potencial estimado (opcional).
        token: el que devolvió el paso 1.
        aprobado_por: nombre de la persona que decide (obligatorio en el paso 2).
        decision: 'aprobar' o 'rechazar'.
        motivo_rechazo: obligatorio si decision='rechazar'.
    """
    tipo_oportunidad = _fold(tipo_oportunidad).strip()
    if tipo_oportunidad not in {"recompra", "venta_cruzada", "rotacion_caducidad"}:
        return {"error": "tipo_oportunidad debe ser 'recompra', 'venta_cruzada' o 'rotacion_caducidad'."}
    if cantidad <= 0:
        return {"error": "cantidad debe ser mayor a 0."}
    if not justificacion.strip():
        return {"error": "Falta la justificación."}
    cliente_id, sku = cliente_id.strip(), sku.strip()

    with closing(_conn()) as conn:
        cli = conn.execute("SELECT cliente_id, nombre, cedis, estatus_credito FROM clientes WHERE cliente_id = ?", (cliente_id,)).fetchone()
        pr = conn.execute("SELECT sku, descripcion, unidad_venta, coalesce(activo,1) AS activo FROM productos WHERE upper(sku) = upper(?)", (sku,)).fetchone()
        if not cli:
            return {"error": f"No existe el cliente '{cliente_id}'."}
        if not pr:
            return {"error": f"No existe el SKU '{sku}'."}
        if cli["estatus_credito"] == "bloqueado":
            return {"error": f"El cliente {cliente_id} tiene el crédito bloqueado; no se puede registrar la oportunidad."}
        if not pr["activo"]:
            return {"error": f"El SKU {pr['sku']} está inactivo."}
        corte = _fecha_corte(conn)
        stock = conn.execute("""SELECT COALESCE(SUM(cantidad),0) AS s FROM inventario_lotes
                                WHERE sku = ? AND cedis = ? AND fecha_caducidad >= ?""", (pr["sku"], cli["cedis"], corte)).fetchone()["s"]
    if stock < cantidad:
        return {"error": f"Stock vigente insuficiente en {cli['cedis']}: hay {stock:g} y se piden {cantidad:g}."}

    sku = pr["sku"]
    firma = _firma(cliente_id, sku, cantidad, tipo_oportunidad)
    resumen = {"cliente": f"{cli['nombre']} ({cliente_id}, CEDIS {cli['cedis']})",
               "producto": f"{pr['descripcion']} ({sku})", "cantidad": cantidad, "unidad_venta": pr["unidad_venta"],
               "tipo_oportunidad": tipo_oportunidad, "margen_estimado_mxn": margen_estimado_mxn,
               "justificacion": justificacion.strip(), "stock_vigente_en_cedis": stock}

    if not token:  # ── Paso 1: previsualización, no escribe ──
        return {"estado": "pendiente_aprobacion", "escribio_en_base": False, "resumen": resumen, "token": firma,
                "siguiente_paso": "Muestra el resumen a la persona. Si decide, vuelve a llamar con los mismos datos, "
                                  "token y aprobado_por (y decision='aprobar' o 'rechazar')."}

    # ── Paso 2: escritura ──
    if not hmac.compare_digest(token, firma):
        return {"error": "Token inválido: los datos cambiaron respecto al paso 1 o el servidor se reinició. Repite el paso 1."}
    if not aprobado_por.strip():
        return {"error": "Falta aprobado_por: debe ser el nombre de la persona que tomó la decisión."}
    decision = _fold(decision).strip()
    if decision not in {"aprobar", "rechazar"}:
        return {"error": "decision debe ser 'aprobar' o 'rechazar'."}
    if decision == "rechazar" and not motivo_rechazo.strip():
        return {"error": "Falta motivo_rechazo."}

    estatus = "aprobada" if decision == "aprobar" else "rechazada"
    with closing(sqlite3.connect(LOG_DB_PATH)) as log:
        log.execute("""CREATE TABLE IF NOT EXISTS oportunidades_agente (
            id INTEGER PRIMARY KEY AUTOINCREMENT, creado_en TEXT NOT NULL, fecha_corte TEXT, cliente_id TEXT NOT NULL,
            sku TEXT NOT NULL, cantidad REAL NOT NULL, tipo_oportunidad TEXT NOT NULL, justificacion TEXT,
            margen_estimado_mxn REAL, estatus TEXT NOT NULL, aprobado_por TEXT NOT NULL, motivo_rechazo TEXT,
            token TEXT NOT NULL UNIQUE)""")
        try:
            cur = log.execute("""INSERT INTO oportunidades_agente (creado_en, fecha_corte, cliente_id, sku, cantidad,
                tipo_oportunidad, justificacion, margen_estimado_mxn, estatus, aprobado_por, motivo_rechazo, token)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(timespec="seconds"), corte, cliente_id, sku, cantidad, tipo_oportunidad,
                 justificacion.strip(), margen_estimado_mxn, estatus, aprobado_por.strip(), motivo_rechazo.strip() or None, token))
            log.commit()
            return {"estado": "registrada", "id": cur.lastrowid, "estatus": estatus, "aprobado_por": aprobado_por.strip(), "resumen": resumen}
        except sqlite3.IntegrityError:
            prev = log.execute("SELECT id, estatus FROM oportunidades_agente WHERE token = ?", (token,)).fetchone()
            return {"estado": "ya_registrada", "id": prev[0], "estatus": prev[1],
                    "nota": "Este token ya se usó; no se duplicó el registro."}


if __name__ == "__main__":
    mcp.run()
