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


## D-CS01 — Propuesta: calidad de productos nuevos para lfm desde `live_quality` (T-CS01) — PENDIENTE del dueño del writer
- **Cambio:** 2 líneas en `live.py` (crear `cold_lq.ColdLQ()` en `initialize()`; en `refresher()` pasar `CLQ.lq_for_lfm(QR, cat, BASE["item"], T.item_frame(), AP.cold.desc)` a `LF.set_catalog` en lugar de `QR.lq`). Detalle en `recsys/COLDSTART_CHALLENGER.md`.
- **Inerte por defecto:** devuelve el mismo `QR.lq` salvo `data/coldlq.json` = `{"mode": "on"}`; solo cambian productos sin q histórica; qrank y sus slates no cambian.
- **Prueba:** bloques de tiempo on/off de 15–20 min leídos con la ventana propia del leaderboard por etiqueta de lfm. **Rollback:** borrar `data/coldlq.json` (≤ 20 s).
- **Evidencia:** E-CS01b/c/d. **Riesgo:** si el modelo oculto no premia los productos nuevos, más exposición puede costar conversión; por eso solo con A/B.
