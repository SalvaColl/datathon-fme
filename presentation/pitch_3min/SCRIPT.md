# Equipo 26 — presentación de tres minutos

Seis diapositivas. Guion breve, pensado para hablar con pausas.
Los tiempos son una guía de ensayo. Las fuentes y límites están en EVIDENCE.md y en el panel de datos del HTML.

## 1. Diez productos. Tres segundos. — 0:00–0:15

Buenas… [Pausa de tres segundos.] Este es el tiempo que teníamos para recomendar los diez mejores productos a cada comprador. Y así es como lo hemos hecho.

## 2. Observar. Cambiar. Comprobar. — 0:15–0:50

Observamos en el historial que los compradores repetían gustos por atributos de las descripciones. Añadimos afinidad para dar más puntuación a productos que encajaran con esos gustos. Comprobamos que la señal también aparecía en nuestro feedback real: los productos con afinidad baja registraban 0,6 compras por diez mil exposiciones, frente a 89,7 con afinidad alta. Son grupos de productos expuestos, no un antes y después del cambio. El segmento tenía solo 36 compras: apoya la señal, pero no demuestra el aumento de conversión de la política.

## 3. El cementerio de ideas. — 0:50–1:25

Este es nuestro cementerio de ideas. Los modelos más complejos y las interacciones probadas no mejoraron la validación. Una variante con grafo ganó 0,20 puntos en una ronda, pero perdió 0,41 al repetirla. El orden de las visitas tampoco añadió una mejora confirmada. No bastaba con que una idea sonara bien: tenía que resistir las pruebas.

## 4. Cada señal suma. Cada comprador cuenta. — 1:25–2:00

Nuestro modelo combina cuatro familias de señales: gustos del comprador, actividad de la sesión, calidad del producto y tendencias. Un modelo lineal las pondera para puntuar cada producto. Entrenamos con clics y compras, dando triple peso a las compras. Ordenamos y elegimos diez productos activos que no haya comprado antes. En la final mantenemos los pesos fijos, pero actualizamos las señales con lo que ocurre en la tienda.

## 5. RawTree: del dato a la acción. — 2:00–2:35

RawTree, creado por Tinybird, es la base de nuestro circuito. Leemos peticiones, eventos y cambios del catálogo. Con SQL agrupamos vistas y compras para alimentar la calidad de producto y las tendencias. Escribimos recomendaciones por lotes, recuperamos su feedback y guardamos métricas en scratch. Así podemos explicar cada decisión y detectar fallos. En práctica, el 99,96 % de las respuestas llegó a tiempo.

## 6. Los agentes aceleran. Nosotros decidimos. — 2:35–3:00

Usamos Claude para programar y Codex para investigar señales y contrastar hipótesis. El equipo controló las pruebas y el despliegue. Cubrimos modelos, nuevas señales, evaluación y fiabilidad. Los agentes aceleraron el trabajo; la evidencia decidió qué conservar. Nos quedamos con una idea: construir rápido y comprobar con rigor.

## Cómo contarlo

Guion: 348 palabras. Plan completo: 180 segundos.
Ensaya una vez en voz alta. No leas los números de muestra con prisa: haz una pausa tras cada idea.
Flecha derecha/espacio avanza; N muestra notas; F activa pantalla completa. Sin temporizador ni botones inferiores.
D abre los datos por versión; Esc vuelve al pitch. No leas las tablas completas durante los tres minutos.
El foco es CÓMO y POR QUÉ. Los cuatro nombres aparecen al final, sin un reparto de funciones no confirmado.
Si preguntan por más detalle, HOW_AND_WHY.md contiene un recorrido por el código. No atribuyas a la final los resultados de práctica.
La comparación de +0,17 puntos usa bloques temporales: no la describas como A/B aleatorizado.
Puedes terminar entre 2:40 y 3:00 dejando pausas. El objetivo es transmitir las decisiones, no agotar el cronómetro.
