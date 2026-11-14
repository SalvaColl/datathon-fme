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
