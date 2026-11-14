# Presentación para el jurado — team_26

**Deck:** https://claude.ai/artifact/PB2ySLznV8ATNCEt1fyJv4 (10 diapositivas, 16:9; se descarga como PowerPoint o PDF desde el menú de compartir). Las fuentes de las diapositivas están en `presentation/project/` (un HTML por diapositiva más `deck.css`); las notas del orador van dentro de cada diapositiva.

**Duración objetivo:** 5 minutos de exposición y 2 de preguntas. Un hallazgo por diapositiva, cada cifra con su N.

## Pendiente de rellenar antes de presentar

| Dónde | Qué falta | De dónde sale |
|---|---|---|
| Portada | `[nombres del equipo]` | — |
| Diapositiva 9, barra discontinua | Resultado del A/B `ab_qrank` (conversión de cada brazo, N, ventana UTC) | `python recsys/compare_versions.py` y marcador |
| Diapositiva 9, tabla | Conversión de cada variante del laboratorio nocturno y diferencia frente a `baseline` de su misma ventana | tabla de ablación de `recsys/night_lab.py` (nueva fila en `experiments.md`) |
| Diapositiva 9, barra de v1 | Actualizar 0,91 si hay una hora limpia de v1 sin caída | `https://datathon.rawtree.dev/api/state` |
| Diapositiva 6 | Si se prueba la variante `trend` en vivo, cambiar «Pendiente de probar en vivo» por el resultado | D-080 |

Regla: si un número no está medido cuando toque presentar, se deja el hueco y se dice en voz alta que está pendiente. No sustituir por estimaciones.

## Guion (lo que se dice)

**1. Portada (15 s).** Somos el equipo 26. Os contamos qué descubrimos en los datos sobre lo que la gente compra y lo que no, cómo montamos un sistema que se cambia en caliente sin dejar de responder, y qué hemos medido de verdad.

**2. El reto (30 s).** Una tienda nos pregunta tres veces por segundo qué diez productos enseñar, y hay tres segundos para contestar. Un solo producto agotado invalida la respuesta. Cuenta la probabilidad de compra, no los ingresos. El recomendador de partida convierte el 0,69 %; la referencia de los organizadores, el 2,03 %. Ese hueco es el terreno de juego.

**3. Qué no se compra (40 s).** Lo más rentable fue mirar qué no se vende. En 6.266 peticiones nuestras, el 31 % de los huecos iba a productos de otra categoría y dio 13 de las 84 compras. Lo ya comprado lo enseñamos 1.118 veces: cero compras. Decisión: solo la categoría que el cliente mira, nunca lo ya comprado, ordenado por la calidad de cada producto. Eso es `qrank`. La página de inicio sigue siendo la zona débil (0,14 % en el histórico frente a 1,7 %).

**4. Qué sí se compra (45 s).** Todas las descripciones son marca, subcategoría y dos frases de una lista fija de veinte. Cada cliente tiene gustos estables sobre esas frases. Con navegación orgánica y separación temporal, la compra por cada cien vistas pasa de 1,6 a 23,4 según la afinidad. En nuestro carrusel en vivo la forma es la misma (0,6 a 89,7 por diez mil), con solo 36 compras: confirma la dirección, no la cifra.

**5. Productos nuevos (35 s).** Un producto nuevo no tiene historial, pero sí descripción. Las dos frases cruzadas con la categoría ordenan productos nunca vistos con 0,84 de acierto, frente a 0,41 de la subcategoría. Con los cien productos lanzados de verdad hoy, 0,68. Así un producto nuevo compite desde el minuto cero y sus primeras vistas corrigen la nota.

**6. Tendencias (35 s).** Las modas no son productos sueltos: una subcategoría entera multiplica sus vistas por cuatro de golpe y dura unos 45 minutos. El detector avisa a los cinco minutos. Solo hemos visto dos episodios y el efecto en el carrusel está sin medir; está listo como variante apagada.

**7. Cómo medimos (40 s).** Las compras reales son ruido: 84 en una hora no distinguen dos variantes. El marcador publica la conversión esperada, sin ese azar, y se recalcula cada minuto sobre la última hora exacta. Con una variante durante 65 minutos, su cifra se lee directa. El laboratorio nocturno rota cuatro variantes en dos vueltas, las compara con el punto de partida de su misma hora y retira una variante mala en menos de 16 minutos.

**8. El sistema (40 s).** Un único proceso lee, junta candidatos, ordena, pasa las guardas y escribe. Un solo escritor porque con dos nuestra lista llegaba al 37 % de los clientes. La variante se elige en un fichero que se relee cada 20 segundos: cambiar o volver atrás no reinicia nada. Las guardas van antes que el modelo. En una hora normal, 99,5 % a tiempo.

**9. Resultados (40 s).** Punto de partida 0,69; nuestro primer modelo 0,91 en una hora que incluye 14 minutos de caída; referencia 2,03. *[Decir el resultado del A/B de qrank y leer la tabla del laboratorio.]* Offline, la afinidad sube el acierto en primera posición de 0,472 a 0,519.

**10. Qué nos llevamos (30 s).** Quitar lo que no vende rinde más que afinar el modelo. El dato en vivo manda sobre el histórico. Antes de optimizar, construye con qué medir. Y la fiabilidad es operación: nuestra peor caída fue una tapa de portátil cerrada.

## Cómo encaja con los criterios del jurado

| Criterio (puntos) | Diapositivas | Argumento |
|---|---|---|
| Método (10) | 3, 4, 5, 7, 9 | Separación temporal en todo lo offline, N en cada cifra, hipótesis numeradas con estado, y un instrumento de medida sin ruido de compras |
| Aprender del stream (10) | 3, 5, 6, 7 | Feedback en vivo que corrige al histórico, nota de productos nuevos que se actualiza con sus vistas, detector de ráfagas, rotación de variantes con guardia |
| Uso de RawTree (5) | 8 | Lectura incremental de peticiones, eventos y stock por SQL; detector de tendencias (15 min frente a 3 h) calculado en consulta |
| Comunicación (5) | todas | Una idea por diapositiva, lenguaje de producto, huecos visibles donde aún no hay medida |

## De dónde sale cada número

| Diapositiva | Cifra | Fuente |
|---|---|---|
| 2, 9 | 0,69 % / 0,91 % / 2,03 %, N = 10.785, 63,6 % a tiempo | Marcador público, `api/state`, 14 nov 13:50 UTC |
| 3 | 31 %, 13 de 84, 0 de 1.118, barras por 10.000 impresiones | I-082, E-081 (feedback 12:01–13:02 UTC, 6.266 peticiones) |
| 3 (notas) | Inicio 0,14 % frente a 1,71 % | I-010 (histórico, 1,99 M de sesiones) |
| 4 | 1,6 → 23,4 por 100 vistas | I-092 punto 1, E-093 (3,9 M de pares, 167.527 compras) |
| 4 | 0,6 → 89,7 por 10.000 impresiones | I-092 punto 3, E-093 (84.388 impresiones, 36 compras) |
| 4, 9 | 0,472 → 0,519 | E-092 (4.697 sesiones con compra) |
| 5 | 0,41 / 0,50 / 0,60 / 0,84 y 0,68 | I-090, E-090 |
| 6 | 45 → 190, 160 → 760, 5 min, 45 min | I-080, E-080 (873.000 eventos, 2 episodios) |
| 7 | 60 s, 65 min, 16 min, 11 pruebas | I-160, E-160 |
| 8 | 99,5 % (7.977 de 8.016), 1,35 s, 2,1 s | I-084 |
| 8 | 37 % (531 de 1.437) | I-017 |
| 10 | 14 minutos de caída | 14 nov 13:24–13:38 UTC, tapa del portátil cerrada |

Las barras de la diapositiva 3 son compras ÷ impresiones × 10.000 calculadas a partir de I-082: 0/1.118, 13/19.092, 56/40.729 y 15/1.721.

## Preguntas probables

- **¿Cómo sabéis que la afinidad no es solo popularidad?** Se mide sobre productos que el cliente nunca había tocado, con la afinidad calculada antes y las compras después; y compartir frases con el último producto visto multiplica la compra controlando por producto y posición (I-092).
- **¿El marcador es un A/B de verdad?** No es aleatorizado: comparamos bloques en el tiempo, cada uno contra el punto de partida de su misma ventana para descontar la deriva. Para comparación aleatorizada usamos el reparto 50/50 por cliente (`ab_qrank`).
- **¿Qué pasa si en la final cambian las frases?** Una frase desconocida pesa cero y el modelo cae a subcategoría, marca y precio (I-090).
- **¿Y si se cae el portátil?** Es el riesgo operativo que ya nos pasó; para la final, tapa abierta, sin suspensión y un solo escritor.
- **¿Usasteis agentes de IA?** Sí, y por eso cada hipótesis, experimento y decisión está numerado en el repositorio, incluidas las ideas descartadas.
