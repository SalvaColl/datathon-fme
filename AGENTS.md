# Agent operating instructions — Datathon FME 2026 / RawTree

**Every agent must read this file, `challenge.md`, `strategy.md`, `tasks.md` and relevant `insights.md`/`experiments.md` before coding.** Official site/repository and any newer organizer clarification supersede this pack. This document is current as of **2026-11-14**.

## Non-negotiable challenge contract

- Shared RawTree stream: `shop.requests` **~3/sec** (not 1 per 3 sec); `shop.events`, `shop.catalog_updates`. Private read/write database: `${TEAM_ID}`.
- Submit **one** JSON record/request to `<TEAM_ID>.submissions` through RawTree: `request_id`, `items` (ordered **exactly 10 unique active real product IDs**), `model_version`.
- Organizer receives valid submission **within 3 seconds from request `ts`**. Late/invalid/missing -> baseline fallback and lost reliability.
- Final scoring: **Sunday Nov 15 10:00–12:00 CET**, new buyers/products/trends, leaderboard hidden. Primary 50 points conversion (expected purchases), 10 cold-start, 10 reliability, 30 jury. Revenue is a tie-breaker only.
- Keep the recommender running unattended, including overnight; never disable the serving loop for experiments.
- Official starter: `starter/recommender.py`; modify the `recommend()` policy or compatible wrapper, **preserve proven polling/batched writer** unless consciously upgrading and testing it. Offline notebook: `starter/offline_eval.ipynb`.

Read precise schemas, metrics, sources and discrepancies in `challenge.md`.

## Coordination and code ownership

1. Claim a task/branch in `tasks.md` **before making code changes**. One owner for serving loop, RawTree client, feature interface, deployment and model promotion. Other agents work in isolated policy modules or branches.
2. Keep a stable **champion** and separate **challengers**; no simultaneous writer processes inserting answers for the same request. An experiment must not duplicate live submissions.
3. Never replace the champion because a model *sounds* more sophisticated. Require a reproducible offline comparison in `experiments.md`, valid-slate/latency checks and rollback procedure.
4. Do not fabricate metrics or claim that simulation matches the hidden buying model. Label evidence `OFFICIAL RULE`, `OBSERVED DATA`, `OFFLINE ESTIMATE`, `LIVE FEEDBACK`, `HYPOTHESIS`, or `UNTESTED`.
5. Code must have deterministic seeds/configs, static interfaces, tests for failure cases and short handoff docs. Make changes incrementally and avoid unnecessary refactors.
6. Use the team's existing Python virtual environment. Install nothing without coordination. Do **not** change `.env`, overwrite secrets, commit credentials or paste real API keys into agent prompts/logs/issues.
7. Never train with future information. **Time-split data**, correctly reconstruct product prices/status at prediction time, and exclude later events/feedback from features.
8. Historical carousel impressions are **selection-biased and position-biased**. Do not treat non-exposed items as negatives. Historical purchase labels on shown slates need careful handling. Propensity estimators need support and variance checks; `starter/offline_eval.ipynb` is a starting point, not proof of unbiased full-slate evaluation.
9. Handle new buyers, new items, price changes, late stock changes, missing features, RawTree query delays, retry/restart behavior and duplicate IDs. An inactive item invalidates the whole slate. The last-known catalog may be stale: prioritize refresh and conservative validity.
10. Preserve knowledge: `challenge.md` for verified contract; `strategy.md` for current plan; `insights.md` for ideas and rejections; `experiments.md` for measured tests; `decisions.md` for binding choices; `tasks.md` for work ownership; `runbook.md` for operation.

## Suggested interfaces (team design, NOT official schema)

- `recommend(request, feature_snapshot, catalogue_snapshot) -> list[str]` with exactly 10 ordered IDs.
- `validate_slate(items, active_ids) -> bool` returns true only for ten distinct active IDs.
- Separate `RawTreeClient`, asynchronous/batched ingestion, short-lived feature snapshots, and a background online learner. Ensure critical response path is bounded and does not require an LLM API call.
- Persist `request_id -> model_version`/chosen slate to attribute feedback, and checkpoint poll state across restarts. Never send duplicate answers.

## Every agent handoff must include

1. Task/branch/commit and files changed.
2. Interface and dependency changes.
3. Exact commands and tests run, with results (or explicitly *not run*).
4. Evidence/experiment ID and any data leakage or evaluation limitations.
5. Serving risks, p95/p99 latency where measured, rollback plan.
6. Updates to `tasks.md`, `insights.md`, `experiments.md` or `decisions.md` as appropriate.

## Priorities

**Valid production loop > data/time integrity > historical evaluation and cold-start signals > strong hybrid policy > cautious live adaptation > complex RL.** The winning solution also needs a clear jury explanation. AI tools are expressly allowed, but team members must understand the implementation.

Sources: https://datathon.rawtree.dev/ and https://github.com/rawtreedb/datathon-fme-2026
