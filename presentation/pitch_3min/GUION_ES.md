# Equipo 26 — presentación de tres minutos

Seis diapositivas. Guion breve, pensado para hablar con pausas.
Los tiempos son una guía de ensayo. Las fuentes y límites están en EVIDENCE.md y en el panel de datos del HTML.

## 1. Diez productos. Tres segundos. — 0:00–0:15

Buenas… [Pausa de tres segundos.] Este es el tiempo que teníamos para recomendar los diez mejores productos a cada comprador. Y así es como lo hemos hecho.

## 2. Observar. Cambiar. Comprobar. — 0:15–0:50

Nuestro método fue observar, cambiar y comprobar. Por ejemplo: descubrimos que los compradores repetían gustos por ciertos atributos de las descripciones. Añadimos afinidad para priorizar productos que encajaran con esos gustos. Después buscamos esa misma señal en nuestro feedback: por cada diez mil exposiciones, vimos 0,6 compras con afinidad baja y 89,7 con afinidad alta. No es un antes y después del modelo: es una comprobación de que la señal también aparecía en las compras reales.

## 3. El cementerio de ideas. — 0:50–1:25

Pero muchas ideas acabaron aquí. Probamos gradient boosting e interacciones: más complejidad, sin mejores resultados. También relacionamos productos vistos en la misma sesión. Parecía evidente que ayudaría, pero la mejora no se mantuvo al repetir la prueba. Y saber el orden de las visitas tampoco aportó una mejora confirmada. La intuición proponía; los datos decidían.

## 4. Cada señal suma. Cada comprador cuenta. — 1:25–2:00

Nos quedamos con un modelo lineal que combina gustos, actividad de la sesión, calidad del producto y tendencias. Aprendió los pesos con clics y compras, dando más importancia a las compras. Así puntuamos los productos y elegimos los diez mejores, excluyendo los agotados y los ya comprados. Para la final fijamos los pesos, pero seguimos actualizando las señales: el modelo es estable; la información está viva.

## 5. RawTree: del dato a la acción. — 2:00–2:35

RawTree nos permitió cerrar todo ese circuito en una misma plataforma: leer la tienda, agregar actividad con SQL, enviar recomendaciones y recuperar su feedback. Lo más útil fue poder pasar del dato a una decisión medible sin montar toda esa infraestructura nosotros. Y tenía que funcionar en tiempo real: en la ventana de práctica documentada, respondimos a tiempo al 99,96 % de las peticiones.

## 6. Los agentes aceleran. Nosotros decidimos. — 2:35–3:00

Usamos Claude para programar e integrar mejoras, y Codex para investigar señales y contrastar hipótesis. El proceso era este: plantear una hipótesis, implementar la idea, probarla y decidir. Los agentes nos permitieron explorar más; nosotros mantuvimos el control de las pruebas y del despliegue. Los agentes aceleran. Nosotros decidimos.

## Cómo contarlo

Guion: 337 palabras. Plan completo: 180 segundos.
Ensaya una vez en voz alta. No leas los números de muestra con prisa: haz una pausa tras cada idea.
Flecha derecha/espacio avanza; N muestra notas; F activa pantalla completa. Sin temporizador ni botones inferiores.
D abre los datos por versión; Esc vuelve al pitch. No leas las tablas completas durante los tres minutos.
El foco es CÓMO y POR QUÉ. Los cuatro nombres aparecen al final, sin un reparto de funciones no confirmado.
Si preguntan por más detalle, HOW_AND_WHY.md contiene un recorrido por el código. No atribuyas a la final los resultados de práctica.
La comparación de +0,17 puntos usa bloques temporales: no la describas como A/B aleatorizado.
Puedes terminar entre 2:40 y 3:00 dejando pausas. El objetivo es transmitir las decisiones, no agotar el cronómetro.
