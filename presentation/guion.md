# Presentación para el jurado — team_26

**Deck:** https://claude.ai/artifact/PB2ySLznV8ATNCEt1fyJv4 (13 diapositivas, 16:9; se descarga como PowerPoint o PDF desde el menú de compartir). Las fuentes de las diapositivas están en `presentation/project/` (un HTML por diapositiva más `deck.css`); las notas del orador van dentro de cada diapositiva. Todas las cifras, con ventana, N y comando, están en `presentation/cifras.md`. Consulta para la demo: `presentation/consulta_rawtree.sql`.

**Actualizado:** 15 nov 2026, 11:45 UTC, después de la final. Cuenta el recorrido completo, con lo descartado, los fallos propios y el resultado final. Las diapositivas se han revisado renderizadas en el visor.

**Duración:** el guion completo son unos 12 minutos. Para 5 minutos, usar el guion corto y saltar las diapositivas 4, 5, 8 y 11 (quedan 9). Horas en UTC (CET = UTC + 1).

## Pendiente antes de presentar

| Dónde | Qué falta |
|---|---|
| Portada | `[nombres del equipo]` |
| Diapositiva 6 (fuente) | La asignación de cada bloque a su política sale del registro de despliegue (`recsys/data/policy_changes.log` en la máquina del writer), que no está en el repo; las ocho diferencias sí se reproducen con la API |

Reglas que se mantienen: ninguna cifra de exposición se presenta como mejora de conversión; lo offline se dice como offline; lo no desplegado (arreglo de `newcap`, PR 66; prior de lanzados, PR 60; interruptor `prior_purchases`, PR 62; reserva en otra máquina, PR 69) se dice como no desplegado. La final se jugó con una sola política (ur2, código `e8a1f18`).

## Guion corto (5 minutos)

**1. Portada.** Somos el equipo 26. Os contamos el recorrido entero: qué funcionó, qué falló, cómo lo medimos y cómo quedó la final.

**2. El reto.** Una tienda pregunta tres veces por segundo qué diez productos enseñar, con tres segundos para contestar. Cuenta la probabilidad de compra.

**3. El camino en una imagen.** El día en una imagen, siempre contra la referencia de los organizadores en la misma ventana: de un punto por debajo el sábado a mediodía a 27 centésimas por encima a las siete de la mañana, con un retroceso por fallos nuestros a las ocho de la tarde. Y en la final, tres centésimas por debajo.

**4. Qué no se compra.** (Se puede saltar.) Un tercio de los huecos iba a otra categoría y casi no vendía; lo ya comprado, cero. Son las reglas más antiguas del sistema.

**5. Qué sí se compra.** (Se puede saltar.) El gusto del cliente se lee en las frases de las descripciones: de 1,6 a 23,4 compras por cien vistas, offline. De ahí sale un modelo lineal de unas veinte señales.

**6. Cómo medimos.** Las compras reales son ruido. Leemos bloques de 15 minutos con todo el tráfico en una política y restamos la referencia de esa ventana: entre cinco y siete veces más fino que repartir el tráfico.

**7. Lo que funcionó.** Lo único de modelo que medimos con bloques alternos: reajustar los pesos con las compras de nuestro propio carrusel, +0,17 puntos con error típico 0,05. Y dos de operación: listas genéricas del 3 % al 0,15 %, y de 200 peticiones perdidas por reinicio a 3.

**8. Las modas.** (Se puede saltar.) Las modas son subcategorías enteras durante 45 minutos. Es lectura de feedback, marca dirección y no es un experimento.

**9. Lo que no funcionó.** Veintinueve ideas descartadas con su cifra. Varias parecían enormes en bruto y se quedaron en nada al compararlas dentro del mismo tipo de cliente: listas genéricas en inicio, modelo no lineal, secuencias, dosis alta de productos nuevos.

**10. Nuestros errores.** Seis fallos nuestros: dos procesos escribiendo a la vez, el precio a cero casi cuatro horas, una tarde de reinicios, un ×10 que era selección, un tope que contaba de más y la última pieza, que entró sin bloque de control.

**11. El sistema y RawTree.** (Se puede saltar si no hay demo.) Un único proceso lee de RawTree por SQL, ordena, pasa las guardas y escribe; la política se cambia en caliente. En la final, ninguna respuesta inválida.

**12. La final.** Final: 2,11, quintos en conversión y sextos en la nota del stream, tres centésimas por debajo de la referencia. Medido: la referencia sube 0,2 y nosotros bajamos 0,08 en clientes nuevos en página. No sabemos cuánto es la política y cuánto que los clientes son otros.

**13. Qué haríamos distinto.** Mañana: construir antes la regla de medir, cerrar antes la configuración con cada pieza leída contra su control, y tratar la fiabilidad como operación. Queda preparado y sin desplegar: el arreglo del tope, la nota inicial de productos nuevos y el interruptor de compras previas.

## Guion completo (12 minutos, igual que las notas de cada diapositiva)

**1. Portada.** Somos el equipo 26. Os contamos el recorrido completo: de dónde partimos, qué funcionó y qué no, nuestros propios errores, cómo medimos cada cambio y cómo quedó la final, con lo que sabemos explicar y lo que no.

**2. El reto.** El reto en una frase: una tienda online nos pregunta tres veces por segundo qué diez productos enseñar a un cliente, y tenemos tres segundos para contestar. Si un solo producto está agotado, la respuesta entera no vale. Lo que cuenta no son los ingresos sino la probabilidad de que el cliente compre. Para situar la escala, en las dos últimas horas limpias de práctica: el recomendador de partida, que enseña los más vendidos, convierte el 0,53 por ciento; la referencia de los organizadores, el 1,87. Esa referencia es además nuestra regla de medir, como veréis.

**3. El camino en una imagen.** Antes de entrar en detalle, el día entero en una imagen. Cada fila es nuestra conversión menos la de la referencia de los organizadores en la misma ventana, así que el ruido del tráfico se cancela. El sábado a mediodía estábamos un punto entero por debajo, con el primer modelo y solo tres de cada cuatro respuestas a tiempo. Por la tarde, con un modelo lineal y las categorías favoritas de cada cliente, a quince centésimas. A las ocho de la tarde retrocedimos: una cadena de reinicios y un fallo nuestro que dejó el precio a cero. De madrugada llegaron las tres cosas que nos pusieron por delante: cambiar de versión sin perder peticiones, leer cada cambio en bloques de quince minutos y reajustar los pesos con las compras reales de nuestro carrusel. A las siete de la mañana íbamos 27 centésimas por encima. Y en la final quedamos tres centésimas por debajo. La columna de la derecha dice qué había cambiado en cada momento, no cuánto aporta cada pieza: eso solo lo sabemos donde hubo bloques alternos, y lo enseñamos más adelante.

**4. Qué no se compra.** Primer hallazgo, y el más rentable: mirar qué NO se compra. Analizamos nuestro propio feedback en vivo, 6.266 peticiones del primer modelo. Gastaba el 31 por ciento de los huecos del carrusel en productos de otra categoría, y esos huecos dieron solo 13 de las 84 compras. Y lo que el cliente ya había comprado: lo enseñamos 1.118 veces y no se volvió a comprar ni una. El histórico sugería lo contrario; el dato en vivo lo desmiente. Estas dos reglas son las más antiguas del sistema y siguen en la versión final: lo ya comprado no se enseña nunca, y un producto de otra categoría solo entra si el cliente lo tiene en el carrito o su gusto lo justifica.

**5. Qué sí se compra.** Segundo hallazgo: qué sí se compra. Todas las descripciones están hechas igual: marca, subcategoría y dos frases de una lista fija de veinte. Y cada cliente tiene gustos estables sobre esas frases. El gráfico usa solo navegación orgánica del histórico, con la afinidad calculada antes del 15 de octubre y las compras después: de 1,6 a 23,4 compras por cada cien vistas. Es una medida offline. Con esto y otras señales parecidas, el carrito pendiente, las categorías favoritas del cliente, lo último que ha visto, montamos el modelo que sirve hoy: unas veinte señales por petición y un modelo lineal, con pesos distintos para clientes conocidos y nuevos y para páginas con y sin vistas. Lineal a propósito: probamos uno no lineal sobre las mismas señales y predecía peor.

**6. Cómo medimos.** ¿Cómo sabemos si un cambio mejora? Las compras reales son muy ruidosas: unas 225 por hora no distinguen dos variantes. El marcador público da la conversión esperada según el modelo oculto, sin ese azar, y desde ayer por la tarde admite ventanas a medida. Primero repartimos el tráfico entre brazos en paralelo, y el mismo par de brazos bailaba cuatro décimas entre rondas. Así que cambiamos de instrumento: una sola política para todo el tráfico durante quince minutos, luego otra, alternando, y de cada bloque leemos nuestra conversión menos la de la referencia de los organizadores en esa misma ventana, que descuenta la deriva del tráfico. Entre bloques de la misma política esa diferencia se mueve seis a ocho centésimas. Abajo veis una ronda real: A es la política que teníamos, B la candidata. No es un experimento aleatorizado, son bloques en el tiempo, y por eso repetimos y alternamos.

**7. Lo que funcionó.** Qué funcionó, y lo decimos solo de lo que medimos en vivo. Lo primero: aprender de nuestras propias ventas. Hasta la una de la madrugada los pesos venían del histórico y de la navegación orgánica. Los reajustamos preguntando, dentro de cada lista nuestra que acabó en compra, cuál de los diez productos se compró. Lo probamos en ocho bloques alternos de quince minutos: los pesos anteriores quedaban 4 centésimas por encima de la referencia y los nuevos 21. Diecisiete centésimas, con un error típico de cinco. Es la única mejora de modelo que tenemos medida así, y lo decimos tal cual: el resto de la subida de la noche es trayectoria, no experimento. Las otras dos cosas son de operación. Medimos que el 3 por ciento de las peticiones recibía una lista genérica porque un umbral de tiempo era demasiado prudente; al subirlo bajó al 0,15. Y cambiar de versión costaba unas doscientas peticiones por reinicio; con el relevo, en el que el proceso nuevo carga al lado del viejo y recibe el candado, costó tres.

**8. Las modas.** Lo segundo que se aprende del stream: las tendencias. No son productos sueltos: una subcategoría entera multiplica sus vistas por cuatro de golpe, dura 45 minutos y se apaga igual. Ayer vimos siete. Al principio lo descartamos: lo probamos en la página de inicio sin ninguna moda activa y no dio nada. Al volver a mirar con más datos, el efecto existe y está concentrado en quien ya está mirando esa categoría: con un producto de moda en la lista la conversión pasa de 0,7 a 3 por ciento, y con tres o cuatro a 5,7. Cuidado, esto es feedback con compras reales y fue el modelo quien eligió a quién enseñárselos, así que marca la dirección y no el tamaño. El detector compara las vistas de los últimos quince minutos con las tres horas anteriores, directamente sobre los eventos de RawTree, y mientras dura la moda esos productos suben en la lista. Está en vivo desde esta madrugada dentro de la política única.

**9. Lo que no funcionó.** Lo que no funcionó, que es más largo que lo que sí. Siete ejemplos de veintinueve. Listas genéricas para la página de inicio, por tendencia o por más vendidos: peores que el control en vivo, retiradas en cuarenta minutos. Un modelo no lineal en lugar del lineal: predice peor con usuarios apartados. Modelos de secuencia sobre el orden de la sesión: el siguiente producto lo acierta mejor la popularidad. Subir mucho los productos recién lanzados: en la misma lista vendían ocho por diez mil frente a veintidós del resto. Ajustar los pesos con el carrusel histórico: peor que ajustarlos con el nuestro. Una señal de producto a producto que dio más veinte centésimas en una ronda y menos cuarenta y una en la siguiente: era ruido, y nos enseñó a no fiarnos de una ronda. Y mover el servicio a una máquina más cercana: medimos primero, y solo quedaba un 0,2 por ciento de peticiones que recuperar. El patrón que se repite: varias ideas parecían enormes en bruto y se quedaron en casi nada al compararlas dentro del mismo tipo de cliente y de la misma lista.

**10. Nuestros errores.** Nuestros errores, que es de donde más aprendimos. Uno: el primer día tuvimos dos procesos respondiendo a la vez y nuestra lista llegaba al 37 por ciento de los clientes; desde entonces hay un único escritor con candado. Dos: un cambio nuestro dejó las señales de precio a cero durante casi cuatro horas; al corregirlo cambiaba el 84 por ciento de las listas, y tiramos todas las lecturas de esas horas en lugar de mezclarlas. Tres: una tarde de reinicios nos costó casi tres mil peticiones sin respuesta; de ahí salió el relevo sin pérdida. Cuatro: vimos que los productos recién lanzados vendían diez veces más de lo esperado y era un efecto de selección; al subirlos mucho vendieron menos que los demás. Cinco: el tope de productos nuevos por lista descontaba productos que ni siquiera llegaban a la lista; lo esquivamos cambiando la configuración, y el arreglo de código se quedó sin desplegar porque exigía reiniciar antes de la final. Seis, el más reciente: la última pieza, que deduce gustos de las visitas anteriores del cliente, entró 24 minutos antes de fijar la política y sin bloques alternos. Offline tenía apoyo. En vivo no sabemos si sumó o restó.

**11. El sistema y RawTree.** El sistema. Un único proceso lee de RawTree, por SQL y de forma incremental, las peticiones, los eventos orgánicos y los cambios de stock; calcula unas veinte señales por petición, ordena, pasa las guardas y escribe. Un solo proceso escribe: con dos a la vez nuestra lista solo llegaba al 37 por ciento de los clientes. La política, es decir los pesos, vive en un fichero que el proceso relee cada veinte segundos y valida entero antes de aplicarlo; así es como rotamos políticas cada quince minutos sin reiniciar. Las guardas van antes que el modelo: si una petición va justa de tiempo recibe una lista segura, unas 17 por hora. Para cambiar de código hay un relevo: el proceso nuevo carga mientras el viejo sigue respondiendo; el relevo real de esta noche perdió 3 peticiones, cuando ayer cada reinicio costaba unas doscientas. En las últimas cuatro horas de práctica, 99,96 por ciento a tiempo; en la final, ninguna respuesta inválida y 93 peticiones sin responder, 82 de ellas en un corte de red de treinta segundos. Y RawTree no es solo la entrada: guardamos en nuestra tabla scratch un resumen por bloque de quince minutos, y tenemos una consulta que sigue una petición de principio a fin, de la petición a las señales, a nuestra lista y a la compra. La podemos enseñar en la demo.

**12. La final.** La final, solo lo medido. Sobre las mismas 21.600 peticiones para todos: el punto de partida convierte 0,75, nosotros 2,11, la referencia de los organizadores 2,14 y el mejor equipo 2,25. Somos quintos en conversión y sextos en la nota del stream, con 53,67 sobre 100, a una centésima del quinto. En arranque en frío hacemos 2,43 frente a 2,20 de la referencia. Dos horas antes íbamos 27 centésimas por encima de la referencia y acabamos tres por debajo. Qué sabemos. Medido: la referencia sube unas veinte centésimas respecto a la última hora de práctica, sobre todo en frío, y los equipos que iban por delante también pierden distancia con ella. Medido también: nuestro número baja ocho centésimas, y esa bajada está en los clientes nuevos en página, de 3,4 a 3,1; los otros tres segmentos quedan igual. Lo que no sabemos: por qué las listas genéricas mejoran tanto en la final, ni cuánto de nuestra bajada en clientes nuevos es la política y cuánto que los clientes son otros. Son horas distintas y no hay comparación limpia, así que no lo vamos a adornar. El corte de red de treinta segundos nos costó 82 peticiones, menos de una centésima.

**13. Qué haríamos distinto.** Qué haríamos distinto. Primero, construir antes la regla de medir. Hasta las once de la noche del sábado comparábamos variantes repartiendo el tráfico, con cuatro décimas de ruido entre rondas, y con eso se decide poco. Los bloques contra la referencia son entre cinco y siete veces más finos y llegaron tarde. Segundo, cerrar antes la configuración: cada pieza nueva con su bloque de control, y lo que no dé tiempo a leer se queda fuera. Tercero, la fiabilidad es operación y no modelo: un portátil y una red, y en la final un corte de treinta segundos. Teníamos preparada una reserva en otra máquina, pero comprobamos que el candado de escritor único es local, así que arrancarla podía duplicar respuestas, y no la usamos. Y cuarto, lo que queda preparado y sin desplegar, dicho como tal: el arreglo del tope de productos nuevos, una nota inicial para productos nuevos a partir de su descripción y un interruptor para las compras previas que al final no hizo falta, porque la organización confirmó que el mundo no se reiniciaba. Todo esto está en el repositorio con sus cifras. Gracias.

## Cómo encaja con los criterios del jurado

Reparto documentado en `challenge.md` (tabla "Scoring"): método 10, aprender del stream 10, uso de RawTree 5, comunicación 5.

| Criterio (puntos) | Diapositivas | Argumento |
|---|---|---|
| Método (10) | 3, 4, 5, 6, 9, 10, 12 | Un instrumento de medida sin el ruido de las compras (bloques contra la referencia), corte temporal en lo offline, N y ventana en cada cifra, 29 descartes con evidencia, seis fallos propios contados y la final explicada separando lo medido de lo que no sabemos |
| Aprender del stream (10) | 7, 8 | Pesos reajustados con las compras del propio carrusel y medidos en vivo; calidad de producto desde el stream; detector de modas en vivo; productos lanzados con peso y tope |
| Uso de RawTree (5) | 11 y demo | Lectura incremental por SQL de peticiones, eventos y stock; señales de moda calculadas sobre `shop.events`; snapshots por bloque en `team_26.scratch` (`tools/scratch_snapshot.py`); consulta que sigue una petición por las cuatro tablas (`consulta_rawtree.sql`, 1 s) |
| Comunicación (5) | todas | Una idea por diapositiva, lenguaje de producto, huecos visibles donde no hay medida |

## Demo de RawTree (30 s, si hay turno)

1. Pegar `presentation/consulta_rawtree.sql` en la consola: diez filas, una por puesto, con el interés del cliente por la subcategoría, las compras orgánicas por vista del producto, la ráfaga de la subcategoría, quién sirvió, la latencia y cuál se compró. Salida real en `cifras.md`, sección 10.2.
2. `python tools/scratch_snapshot.py --read 3`: las últimas filas de métricas por bloque guardadas en `team_26.scratch`.

## De dónde sale cada número

Detalle, comandos y salidas en `presentation/cifras.md` (secciones 1 a 12 para lo anterior a esta versión; sección 13 para las cifras nuevas de las diapositivas 3, 7, 9, 10 y 13).

## Preguntas probables

- **¿Los bloques son un A/B de verdad?** No es aleatorizado: son bloques en el tiempo, cada uno contra la referencia de su misma ventana para descontar la deriva, alternados y repetidos. Lo elegimos porque el reparto por cliente daba ±0,4 puntos de ruido por ronda.
- **¿Qué significa "reajustar con compras del carrusel"?** Un ajuste dentro de cada petición: cuál de los diez productos mostrados se compró o se clicó, con el puesto controlado, entrenando con peticiones anteriores y comprobando con posteriores.
- **¿Por qué un modelo lineal?** Porque lo medimos: el no lineal y las interacciones predecían igual o peor con usuarios apartados (R-24), y el lineal se puede cambiar en caliente y explicar peso a peso.
- **¿Cómo sabéis que la afinidad no es solo popularidad?** Se mide sobre productos que el cliente nunca había tocado, con la afinidad calculada antes y las compras después (I-092).
- **¿Qué pasa si en la final cambian las frases o los clientes?** Una frase desconocida pesa cero y el modelo cae a subcategoría, marca y calidad orgánica; hay un ensayo con ocho escenarios de la final sin ninguna respuesta inválida (E-502).
- **¿Y si se cae el portátil?** Ya nos pasó el sábado. En la final hubo un corte de red de 30 segundos (82 peticiones). Teníamos una reserva preparada en otra máquina y no la arrancamos: el candado de escritor único es local y dos escritores duplican respuestas.
- **¿Por qué caísteis respecto a la referencia en la final?** Medido: la referencia sube unas 0,2 (sobre todo en frío) y nosotros bajamos 0,08, en clientes nuevos en página. No medido: cuánto es nuestra política (la última pieza entró sin bloque de control) y cuánto que los clientes de esas horas son otros.
- **¿Qué aporta cada pieza?** Solo lo sabemos del reajuste de pesos (+0,17, ocho bloques alternos). El resto entró junto; lo decimos como trayectoria, no como efecto.
- **¿Usasteis agentes de IA?** Sí, y por eso cada hipótesis, experimento y decisión está numerado en el repositorio, incluidas las ideas descartadas y los fallos.
- **¿Qué habéis guardado en RawTree?** Además de las respuestas, snapshots de métricas por bloque de 15 minutos en `scratch`. No están en el camino de servicio.
