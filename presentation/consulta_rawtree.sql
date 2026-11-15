-- Una petición, de principio a fin, dentro de RawTree (team_26, Datathon FME 2026).
-- shop.requests -> señales calculadas en SQL sobre shop.events -> la lista que enviamos (team_26.submissions)
-- -> lo que pasó (team_26.feedback). Solo lectura. Cambiar el request_id de la primera línea para ver otra.
-- Las señales usan solo eventos ANTERIORES a la petición (sin información del futuro).
WITH
  'r_c6ac5a730257ef6f' AS rid,
  req AS (SELECT user_id::String AS u, toDateTime(ts::String) AS t
          FROM shop.requests WHERE request_id::String = rid LIMIT 1),
  lista AS (SELECT pos, items::Array(String)[pos] AS pid
            FROM team_26.submissions ARRAY JOIN arrayEnumerate(items::Array(String)) AS pos
            WHERE request_id::String = rid),
  cat AS (SELECT product_id::String AS pid, any(subcategory::String) AS sub
          FROM (SELECT product_id, subcategory FROM shop.catalog
                UNION ALL SELECT product_id, subcategory FROM shop.catalog_updates)
          GROUP BY pid),
  -- 1) el cliente: qué ha visto y metido en el carrito durante el evento, por subcategoría
  cliente AS (SELECT c.sub AS sub, countIf(e.event_type::String = 'view') AS vistas,
                     countIf(e.event_type::String = 'add_to_cart') AS carritos
              FROM shop.events e JOIN cat c ON c.pid = e.product_id::String
              WHERE e.user_id::String = (SELECT u FROM req) AND toDateTime(e.ts::String) < (SELECT t FROM req)
              GROUP BY sub),
  -- 2) el producto: compras orgánicas por cada 100 vistas en las 24 h anteriores
  producto AS (SELECT product_id::String AS pid, countIf(event_type::String = 'view') AS vistas,
                      round(100 * countIf(event_type::String = 'purchase') / greatest(vistas, 1), 1) AS compras_por_100_vistas
               FROM shop.events
               WHERE product_id::String IN (SELECT pid FROM lista)
                 AND toDateTime(ts::String) < (SELECT t FROM req)
                 AND toDateTime(ts::String) >= (SELECT t FROM req) - INTERVAL 24 HOUR
               GROUP BY pid),
  -- 3) la tendencia: vistas de la subcategoría en los últimos 15 min frente a la media de las 3 h anteriores
  tendencia AS (SELECT c.sub AS sub,
                       round(countIf(toDateTime(e.ts::String) >= (SELECT t FROM req) - INTERVAL 15 MINUTE)
                             / greatest(countIf(toDateTime(e.ts::String) < (SELECT t FROM req) - INTERVAL 15 MINUTE) / 12, 1), 2) AS ratio_15min_vs_3h
                FROM shop.events e JOIN cat c ON c.pid = e.product_id::String
                WHERE e.event_type::String = 'view' AND toDateTime(e.ts::String) < (SELECT t FROM req)
                  AND toDateTime(e.ts::String) >= (SELECT t FROM req) - INTERVAL 195 MINUTE
                GROUP BY sub)
SELECT l.pos AS puesto, l.pid AS producto, c.sub AS subcategoria,
       cl.vistas AS cliente_vistas_subcat, cl.carritos AS cliente_carritos_subcat,
       p.vistas AS vistas_24h, p.compras_por_100_vistas, t.ratio_15min_vs_3h,
       f.served_by::String AS servido_por, f.latency_ms::Int64 AS latencia_ms,
       if(f.purchased::String = l.pid, 'COMPRADO', '') AS resultado
FROM lista l
LEFT JOIN cat c ON c.pid = l.pid
LEFT JOIN cliente cl ON cl.sub = c.sub
LEFT JOIN producto p ON p.pid = l.pid
LEFT JOIN tendencia t ON t.sub = c.sub
CROSS JOIN (SELECT served_by, latency_ms, purchased FROM team_26.feedback WHERE request_id::String = rid LIMIT 1) f
ORDER BY puesto
