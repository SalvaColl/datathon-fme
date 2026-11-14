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
- **Date / owner / status:** 2026-11-14 / agente de Javi (T-009, rama `javi/cold-items`) / **PROPOSED** (no aplicada; `live.py` y `fe.py` no se han tocado)
- **Question and alternatives:** v1 ignora las frases de la descripción (I-090, I-092). Alternativas: (a) multiplicador de afinidad sobre el score actual + candidatos por afinidad; (b) reentrenar el GBM con esas features (peor offline: hit@1 0,495 frente a 0,519, y obliga a cambiar `fe.py`); (c) nada.
- **Decision (propuesta):** (a), detrás de una variante `aff` en `policy.json`. Es un multiplicador, así que se compone con cualquier score (v1, `qrank` de D-081, `home_cands` de D-130) y con el filtro de productos muertos de D-130, que conviene aplicar antes. Cambio en `live.py`, 6 líneas:
  1. Arriba: `import cold_items, attr_affinity; COLD = cold_items.ColdStart(); AFF = attr_affinity.AttrAffinity(COLD)` (carga `data/user_item_all.parquet`, unos 15 s).
  2. En `refresh_events()`, dentro del bucle: `AFF.add(r["u"], r["i"], r["v"])`.
  3. En `refresher()`, tras `refresh_events()`: `COLD.sync(query); cold = COLD.tables(cat, BASE["item"], T.item_frame())` y guardar `cold` en `state`. (Parte A, productos nuevos.)
  4. En `predict()`: `featurize(P, [BASE, live, cold], ...)` en lugar de `[BASE, live]`. (Parte A.)
  5. En `candidates()`: `c += AFF.candidates(req["user_id"], rv, cat, unavail, n=60, score=None)`; con `category=cat.at[rv[-1], "category"]` si se quiere mantener la categoría de la sesión en product/category.
  6. En `predict()`, tras `predict_proba`: `X["s"] *= AFF.boost_frame(X)`; `model_version = "v1-aff"`.
- **Why, evidence/experiment:** I-092, E-092, E-093, E-094. Offline hit@1 0,472 → 0,519; en vivo los productos con afinidad <0,15 (85% de lo que mostramos a usuarios conocidos) casi no se compran. Estimación con tasas del feedback: de ~0,9% a ~2,4% por petición; es una extrapolación, no una medida del modelo oculto.
- **Affected modules/interfaces/owners:** `recsys/live.py` (dueño del writer). Nuevos: `recsys/cold_items.py`, `recsys/attr_affinity.py`, `recsys/cold_prior.json` (270 KB, se regenera con `python cold_items.py fit`). Sin dependencias nuevas en el camino de servicio (numpy/pandas).
- **Rollout / rollback:** `python live.py --dry-run` con la variante (medido en copia parcheada: p95 1,2–1,4 s); después un bloque de 10 min alineado con `updated_at` del leaderboard, comparar contra `baseline` y contra el bloque anterior de v1. Rollback = quitar `aff` de `policy.json`. `AttrAffinity(beta=...)` regula la agresividad (40 por defecto; 20 es la opción prudente).
- **Revisit condition:** si el bloque en vivo no mejora frente a v1, bajar β a 20 o limitar a la categoría de la sesión antes de descartar.

## Corrected previous assumptions

- OLD: 1 request every 3 seconds -> **3/sec**.
- OLD: leaderboard hourly -> **refresh 10min, reports last hour during practice**.
- OLD: exact objective unconfirmed -> **conversion expected probability; revenue tie-breaker**.
- OLD: no historical data assumed -> **historical propensities, sessions, organic events available**.
- OLD: need server endpoint -> **continuous RawTree polling and insert loop, no recommendation webserver required**.

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
