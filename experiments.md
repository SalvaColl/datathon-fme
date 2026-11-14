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
| E-090 | 2026-11-14 12:45 UTC | agente de Javi (T-009) | `recsys/cold_items.py eval`, rama javi/cold-items | (a) hold-out de productos 5 folds × 3 semillas, `history_events` 60 d; (b) lanzamiento real: ajuste con catálogo histórico, test con `shop.events` de los productos `new_product` | (a) 5.000 productos, 548.160 compras; (b) 100 productos, 12.109 vistas, 775 compras | Spearman con compras/vista: subcategoría 0,41 / sub+marca+precio 0,50 / kNN TF-IDF 0,60 / GLM de frases **0,84**; lanzamiento real 0,50 / 0,50 / 0,59 / **0,68** (techo de ruido 0,84) | Prior de frases adoptado en `cold_items`; TF-IDF inferior |
| E-091 | 2026-11-14 12:50 UTC | agente de Javi (T-009) | `recsys/ev_cold_launch.py`, modelo v1 del repo | lanzamientos simulados (20% del catálogo × 5 folds), priors con eventos <11 oct, features <15 oct, sesiones con compra ≥4 nov | 4.697 sesiones; 1.553 "cold" | hit@1 cuando se compra el lanzamiento: sin contadores 0,000 / prior subcategoría 0,004 / prior frases 0,133 / +1 h eventos 0,154 / oráculo 0,472; cold 0,227 → 0,402 → 0,442; coste en antiguos 0,517 → 0,503 | Proponer tabla extra de `cold_items` (D-090, parte A) |
| E-092 | 2026-11-14 13:00 UTC | agente de Javi (T-009) | `recsys/explore_attr_affinity.py slates` + reentreno de prueba (110k sesiones) | mismo split que E-003; afinidad con vistas <15 oct | 4.697 sesiones con compra | hit@1 / hit@3 / MRR: v1 0,472 / 0,755 / 0,644; v1 × exp(20·afinidad) **0,519 / 0,809 / 0,684**; β=40 0,519 / 0,816 / 0,686; GBM reentrenado con features de afinidad 0,495 / 0,808 / 0,671 (IC 95% hit@1 +0,012…+0,037 frente a mismas features sin afinidad) | Multiplicador sobre v1, sin reentrenar |
| E-093 | 2026-11-14 13:05 UTC | agente de Javi (T-009) | `recsys/explore_attr_affinity.py organic` y `live` | (a) orgánico: afinidad <15 oct, pares usuario–producto nuevos después; (b) `team_26.feedback` 11:09–13:05 UTC, afinidad solo con histórico | (a) 3,9M pares, 167.527 compras; (b) 21.691 peticiones, 84.388 impresiones en el segmento, 36 compras, 145 clics | (a) compras por vista 1,6% → 23,4% de afinidad <0,10 a >0,25; (b) compras por 10.000 impresiones 0,6 / 1,2 / 0,7 / 10,0 / 18,2 / 89,7 | Señal confirmada en vivo; falta leaderboard |
| E-094 | 2026-11-14 13:15 UTC | agente de Javi (T-009) | copia parcheada de `live.py` en dry-run (no escribe), `cold_items` + `attr_affinity` | peticiones en vivo, mismas peticiones para todas las variantes; conversión ESTIMADA con las tasas por celda de E-093 (no es el modelo oculto) | 789 peticiones | estimación por petición: v1 0,92% (leaderboard real 0,85%) / β=20 1,78% / **β=40 2,37%** / solo afinidad 3,53% (extrapola, optimista); productos con afinidad >0,20 por slate 0,6 → 2,1; latencia p50 0,8 s, p95 1,2–1,4 s, afinidad ~1 ms por petición; 3,5 productos "muertos" (I-130) por slate en todas | Pedir bloque en vivo con `aff` (D-090) |

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
