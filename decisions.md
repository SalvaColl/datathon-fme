# Shared technical decisions (status matters)

Record consequences affecting other agents, especially interfaces, data assumptions, production deployment and promotion. **Status `RECOMMENDED` does not mean the team has agreed or implemented it.** No team decisions beyond user-provided planning have been confirmed.

| ID | Status | Decision / correction | Rationale / evidence | Revisit when |
|---|---|---|---|---|
| D-001 | RECOMMENDED | Maintain `AGENTS.md`, `CLAUDE.md`, `challenge.md`, `strategy.md`, `insights.md`, `experiments.md`, `decisions.md`, `tasks.md`, `runbook.md` | Shared knowledge and clear agent coordination | After first integration |
| D-002 | RECOMMENDED | Keep official starter's proven pull/predict/batch-push path running as baseline; implement challengers behind a compatible interface | Reliability and official 3-sec deadline | Integration and benchmark evidence |
| D-003 | RECOMMENDED | One live writer/champion; isolated challengers; versioned experiment logs and rollback | Duplicate submissions invalid for A/B comparisons and difficult to diagnose | Integration / deploy |
| D-004 | **RESOLVED RULE** | Optimize **expected conversion**, not revenue as primary; cold start and reliability are separate scoring components; revenue tie-breaker | Official site/README, 50+10+10 automated +30 jury | If organizers amend rules |
| D-005 | RECOMMENDED | Start with personalized heuristics + history-trained ranker and online trends; only then consider bandits | ~2M impressions +12M organic events support supervised offline testing | E-002/E-003/E-004 results |
| D-006 | RECOMMENDED | Defer PPO until faithful simulator and proof of advantage | Hidden simulator, scarce time, final domain shift | New evidence |
| D-007 | **RESOLVED RULE** | Handle **~3 requests/s**, one valid slate of ten unique active IDs in RawTree within **3 s from request timestamp** | Official README and starter | If organizers amend rules |
| D-008 | RECOMMENDED | Use `starter/offline_eval.ipynb` first, carefully inspect IPS estimator and historical selection bias | Already provided by organizer | Data/model comparison evidence |
| D-009 | PENDING TEAM DECISION | Choose hosting/uptime/backup owner; keep laptop awake or move to stable host | Unattended final + overnight stream | Before final phase |
| D-010 | PENDING TEAM DECISION | Agree model promotion threshold and allowable exploration live | Need reliable evidence / guardrails | First practice results |

### D-090 — Variante `aff` (afinidad de frases) y tabla de productos nuevos en el writer
- **Date / owner / status:** 2026-11-14 / agente de Javi (T-009, rama `javi/cold-items`) / **PROPOSED** (código en el PR #2, sin fusionar ni desplegar; `fe.py` no se ha tocado)
- **Question and alternatives:** v1 ignora las frases de la descripción (I-090, I-092). Alternativas: (a) multiplicador de afinidad sobre el score actual + candidatos por afinidad; (b) reentrenar el GBM con esas features (peor offline: hit@1 0,495 frente a 0,519, y obliga a cambiar `fe.py`); (c) nada.
- **Decision (propuesta):** (a), como variantes del writer endurecido (rama `javi/qrank-serving`, PR #1). Es un multiplicador, así que se compone con v1 y con `qrank` (D-081). El cambio de `live.py` (63 líneas añadidas, 18 sustituidas) está aplicado en la rama `javi/aff-serving` (PR #2) con el visto bueno de Javi del 14 nov 13:22 UTC; no está fusionado ni corriendo en el writer. Variantes nuevas en `data/policy.json` (o flags `--aff`, `--qrank-aff`, `--ab-aff`, `--ab-qrank-aff`):
  - `aff`: GBM v1 + candidatos por afinidad + multiplicador, en todas las páginas (`model_version = v1-aff-r1`).
  - `qrank_aff`: `qrank` × afinidad en product/category (`v2-qrank-aff-r1`, misma categoría y sin lo ya comprado, como `qrank`) y GBM × afinidad en home.
  - `ab_aff`: 50/50 por hash de usuario, v1 frente a `aff`. `ab_qrank_aff`: 50/50, `qrank` frente a `qrank_aff`. El brazo es el mismo hash que `ab_qrank`, así que `compare_versions.py` compara por `model_version`.
  - La tabla de productos nuevos (parte A, `cold_items`) solo entra en `aff` y `qrank_aff`, no en las variantes A/B, para que el control quede limpio.
  - Todo lo nuevo vive en `recsys/aff_policy.py`. Si `aff_policy` no carga o falla en una petición, esa petición sigue por el camino v1/qrank de siempre; `qrank_slates()` mantiene su contrato y los tests existentes pasan sin cambios.
  - El filtro de productos muertos de D-130 sigue siendo independiente y conviene aplicarlo antes.
- **Why, evidence/experiment:** I-092, E-092, E-093, E-094. Offline hit@1 0,472 → 0,519; en vivo los productos con afinidad <0,15 (85% de lo que mostramos a usuarios conocidos) casi no se compran. Estimación con tasas del feedback: de ~0,9% a ~2,4% por petición; es una extrapolación, no una medida del modelo oculto.
- **Affected modules/interfaces/owners:** `recsys/live.py` (dueño del writer; cambio en el PR #2). Nuevos: `recsys/aff_policy.py`, `recsys/cold_items.py`, `recsys/attr_affinity.py`, `recsys/cold_prior.json` (270 KB, se regenera con `python cold_items.py fit`), `tests/test_aff_policy.py`. Sin dependencias nuevas en el camino de servicio (numpy/pandas).
- **Rollout / rollback:** `python live.py --dry-run --qrank-aff` (E-095, copia parcheada: 448 peticiones, 100% slates válidos, +5 ms por lote); después un bloque de 10 min alineado con `updated_at` del leaderboard, comparar contra `baseline` y contra el bloque anterior de v1. Rollback = volver a `qrank` o `v1` en `policy.json` (se relee cada ciclo). `AttrAffinity(beta=...)` regula la agresividad (40 por defecto; 20 es la opción prudente).
- **Revisit condition:** si el bloque en vivo no mejora frente a v1, bajar β a 20 o limitar a la categoría de la sesión antes de descartar.

## Corrected previous assumptions

- OLD: 1 request every 3 seconds -> **3/sec**.
- OLD: leaderboard hourly -> **refresh 10min, reports last hour during practice**.
- OLD: exact objective unconfirmed -> **conversion expected probability; revenue tie-breaker**.
- OLD: no historical data assumed -> **historical propensities, sessions, organic events available**.
- OLD: need server endpoint -> **continuous RawTree polling and insert loop, no recommendation webserver required**.

### D-080 — Variante `trend` en el writer: candidatos y boost de subcategorías calientes
- **Date / owner / status:** 2026-11-14 / Javi (agente, T-008) / **PROPOSED** (no aplicada; `live.py` es del dueño del writer)
- **Question and alternatives:** ¿usar `recsys/trends.py` en `live.py`? Alternativas: (a) nada; (b) solo candidatos; (c) candidatos + multiplicador.
- **Decision (propuesta):** (c), detrás de una variante `trend` en `policy.json`, apagada por defecto. Cambio de ~6 líneas en `live.py`:
  1. `import trends` y, en `refresher()`, tras `refresh_events()`: `snap = trends.snapshot(query, cat["sub"].to_dict())` y guardarlo en `state["trend"]` (1,7 s en el hilo de refresco; si falla devuelve un snapshot neutro).
  2. En `candidates()`: si `snap.hot`, añadir `snap.hot_items(pools["sub"], 10)` cuando no hay `recent_views` (home) o cuando la categoría de la última vista coincide con la de la subcategoría caliente.
  3. En `predict()`: `X["s"] *= snap.multiplier(X.i.values)` (√lift con tope 3; vale exactamente 1,0 fuera de subcategorías calientes, así que sin ráfaga la variante es idéntica a v1).
  - Mantener el filtro de "ya comprado por este usuario" también para estos candidatos (los ya comprados casi no se revenden en el carrusel, hallazgo del hilo de home).
- **Why, evidence/experiment:** I-080, I-081, E-080.
- **Affected modules/interfaces/owners:** `recsys/live.py` (dueño del writer). `fe.py` no cambia; el modelo no se reentrena.
- **Rollout / rollback:** bloque de 10 min alineado con `updated_at` **mientras `python trends.py` muestre una subcategoría caliente**; comparar el bloque contra `baseline` y contra el bloque v1 anterior. Rollback = quitar `trend` de `policy.json`.
- **Revisit condition:** resultado del bloque en vivo, o si las ráfagas de la tarde no son de subcategoría.
### D-081 — Variante `qrank` en el writer para páginas product/category
- **Date / owner / status:** 2026-11-14 / Javi (agente, T-015) / **IMPLEMENTED en rama de integración, sin desplegar** (el despliegue lo decide el dueño del writer)
- **Question and alternatives:** v1 pierde slots en otra categoría y en productos ya comprados (I-082). Alternativas: (a) reglas sobre v1 (quitar comprados y otra categoría); (b) sustituir el ranking de product/category por `qrank`; (c) nada.
- **Decision (propuesta):** (b) detrás de una variante `qrank` en `policy.json`; home sigue con la lógica actual (o la de T-013). Cambio en `live.py`, ~8 líneas:
  1. Arriba: `import qrank; QR = qrank.Ranker.load()` y `BOUGHT = collections.defaultdict(set)`.
  2. En `refresh_events()`: dentro del bucle de eventos, `if r["p"]: BOUGHT[r["u"]].add(r["i"])`; y lo mismo donde se añaden las compras de `feedback`.
  3. En `refresher()`, tras `fe.set_catalog(cat)`: `QR.set_catalog(cat, unavail)`.
  4. En `predict()`, antes del bucle final: `qr = QR.slates([{"rv": r["rv"], "page": r["page"], "bought": BOUGHT.get(r["user_id"], ())} for r in reqs]) if variante == "qrank" else [None] * len(reqs)`, y en el bucle `items = qr[k] or top.get(k, [])[:10]` con `model_version = "v2-qrank"` cuando `qr[k]` no es None. El relleno y las guardas existentes no cambian.
  - `qrank.slates` devuelve `None` en home, sin vistas o si el último visto no está en el catálogo: en esos casos sigue v1.
  - El artefacto `data/qrank.joblib` (145 KB) está en el repo; se regenera con `python qrank_build.py --pull` (necesita scikit-learn 1.9.1, la versión fijada).
- **Why, evidence/experiment:** I-082, I-083, E-081: de 1,34% a ~2,1% estimado en product/category (prudente), ~+0,6 pp global.
- **Affected modules/interfaces/owners:** `recsys/live.py` (dueño del writer). `fe.py` y `model_buy.joblib` no cambian.
- **Rollout / rollback:** primero `python live.py --dry-run` con la variante para ver latencia; después un bloque de 10 min alineado con `updated_at`, o mejor `--ab` 50/50 por hash de usuario durante 30 min, y comparar el bloque contra `baseline` y contra v1. Rollback = quitar `qrank` de `policy.json`.
- **Estado 14:35 CET — implementado sobre el writer de Salva** (rama `javi/qrank-serving`, PR contra `salva/serving-reliability`): `live.py` carga `data/qrank.joblib` en `initialize()`, mantiene `BOUGHT` y enruta por variante. `v1` es el valor por defecto (comportamiento idéntico al de Salva). Se cambia en caliente con `recsys/data/policy.json` = `{"variant": "qrank"}` o `{"variant": "ab_qrank"}` (se relee cada ~20 s), o al arrancar con `--qrank` / `--ab-qrank`. `ab_qrank` reparte 50/50 por hash de usuario entre `v1-gbm-cand-r1` y `v2-qrank-r1`. Si qrank falla o no aplica, la petición sigue por el GBM; las guardas de plazo, stock y at-most-once de Salva se aplican igual a los slates de qrank. Dry-run (sin escribir) 90 s con `--ab-qrank`: 132 peticiones, 44 por qrank, 0 slates inválidos, `predict` p50 49 ms / p95 86 ms. 30 tests pasan (21 de Salva + 9 nuevos).
- **Convivencia con D-130 (hilo de home, `home_cands.py`):** `qrank` solo responde peticiones CON `recent_views`; la variante `home` de D-130 solo las que NO tienen. Tráfico disjunto, se pueden activar a la vez. En cambio `drop_dead()` (D-130 b) filtra los candidatos de v1 en product/category, el mismo tráfico que `qrank` sustituye: **no medir los dos en el mismo bloque**. Con `qrank` activo, `drop_dead` deja de tener efecto en product/category (qrank no usa `candidates()`); si se quiere su lista de "muertos", se pasa como `bought` a `QR.slates` (`BOUGHT[u] | dead`), sin más cambios. Orden propuesto de bloques de 10 min: (1) v1 (control, ya corriendo) → (2) `v1_nodead` de D-130 → (3) `qrank` → (4) `qrank` + `home`. Cada bloque se compara con `baseline` de su misma ventana y con el bloque anterior.
- **Revisit condition:** resultado del bloque; recalibrar `viewed_factor` (ahora 0,45) con el feedback de la propia variante.

### D-160 — Laboratorio nocturno: rotar variantes del writer con `night_lab.py` (propuesta)
- **Status / date / owner:** PROPOSED — 2026-11-14 — Javi (agente, T-016). Decide y arranca el dueño del writer.
- **Qué:** la noche del 14 al 15 lanzar `recsys/night_lab.py run --arms v1,qrank,qrank+home,qrank_aff+home --until 08:30` junto al writer (pasos en `runbook.md`). Dos réplicas de cuatro brazos en bloques de 65 min, cada uno comparado con `baseline` y `reference` de su misma ventana.
- **Cambios en código compartido:** ninguno. No toca `live.py`, `fe.py` ni RawTree; solo escribe `data/policy.json` y `data/d130.json`, que el writer ya relee en caliente. Requiere que el writer en marcha incluya las variantes del plan (PR #1, `aff_live.patch` del PR #2, hook del PR #3); `night_lab.py check` lo valida contra el `live.py` en disco.
- **Riesgo y vuelta atrás:** un brazo malo corre como mucho ~13 min antes de que la guardia vuelva al mejor medido. Ctrl-C restaura los JSON originales. Se detiene solo 60 min antes de la final. Por defecto no deja promocionada ninguna variante.
- **Evidencia:** E-160, I-160.

### D-170 — Variantes `attr` / `attr_aff` en el writer: ranker por atributos para páginas con vistas (propuesta)
- **Date / owner / status:** 2026-11-14 / agente de Javi (T-017) / **PROPOSED; implementado en la rama `javi/attr-model`, apagado por defecto, sin desplegar**
- **Question and alternatives:** la final trae compradores, productos y tendencias nuevos. qrank ordena por un número aprendido del historial de cada producto y no sabe qué hacer con uno recién lanzado (hit@1 0,002 en la simulación, E-171). Alternativas: (a) seguir con qrank / qrank_aff; (b) sustituir el ranker de páginas con vistas por `attr_model`; (c) usar `attr_model` solo para productos nuevos.
- **Decision (propuesta):** (b) detrás de variantes nuevas en `data/policy.json`, a validar con un bloque antes de decidir. No cambia nada si no se activa.
  - `attr`: `attr_model` en peticiones con `recent_views` (`model_version = v3-attr-r1`); home sigue por el GBM. Solo usa la petición y el catálogo.
  - `attr_aff`: lo mismo más el gusto guardado del comprador (historial + vistas en vivo, sin `recent_views`, β=20; `v3-attr-aff-r1`); home y productos nuevos del GBM como en `qrank_aff`.
  - `ab_attr`: 50/50 por hash de usuario, v1 frente a `attr`. `ab_attr_aff`: 50/50, `qrank_aff` frente a `attr_aff` (solo cambia el ranker de páginas con vistas).
  - Candidatos: todos los productos activos de la categoría de la última vista (~500) más los vistos; fuera lo ya comprado y lo agotado. La calidad se recalcula en cada refresco (20 s) con los conteos en vivo, así que un producto nuevo arranca en su prior de atributos y se corrige con el stream.
  - Si `attr_policy` no carga o falla en una petición, esa petición sigue por qrank/GBM como hasta ahora. Compatible con D-130 (home) y con `night_lab.py` (lee `VARIANTS` de `live.py`).
- **Why, evidence/experiment:** I-170, I-171; E-170…E-173. Empata con qrank en productos conocidos y es el único que coloca productos nuevos. No hay medida del leaderboard.
- **Affected modules/interfaces/owners:** `recsys/live.py` (dueño del writer): +42 líneas, 7 sustituidas (import, variantes, `use_attr`, carga en `initialize()`, refresco, `attr_slates()`). `tests/test_aff_policy.py`: la tabla de variantes esperadas incluye las 4 nuevas. Nuevos: `recsys/attr_model.py`, `attr_policy.py`, `attr_model_build.py`, `attr_model_eval.py`, `recsys/data/attr_model.joblib` (298 KB), `tests/test_attr_model.py`. Sin dependencias nuevas.
- **Rollout / rollback:** `python recsys/live.py --dry-run --ab-attr-aff` en el Mac para ver latencia; después `{"variant": "ab_attr_aff"}` o un bloque completo `attr_aff` medido contra `baseline` del leaderboard. Rollback = volver a la variante anterior en `policy.json` (se relee cada ~20 s). Regenerar el artefacto: `python qrank_build.py --pull` (una vez) y `python attr_model_build.py`.
- **Revisit condition:** si el bloque no iguala a `qrank_aff`, dejar `attr_model` solo como fuente de calidad para productos nuevos (encaja en `LiveQuality(prior=...)` de T-018).
### D-180 — Variante `lfm` del writer: slate ajustado con el feedback de hoy (afinidad + carrito, por tipo de usuario)
- **Date / owner / status:** 2026-11-14 / Javi (agente, T-018) / PROPOSED. Implementada y apagada por defecto; la activa el dueño del writer.
- **Qué:** `policy.json` acepta `{"variant": "lfm"}` (todas las peticiones) y `{"variant": "ab_lfm"}` (50/50 por hash de usuario: control = qrank, tratado = lfm). lfm puntúa todos los productos activos con el modelo de E-180 y sirve los 10 mejores; quita lo ya comprado y lo visto en el histórico sin carrito.
- **Por qué:** I-180, I-181, E-180. Es la pieza más grande sin cubrir: usuarios que vuelven (56% del tráfico a 0,72%).
- **Cambios en código compartido:** `live.py` gana 2 variantes, `lfm_slates()` y tres ganchos de una línea (carga, eventos en vivo, refresco de catálogo). Con cualquier otra variante el comportamiento es idéntico. Si lfm falla en una petición, esa petición sigue por qrank/GBM. Necesita reiniciar el writer una vez para cargar el código (~1 min de fallback).
- **Cómo medir:** `ab_lfm` durante 20 min y leer `api/state?by=model`: `v3-lfm-r1-k`/`-n`/`-kh`/`-nh` frente a `v2-qrank-r1` y `v1-gbm-cand-r1` (este último es el home del control).
- **Rollout / rollback:** `{"variant": "qrank"}` en `policy.json`, sin reiniciar.
- **Riesgo para la final:** los pesos salen del feedback de hoy; si mañana los compradores son todos nuevos solo aplica la mitad "nuevo" (carrito de hoy + afinidad de sesión). Reajustar con `python lfm_build.py --pull` antes de las 10:00 con todo el feedback de la noche.
- **Revisit condition:** si `-k` no supera a qrank en usuarios que vuelven en el leaderboard, dejar lfm solo para usuarios nuevos o descartarlo.

### D-210 — Brazos de pesos de lfm en caliente, medidos por el leaderboard (T-021)
- **Date / owner / status:** 2026-11-14 / Javi (agente, T-021) / PROPOSED. Sin brazos el comportamiento es idéntico al actual.
- **Qué:** `policy.json` admite `"lfm_arms"`: de 2 a 4 brazos, cada uno con `tag`, opcionalmente `file` (otro `lfm_coef*.json` del repo) y `w` (pesos sueltos que sustituyen a los del brazo, por segmento `known` / `new`). Un brazo con solo `tag` son los pesos publicados (control). Los usuarios se reparten a partes iguales por hash y cada brazo escribe `v3-lfm-<tag>-k|-n|-kh|-nh`. Se relee cada ~20 s, sin reiniciar.
- **Por qué:** I-211, E-210. Las compras ya no distinguen variantes; el leaderboard sí, en una hora.
- **Primer experimento propuesto:** `{"variant": "lfm", "lfm_arms": [{"tag": "r1"}, {"tag": "r2", "file": "lfm_coef_r2.json"}, {"tag": "t1", "w": {"known": {"hcart": 1.5, "islast": 3.0}, "new": {"nbp": 0.6, "bsub": 0.6}}}]}`. r2 = todo reajustado; t1 = pesos publicados más solo las tres ideas del tablero (I-201, I-202, I-209). Leer a los 60 min; dejar el mejor brazo por segmento.
- **Cambios en código compartido:** `live.py` pide también `context.device` y `context.region` en la consulta de peticiones; `lfm.py` gana 6 features (peso 0 con el fichero publicado) y `set_arms`. Hace falta reiniciar el writer una vez para cargar el código.
- **Rollout / rollback:** quitar `lfm_arms` de `policy.json`. Un brazo mal escrito se ignora entero y se sirve lfm normal; si un brazo falla en una petición, esa petición usa los pesos publicados.
- **Revisit condition:** si ningún brazo supera a r1 en dos lecturas de una hora, congelar r1 para la final.

## Decision template

```markdown
### D-XXX — title
- **Date / owner / status:** PROPOSED | RECOMMENDED | ACCEPTED | REVERSED | SUPERSEDED | RESOLVED RULE
- **Question and alternatives:**
- **Decision:**
- **Why, evidence/experiment:**
- **Affected modules/interfaces/owners:**
- **Rollout / rollback:**
- **Revisit condition:**
```

Official sources: https://datathon.rawtree.dev/ ; https://github.com/rawtreedb/datathon-fme-2026

### D-011 — Offline league policy interface (implemented for T-013)
- **Date / owner:** 2026-11-14 / Codex.
- **Interface:** register a zero-argument factory in `tools.league_policies`; returned object implements `fit(training_snapshot)` and `recommend(request, features, catalog) -> list[str]`. Catalog is read-only and eligible as of request time; features currently empty; rewards/logged actions withheld from recommend. No serving interface/dependency change.
- **Discipline:** independent chronological caches; train-only fitting, validation tuning, frozen policy/source selection and one-time final-test scoring. Previously evaluated legacy request IDs excluded. Plugins may not read outside the provided training data; trusted modules and external/transitive dependencies require review. See `tools/LEAGUE.md`.
- **Rollback:** offline-only change; retain live champion and do not restart it. No promotion from these proxies alone.

### D-REL-001 — Serving reliability patch prepared; deployment remains with Javi
- **Implemented code:** `7176c03` adds deadline-first batching, fresh-cache validity checks, per-thread transport and durable at-most-once claims. Request/model schema unchanged; catalogue argument to `featurize` is optional and backward compatible. Existing model artifact retained, served as v1-gbm-cand-r1 for attribution. No dependency installation.
- **Tradeoff:** without documented server idempotency, ambiguous POST failures are not blindly retried. Journal crash window can lose an answer; duplicates cannot safely be used as an update mechanism. Local process lock plus team-designated host; no claim of cross-host enforcement.
- **Deployment:** Javi owns the active laptop. Patch is tested locally and available for cherry-pick; no writer launched/stopped here. Retain old model/checkout and journal; monitor five-minute accepted/missing/invalid counts and stage timing after an owner-controlled handoff. Source evidence and limits: E-REL-001; detailed operations: recsys/README.md.

### D-180 — `live_quality`: calidad en vivo para qrank, apagada por defecto (T-018) — PROPOSED, pendiente de A/B por el dueño del writer
- **Qué cambia en `recsys/live.py`:** 3 líneas (import + `live_quality.install(globals())` dentro de `initialize()`, con try/except como D-130). Sin `recsys/data/lq.json` el writer sirve exactamente igual y el módulo no hace ninguna consulta de más salvo una copia inicial. Hace falta reiniciar el writer una vez para cargar el hook; después se enciende y apaga en caliente.
- **Interruptor:** `recsys/data/lq.json` = `{"mode": "off" | "on" | "ab"}`. `ab` reparte 50/50 por hash de usuario (sal distinta a la de `policy.json`, así que se cruza limpio con `ab_qrank`). Las respuestas tocadas llevan `model_version` `v2-qrank-r1+lq`, comparables con `compare_versions.py`.
- **Qué hace encendido:** solo toca los slates de qrank puro (peticiones con vistas que la variante activa manda a qrank y que no pasan por afinidad). Mantiene una segunda copia del ranker con q corregida cada 30 s: productos nuevos con q = exp(a_sub + 2·log tasa orgánica) en vez de la mediana de su subcategoría (I-183) y subcategorías calientes con q × multiplicador (I-181, tope ×4). Los productos antiguos en calma no cambian.
- **Seguridad:** cualquier excepción, slate que no tenga 10 ids distintos, o datos en vivo con más de 5 min de antigüedad devuelven el slate de qrank original. Stock y productos ya comprados se filtran igual que en qrank. Coste medido: reconstruir la copia 0,13 s en hilo aparte; por petición 0,43 ms frente a 0,46 ms (E-182). 9 tests en `tests/test_live_quality.py`; la suite completa pasa (73).
- **Prior de atributos:** usa `cold_prior.json` (T-009). Cuando el modelo de T-017 esté en main basta pasar su predictor a `LiveQuality(prior=...)`; no se duplica nada.
- **Cómo medirlo:** modo `ab` durante ≥ 60 min con `ab_qrank` o `qrank` activos y comparar `v2-qrank-r1+lq` frente a `v2-qrank-r1`; o un bloque de 65 min en modo `on` leído en el leaderboard (el laboratorio nocturno todavía no rota `lq.json`: habría que añadirlo a sus brazos). Mirar también la fila de cold start.
- **Rollback:** borrar `lq.json` o poner `{"mode": "off"}`; efecto en ≤ 1 s, sin reinicio.
- **Riesgo principal:** que el modelo oculto no premie a los productos nuevos como predice la relación entre productos antiguos (HYPOTHESIS). Con `on`, el 31,6% de los slates cambia y las impresiones a productos nuevos pasan del 0,03% al 3,1%; el slot 1 solo cambia en el 4,7%.
### D-130 — Filtrar productos "muertos" en todas las páginas y variante `home` con `recsys/home_cands.py`
- **Date / owner / status:** 2026-11-14 · agente de Javi (T-013) · **PROPOSED** (requiere tocar `recsys/live.py`, que no es mío; decide el dueño del writer)
- **Question and alternatives:** (a) seguir con v1 tal cual; (b) solo filtrar de los candidatos lo ya comprado y lo visto-sin-carrito del histórico; (c) además responder las peticiones sin `recent_views` con `HomeCands.slate()` en vez del GBM.
- **Decision proposed:** (b) primero, en un bloque de 10 min alineado con `updated_at`; si el bloque mejora frente al baseline, añadir (c).
- **Why, evidence:** I-130 / E-131 (28% de nuestras impresiones son de productos que en vivo dan 1 compra en 30.847), I-131 / E-130, E-132.
- **Cambio mínimo en `live.py` (4 puntos, todo en memoria, sin consultas nuevas):**
  ```python
  import home_cands                                                   # arriba
  HC = home_cands.HomeCands(pd.read_parquet("data/user_item_all.parquet"), fe.C)   # junto a BASE (7,7 s al arrancar)
  # refresh_events(): al lado de LIVE.add(...)  ->  HC.add(r["u"], r["i"], r["v"], r["a"], r["p"])   (y HC.add(u, i, 0, 0, 1) con el feedback)
  # refresher(): tras make_pools(...)           ->  HC.refresh(cat, unavail)
  # candidates(): antes del return              ->  out = HC.drop_dead(req["user_id"], out)             # (b)
  # predict(): si not r["rv"] y policy == "home" ->  items = HC.slate(r["user_id"])                      # (c), sin pasar por el GBM
  ```
- **Affected modules/owners:** `recsys/live.py` (Javi). `fe.py` no cambia. El fallback `best` de `predict` sigue rellenando si faltan candidatos.
- **Rollout / rollback:** nueva variante en `policy.json` (p. ej. `v1_nodead`, `home`); volver a `v1` en caliente. Comprobar antes con `live.py --dry-run`.
- **Revisit condition:** si el bloque de leaderboard no mejora, o si en la final (compradores nuevos) el histórico deja de aplicar: entonces solo queda la parte de usuario desconocido y el carrito del propio stream.
- **Actualización 2026-11-14 13:15 UTC (aprobada la prueba por Javi):** el cambio queda en UNA línea de `live.py`, sin tocar sus funciones: `import d130; d130.install(globals())` justo encima de `if __name__ == "__main__":`. `recsys/d130.py` envuelve `LIVE.add`, `make_pools`, `candidates` y `predict`, así que es independiente de las variantes de `policy.json` (y de `qrank.py`). Se conmuta en caliente con `recsys/data/d130.json`: `{"mode": "off" | "nodead" | "home"}`; sin fichero = `off` = comportamiento anterior. Las respuestas tocadas llevan `model_version` con sufijo `+nd` o `+home`. Probado con `live.py --dry-run` en los tres modos: 0 errores, 17–26% de candidatos eliminados, edad p95 0,95 s (igual que sin el hook). Medición: `python d130_measure.py lb|fb`.
- **Actualización 2026-11-14 13:30 UTC (compatibilidad con el writer endurecido):** `d130.py` probado también sobre `recsys/live.py` de `javi/qrank-serving` (8d4b6f3, serving de Salva + qrank) con `--dry-run`, `policy.json` en `ab_qrank` y modos `home` y `nodead`: 0 errores, 15–18% de candidatos eliminados, `loop_ms` p50 164 / p95 215 (sin hook 159 / 227). Rutas relativas a `recsys/data/` y stock (`stock_out`) incluidos. Las slates de qrank no se tocan ni se etiquetan; `home` solo cambia peticiones sin vistas, que qrank no sirve, así que los bloques se pueden correr en secuencia sin confundirse. `d130.HC.is_dead(user, item)` queda disponible para qrank si quiere filtrar también lo comprado/visto en el histórico.

### D-230 — Afinar los pesos de lfm por rondas contra el leaderboard (`lfm_tuner.py`) — PROPUESTA (T-023, 2026-11-14)
- **Date / owner / status:** 2026-11-14 16:00 UTC / Javi (agente, T-023) / PROPOSED. Sin arrancar el script nada cambia.
- **Qué:** `recsys/lfm_tuner.py` corre al lado del writer. Cada ronda de 30 min pone 3 brazos en `lfm_arms` (control = mejores pesos hasta ahora; el mismo juego con un peso +paso; con ese peso -paso), uno por segmento a la vez (usuarios que vuelven y nuevos se buscan en paralelo porque el leaderboard los da por separado). Al cerrar la ronda lee `api/state?by=model&from=<inicio>` y, por segmento, se queda con el brazo que gane al control por más que el ruido. Rota la posición de los brazos para que el control no sea siempre el mismo tercio de usuarios. Al parar deja un solo brazo `best` con los pesos ganadores.
- **Por qué:** I-211: las compras reales ya no distinguen variantes de lfm; el leaderboard sí. Lectura 15:10-15:40 UTC: equipo 1.82%, team_06 2.08%. Los pesos de lfm salen de clics, no del modelo oculto, y el modelo sobreestima sus propios slates, así que hay margen que solo el leaderboard puede enseñar.
- **Qué distingue y qué no (medido, no supuesto):** la conversión esperada por petición varía ~3.5 puntos (usuarios que vuelven) y ~5-6.5 (nuevos) entre ventanas de 5-10 min del propio leaderboard. Con ~1.100 y ~470 peticiones por brazo en 30 min, una ronda ve diferencias de ~0.25 puntos en los que vuelven y ~0.6 en los nuevos. Cambios más pequeños no se aceptan. No hay todavía ningún resultado en vivo del afinador.
- **Cambio en código compartido:** `live.clean_lfm_arms` admite 1 brazo (antes 2-4) y rechaza la lista entera si algún brazo es inválido (antes descartaba solo el malo). El writer necesita este commit para que el brazo `best` final funcione; con el código de main actual las rondas de 3 brazos ya funcionan y al terminar hay que usar `--finish off`.
- **Riesgo:** durante las rondas 2/3 de los usuarios llevan un peso movido; un paso malo cuesta como mucho una ronda en un tercio del tráfico de un segmento. Se para solo fuera de práctica o a menos de 1 h + una ronda de la final.
- **Rollback:** Ctrl-C (deja `best`) o borrar `lfm_arms` de `policy.json`.

### D-240 — lfm r3 (reparto de categorías del usuario) como brazo — PROPUESTA (T-024, 2026-11-14)
- **Date / owner / status:** 2026-11-14 16:50 UTC / Javi (agente, T-024) / PROPOSED. Sin el brazo en `policy.json` el writer sirve exactamente lo mismo que hoy (los pesos publicados no tienen `ucat` / `usub`).
- **Qué:** `lfm.py` calcula para cada usuario cuántas vistas tiene en cada categoría y subcategoría (historial de 60 días + vistas de hoy) y dos features nuevas por producto: la parte de las vistas del usuario en la categoría (`ucat`) y en la subcategoría (`usub`) del producto. `lfm_coef_r3.json` son los pesos reajustados con ellas.
- **Por qué:** I-240, E-240. Es la primera variante de lfm que mejora en datos apartados de forma consistente.
- **Experimento propuesto tras reiniciar el writer con este código:** `{"variant": "lfm", "lfm_arms": [{"tag": "r1"}, {"tag": "r3", "file": "lfm_coef_r3.json"}]}`, leer a los 30 min por segmento. Si se está corriendo `lfm_tuner.py`, pararlo antes (los dos escriben `lfm_arms`).
- **Cambios en código compartido:** `LiveFit.user_state` devuelve un quinto elemento (el reparto); `LiveFit.add` cuenta las vistas de hoy; la primera `set_catalog` construye dos matrices usuario x categoría desde el historial (hilo de refresco, no el de servir). Si esa construcción falla, las dos features valen 0 y lfm sigue igual.
- **Riesgo:** un usuario con pocas vistas no tiene preferencia fiable; por eso el reparto se encoge hacia "sin preferencia" con 5 vistas ficticias.
- **Rollback:** quitar el brazo de `policy.json`.

### D-241 — Tras un reinicio, recuperar todas las compras hechas por nuestro carrusel (T-024, 2026-11-14)
- **Date / owner / status:** 2026-11-14 16:35 UTC / Javi (agente) / IMPLEMENTED, activo por defecto al cargar el código.
- **Por qué:** aclaración de la organización (14-nov): quien ya compró un producto, también a través de nuestras recomendaciones, casi no lo vuelve a comprar. Medido: 676 de 695 compras de nuestro carrusel NO aparecen en `shop.events`; el writer solo las leía de `feedback` de los últimos 2 minutos, así que cada reinicio las olvidaba y esos productos (casi siempre de carrito, los que lfm pone arriba) volvían al slate.
- **Qué:** la primera lectura de `feedback` tras arrancar trae todas las compras (0,5 s, 695 filas); las siguientes, los últimos 10 minutos.
- **Comprobado que ya estaba bien:** lfm excluye lo comprado en el historial de 60 días, en `shop.events` de hoy (cada ciclo de refresco) y en `feedback`; ninguna feature premia "comprado antes" (`nbp` y `bsub` valen 0 para el propio producto comprado).

### D-220 — Reinicios del writer con relevo (`--takeover`) — PROPUESTA (T-022, 2026-11-14)
- Arrancar siempre el writer nuevo con `python live.py --takeover` mientras el viejo sigue sirviendo. El nuevo carga, aplica el día, puntúa peticiones reales sin enviar, y solo entonces pide al viejo que pare; empieza a escribir cuando el sistema operativo le entrega `writer.lock`. Nunca hay dos writers: sin el candado no se escribe, y el diario compartido evita responder dos veces.
- Evidencia: E-220. Estado: implementado y ensayado sin escribir; la primera aplicación real la hace el dueño del writer (el proceso actual es anterior y necesita `--replace-pid`).
- Vuelta atrás: el mismo relevo con el commit anterior, o `kill` + arranque normal como hasta ahora.

### D-270 — r5 (r3 + `cv`) se decide solo por el leaderboard
- **Date / owner:** 2026-11-14 · Javi. **Status:** PROPOSED, pendiente del reinicio con relevo.
- **Decisión:** tras cargar el código, `"lfm_arms": [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "r5", "file": "lfm_coef_r5.json"}]` durante 30 minutos; se queda solo el brazo que gane en el leaderboard. No se descarta por validación offline (I-270: el histórico y nuestro feedback no pueden medirla). No más de dos brazos a la vez.
- **Rollback:** quitar r5 de `lfm_arms` (sin reinicio). Sin `lfm_graph_B.json`, o con pesos sin `cv`, lfm se comporta exactamente como antes.

### D-360 — Ventanas de estado de lfm: qué es persistente, qué es del día y qué no se borra nunca (T-036)
- **Date / owner:** 2026-11-14 · Javi (agente). **Status:** PROPOSED (código en PR, apagado por defecto; activar es decisión de Javi).
- **Definiciones (hora del evento, UTC, nunca la hora de llegada):**

| Estado | Dónde vive | Ventana | Motivo |
|---|---|---|---|
| Preferencias históricas (afinidad, reparto de categorías de 60 días, carritos y compras de histórico) | ficheros de histórico, `LiveFit.UC/US/hcart/hbought` | Persistente | Son el perfil del comprador |
| Vistas del evento (reparto de categorías `lmix`, afinidad en vivo) | `LiveFit.lmix`, `AttrAffinity` | Persistente, sin corte de día | Son preferencias; r3 ganó con ellas acumuladas |
| Exclusión de comprados (`BOUGHT`, `lbought`, compras del carrusel) | writer + `LiveFit` | **Permanente. Nunca se borra**, tampoco con `state_window` | Regla del organizador: lo comprado casi no se vuelve a comprar |
| Carritos del evento (`lcart` -> feature `cl`) | `LiveFit.lcart` + hora en `lcart_t` | Persistente por defecto. Opción `carts: day`: los anteriores a `day_start` pasan a carritos de histórico (`chn`), no se borran | Un carrito vale lo mismo con 10 minutos que con más de 4 horas, y lo mismo que uno del histórico (E-360) |
| "Comprado hoy" (features `nbp`, `bsub`) | `LiveFit.lbought` + hora en `lbought_t` | Persistente por defecto. Con `day_start`: solo compras desde esa hora | El efecto sigue visible a más de 2 horas (E-360); de un día para otro no es medible con un solo día de datos |
| Vistas recientes de la petición | petición | De la sesión, las da RawTree | |
| Tendencia de producto (`LIVE`, pools) | writer | Acumulado desde `EVENTS_SINCE`; lfm no lo usa | Solo alimenta variantes que no están en vivo |

- **Decisión propuesta para la final:** sin ventana de día (comportamiento actual, el mismo con el que se ajustaron y ganaron los pesos r3). `EVENTS_SINCE` no se mueve al domingo (runbook corregido). El interruptor queda disponible y probado, pero activarlo cambia el 42% de los slates sin evidencia a favor: solo tras una lectura del leaderboard, y la final no la tiene.
- **Qué no sabemos:** si la final usa los mismos compradores que la práctica. Si son nuevos, el estado del sábado no molesta (nadie lo consulta). Si son los mismos, conservarlo es lo correcto.
- **Rollback:** quitar `state_window` de `policy.json`; sin esa clave el código nuevo devuelve exactamente el estado anterior (test `test_without_a_window_nothing_changes`).

### D-280 — cold_lq se prueba como brazo de lfm, no por bloques de tiempo (T-028)

- **Decisión:** la calidad de productos nuevos de `cold_lq` (T-CS01) se sirve por brazo: `{"tag": "c1", "file": "<pesos del ganador>", "lq": "cold"}` contra el ganador de r3/r5, 30 minutos, lectura por `-k` y `-n` en `api/state?by=model&from=`. `"cold_new"` la aplica solo a usuarios nuevos. Máximo dos brazos a la vez. `data/coldlq.json` no se usa.
- **Coste:** un reinicio con relevo para cargar `lfm.py`, `live.py` y `cold_lq.py`. Sin ningún brazo con `"lq"` no se calcula nada y lfm sirve exactamente igual que antes.
- **Rollback:** quitar el brazo de `lfm_arms` (sin reinicio). Si `cold_lq` falla o no hay productos nuevos, el brazo sirve sus pesos con la calidad de qrank.

> D-280 queda sustituido por D-281.

### D-281 — primera prueba de cold_lq: un brazo acotado, solo páginas con vistas (T-028)

- **Comportamiento:** apagado por defecto. Un brazo con `"lq": "cold"` usa, solo en peticiones de producto/categoría con vistas recientes, la calidad corregida de los productos llegados por `new_product` y sin calidad histórica: prior de atributos + evidencia orgánica (K = 100, tasa al cuadrado, sin tocar), acotada a ±log(20) respecto a la calidad actual. Va por `lq` y por `seglq`. Home, productos establecidos, pesos y el brazo de control no cambian. Sin prior, con metadatos incompletos, números no finitos o cualquier error, se conserva la calidad actual (nunca el fallback por subcategoría de `LiveQuality`, I-CS02). El límite ±log(20) es un tope de riesgo fijado de antemano, no un parámetro ajustado.
- **Configuración exacta** (con el campeón r3; si gana r5, los dos brazos llevan el mismo `file` y `w` del ganador y solo cambia `"lq"`):
  `"lfm_arms": [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "c1", "file": "lfm_coef_r3.json", "lq": "cold"}]`
  Ficheros listos, sin activar: `recsys/policy.cold_lq_r3.json` (campeón r3) y `recsys/policy.cold_lq_f5c05.json` (si `f5c05` gana su ronda: mismo `file`, `w` y `home` en los dos brazos). Con `f5c05` como base no se ha hecho ensayo en seco.
- **Lectura:** ventana fija de 30 minutos que empieza 2 minutos después de activar, `api/state?by=model&from=&to=` con el mismo `from`/`to` para los dos brazos. Se comparan `-k` con `-k` y `-n` con `-n`. Las filas `-kh`/`-nh` son idénticas por construcción y sirven de control de cordura. Coeficientes y home fijos durante la prueba; nada más cambia en `policy.json`.
- **Éxito:** c1 por encima del control en `-k` y en `-n`, y al menos +0,25 pt en el conjunto de las dos (ponderado por peticiones). Entonces se repite un segundo bloque nuevo de 30 minutos; solo se queda si repite el signo.
- **Regresión:** a los 30 minutos, c1 al menos 0,25 pt por debajo en el conjunto, o una única mirada intermedia a los 15 minutos con c1 al menos 0,5 pt por debajo en `-k` con 400 o más peticiones por brazo. Se quita el brazo.
- **Indistinguible** (menos de 0,25 pt en cualquier sentido): se quita el brazo y se queda la política más simple.
- **Parada inmediata:** envíos inválidos o ausentes, peticiones caducadas por encima de lo habitual, o eventos `cold_lq` con `reason` distinto de `null` de forma repetida.
- **Rollback:** quitar el brazo de `lfm_arms` (sin reinicio). **Coste de activar:** un reinicio con relevo para cargar el código. Activa y revierte Javi; para la final solo entra si está confirmado antes de las 08:30 CET del domingo.

### D-340 — la primera prueba de cold_lq es solo para usuarios nuevos (`cold_new`); sustituye el plan de D-281

- **Hipótesis:** el ranker da a los productos lanzados hoy la mediana de su subcategoría; cambiarla por el prior de atributos más la evidencia orgánica anterior puede mejorar las recomendaciones a usuarios nuevos. La evidencia offline es de predicción de calidad; la conversión no está confirmada. Subir la exposición de productos nuevos no es el objetivo.
- **Qué cambia:** solo la calidad (`lq` y `seglq`) de productos lanzados hoy, y solo cuando `is_new_user`, la página es producto o categoría y hay vistas recientes. Mismos coeficientes, overrides, grafo (`cv`) y home en control y retador: la lista se rechaza entera si el brazo `cold_new` no tiene un control con pesos idénticos. Usuarios que vuelven y home del brazo retador se sirven y se etiquetan como el control.
- **Configuración exacta, sin activar:** `recsys/policy.cold_new_r3.json` si el campeón es r3; `recsys/policy.cold_new_f5c05.json` si `f5c05` gana su ronda. Etiquetas internas: control `v3-lfm-<campeón>-n`, retador `v3-lfm-cn1-n`. El control conserva su código público; el retador recibe uno nuevo derivado de la sal de `data/labels.json` (queda en el log como evento `label`).
- **Cuándo:** después de cerrar r3 contra `f5c05`, sin interrumpirla. Un reinicio con relevo para cargar el código; la política se cambia después en caliente. Guardar antes la `policy.json` vigente.
- **Lectura:** una ventana fija de 30 minutos que empieza 2 minutos después de activar, mismo `from`/`to`. Se juzga solo `…-n` del control contra `cn1-n` (usuarios nuevos, producto/categoría). Se anotan peticiones por brazo, `reference` en la misma ventana, envíos válidos y a tiempo y latencia del bucle. Sin miradas intermedias.
- **Potencia:** unas 620–650 peticiones por brazo cada 30 minutos (E-271) y un ruido de 5–6,5 pt por petición dan un error típico de la diferencia de unos 0,35 pt por bloque. Solo cambia 1 de cada 5 slates, así que un bloque solo distingue efectos grandes.
- **Criterios fijados de antemano:** primer bloque de cribado: si `cn1-n` supera al control en +0,5 pt o más, se hace un segundo bloque nuevo; se acepta solo si el segundo repite el signo y la diferencia conjunta de los dos es de +0,5 pt o más. Si en el primer bloque queda 0,5 pt o más por debajo, se quita. Cualquier otra cosa es no concluyente: se quita el brazo y sigue el campeón. Máximo tres bloques en total.
- **Parada inmediata:** envíos inválidos o ausentes, más caducadas de lo habitual, o eventos `cold_lq` con `reason` distinto de `null` repetidos.
- **Rollback:** restaurar la `policy.json` guardada (o quitar el brazo `cn1`), sin reinicio. Para la final solo entra con evidencia confirmada antes de las 08:30 CET del domingo; configuración congelada a las 09:00 CET.
- **Si se confirma (forma de promoción):** una lista en la que todos los brazos llevan `"lq": "cold_new"` es válida sin control; cada brazo conserva su propia etiqueta en todas las cohortes. Fichero listo, sin activar: `recsys/policy.cold_new_promoted_r3.json` (un solo brazo `cn1` con los pesos de r3). Así también valen las rondas del afinador sobre un campeón `cold_new`, que copia `lq` a todos los brazos. Una lista que mezcla brazos con y sin `lq` sigue exigiendo el control idéntico.
- **Riesgo conocido, anterior a este cambio:** `serving.repair` rellena con los más vendidos activos sin mirar lo ya comprado por el usuario. Solo actúa si un producto del slate se queda sin stock entre el ranking y el envío. No se toca aquí (`serving.py` es de T-014); el brazo no añade ningún camino nuevo.

### D-350 — r6 (`mf`) se prueba como retador único contra el campeón del momento (propuesta, T-035)
- **Qué:** tras fusionar `javi/mf-r6` y un reinicio con relevo, una ronda de 30 minutos con `{"tag": "r6", "file": "lfm_coef_r6.json"}` contra el campeón. Si en ese momento el campeón lleva `cv` (brazo `f5c05`), el retador equivalente es `{"tag": "r6c", "file": "lfm_coef_r5.json", "w": {"known": {"cv": 0.5, "mf": 0.0627}, "new": {"cv": 0.5}}, "home": {"file": "lfm_coef_r6.json"}}`.
- **Regla:** gana quien tenga más conversión en las filas de conocidos (producto/categoría y home) de la misma ventana; los nuevos no cambian (peso 0). Si r6 gana, siguiente ronda con el peso al doble (`"w": {"known": {"mf": 0.125}}`), que se cambia sin reiniciar.
- **Vuelta atrás:** quitar el brazo de `policy.json`. Sin `lfm_mf.npz` la feature vale 0 y todo se comporta como antes.

### D-390 — Brazo `np1` (peso para productos lanzados durante el evento, usuarios conocidos en páginas). Lo activa y revierte Javi
- **Fecha / propone:** 2026-11-14 20:30 UTC · Javi (agente, T-039). Evidencia I-390, E-390.
- **Qué:** tras un reinicio con relevo que cargue `lfm.py` y `live.py` de esta rama, política `recsys/policy.newp_r3.json`: `r3` contra `np1` = r3 con `"w": {"known": {"newp": 1.0}}`. Solo cambia usuarios conocidos en producto/categoría con vistas.
- **Lectura:** ventana fija de 30 minutos, fila de conocidos en páginas de cada brazo, mirando `conversion` y también `cold_conversion` con `cold_requests` (es el tramo "conocido con producto nuevo en las vistas"). Confirmar con un segundo bloque antes de promover (E-272). Si gana dos veces, siguiente brazo con 1,9.
- **Se quita si:** 0,25 pt por debajo a los 30 minutos, o envíos inválidos. Rollback sin reinicio: quitar el brazo de `lfm_arms`.
- **No a la vez que** la confirmación de `cold_new` (son cohortes distintas y podrían convivir, pero la regla es un retador cada vez).

### D-420 — Confirmación de `cold_new` y `np1` sobre la base con precios corregidos (T-042). Propuesta: activa y revierte Javi
- **Fecha / propone:** 2026-11-14 23:00 UTC · Javi (agente, T-042). Evidencia I-420, E-420…E-422. Fijado antes de ver ningún dato posterior al arreglo.
- **Requisito:** un reinicio con relevo desde la rama `javi/snap-price-fix` (o `main` con ella fusionada). Lo decide y lo ejecuta Javi. Sea `R` la hora UTC en que el writer nuevo escribe `ready`, redondeada hacia arriba a 5 minutos.
- **Versiones distinguibles:** las políticas nuevas usan etiquetas nuevas (`r3p`, `cn1p`, `np1p`), así que el writer les asigna códigos públicos nuevos con la misma sal privada. Ninguna fila posterior al arreglo se mezcla con una anterior. La tabla interna/pública sigue solo en el Mac.
- **Una comparación cada vez, dos brazos, sin exploración:**

| Fase | Política | Cohorte que se juzga | Control | Retador | Descubrimiento | Confirmación |
|---|---|---|---|---|---|---|
| A | `recsys/policy.fix_a_cold_new.json` | usuarios nuevos, producto/categoría con vistas | `v3-lfm-r3p-n` | `v3-lfm-cn1p-n` | R+10 a R+100 (90 min) | R+100 a R+160 (60 min) |
| B | `recsys/policy.fix_b_np1.json` (cambio en caliente en R+160, anotado en `policy_changes.log`) | usuarios conocidos, producto/categoría con vistas | `v3-lfm-r3p-k` | `v3-lfm-np1p-k` | R+165 a R+255 (90 min) | R+255 a R+315 (60 min) |

- **Tamaños esperados** (tráfico del 14 nov, 10.800 peticiones/h; nuevos en páginas 24%, conocidos en páginas 57%): fase A ≈1.900 por brazo en descubrimiento y ≈1.300 en confirmación (error típico de la diferencia ≈0,19 y ≈0,24 pt; conjunto ≈0,15); fase B ≈4.600 y ≈3.100 por brazo (≈0,11 y ≈0,14 pt; conjunto ≈0,09). Compras esperadas por brazo a las tasas de hoy: A ≈65 y ≈45; B ≈90 y ≈60.
- **Agrupar controles:** con dos brazos no hay nada que agrupar. Si Javi prefiere mantener más brazos, solo se suman filas que sirvan exactamente la misma política a la cohorte (mismos pesos, sin exploración, mismo código). En la política `x2`, `np2-n` y `r3-n` cumplían eso; `np1-n` (exploración) y `og1-n` (exploración) no.
- **Qué se anota en cada ventana** (`python recsys/confirm_read.py --from … --to … --control … --challenger …`, mismas horas para todos): peticiones, conversión esperada y compras esperadas de cada brazo, `reference` y `baseline` de la misma ventana, peticiones y conversión cold oficiales, `on_time` del equipo, diferencia con su error típico nominal y por bloques de 15 minutos. Sin miradas intermedias que cambien el plan.
- **Regla, fijada de antemano:** el retador se promueve solo si (1) la diferencia del bloque de descubrimiento es positiva, (2) la del bloque de confirmación, que es un bloque nuevo, también, (3) la diferencia conjunta supera 2 errores típicos (el mayor entre el nominal y el de bloques), (4) su conversión cold no cae más de 2 errores típicos y (5) `on_time` ≥ 99,5% en las dos ventanas. Si el descubrimiento sale negativo se quita el retador sin bloque de confirmación. Cualquier otro resultado es no concluyente: sigue el campeón (`recsys/policy.fix_champion.json`, r3 solo con precios).
- **Límites de hora:** nada se lee después de las 07:15 UTC del 15 nov; elección a las 07:30 UTC, congelación a las 08:00 UTC, sin cambios en el writer de 09:00 a 13:00 UTC. Si `R` es posterior a las 01:45 UTC la fase B no cabe entera y queda como no concluyente. Si solo cabe una fase, va la A.
- **`np2` y `og1`:** exploratorios. No entran en estas dos comparaciones y no se sube más el peso de `newp`.
- **Vuelta atrás:** política, `cp policy.fix_champion.json data/policy.json` (en caliente). Código, reiniciar con relevo desde `6150ffc` y `cp policy.champion.json data/policy.json` (r3 solo: sin brazo `lq` el código antiguo sirve los precios bien).
- **Lo que no se puede afirmar:** una mejora vista esta noche es de esta noche. La final trae compradores, productos y tendencias nuevos; lo observado hoy no se atribuye a mañana.

### D-421 — Adaptación de D-420 a la rotación por bloques aprobada por Javi (r3 / cx3 / r3 / og1, 15 minutos, una variante al 100%, sin brazo `lq`)
- **Fecha / propone:** 2026-11-14 23:05 UTC · Javi (agente, T-042), a petición del coordinador. La rotación la aprobó Javi en el hilo de despliegue; aquí solo se fija cómo leerla.
- **Precios durante la rotación:** con políticas sin brazo `lq` el código actual (`6150ffc`) sirve los precios bien. `read_policy` llama a `LF.set_arms` en cada cambio y eso vacía `alt_lq`; `cold_lq_for_arms` devuelve entonces `None` y el snapshot siguiente (un ciclo, unos 20–40 s) se construye por el camino correcto. Los casos "sin correcciones" de `tests/test_snap_prices.py` pasan también con el código antiguo. Por tanto el arreglo no es urgente mientras ninguna política lleve `lq`: va en el relevo planificado.
- **Condición:** no volver a poner `cn1` ni ningún brazo `"lq"` hasta que el writer cargue el PR #41. Hacerlo deja sin precios a todos los brazos.
- **Corte de serie:** el r3 de la rotación (con precios) no es el r3 de 19:07–22:57 UTC (sin precios) aunque comparta código público. No sumar filas de los dos tramos; leer siempre por ventana exacta de bloque.
- **Lectura** (`python recsys/rotation_read.py --start "<inicio UTC>" --block-min 15 --seq r3,cx3,r3,og1 --until "2026-11-15 07:15"`): como cada bloque sirve una sola variante a todo el tráfico, se usa la fila del equipo de cada bloque menos `reference` en la misma ventana. No hacen falta etiquetas. Cada bloque del retador se compara con la media de los dos bloques de r3 que lo rodean. En la tarde del 14 nov esa diferencia frente a `reference` varió unos 0,07 pt entre bloques de 15 minutos, así que con 6–8 bloques por retador el error típico de la comparación ronda 0,04–0,05 pt.
- **Regla, fijada de antemano:** un retador sustituye a r3 solo si su diferencia emparejada media es positiva en las dos mitades de la noche y supera 2 errores típicos entre ciclos, con al menos 6 bloques válidos (a tiempo ≥ 99%), sin caída de la conversión cold y sin que las compras reales lo contradigan. Si no, sigue r3. Lectura única a las 07:15 UTC; elección a las 07:30, congelación a las 08:00.
- **Límites de la rotación:** los primeros ~40 s de cada bloque todavía sirven la variante anterior (4% del bloque, sesga hacia cero). El estado del comprador (carritos, compras) pasa de un bloque al siguiente, así que es una comparación entre políticas alternadas, no entre usuarios separados.
- **`cold_new` y `np1` (D-420):** quedan para después del relevo con el PR #41. `cold_new` no se puede probar sin el arreglo. Si el relevo llega después de las 01:45 UTC solo cabe la fase A; si llega después de las 04:30 UTC no cabe ninguna y la final va sin `cold_new` ni `np1`. `np1` sí puede entrar en la rotación como una variante más sin reinicio, porque no usa `lq`; es decisión de Javi.

### D-422 — Enmiendas a D-421: emparejamiento por ráfagas y lectura continua con umbral secuencial
- **Fecha:** 2026-11-14 23:40 UTC · Javi (agente, T-042). Escrito antes de leer ningún bloque de la rotación (empezó a las 23:00 UTC).
- **Por qué (1), ráfagas:** la auditoría de reglas encontró ráfagas de una subcategoría de 45 minutos a y media de las horas impares UTC (09:30, 11:30, 13:30, 15:30, 19:30, 21:30; ninguna a las 17:30). Con la secuencia :00 r3, :15 cx3, :30 r3, :45 og1, el bloque de cx3 nunca cae en ráfaga y uno de sus dos vecinos r3 siempre. Comprobado aquí con el leaderboard (15:30–23:30 UTC, bloques con ≥ 99% a tiempo): equipo menos referencia −0,09 pt en ráfaga (6 bloques) y −0,14 en calma (17 bloques, desviación 0,08). La diferencia (+0,05) no es significativa por sí sola, pero el desequilibrio de diseño es real y sesgaría contra cx3 unos 0,03 pt, del orden del error típico.
- **Cambio (1):** el emparejamiento principal usa solo vecinos r3 en el mismo estado (ráfaga o calma) que el bloque del retador. Para cx3 eso es el r3 de :00 en las horas impares y el de :30 en las pares; og1 conserva sus dos vecinos, que siempre comparten su estado. Las ráfagas reales de la noche se comprueban en `shop.events` y se pasan con `--bursts`; si una hora no tuvo ráfaga, sus bloques cuentan como calma. El emparejamiento con los dos vecinos se sigue imprimiendo (`paired_all_neighbours`).
- **Por qué (2), lectura continua:** Javi (23:28 UTC) retira la lectura única de las 07:15 UTC y la espera hasta las 08:00: está despierto y decide sobre la marcha.
- **Cambio (2):** se lee al cierre de cada ciclo de una hora (primera lectura a las 00:00 UTC) y se publica la tabla. Mirar muchas veces infla los falsos positivos, así que el umbral para actuar es más exigente al principio:

| Bloques emparejados del retador | Sustituye a r3 si | Se descarta si |
|---|---|---|
| 3 o 4 | z ≥ 3,0 | z ≤ −2,5 |
| 5 o 6 | z ≥ 2,5 y positivo en las dos mitades | z ≤ −2,0 |
| 7 o más | z ≥ 2,0 y positivo en las dos mitades | z ≤ −2,0, o media + 2 errores típicos < +0,05 pt (no puede ser una mejora útil) |

  z = diferencia emparejada media dividida por su error típico entre ciclos. Con menos de 3 bloques no se decide nada. Bloques con menos del 99% a tiempo no cuentan. Además, para sustituir: conversión cold sin caída de más de 2 errores típicos.
- **Lo que no cambia:** equipo menos referencia por bloque, r3 como base, y que lo observado esta noche no se atribuye a la final. Un retador descartado se sustituye por el siguiente candidato en su hueco de la rotación; un retador que gana pasa a ser la base y la cuenta de bloques empieza de nuevo contra él.
- **Aviso honesto:** estos umbrales reducen los falsos positivos de mirar cada hora, no los eliminan. Con 3 retadores y 8 lecturas, alguna señal de z ≈ 2 aparecerá por azar.
