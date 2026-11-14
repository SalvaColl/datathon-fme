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
| T-009 | P1 | New-product content-based cold-start candidate generation | TBD / TBD | READY | T-004/T-005; catalog descriptions |
| T-010 | P1 | Slate ordering/diversity/price ablation | TBD / TBD | READY | T-005/T-006 or T-007 |
| T-011 | P2 | Optional bounded bandit after proven ranker | TBD / TBD | HOLD | Reliable feedback attribution and offline/live evidence |
| T-012 | P0 | Final deployment, backup, monitoring/rollback + jury demo | TBD / TBD | READY | Live loop, champion, experiment metrics |

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
