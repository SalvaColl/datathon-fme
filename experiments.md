# Experiment registry and champion-promotion protocol

This is a **ledger, not a claim that tests have run**. Initial pack had no results; E-010/E-011 below record team results on 2026-11-14. Keep real experiments here; raw logs and model files should live in versioned project paths / private RawTree.

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
| — | — | — | — | **No results entered yet** | — | — | Pending |

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

### E-010 — Legacy 10,000-impression league (superseded evaluation design)
- **Date / owner / evidence:** 2026-11-14 / team-provided results; OFFLINE ESTIMATE. Original random cached `data/local_eval/holdout.json` preserved.
- **Results:** baseline hit@10 0.3943 / SNIPS slot1 buy 0.0290 / ESS 414; same_category 0.7809 / 0.0109 / 1745.3469; same_subcategory 0.2835 / 0.0075 / 170.9576; mixed_category 0.7552 / 0.0075 / 170.9576.
- **OBSERVED DATA:** local inspection confirms all 10,000 legacy requests have no impression `ts`; all 10,000 same_subcategory/mixed_category first actions agree. Both prioritize the same highest-popularity subcategory product. Their later slots differ, explaining hit@10 differences without slot-1 differences.
- **Limitations:** random sampling was not reproducible after cache deletion; a two-way split cannot separate tuning from final testing; missing request timestamps prevent split/as-of verification. Historical selection/position bias, limited support and no uncertainty intervals remain. These are not full-slate conversion estimates. No promotion justified.

### E-011 — Chronological league v2 framework
- **Date / owner / task:** 2026-11-14 / Codex / T-013, salva/league branch, uncommitted working-tree changes. No serving code or dependencies changed.
- **OBSERVED DATA coverage (UTC):** history_sessions 2,000,000 rows, 2026-09-15 07:00:01.456 through 2026-11-14 06:59:59.207; history_events 11,996,560 rows, 2026-09-15 07:00:06.371 through 2026-11-14 07:08:13.507. Read-only aggregate queries verified before choosing boundaries.
- **Split:** overlapping range divided 70/15/15 by elapsed time. Half-open train [2026-09-15 07:00:06.371, 2026-10-27 07:00:01.356), validation [2026-10-27 07:00:01.356, 2026-11-05 07:00:00.281), final test [2026-11-05 07:00:00.281, 2026-11-14 06:59:59.208). 10,000 deterministic hash-sampled impressions per period; seed 20261114. All 10,000 legacy holdout IDs excluded from every period to avoid reusing already inspected rewards.
- **Reproducibility:** independent private JSON snapshots plus SHA256 manifest in `data/local_eval/league_v2`; immutable completed preparation. Training labels/popularity only from train interval. Validation/test labels and logged actions withheld from inference. Frozen source/config selection and one-time final-test access marker. Plugins are trusted code; external/transitive dependencies must be audited separately.
- **Catalogue:** 5,000 base products, all have created_at; zero timestamped catalogue updates in the historical range. Creation-time eligibility and available as-of full-state updates are supported. Initial base category/price/stock history is unavailable; historical eligibility remains conditional on the documented base-state assumption. No current merged catalogue is substituted. Unknown creation timestamps excluded. This limitation is not resolved by the new harness.
- **Integrity:** ten automated tests pass: split boundaries/duplicates, as-of changes and future products, invalid top-10, exceptions/invalid propensity, request label isolation, repeatable seeded intervals, training isolation, snapshot tampering, validation without a test file, and fail-closed final-test access. Test fixtures only open synthetic final data; real final test remains unscored.
- **Metrics:** clicked-item hit@10; unclipped slot-1 IPS/SNIPS click/buy; matches/ESS/max weight; paired hourly-block percentile bootstrap 95% intervals; exact-ten/unique/eligible output validity; local inference p50/p95/p99/max. Invalid output disqualifies comparison. Inference timing excludes catalog reconstruction, polling/network/writes and does not establish live E2E SLA.
- **Limits:** logged first-action support and correct propensity assumed; uncontrolled other-slot effects; clustered/repeated users across hours; approximate uncertainty; rare-outcome degeneracy; validation selection bias. Missing historical cold flags mean official cold-start score is not established. No estimate identifies hidden expected full-slate conversion.
- **Commands:** existing `C:\Projects\datathonFME\datathon-env\Scripts\python.exe` ran read-only coverage queries, `tools/local_league.py prepare --sample 10000`, `tools/local_league.py validation --bootstrap 500`, and `-m unittest discover -s tests -v`. Initial preparation exposed a RawTree DateTime64 timezone-literal incompatibility; SQL literals now use UTC millisecond strings, while manifest times retain UTC offsets. Nothing installed. Freeze/final-test evaluation deliberately NOT RUN.
- **Operation / rollback:** existing live champion untouched; no submission process started. No model promotion. Rollback consists of disregarding the offline framework; live writer needs no restart. See `tools/LEAGUE.md` for interface, plugin example and full commands.

#### E-011 initial validation results — OFFLINE ESTIMATE

10,000 validation impressions across 216 UTC-hour blocks; 500 paired seeded block-bootstrap replicates; zero malformed slot-1 propensities. All four policies returned valid reconstructed top-10 outputs on 100% of rows with no exceptions. Real final test remains unscored.

| Policy | hit@10 | SNIPS slot1 buy | Approx. 95% interval | Slot1 matches | ESS | Inference p95 / p99 (ms) |
|---|---:|---:|---|---:|---:|---|
| baseline | 0.3812 | 0.0296 | [0.0132, 0.0481] | 406 | 406.00 | 0.1215 / 0.4194 |
| same_category | 0.7572 | 0.0104 | [0.0063, 0.0147] | 2159 | 1687.16 | 0.1212 / 0.3716 |
| same_subcategory | 0.2689 | 0.0108 | [0.0041, 0.0196] | 825 | 97.93 | 0.1085 / 0.4101 |
| mixed_category | 0.7154 | 0.0108 | [0.0041, 0.0196] | 825 | 97.93 | 0.1165 / 0.3838 |

- **OBSERVED DATA:** subcategory/mixed first-slot agreement again 10,000/10,000. Match count alone is insufficient: those policies have 825 matches but only ~98 ESS because of unequal inverse weights.
- **Evidence:** private `data/local_eval/league_v2/validation_run1.json` and `validation_report.json` contain full IPS/SNIPS click/buy metrics, hit@10 and paired delta intervals, validity, maximum latency, source/snapshot fingerprints and prediction hashes. Point estimates differ from E-010 because these are a different verified chronological validation sample and training cutoff, with legacy IDs excluded.
- **Decision:** no challenger promotion; higher clicked-item coverage does not establish higher purchase performance. Even nominal paired first-slot intervals below baseline cannot establish actual full-slate conversion ranking. Training/tuning may continue on validation; final test must remain sealed until deliberate policy selection/freeze.
- **Performance implementation:** catalog replay and heuristic category indexes are cached by as-of catalogue revision; stock-change/backward-replay regression test passes. Two slow preliminary offline runs were stopped and replaced after profiling; no live process was stopped. Final suite: **10 tests passed**. No installation or serving dependency changes.

- **Repeatability (OBSERVED DATA):** two complete cached validation runs produced exactly identical predictions (SHA256), all point estimates, seeded intervals and source/snapshot fingerprints; latency measurements appropriately vary. Final-test access marker absent. Both script and module entry points use the same plugin registry.
