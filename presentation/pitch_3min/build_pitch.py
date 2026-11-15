"""Build the pitch with the standard library and existing Pillow; no network or serving imports."""
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
from datetime import datetime, timezone
import json
import re
import sys
import textwrap
from PIL import ImageFont

HERE = Path(__file__).resolve().parent
W, H, EMU = 1600, 900, 7620
C = dict(bg="101A29", card="192638", white="F5F7FA", muted="A6B5C8",
         green="61E4B1", orange="FFAC86", line="304154")
slides = []
DECK_STEM = "Team26_3min_ES"
ES_TEXT = {
    "TEAM 26  /  RAWTREE × DATATHON FME 2026": "EQUIPO 26  /  RAWTREE × DATATHON FME 2026",
    "The decision behind the system": "La decisión detrás del sistema",
    "Ten products. Three seconds. One shopper.": "Diez productos. Tres segundos.",
    "Ten products.\nThree seconds.\nOne shopper.": "Diez productos.\nTres segundos.",
    "A changing store.\nA different decision for every shopper.": "Elegir qué enseñar a cada comprador.\nReto de Tinybird · RawTree.",
    "THE DECISION WINDOW": "EL PLAZO PARA RESPONDER",
    "seconds": "segundos",
    "Why this model / how we trained it": "Por qué este modelo / cómo lo entrenamos",
    "A small model. A deliberate choice.": "Un modelo sencillo. Una elección medida.",
    "A small model.\nA deliberate choice.": "Un modelo sencillo.\nUna elección medida.",
    "01 / examples": "01 / ejemplos",
    "Learn from exposure": "Solo lo mostrado",
    "Shown products + feedback.\nPurchases weighted ×3.": "Clics como señal.\nCompras con peso ×3.",
    "02 / fitting": "02 / ajuste",
    "Control position": "Incluir la posición",
    "Regularized logistic model.\nSeparate known/new weights.": "Regresión logística.\nPesos por tipo de usuario.",
    "03 / validation": "03 / validación",
    "Test later requests": "Validación temporal",
    "Earlier training → later test.\nComplexity needs evidence.": "Entrenar antes.\nEvaluar después.",
    "Why linear? Fast to serve, easy to inspect, retained after held-out comparisons.": "El modelo complejo no mejoró la prueba: elegimos rapidez y claridad.",
    "Why this adaptation / how it stays stable": "Cómo nos adaptamos sin perder el control",
    "Frozen weights. Live intelligence.": "Pesos estables. Datos que cambian.",
    "Frozen weights.\nLive intelligence.": "Pesos estables.\nDatos que cambian.",
    "01 / shopper memory": "01 / memoria",
    "Use earlier visits": "Recordar el interés",
    "Session evidence accumulates.\nKnown purchases stay out.": "Visitas y actividad acumuladas.\nLo comprado queda fuera.",
    "02 / product quality": "02 / calidad",
    "Keep sources separate": "Separar las fuentes",
    "Organic counts → quality.\nPrivate buys → user memory.": "Actividad orgánica → calidad.\nNuestro feedback → memoria.",
    "03 / trends": "03 / tendencias",
    "Compare event windows": "Detectar el cambio",
    "Recent activity vs baseline.\nNo timetable assumptions.": "Eventos recientes frente al pasado.\nSin horarios prefijados.",
    "Why: adapt from live evidence; keep the final policy stable.": "La tienda cambia. La política se mantiene bajo control.",
    "Method / evidence": "Método / evidencia",
    "Measure before believing.": "Medir antes de creer.",
    "Measure before\nbelieving.": "Medir antes\nde creer.",
    "+0.17": "+0,17",
    "percentage points": "puntos porcentuales",
    "Observed after refitting the weights": "Diferencia observada tras reajustar",
    "Temporal offline": "Separación temporal",
    "Screen hypotheses without future information.": "Entrenar antes; evaluar con datos posteriores.",
    "Matched windows": "Misma ventana",
    "Compare against the reference at the same time.": "Comparar con la referencia de esa misma hora.",
    "Counterexamples": "Pruebas que fallan",
    "A green test is only as good as its assumptions.": "Buscar casos que los tests no estaban cubriendo.",
    "8 blocks · 10,800 requests per policy": "8 bloques · 10.800 peticiones por política",
    "PRACTICE / 15 NOV 03:20–05:20 CET · TIME BLOCKS, NOT RANDOMIZED A/B": "PRÁCTICA / 15 NOV 03:20–05:20 CET · BLOQUES TEMPORALES, NO A/B ALEATORIZADO",
    "Why it is fast / how RawTree supports it": "Cómo usamos RawTree",
    "Precompute. Validate. Batch.": "RawTree: del dato a la acción.",
    "Precompute.\nValidate. Batch.": "RawTree:\ndel dato a la acción.",
    "99.96%": "99,96%",
    "valid and on time · 43,200 requests": "a tiempo · 43.200 peticiones de práctica",
    "p99  2.35 s     /     deadline  3 s": "99% en menos de 2,35 s · límite: 3 s",
    "RAWTREE → ONE SERVING LOOP": "RAWTREE → UN ÚNICO ESCRITOR",
    "Requests + events + catalogue": "Peticiones + eventos + catálogo",
    "SQL → feature snapshots": "SQL → datos preparados",
    "Rank → validate → batch write": "Ordenar → validar → enviar",
    "Private feedback → evaluation": "Feedback → evaluación",
    "144 stored metric snapshots": "144 registros de métricas",
    "PRACTICE / 15 NOV 04:00–08:00 CET · 43,182 OF 43,200 SERVED ON TIME": "PRÁCTICA / 15 NOV 04:00–08:00 CET · 43.182 DE 43.200 RESPUESTAS A TIEMPO",
    "How we worked / AI-assisted development": "Cómo trabajamos / agentes de programación",
    "Agents accelerated. Evidence decided.": "La IA acelera. La evidencia decide.",
    "Agents accelerated.\nEvidence decided.": "La IA acelera.\nLa evidencia decide.",
    "Development tool": "Herramienta de desarrollo",
    "Implementation, integrations\nand experiments.": "Programar e integrar mejoras.",
    "Audits, evaluation\nand failure cases.": "Investigar y contrastar hipótesis.",
    "Hypothesis → isolated code → tests → measured decision": "Hipótesis → código aislado → pruebas → decisión",
    "Build fast. Verify carefully.": "Construir rápido. Comprobar con rigor.",
}
ES_UPPER = {k.upper(): v.upper() for k, v in ES_TEXT.items()}
def tr(value):
    return ES_TEXT.get(value, ES_UPPER.get(value, value))

ES_NOTES = [
    "Buenas… [Pausa de tres segundos.] "
    "Este es el tiempo que teníamos para recomendar los diez mejores productos a cada comprador. "
    "Y así es como lo hemos hecho.",
    "Probamos modelos más complejos, pero no mejoraron los resultados con datos apartados. "
    "Elegimos un modelo lineal: rápido e interpretable. En el entrenamiento base usamos solo productos mostrados. "
    "Aprendemos de los clics, dando triple peso a las compras, e incluimos la posición. "
    "Entrenamos con peticiones anteriores y validamos después. Los ajustes finales se eligieron por segmento, con pruebas adicionales.",
    "Congelamos los pesos, no la tienda. Seguimos actualizando memoria, calidad, stock y precios. "
    "Separamos nuestras recomendaciones de la actividad orgánica para no inflar la calidad de un producto. "
    "Detectamos tendencias comparando eventos recientes con su nivel habitual. "
    "Así nos adaptamos sin reajustar el modelo con unas pocas compras ruidosas. "
    "Y mantenemos todas las exclusiones de compras anteriores.",
    "El histórico refleja lo que otros modelos eligieron mostrar. Por eso el offline solo filtra ideas. "
    "En vivo comparamos con la referencia de la misma ventana: una hora favorable no debía parecer un modelo mejor. "
    "En ocho bloques, el reajuste mostró 0,17 puntos más, con 10.800 peticiones por política. "
    "No fue un A/B aleatorizado. También buscamos fallos que los tests no estaban cubriendo.",
    "RawTree, creado por Tinybird, es la base de nuestro circuito. "
    "Leemos peticiones, eventos y cambios del catálogo. Con SQL agrupamos vistas y compras para alimentar la calidad de producto y las tendencias. "
    "Escribimos recomendaciones por lotes, recuperamos su feedback y guardamos métricas en scratch. "
    "Así podemos explicar cada decisión y detectar fallos. En práctica, el 99,96 % de las respuestas llegó a tiempo.",
    "Usamos Claude para programar y Codex para investigar señales y contrastar hipótesis. "
    "El equipo controló las pruebas y el despliegue. Cubrimos modelos, nuevas señales, evaluación y fiabilidad. "
    "Los agentes aceleraron el trabajo; la evidencia decidió qué conservar. "
    "Nos quedamos con una idea: construir rápido y comprobar con rigor.",
]
ES_SOURCES = [
    "Contrato oficial y handoff final del equipo: message (4).txt. "
    "El diagrama explica el flujo y su plazo global de 3 segundos, no tiempos medidos por etapa. "
    "RawTree se identifica como producto de Tinybird en https://rawtree.com/.",
    "recsys/lfm_build.py: filas expuestas, etiquetas de clic, peso de compra 3, posición y regresión logística. "
    "R-24/E-260: comparación con gradient boosting. El entrenamiento base no reproduce por sí solo todos los ajustes finales.",
    "Handoff final y aclaración del organizador: el mundo no se reinicia. "
    "Los eventos de carrito son actividad, no pedidos pendientes. No se atribuye una mejora online demostrada a cada señal.",
    "presentation/cifras.md, rama javi/jury-final: 03:20–05:20 CET, 8 bloques de 2.700 peticiones. "
    "4 bloques y 10.800 peticiones por política; diferencia de 0,167 puntos tras ajustar por la referencia. "
    "Comparación temporal, no A/B aleatorizado.",
    "presentation/cifras.md: práctica del 15 nov 04:00–08:00 CET; 43.182/43.200 respuestas a tiempo; "
    "p99 2,35 s. 144 registros de métricas. No es una cifra de la final. "
    "SQL agrega eventos; el código local calcula las puntuaciones y los indicadores. "
    "Uso de team_26.scratch según el handoff y presentation/cifras.md. RawTree es un producto de Tinybird: https://rawtree.com/.",
    "Nombres facilitados por el equipo. Uso confirmado de Claude y Codex a nivel de equipo; "
    "no se inventan funciones individuales ni versiones concretas de los agentes.",
]
ES_NOTES[1] = (
    "Un ejemplo completo: nuestras recomendaciones generaban feedback propio sobre clics y compras. "
    "Lo usamos para reajustar los pesos del modelo. "
    "Al comprobar el resultado, la conversión esperada pasó del 1,99 al 2,12 %. "
    "También comparamos con la referencia de cada ventana: el margen mejoró unos 0,17 puntos. "
    "Son bloques temporales de práctica, no una prueba aleatorizada. La tabla siguiente detalla esa comparación.")
ES_NOTES[2] = (
    "También descartamos ideas al repetir las pruebas. Un grafo ganó 0,20 puntos en una ronda, pero perdió 0,41 en la siguiente. "
    "No lo promovimos. Los modelos más complejos tampoco mejoraron la validación. "
    "Conservamos una base lineal, entrenada con productos mostrados: clics, compras con triple peso y posición. "
    "Entrenamos antes y evaluamos después. La complejidad tenía que demostrar su valor.")
ES_NOTES[3] = (
    "Aquí están las cifras de dos versiones, con sus muestras y su referencia. "
    "El margen pasó de 0,044 a 0,212 puntos: unos 0,17 puntos de diferencia. "
    "Son ocho bloques de práctica, no un A/B aleatorizado. "
    "Las tablas completas están disponibles para preguntas. No atribuimos al modelo final una media que mezcla versiones.")
ES_SOURCES[1] = (
    "E-081/I-082: feedback del primer modelo, 14 nov 12:01–13:02 UTC, 0 compras en 1.118 exposiciones ya compradas. "
    "E-092: 4.697 sesiones históricas con compra, hit@1 0,472 -> 0,519 al incorporar afinidad. "
    "Las dos métricas son distintas; ninguna es una comparación causal de conversión del modelo final.")
ES_SOURCES[2] = (
    "E-271: conocidos/página, r3 1,57% (1.489) vs grafo 1,77% (1.521), 14 nov 17:50–18:20 UTC. "
    "E-272: r3 2,08% (1.539) vs grafo 1,67% (1.476), 18:25–18:55 UTC. "
    "Los brazos difieren en home, pero mantienen los mismos pesos del grafo en páginas. "
    "R-24/E-260: GBM sin mejora; lfm_build.py: entrenamiento base.")
ES_SOURCES[3] = (
    "presentation/cifras.md, javi/jury-final: 8 bloques, 4 por política, 10.800 peticiones por política. "
    "Medias de conversiones documentadas: u1 1,98825 y referencia 1,94425; u3k 2,117 y referencia 1,9055. "
    "Margen documentado +0,044 frente a +0,212 pp. Valores mostrados redondeados; comparación temporal, no aleatorizada.")

def slide(kicker, title, seconds, notes, source):
    n = len(slides)
    kicker, title = tr(kicker), tr(title)
    notes, source = ES_NOTES[n], ES_SOURCES[n]
    s = dict(kicker=kicker, title=title, seconds=seconds, notes=notes, source=source, shapes=[])
    slides.append(s)
    rect(s, 0, 0, W, H, C["bg"])
    rect(s, 70, 70, 36, 6, C["green"])
    text(s, 122, 57, kicker.upper(), 20, C["green"], bold=True)
    return s

def rect(s, x, y, w, h, color, radius=0):
    s["shapes"].append(dict(kind="rect", x=x, y=y, w=w, h=h, color=color, radius=radius))

def text(s, x, y, value, size=30, color=None, bold=False, width=None):
    value = tr(value)
    color = color or C["white"]
    lines = []
    font_path = Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf")
    font = ImageFont.truetype(str(font_path), size)
    for para in value.split("\n"):
        if width is None:
            lines.append(para)
            continue
        words, line = para.split(), ""
        for word in words:
            nxt = (line + " " + word).strip()
            if line and font.getlength(nxt) > width:
                lines.append(line)
                line = word
            else:
                line = nxt
        lines.append(line)
    s["shapes"].append(dict(kind="text", x=x, y=y, w=width or W-x-65,
                            h=max(1, len(lines))*size*1.19+12, lines=lines,
                            size=size, color=color, bold=bold))

def card(s, x, y, w, h, eyebrow, headline, body=None, accent=None):
    rect(s, x, y, w, h, C["card"], 22)
    text(s, x+28, y+24, eyebrow.upper(), 18, accent or C["green"], True, w-56)
    text(s, x+28, y+67, headline, 34, bold=True, width=w-56)
    if body:
        text(s, x+28, y+133, body, 25, C["muted"], width=w-56)

s = slide("The decision behind the system", "Ten products. Three seconds. One shopper.", 15,
    "Ten products. Three seconds. One shopper. "
    "We are Team 26. The difficult part was choosing what to trust: old data, live behavior, or a more complicated model. "
    "Our answer was to make every extra layer earn its place.",
    "Official challenge contract; team final handoff, message (4).txt.")
text(s, 70, 180, "Ten products.\nThree seconds.\nOne shopper.", 100, bold=True)
text(s, 75, 595, "A changing store.\nA different decision for every shopper.", 31, C["muted"])
rect(s, 970, 166, 560, 575, C["card"], 28)
text(s, 1005, 193, "DE LA PETICIÓN A LA RESPUESTA", 20, C["green"], True)
for y, step, label, description in [
    (245, "01", "LEER DE RAWTREE", "Petición de un cliente"),
    (375, "02", "MODELO LOCAL", "Puntuar y validar"),
    (505, "03", "ENVIAR LA RESPUESTA", "Las 10 mejores recomendaciones"),
]:
    rect(s, 1005, y, 490, 97, C["bg"], 14)
    text(s, 1026, y+17, step, 21, C["green"], True)
    text(s, 1073, y+13, label, 16, C["muted"], True)
    text(s, 1073, y+43, description, 24, bold=True, width=410)
    if step != "03":
        text(s, 1230, y+98, "↓", 28, C["green"])
rect(s, 1005, 638, 490, 59, C["green"], 13)
text(s, 1042, 650, "PLAZO TOTAL: 3 SEGUNDOS", 26, C["bg"], True)



s = slide("Observaciones que cambiaron el modelo", "Observar. Cambiar. Comprobar.", 35, "", "")
text(s, 70, 143, "Observar. Cambiar.\nComprobar.", 78, bold=True)
card(s, 70, 365, 470, 340, "01 · OBSERVAR", "Aprender del feedback",
     "Vimos qué recomendaciones recibían clics y cuáles terminaban en compra.")
card(s, 565, 365, 470, 340, "02 · CAMBIAR", "Reajustar el modelo",
     "Actualizamos los pesos con nuestro feedback para aprender de esos resultados.")
card(s, 1060, 365, 470, 340, "03 · COMPROBAR", "1,99% → 2,12%",
     "Conversión esperada observada.\n10.800 peticiones por versión.")
text(s, 75, 745, "Margen frente a la referencia de cada ventana: +0,17 puntos", 30, C["green"], True)

s = slide("Ideas descartadas / por qué repetimos las pruebas", "Una ronda no bastaba.", 35, "", "")
text(s, 70, 143, "Una ronda\nno bastaba.", 79, bold=True)
text(s, 810, 165, "¿Ayuda relacionar productos entre sí?", 25, C["green"], True)
text(s, 810, 204, "Conversión · usuarios conocidos en páginas", 22, C["muted"])
for x, label in [(830,"Ronda"),(1000,"Base"),(1175,"+ relaciones"),(1380,"Diferencia")]:
    text(s, x, 235, label, 22, C["muted"])
for y, vals, col in [
    (292, ["01","1,57%","1,77%","+0,20 pp"], C["green"]),
    (358, ["02","2,08%","1,67%","−0,41 pp"], C["orange"]),
]:
    for x, value in zip([830,1000,1175,1380], vals):
        text(s, x, y, value, 29 if x<1380 else 25, col if x==1380 else C["white"], True)
text(s, 830, 429, "No repitió la mejora → descartamos esa variante", 24, C["orange"], True)
rect(s, 70, 528, 1460, 112, C["card"], 16)
text(s, 100, 551, "También descartamos", 24, C["green"], True)
text(s, 100, 590, "Ni modelos más complejos ni el orden de las visitas mejoraron la validación", 27)
rect(s, 70, 681, 1460, 74, C["line"], 13)
text(s, 98, 701, "Elegimos un modelo lineal: aprende de clics y compras; se valida con datos posteriores", 26)

s = slide("Datos por versión / comparación con contexto", "Cada versión, con su contexto.", 35, "", "")
text(s, 70, 143, "Cada versión,\ncon su contexto.", 78, bold=True)
text(s, 1100, 158, "+0,17", 110, C["green"], True)
text(s, 1110, 290, "puntos de margen", 28, C["muted"])
text(s, 75, 355, "Reajustamos con nuestro feedback. Comparamos con la referencia de cada ventana.", 27, C["muted"])
rect(s, 70, 432, 1460, 249, C["card"], 22)
columns=[100,570,790,1050,1310]
for x,label in zip(columns,["Versión","Peticiones","Conversión","Referencia","Margen"]):
    text(s, x, 457, label, 22, C["muted"], True)
for y, vals, col in [
    (514, ["u1 · anterior","10.800","1,988%","1,944%","+0,044 pp"], C["muted"]),
    (590, ["u3k · reajustada","10.800","2,117%","1,906%","+0,212 pp"], C["green"]),
]:
    for x,value in zip(columns,vals):
        text(s, x, y, value, 29 if x<1310 else 27, col, True)
text(s, 75, 715, "Margen = conversión − referencia", 28, bold=True)

s = slide("Why it is fast / how RawTree supports it", "Precompute. Validate. Batch.", 35,
    "To protect the deadline, SQL aggregation runs in the background and local scoring stays small. "
    "We validate products before batched writes, with one writer and durable request claims. "
    "That design served ninety-nine-point-nine-six percent on time across forty-three thousand two hundred practice requests. "
    "RawTree snapshots and feedback let us trace a decision from input to outcome.",
    "presentation/cifras.md, sections 3 and 10: 15 Nov 03:00–07:00 UTC / 04:00–08:00 CET, "
    "43,182/43,200 on time; p50 1.22 s, p95 1.91 s, p99 2.35 s. "
    "144 scratch snapshots recorded. Handoff's p99≈2.0 s has no comparable window; use documented 2.35 s.")
text(s, 70, 145, "Precompute.\nValidate. Batch.", 73, bold=True)
text(s, 75, 397, "99.96%", 126, C["green"], True)
text(s, 82, 550, "valid and on time · 43,200 requests", 27)
text(s, 83, 602, "p99  2.35 s     /     deadline  3 s", 28, C["muted"])
rect(s, 890, 164, 640, 533, C["card"], 24)
text(s, 925, 196, "RAWTREE · TINYBIRD", 26, C["green"], True)
for j, (label, detail) in enumerate([
    ("Leer la tienda", "shop.requests · shop.events · shop.catalog_updates"),
    ("Agregar actividad con SQL", "Conteos por producto · ventanas temporales"),
    ("Enviar y aprender del resultado", "team_26.submissions → team_26.feedback"),
    ("Guardar evidencia", "team_26.scratch · 144 registros de métricas"),
]):
    y = 269+j*91
    rect(s, 925, y+7, 5, 29, C["green"] if j%2==0 else C["orange"], 2)
    text(s, 947, y, label, 28, bold=True, width=550)
text(s, 925, 652, "Trazabilidad: de la petición a su feedback.", 21, C["green"])

s = slide("How we worked / AI-assisted development", "Agents accelerated. Evidence decided.", 25,
    "We used Claude and Codex to implement experiments, audit code and find failure cases in isolated branches. "
    "People controlled integration, measurements and the single live deployment. "
    "The four of us covered modeling, independent challengers, cold-start research and reliability. "
    "The lesson was to use agents to move faster, while making every claimed improvement explainable and testable. "
    "Build fast. Verify carefully.",
    "Team roster supplied by the user. Claude/Codex use is confirmed at team level; no unconfirmed per-person "
    "tool or workstream assignment is asserted. Examples of agent work are in tasks and branch histories. "
    "Practice conversion 2.159% remains in EVIDENCE.md, not presented as a final result.")
text(s, 70, 149, "Agents accelerated.\nEvidence decided.", 79, bold=True)
card(s, 70, 395, 710, 235, "PROGRAMACIÓN", "Claude",
     "Implementation, integrations\nand experiments.")
card(s, 800, 395, 730, 235, "INVESTIGACIÓN", "Codex",
     "Audits, evaluation\nand failure cases.")
text(s, 75, 690, "Hypothesis → isolated code → tests → measured decision", 33, C["green"], True)
text(s, 75, 754, "Salvador Coll · Héctor Verdeal · Daniel Nieto · Javier Andrés García", 24)

def svg(s):
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(s["title"])}">']
    for sh in s["shapes"]:
        x,y,w,h = [sh[k] for k in ("x","y","w","h")]
        color="#"+sh["color"]
        if sh["kind"]=="rect":
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{sh["radius"]}" fill="{color}"/>')
        else:
            size=sh["size"]
            out.append(f'<text fill="{color}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{700 if sh["bold"] else 400}">')
            for j,line in enumerate(sh["lines"]):
                out.append(f'<tspan x="{x}" y="{y+size*.94+j*size*1.19}">{escape(line)}</tspan>')
            out.append("</text>")
    return "".join(out)+"</svg>"

A="http://schemas.openxmlformats.org/drawingml/2006/main"
P="http://schemas.openxmlformats.org/presentationml/2006/main"
R="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG="http://schemas.openxmlformats.org/package/2006/relationships"
DECL='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
GROUP='<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
CLR='<p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>'

def rels(items):
    return DECL+f'<Relationships xmlns="{PKG}">'+''.join(f'<Relationship Id="{i}" Type="{R}/{typ}" Target="{target}"/>' for i,typ,target in items)+'</Relationships>'

def paragraphs(lines,size=24,color="F5F7FA",bold=False):
    return "".join(f'<a:p><a:pPr marL="0" indent="0"/><a:r><a:rPr lang="es-ES" sz="{int(size*60)}" b="{int(bold)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Arial"/></a:rPr><a:t xml:space="preserve">{escape(line)}</a:t></a:r><a:endParaRPr lang="es-ES" sz="{int(size*60)}"/></a:p>' for line in lines)

def shape_xml(sh,i):
    x,y,w,h=[int(sh[k]*EMU) for k in ("x","y","w","h")]
    text_kind=sh["kind"]=="text"
    geom="roundRect" if sh.get("radius") else "rect"
    fill='<a:noFill/>' if text_kind else f'<a:solidFill><a:srgbClr val="{sh["color"]}"/></a:solidFill>'
    geomval='<a:avLst><a:gd name="adj" fmla="val 7000"/></a:avLst>' if sh.get("radius") else '<a:avLst/>'
    result=f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Shape {i}"/><p:cNvSpPr'+(' txBox="1"' if text_kind else '')+'/>'+'<p:nvPr/></p:nvSpPr>'
    result+=f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{geom}">{geomval}</a:prstGeom>{fill}<a:ln><a:noFill/></a:ln></p:spPr>'
    if text_kind:
        result+='<p:txBody><a:bodyPr wrap="none" lIns="0" rIns="0" tIns="0" bIns="0" anchor="t"/><a:lstStyle/>'+paragraphs(sh["lines"],sh["size"],sh["color"],sh["bold"])+'</p:txBody>'
    return result+'</p:sp>'

def build_pptx():
    parts={}
    def put(name,txt):parts[name]=txt
    put("_rels/.rels",rels([("rId1","officeDocument","ppt/presentation.xml")]))
    p_rel=[("rId1","slideMaster","slideMasters/slideMaster1.xml")]
    for i in range(1,len(slides)+1):p_rel.append((f"rId{i+1}","slide",f"slides/slide{i}.xml"))
    p_rel.append(("rId100","notesMaster","notesMasters/notesMaster1.xml"))
    put("ppt/_rels/presentation.xml.rels",rels(p_rel))
    put("ppt/presentation.xml",DECL+f'<p:presentation xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rId100"/></p:notesMasterIdLst><p:sldIdLst>'+''.join(f'<p:sldId id="{255+i}" r:id="rId{i+1}"/>' for i in range(1,len(slides)+1))+f'</p:sldIdLst><p:sldSz cx="{W*EMU}" cy="{H*EMU}" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle/></p:presentation>')
    put("ppt/slideMasters/slideMaster1.xml",DECL+f'<p:sldMaster xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld>{CLR}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>')
    put("ppt/slideMasters/_rels/slideMaster1.xml.rels",rels([("rId1","slideLayout","../slideLayouts/slideLayout1.xml"),("rId2","theme","../theme/theme1.xml")]))
    put("ppt/slideLayouts/slideLayout1.xml",DECL+f'<p:sldLayout xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{GROUP}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    put("ppt/slideLayouts/_rels/slideLayout1.xml.rels",rels([("rId1","slideMaster","../slideMasters/slideMaster1.xml")]))
    colors={"dk1":"101A29","lt1":"F5F7FA","dk2":"192638","lt2":"A6B5C8","accent1":"61E4B1","accent2":"FFAC86","accent3":"A6B5C8","accent4":"304154","accent5":"5088A8","accent6":"D6DDF5","hlink":"61E4B1","folHlink":"FFAC86"}
    scheme=''.join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k,v in colors.items())
    fill='<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    put("ppt/theme/theme1.xml",DECL+f'<a:theme xmlns:a="{A}" name="Team 26"><a:themeElements><a:clrScheme name="Team 26">{scheme}</a:clrScheme><a:fontScheme name="Arial"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Team 26"><a:fillStyleLst>{fill*3}</a:fillStyleLst><a:lnStyleLst>'+''.join(f'<a:ln w="{w}">{fill}<a:prstDash val="solid"/></a:ln>' for w in [9525,19050,28575])+f'</a:lnStyleLst><a:effectStyleLst>{("<a:effectStyle><a:effectLst/></a:effectStyle>")*3}</a:effectStyleLst><a:bgFillStyleLst>{fill*3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    put("ppt/notesMasters/notesMaster1.xml",DECL+f'<p:notesMaster xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>{GROUP}</p:spTree></p:cSld>{CLR}<p:notesStyle/></p:notesMaster>')
    put("ppt/notesMasters/_rels/notesMaster1.xml.rels",rels([("rId1","theme","../theme/theme1.xml")]))
    for i,s in enumerate(slides,1):
        shapes=''.join(shape_xml(sh,k+2) for k,sh in enumerate(s["shapes"]))
        put(f"ppt/slides/slide{i}.xml",DECL+f'<p:sld xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld name="{escape(s["title"])}"><p:spTree>{GROUP}{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
        put(f"ppt/slides/_rels/slide{i}.xml.rels",rels([("rId1","slideLayout","../slideLayouts/slideLayout1.xml"),("rId2","notesSlide",f"../notesSlides/notesSlide{i}.xml")]))
        ntext=f'{s["seconds"]} segundos. '+s["notes"]+"\nFUENTE / LÍMITE: "+s["source"]
        note=f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr txBox="1"/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs(ntext.splitlines(),18)}</p:txBody></p:sp>'
        put(f"ppt/notesSlides/notesSlide{i}.xml",DECL+f'<p:notes xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>{GROUP}{note}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')
        put(f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels",rels([("rId1","notesMaster","../notesMasters/notesMaster1.xml"),("rId2","slide",f"../slides/slide{i}.xml")]))
    overrides=[]
    for path in parts:
        if path.endswith(".rels"):continue
        if path=="ppt/presentation.xml":typ="presentation.main"
        elif "/slideMasters/" in path:typ="slideMaster"
        elif "/slideLayouts/" in path:typ="slideLayout"
        elif "/notesMasters/" in path:typ="notesMaster"
        elif "/notesSlides/" in path:typ="notesSlide"
        elif "/theme/" in path:
            overrides.append(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>');continue
        else:typ="slide"
        overrides.append(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.presentationml.{typ}+xml"/>')
    parts["[Content_Types].xml"]=DECL+'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+''.join(overrides)+'</Types>'
    with ZipFile(HERE/(DECK_STEM+".pptx"),"w",ZIP_DEFLATED) as z:
        for p,t in parts.items():z.writestr(p,t.encode("utf8"))

def build_html():
    sections=''.join(f'<section class="slide" aria-label="Diapositiva {i+1}">{svg(s)}</section>' for i,s in enumerate(slides))
    data=json.dumps([dict(notes=s["notes"],seconds=s["seconds"]) for s in slides]).replace("</","<\\/")
    evidence = (HERE/"datos_versiones.html").read_text(encoding="utf8")
    evidence_style = re.search(r"<style>(.*?)</style>", evidence, re.S).group(1)
    evidence_body = re.search(r"<body[^>]*>(.*?)</body>", evidence, re.S).group(1)
    html="""<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Equipo 26 — Presentación de tres minutos</title><style>
*{box-sizing:border-box}body{margin:0;background:#101a29;color:#f5f7fa;font-family:Arial,sans-serif}
#stage{height:100vh;display:grid;place-items:center}.slide{display:none;width:min(100vw,177.7778vh);height:min(56.25vw,100vh)}.slide.active{display:block}svg{display:block;width:100%;height:100%}
button{background:#26374a;border:0;border-radius:7px;color:white;padding:8px 12px;cursor:pointer}button:hover{background:#38516c}
aside{display:none;position:fixed;right:24px;top:24px;max-width:420px;padding:24px;background:#101a29f5;border:1px solid #61e4b1;border-radius:14px;font-size:18px;line-height:1.55}aside.open{display:block}
__EVIDENCE_STYLE__
dialog#versions{width:min(1440px,95vw);max-height:92vh;padding:12px;background:#101a29;color:#f5f7fa;border:1px solid #61e4b1;border-radius:18px}dialog#versions::backdrop{background:#000b}.close-data{position:sticky;top:0;float:right;z-index:2}
@page{size:13.333333in 7.5in;margin:0}@media print{html,body,#stage{width:13.333333in;height:auto}#stage{display:block}.slide,.slide.active{display:block;width:13.333333in;height:7.5in;break-after:page;page-break-after:always}.slide:last-child{break-after:auto;page-break-after:auto}nav,aside,dialog{display:none!important}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style><main id="stage">__PITCH_SECTIONS__</main><aside id="notes"></aside>
<dialog id="versions"><button class="close-data" onclick="document.getElementById('versions').close()">Volver al pitch · Esc</button>__EVIDENCE_BODY__</dialog>
<script>const data=__PITCH_DATA__;let idx=+(new URLSearchParams(location.search).get('s')||0);const pages=[...document.querySelectorAll('.slide')],note=document.getElementById('notes');
function show(i){idx=Math.max(0,Math.min(pages.length-1,i));pages.forEach((p,k)=>p.classList.toggle('active',k===idx));note.textContent=data[idx].seconds+' s — '+data[idx].notes;document.title='Equipo 26 — '+(idx+1)+'/6';}
function next(){show(idx+1)}function toggleNotes(){note.classList.toggle('open')}function full(){if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen()}function showData(){const v=document.getElementById('versions');if(v.open)v.close();else v.showModal()}
document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='d'){e.preventDefault();showData();return}if(document.getElementById('versions').open)return;if(['ArrowRight',' ','PageDown'].includes(e.key)){e.preventDefault();next()}if(['ArrowLeft','PageUp'].includes(e.key))show(idx-1);if(e.key.toLowerCase()==='n')toggleNotes();if(e.key.toLowerCase()==='f')full();if(e.key==='Home')show(0);if(e.key==='End')show(pages.length-1)});
show(idx);
if(new URLSearchParams(location.search).has('datos'))showData();
</script></html>""".replace("__PITCH_SECTIONS__",sections).replace("__PITCH_DATA__",data).replace("__EVIDENCE_STYLE__",evidence_style).replace("__EVIDENCE_BODY__",evidence_body)
    (HERE/"pitch.html").write_text(html,encoding="utf8")

def build_notes():
    out=["# Equipo 26 — presentación de tres minutos", "",
         "Seis diapositivas. Guion breve, pensado para hablar con pausas.",
         "Los tiempos son una guía de ensayo. Las fuentes y límites están en EVIDENCE.md y en el panel de datos del HTML.", ""]
    elapsed=0
    for i,s in enumerate(slides,1):
        end=elapsed+s["seconds"]
        fmt=lambda n:f"{n//60}:{n%60:02d}"
        out += [f'## {i}. {s["title"]} — {fmt(elapsed)}–{fmt(end)}', "", s["notes"], ""]
        elapsed=end
    words=sum(len(s["notes"].split()) for s in slides)
    out += ["## Cómo contarlo", "", f"Guion: {words} palabras. Plan completo: {elapsed} segundos.",
            "Ensaya una vez en voz alta. No leas los números de muestra con prisa: haz una pausa tras cada idea.",
            "Flecha derecha/espacio avanza; N muestra notas; F activa pantalla completa. Sin temporizador ni botones inferiores.",
            "D abre los datos por versión; Esc vuelve al pitch. No leas las tablas completas durante los tres minutos.",
            "El foco es CÓMO y POR QUÉ. Los cuatro nombres aparecen al final, sin un reparto de funciones no confirmado.",
            "Si preguntan por más detalle, HOW_AND_WHY.md contiene un recorrido por el código. No atribuyas a la final los resultados de práctica.",
            "La comparación de +0,17 puntos usa bloques temporales: no la describas como A/B aleatorizado.",
            "Puedes terminar entre 2:40 y 3:00 dejando pausas. El objetivo es transmitir las decisiones, no agotar el cronómetro.", ""]
    (HERE/"SCRIPT.md").write_text("\n".join(out),encoding="utf8")
    (HERE/"GUION_ES.md").write_text("\n".join(out),encoding="utf8")
    (HERE/"slides.json").write_text(json.dumps(slides,indent=2),encoding="utf8")
    for i,s in enumerate(slides,1):(HERE/f"slide_{i:02d}.svg").write_text(svg(s),encoding="utf8")
    print(json.dumps(dict(slides=len(slides),seconds=elapsed,script_words=words,html=str(HERE/"pitch.html"),
                          pptx_requested="--pptx" in sys.argv)))

if __name__=="__main__":
    build_html();build_notes()
    if "--pptx" in sys.argv:
        build_pptx()
