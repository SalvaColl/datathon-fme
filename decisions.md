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
