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

## T-013 — home y usuarios nuevos (IDs E-13x; rama `javi/home-new-users`)

### E-130 — Score de home de 6 pesos: split temporal en histórico y transferencia a feedback en vivo
- **Date / owner / branch:** 2026-11-14 12:50 UTC · agente de Javi · `javi/home-new-users` · `python recsys/home_eval.py fit`
- **Comparison:** orden registrado / solo conversión orgánica del producto / score `home_cands` (logística: carrito, subcategoría comprada, cuota de categoría, usuario desconocido, log conv. orgánica, log popularidad, slot).
- **Data:** `history_sessions` página home, 400.549 sesiones × 10; features de usuario y producto acumuladas hasta el día anterior a cada sesión (`home_feats.py`, `merge_asof` sin coincidencias exactas); filas de productos ya comprados excluidas (I-130). Train < 2026-11-04 (3,26M filas), test ≥ 2026-11-04: 681.943 filas, **47 compras, 380 clics**.
- **Results (test, slot=0 al puntuar):** AUC por impresión compra 0,890 / clic 0,771. Dentro de la slate, compra hit@1 / MRR: aleatorio 0,04 / 0,28, orden registrado 0,34 / 0,53, conv. orgánica 0,43 / 0,63, score 0,43 / 0,61 (N=47). Clic: orden registrado 0,27 / 0,47, score 0,28 / 0,48 (N=380).
- **Transferencia a vivo (feedback servido por el equipo, sin comprados ni `recent_views`, features solo de histórico):** AUC de clic home 0,720 (16.857 filas, 36 clics, 7 compras; AUC compra 0,845), home conocidos 0,723, home nuevos 0,606, otras páginas 0,733 (70.367 filas, 245 clics, 78 compras; AUC compra 0,818). Referencias: el slot mostrado 0,66–0,70, solo conv. orgánica 0,57–0,65.
- **Limitations:** dentro de la slate histórica (una sola categoría) el score no mejora al ranking por conversión orgánica: su valor está en elegir candidatos entre categorías, que el histórico no permite medir por slate. N de compras pequeño (47 y 7). El AUC en vivo no usa el slot, pero las slates en vivo las eligió v1.
- **Decision:** pesos fijados en `home_cands.W`; candidato a variante `home` (D-130).

### E-131 — Feedback en vivo por relación previa usuario–producto
- **Date / owner:** 2026-11-14 12:41 UTC · agente de Javi · `python recsys/home_eval.py live` (solo lectura)
- **Data:** `team_26.feedback` con `served_by='team'` unido a `shop.requests`, 10.977 peticiones, 11:09–12:41 UTC; relación calculada con `history_events` completo.
- **Results:** tabla en I-130. Comprado 1 compra / 21.113 impresiones; visto sin carrito 0 / 9.734; carrito sin compra 29 / 9.293; sin relación 71 / 69.630.
- **Decision:** excluir comprados y vistos-sin-carrito del histórico (D-130).

### E-132 — Repetición de las peticiones home en vivo a través de `HomeCands` (estado solo de histórico) y comprobación en seco
- **Date / owner:** 2026-11-14 12:55 UTC · agente de Javi · `python recsys/home_eval.py slate` y `dry` (solo lectura, no escribe en `submissions`)
- **Data:** 3.200 peticiones home con feedback (2.246 de usuarios conocidos, 954 nuevos); objetivo proxy: compras ORGÁNICAS del mismo usuario en `shop.events` posteriores a la petición.
- **Results:** composición de lo mostrado en vivo a conocidos: 22,6% comprado, 13,8% visto sin carrito, 8,7% carrito pendiente; con `home_cands`: 0% / 0% / 54,1%. Peticiones cuyo usuario compra después orgánicamente (por primera vez) algo de la slate: conocidos **36 / 279 (12,9%)** frente a 6 / 279 (2,2%) de lo mostrado en vivo; nuevos 9 / 93 (9,7%) frente a 3 / 93 (3,2%).
- **Integrity / latency:** en seco sobre las últimas 2.000 peticiones home y el catálogo actual (5.100 productos, 37 no disponibles): 2.000 / 2.000 slates con 10 ids distintos y en stock; 0,11–0,16 ms por petición; construir el índice 7,7 s; `refresh` 0,02 s.
- **Limitations:** la compra orgánica no es la compra del carrusel (orgánicamente se recompra, en el carrusel no); N pequeño en nuevos (93). No hay medida del modelo oculto: falta el bloque de 10 min en el leaderboard.
- **Decision:** pedir prueba en vivo vía `policy.json` (D-130). No promovido.

### E-133 — D-130 `home` en vivo contra `lfm` en home (modelo oculto, `/api/state?by=model`)
- **Date / owner:** 2026-11-14 15:06–15:19 UTC · agente de Javi · writer único desde `main`, `policy.json` en `lfm` 100%, `d130.json` `{"mode": "home"}` (activado por el hilo de despliegue)
- **Comparison:** slates de home de `lfm` (14:33–15:00 UTC) frente a `HomeCands.slate()` (15:06–15:19 UTC). Conversión esperada del modelo oculto por versión, no compras realizadas.
- **Results:** home con usuario conocido: D-130 **0,459%** (339 peticiones) frente a lfm 0,520% (471); ingresos 0,16 frente a 0,28 € por petición. Home con usuario nuevo: D-130 1,104% (133) frente a lfm 0,973% (190); ingresos 0,25 frente a 1,02 €. Home combinado: 0,641% frente a 0,650%.
- **Limitations:** ventanas consecutivas, no simultáneas (cambia la mezcla de usuarios); 133–471 peticiones por brazo.
- **Decision:** **NO promover** D-130 `home`: no mejora a lfm en conocidos y pierde el desempate por ingresos; la ventaja en nuevos es pequeña y con N bajo. Recomendado volver a `off`. La hipótesis "carrito pendiente primero + categoría afín" (I-131) no sube home-conocidos por encima de ~0,5% en el modelo oculto: REJECTED como palanca grande. El hallazgo I-130 (no mostrar lo ya comprado) sigue en pie y ya lo aplican qrank/lfm.
