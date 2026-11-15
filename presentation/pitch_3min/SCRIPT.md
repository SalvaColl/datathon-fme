# Equipo 26 — presentación de tres minutos

Seis diapositivas. Guion breve, pensado para hablar con pausas.
Los tiempos son una guía de ensayo. Las fuentes y límites están en EVIDENCE.md y en el panel de datos del HTML.

## 1. Diez productos. Tres segundos. Un comprador. — 0:00–0:15

Diez productos. Tres segundos. Un comprador. Somos el equipo 26. Lo difícil no era añadir otro modelo, sino decidir qué señales creer y llegar a tiempo.

## 2. Observar. Cambiar. Comprobar. — 0:15–0:50

Las observaciones cambiaron el modelo. Mostramos productos ya comprados 1.118 veces: no hubo ninguna compra. Eso reforzó la exclusión de compras anteriores. También encontramos gustos en los atributos de las descripciones. En una prueba histórica, añadir afinidad mejoró el acierto en primer puesto del 47,2 al 51,9 %. Es una mejora de orden offline, no una cifra de conversión.

## 3. Una ronda no bastaba. — 0:50–1:25

También descartamos ideas al repetir las pruebas. Un grafo ganó 0,20 puntos en una ronda, pero perdió 0,41 en la siguiente. No lo promovimos. Los modelos más complejos tampoco mejoraron la validación. Conservamos una base lineal, entrenada con productos mostrados: clics, compras con triple peso y posición. Entrenamos antes y evaluamos después. La complejidad tenía que demostrar su valor.

## 4. Cada versión, con su contexto. — 1:25–2:00

Aquí están las cifras de dos versiones, con sus muestras y su referencia. El margen pasó de 0,044 a 0,212 puntos: unos 0,17 puntos de diferencia. Son ocho bloques de práctica, no un A/B aleatorizado. Las tablas completas están disponibles para preguntas. No atribuimos al modelo final una media que mezcla versiones.

## 5. RawTree: del dato a la acción. — 2:00–2:35

RawTree, creado por Tinybird, es la base de nuestro circuito. Leemos peticiones, eventos y cambios del catálogo. Con SQL agrupamos vistas y compras para alimentar la calidad de producto y las tendencias. Escribimos recomendaciones por lotes, recuperamos su feedback y guardamos métricas en scratch. Así podemos explicar cada decisión y detectar fallos. En práctica, el 99,96 % de las respuestas llegó a tiempo.

## 6. La IA acelera. La evidencia decide. — 2:35–3:00

Usamos Claude para programar y Codex para investigar señales y contrastar hipótesis. El equipo controló las pruebas y el despliegue. Cubrimos modelos, nuevas señales, evaluación y fiabilidad. Los agentes aceleraron el trabajo; la evidencia decidió qué conservar. Nos quedamos con una idea: construir rápido y comprobar con rigor.

## Cómo contarlo

Guion: 307 palabras. Plan completo: 180 segundos.
Ensaya una vez en voz alta. No leas los números de muestra con prisa: haz una pausa tras cada idea.
Flecha derecha/espacio avanza; N muestra notas; F activa pantalla completa. Sin temporizador ni botones inferiores.
D abre los datos por versión; Esc vuelve al pitch. No leas las tablas completas durante los tres minutos.
El foco es CÓMO y POR QUÉ. Los cuatro nombres aparecen al final, sin un reparto de funciones no confirmado.
Si preguntan por más detalle, HOW_AND_WHY.md contiene un recorrido por el código. No atribuyas a la final los resultados de práctica.
La comparación de +0,17 puntos usa bloques temporales: no la describas como A/B aleatorizado.
Puedes terminar entre 2:40 y 3:00 dejando pausas. El objetivo es transmitir las decisiones, no agotar el cronómetro.
