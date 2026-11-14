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

### D-011 — Offline league policy interface (implemented for T-013)
- **Date / owner:** 2026-11-14 / Codex.
- **Interface:** register a zero-argument factory in `tools.league_policies`; returned object implements `fit(training_snapshot)` and `recommend(request, features, catalog) -> list[str]`. Catalog is read-only and eligible as of request time; features currently empty; rewards/logged actions withheld from recommend. No serving interface/dependency change.
- **Discipline:** independent chronological caches; train-only fitting, validation tuning, frozen policy/source selection and one-time final-test scoring. Previously evaluated legacy request IDs excluded. Plugins may not read outside the provided training data; trusted modules and external/transitive dependencies require review. See `tools/LEAGUE.md`.
- **Rollback:** offline-only change; retain live champion and do not restart it. No promotion from these proxies alone.

### D-REL-001 — Serving reliability patch prepared; deployment remains with Javi
- **Implemented code:** `7176c03` adds deadline-first batching, fresh-cache validity checks, per-thread transport and durable at-most-once claims. Request/model schema unchanged; catalogue argument to `featurize` is optional and backward compatible. Existing model artifact retained, served as v1-gbm-cand-r1 for attribution. No dependency installation.
- **Tradeoff:** without documented server idempotency, ambiguous POST failures are not blindly retried. Journal crash window can lose an answer; duplicates cannot safely be used as an update mechanism. Local process lock plus team-designated host; no claim of cross-host enforcement.
- **Deployment:** Javi owns the active laptop. Patch is tested locally and available for cherry-pick; no writer launched/stopped here. Retain old model/checkout and journal; monitor five-minute accepted/missing/invalid counts and stage timing after an owner-controlled handoff. Source evidence and limits: E-REL-001; detailed operations: recsys/README.md.
