# Experiment registry and champion-promotion protocol

This is a **ledger, not a claim that tests have run**. As of 2026-11-14, no team-specific results are provided in this pack. Keep real experiments here; raw logs and model files should live in versioned project paths / private RawTree.

## Official goal and measurement hierarchy

The **primary metric is expected conversion per request** in the final round (50 pts), with cold-request conversion (10 pts) and successful on-time valid responses (10 pts). The organizers know a hidden simulator probability; **our own offline/live datasets do not expose it**. Treat actual purchases/CTR as noisy proxies. Price-weighted revenue is a tie-breaker.

1. **Offline historical evaluation** — `starter/offline_eval.ipynb` on chronological holdouts from `shop.history_sessions`. Inspect the IPS method; do not blindly trust propensities for unsupported candidate slates or use click-IPS as purchase score.
2. **Complementary predictive evaluations** — purchase AUC/log loss/calibration, within-impression slate ranking, support-aware IPS when justified, user/product cold subsets, robustness to temporal drift.
3. **Shadow/live diagnostics** — generate challenger recommendations on real live requests **without a second submission** to validate schema, stock, compute/RawTree latency; counterfactual purchases are unobserved.
4. **Live randomized trials** — only if team agrees and instrumentation accurately assigns version per request; preserve valid submissions and check uncertainty, time drift, segment mix. Leaderboard (rolling last hour, refreshes 10min) is not a clean randomized comparison.
5. **Synthetic league** — shared seeded and adversarial scenarios for code integrity; no claim of hidden-model performance.

## Historical evaluation caveats

- Historic carousel = **best sellers plus randomness**; positives only for exposed items. Never treat unshown items as observed negatives.
- `propensity` entries are **conditional per displayed slot**. An estimator needs correct target/logging-policy action probabilities, nonzero support and enough effective samples. Record weight distribution/clipping and confidence interval. Inspect notebook assumptions before reuse for full slates or purchase reward.
- Time-split all item/user features; feature lookups for an impression at time `t` must use only data recorded **before** `t`.
- Cold segment as official: `is_new_user` **or** `recent_views` contains a product introduced during event. Historical sessions may lack `is_new_user`; mark approximations clearly and add explicit live cold evaluation.
- Do not contaminate history with final-round requests or simulate future catalog status on earlier requests.
- Compare matched datasets, report N requests and N purchases, repeated seeds where relevant, uncertainty and significant regressions.

## Required metrics per comparison

| Family | Metrics |
|---|---|
| Accuracy | Realized purchase / request, click / request, purchase AUC/log loss, support-aware IPS proxy (if valid), revenue / request as secondary |
| Cold start | New user, new-product-in-recent-views, no recent views, new products recommended; counts, conversion proxy |
| Reliability | % `served_by='team'`, `fallback_reason` counts (`missing`/`late`/`invalid`), unique/active exact-10 rate |
| Latency | E2E feedback `latency_ms` p50/p95/p99/max; missed deadlines; poll interval, POST batch delay |
| Data drift | Trend-shift, price-change and stockout segments; model/feature age, inventory refresh lag |
| Data integrity | Leakage checks; training window, time cutoff, catalog as-of timestamp, random seeds |

## Planned experiments (NOT RUN)

| ID | Priority | Challenger | Comparison / dataset | Pass condition |
|---|---|---|---|---|
| E-001 | P0 | Official B0 baseline | Live feedback + starter notebook | Verified `served_by=team`, stable latency, recorded baseline |
| E-002 | P0 | B1 context/category/co-view heuristic | Chronological historical holdout vs B0 | Better purchase proxy/cold, no validity regressions |
| E-003 | P0 | B2 history-trained logistic/LightGBM | Same holdout vs B0/B1 | Positive and credible improvement, acceptable variance/support |
| E-004 | P1 | Organic trends (15min/1h) | Ablation + practice feedback | Consistent benefit on drift segments |
| E-005 | P1 | New-product text/category neighbors | Historical product-launch holdout | Cold performance improves |
| E-006 | P1 | Diversity/position-aware slate | Fixed candidates/held out + practice | Improved expected proxy w/o narrowing overfit |
| E-007 | P1 | Inventory refresh / batching stress | Synthetic update storm + real feedback | No invalid slates, E2E deadline satisfied |
| E-008 | P2 | Thompson/UCB adjustment | Controlled live (if practical) | Improved proxy with bounded exploration cost |
| E-009 | P2 | PPO | Not scheduled | Requires a faithful simulator / compelling evidence; otherwise defer |

## Actual experiment records

| ID | Timestamp | Owner | Model + commit | Dataset/time split or live window | N | Primary/cold/validity/latency | Decision |
|---|---|---|---|---|---|---|---|
| E-001 (obs.) | 2026-11-14 12:45 | Javi (read-only) | team baseline writer | live feedback to 12:45 | 3,219 | realized conv 0.62%, CTR 2.5%; ~30% `missing` in last 10 min | Baseline recorded; writer loses requests |
| E-002 | 2026-11-14 13:00 | Javi | heuristics, `recsys/ev.py` | train sessions <2026-11-04, test ≥2026-11-04 (user feats from <2026-10-15) | 1,123 buying test sessions | within-slate hit@1 / MRR: random 0.10/0.30, logged order 0.31/0.51, viewed+sub+cr 0.35/0.54, +user cart 0.51/0.67 | Heuristics beat logged order |
| E-003 | 2026-11-14 13:00 | Javi | HistGB `recsys/train.py` (branch javi/v1-gbm-recommender) | same split, 250k sessions / 2.5M rows | 1,123 buying test sessions | item AUC 0.95 (mostly between-session); within-slate hit@1 0.49 / MRR 0.65 (slot=0) | Implemented as challenger `v1-gbm-cand`; live A/B pending |
| E-007a | 2026-11-14 13:10 | Javi | `recsys/live.py --dry-run` | live stream, no writes | 5×60 requests | age p50 0.6–0.7 s, p95 0.9–1.5 s, max 1.9 s | Latency OK for promotion |

## Champion promotion checklist

- [ ] Champion baseline stays runnable, rollback verified; only one live writer.
- [ ] Proposed change has reproducible experiment ID, owner, commit, data range, metric and sample sizes.
- [ ] Offline estimator assumptions documented (not just attractive number); results corroborated where possible.
- [ ] No leakage or invalid use of future events/catalog updates.
- [ ] Exactly ten unique active items, correct order and one submission/request on edge cases.
- [ ] p95/p99 end-to-end latency with buffer below 3 sec; fallback `late/invalid/missing` not worse.
- [ ] Cold-start, new product and stockout subsets checked.
- [ ] Human can explain effect and methodology to jury; `strategy.md`/`decisions.md` updated.

## Reusable experiment record

```markdown
### E-XXX — descriptive title
- **Date / owner / branch / commit:**
- **Comparison:** current champion vs challenger
- **Hypothesis / precise change:**
- **Data:** train/val/test start-end times (UTC), schema/feature as-of timestamps, request N, positive N
- **Metrics:** purchase proxy, IPS assumptions/ESS/CI if used, cold subset, CTR/revenue secondary
- **Integrity:** exact-ten/active/unique %, feedback fallbacks, E2E p50/p95/p99, errors
- **Results:** values and uncertainty (or NOT RUN)
- **Limitations:** bias, drift, missing counterfactuals
- **Decision / link to logs:**
```

Sources: https://datathon.rawtree.dev/ ; https://github.com/rawtreedb/datathon-fme-2026/blob/main/starter/offline_eval.ipynb
