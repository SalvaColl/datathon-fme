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
- **`EVENTS_SINCE`:** el writer aplica `shop.events` desde `2026-11-14 07:00:00`. **Para la final NO se cambia** (corregido por T-031, D-310): arrancar el domingo con `EVENTS_SINCE='2026-11-15 ...'` borraría las 98.005 compras orgánicas del sábado de las exclusiones (el 59% de los usuarios que nos pidieron carrusel compró algo el sábado), sus carritos y sus vistas. La carga va por ventanas de una hora, así que el rango largo no agota la consulta. Si algún día hiciera falta separar el sábado del domingo, se hace con `state_window` en `policy.json` (ver abajo), nunca recortando los eventos.
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

## Ventanas de estado de lfm en el paso de práctica a final — T-031 (2026-11-14)

Definiciones en D-310. **Por defecto no hay ventana de día y no hay que hacer nada el domingo**: ni reiniciar, ni tocar `EVENTS_SINCE`, ni `policy.json`.

- Writer que sigue encendido toda la noche: conserva el estado del sábado. Correcto.
- Writer reiniciado el domingo: con `EVENTS_SINCE` por defecto recarga el sábado por ventanas de una hora y la primera lectura de feedback trae todas las compras del carrusel. Llega al mismo estado (test `test_a_restart_on_sunday_rebuilds_the_same_state`).
- Interruptor opcional, sin reinicio una vez cargado el código de T-031: `"state_window": {"day_start": "2026-11-15 00:00:00", "carts": "persistent"}` en `data/policy.json`. Con él, solo las compras desde `day_start` alimentan las features de "comprado hoy"; las compras siguen excluidas siempre. `"carts": "day"` además pasa los carritos anteriores a carritos de histórico (no los borra). **No recomendado sin lectura del leaderboard**: en datos reales cambia el 42% de los slates (48% con `carts: day`) y no hay evidencia de que ayude (E-310).
- Vuelta atrás: quitar `state_window` de `policy.json` (el writer lo aplica en el siguiente ciclo y lo escribe en el log como `{"event": "policy", "state_window": null}`).

