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
