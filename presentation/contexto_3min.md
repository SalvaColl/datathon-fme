# Contexto para preparar la presentación de 3 minutos — team_26, Datathon FME 2026 (reto RawTree)

Este documento se puede pegar entero en una IA que no sepa nada del proyecto. Contiene todo lo necesario para preparar una presentación de **3 minutos centrada en el POR QUÉ y el CÓMO** de nuestro modelo, no en la lista de lo que hicimos.

**Instrucciones para la IA que lo reciba:**

- Usa solo las cifras de este documento y no inventes ninguna. Si falta un dato, dilo.
- Cada cifra lleva su tipo: "en vivo con control", "en vivo sin control", "offline" u "observación". No subas ninguna de categoría.
- No presentes como mejora de conversión algo que solo sea "mostramos más de tal producto".
- Lo marcado como "no desplegado" se dice como no desplegado.
- Idioma: castellano, lenguaje de producto, sin nombres internos de variables.
- Horas en UTC (España peninsular = UTC + 1).

---

## 1. La competición en un minuto

- Una tienda online simulada envía **3 peticiones por segundo**. Cada petición dice: este cliente está en esta página (inicio, producto o categoría), ¿qué **10 productos** le enseñamos en el carrusel de recomendados?
- Hay **3 segundos** para contestar. Los 10 productos deben ser distintos y estar en stock; un solo producto agotado invalida la respuesta. Si no contestamos a tiempo, el cliente ve una lista genérica de los organizadores.
- Los datos (peticiones, eventos de navegación, cambios de stock y precio, resultado de cada lista que servimos) viven en **RawTree**, una base de datos que se consulta por SQL.
- Catálogo de unos 5.000 productos. Durante el evento se lanzan productos nuevos, cambian precios y hay modas.
- **Qué se puntúa (100 puntos):** 70 del stream durante la final (50 conversión, 10 arranque en frío, 10 fiabilidad) y 30 del jurado (10 método, 10 aprender del stream, 5 uso de RawTree, 5 comunicación).
- **Conversión** = compras esperadas por cada 100 peticiones, según el simulador. No se mide con las compras reales, que son pocas y ruidosas, sino con la probabilidad de compra que el simulador calcula para nuestra lista.
- **Arranque en frío** = la misma medida solo en peticiones de clientes nuevos o que acaban de ver un producto lanzado durante el evento.
- Todos los equipos responden **exactamente las mismas peticiones**, así que las diferencias entre equipos son solo de política, no de suerte con el tráfico.
- Hay dos listones públicos de los organizadores: el **punto de partida** (los más vendidos, convierte alrededor de 0,5–0,75) y la **referencia** (un recomendador decente de los organizadores, alrededor de 1,9–2,1).
- Calendario: práctica desde el sábado 14 nov a mediodía; **final el domingo 15 nov de 09:00 a 11:00 UTC** (21.600 peticiones).

## 2. El resultado, sin adornos

| | Conversión en la final |
|---|---|
| Punto de partida de los organizadores | 0,75 |
| **team_26 (nosotros)** | **2,11** |
| Referencia de los organizadores | 2,14 |
| Mejor equipo | 2,25 |

- **Quintos en conversión** de 42 equipos y **sextos en la nota del stream** (53,67 de 100, a una centésima del quinto).
- En arranque en frío, 2,43 frente a 2,20 de la referencia.
- Fiabilidad en la final: 99,57 % a tiempo, **ninguna respuesta inválida**. 93 peticiones sin respuesta, 82 de ellas en un corte de red de 30 segundos.
- **El recorrido** (nuestra conversión menos la de la referencia en la misma ventana): sábado a mediodía **−1,07**; sábado tarde −0,15; domingo de madrugada +0,10, +0,20 y **+0,27** a las 05:00–07:00; final **−0,03**.
- **Por qué caímos de +0,27 a −0,03, lo que sabemos:** la referencia subió unas 0,2 en la final (sobre todo en arranque en frío) y los equipos de delante también perdieron distancia con ella. Nosotros bajamos 0,08 en valor absoluto, y esa bajada está en clientes nuevos en páginas de producto (de 3,4 a 3,1); el resto de segmentos quedó igual.
- **Lo que no sabemos:** por qué las listas genéricas mejoraron en la final, ni cuánto de nuestra bajada es culpa de nuestra política y cuánto que los clientes de esas horas eran otros. Son horas distintas y no hay comparación limpia. Esto se dice tal cual.

## 3. POR QUÉ: las decisiones de diseño y su razón

Esta es la parte central de la presentación. Cada decisión salió de una observación medida.

**3.1. Por qué empezamos mirando qué NO se compra.** En la primera hora, con nuestro primer modelo (6.266 peticiones, 84 compras), el 31 % de los huecos del carrusel iba a productos de otra categoría y solo dio 13 compras. Lo que el cliente ya había comprado lo enseñamos 1.118 veces: cero compras. Por cada 10.000 veces que mostrábamos un producto: ya comprado 0; otra categoría 6,8; misma categoría sin ver 13,7; misma categoría y visto en la sesión 87,2. *(Observación sobre nuestro feedback en vivo.)* Conclusión: antes de "acertar", dejar de desperdiciar huecos. De ahí las dos reglas más antiguas, que llegaron a la final: nunca lo ya comprado, y otra categoría solo si hay carrito o gusto claro.

**3.2. Por qué un modelo lineal y no algo más sofisticado.** Tres razones, las tres medidas o prácticas:
- Lo probamos: un modelo no lineal predecía peor con clientes apartados (verosimilitud −645 frente a −628, *offline*). Los modelos de secuencia tampoco: el siguiente producto lo acierta mejor la simple popularidad (5,1 % frente a 3,7 %, *offline*).
- Un modelo lineal son unas 20 señales con un peso cada una, guardadas en un fichero. Se puede **cambiar en caliente en 20 segundos sin reiniciar** y explicar peso a peso.
- Con 3 segundos por respuesta y un portátil sirviendo, lo simple es lo fiable.

**3.3. Por qué pesos distintos por tipo de cliente y de página.** Un cliente con historial en una página de producto y un cliente nuevo en la página de inicio no se parecen: el primero compra por su propio rastro (carrito, lo que acaba de ver, sus categorías); del segundo no sabemos nada. Cuatro situaciones (conocido o nuevo, página de producto o inicio), cuatro juegos de pesos. En la final: clientes conocidos en página 2,2; nuevos en página 3,1; inicio 0,6–1,0. La página de inicio es solo el 6 % de las compras y nada de lo que probamos allí mejoró.

**3.4. Por qué el "gusto" del cliente se lee en las descripciones.** Las descripciones de producto son marca, subcategoría y dos frases de una lista fija de veinte. Cada cliente tiene gustos estables sobre esas frases. Sobre productos que el cliente nunca había tocado, las compras por cada 100 vistas van de 1,6 (afinidad baja) a 23,4 (afinidad alta). *(Offline, histórico, afinidad calculada antes y compras después.)* Esa afinidad es una de las señales principales.

**3.5. Por qué reajustamos los pesos con las compras de NUESTRO carrusel.** Al principio los pesos se ajustaban con el histórico y con lo que la gente compra navegando por su cuenta. Pero lo que se compra *desde un carrusel* no es lo mismo: por ejemplo, el 41 % de las compras de clientes conocidos en nuestro carrusel eran productos que tenían en el carrito, frente al 7 % en las compras por navegación. Así que preguntamos directamente a nuestros datos: dentro de cada lista nuestra que acabó en compra, ¿cuál de los diez se compró? Y ajustamos los pesos a eso. **Es la única mejora de modelo que tenemos medida en vivo con control: +0,17 puntos** (pesos anteriores +0,04 sobre la referencia, pesos nuevos +0,21; 8 bloques alternos de 15 minutos, 10.800 peticiones por política, error típico 0,05).

**3.6. Por qué seguimos las modas.** De golpe, una subcategoría entera multiplica sus vistas por cuatro durante unos 45 minutos (vimos siete episodios el sábado). Para quien ya está mirando esa categoría, la lista con un producto de moda convierte 3,0 % frente a 0,7 % sin ninguno. *(Observación sobre feedback: marca dirección, no es un experimento.)* Un detector compara los últimos 15 minutos con las últimas 3 horas y sube esos productos mientras dura.

**3.7. Por qué medimos contra la referencia en bloques de 15 minutos.** Esta es probablemente la decisión de método más importante.
- Las compras reales son muy pocas: repartiendo el tráfico entre variantes, la misma pareja bailaba **±0,4 puntos** entre rondas. Con ese ruido no se puede decidir nada.
- El marcador público da la conversión esperada (sin azar) y admite ventanas a medida. Así que durante 15 minutos todo el tráfico va a una sola política (2.700 peticiones) y leemos **nuestra conversión menos la de la referencia en esa misma ventana**. Como todos responden las mismas peticiones, el efecto de "qué clientes tocaron" se cancela.
- Resultado: 0,06–0,08 de ruido por bloque, **entre 5 y 7 veces más fino**. Se alternan políticas A, B, A, B y se repite.
- No es un experimento aleatorizado: son bloques en el tiempo. Por eso se alterna y se repite, y lo decimos.

**3.8. Por qué un único proceso que escribe.** El primer día tuvimos dos procesos respondiendo a la vez y nuestra lista solo llegaba al 37 % de los clientes. Desde entonces hay un solo escritor con candado, y para cambiar de versión el proceso nuevo carga al lado del viejo y recibe el relevo.

## 4. CÓMO funciona, de principio a fin

1. **Leer.** Un proceso lee de RawTree por SQL, de forma incremental, las peticiones nuevas, los eventos de navegación (vistas, carritos, compras) y los cambios de stock y precio.
2. **Puntuar.** Para cada petición calcula unas 20 señales por producto candidato: si está en el carrito, si lo vio en esta sesión, afinidad con sus gustos, sus categorías favoritas, calidad del producto (compras por vista en el stream), si su subcategoría está de moda, si es un producto recién lanzado. Cada señal se multiplica por su peso y se suma. Los pesos dependen de la situación (cliente conocido o nuevo, página o inicio).
3. **Guardas.** Antes de enviar: 10 productos distintos, todos en stock, ninguno ya comprado por ese cliente, y dentro de plazo. Si una petición va justa de tiempo, recibe una lista segura en vez de arriesgar.
4. **Escribir.** Una respuesta por petición en RawTree.
5. **Aprender.** El resultado de cada lista (qué se mostró, qué se clicó, qué se compró) vuelve por RawTree. Con eso se reajustan los pesos y se recalcula la calidad de cada producto.
6. **Cambiar sin parar.** Los pesos viven en un fichero que el proceso relee cada 20 segundos y valida entero antes de aplicarlo. Así se rotan políticas cada 15 minutos sin reiniciar.

Latencia típica 1,2–1,4 segundos; el 95 % por debajo de 2,2 segundos en la final.

## 4 bis. RawTree: cómo lo usamos (para el criterio "uso de RawTree" del jurado)

RawTree no fue solo la tubería de entrada y salida. Estos son los usos reales, todos en el código o en lo medido, cada uno con su porqué.

1. **Nuestro propio feedback como datos de entrenamiento.** RawTree guarda, para cada lista que servimos, qué se mostró, qué se clicó y qué se compró. Lo usamos para reajustar los pesos preguntando "de los diez que enseñamos, cuál se compró". *Por qué:* lo que se compra desde un carrusel no es lo que se compra navegando, y esa tabla es la única fuente que lo dice. Es el origen del +0,17 medido en vivo. Probablemente el uso más original.
2. **Las señales del modelo se calculan sobre la tabla de eventos del stream.** La calidad de cada producto es sus compras por vista en el stream (no en el histórico), y el detector de modas compara las vistas por subcategoría de los últimos 15 minutos con las 3 horas anteriores. *Por qué:* los productos y las modas cambian durante el evento y el histórico no lo ve.
3. **Lectura incremental, y medimos su retraso.** El proceso lee solo lo nuevo de peticiones, eventos y stock. Medimos cuánto tarda un carrito en llegar al modelo: es consultable en RawTree entre 0,4 y 0,8 segundos después de ocurrir, y entra en nuestro estado a los 12 segundos de mediana (21 en el peor 5 %), porque refrescamos cada 20 segundos. *Por qué:* el carrito es la señal que más vende; había que saber si llegaba a tiempo.
4. **RawTree como herramienta de diagnóstico de nuestros propios fallos.** Comparando lo que enviamos con lo que el feedback dice que se mostró descubrimos que con dos procesos escribiendo nuestra lista solo llegaba al 37 % de los clientes. Con el mismo feedback medimos que el 3 % de las peticiones recibía lista genérica y lo bajamos al 0,15 %.
5. **Vigilancia de solo lectura durante la final.** Desde otra máquina, una consulta por minuto sobre nuestro feedback: porcentaje a tiempo, respuestas inválidas y segundos sin enviar. Sin escribir nada y sin tocar el proceso que servía. *Por qué:* queríamos detectar una caída sin arriesgarnos a provocarla. Detectó el corte de red de 30 segundos.
6. **Memoria propia en nuestra tabla libre.** Guardamos un resumen por bloque de 15 minutos (peticiones, a tiempo, latencia, compras, política activa): 144 filas, y volver a ejecutarlo no duplica nada. *Por qué:* la lectura por bloques es nuestro instrumento de medida y queríamos que quedara dentro de la plataforma, no en un portátil.
7. **Una sola consulta SQL que sigue una petición de principio a fin.** Petición, señales calculadas solo con eventos anteriores a ella, la lista que enviamos y qué se compró. Tarda 1 segundo y sirve de demo: en el ejemplo guardado, el producto del puesto 1 (un champú que el cliente tenía en el carrito) es el que se compró.

**Lo que no usamos, dicho tal cual:** no usamos embeddings. Las descripciones son frases de una lista fija de veinte, así que contar frases compartidas bastaba.

**Matiz:** la comparación por bloques contra la referencia sale del marcador público de la plataforma, no de una consulta SQL nuestra.

## 5. CÓMO decidíamos qué entraba

- **Regla:** una idea entra si tiene apoyo independiente (offline con corte temporal) y la lectura en vivo por bloques no va en contra. Una idea dudosa solo entra con señal clara en vivo.
- **Lo que parecía enorme y no lo era.** Varias señales daban multiplicadores espectaculares en bruto y se quedaban en casi nada al comparar dentro del mismo tipo de cliente y de la misma lista. Ejemplo: los productos recién lanzados parecían vender 10 veces lo esperado (16 compras); al subirlos mucho vendieron menos que el resto (8 compras por 10.000 frente a 22). Era un efecto de selección.
- **29 ideas descartadas con su cifra**, entre ellas: listas genéricas para la página de inicio (0,14–0,38 % frente a 0,49 % del control, *en vivo*), modelo no lineal (*offline*), secuencias (*offline*), una señal producto a producto que dio +0,20 en una ronda y −0,41 en la siguiente (*en vivo*; nos enseñó a no fiarnos de una ronda), mover el servicio a otra máquina (solo quedaba un 0,2 % de peticiones por recuperar).
- Todo está numerado en el repositorio: 52 experimentos, 66 hallazgos, 33 decisiones, 29 descartes.

## 6. Nuestros errores (contarlos suma en "método")

1. Dos procesos escribiendo a la vez: la lista llegó al 37 % de los clientes. Arreglo: escritor único.
2. Un cambio nuestro dejó las señales de precio a cero casi cuatro horas el sábado por la tarde. Al corregirlo cambió el 84 % de las listas; descartamos las lecturas de esas horas.
3. Una tarde de reinicios: 2.821 peticiones sin respuesta y 1.570 con lista genérica en 100 minutos. De ahí salió el relevo sin pérdida (3 peticiones perdidas en vez de unas 200 por reinicio).
4. El ×10 de los productos nuevos, que era selección (ver arriba).
5. El tope de productos nuevos por lista contaba productos que no llegaban a mostrarse. Se esquivó por configuración; el arreglo de código **no se desplegó**.
6. La última pieza (deducir gustos de las visitas anteriores del cliente) entró 24 minutos antes de cerrar la configuración, **sin bloques de control**. Tenía apoyo offline. No sabemos si en la final sumó o restó.

**Preparado y no desplegado:** el arreglo del tope de productos nuevos, una nota inicial para productos nuevos según su descripción, un interruptor sobre compras previas y una reserva en otra máquina (no se arrancó porque el candado de escritor único es local y dos escritores duplican respuestas).

**Qué haríamos distinto:** construir antes la regla de medir (llegó a las 23:00 del sábado), y cerrar antes la configuración: lo que no dé tiempo a leer contra su control, se queda fuera.

## 7. Glosario mínimo

- **Carrusel:** la fila de 10 productos recomendados que ve el cliente.
- **Conversión:** compras esperadas por cada 100 peticiones (la calcula el simulador).
- **Arranque en frío:** peticiones de clientes nuevos o con productos recién lanzados.
- **Referencia:** recomendador de los organizadores que sirve de listón; aparece en el marcador como un equipo más.
- **Punto de partida:** lista de los más vendidos; el listón mínimo.
- **Cliente conocido / nuevo:** con o sin historial anterior al evento.
- **Compra orgánica:** la que hace el cliente navegando por su cuenta, no desde nuestro carrusel.
- **Feedback:** lo que RawTree nos devuelve de cada lista servida (mostrado, clicado, comprado).
- **Bloque:** 15 minutos con todo el tráfico en una sola política.
- **Política:** un juego completo de pesos para las cuatro situaciones.
- **Lista segura / genérica:** la que se sirve cuando no da tiempo a calcular la buena.
- **team_26:** nuestro nombre en el marcador público.

## 8. Propuesta de estructura para 3 minutos (unas 420 palabras)

| Tiempo | Bloque | Idea que debe quedar |
|---|---|---|
| 0:00–0:20 | El problema | Diez productos en tres segundos, tres veces por segundo; cuenta la probabilidad de compra y las compras reales son ruido. |
| 0:20–0:55 | Por qué medir así | Con tráfico repartido, ±0,4 de ruido: no se decide nada. Bloques de 15 minutos contra la referencia en las mismas peticiones: 5 a 7 veces más fino. Todo lo demás depende de esto. |
| 0:55–1:40 | Por qué este modelo | Primero dejar de desperdiciar huecos (lo ya comprado: cero ventas). Un modelo lineal porque el complejo predecía peor y el simple se cambia en caliente. Pesos por tipo de cliente porque compran por razones distintas. |
| 1:40–2:15 | Cómo aprende en vivo, con RawTree | RawTree nos devuelve qué se compró de cada lista nuestra: con eso reajustamos los pesos (+0,17 medido con bloques alternos). Las modas y la calidad de producto se calculan sobre los eventos del stream. Una frase para el jurado: "usamos RawTree como datos de entrenamiento, como diagnóstico y como vigilancia, no solo como tubería". |
| 2:15–2:45 | Qué falló | 29 ideas descartadas; multiplicadores que eran selección; la última pieza entró sin control. |
| 2:45–3:00 | Resultado y cierre | De un punto por debajo de la referencia a 0,27 por encima; en la final, quintos, tres centésimas por debajo, y decimos qué parte sabemos explicar. |

Consejo: en 3 minutos caben 4 o 5 diapositivas. Del deck existente (13 diapositivas, https://claude.ai/artifact/PB2ySLznV8ATNCEt1fyJv4, privado hasta que su dueño lo comparta) las que mejor sirven al por qué y al cómo son: el camino en una imagen (3), cómo medimos (6), lo que funcionó (7), nuestros errores (10) y la final (12).

## 9. Las cuatro cifras que merece la pena decir en voz alta

1. **De −1,07 a +0,27** frente a la referencia en 18 horas; **−0,03** en la final (quintos de 42 en conversión).
2. **5 a 7 veces** menos ruido midiendo por bloques contra la referencia (0,06–0,08 frente a ±0,4).
3. **+0,17** al reajustar los pesos con las compras de nuestro propio carrusel: lo único de modelo medido en vivo con control.
4. **29 ideas descartadas** con su cifra, y **cero respuestas inválidas** en las 21.600 peticiones de la final.

Opcional si sobra una frase: lo ya comprado se mostró 1.118 veces y no vendió ninguna.

## 10. Preguntas probables del jurado

- **¿Es un A/B de verdad?** No es aleatorizado: son bloques en el tiempo, cada uno contra la referencia de su misma ventana, alternados y repetidos.
- **¿Por qué lineal?** Porque lo medimos (el no lineal predecía peor offline) y porque se cambia en caliente y se explica peso a peso.
- **¿Qué aporta cada pieza?** Solo lo sabemos del reajuste de pesos (+0,17). El resto entró junto y lo contamos como trayectoria, no como efecto de cada pieza.
- **¿Por qué caísteis en la final?** Ver sección 2: la referencia subió 0,2, nosotros bajamos 0,08 en clientes nuevos en página, y no podemos separar política de población.
- **¿Cómo usasteis RawTree?** Ver sección 4 bis: feedback propio como datos de entrenamiento, señales sobre los eventos del stream, retraso del carrito medido, diagnóstico de fallos, vigilancia de solo lectura en la final, resumen por bloques en nuestra tabla y una consulta que sigue una petición de principio a fin.
- **¿Usasteis IA?** Sí, y por eso cada hipótesis, experimento y decisión está numerada en el repositorio, incluidos los descartes y los fallos.
