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
| E-001 (obs.) | 2026-11-14 12:45 | Javi (read-only) | team baseline writer | live feedback to 12:45 | 3,219 | realized conv 0.62%, CTR 2.5%; ~30% `missing` in last 10 min | Baseline recorded; writer loses requests |
| E-002 | 2026-11-14 13:00 | Javi | heuristics, `recsys/ev.py` | train sessions <2026-11-04, test ≥2026-11-04 (user feats from <2026-10-15) | 1,123 buying test sessions | within-slate hit@1 / MRR: random 0.10/0.30, logged order 0.31/0.51, viewed+sub+cr 0.35/0.54, +user cart 0.51/0.67 | Heuristics beat logged order |
| E-003 | 2026-11-14 13:00 | Javi | HistGB `recsys/train.py` (branch javi/v1-gbm-recommender) | same split, 250k sessions / 2.5M rows | 1,123 buying test sessions | item AUC 0.95 (mostly between-session); within-slate hit@1 0.49 / MRR 0.65 (slot=0) | Implemented as challenger `v1-gbm-cand`; live A/B pending |
| E-007a | 2026-11-14 13:10 | Javi | `recsys/live.py --dry-run` | live stream, no writes | 5×60 requests | age p50 0.6–0.7 s, p95 0.9–1.5 s, max 1.9 s | Latency OK for promotion |
| E-081 | 2026-11-14 14:15 | Javi (agente) | `recsys/qrank.py`, `qrank_build.py`, `qrank_eval.py`, artefacto `recsys/data/qrank.joblib`; rama javi/rv-first-slate | Calidad q por producto con impresiones no vistas < 25 oct (10,4M impresiones, 15.198 compras); modelo de contexto (HistGB, 11 features) entrenado 25 oct–7 nov, test 8–14 nov. En vivo: feedback de v1 12:01–13:02 UTC, solo lectura. OFFLINE ESTIMATE + LIVE FEEDBACK | Test histórico 1.708.000 impresiones / 3.013 compras; chequeo de política 4.000 sesiones; en vivo 6.266 peticiones / 84 compras | Histórico: AUC 0,865, log-loss 0,01079 vs 0,01295 constante, calibrado por tramos (tramo alto 11,4% predicho vs 13,3% observado; vistos slot 1 7,0% vs 7,0%). Política en histórico (por modelo): slates logueados 1,75% (real 1,88%) vs qrank 3,93%. En vivo: el modelo predice 1,81% para los slates de v1 (real 1,34%); ratio real/modelo 0,35 en vistos y 0,80 en no vistos. qrank en las mismas peticiones: 3,43% sin corregir, **2,15% con los ratios en vivo** (1,96% si el ratio de vistos fuera 0,20). Experimento natural: cuando el slot 1 de v1 coincide con el de qrank la petición convierte 2,61% (24/918) vs 1,12% (60/5.348); por solape de slates 0,65% / 1,03% / 1,72% / 2,23%. Validez 100% (10 ids distintos, en stock, no comprados) en 6.266; 10 ms por lote de 8 | **Candidato a promoción con A/B en vivo** (D-081). Estimación por modelo, no medida del modelo oculto |
| E-090 | 2026-11-14 12:45 UTC | agente de Javi (T-009) | `recsys/cold_items.py eval`, rama javi/cold-items | (a) hold-out de productos 5 folds × 3 semillas, `history_events` 60 d; (b) lanzamiento real: ajuste con catálogo histórico, test con `shop.events` de los productos `new_product` | (a) 5.000 productos, 548.160 compras; (b) 100 productos, 12.109 vistas, 775 compras | Spearman con compras/vista: subcategoría 0,41 / sub+marca+precio 0,50 / kNN TF-IDF 0,60 / GLM de frases **0,84**; lanzamiento real 0,50 / 0,50 / 0,59 / **0,68** (techo de ruido 0,84) | Prior de frases adoptado en `cold_items`; TF-IDF inferior |
| E-091 | 2026-11-14 12:50 UTC | agente de Javi (T-009) | `recsys/ev_cold_launch.py`, modelo v1 del repo | lanzamientos simulados (20% del catálogo × 5 folds), priors con eventos <11 oct, features <15 oct, sesiones con compra ≥4 nov | 4.697 sesiones; 1.553 "cold" | hit@1 cuando se compra el lanzamiento: sin contadores 0,000 / prior subcategoría 0,004 / prior frases 0,133 / +1 h eventos 0,154 / oráculo 0,472; cold 0,227 → 0,402 → 0,442; coste en antiguos 0,517 → 0,503 | Proponer tabla extra de `cold_items` (D-090, parte A) |
| E-092 | 2026-11-14 13:00 UTC | agente de Javi (T-009) | `recsys/explore_attr_affinity.py slates` + reentreno de prueba (110k sesiones) | mismo split que E-003; afinidad con vistas <15 oct | 4.697 sesiones con compra | hit@1 / hit@3 / MRR: v1 0,472 / 0,755 / 0,644; v1 × exp(20·afinidad) **0,519 / 0,809 / 0,684**; β=40 0,519 / 0,816 / 0,686; GBM reentrenado con features de afinidad 0,495 / 0,808 / 0,671 (IC 95% hit@1 +0,012…+0,037 frente a mismas features sin afinidad) | Multiplicador sobre v1, sin reentrenar |
| E-093 | 2026-11-14 13:05 UTC | agente de Javi (T-009) | `recsys/explore_attr_affinity.py organic` y `live` | (a) orgánico: afinidad <15 oct, pares usuario–producto nuevos después; (b) `team_26.feedback` 11:09–13:05 UTC, afinidad solo con histórico | (a) 3,9M pares, 167.527 compras; (b) 21.691 peticiones, 84.388 impresiones en el segmento, 36 compras, 145 clics | (a) compras por vista 1,6% → 23,4% de afinidad <0,10 a >0,25; (b) compras por 10.000 impresiones 0,6 / 1,2 / 0,7 / 10,0 / 18,2 / 89,7 | Señal confirmada en vivo; falta leaderboard |
| E-094 | 2026-11-14 13:08 UTC | agente de Javi (T-009) | copia parcheada de `live.py` en dry-run (no escribe), `cold_items` + `attr_affinity` | peticiones en vivo, mismas peticiones para todas las variantes; conversión ESTIMADA con las tasas por celda de E-093 (no es el modelo oculto) | 789 peticiones | estimación por petición: v1 0,92% (leaderboard real 0,85%) / β=20 1,78% / **β=40 2,37%** / solo afinidad 3,53% (extrapola, optimista); productos con afinidad >0,20 por slate 0,6 → 2,1; latencia p50 0,8 s, p95 1,2–1,4 s, afinidad ~1 ms por petición; 3,5 productos "muertos" (I-130) por slate en todas | Pedir bloque en vivo con `aff` (D-090) |
| E-095 | 2026-11-14 13:19 UTC | agente de Javi (T-009) | `live.py` de `javi/qrank-serving` + `recsys/aff_live.patch`, en copia aparte, sin escribir | peticiones en vivo; cada lote puntuado con las 7 variantes | 448 peticiones | slates válidos (10 distintos y activos) 100% en las 7 variantes; `predict` por lote p50 49 ms v1 / 54 ms `aff` / 6 ms `qrank` / 7 ms `qrank_aff`; productos con afinidad >0,20 por slate: v1 0,77, `aff` 2,21, `qrank` 0,49, `qrank_aff` 1,69; suite de tests 40/40 | Parche listo; falta aplicarlo y el bloque en vivo |
| E-160 | 2026-11-14 13:40 UTC | agente de Javi (T-016) | `recsys/night_lab.py`, `tests/test_night_lab.py`, rama javi/night-lab | (a) leaderboard público `/api/state`; (b) leaderboard simulado (media móvil de 60 min, recalculada cada minuto, baseline con deriva) que lee los mismos `policy.json`/`d130.json` que escribe el laboratorio; (c) dry-run real | (a) 9 snapshots; (b) 11 tests; (c) 2 bloques de 3 min, 6 snapshots | (a) cadencia 60 s, ventana 3600 s exactos (I-160). (b) con bloques de 65 min la lectura directa recupera el lift de cada brazo con error < 1e-6 pese a la deriva; la guardia aborta un brazo con on_time 40% o lift 0,05 en menos de 16 min, vuelve al mejor brazo y no lo repite; al terminar restaura los JSON originales; solo escribe sus logs y esos dos JSON. Con bloques de 30 min el ajuste por mínimos cuadrados recupera el lift con error < 0,03 SOLO con tráfico estable. (c) lee y registra bien; en dry-run no escribe nada | Herramienta lista; NO arrancada. Ninguna medida de variantes todavía: el resultado de la noche irá en una fila nueva. `python -m unittest tests.test_night_lab`: 11 OK |

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

### E-REL-001 — v1-gbm-cand reliability investigation and patch
- **Date / owner / branch:** 2026-11-14 / Codex / `salva/serving-reliability`, task T-014. Source reviewed: Javi's `5541d74`; isolated code fix `7176c03`. User reports Javi owns the actual laptop process. No live process controlled here.
- **USER-REPORTED LIVE FEEDBACK:** leaderboard fourth; conversion 0.8284%, cold start 1.4264%, on-time 76.0%, EUR/request 0.290. Row time/window unknown; do not compare it directly to a later short feedback window or claim causality.
- **OBSERVED DATA (read-only team_26 queries):** first last-hour query: team 8,835, fallback/missing 1,934, fallback/invalid 30; accepted-answer p50 1,414ms, p95 2,420ms. A subsequent 60-minute audit: team 8,874, missing 1,896, invalid 30. There were 1,060 successfully served request IDs with multiple submissions, and submitted versions included baseline (4,243 rows), v1-gbm-cand (7,037), guard (51). Of the 1,896 missing-feedback IDs, 1,367 nevertheless have a submission row and 529 do not. Thus missing feedback does NOT prove that no POST happened; submission presence does not prove timely arrival either.
- **OBSERVED DATA time slices (UTC):** missing counts in 11:40, 11:45, 11:50 and 11:55 five-minute buckets were 349 (partial bucket), 318, 819 and 400. By contrast, the subsequent 30-minute audit had team 5,363, missing 10, invalid 28: 99.30% successfully served. All recent feedback IDs had exactly one submission. Accepted-answer five-minute p95 roughly 2.05–2.28s and p99 roughly 2.52–2.79s. These describe the existing deployed process, not our patch.
- **Interpretation:** much of the bad rolling-hour reliability comes from an earlier disruption/overlap, consistent with Javi's branch note about simultaneous baseline/GBM writers. Current 24% ongoing failure is not established. Duplicate writer identity, Javi's network/clock/CPU behavior and exact failure causes need his host logs; no causal attribution of every miss is possible from feedback alone. Invalid feedback latency in this sample was >3.2s, so do not assume all invalid rows were caused by stock.
- **Code issues confirmed by inspection:** guard answers queued behind younger model inference; one mutable Session shared across threads; requests marked seen before success; blind retry after ambiguous POST; 20s stock refresh plus no final eligibility recheck; expensive catalogue reindex per candidate; global catalogue race; unknown last-view ID can abort candidate construction. Published cold-items/home-new-users/live-trends branches differ from GBM only by task claims at fetched tips; unpushed work is unknown. Home T-013 conflicts with league T-013 numbering and needs team reconciliation, not an assumption of shared ownership.
- **Implemented:** urgent-first small-batch scheduling, bounded polling + reduced idle tax, durable at-most-once journal/local writer lock/startup reconciliation, no blind timeout retries, pinned feature snapshot and synchronized live lookups, independent fast stock checks/final eligible-ten repair, safe unknown views, early historical-feature startup, thread-local HTTP sessions, per-stage JSON timing logs. Policy version label is `v1-gbm-cand-r1`; trained model binary and feature definitions were not changed. No new dependencies installed.
- **ENGINEERING BENCHMARK:** synthetic count features with real catalogue, two requests / 400 candidate rows, 20 repetitions. All 31 feature columns equal to original `fe.py` on the same fixture. Original feature construction p50/p95/p99 = 294.96/810.83/1852.21ms; fixed = 86.81/98.76/99.47ms. Sequential measurements on this Windows machine, small N; exclude model inference, polling, network, journal and submission. Not an E2E SLA measurement or purchase uplift estimate.
- **Read-only poll probe:** eight original request queries from fresh HTTP connections: median 1.107s, max 2.275s (range 0.814–2.275). Rejected proposed 1s read timeout; final setting connect 0.5s/read 2s. Javi's persistent-session timings may differ.
- **Verification commands/results:** existing `C:\Projects\datathonFME\datathon-env\Scripts\python.exe -m unittest discover -s tests -v`: 21 tests pass. `tools/reliability_audit.py --minutes 30/60 --output data/local_eval/reliability_audit*.json`: successful read-only queries. Local feature equivalence/timing script produced `data/local_eval/reliability_feature_benchmark.json`; poll probe produced `reliability_poll_timing.json`. Full live/model dry-run NOT RUN: this checkout lacks Javi's ignored user-item history artifact. No final-test access or training experiment performed.
- **Risks / rollout / rollback:** patch not deployed, so post-fix on-time/p95/p99 are UNTESTED. New transport scheduling, SQLite disk I/O and short timeouts need Javi's host rehearsal. Timeout claims sacrifice automatic recovery for nonduplication; a claim-before-POST crash can lose a request. Local lock does not coordinate different hosts or old scripts. Stock freshness still depends on the network. Javi should apply only `7176c03`, test, then control exactly one writer during handoff; see `recsys/README.md`. Preserve old checkout/model and journal for rollback. No shared starter change and no stopping/starting of serving processes here.
- **Statistical limitation:** expected leaderboard conversion is lower-noise than realized purchases, but overlapping rolling aggregates are not an identified causal A/B trial. Differences of rolling means alone do not recover unique 10-minute blocks without initial block information/denominators, and policy allocation/time drift/fallbacks confound comparison. Never present this transport benchmark as full-slate conversion evidence.
