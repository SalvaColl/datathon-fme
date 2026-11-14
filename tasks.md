# Parallel task board — assign owners before agents modify shared code

**Priority: get an official starter response served now, then evaluate historical data.** Every row needs a human/agent owner, branch and status. Suggested priority/order below does **not** imply work is completed.

| Task | Priority | Workstream and deliverable | Owner/branch | Status | Dependencies |
|---|---|---|---|---|---|
| T-001 | P0 | Official spec + starter files reviewed, schemas and score in `challenge.md` | Doc owner / docs refresh | **DONE (public sources only)** | Actual team API access not tested |
| T-002 | P0 | Run baseline `starter/recommender.py`, verify live feedback `served_by='team'`, p95, `.env` safe | TBD / TBD | READY | TEAM_ID/key; available Python env |
| T-003 | P0 | RawTree client, polling ledger, batch writer, stock refresh, valid-ten guard, retries and restarts | TBD / TBD | READY | T-002 working instance; **single writer** |
| T-004 | P0 | Inspect `history_sessions`/`history_events`; time-split, data size/quality and offline notebook + IPS assumptions | Javi / javi/v1-gbm-recommender | **DONE (first pass, I-010…I-015)** | RawTree read credentials |
| T-005 | P0 | B1 personalized heuristic: recent views, co-views, category/brand profile, candidate assembly | Javi / javi/v1-gbm-recommender | **IN PROGRESS (candidates in `recsys/live.py`)** | T-004 features; policy interface |
| T-006 | P0/P1 | Offline evaluation harness, replay and cold-start slices, reproducible experiment registry | TBD / TBD | READY | T-004; no hidden-simulator access |
| T-007 | P1 | B2 ranker logistic/LightGBM or CatBoost; model registry and offline comparison | Javi / javi/v1-gbm-recommender | **IN PROGRESS (v1 HistGB, E-003; awaiting live swap by serving owner)** | T-004 and T-006; library availability |
| T-008 | P1 | Real-time `shop.events` trend aggregates + `catalog_updates` cache | Javi (agente) / javi/live-trends | **OFFLINE DONE (E-080, I-080/I-081); integración propuesta en D-080, pendiente de A/B en vivo por el dueño del writer** | T-003; frequent incremental refresh |
| T-009 | P1 | New-product content-based cold-start candidate generation | Javi (agent) / javi/cold-items | **MVP DONE, pendiente de prueba en vivo (D-090; I-090…I-092; E-090…E-094). Incluye `recsys/attr_affinity.py` (afinidad usuario × frases de descripción)** | T-004/T-005; catalog descriptions |
| T-010 | P1 | Slate ordering/diversity/price ablation | TBD / TBD | READY | T-005/T-006 or T-007 |
| T-011 | P2 | Optional bounded bandit after proven ranker | TBD / TBD | HOLD | Reliable feedback attribution and offline/live evidence |
| T-012 | P0 | Final deployment, backup, monitoring/rollback + jury demo | TBD / TBD; jury deck: Javi (agente) / javi/jury-deck | READY; **jury deck drafted in `presentation/` (placeholders for ab_qrank and night-lab results)** | Live loop, champion, experiment metrics |
| T-015 | P0 | Ranker `qrank` para product/category: calidad del producto en el carrusel aleatorizado × contexto (visto, subcategoría, slot), solo misma categoría y sin lo ya comprado; módulo `recsys/qrank.py` importable por `live.py` | Javi (agente) / javi/rv-first-slate → javi/qrank-serving | **IMPLEMENTED/TESTED sobre el writer de Salva (rama `javi/qrank-serving`, 30 tests, dry-run OK); sin desplegar, pendiente de A/B en vivo por el dueño del writer** | Feedback en vivo de v1; no toca `live.py` |
| T-016 | P0 | Laboratorio nocturno contra el leaderboard: `recsys/night_lab.py` rota variantes de `policy.json`/`d130.json` del writer único en bloques, registra cada snapshot (conversión vs `baseline` y `reference` de la misma ventana), guardia de seguridad con vuelta a la mejor variante y tabla de ablación. Solo escribe esos dos JSON; nunca toca RawTree | Javi (agente) / javi/night-lab | **IMPLEMENTED/TESTED (11 tests con leaderboard simulado + dry-run real, E-160); sin arrancar: lo lanza Javi en su Mac (runbook, D-160)** | Writer con variantes de PR #1–#3; lo arranca Javi en su Mac |
| T-019 | P0 | Afinar `qrank` con brazos medibles en el leaderboard: `policy.json` admite `qrank_arms` (reparto por hash de usuario, cada brazo con su `viewed_factor` y su `model_version` `v2-qrank-<tag>`), para comparar con `/api/state?by=model` en ~15 min sin reiniciar | Javi (agente) / javi/qrank-tune | **IMPLEMENTED/TESTED (66 tests); pendiente de entrar en el próximo reinicio del writer y de medir** | T-015 en main |
| T-018 | P0 | Descomponer el hueco con la referencia por segmento y atacar el mayor: variante `lfm` (modelo ajustado con el feedback de hoy, pesos distintos para usuario nuevo y recurrente, carrito no comprado + afinidad) | Javi (agente) / javi/lfm-live-fit | **IMPLEMENTED/TESTED (77 tests, dry-run real sin escribir, E-180); apagada por defecto, pendiente de A/B por leaderboard por el dueño del writer (D-180)** | Writer de main; reinicio único para cargar el código |
| T-012 | P0 | Final deployment, backup, monitoring/rollback + jury demo | TBD / TBD | READY | Live loop, champion, experiment metrics |
| T-013 | P1 | `home` page + new-user candidates (no session views): organic user affinity / global converters, new module `recsys/home_cands.py` importable by `live.py`; offline time-split eval | Javi's agent (Claude) / javi/home-new-users | **MVP DONE, pendiente de prueba en vivo (D-130; I-130…I-132, E-130…E-132)** | I-010; RawTree read access; does not edit `fe.py`/`live.py` |
| T-021 | P0 | lfm v2: reajuste con feedback propio, 6 features nuevas (`lfm_coef_r2.json`) y brazos de pesos en caliente (`lfm_arms` en `policy.json`) leídos por segmento en el leaderboard | Javi (agente) / javi/lfm-v2 | **IMPLEMENTED/TESTED (114 tests, dry-run real sin escribir, E-210); sin brazos no cambia nada; pendiente de reinicio y experimento por el dueño del writer (D-210)** | lfm en main |
| T-023 | P0 | Afinador de pesos de lfm por rondas contra el leaderboard (`recsys/lfm_tuner.py`): 3 brazos por ronda de 30 min, se queda con lo que gana por segmento; admite un solo brazo en `lfm_arms` para dejar puestos los mejores pesos | Javi (agente) / javi/lfm-tuner | **IMPLEMENTED/TESTED (133 tests con leaderboard simulado, ensayo en seco contra el leaderboard real); sin resultado en vivo todavía; arrancarlo es decisión del dueño del writer (D-230)** | T-021 en main, writer en `lfm` |
| T-K30 | P0 | Returning product/category users: taste-conditioned pending-cart boost, distinct from Javi's uniform cart weights; opt-in coefficient-file policy arm and read-only as-of replay | Codex / salva/k30 (main 9e87814 integrated); recsys/k30.py, lfm.py, new coefficient artifact, tests and handoff | READY FOR REVIEW / UNTESTED ONLINE; E-K30, 159 tests OK (8 Windows skips); recsys/K30.md | Javi owns deployment; no second writer; coordinate with javi/known-session / tuner |

| T-024 | P0 | lfm r3: reparto de categorías de cada usuario (vistas de 60 días + hoy) como señal nueva (`ucat`, `usub`), pesos en `lfm_coef_r3.json`, servido como brazo `{"tag": "r3", "file": "lfm_coef_r3.json"}` | Javi (agente) / javi/known-gap | **IMPLEMENTED/TESTED (138 tests, ensayo en seco real sin escribir, E-240); sin lectura del leaderboard todavía; necesita un reinicio del writer para cargar el código; activar el brazo es decisión del dueño del writer (D-240)** | T-021 en main |

## Proposed responsibility split (adapt to actual team size)

- **Serving/RawTree owner:** T-002, T-003; only person integrating/deploying the live writer. Prevent simultaneous independent submissions.
- **Data/evaluation owner:** T-004, T-006; reconstruct chronological features and support-aware offline evaluation.
- **Ranking owner:** T-005, T-007, T-010; champion/challenger scorer modules, does not edit network loop directly.
- **Stream/cold-start owner:** T-008, T-009; incremental trends, catalog updates, cold profiles/new products.
- **Integration/presentation owner:** T-012 (could be combined with serving owner); runbook, diagrams, metrics, demonstration.

## Internal proposed API boundaries — decide once, document in code

```text
request: dict with request_id, ts, user_id, is_new_user, context, recent_views
catalog_snapshot: mapping product_id -> metadata incl active and current price
feature_snapshot: as-of timestamp, customer/item/trend lookups
policy.recommend(request, features, catalog) -> list[10 real product_id strings]
validate_slate(items, catalog) -> bool
logger(request_id, submitted_items, model_version, timings)
```

**Official** on-wire output is submitted to `<TEAM_ID>.submissions` as `{request_id,items,model_version}`; these internal function signatures are only a team proposal. Ensure code remains compatible with the starter `recommend(recent_views, best, unavailable)` wrapper if existing notebook imports it.

## Integration handoff rules

1. Claim owner and branch, declare file ownership and expected inputs/outputs.
2. If changing shared interface, propose change in `decisions.md` and notify affected owners before coding.
3. Commit atomic code + tests; add run commands and measured impact to `experiments.md`/`runbook.md`.
4. Never deploy challenger without approval of serving owner and tested rollback.
5. Before Sunday 10:00 CET, freeze high-risk experiments and leave a verified champion running.

## Coordination cadence

- Reconcile commits after each working feature or every 1–2 hours during practice.
- Review leaderboard **every 10 minutes** if useful, but remember it summarizes the **last hour** and is not clean per-version A/B attribution.
- Monitor `feedback` frequently and prepare a concise jury narrative using genuine offline experiments and adaptation logs.
`n| T-013 | P0 | Three-period reproducible offline league, registry, uncertainty and leakage tests | Codex / current working branch; tools/local_league.py, tools/league_*, tests, evaluation docs | DONE; E-010/E-011, 10 tests pass; final test unscored | Read-only RawTree; live starter excluded |

| T-014 | P0 | Investigate v1-gbm-cand missing/invalid feedback; harden deadline handling, transport and stock checks | Codex / salva/serving-reliability; recsys serving/tests + diagnostics/docs | IMPLEMENTED/TESTED; code 7176c03; 21 tests pass; E-REL-001; rollout with Javi | Javi owns live process on his laptop; no deployment or second writer |

| T-018 | P0 | Calidad en vivo desde `shop.events` (`live_quality`): tasa compra/vista rolling (30–60 min) por producto y subcategoría con shrinkage bayesiano hacia un prior de atributos (el de T-017 cuando exista; `cold_prior.json` mientras tanto). Validación por replay con features solo del pasado. Variante de policy apagada por defecto. IDs de docs 18x | Javi (agente) / javi/live-quality (sobre main) | **IMPLEMENTED/TESTED (9 tests, replay E-180…E-183, I-180…I-184); hook inerte en `live.py`, pendiente de A/B en vivo por el dueño del writer (D-180)** | trends.py, cold_items.py, T-017; no toca `live.py` sin propuesta |
| T-017 | P0 | Ranker por atributos generalizable (`attr_model`): calidad = f(categoría, frases de la descripción, marca, precio relativo en la subcategoría) × afinidad del usuario calculada solo con `recent_views`; calidad por ID solo como corrección con shrinkage. Variante de policy apagada por defecto. IDs de docs 17x | Javi (agente) / javi/attr-model (sobre main) | **IMPLEMENTED/TESTED, apagado por defecto, sin desplegar; pendiente de bloque en vivo por el dueño del writer (D-170; I-170…I-172; E-170…E-173; 80 tests)** | qrank.py, attr_affinity.py, cold_items.py; no toca `live.py` |
| T-020 | P1 | Tablero de ideas del equipo en `insights.md` (descartadas R-01…R-16, ideas nuevas I-200…I-209 con `owner: free`) y pruebas offline baratas sobre el feedback en vivo (E-200…E-205; `recsys/explore_t020*.py`, solo lectura) | Javi (agente) / main (solo docs y scripts de exploración) | **DONE 2026-11-14 15:00 UTC**; las ideas I-200…I-209 están libres | lfm en evaluación (T-018) |
| T-022 | P0 | Respuestas a tiempo: quitar el bloqueo de ~60 s tras cada arranque, reinicio sin pérdida con relevo de un solo writer (`--takeover`), pausas del recolector de basura. IDs de docs 22x | Javi (agente) / javi/on-time-handoff (sobre main) | **IMPLEMENTED/TESTED (14 tests nuevos, 118 en total; E-220; ensayo de relevo 300/300 sin duplicados). Sin desplegar: lo aplica el hilo de despliegue en el reinicio previo a la final (D-220)** | T-014 (`serving.py`), dueño del writer |
