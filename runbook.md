# Operations runbook — RawTree realtime recommender

**Status:** official setup commands VERIFIED in public repo; **team deployment NOT YET TESTED**. One process must run continuously from practice through Sunday final. Handle secrets privately; never commit `.env`.

## Source and credentials

Official repo: https://github.com/rawtreedb/datathon-fme-2026

```bash
# Only if team has NOT yet cloned the official starter:
git clone https://github.com/rawtreedb/datathon-fme-2026.git
cd datathon-fme-2026
cp .env.example .env
# Edit .env privately with TEAM_ID=team_NN and RAWTREE_API_KEY=<secret>
# Use the existing virtualenv; if needed only:
pip install -r starter/requirements.txt
python starter/recommender.py
```

Official alternative without changing global Python: `uv run --with requests python starter/recommender.py` (verify your env already has needed dependencies). **Do not run a second live recommender if one is already serving; duplicates are not a legitimate policy comparison.** `TEAM_ID` and `RAWTREE_API_KEY` are supplied at RawTree stand.

RawTree endpoint: `https://api.rawtree.com`, bearer authorization. For terminal queries the official CLI offers:

```bash
rtree query --api-key "$RAWTREE_API_KEY" --database "$TEAM_ID" "SELECT count() FROM shop.requests"
```

You can query with Python HTTP API `POST /v1/query` `{"sql":"..."}` and submit batch JSON to `POST /v1/tables/submissions?database=$TEAM_ID`. Dynamic typed columns often need casts like `product_id::String`, `ts::DateTime64(3)` in SQL joins/aggregations. Reuse official `starter/queries.sql` when possible.

## Live polling and submission invariants

- `shop.requests`: ~**3/sec**. The starter queries 50 newest records and polls every **0.3 seconds**. A stall beyond ~16.7s at advertised rate can overrun the 50-record window; instrument gaps and consider durable request cursor / overlapping backfill.
- One record per request in `<TEAM_ID>.submissions`: `request_id`, ordered `items` with **exactly 10 unique and currently active IDs**, `model_version`.
- Endpoint insert must reach RawTree **within 3 sec of the request's UTC `ts`**. Batch ~0.5 sec; don't add ML model fitting or large SQL joins to request path. Normal starter ~1sec, p95 ~1.5sec total from `ts`.
- Model version ledger maps `request_id` to policy version. Do not rely on `feedback` to contain model_version. Retried POSTs require careful duplicate prevention.
- `shop.catalog_updates`: full latest product record, including new product, price change, stockout/back-in-stock. Rebuild current active/price cache from base catalog + latest updates; refresh frequently, validate final slate again just before posting.
- Response must be ordered. User sees first slots disproportionately often. Avoid known-inactive products, duplication, nonexistent IDs, or fewer/more than ten.

## Quick health checks

Query your team's `feedback` (ignore `request_id='__init__'`):

```sql
SELECT served_by::String AS served_by,
       fallback_reason::String AS reason,
       count() AS requests,
       quantile(0.95)(latency_ms::Float64) AS p95_ms,
       100.0 * countIf(purchased != '') / count() AS realized_conversion_pct
FROM team_NN.feedback
WHERE request_id != '__init__'
GROUP BY served_by, reason
ORDER BY requests DESC;
```

Replace `team_NN` with actual team DB; if you are querying using `$TEAM_ID`, substitute it safely in code. Example starter SQL also includes hourly conversion/revenue and last-30-minute fallback/latency. **Realized** conversion is *not* the official hidden expected-conversion score.

Health expectations: `served_by='team'` nearly always, `fallback_reason` usually blank, no `missing`/`late`/`invalid`, p95 comfortably under 3000ms. Monitor p99 and maximum, not just model inference. During final leaderboard only **team green/red health light** visible: green means **>90% valid and on-time over last 5 min**, it is not a quality score.

## Preflight checklist

- [ ] Confirm Sunday **Nov 15 10:00 CET** start, 12:00 end; monitor local time versus UTC event timestamps.
- [ ] Team id and API key configured privately in `.env` or environment. `.env` is `.gitignore`d; verify before commit.
- [ ] Existing virtualenv selected; starter script reads and writes RawTree successfully.
- [ ] Only **one** live writer; no accidental duplicate team submissions from tests/staging.
- [ ] All replies exactly ten unique active IDs; test missing user/session, new buyer, new product, price/stock changes and unexpected nulls.
- [ ] Last-known good model/champion and baseline fallback available; tested rollback command.
- [ ] Real `team_NN.feedback` confirms valid servability, latency, and not fallback.
- [ ] Request ledger/dedup survives process restart; no missed/newest-window races.
- [ ] Model artifacts cached, no full historic SQL in inference path.
- [ ] Machine/network stable; disable laptop sleep/hibernation, check AC power and Wi-Fi; designate monitoring/backup owner.
- [ ] Evidence/plots for jury: history feature SQL, time-split validation and controlled learning demonstration.

## Incident response

| Symptom | Action |
|---|---|
| `fallback_reason='late'` | Measure source timestamp to write acknowledgement; disable costly on-request inference, reduce batch delay, check network/query time; restore known fast champion |
| `invalid` | Check 10 distinct active real products, recent stockouts/new catalogue, serialized JSON/schema, duplicates; revert safely |
| `missing` | Inspect live process liveness, request backlog, polling cursor/window, API authorization/network; restart single supervised writer |
| RawTree SQL `Illegal type Dynamic` | Add explicit casts in joins/aggregate expressions (`::String`, `::DateTime64(3)`) |
| `Unknown expression identifier` on empty live tables | May occur before stream has rows; retry; shouldn't persist once live events arrive |
| Stock cache stale | Merge latest `catalog_updates`, refresh before slate validation; use known valid eligible candidates |
| Model regression / errors | Revert to pinned champion, retain one writer, log incident and measured effect in `experiments.md` |

## Timeline and freeze

- **Practice:** Sat Nov 14 10:00–Sun Nov 15 10:00 CET; leaderboard refreshed each **10min** with **last-hour** estimate. Historical offline benchmark is primary development signal.
- **Final:** Sun Nov 15 10:00–12:00 CET; new data distribution, leaderboard blacked out, monitor `feedback` and health only. Changes allowed but high-risk changes strongly discouraged. Stay online continuously.
- **12:00:** organizers stop stream and publish final ranking; jury presentation Sunday afternoon. Preserve readable repo and evidence; no submission file required.

## Team-specific operations to fill in

| Item | Command / owner / artifact |
|---|---|
| Exact Python interpreter/venv activation | TBD |
| Single-writer start/restart supervisor | TBD |
| Run unit/integration tests | TBD |
| Model/policy champion version and pinned commit | TBD |
| RawTree feature refresh process | TBD |
| Deployment host / backup machine / network monitoring | TBD |
| Rollback command and responsible person | TBD |
| Jury demo command and figures | TBD |

Official sources: https://datathon.rawtree.dev/ ; https://github.com/rawtreedb/datathon-fme-2026

## Offline league v2

See `tools/LEAGUE.md` for train/validation/test preparation, policy registration and freeze/final-test commands. Use the existing team virtualenv; no installations required. This offline workflow does not launch, stop or modify the live champion. The cached historical test must stay unscored until policy selection is frozen. Rollback requires no live action: retain the current champion and discard/revert offline-only changes if needed.

## v1-gbm reliability handoff — T-014 (2026-11-14)

Actual owner: **Javi on his laptop** (user report). Standalone tested code fix: `7176c03` on `salva/serving-reliability`, based on Javi's `5541d74`. It has not been deployed. Javi can fetch and cherry-pick that commit onto his existing branch without merging the imported snapshot or unrelated docs. Run tests with his existing environment and history artifact, then coordinate a single-writer handoff. See `recsys/README.md` for commands, lock/journal paths, telemetry, limitations and rollback.

Read-only diagnosis: `python tools/reliability_audit.py --minutes 30`; source/reason counts and p95/p99 by five-minute UTC bucket. An hourly 76% score can include old disruptions: measured recent 30-minute acceptance was 99.30%. Do not start another process to chase the rolling score. Current stock/transport risks still warrant the staged patch, but no post-fix E2E improvement has yet been measured. Do not delete the persistent attempts journal or blindly resend uncertain POSTs. Local lock cannot protect against another laptop or unpatched baseline.

## Variante qrank en el writer — T-015 (2026-11-14)

Rama `javi/qrank-serving` = writer robusto de Salva (`7176c03`) + ranker `recsys/qrank.py`. No está desplegado. Sigue habiendo **un único writer**.

- Arranque normal: `python recsys/live.py` sirve v1 como hasta ahora. Probar antes con `--dry-run` (no escribe).
- Cambiar de variante sin reiniciar: escribir `recsys/data/policy.json` con `{"variant": "v1"}`, `{"variant": "qrank"}` o `{"variant": "ab_qrank"}`. El proceso lo relee cada ~20 s y lo anota en el log (`{"event": "policy", ...}`).
- Prueba recomendada: `ab_qrank` durante 30–60 min y `python recsys/compare_versions.py 60` para comparar `v1-gbm-cand-r1` con `v2-qrank-r1` (compras reales; con ~5.000 peticiones por brazo y hora se distingue 1,3% de 2,1%). Para el leaderboard, un bloque de 10 min con `qrank` alineado con `updated_at`.
- Brazos de afinado (T-019): `{"variant": "qrank", "qrank_arms": [{"tag": "vf045", "viewed_factor": 0.45}, {"tag": "vf100", "viewed_factor": 1.0}]}` reparte a los usuarios por hash entre los brazos (2 a 4) y escribe cada uno como `v2-qrank-<tag>`; se comparan en `https://datathon.rawtree.dev/api/state?by=model` (conversión esperada del modelo oculto por `model_version`). Quitar `qrank_arms` vuelve a `v2-qrank-r1`. Solo afecta a las peticiones de qrank puro (no a `qrank_aff`).
- Rollback: `{"variant": "v1"}` en `policy.json`, o borrar el archivo y reiniciar.
- Variante `lfm` (D-180): `{"variant": "ab_lfm"}` reparte 50/50 entre qrank y lfm; `{"variant": "lfm"}` lo pone al 100%. Sus respuestas salen como `v3-lfm-r1-k|-n|-kh|-nh` (vuelve, nuevo, y sus home), legibles por separado en `api/state?by=model`. Reajustar pesos: `python lfm_build.py --pull` y reiniciar el writer.
- Brazos de lfm (D-210): añadir `"lfm_arms": [{"tag": "r1"}, {"tag": "r2", "file": "lfm_coef_r2.json"}]` a `policy.json` reparte a los usuarios entre brazos sin reiniciar; cada brazo sale como `v3-lfm-<tag>-k|-n|-kh|-nh` (con `labels.json`, el código público de cada uno queda en el log como `{"event": "label"}`). Quitar la clave vuelve a lfm normal.
- Política rechazada (D-430, con el código de T-043 cargado): si `policy.json` o uno de sus ficheros de pesos está mal (JSON cortado, variante desconocida, lista de brazos inválida, fichero de pesos ausente o incompleto, coeficientes no finitos), el writer **no cambia nada** y escribe una vez `{"event": "policy_rejected", "reason": ..., "kept": {"variant": ..., "lfm_arms": [...]}}`. Sigue sirviendo la última política válida. Corregir el fichero (o copiar el fichero de pesos que faltaba) basta: entra en el siguiente ciclo y el log dice `{"event": "policy_recovered"}`. Comprobar siempre en el log que tras un cambio aparece `{"event": "policy", ...}` y no `policy_rejected`.
- Afinador de lfm (D-230): con el writer en `lfm`, desde `recsys/`: `python lfm_tuner.py check` y luego `caffeinate -i python lfm_tuner.py run --until 08:30 2>&1 | tee -a data/lfm_tuner.log`. Solo escribe `lfm_arms` en `data/policy.json` y `data/lfm_tuner/`; no llama a RawTree. `python lfm_tuner.py report` da la tabla de rondas. Ctrl-C deja un brazo `best` con los pesos ganadores (con el writer anterior a T-023, usar `--finish off`). No correrlo a la vez que `night_lab.py`: los dos escriben `policy.json`.
- lfm r3 (D-240): con el writer reiniciado en un commit que incluya T-024, `"lfm_arms": [{"tag": "r1"}, {"tag": "r3", "file": "lfm_coef_r3.json"}]` compara los pesos con reparto de categorías del usuario contra los publicados. Reajuste: `python lfm_build.py --pull --out lfm_coef_r3.json`.
- Reconstruir el artefacto: `cd recsys && python qrank_build.py --pull` (scikit-learn 1.9.1).

## Laboratorio nocturno contra el leaderboard — T-016 (2026-11-14)

`recsys/night_lab.py` rota las variantes del writer único por bloques y mide cada una con el leaderboard. Solo escribe `recsys/data/policy.json`, `recsys/data/d130.json` y sus logs en `recsys/data/night_lab/`. No usa la API key ni habla con RawTree. **No es un writer y no sustituye a `live.py`: `live.py` tiene que seguir corriendo en otra terminal.**

**Antes de arrancar (5 min)**

1. El writer debe estar sano. Si `on_time` está bajo (el 14/11 a las 13:30 UTC estaba en 57–73% y cayendo), arréglalo primero: lo tardío lo sirve el baseline y diluye todas las medidas.
2. El `live.py` que está corriendo tiene que entender todos los brazos del plan. Una variante que no conoce la ignora sin avisar. Compruébalo contra el código en disco (si el proceso arrancó con otro código, reinícialo antes):
   ```bash
   cd recsys
   python night_lab.py check --arms v1,qrank,qrank+home,qrank_aff+home
   ```
   `qrank` necesita el PR #1; `aff`, `qrank_aff` y los `ab_*` de afinidad necesitan `recsys/aff_live.patch` aplicado (PR #2); `+nodead` y `+home` necesitan el hook d130 (PR #3).
3. Prueba en seco un par de minutos (no escribe los JSON): `python night_lab.py run --arms v1,qrank --dry-run --block-min 3 --until HH:MM`.

**Arrancar** (en el Mac, en una terminal aparte; `caffeinate` evita que el Mac se duerma):

```bash
cd recsys
caffeinate -i python night_lab.py run --arms v1,qrank,qrank+home,qrank_aff+home --until 08:30 2>&1 | tee -a data/night_lab.log
```

- Un brazo es `variante` o `variante+modo_d130`. Sin `+modo`, d130 queda en `off`.
- Bloques de 65 min: 60 de ventana del leaderboard, 3 de asentamiento tras el cambio y 2 de margen. Así la conversión de cada bloque se lee directamente de la ventana horaria, sin supuestos. De 23:00 a 08:30 caben 8 bloques: dos réplicas de cuatro brazos.
- Empieza por `v1` si es lo que ya corre: sirve de control y de referencia para la guardia.
- En el primer minuto mira la terminal de `live.py`: debe salir `{"event": "policy", "variant": ...}` en cada cambio de variante y `d130 mode -> ...` en cada cambio de modo. Si no salen, el writer no está leyendo los ficheros.
- Los brazos `ab_*` reparten 50/50 dentro del writer: el leaderboard solo ve la mezcla. Sirven para `compare_versions.py`, no para esta tabla.

**Guardia.** Pasados 10 min de un bloque, si el `on_time` implícito del bloque queda más de 10 puntos por debajo del brazo seguro (`--safe`, por defecto `v1`), o su lift cae a menos de la mitad, durante 3 snapshots seguidos, el laboratorio vuelve al mejor brazo medido hasta el final del bloque y no vuelve a probar el brazo culpable. Peor caso: unos 13 min con una variante rota. El brazo seguro nunca se retira. Umbrales: `--guard-on-time-drop`, `--guard-lift-drop`, `--guard-consec`, `--guard-after-min`.

**Parar y volver atrás.** Ctrl-C (o `kill`): cierra el bloque y deja `policy.json` y `d130.json` exactamente como estaban antes de empezar. Lo mismo al llegar la hora límite, si el leaderboard sale de modo práctica o si falta menos de 60 min para la final. Vuelta atrás manual si el proceso muere de golpe: `echo '{"variant": "v1"}' > data/policy.json; echo '{"mode": "off"}' > data/d130.json`. Con `--finish best` deja puesta la mejor variante medida; por defecto no promociona nada.

**Por la mañana.** `recsys/data/night_lab/report.md` tiene la tabla por brazo y por bloque (se reescribe al cerrar cada bloque; `python night_lab.py report` la regenera). Mira el rango entre réplicas antes de creer una diferencia, y `lift_ot` para separar ranking de latencia. Decidid el campeón y dejadlo fijo antes de las 09:00 CET.

**Límites.** El leaderboard mide todo el tráfico junto: no separa home de product/category. El cold start (`lift cold`) sale de menos peticiones. La columna "ajuste" supone conversión constante dentro del bloque y solo es fiable con tráfico estable.

## Reinicio sin pérdida y arranque — T-022 (2026-11-14)

- **Reiniciar con relevo** (en el Mac, desde `recsys/`, con el writer viejo en marcha; no pararlo antes):
  `caffeinate -i nohup ../../.venv/bin/python live.py --takeover >> data/live_main.log 2>&1 &`
  Si el writer viejo es anterior a T-022 (no dejó `writer.pid`), añadir `--replace-pid <pid>`. El nuevo tarda 1–2 min en cargar y calentar; el viejo sigue respondiendo todo ese tiempo.
- **Qué mirar en el log:** `{"event": "warm_up", ...}`, luego `{"event": "takeover", "old_pid": ..., "waited_ms": ..., "signals": [...]}` y `ready LIVE`. El viejo escribe `{"event": "stopped"}` (si es de T-022). Comprobar con `pgrep -fl live.py` que queda uno solo.
- **Si el relevo falla** (`Takeover failed: ...`): el nuevo sale sin escribir nada y el viejo sigue. Señales al viejo: SIGINT al momento, SIGTERM a los 3 s, SIGKILL a los 6 s; se rinde a los 12 s.
- **Parar a mano:** `kill -INT <pid>` o `kill <pid>`; el writer de T-022 termina el bucle en curso y suelta el candado.
- **Arranque en frío** (sin writer previo): `python live.py` como siempre. Ya no hay bloqueo de ~60 s tras `ready`: responde desde el primer bucle con features históricas mientras aplica el día en trozos.
- **Memoria:** durante el relevo hay dos procesos de ~2,8 GB. Cerrar lo que sobre en el Mac antes de lanzarlo.
- **`EVENTS_SINCE`:** el writer aplica `shop.events` desde `2026-11-14 07:00:00`. **Para la final NO se cambia** (corregido por T-036, D-360): arrancar el domingo con `EVENTS_SINCE='2026-11-15 ...'` borraría las 98.005 compras orgánicas del sábado de las exclusiones (el 59% de los usuarios que nos pidieron carrusel compró algo el sábado), sus carritos y sus vistas. La carga va por ventanas de una hora, así que el rango largo no agota la consulta. Si algún día hiciera falta separar el sábado del domingo, se hace con `state_window` en `policy.json` (ver abajo), nunca recortando los eventos.
- **Parones:** cualquier recolección de basura de más de 200 ms queda como `{"event": "gc_pause", ...}`. Si tras este cambio sigue habiendo bucles de varios segundos sin `gc_pause` al lado, la causa es otra (red o reposo del Mac).
- **Ensayo sin escribir** (en otra máquina, nunca junto al writer): ver la cabecera de `tools/handoff_rehearsal.py`.

## Brazos fusionados de lfm — T-025 (2026-11-14)

Un brazo de `lfm_arms` puede llevar `"home": {...}` (misma forma que el brazo: `file` y/o `w`; `{}` = pesos publicados) para usar otros pesos en las peticiones de home (sin vistas recientes). Sirve para juntar lo mejor de dos brazos cuando uno gana en producto/categoría y otro en home:

```json
{"variant": "lfm", "lfm_arms": [{"tag": "r1"}, {"tag": "f1", "w": {"known": {"hcart": 1.5, "islast": 3.0}, "new": {"nbp": 0.6, "bsub": 0.6}}, "home": {}}, {"tag": "r3", "file": "lfm_coef_r3.json"}]}
```

Las etiquetas no cambian (`v3-lfm-<tag>-k|-n|-kh|-nh`). Sin `home` el brazo se comporta como antes. Necesita un reinicio (con relevo) para cargar el código.

## lfm r5: co-ocurrencia producto a producto — T-027 (2026-11-14)

Con el writer reiniciado (con relevo) en un commit que incluya T-027:

```json
{"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "r5", "file": "lfm_coef_r5.json"}]}
```

r5 son los pesos de r3 más `cv` (grafo `recsys/lfm_graph_B.json`, se carga solo al arrancar). Etiquetas `v3-lfm-r5-k|-n|-kh|-nh`. Para probar otro peso sin reiniciar: `{"tag": "r6", "file": "lfm_coef_r3.json", "w": {"known": {"cv": 0.5}, "new": {"cv": 0.5}}}`. Rehacer el grafo: `python lfm_graph_build.py`; reajustar: `python lfm_build.py --pull --base lfm_coef_r3.json --add cv --out lfm_coef_r5.json`.

## Ventanas de estado de lfm en el paso de práctica a final — T-036 (2026-11-14)

Definiciones en D-360. **Por defecto no hay ventana de día y no hay que hacer nada el domingo**: ni reiniciar, ni tocar `EVENTS_SINCE`, ni `policy.json`.

- Writer que sigue encendido toda la noche: conserva el estado del sábado. Correcto.
- Writer reiniciado el domingo: con `EVENTS_SINCE` por defecto recarga el sábado por ventanas de una hora y la primera lectura de feedback trae todas las compras del carrusel. Llega al mismo estado (test `test_a_restart_on_sunday_rebuilds_the_same_state`).
- Corte del lector de feedback (T-066): las lecturas siguientes parten de la última lectura buena menos 10 min (`FB_OVERLAP_S`), así que un corte de cualquier duración se relee entero al volver. `fb refresh failed` en el log = la marca no avanza. Una fila que llegue más de 10 min después de su `ts` solo se recupera al reiniciar.
- Interruptor opcional, sin reinicio una vez cargado el código de T-036: `"state_window": {"day_start": "2026-11-15 00:00:00", "carts": "persistent"}` en `data/policy.json`. Con él, solo las compras desde `day_start` alimentan las features de "comprado hoy"; las compras siguen excluidas siempre. `"carts": "day"` además pasa los carritos anteriores a carritos de histórico (no los borra). **No recomendado sin lectura del leaderboard**: en datos reales cambia el 42% de los slates (48% con `carts: day`) y no hay evidencia de que ayude (E-360).
- Vuelta atrás: quitar `state_window` de `policy.json` (el writer lo aplica en el siguiente ciclo y lo escribe en el log como `{"event": "policy", "state_window": null}`).
- **Compras anteriores a la final (T-063, `prior_purchases`)**. Solo existe con el código de T-063 cargado; un writer anterior ignora la clave sin avisar. Clave de primer nivel de `data/policy.json`, recargable en caliente, junto a `variant` y `lfm_arms`:
  - ausente o `null`: comportamiento de siempre, nada se cuenta (por defecto).
  - `"prior_purchases": {"boundary": "2026-11-15 09:00:00"}` (o `"mode": "exclude"`): mismas respuestas que sin la clave; solo activa el diagnóstico en sombra.
  - `"prior_purchases": {"boundary": "2026-11-15 09:00:00", "mode": "allow"}`: las compras en vivo (flujo orgánico desde `EVENTS_SINCE` y nuestras compras del carrusel) cuya última fecha es anterior a `boundary` (UTC) dejan de excluirse en `lfm.scores` y en la guarda de envío (`live.user_bought`, que usan `repair_for` y `fallback_answers`). Compiten con su puntuación normal.
  - Siguen excluidas en ambos modos: compras desde `boundary`, compras sin fecha y compras del histórico de 60 días. No se borra nada: vistas, carritos, preferencias y `EVENTS_SINCE` no cambian. Un valor inválido rechaza la política entera (`policy_rejected`) y se conserva la activa.
  - **Ojo**: la clave vive en `data/policy.json`. Copiar encima otro fichero de política sin la clave la apaga. Las ramas sin lfm (qrank, attr) no la miran.
  - Versión activa: cada cambio escribe `{"event": "policy", "prior_purchases": ...}` en el log, y con frontera activa hay una línea `{"event": "prior_purchases", "boundary", "mode", "requests", "requests_with_prior", "prior_candidates", "requests_entering", "products_entering", "top3_requests"}` cada 5 minutos (en `exclude`, cuántas entrarían en el top 10 sin tope de lanzados; en `allow`, cuántas se sirvieron). Al reiniciar, el modo se reconstruye de `policy.json` y de las fechas del flujo.
  - Vuelta atrás: quitar la clave (o `"mode": "exclude"`); se aplica en el siguiente ciclo, sin reinicio.

## lfm r6: filtrado colaborativo — T-035 (2026-11-14)

`recsys/lfm_mf.npz` (4 MB, versionado) se carga una vez al arrancar; si falta, `mf` vale 0. Brazo: `{"tag": "r6", "file": "lfm_coef_r6.json"}` (pesos de r3 más `mf` = 0,0627 en conocidos, 0 en nuevos). Otro peso sin reiniciar: `{"tag": "r6b", "file": "lfm_coef_r6.json", "w": {"known": {"mf": 0.125}}}`. Rehacer los factores (no hace falta salvo que cambie el histórico): `python download_user_items.py && python lfm_mf_build.py`. Evidencia y regla de decisión: E-350, D-350.

## Arreglo de precios del snapshot de lfm y confirmación de retadores — T-042 (2026-11-14)

- Síntoma del fallo (código hasta `6150ffc`): con un brazo `"lq"` en `lfm_arms` y productos lanzados hoy, `LF.snap.p40.sum()` y `LF.snap.cheap.sum()` valen 0. Con el arreglo son del orden de 2.000 y 1.700 (de 5.400 productos).
- Comprobar sin escribir nada, en otra máquina: `cd recsys && python cold_lq_replay.py --pull && python snap_price_replay.py --n 6000` (E-421). Prueba en seco del writer: `python live.py --dry-run` con la política a probar copiada en `data/policy.json`.
- Despliegue: un reinicio con relevo (sección T-022) desde la rama con el arreglo. Lo decide Javi. No cambia pesos, política, catálogo, stock ni estado.
- Comparaciones tras el reinicio (D-420), una cada vez, anotando cada cambio en `data/policy_changes.log`:
  1. `cp policy.fix_a_cold_new.json data/policy.json` → `cold_new` contra r3 en usuarios nuevos de producto/categoría.
  2. `cp policy.fix_b_np1.json data/policy.json` → `np1` contra r3 en usuarios conocidos de producto/categoría.
  3. Campeón corregido solo: `cp policy.fix_champion.json data/policy.json`.
- Lectura de una ventana: `python recsys/confirm_read.py --from "2026-11-15 00:10" --to "2026-11-15 01:40" --control <código> --challenger <código> --sd 6.0` (usar `--sd 5.5` para conocidos). Los códigos públicos de `r3p`, `cn1p` y `np1p` salen en el log del writer como eventos `label` al servir la primera petición de cada uno.
- Vuelta atrás: política, `cp policy.fix_champion.json data/policy.json`; código, reinicio con relevo desde `6150ffc` y `cp policy.champion.json data/policy.json`.


## Vigilancia y relevo entre máquinas (final) — T-063 (2026-11-15)

Evidencia: E-630..E-632. Decisión: D-630. Nada de esto toca al writer del Mac: el vigilante solo lee y el modo de espera es un proceso aparte que no escribe hasta que una persona lo promueve.

**Vigilante (solo lectura; en una máquina que NO sea la del writer).**

- Una pasada: `python3 tools/watchdog.py --once` (añadir `--json` para máquina). Código de salida 0 = OK, 1 = WARN, 2 = CRITICAL.
- En continuo: `python3 tools/watchdog.py --watch 20` (una línea cada 20 s, más los motivos si los hay).
- La lista de guardia se reconoce por su etiqueta pública: `--guard-labels m0312d` (por defecto). Si cambia `labels.json` o escribe otra máquina, la etiqueta cambia: mirar el evento `label` de `...-guard` en el log del writer y pasarla aquí.
- Ventanas: `--window 5` (minutos recientes), `--baseline 45`, conversión `--conv-window 30` contra los 90 minutos anteriores. Los últimos 8 s se dejan fuera porque el feedback llega con retraso (E-630).

| Señal | WARN | CRITICAL |
|---|---|---|
| Sin fila servida por el equipo (y sí llegan filas de reserva) | > 10 s | > 20 s (`writer_silent`) |
| Sin ninguna fila de feedback | > 20 s (`feedback_stale`: fallo del feedback o de la consulta, no dice nada del writer) | — |
| `missing` | > 1% en 5 min, o > 5% en el último minuto | > 5% en 2 minutos seguidos |
| `invalid` | > 0,5% en 5 min, o > 2% en el último minuto | > 2% en 2 minutos seguidos |
| Lista de guardia | > 2% en 5 min | > 20% en 2 minutos seguidos |
| Latencia servida | p95 ≥ 2.400 ms o p99 ≥ 2.700 ms | p99 ≥ 2.900 ms |
| Peticiones por minuto | < 120 | — |
| Conversión | intervalo reciente entero por debajo del de referencia, **solo** con ≥ ~3.200 peticiones recientes (≈18 min) y ≥ 100 compras de referencia | nunca |

La conversión nunca da CRITICAL y con 5 minutos (unas 900 peticiones, 18 compras) no puede dar ni aviso: la salida dice siempre la muestra mínima y si se alcanza. Normal medido (E-630): `missing` < 0,1%, guardia 0,1–0,6%, p99 2,3–2,5 s, última fila servida hace 1–2 s.

**Qué protege a quién.** El candado `writer.lock` es local: solo impide dos writers en la MISMA máquina. Entre máquinas no hay exclusión: un segundo `live.py` en otro equipo arranca sin conflicto y responde las mismas peticiones, y un writer que vuelve de un corte de red o del reposo sigue escribiendo sin comprobar nada (E-631). Con dos writers nuestra lista llegó solo al 37% de los compradores (I-017). El writer del Mac no se reinicia antes de la final, así que hoy la exclusión entre máquinas es este procedimiento, no el código.

**Arrancar un proceso en espera** (en la segunda máquina, desde `recsys/`, con el mismo commit, la misma `data/policy.json` y la misma `data/labels.json` que el Mac; sin `labels.json` escribiría las etiquetas internas en el leaderboard):

`nohup python live.py --standby --promote-token <palabra> >> data/standby.log 2>&1 &`

Carga como un writer normal (unos 3–4 min), mantiene el estado al día, puntúa peticiones reales y **no envía nada**: en el log sale `ready STANDBY (not writing)`. No toma el candado local ni escribe en `scratch`. Arrancarlo es decisión de Javi (es un `live.py` sin `--dry-run`); mientras nadie lo promueva no puede escribir (lo impide también `post_batch`).

**Promover (solo a mano, nunca automático).**

1. El vigilante da `CRITICAL writer_silent` de forma sostenida (≥ 30 s) y el Mac no se recupera ya.
2. Confirmar que el writer del Mac está muerto: en el Mac, `pgrep -fl live.py`; si sigue vivo, `kill -INT <pid>` y, si no sale, `kill -9 <pid>`. Si el Mac no responde (sin red, en reposo), dejarlo sin red o apagado: **no debe volver a escribir mientras escriba el relevo**.
3. En la máquina en espera: `echo "<palabra>" > recsys/data/PROMOTE`.
4. En `data/standby.log`: `{"event": "promoted", ...}` y `ready LIVE (promoted)`. Si sale `{"event": "promote_refused", "reason": ...}`: `another_writer_is_answering` = alguien respondió peticiones de los últimos 4–12 s (el Mac sigue vivo; volver al paso 2, el mismo fichero vale durante 120 s y se reintenta cada segundo); `local_lock_held` = hay otro writer en esa misma máquina.
5. Vigilante: `writer_silent` desaparece en unos 10 s. Pasar la nueva etiqueta de guardia a `--guard-labels`.

El fichero solo vale si se escribe después de arrancar el proceso (o de su última cesión), si tiene menos de 120 s y si la primera palabra es la del arranque. `echo "<palabra> FORCE" > recsys/data/PROMOTE` se salta la comprobación de "nadie más responde" y desactiva la cesión automática: solo si la comprobación falla por la consulta y se ha verificado a mano que el Mac está parado.

**Si el Mac vuelve mientras escribe el relevo.** El relevo mira cada 3 s los envíos de las peticiones de hace 4–12 s; si hay 5 o más que no son suyos, deja de escribir, suelta el candado y vuelve a la espera (`{"event": "stepped_down", "reason": "foreign_writer:..."}`). Eso deja entre 10 y 20 s de respuestas duplicadas y después un solo writer (el Mac). Para volver a promover hace falta un fichero nuevo. Desactivar la cesión: `STANDBY_YIELD=0` al arrancar.

**Vuelta atrás.**

- Parar el relevo: `kill -INT <pid>` en su máquina (termina el bucle y suelta el candado). Desde ese momento no escribe nadie hasta que arranque otro writer.
- Volver al Mac sin hueco largo: arrancar el Mac también en espera (`live.py --standby --promote-token <otra>`), esperar a `ready STANDBY`, parar el relevo con `kill -INT` y escribir el `PROMOTE` del Mac (hueco de unos 12–15 s, lo que tarda la comprobación en ver silencio). No arrancar el Mac con `python live.py` ni con `--takeover` mientras el relevo escribe: `--takeover` solo ve writers de su propia máquina.
- Código: sin `--standby` y sin `WRITER_LEASE=1`, `live.py` se comporta exactamente como antes (`GATE` es `None`).

**Testigo remoto (opcional, apagado; no usar en la final).** Con `WRITER_LEASE=1` un writer escribe una fila `{"kind": "writer_lease", "token": <ms del reloj del servidor>, "holder": ...}` en `team_26.scratch`, relee el máximo cada 3 s y deja de escribir si hay un token mayor; si lleva más de 20 s sin confirmarlo (`WRITER_LEASE_MAX_STALE`, reloj de pared: cubre el reposo del portátil) lo relee antes de volver a escribir. Solo excluye si TODOS los writers lo llevan activado, y hace depender la escritura de que `scratch` responda. Está probado con tests y una fila de prueba (E-631), no con dos writers reales.
