# Cifras verificadas para el jurado (team_26)

Comprobadas el 15 nov 2026 entre las 07:19 y las 07:30 UTC. Todas las horas son UTC. Toda cifra lleva ventana, N y fuente. "Marcador" = API pública `https://datathon.rawtree.dev/api/state?from=<epoch>&to=<epoch>` (conversión esperada del modelo oculto por 100 peticiones; filas `team_26`, `baseline` y `reference` de la misma ventana). "Feedback" = tabla privada `team_26.feedback` por SQL (`recsys/rt.py`). Lo offline se marca OFFLINE y no es una ganancia en vivo.

Reparto del jurado (30 de 100 puntos), documentado en `challenge.md`, tabla "Scoring": método 10, aprender del stream 10, uso de RawTree 5, comunicación 5.

## 1. Dónde estamos (marcador, ventana limpia más reciente)

Ventana 15 nov 05:00–07:00 UTC, N = 21.600 peticiones (las mismas para todos). `api/state?from=1794718800&to=1794726000`.

| Fila | Conversión | Conversión cold | A tiempo |
|---|---|---|---|
| `baseline` (punto de partida) | 0,53 | 0,74 | 100 |
| `reference` (organizadores) | 1,87 | 1,64 | 100 |
| team_26 | 2,14 | 2,56 | 99,94 % |

- team_26 menos referencia: +0,27 en conversión y +0,92 en cold.
- Puesto en esa ventana: 4.º de 42 filas de equipo en conversión (las cuatro primeras entre 2,14 y 2,21) y 5.º en cold. Es práctica: no predice la final.

## 2. Trayectoria durante el evento (marcador, mismas ventanas para las tres filas)

| Ventana UTC | N | `baseline` | `reference` | team_26 | team_26 − referencia | Cold team_26 | A tiempo | Qué servía (según docs) |
|---|---|---|---|---|---|---|---|---|
| 14 nov 12:00–13:00 | 10.800 | 0,70 | 2,03 | 0,96 | −1,07 | 1,66 | 76,9 % | v1 (GBM), I-082 |
| 14 nov 13:00–14:00 | 10.800 | 0,70 | 2,04 | 0,99 | −1,05 | 1,60 | 80,0 % | v1, con la caída de las 13:24 (I-161) |
| 14 nov 15:00–16:00 | 10.771 | 0,67 | 2,10 | 1,82 | −0,27 | 2,27 | 96,7 % | lfm desde las 14:33 (HANDOFF) |
| 14 nov 17:00–18:00 | 10.800 | 0,59 | 2,03 | 1,88 | −0,15 | 2,48 | 99,9 % | lfm r3 (I-330) |
| 14 nov 20:00–22:00 | 21.600 | 0,56 | 1,98 | 1,72 | −0,27 | 2,22 | 86,9 % | r3 sin precios (I-420) y pruebas |
| 14 nov 23:00–15 nov 01:00 | 21.600 | 0,56 | 2,00 | 1,91 | −0,09 | 2,52 | 99,7 % | rotación por bloques (D-421); u1 desde las 00:37 |
| 15 nov 01:00–03:00 | 21.600 | 0,53 | 1,96 | 2,06 | +0,10 | 2,53 | 99,9 % | política única u1 y ronda factorial |
| 15 nov 03:00–05:00 | 21.600 | 0,49 | 1,87 | 2,06 | +0,20 | 2,51 | 99,98 % | ronda factorial, base u3k desde las 04:25 |
| 15 nov 05:00–07:00 | 21.600 | 0,53 | 1,87 | 2,14 | +0,27 | 2,56 | 99,94 % | base u3k y dosis de lanzados |

Fuente: nueve llamadas a `api/state?from=&to=` (todas con `custom: true`). La última columna sale de los documentos del repo y del registro de despliegue; el marcador no la contiene.

## 3. Fiabilidad y latencia (feedback)

Ventana 15 nov 03:00–07:00 UTC, N = 43.200 peticiones (coincide con `count(DISTINCT request_id)` de `shop.requests`).

| Cifra | Valor | Fuente |
|---|---|---|
| Servidas por nosotros a tiempo | 43.182 de 43.200 (99,96 %) | `countIf(served_by='team')` |
| Respuesta de reserva de la plataforma | 18 (17 `missing`, 1 `invalid`, 0 `late`); por hora 2, 3, 10, 3 | `fallback_reason` |
| Lista de guarda propia (válida y a tiempo, sin modelo) | 68 (16, 27, 13, 12 por hora), 0,16 % | `team_26.scratch`, `sum(guard)`; etiqueta de guarda fuera del repo |
| Latencia de lo servido | p50 1,22 s, p95 1,91 s, p99 2,35 s | `quantileIf(latency_ms)` |
| Compras reales | 911 (234, 216, 236, 225 por hora) | `countIf(purchased != '')` |
| Compras reales por segmento | conocidos en página 506 de 24.147 (2,10 %); nuevos en página 339 de 10.442 (3,25 %); home conocidos 43 de 5.971 (0,72 %); home nuevos 23 de 2.640 (0,87 %) | `team_26.scratch`, `kind='metrics_15m'` |

Todo el evento hasta las 07:20 UTC del 15 nov: 218.154 filas de feedback, 203.626 servidas por nosotros, 3.810 compras, 12.291 clics.

## 4. El instrumento: bloques de 15 minutos al 100 % contra la referencia

- Cada bloque: 2.700 peticiones, una sola política para todo el tráfico; se lee `team_26 − reference` de esa misma ventana.
- Brazos paralelos (método anterior): el mismo par de brazos oscila ±0,4 puntos entre rondas de 30 minutos con unas 1.500 peticiones por brazo (HANDOFF, "Medida"; E-274).
- Bloques: la desviación típica de `team_26 − reference` entre bloques de la misma política es 0,06 y 0,08 puntos (los 8 bloques de abajo). Es decir, entre 5 y 7 veces más fino por lectura. La cifra "unas 6 veces" es este cociente, no una medida aparte.

## 5. Aprender del stream: pesos reajustados con compras del carrusel (u3k), lectura en vivo

Ronda factorial del 15 nov 02:20–04:20 UTC, 8 bloques de 15 minutos, 2.700 peticiones cada uno. `api/state?from=&to=` por bloque (sin `by=model`).

| Bloque UTC | team_26 | `reference` | Diferencia | Política |
|---|---|---|---|---|
| 02:20 | 1,860 | 1,920 | −0,059 | u1 |
| 02:35 | 2,121 | 1,950 | +0,171 | u3k |
| 02:50 | 2,053 | 2,020 | +0,032 | u1 |
| 03:05 | 1,998 | 1,844 | +0,154 | u3k |
| 03:20 | 2,186 | 1,932 | +0,255 | u3k |
| 03:35 | 2,132 | 2,027 | +0,105 | u1 |
| 03:50 | 2,163 | 1,896 | +0,266 | u3k |
| 04:05 | 1,908 | 1,810 | +0,098 | u1 |

- Media u3k +0,212 (4 bloques, 10.800 peticiones); media u1 +0,044 (4 bloques, 10.800 peticiones). Diferencia **+0,167 puntos**. Error típico 0,048 (Welch, 4 contra 4): z 3,5.
- La asignación de cada bloque a su política viene del registro de despliegue (`recsys/data/policy_changes.log` en la máquina del writer), que no está en el repo; las ocho diferencias de la tabla sí se reproducen desde la API. El hilo de despliegue da z 2,96 con su propio emparejamiento: no reproducido aquí.
- Coherente con antes y después: 00:40–02:20 (u1 fijo, N 18.000) +0,126; 04:25–05:50 (base u3k, N 15.300) +0,292. No es un A/B aleatorizado: son bloques en el tiempo.
- Qué es u3k: los pesos de las páginas de usuarios conocidos de la política única, reajustados contra las compras reales de nuestro carrusel (`recsys/policy.rot_u3k.json`, commit 2a39a3a, 15 nov 02:02 UTC).

## 6. Relevo del writer sin pérdida

| Cifra | Valor | Fuente |
|---|---|---|
| Antes del relevo: 5 reinicios | unas 1.080 peticiones sin responder (6,7 % de 16.200) | E-220, feedback 14 nov 13:40–15:10 |
| Ensayo de relevo | 300 de 300 respondidas una vez, 0 nunca, 0 dos veces | E-220, `tools/handoff_rehearsal.py` (sin escribir) |
| Relevo real, 15 nov 00:36:39 | 3 `missing` de 2.343 peticiones entre 00:31:39 y 00:44:39 (las tres en 00:35:48–00:35:49) | feedback |
| Relevo real, 15 nov 06:20 | 1 `missing` de 2.343 entre 06:15 y 06:28 (06:16:12, antes del relevo) | feedback |
| Relevo real, 14 nov 19:05 | 15 `missing` de 2.343 entre 19:00 y 19:13 | feedback |

Las horas de los relevos vienen de las notas de despliegue; las pérdidas se han contado en el feedback con `served_by != 'team'` en la ventana de −5 a +8 minutos.

## 7. Fallos que cambiaron decisiones

| Fallo | Cifra | Fuente |
|---|---|---|
| I-420: señales de precio a cero en todos los brazos desde las 14 nov 19:07 | cero en los 44 snapshots reconstruidos entre 19:07 y 22:44; con el arreglo cambia el 84 % de las listas de r3 (OFFLINE, replay) | I-420, E-421 |
| I-470: compras del carrusel contadas como orgánicas | 33 compras de más en 11 de 400 lanzamientos; inflación mediana ×1,029, máxima ×1,089 | I-470 (dato de las 14 nov 23:10) |
| Dos procesos escribiendo a la vez | nuestra lista llegó al 37 % (531 de 1.437) | I-017 |
| Caída por la tapa del portátil | 14 minutos, 14 nov 13:24–13:38 | I-161 |

## 8. Ideas rechazadas con evidencia

- Tabla de descartes en `insights.md`: 29 filas (R-01 a R-30; la R-17 se cita aparte). Recuento: `grep -oE '^\| R-[0-9]+' insights.md | sort -u | wc -l`.
- Ejemplo para la diapositiva, R-24: modelo no lineal (gradient boosting) sobre las mismas señales. OFFLINE, usuarios apartados: log-verosimilitud de compra −645,3 frente a −627,5 del modelo lineal en conocidos y −606,1 frente a −597,7 en nuevos (E-260 citado en R-24).
- Ejemplo en vivo, R-18: brazos genéricos de home, 14 nov 17:05–17:35, conocidos en home: control 0,49 %; `conv` 0,38 %; `catbest` 0,21 %; `trend` 0,14 % (E-271, marcador por versión). Apagados a las 17:45.
- R-23 (trucos de lista): 1,6 M de impresiones del histórico aleatorizado, sin canibalización (coeficiente −0,007 ± 0,12).

## 9. Volumen de trabajo documentado (recuento del repo en 2e9d1b9)

| Qué | Cuántos | Comando |
|---|---|---|
| Experimentos (IDs E distintos) | 52 | `grep -oE '^#{2,4} E-[0-9A-Z-]+' experiments.md \| sort -u \| wc -l` |
| Hallazgos e hipótesis (IDs I distintos) | 66 | lo mismo con `I-` en `insights.md` |
| Decisiones (entradas D) | 33 | `grep -cE '^#{2,4} D-' decisions.md` |
| Ideas descartadas (filas R) | 29 | arriba |
| Tests automáticos | 394, todos pasan (49 s) | `python -m unittest discover -s tests` (incluye los 6 nuevos) |

## 10. Uso de RawTree

### 10.1 Snapshots en `team_26.scratch`

`tools/scratch_snapshot.py` (fuera del camino de servicio). Ejecutado el 15 nov 07:23 UTC con `--hours 6`: 24 ventanas de 15 minutos (01:15–07:15), 144 filas insertadas (120 `metrics_15m` en 5 segmentos, 24 `policy_versions`); segunda ejecución: 0 insertadas (idempotente). Antes la tabla estaba vacía (`count() = 0`, sin columnas).

Lectura de vuelta (`python tools/scratch_snapshot.py --read 2`, una fila):

```json
{"kind": "metrics_15m", "segment": "all", "window_start": "2026-11-15 06:45:00", "window_end": "2026-11-15 07:00:00", "requests": 2700, "on_time": 2698, "fallback": 2, "on_time_share": 0.99926, "guard": 5, "guard_share": 0.00185, "latency_p50_ms": 1306.5, "latency_p95_ms": 1979.2, "purchases": 50, "clicks": 176, "ts": "2026-11-15 07:23:47"}
```

Resumen por hora leído de scratch:

```sql
SELECT substring(window_start::String,1,13) h, sum(requests::Int64) n, sum(on_time::Int64) ok, sum(fallback::Int64) fb,
       sum(guard::Int64) guard, max(latency_p95_ms::Float64) worst_p95, sum(purchases::Int64) buys
FROM team_26.scratch WHERE kind::String='metrics_15m' AND segment::String='all' GROUP BY h ORDER BY h
```

| Hora UTC (15 nov) | Peticiones | A tiempo | Reserva | Guarda | Peor p95 de un bloque (ms) | Compras |
|---|---|---|---|---|---|---|
| 02 | 10.800 | 10.796 | 4 | 22 | 2.032 | 203 |
| 03 | 10.800 | 10.798 | 2 | 16 | 1.962 | 234 |
| 04 | 10.800 | 10.797 | 3 | 27 | 2.148 | 216 |
| 05 | 10.800 | 10.790 | 10 | 13 | 1.962 | 236 |
| 06 | 10.800 | 10.797 | 3 | 12 | 1.979 | 225 |

### 10.2 Una petición de principio a fin en SQL

`presentation/consulta_rawtree.sql`, tal cual, tarda 1,0 s. Petición `r_c6ac5a730257ef6f` (15 nov 06:30:37 UTC, usuario conocido, página de producto): el producto del puesto 1 se compró.

| puesto | producto | subcategoria | cliente_vistas_subcat | cliente_carritos_subcat | vistas_24h | compras_por_100_vistas | ratio_15min_vs_3h | servido_por | latencia_ms | resultado |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | p_40ec57 | Shampoo | 2 | 1 | 3834 | 23,3 | 0,96 | team | 1413 | COMPRADO |
| 2 | p_8ca8ed | Smartwatches | 0 | 0 | 3864 | 28,9 | 1,02 | team | 1413 | |
| 3 | p_95d5df | Laptop Sleeves | 7 | 0 | 1617 | 17,4 | 0,90 | team | 1413 | |
| 4 | p_d49ad0 | Laptop Sleeves | 7 | 0 | 1928 | 9,2 | 0,90 | team | 1413 | |
| 5 | p_33cf5b | Phone Cases | 8 | 1 | 1410 | 13,1 | 1,00 | team | 1413 | |
| 6 | p_1036d3 | Strollers | 0 | 0 | 4205 | 29,6 | 1,03 | team | 1413 | |
| 7 | p_22f07f | Phone Cases | 8 | 1 | 1145 | 12,2 | 1,00 | team | 1413 | |
| 8 | p_170f13 | RC Cars | 1 | 0 | 2707 | 23,5 | 1,04 | team | 1413 | |
| 9 | p_b8227f | Laptop Sleeves | 7 | 0 | 2092 | 17,0 | 0,90 | team | 1413 | |
| 10 | p_adfc71 | Laptop Sleeves | 7 | 0 | 524 | 4,4 | 0,90 | team | 1413 | |

Las columnas de la consulta son una versión legible de tres señales del modelo (interés del cliente por subcategoría, compras orgánicas por vista del producto, ráfaga de subcategoría de 15 min frente a 3 h). El writer calcula las suyas de forma incremental con más detalle; la consulta no es el código de servicio.

## 11. Cifras que siguen valiendo de la versión anterior (sin cambios, fuente en los docs)

| Cifra | Fuente |
|---|---|
| 31 % de huecos en otra categoría, 13 de 84 compras; ya comprado 0 de 1.118; barras 0 / 6,8 / 13,7 / 87,2 por 10.000 | I-082, E-081 (feedback 14 nov 12:01–13:02, 6.266 peticiones) |
| Afinidad 1,6 → 23,4 compras por 100 vistas (OFFLINE, corte temporal) | I-092, E-093 (3,9 M de pares, 167.527 compras) |
| Ráfagas: 7 del 14 nov, 45 minutos; productos calientes 301 frente a 45,5 compras por 10.000 impresiones ponderadas (15 compras) | I-440, E-440 |
| Ráfaga con contexto: 30 compras frente a 2,7 esperadas; caliente en el puesto 1: 6,93 % (274 listas) frente a 1,26 % (4.597) | E-530, I-530 |
| Detector: regla de 15 min entra en el minuto 4–8; rápido en el 2–3, 0 minutos marcados fuera de las 7 ráfagas (OFFLINE, replay) | E-532 |
| Calidad orgánica frente a `lq`: ganancia fuera de muestra +25,4 [11,9; 39,1] (nuevos, n 469) y +21,9 [9,2; 34,5] (conocidos, n 574) en log-verosimilitud (OFFLINE) | E-490 |
| Lanzados: observado/esperado 10,2 (IC 95 % 5,8–16,5), 16 compras en 1.256 impresiones a conocidos | I-390 |
| Tope `newcap` 2: listas con 3 o más lanzados del 17 % al 0,3 % (OFFLINE, exposición, 5.006 peticiones) | E-610 |

## Pendiente o no verificable ahora

| Qué | Por qué |
|---|---|
| Resultado de la final (09:00–11:00 UTC) | marcador oculto; se publica al terminar |
| Política exacta que corre en la final (candidatas uf1 / uf0 / uf1n) | la decide el dueño del writer; no está en los docs |
| Efecto en vivo de `newp` / `newph` y del tope `newcap` | rondas e5 y posteriores sin entrada en `experiments.md`; E-610 solo mide exposición |
| Efecto en vivo de `hot` y de `orate` / `opop` por separado | entraron juntos en u1; solo hay lectura del conjunto (sección 2) |
| z 2,96 de la lectura de u3k | cifra del hilo de despliegue; aquí sale 3,5 con Welch sobre los mismos 8 bloques |
| Asignación bloque → política de la ronda 02:20–04:20 | registro en la máquina del writer, fuera del repo |
| Nombres del equipo en la portada | marcador de posición |

## 12. La final, 15 nov 09:00–11:00 UTC (añadido a las 11:20 UTC)

Detalle y límites en `experiments.md` E-650.

| Cifra | Valor | N | Fuente |
|---|---|---|---|
| team_26, conversión esperada | 2,110% (quintos en conversión; sextos en nota del stream, 53,67 de 100, team_37 53,68) | 21.600 | `api/state`, modo final |
| team_26, cold | 2,434% | 10.419 cold | ídem |
| Referencia | 2,141% (cold 2,199%) | 21.600 | ídem |
| Punto de partida | 0,750% | 21.600 | ídem |
| A tiempo | 99,57% (marcador); 99,43% servidas por el modelo | 21.600 | `api/state`; `team_26.feedback` |
| Sin respuesta | 93, de ellas 82 en un corte de ~30 s a las 10:33 UTC | 21.600 | `team_26.feedback` |
| Inválidas | 0 | 21.600 | ídem |
| Latencia servida | p50 1,38 s, p95 2,18 s, p99 2,65 s | 21.476 | ídem |
| Compras reales / clics | 431 / 1.427 | 21.600 | ídem |
| Nuevos en página, conversión esperada | 3,09% (práctica 06:19–07:19 UTC: 3,41%) | 5.132 / 2.614 | `api/state?by=model` |

No decir: que la política de la final fuera peor o mejor que la de práctica (no hay comparación limpia), ni por qué subió la referencia (no observable).

## 13. Cifras nuevas del deck de recorrido completo (15 nov 11:45 UTC)

Las diapositivas 3, 7, 9, 10 y 13 añaden cifras. Las marcadas "otros hilos" se midieron en otros hilos del proyecto y no se han vuelto a calcular aquí.

| Diapositiva | Cifra | Fuente |
|---|---|---|
| 3 | Nueve filas de trayectoria (−1,07 … +0,27) | Sección 2 de este fichero (marcador por ventana) |
| 3, 12 | Final −0,03; 2,11 / 2,14 / 2,25 / 0,75; nota 53,67 | Sección 12; E-650 |
| 7 | +0,04 y +0,21, error típico 0,05 | Sección 5 |
| 7 | Listas genéricas 3 % → 0,15 % (69 de 46.821) | 3 %: 14 nov 20:00–22:30 UTC (otros hilos, T-043); 0,15 %: E-633, feedback 15 nov 03:00–07:30 UTC |
| 7 | 3 de 2.343 en el relevo; unas 1.080 en 5 reinicios | Sección 6; E-220 |
| 9 | Inicio: control 0,49 %, 0,38 / 0,21 / 0,14 % | R-18 / E-271, 14 nov 17:05–17:35 UTC |
| 9 | No lineal −645 frente a −628 (offline) | R-24 / E-260 |
| 9 | Secuencias 3,7 % frente a 5,1 % (offline) | R-26 / E-320 |
| 9 | Productos nuevos con dosis alta: 4,3 por lista, 7 compras en unas 8.500 impresiones (8 por 10.000) frente a 22 | Otros hilos (revisión del día 14 nov 22:10 UTC); compras reales, primeros 75 minutos, páginas de conocidos |
| 9 | Pesos del histórico −0,05 (IC −0,10 a −0,01), offline sobre nuestro feedback | Otros hilos (T-040): puesto recíproco medio de la compra, listas anteriores a las 16:00 UTC del 14 nov |
| 9 | Señal producto a producto +0,20 y −0,41 | E-271 y ronda siguiente (`experiments.md`) |
| 9 | Mover el servicio: 0,2 % recuperable | E-633 |
| 10 | 37 % (531 de 1.437) | I-017 |
| 10 | Precio a cero 19:07–22:44 UTC, 84 % de listas, 44 instantáneas | I-420, E-421 |
| 10 | 2.821 sin respuesta y 1.570 con lista genérica, 14 nov 20:20–22:01 UTC | Otros hilos (revisión del día 14 nov 22:10 UTC), feedback |
| 10 | Razón 10,2 (IC 5,8–16,5), 16 compras | I-390 |
| 10 | Última pieza: 24 minutos en vivo sin bloque de control | Registro de despliegue (hilo de despliegue), 15 nov 07:32–07:56 UTC |
| 13 | 30 segundos, 82 peticiones | Sección 12 |
| 13 | 52 experimentos, 66 hallazgos, 33 decisiones, 29 descartes | Sección 9 |
| 11 | Carrito: consultable a 0,4–0,8 s, en el estado a 12 s de mediana y 21 s en el p95 (refresco cada 20 s) | E-632 / nota A5 del PR 69, ensayo sin escritura en la nube |
| 11 | Una consulta por minuto de solo lectura durante la final | `tools/watchdog.py --once` (PR 69), registro de vigilancia 10:35–11:00 UTC; antes, cada 5 minutos |
