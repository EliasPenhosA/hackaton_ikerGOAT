# Guía de la base de datos `la_cosecha.db`

Extracto del sistema SICOM de Distribuidora La Cosecha del Bajío, con **fecha de corte al 30 de septiembre de 2026**. Es una base SQLite: un solo archivo, sin servidor y sin instalar nada (Python trae `sqlite3`).

> Los datos son ficticios y se generaron para el curso. Las cifras coinciden con los documentos de la carpeta de la empresa.

## Cómo conectarse

En el kit, la conexión está en `agente/db.py` y la ruta de la base sale de `LA_COSECHA_DB` en `agente/.env`:

```python
from agente.db import consultar, ejecutar      # desde un script en la carpeta del kit
# dentro de agente/agent.py:  from .db import consultar

filas = consultar("SELECT cliente_id, nombre, estatus_credito FROM clientes WHERE cedis = ? LIMIT 5", ("QRO",))
for f in filas:
    print(f["cliente_id"], f["nombre"], f["estatus_credito"])
```

- `consultar(sql, params)` abre la base **en modo sólo lectura** y regresa una lista de diccionarios.
- `ejecutar(sql, params)` sirve para escribir (INSERT, UPDATE). Úsenla sólo si su agente debe registrar algo (por ejemplo, un pedido o una nota de crédito propuesta). Hagan una copia de la base antes.
- Siempre usen parámetros (`?`) en lugar de pegar texto del usuario dentro del SQL.

> **Base de práctica.** Hasta el día del examen trabajan con `la_cosecha_practica.db`: el mismo esquema, pero 300 clientes con datos aleatorios de junio de 2026 (claves `C90001`…, `PP000001`…). Los conteos y las claves de ejemplo de esta guía (`C10007`, `FP-00010`…) son de la base real, así que en la de práctica algunas consultas regresan vacío. Es normal.

## Qué periodo cubre cada tabla

| Tabla | Periodo |
| --- | --- |
| `clientes`, `productos`, `proveedores`, `vendedores` | Situación al 30-sep-2026 |
| `inventario_lotes` | Existencias al 30-sep-2026 |
| `pedidos`, `pedido_detalle` | Septiembre 2026 |
| `facturas` | Todas las facturas de septiembre y las facturas anteriores que siguen abiertas |
| `movimientos_banco` | Agosto y septiembre 2026 |
| `reclamaciones`, `notas_credito` | Enero a septiembre 2026 |
| `certificados_proveedor` | Situación al 30-sep-2026 |
| `solicitudes_credito` | Julio a septiembre 2026 |
| `ordenes_compra`, `oc_detalle`, `recepciones_almacen`, `facturas_proveedor`, `factura_prov_detalle` | Agosto y septiembre 2026 |

## Cómo se relacionan las tablas

Cada fila dice cómo se une una tabla con otra en un `JOIN`: por qué columna y cuántos hay de cada lado.

**Clientes y ventas**

| Tabla | Se une con | Columna | Relación |
| --- | --- | --- | --- |
| `clientes` | `vendedores` | `vendedor_id` | cada cliente tiene un vendedor |
| `pedidos` | `clientes` | `cliente_id` | un cliente, muchos pedidos |
| `pedido_detalle` | `pedidos` | `pedido_id` | un pedido, muchos renglones |
| `pedido_detalle` | `productos` | `sku` | cada renglón es un producto |
| `facturas` | `pedidos` | `pedido_id` | una factura por pedido entregado; las facturas anteriores a septiembre no traen `pedido_id` |
| `facturas` | `clientes` | `cliente_id` | un cliente, muchas facturas |

**Cobranza y crédito**

| Tabla | Se une con | Columna | Relación |
| --- | --- | --- | --- |
| `movimientos_banco` | `clientes` | `cliente_id_aplicado` | sólo si el pago se identificó; si no, está vacía |
| `solicitudes_credito` | `vendedores` | `vendedor_id` | todavía no son clientes: no tienen `cliente_id` |

**Reclamaciones**

| Tabla | Se une con | Columna | Relación |
| --- | --- | --- | --- |
| `reclamaciones` | `clientes` | `cliente_id` | un cliente, muchas reclamaciones |
| `reclamaciones` | `pedidos`, `facturas` | `pedido_id`, `factura_id` | el pedido y la factura reclamados; vacíos antes de septiembre |
| `reclamaciones` | `pedido_detalle` | `pedido_id` **y** `sku` | el renglón reclamado (cantidad y precio facturados) |
| `notas_credito` | `reclamaciones` | `reclamacion_id` | cada nota viene de una reclamación |

**Productos e inventario**

| Tabla | Se une con | Columna | Relación |
| --- | --- | --- | --- |
| `productos` | `proveedores` | `proveedor_id` | un proveedor, muchos productos |
| `inventario_lotes` | `productos` | `sku` | un producto, muchos lotes (por CEDIS y caducidad) |

**Compras y proveedores**

| Tabla | Se une con | Columna | Relación |
| --- | --- | --- | --- |
| `certificados_proveedor` | `proveedores` | `proveedor_id` | un proveedor, muchos documentos |
| `ordenes_compra` | `proveedores` | `proveedor_id` | un proveedor, muchas órdenes |
| `oc_detalle` | `ordenes_compra` | `oc_id` | una orden, muchos renglones |
| `recepciones_almacen` | `oc_detalle` | `oc_id` **y** `sku` | lo que llegó de cada renglón |
| `facturas_proveedor` | `ordenes_compra` | `oc_id` | la factura del proveedor por esa orden |
| `factura_prov_detalle` | `facturas_proveedor` | `factura_prov_id` | una factura, muchos renglones |

Para comparar lo pedido, lo recibido y lo facturado, unan `oc_detalle`, `recepciones_almacen` y `factura_prov_detalle` por `oc_id` y `sku` (la consulta de ejemplo 10).

## Tablas

### `clientes` (4,850 filas)

| Columna | Descripción |
| --- | --- |
| `cliente_id` | Clave del cliente, por ejemplo `C10007` |
| `nombre`, `tipo` | Nombre comercial y tipo: `tiendita`, `restaurante_hotel`, `institucional`, `cadena` |
| `rfc`, `contacto`, `telefono_whatsapp`, `email` | Datos de contacto |
| `cedis`, `ciudad`, `colonia` | CEDIS que lo surte: `LEO`, `QRO`, `AGS` |
| `vendedor_id` | Vendedor asignado |
| `condicion_pago`, `dias_credito`, `linea_credito` | `contado` o `credito`; plazo y línea en MXN |
| `estatus_credito` | `activo`, `bloqueado` o `contado` |
| `fecha_bloqueo`, `motivo_bloqueo` | Cuándo y por qué se bloqueó |

### `productos` (257 filas)

`sku`, `descripcion`, `categoria`, `subcategoria`, `marca`, `presentacion`, `unidad_venta` (caja, pieza, bulto, galón…), `piezas_por_unidad`, `precio_lista` (MXN sin IVA), `costo_unitario` (**confidencial**), `refrigerado` (1/0), `vida_util_dias`, `proveedor_id`, `activo`.

### `inventario_lotes`

`lote_id`, `sku`, `cedis`, `cantidad` (en unidades de venta), `fecha_entrada`, `fecha_caducidad`, `ubicacion`.

### `pedidos` y `pedido_detalle`

| Columna de `pedidos` | Descripción |
| --- | --- |
| `pedido_id`, `cliente_id`, `fecha`, `hora_recepcion` | Cuándo llegó el pedido |
| `canal` | `whatsapp`, `telefono`, `correo`, `app_vendedor` |
| `capturado_por`, `minutos_captura` | Capturista (`CAP01`…`CAP11`) o vendedor, y tiempo de captura |
| `cedis`, `turno_surtido`, `fecha_entrega`, `estatus` | Surtido y entrega |
| `total` | Importe del pedido en MXN |
| `error_captura`, `tipo_error`, `requirio_reentrega` | Si el pedido se capturó con error y de qué tipo |
| `mensaje_original` | Texto con el que llegó el pedido (sólo en la muestra de chats de WhatsApp) |

`pedido_detalle`: `pedido_id`, `renglon`, `sku`, `cantidad`, `precio_unitario`, `descuento_pct`, `importe`.

### `facturas`

`factura_id`, `uuid_cfdi`, `cliente_id`, `pedido_id` (vacío en facturas anteriores a septiembre), `fecha`, `fecha_vencimiento`, `total`, `saldo`, `estatus` (`pagada`, `vigente`, `vencida`).

### `movimientos_banco`

`movimiento_id`, `fecha`, `monto`, `concepto` (texto libre que escribe quien paga), `referencia`, `cuenta_origen`, `banco_origen`, `estatus` (`aplicado` o `no_identificado`), `cliente_id_aplicado`, `facturas_aplicadas`.

### `reclamaciones` y `notas_credito`

`reclamaciones`: `reclamacion_id`, `fecha_reclamo`, `cliente_id`, `pedido_id` y `factura_id` (vacíos en reclamaciones anteriores a septiembre), `sku`, `cantidad`, `monto_reclamado`, `tipo` (`faltante`, `danado`, `caducado_o_proximo`, `diferencia_precio`, `producto_equivocado`), `canal`, `cedis_origen`, `horas_desde_entrega`, `evidencia_foto`, `remision_con_observacion`, `descripcion`, `estatus` (`abierta`, `resuelta`, `rechazada`), `fecha_resolucion`, `dias_resolucion`, `analista`, `nota_credito_id`.

`notas_credito`: `nota_credito_id`, `fecha`, `cliente_id`, `reclamacion_id`, `monto`, `motivo`, `autorizado_por`, `aplicada_a_factura`.

La base sólo trae los pedidos de septiembre. Por eso las reclamaciones de enero a agosto tienen todo lo demás (cliente, producto, tipo, monto, evidencia, estatus y nota de crédito), pero no el pedido ni la factura. Todas las reclamaciones abiertas son de septiembre y sí los traen.

### `proveedores` y `certificados_proveedor`

`proveedores`: `proveedor_id`, `razon_social`, `rfc`, `contacto`, `email`, `categoria`, `terminos_pago`, `surte_a_supermercados_del_centro`.

`certificados_proveedor`: `certificado_id`, `proveedor_id`, `tipo_documento`, `folio`, `fecha_emision`, `fecha_vencimiento`, `archivo`, `requerido_por_supermercados_del_centro`.

### `solicitudes_credito`

`solicitud_id`, `fecha_solicitud`, `nombre_negocio`, `rfc`, `tipo`, `cedis`, `vendedor_id`, `compra_mensual_estimada`, `linea_solicitada`, documentos entregados (`constancia_fiscal`, `comprobante_domicilio`, `identificacion`, `referencias_comerciales`, `estados_financieros`: 1/0), `estatus` (`aprobada`, `rechazada`, `en_revision`, `abandonada`), `fecha_resolucion`, `dias_en_proceso`, `linea_aprobada`, `notas`.

### Compras: `ordenes_compra`, `oc_detalle`, `recepciones_almacen`, `facturas_proveedor`, `factura_prov_detalle`

- `ordenes_compra`: `oc_id`, `proveedor_id`, `fecha`, `cedis_destino`, `terminos_pago`, `total`, `comprador`.
- `oc_detalle` y `factura_prov_detalle`: renglones con `sku`, `cantidad`, `precio_unitario`.
- `recepciones_almacen`: `recepcion_id`, `oc_id`, `sku`, `fecha_recepcion`, `cantidad_recibida`, `registro` (`sistema` o `papel`), `fecha_captura_sistema`, `recibio`.
- `facturas_proveedor`: `factura_prov_id`, `proveedor_id`, `oc_id`, `uuid_cfdi`, `fecha_factura`, `total`, `terminos_pago`, `fecha_limite_descuento`, `estatus`, `dias_en_validacion`, `fecha_pago`, `descuento_aplicado`, `diferencia_detectada`.

## Consultas de ejemplo

```sql
-- 1. Ficha de un cliente
SELECT * FROM clientes WHERE cliente_id = 'C10007';

-- 2. Últimos pedidos de un cliente con su detalle
SELECT p.pedido_id, p.fecha, d.sku, pr.descripcion, d.cantidad
FROM pedidos p JOIN pedido_detalle d USING(pedido_id) JOIN productos pr USING(sku)
WHERE p.cliente_id = 'C10007' ORDER BY p.fecha DESC LIMIT 20;

-- 3. Buscar productos por palabra
SELECT sku, descripcion, unidad_venta, precio_lista FROM productos
WHERE descripcion LIKE '%mayonesa%';

-- 4. Existencias de un producto por CEDIS
SELECT cedis, SUM(cantidad) AS existencia FROM inventario_lotes WHERE sku = 'ABA-0001' GROUP BY cedis;

-- 5. Lotes refrigerados que caducan en los próximos 15 días
SELECT l.lote_id, l.sku, p.descripcion, l.cedis, l.cantidad, l.fecha_caducidad
FROM inventario_lotes l JOIN productos p USING(sku)
WHERE p.refrigerado = 1 AND l.fecha_caducidad <= date('2026-09-30', '+15 days')
ORDER BY l.fecha_caducidad;

-- 6. Facturas abiertas de un cliente
SELECT factura_id, fecha, fecha_vencimiento, saldo, estatus FROM facturas
WHERE cliente_id = 'C10007' AND saldo > 0;

-- 7. Depósitos sin identificar más recientes
SELECT movimiento_id, fecha, monto, concepto FROM movimientos_banco
WHERE estatus = 'no_identificado' ORDER BY fecha DESC LIMIT 20;

-- 8. Reclamaciones abiertas, las más antiguas primero
SELECT reclamacion_id, fecha_reclamo, cliente_id, tipo, monto_reclamado FROM reclamaciones
WHERE estatus = 'abierta' ORDER BY fecha_reclamo LIMIT 20;

-- 9. Documentos de proveedores que vencen antes de una fecha
SELECT p.razon_social, c.tipo_documento, c.fecha_vencimiento FROM certificados_proveedor c
JOIN proveedores p USING(proveedor_id) WHERE c.fecha_vencimiento < '2026-12-31' ORDER BY c.fecha_vencimiento;

-- 10. Una factura de proveedor contra su orden de compra y su recepción
SELECT o.sku, o.cantidad AS pedido, r.cantidad_recibida AS recibido, f.cantidad AS facturado,
       o.precio_unitario AS precio_oc, f.precio_unitario AS precio_factura
FROM facturas_proveedor fp
JOIN oc_detalle o ON o.oc_id = fp.oc_id
LEFT JOIN recepciones_almacen r ON r.oc_id = o.oc_id AND r.sku = o.sku
LEFT JOIN factura_prov_detalle f ON f.factura_prov_id = fp.factura_prov_id AND f.sku = o.sku
WHERE fp.factura_prov_id = 'FP-00010';
```

## Consejos

- Las fechas están como texto `AAAA-MM-DD`; SQLite las compara bien y entiende `date('2026-09-30', '+15 days')`.
- La "fecha de hoy" del caso es el **30 de septiembre de 2026**, no la fecha real.
- Las tablas grandes (`pedido_detalle` tiene más de 200,000 renglones) se consultan rápido con filtros; no las carguen completas al contexto del modelo.
