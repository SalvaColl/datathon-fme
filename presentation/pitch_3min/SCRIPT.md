# Equipo 26 — presentación de tres minutos

Seis diapositivas. Guion breve, pensado para hablar con pausas.
Los tiempos son una guía de ensayo. Las fuentes están en las notas de PowerPoint y EVIDENCE.md.

## 1. Diez productos. Tres segundos. Un comprador. — 0:00–0:15

Diez productos. Tres segundos. Un comprador. Somos el equipo 26. Lo difícil no era añadir otro modelo, sino decidir qué señales creer y llegar a tiempo.

## 2. Un modelo sencillo. Una elección medida. — 0:15–0:50

Probamos modelos más complejos, pero no mejoraron los resultados con datos apartados. Elegimos un modelo lineal: rápido e interpretable. En el entrenamiento base usamos solo productos mostrados. Aprendemos de los clics, dando triple peso a las compras, e incluimos la posición. Entrenamos con peticiones anteriores y validamos después. Los ajustes finales se eligieron por segmento, con pruebas adicionales.

## 3. Pesos estables. Datos que cambian. — 0:50–1:25

Congelamos los pesos, no la tienda. Seguimos actualizando memoria, calidad, stock y precios. Separamos nuestras recomendaciones de la actividad orgánica para no inflar la calidad de un producto. Detectamos tendencias comparando eventos recientes con su nivel habitual. Así nos adaptamos sin reajustar el modelo con unas pocas compras ruidosas. Y mantenemos todas las exclusiones de compras anteriores.

## 4. Medir antes de creer. — 1:25–2:00

El histórico refleja lo que otros modelos eligieron mostrar. Por eso el offline solo filtra ideas. En vivo comparamos con la referencia de la misma ventana: una hora favorable no debía parecer un modelo mejor. En ocho bloques, el reajuste mostró 0,17 puntos más, con 10.800 peticiones por política. No fue un A/B aleatorizado. También buscamos fallos que los tests no estaban cubriendo.

## 5. RawTree: del dato a la acción. — 2:00–2:35

RawTree, creado por Tinybird, es la base de nuestro circuito. Leemos peticiones, eventos y cambios del catálogo. Con SQL agrupamos vistas y compras para alimentar la calidad de producto y las tendencias. Escribimos recomendaciones por lotes, recuperamos su feedback y guardamos métricas en scratch. Así podemos explicar cada decisión y detectar fallos. En práctica, el 99,96 % de las respuestas llegó a tiempo.

## 6. La IA acelera. La evidencia decide. — 2:35–3:00

Claude y Codex nos ayudaron a implementar experimentos, auditar código y buscar fallos. El equipo controló las pruebas y el despliegue. Cubrimos modelos, nuevas señales, evaluación y fiabilidad. Los agentes aceleraron el trabajo; la evidencia decidió qué conservar. Nos quedamos con una idea: construir rápido y comprobar con rigor.

## Cómo contarlo

Guion: 316 palabras. Plan completo: 180 segundos.
Ensaya una vez en voz alta. No leas los números de muestra con prisa: haz una pausa tras cada idea.
R inicia el cronómetro; flecha derecha/espacio avanza; N muestra notas; F activa pantalla completa.
El foco es CÓMO y POR QUÉ. Los cuatro nombres aparecen al final, sin un reparto de funciones no confirmado.
Si preguntan por más detalle, HOW_AND_WHY.md contiene un recorrido por el código. No atribuyas a la final los resultados de práctica.
La comparación de +0,17 puntos usa bloques temporales: no la describas como A/B aleatorizado.
Puedes terminar entre 2:40 y 3:00 dejando pausas. El objetivo es transmitir las decisiones, no agotar el cronómetro.
