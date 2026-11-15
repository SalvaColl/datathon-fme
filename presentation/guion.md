# Presentación para el jurado — team_26

**Deck:** https://claude.ai/artifact/PB2ySLznV8ATNCEt1fyJv4 (10 diapositivas, 16:9; se descarga como PowerPoint o PDF desde el menú de compartir). Las fuentes de las diapositivas están en `presentation/project/` (un HTML por diapositiva más `deck.css`); las notas del orador van dentro de cada diapositiva. Todas las cifras, con ventana, N y comando, están en `presentation/cifras.md`. Consulta para la demo: `presentation/consulta_rawtree.sql`.

**Actualizado:** 15 nov 2026, 07:30 UTC (antes de la final de las 09:00–11:00 UTC). Sustituye a la versión del 14 nov, que describía `qrank`.

**Duración objetivo:** 5 minutos de exposición y 2 de preguntas. Un hallazgo por diapositiva, cada cifra con su N. Horas en UTC (CET = UTC + 1).

## Pendiente de rellenar antes de presentar

| Dónde | Qué falta | De dónde sale |
|---|---|---|
| Portada | `[nombres del equipo]` | — |
| Diapositiva 9, barra discontinua | Resultado de la final. No se puede saber antes: el marcador está oculto de 09:00 a 11:00 UTC | Publicación de los organizadores |
| Diapositiva 7, tarjeta de lanzados | Efecto en vivo del peso de productos lanzados (`newp`, `newph`) y del tope por lista (`newcap`): las rondas posteriores a las 04:20 UTC no tienen entrada en `experiments.md`; E-610 solo mide exposición | Lectura por bloques del dueño del writer (`rotation_read.py`) |
| Diapositivas 7 y 8 (notas) | Qué política exacta corre en la final (candidatas uf1, uf0, uf1n) | Dueño del writer |
| Diapositiva 5 (fuente) | La asignación de cada bloque a su política sale del registro de despliegue, que no está en el repo; las ocho diferencias sí se reproducen con la API | `recsys/data/policy_changes.log` en la máquina del writer |
| Diapositivas 7 y 8 | Efecto en vivo por separado de tendencias y de calidad orgánica: entraron juntas en la política única; solo hay lectura del conjunto | — |

Regla: si un número no está medido cuando toque presentar, se deja el hueco y se dice en voz alta que está pendiente. No sustituir por estimaciones. Lo offline se dice como offline.

## Guion (lo que se dice)

**1. Portada (15 s).** Somos el equipo 26. Os contamos qué se compra y qué no, cómo medimos, cómo aprende el sistema en vivo y qué hemos medido de verdad, fallos incluidos. El resultado de la final no lo conocemos.

**2. El reto (25 s).** Una tienda nos pregunta tres veces por segundo qué diez productos enseñar, y hay tres segundos para contestar. Un solo producto agotado invalida la respuesta. Cuenta la probabilidad de compra. En las dos últimas horas de práctica el punto de partida convierte el 0,53 % y la referencia de los organizadores el 1,87 %.

**3. Qué no se compra (30 s).** En 6.266 peticiones de nuestro primer modelo, el 31 % de los huecos iba a otra categoría y dio 13 de las 84 compras. Lo ya comprado lo enseñamos 1.118 veces: cero compras. Son las dos reglas más antiguas del sistema y siguen en el final.

**4. Qué sí se compra (35 s).** Las descripciones son marca, subcategoría y dos frases de una lista fija de veinte, y cada cliente tiene gustos estables sobre ellas: offline, de 1,6 a 23,4 compras por cien vistas según la afinidad. Con esa y otras señales (carrito, categorías favoritas, última vista) el modelo que sirve es lineal: unas veinte señales por petición y pesos por tipo de cliente y de página. Lineal a propósito: el no lineal predecía peor.

**5. Cómo medimos (40 s).** Las compras reales son ruido. El marcador da la compra esperada y admite ventanas a medida. Con brazos en paralelo el mismo par bailaba ±0,4 puntos. Cambiamos a bloques de 15 minutos con todo el tráfico en una política, 2.700 peticiones, y leemos nuestra conversión menos la de la referencia de esa ventana: se mueve 0,06 a 0,08 entre bloques iguales. Abajo, una ronda real de ocho bloques. No es aleatorizado; por eso se alterna y se repite.

**6. El sistema y RawTree (40 s).** Un único proceso lee de RawTree por SQL, ordena, pasa las guardas y escribe. Los pesos están en un fichero que se relee cada 20 segundos: así rotamos políticas sin reiniciar. Para cambiar de código, relevo: el nuevo carga mientras el viejo responde; el de esta noche perdió 3 peticiones, antes unas 200 por reinicio. Últimas cuatro horas: 99,96 % a tiempo, p95 1,91 s. En scratch guardamos un resumen por bloque de 15 minutos, y una consulta sigue una petición de principio a fin.

**7. Aprender del stream, 1 (40 s).** Reajustamos los pesos de clientes conocidos contra las compras reales de nuestro carrusel: +0,17 puntos frente a los pesos anteriores, cuatro bloques contra cuatro, 10.800 peticiones por política. La calidad de producto sale ahora de las compras orgánicas por vista del stream. Los productos lanzados durante el evento vendían diez veces lo esperado (16 compras): tienen peso propio y tope por lista preparados; su efecto en vivo está pendiente.

**8. Aprender del stream, 2 (30 s).** Las modas son subcategorías enteras que multiplican sus vistas por cuatro durante 45 minutos; siete el 14 nov. Lo descartamos una vez con una prueba sin potencia y lo recuperamos con más datos: para quien ya mira esa categoría, la lista con un producto de moda convierte 3,0 % frente a 0,7 %. Es feedback, marca dirección. El detector compara 15 minutos con 3 horas sobre los eventos y está en vivo.

**9. Resultados (40 s).** 15 nov 05:00–07:00 UTC, 21.600 peticiones: punto de partida 0,53, referencia 1,87, nosotros 2,14; en frío 2,56 frente a 1,64. El camino: −1,07 respecto a la referencia ayer a mediodía, −0,15 por la tarde, +0,10 de madrugada, +0,27 ahora. Es práctica. La final está oculta: no damos ese número.

**10. Fallos y descartes (35 s).** Un fallo nuestro dejó las señales de precio a cero desde las 19:07 UTC; al corregirlo cambiaba el 84 % de las listas y no mezclamos esas medidas con las posteriores. Contábamos compras de nuestro carrusel como orgánicas: 33 compras, pero se realimentaba. 29 ideas descartadas con evidencia. Antes de optimizar, construye con qué medir; y la fiabilidad es operación.

## Cómo encaja con los criterios del jurado

Reparto documentado en `challenge.md` (tabla "Scoring"): método 10, aprender del stream 10, uso de RawTree 5, comunicación 5.

| Criterio (puntos) | Diapositivas | Argumento |
|---|---|---|
| Método (10) | 3, 4, 5, 9, 10 | Un instrumento de medida sin el ruido de las compras (bloques contra la referencia), corte temporal en lo offline, N y ventana en cada cifra, 29 descartes con evidencia y dos fallos propios contados |
| Aprender del stream (10) | 7, 8 | Pesos reajustados con las compras del propio carrusel y medidos en vivo; calidad de producto desde el stream; detector de modas en vivo; productos lanzados con peso y tope |
| Uso de RawTree (5) | 6 y demo | Lectura incremental por SQL de peticiones, eventos y stock; señales de moda calculadas sobre `shop.events`; snapshots por bloque en `team_26.scratch` (`tools/scratch_snapshot.py`); consulta que sigue una petición por las cuatro tablas (`consulta_rawtree.sql`, 1 s) |
| Comunicación (5) | todas | Una idea por diapositiva, lenguaje de producto, huecos visibles donde no hay medida |

## Demo de RawTree (30 s, si hay turno)

1. Pegar `presentation/consulta_rawtree.sql` en la consola: diez filas, una por puesto, con el interés del cliente por la subcategoría, las compras orgánicas por vista del producto, la ráfaga de la subcategoría, quién sirvió, la latencia y cuál se compró. Salida real en `cifras.md`, sección 10.2.
2. `python tools/scratch_snapshot.py --read 3`: las últimas filas de métricas por bloque guardadas en `team_26.scratch`.

## De dónde sale cada número

Detalle, comandos y salidas en `presentation/cifras.md`.

| Diapositiva | Cifra | Fuente |
|---|---|---|
| 2, 9 | 0,53 / 1,87 / 2,14; cold 0,74 / 1,64 / 2,56; N = 21.600 | Marcador, `api/state?from=1794718800&to=1794726000` (15 nov 05:00–07:00 UTC) |
| 3 | 31 %, 13 de 84, 0 de 1.118, barras por 10.000 impresiones | I-082, E-081 (feedback 14 nov 12:01–13:02 UTC, 6.266 peticiones) |
| 4 | 1,6 → 23,4 por 100 vistas (offline) | I-092, E-093 (3,9 M de pares, 167.527 compras) |
| 4, 10 | No lineal −645,3 frente a −627,5 (offline) | R-24 / E-260 |
| 5, 7 | Ocho bloques 02:20–04:20 UTC, 2.700 peticiones cada uno; medias +0,04 y +0,21; diferencia +0,167; error típico 0,048 | Marcador por bloque; cálculo en `cifras.md` sección 5 |
| 5 | ±0,4 con brazos paralelos; 0,06–0,08 por bloque; 5 a 7 veces | HANDOFF "Medida", E-274; `cifras.md` sección 4 |
| 6 | 99,96 % (43.182 de 43.200), p50 1,22 s, p95 1,91 s, unas 17 listas de guarda por hora | Feedback 15 nov 03:00–07:00 UTC |
| 6 | 3 de 2.343 en el relevo de las 00:36 UTC; unas 1.080 en 5 reinicios | Feedback; E-220 |
| 6 | 144 filas, 24 bloques | `team_26.scratch`, `tools/scratch_snapshot.py`, 15 nov 07:23 UTC |
| 6 (notas) | 37 % (531 de 1.437) | I-017 |
| 7 | Lanzados: observado/esperado 10,2 (5,8–16,5), 16 compras, 1.256 impresiones | I-390 |
| 7 (notas) | Calidad orgánica mejor que la histórica (offline) | E-490 |
| 8 | 0,72 / 3,04 / 4,83 / 5,73 %; 7 ráfagas; 45 minutos; ×4 | E-530, I-440 |
| 9 | Tabla de trayectoria y a tiempo 76,9 % → 99,94 % | Marcador, cinco ventanas (`cifras.md` sección 2) |
| 10 | 84 % de listas, 44 snapshots | I-420, E-421 |
| 10 | 33 compras en 11 de 400 lanzamientos | I-470 |
| 10 | 29 descartes, 52 experimentos, 66 hallazgos, 33 decisiones, 394 tests | Recuento del repo (`cifras.md` sección 9) |
| 10 | 14 minutos de caída | I-161, 14 nov 13:24–13:38 UTC |

## Preguntas probables

- **¿Los bloques son un A/B de verdad?** No es aleatorizado: son bloques en el tiempo, cada uno contra la referencia de su misma ventana para descontar la deriva, alternados y repetidos. Lo elegimos porque el reparto por cliente daba ±0,4 puntos de ruido por ronda.
- **¿Qué significa "reajustar con compras del carrusel"?** Un ajuste dentro de cada petición: cuál de los diez productos mostrados se compró o se clicó, con el puesto controlado, entrenando con peticiones anteriores y comprobando con posteriores.
- **¿Por qué un modelo lineal?** Porque lo medimos: el no lineal y las interacciones predecían igual o peor con usuarios apartados (R-24), y el lineal se puede cambiar en caliente y explicar peso a peso.
- **¿Cómo sabéis que la afinidad no es solo popularidad?** Se mide sobre productos que el cliente nunca había tocado, con la afinidad calculada antes y las compras después (I-092).
- **¿Qué pasa si en la final cambian las frases o los clientes?** Una frase desconocida pesa cero y el modelo cae a subcategoría, marca y calidad orgánica; hay un ensayo con ocho escenarios de la final sin ninguna respuesta inválida (E-502).
- **¿Y si se cae el portátil?** Ya nos pasó. Para la final: un solo escritor, relevo ensayado, guardas antes que el modelo.
- **¿Usasteis agentes de IA?** Sí, y por eso cada hipótesis, experimento y decisión está numerado en el repositorio, incluidas las ideas descartadas y los fallos.
- **¿Qué habéis guardado en RawTree?** Además de las respuestas, snapshots de métricas por bloque de 15 minutos en `scratch`. No están en el camino de servicio.
