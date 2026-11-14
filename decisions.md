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

## Corrected previous assumptions

- OLD: 1 request every 3 seconds -> **3/sec**.
- OLD: leaderboard hourly -> **refresh 10min, reports last hour during practice**.
- OLD: exact objective unconfirmed -> **conversion expected probability; revenue tie-breaker**.
- OLD: no historical data assumed -> **historical propensities, sessions, organic events available**.
- OLD: need server endpoint -> **continuous RawTree polling and insert loop, no recommendation webserver required**.

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
