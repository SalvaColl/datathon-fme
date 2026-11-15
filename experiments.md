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
| E-080 | 2026-11-14 13:50 | Javi (agente) | `recsys/trends.py` + `recsys/trends_replay.py`, rama javi/live-trends | Replay sobre `shop.events` 09:00–12:35 UTC en pasos de 5 min; features solo con eventos anteriores a cada paso; objetivo = compras orgánicas de los 15 min siguientes. OFFLINE ESTIMATE, sin escribir submissions | 873k eventos, 32 pasos × 89 subcategorías = 2.848 filas, 86.721 compras futuras; 39.350 peticiones en la parte C | Marcadas calientes 15 filas (2 episodios: Aquariums, Kettles): vistas siguientes ×2,69 de lo esperado, compras ×4,19, compra/vista ×1,66 (no calientes: ×0,99). Deviance Poisson de compras por subcategoría: estática 9.593 → multiplicador por defecto (√lift, tope 3) 8.602 (−10,3%), lift completo 7.840 (−18,3%), lift² 11.567 (+20,6%, peor); mejora en las dos mitades del día. Lift por producto dentro de la subcategoría: sin ganancia. Detección 5 min después del inicio; la marca sobrevive ~10 min al final. No-espectadores que compran la subcategoría caliente en 10 min: 14/13.063 vs 6/43.739 (×7,8, p=1e-5). Consulta+cálculo 1,7 s (hilo de refresco, fuera del camino de la petición) | Señal real pero N=2 episodios y objetivo orgánico; **no promover sin A/B en vivo** (D-080). Re-ejecutar con más episodios |
| E-081 | 2026-11-14 14:15 | Javi (agente) | `recsys/qrank.py`, `qrank_build.py`, `qrank_eval.py`, artefacto `recsys/data/qrank.joblib`; rama javi/rv-first-slate | Calidad q por producto con impresiones no vistas < 25 oct (10,4M impresiones, 15.198 compras); modelo de contexto (HistGB, 11 features) entrenado 25 oct–7 nov, test 8–14 nov. En vivo: feedback de v1 12:01–13:02 UTC, solo lectura. OFFLINE ESTIMATE + LIVE FEEDBACK | Test histórico 1.708.000 impresiones / 3.013 compras; chequeo de política 4.000 sesiones; en vivo 6.266 peticiones / 84 compras | Histórico: AUC 0,865, log-loss 0,01079 vs 0,01295 constante, calibrado por tramos (tramo alto 11,4% predicho vs 13,3% observado; vistos slot 1 7,0% vs 7,0%). Política en histórico (por modelo): slates logueados 1,75% (real 1,88%) vs qrank 3,93%. En vivo: el modelo predice 1,81% para los slates de v1 (real 1,34%); ratio real/modelo 0,35 en vistos y 0,80 en no vistos. qrank en las mismas peticiones: 3,43% sin corregir, **2,15% con los ratios en vivo** (1,96% si el ratio de vistos fuera 0,20). Experimento natural: cuando el slot 1 de v1 coincide con el de qrank la petición convierte 2,61% (24/918) vs 1,12% (60/5.348); por solape de slates 0,65% / 1,03% / 1,72% / 2,23%. Validez 100% (10 ids distintos, en stock, no comprados) en 6.266; 10 ms por lote de 8 | **Candidato a promoción con A/B en vivo** (D-081). Estimación por modelo, no medida del modelo oculto |
| E-090 | 2026-11-14 12:45 UTC | agente de Javi (T-009) | `recsys/cold_items.py eval`, rama javi/cold-items | (a) hold-out de productos 5 folds × 3 semillas, `history_events` 60 d; (b) lanzamiento real: ajuste con catálogo histórico, test con `shop.events` de los productos `new_product` | (a) 5.000 productos, 548.160 compras; (b) 100 productos, 12.109 vistas, 775 compras | Spearman con compras/vista: subcategoría 0,41 / sub+marca+precio 0,50 / kNN TF-IDF 0,60 / GLM de frases **0,84**; lanzamiento real 0,50 / 0,50 / 0,59 / **0,68** (techo de ruido 0,84) | Prior de frases adoptado en `cold_items`; TF-IDF inferior |
| E-091 | 2026-11-14 12:50 UTC | agente de Javi (T-009) | `recsys/ev_cold_launch.py`, modelo v1 del repo | lanzamientos simulados (20% del catálogo × 5 folds), priors con eventos <11 oct, features <15 oct, sesiones con compra ≥4 nov | 4.697 sesiones; 1.553 "cold" | hit@1 cuando se compra el lanzamiento: sin contadores 0,000 / prior subcategoría 0,004 / prior frases 0,133 / +1 h eventos 0,154 / oráculo 0,472; cold 0,227 → 0,402 → 0,442; coste en antiguos 0,517 → 0,503 | Proponer tabla extra de `cold_items` (D-090, parte A) |
| E-092 | 2026-11-14 13:00 UTC | agente de Javi (T-009) | `recsys/explore_attr_affinity.py slates` + reentreno de prueba (110k sesiones) | mismo split que E-003; afinidad con vistas <15 oct | 4.697 sesiones con compra | hit@1 / hit@3 / MRR: v1 0,472 / 0,755 / 0,644; v1 × exp(20·afinidad) **0,519 / 0,809 / 0,684**; β=40 0,519 / 0,816 / 0,686; GBM reentrenado con features de afinidad 0,495 / 0,808 / 0,671 (IC 95% hit@1 +0,012…+0,037 frente a mismas features sin afinidad) | Multiplicador sobre v1, sin reentrenar |
| E-093 | 2026-11-14 13:05 UTC | agente de Javi (T-009) | `recsys/explore_attr_affinity.py organic` y `live` | (a) orgánico: afinidad <15 oct, pares usuario–producto nuevos después; (b) `team_26.feedback` 11:09–13:05 UTC, afinidad solo con histórico | (a) 3,9M pares, 167.527 compras; (b) 21.691 peticiones, 84.388 impresiones en el segmento, 36 compras, 145 clics | (a) compras por vista 1,6% → 23,4% de afinidad <0,10 a >0,25; (b) compras por 10.000 impresiones 0,6 / 1,2 / 0,7 / 10,0 / 18,2 / 89,7 | Señal confirmada en vivo; falta leaderboard |
| E-094 | 2026-11-14 13:08 UTC | agente de Javi (T-009) | copia parcheada de `live.py` en dry-run (no escribe), `cold_items` + `attr_affinity` | peticiones en vivo, mismas peticiones para todas las variantes; conversión ESTIMADA con las tasas por celda de E-093 (no es el modelo oculto) | 789 peticiones | estimación por petición: v1 0,92% (leaderboard real 0,85%) / β=20 1,78% / **β=40 2,37%** / solo afinidad 3,53% (extrapola, optimista); productos con afinidad >0,20 por slate 0,6 → 2,1; latencia p50 0,8 s, p95 1,2–1,4 s, afinidad ~1 ms por petición; 3,5 productos "muertos" (I-130) por slate en todas | Pedir bloque en vivo con `aff` (D-090) |
| E-095 | 2026-11-14 13:19 UTC | agente de Javi (T-009) | `live.py` de `javi/qrank-serving` + `recsys/aff_live.patch`, en copia aparte, sin escribir | peticiones en vivo; cada lote puntuado con las 7 variantes | 448 peticiones | slates válidos (10 distintos y activos) 100% en las 7 variantes; `predict` por lote p50 49 ms v1 / 54 ms `aff` / 6 ms `qrank` / 7 ms `qrank_aff`; productos con afinidad >0,20 por slate: v1 0,77, `aff` 2,21, `qrank` 0,49, `qrank_aff` 1,69; suite de tests 40/40 | Parche listo; falta aplicarlo y el bloque en vivo |
| E-160 | 2026-11-14 13:40 UTC | agente de Javi (T-016) | `recsys/night_lab.py`, `tests/test_night_lab.py`, rama javi/night-lab | (a) leaderboard público `/api/state`; (b) leaderboard simulado (media móvil de 60 min, recalculada cada minuto, baseline con deriva) que lee los mismos `policy.json`/`d130.json` que escribe el laboratorio; (c) dry-run real | (a) 9 snapshots; (b) 11 tests; (c) 2 bloques de 3 min, 6 snapshots | (a) cadencia 60 s, ventana 3600 s exactos (I-160). (b) con bloques de 65 min la lectura directa recupera el lift de cada brazo con error < 1e-6 pese a la deriva; la guardia aborta un brazo con on_time 40% o lift 0,05 en menos de 16 min, vuelve al mejor brazo y no lo repite; al terminar restaura los JSON originales; solo escribe sus logs y esos dos JSON. Con bloques de 30 min el ajuste por mínimos cuadrados recupera el lift con error < 0,03 SOLO con tráfico estable. (c) lee y registra bien; en dry-run no escribe nada | Herramienta lista; NO arrancada. Ninguna medida de variantes todavía: el resultado de la noche irá en una fila nueva. `python -m unittest tests.test_night_lab`: 11 OK |
| E-180 | 2026-11-14 14:20 UTC | Javi (agente), T-018 | `recsys/live_quality.py` + `live_quality_replay.py`, rama `javi/live-quality` | `shop.events` 14 nov 09:00–13:50 UTC en cubos de 5 min; cada 15 min, features solo del pasado, objetivo = compras de los 15 min siguientes dadas las vistas; hiperparámetros elegidos en la 1.ª mitad, resultado en la 2.ª | test: 24.646 compras / 466 k vistas | Log-verosimilitud Poisson frente a calidad estática, nats por 1.000 compras (test): productos antiguos en calma +0,6 (N 22.731); subcategoría caliente +312, calibración 0,42 → 0,97 (N 393); productos nuevos +92, calibración 0,88 → 0,97 (N 665); en descuento +9 (N 894); total +8,4. Multiplicador de subcategoría sin puerta: −3,6 en calma | OFFLINE ESTIMATE. El stream aporta en nuevos, ráfagas y descuentos; nada en el resto (I-180, I-181) |
| E-181 | 2026-11-14 14:20 UTC | Javi (agente), T-018 | `live_quality_replay.py` | Productos con `price_change`, eventos orgánicos con precio ≤ 95% del catálogo frente a la tasa histórica del mismo producto | 1.247 productos, 52.658 vistas en descuento | 1.764 compras frente a 1.541 esperadas: ×1,145 (z 5,7). Mismos productos a precio normal ×1,016; nunca descontados ×1,021 | OBSERVED DATA. Factor fijo 1,145 en `live_rate`; no se aplica a q por defecto (I-182) |
| E-182 | 2026-11-14 14:20 UTC | Javi (agente), T-018 | `live_quality_replay.py`, `data/qrank.joblib` | q de qrank frente a tasa orgánica en 5.000 productos; después cada producto tratado como nuevo (prior de atributos en 5 folds sin él + solo eventos en vivo) | 5.000 productos | log q = a_sub + 2,02·log tasa, r 0,937. Calidad del top-10 por categoría capturada: mediana de subcategoría (qrank hoy) 10%; prior de atributos 60%; + 1 h de stream 77%; + 2 h 82%; + 4 h 84%. En 6.000 peticiones reales: cambia el 31,6% de los slates, el 4,7% del slot 1; impresiones a productos nuevos 0,03% → 3,1% | OFFLINE ESTIMATE; efecto en el modelo oculto UNTESTED (I-183) |
| E-183 | 2026-11-14 14:20 UTC | Javi (agente), T-018 | `live_quality_replay.py` | `team_26.feedback` 11:40–13:50 UTC | 28.826 peticiones, 288 k impresiones, 248 compras | Productos nuevos 611 impresiones / 2 compras; subcategorías calientes 258 / 0 | LIVE FEEDBACK sin potencia; hace falta A/B (I-184) |
| E-170 | 2026-11-14 14:45 UTC | agente de Javi (T-017) | `recsys/attr_model_build.py`, artefacto `recsys/data/attr_model.joblib`; rama javi/attr-model | Calidad por atributos ajustada con eventos orgánicos y carrusel < 25 oct; evaluada contra compras del carrusel 25 oct–14 nov (impresiones no vistas, corregidas por slot). 20% del catálogo oculto en todos los ajustes ("productos nuevos", semilla 0) | 5.000 productos; 903 nuevos simulados con exposición (1.397 compras), 3.455 conocidos (6.469 compras) | OFFLINE ESTIMATE. Devianza explicada, nuevos simulados: categoría 0,471 / **atributos 0,662** / con sus conteos 0,895. Conocidos: 0,477 / 0,725 / 0,928. Fórmula desplegada: exp(categoría + 1,04·prior conversión + 0,71·popularidad + 0,02·residuo conversión). Prior de popularidad por atributos probado y rechazado (0,608 en nuevos) | Calidad por atributos adoptada en `attr_model`; I-170, I-172 |
| E-171 | 2026-11-14 14:45 UTC | agente de Javi (T-017) | mismo script; HistGB con 13 features (las 11 de qrank + frases compartidas con la última vista + reparto de frases de la sesión), calidad de E-170 | Entrenamiento con el carrusel aleatorizado 25 oct–7 nov, test 8–14 nov; el modelo no lee user_id ni historial. Ranking dentro del slate mostrado, slot neutralizado | 170.800 sesiones de test, 3.013 con compra (529 con compra de un producto "nuevo") | OFFLINE ESTIMATE. AUC 0,882, log-loss 0,01052 (constante 0,01295). hit@1 / hit@3 / MRR: `attr_model` todo conocido 0,436 / 0,756 / 0,621; qrank (calidad por ID) 0,430 / 0,748 / 0,616; sin las 2 features de frases 0,430 / 0,736 / 0,611. Con 20% de productos nuevos: `attr_model` 0,441 global y **0,293** cuando lo comprado es nuevo; qrank 0,418 y **0,002**. Todo el catálogo sin conteos: 0,346. Sesgo: solo ordena dentro de slates de best-sellers | Empate con qrank en conocidos, ventaja clara en nuevos; I-170 |
| E-172 | 2026-11-14 15:00 UTC | agente de Javi (T-017) | `recsys/attr_model_eval.py` (solo lectura), `attr_model` en frío (sin conteos en vivo) frente a `qrank.joblib` y a los multiplicadores de `attr_affinity` | Feedback en vivo de team_26 (servido por el writer y por el fallback), páginas product/category, 11:09–13:35 UTC; impresiones elegibles = misma categoría que la última vista y no compradas | 21.046 peticiones, 205 compras; 75.697 impresiones elegibles, 131 compras, 372 clics | LIVE FEEDBACK. AUC compra 0,831 vs qrank 0,787 (dif. +0,046, IC 95% 0,021…0,069); clic 0,748 vs 0,721. Dentro de la petición: log-verosimilitud −1,435 vs −1,515, hit@1 0,481 vs 0,504, clics 0,401 vs 0,446. Sin historial (71 compras): qrank 0,507, qrank×exp(40·afinidad) 0,408, `attr` 0,465. Con historial (60 compras): 0,500 / 0,567 / `attr_aff` 0,550. Calibración: el modelo del histórico predice 1,7× de más; factor de vistos 0,66 (IC 90% 0,46–1,44). Otra categoría sin ver: 5,2 compras por 10.000 impresiones (N=132.001) frente a 13,9 en la misma (N=72.873); ya comprado: 1 compra en 2.245. Slates: 3.007 de 3.007 válidos, 11 ms por lote de 4 (p95 14 ms), 5,7 de 10 productos en común con qrank, 0,09 productos lanzados hoy por slate (qrank 0,00) | No promocionar sin bloque de leaderboard; I-170, I-171 |
| E-173 | 2026-11-14 15:05 UTC | agente de Javi (T-017) | `recsys/live.py` de la rama con `--dry-run --ab-attr-aff` (no reclama journal ni escribe) | Peticiones en vivo durante 110 s, contenedor en la nube | 86 peticiones: 30 `v3-attr-aff-r1`, 29 `v2-qrank-aff-r1`, 27 `v1-aff-r1` (20 home, 7 sin slate de ranker) | 0 slates inválidos (10 distintos y activos); `predict` por lote p50 8 ms, p95 86 ms. `attr_aff`: 99% misma categoría, 0,27 productos lanzados hoy por slate (qrank_aff 0,03), última vista en el slate 23% (qrank_aff 21%). 80 tests pasan | Listo para un bloque en el writer único; desplegar lo decide su dueño |

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

### E-180 — lfm: modelo ajustado con el feedback de hoy, validación con corte temporal
- **Date / owner / branch:** 2026-11-14 14:30 UTC / Javi (agente) / `javi/lfm-live-fit`, T-018. Solo lectura en RawTree; ningún envío.
- **Datos:** `team_26.feedback` 11:09–14:13 UTC unido a `shop.requests`, `shop.events` y catálogo: 31.776 peticiones, 317.760 impresiones, 285 compras, 935 clics. Estado de cada usuario reconstruido con lo anterior a cada petición.
- **Impresiones muertas (ya comprado, o visto en el histórico sin carrito):** 81.550 (26%) con 8 compras. Se excluyen del ajuste y nunca se sirven.
- **Modelo:** regresión logística de 11 pesos (`lfm.FEATS`), una para usuarios que vuelven y otra para nuevos; etiqueta = clic con las compras pesando ×3; `log(slot)` solo en el ajuste. Pesos en `recsys/lfm_coef.json`.
- **Hold-out (ajuste antes de 13:13 UTC, prueba después; 9.533 peticiones):** AUC de compra por impresión 0,910 (vuelve, 37 compras) y 0,862 (nuevo, 63 compras). Calibración: 43,5 compras predichas vs 37 reales y 53,0 vs 63.
- **OFFLINE ESTIMATE del valor (4.000 peticiones del hold-out, compras esperadas por 100 peticiones según el propio modelo):**

| Segmento | Peso | Real | Modelo sobre lo servido | Modelo sobre el slate de lfm |
|---|---:|---:|---:|---:|
| Vuelve, producto/categoría | 57% | 0,92 | 0,74 | 2,75 |
| Vuelve, home | 13% | 0,00 | 0,20 | 1,14 |
| Nuevo, producto/categoría | 24% | 2,37 | 2,27 | 5,07 |
| Nuevo, home | 6% | 1,24 | 0,52 | 0,82 |
| **Total** | | **1,18** | **1,03** | **2,99** |

- **Limitación:** la última columna es el modelo puntuando su propia elección (optimista) y suma probabilidades por slot aunque solo hay una compra por petición; el slate de lfm comparte solo 1,8 de 10 productos con lo servido, así que extrapola. Descontando la mitad de la mejora quedaría en torno al 2,0%. La medida válida es la fila por versión del leaderboard (I-182).
- **Dry-run real sin escribir (14:45 UTC, 329 peticiones del stream):** 0 slates inválidos, 1,6 ms por petición (p95 2,7 ms). Composición media del slate de un usuario que vuelve en producto/categoría: 3,1 carritos del histórico, 0,3 carritos de hoy, 0,25 vistos, 3,2 de la misma categoría y 3,1 de otra categoría por afinidad.
- **Comandos:** `python recsys/lfm_build.py --pull` (47 s); `python -m unittest discover -s tests` → 77 tests OK.
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

## T-020 — pruebas baratas sobre el feedback en vivo (2026-11-14 15:00 UTC, Javi (agente), solo lectura)

Datos comunes: `team_26.feedback` 11:09–14:38 UTC unido a `shop.requests` y `shop.events`: **37.601 peticiones, 376.010 impresiones, 344 compras, 1.132 clics**; 282.386 impresiones "vivas" (333 compras) tras quitar las muertas. "Esperado" = probabilidad de lfm (E-180, reajustado con estos datos) para esa impresión y ese slot. Features solo con eventos anteriores a cada petición. Hold-out: ajuste antes de 13:36 UTC, prueba después (50.349 impresiones / 54 compras en usuarios que vuelven; 33.448 / 68 en nuevos). Comandos: `python lfm_build.py --pull --no-write`, `python explore_t020.py --pull`, `python explore_t020_session.py`, `python explore_t020_segment.py`. LIVE FEEDBACK salvo donde se indica.

| ID | Pregunta | N | Resultado | Decisión |
|---|---|---|---|---|
| E-200 | ¿Vende más un carrito reciente o repetido? | 2.172 impresiones de carrito de hoy, 29 compras | Usuario nuevo, compras por 10.000 según minutos desde el carrito: <10 min 0 (0/47), 10–30 min 274 (2/73), 30–60 min 109 (1/92), >60 min 319 (21/659). Carrito repetido: 278 (1/36) frente a 275 (23/835). Hold-out: log-verosimilitud de clic −971,8 → −971,7. Por slot (nuevo): slot 1 468 (17/363), slots 2–3 246 (5/203), slots 4–10 66 (2/305) | REJECTED (R-12). Confirma I-181: el carrito va en los slots 1–3 |
| E-201 | ¿Lo visto antes hoy, fuera de `recent_views` y sin carrito, está vivo? | 2.330 impresiones, 3 compras | 9,1 y 16,3 compras por 10.000 (vuelve / nuevo) frente a 3,8 y 11,3; observado/esperado 1,73 y 1,60. Peso en hold-out −0,03 (nuevo) | REJECTED como feature (R-16); no se filtra |
| E-202 | ¿Qué pasa cuando el comprador ya ha comprado hoy? | 30.241 peticiones fuera de home | Conversión por compras previas de hoy, usuario nuevo: 0,85% / 1,73% / 3,82% / 9,46% (N 5.666 / 2.081 / 785 / 560). Vuelve: 0,56% / 0,91% / 0,83% / 1,10%. Productos con frases en común con lo comprado hoy (nuevo): 7,8 → 35–41 → 98 por 10.000. Hold-out nuevo con esa feature: AUC compra 0,873 → 0,885, hit@1 0,324 → 0,353 (68 compras). Último visto en usuario que vuelve: 10 compras frente a 3,0 esperadas | SUPPORTED con muestra pequeña → I-201, I-209, I-210 |
| E-203 | ¿Qué vende en home? | 50.733 impresiones vivas en home, 19 compras | Vuelve: genérico 1/23.363 (0,4 por 10.000), carrito del histórico 6/5.441 (11,0), carrito de hoy 1/307. Nuevo: genérico 10/21.366 (4,7), plano por cuartil de calidad | → I-202, I-208 |
| E-204 | ¿Importan región y dispositivo? | Histórico: 8,1M impresiones (mitad de las sesiones fuera de home). En vivo: 30.241 peticiones | OBSERVED DATA histórico: productos <20 € en android × Andalucía / Canarias / Murcia 62,4 / 50,2 / 72,8 compras por 10.000 (1.731 / 365 / 341 compras) frente a 10,8–23,7 en las otras 27 celdas; productos ≥20 € 5,7–17,1 en todas. En vivo: segmento 2,37% (70/2.955) frente a 0,93% (255/27.286); clics 0,80% por debajo de 40 € y 0,27% por encima (12/4.494), resto 0,37% plano. Hold-out con log-precio × segmento: sin mejora (−971,8 → −976,5) | INVESTIGATING → I-204 (calidad propia del segmento); listas por región genéricas REJECTED (R-03) |
| E-205 | ¿El precio cambia la conversión? | 205.173 impresiones genéricas fuera de home | Vuelve: 5,5 / 4,6 / 0,0 / 1,9 compras por 10.000 en <15 / 15–40 / 40–80 / >80 € (34, 16, 0 y 3 compras). Nuevo: 14,6 / 10,5 / 6,9 / 15,4 (60, 29, 4 y 21) | Ordenar por dinero REJECTED para conversión (R-01); desempate en nuevos → I-206 |

- **Limitaciones:** lo mostrado no fue aleatorio (v1, qrank y fallback); son compras reales con ruido, no la probabilidad del modelo oculto. Las tasas "esperadas" vienen de un modelo ajustado con los mismos datos. Ninguna de estas pruebas sustituye a la fila por versión del leaderboard.
- **Sin cambios en** `live.py`, el writer ni `submissions`.

### E-210 — lfm r2: reajuste con feedback propio y 6 features nuevas; brazos en caliente
- **Date / owner / branch:** 2026-11-14 15:15 UTC / Javi (agente) / `javi/lfm-v2`, T-021. Solo lectura en RawTree; ningún envío.
- **Datos:** `team_26.feedback` 11:09–15:14 UTC: 44.026 peticiones, 440.260 impresiones, 430 compras, 1.450 clics; 96.396 impresiones muertas con 12 compras. La afinidad se reconstruye como la calcula el writer (historial + vistas de hoy anteriores a la petición + `recent_views`).
- **Hold-out (ajuste antes de 14:01 UTC; prueba 13.208 peticiones, 81 + 71 compras):**

| Pesos | Segmento | AUC compra | AUC clic | Log-verosimilitud compra | MRR compra | MRR clic |
|---|---|---:|---:|---:|---:|---:|
| `lfm_coef.json` publicado | vuelve | 0,887 | 0,821 | −532,0 | 0,598 | 0,566 |
| 11 features, reajustado | vuelve | 0,881 | 0,818 | −535,8 | 0,583 | 0,562 |
| 17 features, reajustado | vuelve | 0,888 | 0,824 | −536,7 | 0,589 | 0,556 |
| `lfm_coef.json` publicado | nuevo | 0,884 | 0,792 | −449,0 | 0,639 | 0,507 |
| 11 features, reajustado | nuevo | 0,879 | 0,791 | −424,4 | 0,599 | 0,497 |
| 17 features, reajustado | nuevo | 0,884 | 0,800 | −435,4 | 0,542 | 0,460 |

- **Lectura:** sin ganador. El reajuste calibra mejor al usuario nuevo (los pesos publicados predicen 159 compras donde hubo 71) pero no ordena mejor. Pesos nuevos tras ajustar con todo: usuario nuevo `nbp` +0,62 y `bsub` +0,62 (parecido a lo comprado hoy), `segcheap` +0,44; usuario que vuelve `hcart` +0,88 (carrito en home), `p40` +0,13 (el precio alto no penaliza), `islast` 1,95 → 2,19.
- **Dry-run real sin escribir (15:18 UTC, 327 peticiones, brazos r1 / r2 / t1):** 0 slates inválidos, 1,8 ms por petición (p95 3,3 ms), 12 versiones `v3-lfm-<brazo>-<segmento>` repartidas a tercios.
- **Comandos:** `python recsys/lfm_build.py --pull --out lfm_coef_r2.json`; `python -m unittest discover -s tests` → 114 tests OK.
### E-220 — Respuestas a tiempo: dónde se pierden y qué arregla T-022 (2026-11-14, Javi/agente, `javi/on-time-handoff`)
- **LIVE FEEDBACK (solo lectura, `team_26.feedback`, 13:40–15:10 UTC, 16.200 peticiones):** 15.046 servidas por el equipo, 1.152 `missing` (7,1%), 2 `invalid`, 0 `late`. De las `missing`, ~1.080 (6,7%) caen en las ventanas de los 5 reinicios y ~75 (0,5%) en parones sueltos de 3–6 s (10–11 peticiones seguidas cada uno; p. ej. 14:35:10 y 14:51:20 UTC).
- **LIVE FEEDBACK, plazo real:** en todo el día hay 295 respuestas con `latency_ms` entre 3.000 y 3.500 servidas como `team` y 36 `invalid`; ninguna `late` y ninguna aceptada por encima de 3.497 ms. El corte de 2,5 s en el POST (que aterriza hasta ~3,3 s) no está tirando respuestas válidas; no se cambia. La final puede ser más estricta: no depender de ese margen.
- **OBSERVED DATA (log del writer en el Mac, leído por el hilo de despliegue):** los tres arranques tienen un bucle de 59–71 s justo después de `ready LIVE`; últimas 2.000 líneas: `loop_ms` p50 517 / p95 739 / p99 1.357, `post_ms` p50 295 / p95 453. En los parones sueltos `stock_age_s` ≈ duración del bucle: se congela el proceso entero, no una petición de red.
- **OBSERVED DATA (sonda desde la nube, 45 s):** una petición es visible en `shop.requests` a los 0,28 s de mediana (p95 0,64 s) sondeando cada 0,13 s; la consulta tarda 0,12 s.
- **Causa del bloqueo de arranque (reproducida):** `refresh_events()` aplicaba todo el día (1,27 M de filas usuario-producto a las 15:20 UTC) dentro de un único `feature_lock`, y `predict()` espera ese candado. `--dry-run` en la nube con `main` (6168871): un bucle de 66,8 s, 109 de 247 peticiones caducadas en 5 min. Con el arreglo (filas en trozos de 2.000 soltando el candado, consultas por horas): bucle máximo 2,1 s (el primero, con la cola inicial), y después 935 de 935 peticiones dentro de plazo en 7 min, `loop_ms` p50 134 / p95 283 / p99 572.
- **Pausas del recolector de basura (medidas):** una recolección completa recorre todos los objetos con el GIL tomado y para todos los hilos. En la nube: 0,2 s al arrancar y hasta 0,8 s durante la carga del día, creciendo con los datos; tras `gc.freeze()` la misma recolección tarda 3,6 ms y no hay ninguna pausa >200 ms en 7 min. Es la explicación más probable de los parones de 3–6 s del Mac (proceso entero congelado, cada pocos minutos, sin errores de red), pero allí no está medida: el writer nuevo deja `{"event": "gc_pause"}` en el log para comprobarlo.
- **Ensayo de relevo (flujo real, sin escribir; `tools/handoff_rehearsal.py`):** writer A sirviendo, proceso B con `--takeover`. 300 peticiones en la ventana: 300 respondidas una vez, 0 nunca, 0 dos veces; en ±10 s del relevo 60 de 60, peor edad al POST 1,25 s; A no respondió nada después del relevo; B esperó 365 ms por el candado tras un SIGINT. Edad al POST p50 0,95 / p95 1,52 / máx 2,18 s con un POST simulado de 300 ms.
- **Límites:** medido en un contenedor de 4 núcleos, no en el Mac. Dos procesos a la vez ocupan ~2,8 GB cada uno (pico) durante el minuto de calentamiento. No se ha escrito nada en `submissions`. Comandos: `python -m unittest discover -s tests` (118 OK), `python live.py --dry-run`, y los tres pasos del ensayo.

### E-240 — lfm r3: reparto de categorías del usuario (T-024)
- **Date / owner / branch:** 2026-11-14 16:45 UTC / Javi (agente) / `javi/known-gap`. Solo lectura en RawTree; ningún envío.
- **Datos:** 52.298 peticiones con feedback (11:09–16:00 UTC), 622 compras, 1.950 clics.
- **Validación 1, usuarios apartados (mitad de usuarios para ajustar, la otra para medir, y al revés):** verosimilitud de qué producto de los 10 enseñados se compró o se clicó, corrigiendo la posición. r3 mejora a r1 en las 8 celdas; r2 no movía ninguna.

| Segmento | Etiqueta | Slates de | N | r1 | r2 | r3 |
|---|---|---|---:|---:|---:|---:|
| vuelve | compra | políticas anteriores | 154 | -185,2 | -185,5 | **-164,1** |
| vuelve | compra | lfm | 149 | -283,9 | -284,1 | **-278,5** |
| vuelve | clic | políticas anteriores | 533 | -778,8 | -781,3 | **-738,8** |
| vuelve | clic | lfm | 458 | -915,0 | -921,0 | **-903,4** |
| nuevo | compra | políticas anteriores | 181 | -290,6 | -289,8 | **-279,8** |
| nuevo | compra | lfm | 93 | -180,5 | -177,9 | **-172,1** |
| nuevo | clic | políticas anteriores | 447 | -847,3 | -845,0 | **-826,9** |
| nuevo | clic | lfm | 231 | -473,0 | -468,8 | **-458,2** |

- **Validación 2, corte temporal (ajuste antes de 14:33 UTC, medida después):** AUC de compra 0,868 -> 0,900 (vuelve, 170 compras) y 0,865 -> 0,910 (nuevo, 116). El acierto del producto comprado entre los 3 primeros es mixto en slates servidos por lfm (0,64 -> 0,60 en los que vuelven), donde el orden registrado favorece a r1.
- **Ensayo en seco (writer real, sin escribir, brazos r1 y r3):** 328 peticiones, 0 slates inválidos, 2,3 ms por petición (p95 5,5). r3 en usuarios que vuelven: 2,8 productos de carrito por slate frente a 2,3, y menos "misma categoría que la última vista" (2,8 frente a 3,5) a favor de sus categorías habituales.
- **Lo que no se sabe:** cuánto sube la conversión del modelo oculto. La estimación del propio modelo (+12% relativo en los que vuelven) se califica a sí misma y ya ha sobreestimado antes (I-211). Hay que leerlo como brazo en el leaderboard.

### E-270 — Brazo r5 = r3 + `cv` (co-ocurrencia producto a producto), ajuste y ensayo en seco
- **Date / owner / branch:** 2026-11-14 17:45 UTC · Javi (agente) · `javi/cv-graph-r5` (T-027). Etiqueta: LIVE FEEDBACK (sesgado) + OFFLINE ESTIMATE; el resultado del modelo oculto está pendiente.
- **Comandos:** `python lfm_graph_build.py` (grafo B sobre todo `shop.history_events`: 150.000 aristas, 5.000 productos, 3,2 MB); `python lfm_build.py --pull --base lfm_coef_r3.json --add cv --out lfm_coef_r5.json` (pesos de r3 intactos, solo se ajustan `cv`, el término independiente y el de posición).
- **Pesos:** `cv` 0,0643 (vuelven) y 0,1615 (nuevos). Ajuste conjunto de las 20 features: no mejora al de r3 + `cv` en el corte temporal.
- **Corte temporal (ajuste antes de 15:30 UTC, medida después; 219 y 146 compras):** AUC de compra 0,914 -> 0,915 (vuelven) y 0,902 -> 0,906 (nuevos); verosimilitud de clic -5.620,5 -> -5.617,9 y -3.018,4 -> -3.008,9. Mejora pequeña, dentro de lo que este feedback puede separar.
- **Cuánto cambia el slate frente a r3 (3.000 peticiones del tramo final):** vuelven, páginas con vistas: 0,16 productos de 10 distintos y el primero cambia en el 3%; nuevos: 0,61 de 10 y el primero en el 11%. Con `cv` = 0,5 a mano serían 1,5 y 1,9 de 10 (primero 29% y 32%); con 1,0, 3,1 y 3,6.
- **Ensayo en seco (writer real en la nube, `--dry-run`, brazos r3 y r5):** 674 peticiones, 0 errores, 0 caducadas.
- **Lectura prevista:** `api/state?by=model&from=<epoch>`, 30 minutos, r5 contra r3 por separado en `-k` y `-n`. Con los pesos ajustados la diferencia esperable es menor que el ruido de una ronda (±0,25 pt vuelven, ±0,6 nuevos), sobre todo en los que vuelven.
- **Corrección (E-300, T-030):** el corte de arriba puntuaba una base r3 ajustada hasta las 16:00:29 UTC en un tramo que empieza a las 15:30, y la tabla "slates nuevos" construía los slates sin el reparto de categorías. Cifras corregidas en E-300; la conclusión (mejora pequeña) no cambia.


### E-300 — Evaluación offline corregida de lfm: estado completo, compras del carrusel, catálogo a la hora de la petición, cortes y calibración (T-030)
- **Date / owner / branch:** 2026-11-14 18:20 UTC · Javi (agente) · `javi/eval-fixes`. Etiqueta: LIVE FEEDBACK (sesgado) + OFFLINE ESTIMATE. Nada de esto es conversión del modelo oculto ni una mejora demostrada.
- **Comando:** `python lfm_build.py --pull --cut "2026-11-14 15:30" --base lfm_coef_r3.json --add cv --no-write` (sobre main 4ee67ed + esta rama). Datos: 76.969 peticiones respondidas hasta las 18:17 UTC, 769.690 impresiones, 1.053 compras, 3.361 clics. Ajuste: 46.838 peticiones antes de las 15:30; medida: 30.131 después (322 compras de usuarios que vuelven, 221 de nuevos).
- **Procedencia de cada pieza aprendida en la tabla:** todos los pesos y la calibración se ajustan solo con peticiones anteriores a las 15:30. Grafo `cv`: solo `shop.history_events` (anterior al evento). Calidad `lq`: una sola foto de histórico (`qrank.joblib`), no reconstruible por hora. `lfm_coef_r3.json` (ajustado hasta 16:00:29) y `lfm_coef.json` solapan el tramo de medida: el script lo detecta por `meta.fitted_on`, rehace la base con sus 19 features en el tramo de ajuste y avisa.
- **1. Estado del replay (C1).** `report()` pasaba 4 partes del estado a `LF.slate()` y valoraba con 5: los slates "nuevos" se construían sin `ucat`/`usub`. Efecto medido con los mismos pesos (19 features, 4.000 peticiones del tramo de medida): compras esperadas por 100 peticiones según el modelo 2,43 -> 2,78 (vuelven con vistas 2,13 -> 2,56; nuevos con vistas 4,42 -> 4,78; coincidencia con lo servido 6,5 -> 7,7 de 10). Informes afectados: solo la tabla "slates nuevos" de E-240 y E-270 (posteriores a r3). No afectados: tablas de corte temporal (AUC, verosimilitud), validación por usuarios de E-240/E-260, I-207 (E-250) y todo lo leído del leaderboard.
- **2. Compras del carrusel (C2).** Cuentan como compradas desde la hora de su fila de feedback + 30 s (el writer las lee una vez por ciclo). Impresiones "muertas" (producto ya comprado o caducado): 96.965 con 12 compras, es decir 1,2 por 10.000 frente a 15,5 del resto.
- **3. Catálogo a la hora de la petición (C3).** `lfm_catlog.parquet` = catálogo base + las 3.997 filas de `catalog_updates`. Precio (`p40`, `segcheap`) de los productos mostrados a su hora; universo de candidatos del replay sin productos aún no lanzados o sin stock. Solo 8 de 769.690 impresiones mostraron un producto no servible según el registro (retraso de refresco). No reconstruible, se usa el valor último y el script lo imprime: `lq`, frases de la descripción, categoría/subcategoría/marca, y el retraso real de refresco del writer. Dentro de `LF.slate()` el precio sigue siendo el último (afecta a `p40`/`segcheap`, pesos de -0,16).
- **4. Cortes (C4), E-270 corregido** (base r3 rehecha antes de 15:30 -> base + `cv`):

| segmento | compras | AUC compra | verosimilitud compra | MRR compra |
|---|---|---|---|---|
| vuelven | 322 | 0,908 -> 0,909 | -1.901,1 -> -1.899,1 (+2,0) | 0,577 -> 0,579 |
| nuevos | 221 | 0,896 -> 0,900 | -1.277,8 -> -1.269,7 (+8,1) | 0,568 -> 0,571 |

  `cv` sigue siendo una mejora pequeña, algo más visible en nuevos; el ajuste conjunto de las 20 features no la supera (-1.899,2 y -1.279,0). No cambia la decisión de E-270: solo el leaderboard la juzga.
- **5. Calibración (C5).** `fit_add` heredaba la calibración de la base aunque movía término independiente y posición; ahora la reajusta con sus propias filas de ajuste. Las métricas de orden (AUC, MRR) no dependen de ella y se leen aparte. Aviso: aun calibrado en el tramo de ajuste, el modelo predice 417 compras donde hubo 322 (vuelven) y 379 donde hubo 221 (nuevos) en el tramo posterior: la tasa de compra bajó por la tarde, así que las probabilidades absolutas no se trasladan en el tiempo; las comparaciones de verosimilitud entre filas de la tabla sí son válidas.
- **Tests:** `tests/test_lfm_build.py` (12): paridad estado/slate replay = servicio, que falla si se omite el reparto; fronteras de tiempo de eventos y feedback; catálogo por hora; detección de solape; calibración. 172 tests en total.
- **Riesgos / límites:** vistas de hoy en cubos de 10 minutos y retraso de feedback fijo de 30 s son aproximaciones del reloj real del writer. La tabla "slates nuevos" sigue siendo el modelo puntuando su propia elección (optimista).

### E-320 — Qué generaliza: compradores no vistos, historial tapado, productos lanzados, por segmentos (T-032)
- **Date / owner / branch:** 2026-11-14 18:50 UTC · Javi (agente) · `javi/final-validation`. Etiqueta: LIVE FEEDBACK (sesgado: slates elegidos por nuestras propias políticas) + OFFLINE ESTIMATE. No es conversión del modelo oculto y no predice la de mañana.
- **Comando:** `python eval_slices.py` (tras `lfm_build.py --pull --no-write`). Salida completa en `data/eval_slices.csv`.
- **Diseño:** 41.358 compradores en 5 grupos por hash; cada grupo se puntúa con pesos ajustados sin ninguna petición suya y solo con peticiones anteriores a las 14:30 UTC (unas 28.800 peticiones y 260 compras por ajuste). Validación 14:30–16:30 (393 compras); confirmación desde las 16:30, leída una sola vez (332 compras). Intervalos al 95% remuestreando compradores enteros (lotes de lanzamiento en productos lanzados).
- **Medida:** `gain` = nats por compra que los pesos ganan sobre conocer solo la posición (0 = no aporta nada). La corrección de posición es parcial, así que **no sirve para decidir entre dos pesos nuestros**; eso lo hace el leaderboard. MRR se da solo como referencia (favorece a los pesos que ordenaron el slate servido).

| segmento (pesos con features de r3) | validación: compras, gain [IC] | confirmación: compras, gain [IC] |
|---|---|---|
| Todos los compradores no vistos | 393, 0,20 [0,13; 0,27] | 332, 0,10 [0,03; 0,16] |
| Comprador nuevo (sin historial) | 172, 0,19 [0,10; 0,28] | 125, 0,08 [-0,03; 0,17] |
| Vuelve, 20–199 eventos de historial | 79, 0,21 [0,06; 0,35] | 72, 0,17 [0,04; 0,28] |
| Vuelve, 200+ eventos | 137, 0,16 [0,05; 0,27] | 135, 0,08 [-0,03; 0,19] |
| Vuelve con historial TAPADO, pesos de nuevo | 222, -0,06 [-0,16; 0,04] | 207, -0,08 [-0,17; 0,02] |
| Vuelve con historial TAPADO, pesos de vuelve | 222, -0,10 [-0,22; 0,03] | 207, -0,13 [-0,23; -0,02] |
| Los mismos con su historial | 221, 0,20 [0,11; 0,28] | 207, 0,11 [0,02; 0,19] |
| Página de producto | 244, 0,13 [0,05; 0,22] | 218, 0,08 [0,02; 0,16] |
| Página de categoría | 126, 0,28 [0,17; 0,40] | 94, 0,08 [-0,05; 0,21] |
| Home (sin vistas recientes) | 23, 0,42 [0,13; 0,68] | 20, 0,29 [-0,07; 0,63] |
| Menos de 5 vistas en total (petición + día) | 20, 0,28 [0,03; 0,53] | 8, -0,06 [-0,54; 0,45] |
| 5+ vistas | 371, 0,19 [0,11; 0,25] | 323, 0,10 [0,03; 0,16] |
| Producto del catálogo anterior | 390, 0,20 [0,13; 0,28] | 327, 0,10 [0,04; 0,17] |
| Producto lanzado hace 1 h+ | 3 (2 lotes), 0,35 | 5 (2 lotes), -0,16 |
| `lfm_coef_r3.json` congelado (ajustado hasta 16:00:29) | — | 332, 0,17 [0,11; 0,23] |

- **Lo que se sostiene:** (1) con compradores enteros apartados y en un periodo posterior, los pesos siguen aportando sobre la posición en nuevos y en los que vuelven; no hay sobreajuste a usuarios (el modelo no tiene parámetros por usuario). (2) Ningún segmento con datos suficientes se hunde: producto, categoría, home, pocas o muchas vistas.
- **Lo que no se sostiene o queda abierto:** (1) **El valor de los pesos cae con el tiempo**: los ajustados antes de las 14:30 pasan de 0,20 a 0,10 dos horas después; el fichero r3 real, ajustado hasta las 16:00 (con compradores de todos los grupos, así que es fuera de tiempo pero no fuera de usuario), da 0,17 en ese mismo tramo. Los pesos del sábado valdrán menos el domingo y no sabemos cuánto. (2) **Sin historial, el orden dentro del slate no mejora a la posición** (gain negativo con cualquiera de los dos juegos de pesos; los de nuevo son algo mejores en los dos periodos, sin separación estadística). Es una cota pesimista para esta medida, porque los slates se eligieron con historial. Los compradores realmente nuevos sí funcionan. (3) **Productos lanzados durante el evento: casi sin datos** (1.413 impresiones, 8 compras, 55 productos de 3 lotes tras las 14:30). Se compraron 3,3 veces más de lo que predecía el modelo (8 frente a 2,4) mientras el resto se compró la mitad de lo previsto (717 frente a 1.423): el prior de producto nuevo se queda corto. Apoya probar el brazo de calidad de producto nuevo (PR #26, T-028), no lo demuestra. (4) r3 frente a r1 con esta medida no se separan (0,20 frente a 0,18 y 0,10 frente a 0,10): la ventaja de r3 la demostró el leaderboard, no este ensayo. `cv` tampoco se separa (0,21 y 0,10).
- **Calibración:** las probabilidades absolutas no se trasladan en el tiempo (el modelo predice el doble de compras de las que hubo por la tarde). No usar probabilidades offline como previsión de conversión.

### E-321 — Ensayo de robustez con el código real del writer (T-032)
- **Date / owner / branch:** 2026-11-14 18:57 UTC · Javi (agente) · `javi/final-validation`. Etiqueta: comprobación de robustez, **no** estimación de conversión. `python tools/final_rehearsal.py` carga `live.py` en `--dry-run`, llama a `predict()` en lotes de 4 y bloquea cualquier escritura en RawTree; no escribe `policy.json`.
- **Entrada:** 1.500 peticiones registradas (18:47–18:55 UTC), catálogo de 5.300 productos (243 lanzados en el evento, activos), brazo r3. El código de servicio no consulta el leaderboard (comprobado en el arranque del ensayo).

| escenario | n | inválidos | ms por petición p50 / p95 / máx |
|---|---|---|---|
| peticiones tal cual | 1.500 | 0 | 1,2 / 1,9 / 7 |
| comprador nuevo, id desconocido | 1.500 | 0 | 0,6 / 0,8 / 3 |
| nuevo y sin vistas (home) | 1.500 | 0 | 0,6 / 0,7 / 1 |
| solo vistas de productos recién lanzados (sin compras ni aristas) | 1.500 | 0 | 0,6 / 0,8 / 2 |
| metadatos ausentes o desconocidos, vistas con ids inexistentes | 1.500 | 0 | 1,1 / 1,7 / 3 |
| cambio brusco de categorías vistas | 500 | 0 | 1,0 / 1,3 / 2 |
| un tercio del catálogo sin stock de golpe | 1.500 | 0 con 10 válidos; ver E-370 | 16,3 / 24,4 / 343 en main; 7,1 / 10,3 / 12 con T-037 |
| RawTree sin responder (refresco parado) | 1.500 | 0 | 1,1 / 1,6 / 4 |

  Inválido = no son 10 distintos, alguno fuera de catálogo o sin stock según el writer, o alguno ya comprado por ese comprador.
- **Hallazgo:** en el corte de stock, main entrega 10 válidos pero el 96% de las peticiones cae al camino antiguo v1 (133 slates con un producto ya comprado). Arreglo en PR #33 (T-037, E-370).
- **No cubierto:** el POST y el plazo de respuesta de extremo a extremo (los cubre `tools/handoff_rehearsal.py`), y un RawTree lento en vez de caído.


### E-360 — Ventanas de estado: cuánto dura el valor de un carrito y de una compra, y qué cambia el interruptor (T-036)
- **Date / owner / branch:** 2026-11-14 18:40 UTC · Javi (agente) · `javi/state-windows`. Etiqueta: LIVE FEEDBACK (descriptivo, sin controlar por el resto de señales) + medida de latencia. No es conversión del modelo oculto.
- **Datos:** 76.969 peticiones respondidas (11:09–18:17 UTC), estado reconstruido a la hora de cada petición.
- **Carritos por antigüedad (compras por 10.000 impresiones de un producto en el carrito, no comprado):**

| antigüedad del carrito | vuelven (n, compras) | nuevos (n, compras) |
|---|---|---|
| hasta 10 min | 101 (296, 3) | 192 (208, 4) |
| 10–60 min | 27 (1.469, 4) | 124 (884, 11) |
| 1–2 h | 48 (1.652, 8) | 160 (1.127, 18) |
| 2–4 h | 38 (3.146, 12) | 181 (1.991, 36) |
| más de 4 h | 32 (4.925, 16) | 161 (2.865, 46) |
| carrito del histórico (hasta 60 días) | 34 (98.439, 332) | — |
| sin carrito | 5,5 (368.239, 204) | 16 (222.726, 352) |

  Con estos tamaños no se ve caída con la antigüedad: a más de 4 horas un carrito sigue valiendo 6 a 10 veces más que un producto sin carrito, y lo mismo que un carrito del histórico. Borrarlos o degradarlos a medianoche tiraría señal.
- **"Misma subcategoría que una compra de hoy" por tiempo desde la última compra (productos sin carrito, compras por 10.000):** vuelven 35 (hasta 30 min), 39 (30 min–2 h), 24 (más de 2 h), frente a 4–8 del resto; nuevos 83, 60, 67 frente a 0–15. Sigue 3 a 4 veces por encima a más de 2 horas. De un día para otro no se puede medir con un solo día.
- **Qué cambia el interruptor en datos reales** (3.000 peticiones, pesos r3, corte simulado a las 15:00 UTC): exclusiones idénticas y 0 carritos perdidos en los 2.891 usuarios; cambia el 42% de los slates (1,2 productos de 10 de media; en 542 solo el orden) y el 48% con `carts: day`. 0 slates inválidos en todos los casos.
- **Latencia (estado + slate, 3.000 peticiones, misma máquina):** main p50 0,73 ms / p95 1,46; rama sin ventana 0,58 / 1,16; con ventana 0,54 / 1,18; con `carts: day` 0,63 / 1,41. Sin diferencia fuera del ruido.
- **Riesgo de operación encontrado:** el runbook recomendaba arrancar la final con `EVENTS_SINCE` del domingo. Eso quitaría de las exclusiones 98.005 compras orgánicas del sábado (24.522 de los 41.358 usuarios que nos pidieron carrusel compraron algo) y los carritos del 74% de esos usuarios. Corregido en el runbook.
- **Tests:** `tests/test_state_windows.py` (9): fronteras exactas (23:59:59.999 / 00:00:00.000), eventos que llegan tarde, transición sábado-domingo por `apply_events`, reinicio el domingo con el mismo resultado, ventanas de carga que cruzan medianoche. 169 tests en total en esta rama.
- **Conclusión:** no activar ventana de día para la final (D-360).
### E-370 — Corte brusco de stock: lfm dejaba de responder y la petición caía a v1 (T-037)
- **Date / owner / branch:** 2026-11-14 19:00 UTC · Javi (agente) · `javi/slate-stock-fix`. Etiqueta: ensayo de robustez con el código real del writer en `--dry-run` (`tools/final_rehearsal.py`, PR de T-032). No es una estimación de conversión.
- **Causa:** `LiveFit.slate` mira los 30 productos con más puntuación y después quita los que el hilo de stock acaba de marcar como agotados. Si más de 20 de esos 30 están agotados desde la última carga de catálogo, devuelve vacío y la petición la responde el camino antiguo (`v1-gbm-cand-r1`).
- **Ensayo (1.500 peticiones registradas, un tercio del catálogo y todas las vistas recientes agotados de golpe, RawTree sin responder):**

| | respondidas por lfm | slates con un producto ya comprado | ms por petición p50 / p95 / máx |
|---|---|---|---|
| antes (main) | 53 de 1.500 | 133 (del camino v1) | 16,3 / 24,4 / 343 |
| después | 1.500 de 1.500 | 0 | 7,1 / 10,3 / 12 |

  En los dos casos los 10 productos eran distintos y con stock. El resto de escenarios (usuario nuevo, sin vistas, producto recién lanzado, metadatos rotos, cambio de categorías, refresco parado) no cambian: 0 inválidos, p95 por debajo de 2 ms.
- **Alcance real:** con el refresco de catálogo funcionando (cada ciclo) casi nunca hay más de un par de productos agotados entre los 30 mejores; el sábado no se vio. Importa si el catálogo deja de refrescarse mientras el stock sigue cambiando.
- **Cambio:** si tras filtrar quedan menos de 10, se recorre el resto por orden de puntuación. El caso normal no cambia (mismo slate, test).

### E-271 — Brazos de home (T-025) y ronda r3 contra r5 con `cv` a 0,5, modelo oculto
- **Date / owner:** 2026-11-14 18:30 UTC · Javi (agente) · main `4ee67ed`. Etiqueta: HIDDEN MODEL (leaderboard, `api/state?by=model&from=&to=`).
- **Brazos de home, 17:05–17:35 UTC, usuarios conocidos en home:** control (home de lfm r3) 0,49% (157 peticiones); `conv` 0,38% (167); `catbest` 0,21% (184); `trend` 0,14% (180). Ninguno gana al control: apagados a las 17:45 UTC (`data/home_arms.json.off`). Las listas genéricas rinden menos de la mitad que la lista personalizada. RECHAZADO; no borrar el código.
- **r3 contra r5 con `cv` = 0,5 (brazo `r5c05`), 17:50–18:20 UTC, reparto 50/50:**

| Segmento | r3 | r5 `cv` 0,5 |
|---|---:|---:|
| Producto/categoría, conocidos | 1,57% (1.489) | 1,77% (1.521) |
| Producto/categoría, nuevos | 2,61% (645) | 2,61% (619) |
| Home, conocidos | 0,79% (362) | 0,46% (432) |
| Home, nuevos | 0,56% (168) | 1,05% (145) |
| Total del brazo | 1,65% | 1,71% |

- **Lectura:** `cv` ayuda en páginas de producto/categoría de usuarios conocidos (+0,20 pt) y no mueve a los nuevos; en home pierde. Una sola ronda de 30 minutos: la diferencia total (+0,06 pt) está dentro del ruido. Equipo en la ventana: 1,68% (4.º; team_06 1,97%, `reference` 1,78%), 99,98% a tiempo.
- **Siguiente:** brazo fusionado `f5c05` (`cv` 0,5 en páginas, pesos de r3 en home) contra r3 desde las 18:25 UTC; política en `recsys/policy.candidate.json`. El campeón demostrado sigue siendo r3 solo (`recsys/policy.champion.json`) hasta que `f5c05` gane una ronda.

### E-272 — r3 contra brazo fusionado `f5c05` (`cv` 0,5 en páginas, r3 en home), modelo oculto
- **Date / owner:** 2026-11-14 19:00 UTC · Javi (agente) · writer en `4ee67ed`. Etiqueta: HIDDEN MODEL, ventana 18:25–18:55 UTC, reparto 50/50.

| Segmento | r3 | `f5c05` |
|---|---:|---:|
| Producto/categoría, conocidos | 2,08% (1.539) | 1,67% (1.476) |
| Producto/categoría, nuevos | 3,09% (626) | 2,35% (587) |
| Home, conocidos (mismos pesos) | 0,44% (372) | 0,48% (372) |
| Home, nuevos (mismos pesos) | 0,66% (165) | 0,85% (146) |

- **Dos rondas juntas (E-271 + esta), páginas:** conocidos r3 1,83% (3.028) contra `cv` 0,5 1,72% (2.997); nuevos r3 2,85% (1.271) contra 2,48% (1.206). El +0,20 pt de la primera ronda se invierte a -0,41 en la segunda.
- **Decisión:** `cv` a 0,5 RECHAZADO; campeón r3 solo (`recsys/policy.champion.json`). No borrar el código ni `lfm_coef_r5.json`.
- **Lección de medida:** con ~1.500 peticiones por brazo, una ronda de 30 minutos se mueve ±0,4 pt entre rondas con el mismo par de brazos. No promover con una sola ronda; hacen falta dos rondas concordantes o una ventana de 1 h o más.
- Equipo en la ventana: 1,79%, 2.º (team_06 2,04%, team_42 1,78%, `reference` 1,91%), 99,56% a tiempo.

### E-280 — cold_lq como brazo de lfm (T-028), ensayo en seco, 14 nov 18:10–18:15 UTC

- **Qué:** writer real en la nube con `--dry-run` (sin escribir), 5 minutos, `lfm_arms` = `r3` contra `c1` (mismos pesos r3 + `"lq": "cold"`). 300 productos nuevos en catálogo (tandas de 10:00, 14:00 y 18:00 UTC).
- **Resultado:** 851 peticiones, 0 errores, 100% de slates válidos (10 distintos). Caducadas: 54 en el arranque en frío de la nube y 5 después. Bucle p50 138 ms, p95 357 ms.
- **Productos nuevos en las impresiones:** r3 0,2% (6 de 3.290); c1 10,2% (306 de 3.090): conocidos 10,8%, nuevos 7,2%, home conocidos 10,4%, home nuevos 11,3%. Slates de c1 con al menos uno nuevo: 63%. Slot 1 nuevo: 10%.
- **Límite:** solo comprueba que el brazo sirve y cuánto cambia la exposición. No dice nada de conversión: eso solo lo decide el leaderboard. La exposición queda varias veces por encima de la cuota orgánica de vistas (2,4% con 200 productos, E-CS01b), así que puede restar.

> E-280 queda sustituido: medía la primera versión del brazo (todas las páginas, sin límite). Valen E-281 y E-282.

### E-281 — replay por petición del brazo cold_lq, a fecha de cada petición (T-028, encargo C6). Solo diagnóstico

- **Qué:** `python cold_lq_replay.py --pull` (solo lectura). 4.240 peticiones respondidas entre 14:00 y 18:19 UTC del 14 nov (1 de cada 5), cada una puntuada dos veces con los pesos r3: control y `"lq": "cold"`. Catálogo, precio, existencia y stock reconstruidos con `catalog_updates` hasta el instante de la petición; evidencia orgánica de los tramos de 10 minutos ya cerrados; estado del usuario con `state_asof`/`mix_asof`/`aff_asof`; exclusiones de comprados, historial caducado y sin stock como en el servicio. 52 snapshots.
- **Validez:** 100% de slates válidos en los dos brazos (10 distintos, activos, no comprados). Home y peticiones sin vistas: 0 slates distintos de 855.
- **Exposición de productos nuevos (control → brazo), páginas con vistas:** 0,18% → 3,89% de las impresiones (3.385 peticiones); slates con alguno 1,8% → 31,2%; slot 1 0,1% → 2,5%. Conocidos/producto 0,21% → 4,46%; conocidos/categoría 0,31% → 5,23%; nuevos/producto 0,04% → 2,13%; nuevos/categoría 0,00% → 1,72%.
- **Correcciones:** 200 productos a las 14:00 y 300 a las 18:10, ninguno rechazado; 18–30 tocan el límite ±log(20); corrección media +0,54 a +0,58 en log-calidad, al alza en 2 de cada 3.
- **No reconstruido:** compras hechas por nuestro carrusel (solo compras orgánicas en el estado; encargo C2), el retraso de refresco del writer (20 s) y la resolución de 10 minutos de la evidencia.
- **No es conversión.** Sustituye a `cold_lq_slates.py` (E-CS01d), que aplicaba eventos hasta las 15:00 a peticiones anteriores y no reproducía stock ni historial caducado.

### E-282 — ensayo en seco del brazo cold_lq acotado (T-028), 14 nov ~18:40 UTC, contenedor en la nube

- **Qué:** writer real con `--dry-run` (no escribe), 4 minutos cada vez: A = dos brazos de control (r3, r3); B = r3 contra `c1` (`"lq": "cold"`). Se descartan los primeros 60 bucles.
- **Validez:** 0 errores y 100% de slates válidos en los dos ensayos (B: 530 peticiones).
- **Latencia del bucle (A → B):** p50 136 → 136 ms; p95 313 → 355 ms; p99 448 → 1.051 ms; máximo 3.781 → 2.399 ms; caducadas 5 → 4. Las colas son ruidosas en la nube (el máximo es del ensayo sin el brazo). El cálculo de correcciones ocupa unos 125–155 ms del hilo de refresco cada ciclo (~20–30 s) y no hace ninguna consulta.
- **Exposición en B:** c1 conocidos 6,4% de impresiones nuevas (139 peticiones), c1 nuevos 1,9% (42); r3 0,2–0,5%; home de c1 0,0% (44 peticiones). 300 productos corregidos, 29 en el límite.
- **Límite:** medido lejos del Mac; la latencia real hay que mirarla en el writer tras activar.

### E-430 — Guard de compras completo y validación de `policy.json` (T-043): coste y ensayo en seco, 14 nov 23:10 UTC, contenedor en la nube

Correcciones funcionales. **No se les atribuye uplift de conversión** y no hay lectura de leaderboard: nada de esto se ha desplegado. Etiqueta: OFFLINE ESTIMATE (coste) y OBSERVED DATA (ensayo en seco con peticiones reales, sin escribir).

**Coste del guard** (`python tools/bench_guard.py`, catálogo sintético de 20.000 productos, mediana de 7 rondas, µs por llamada a `repair_for`):

| Compras por fuente | Caso | Antes (µs) | Ahora (µs) |
|---:|---|---:|---:|
| 0 | lista válida sin comprados (camino habitual) | 1,65 | 1,11 |
| 30 | lista válida sin comprados (camino habitual) | 0,85 | 2,24 |
| 300 | lista válida sin comprados (camino habitual) | 0,88 | 2,29 |
| 30 | lista válida con 1 comprado (antes se enviaba tal cual) | 0,86 | 5,13 |
| 300 | lista válida con 1 comprado (antes se enviaba tal cual) | 0,87 | 18,67 |
| 30 | lista corta, hay que rellenar | 553,77 | 3,15 |
| 300 | lista corta, hay que rellenar | 633,17 | 16,52 |

El camino habitual cuesta unos 1,4 µs más por petición (30 pruebas de pertenencia, sin copiar conjuntos ni tomar el lock). El relleno es más barato que antes porque ya no filtra la lista entera de los más vendidos. `read_policy` (hilo de refresco, un ciclo cada ~20 s): 41 µs con el fichero sin cambios, ~0,5 ms un cambio válido de 4 brazos, 84 µs un candidato rechazado.

**Ensayo en seco** (`python tools/guard_policy_dryrun.py`, código real del writer con `--dry-run`, modelos, catálogo y eventos reales, política `policy.night_1114_x2.json`, 1.500 peticiones registradas 22:59–23:07 UTC, 1.379 de usuarios con alguna compra):

- Peticiones tal como llegaron: 1.500 slates intactos, 0 reparados, 0 inválidos, 0 con un comprado. El código anterior tampoco enviaba ninguno aquí: lfm ya excluye lo comprado al puntuar. `repair_for` con estado real: p50 2,4 → 5,2 µs, p99 27,7 → 14,8 µs.
- Compra que llega entre el ranking y el envío (se marca como comprado el tercer producto de cada slate, solo en memoria): el código anterior lo enviaba en 1.496 de 1.496; el nuevo en 0, con 10 productos válidos y el orden del resto conservado en los 1.496.
- Cinco actualizaciones malas escritas en `policy.json` con el hilo de refresco real en marcha (fichero de pesos ausente, JSON cortado, peso `NaN`, variante desconocida, `cold_new` sin control): las cinco rechazadas, con política, pesos (los mismos objetos) y etiquetas servidas sin cambios. Después un fichero correcto de 2 brazos entra en el siguiente ciclo.
- Los 15 ficheros de política del repo y de `javi/night-og1b` (incluidos `policy.night_1114_og1b.json` y `policy.night_1114_cx3.json` con el fichero de pesos de og1) pasan la validación nueva con los mismos brazos que acepta el código actual.

Límites: el `policy.json` que está ahora mismo en el Mac no se ha podido leer desde la nube (se ha validado su copia en `javi/night-og1b`). No mide conversión. El caso de menos de diez alternativas sin comprar solo está cubierto por test unitario (no ocurrió con datos reales).

### E-340 — replay a fecha de cada petición del modo `cold_new` (T-034). Solo diagnóstico, no conversión

- **Qué:** `python cold_lq_replay.py --pull --mode cold_new --n 6000` (solo lectura). 6.534 peticiones respondidas entre 14:00 y 18:50 UTC del 14 nov, pesos r3, control contra `"lq": "cold_new"`, estado a fecha de cada petición (como E-281). 59 snapshots, hasta 300 productos corregidos, 29–30 en el límite, ninguno rechazado.
- **Tráfico no objetivo (usuarios que vuelven, home, sin vistas):** 0 slates distintos de 4.987.
- **Cohorte objetivo (usuario nuevo, producto/categoría con vistas):** 1.547 peticiones, 100% de slates válidos en los dos brazos; cambia el 19,1% de los slates y el 1,4% del slot 1; productos nuevos en las impresiones 0,05% → 2,06% (producto 0,06% → 1,87%; categoría 0,04% → 2,51%).
- **Poca evidencia de sesión** (una sola vista reciente, sin carritos ni compras): 139 peticiones, 100% válidas, cambia el 15,8% de los slates, 0,00% → 1,73%. Con más evidencia (1.408): 19,4%, 0,06% → 2,10%.
- **Latencia en el contenedor de la nube (no es garantía para el Mac):** camino de la petición, un slate de lfm: control p50 0,77 ms / p95 1,75 ms; brazo p50 0,76 ms / p95 1,71 ms. Refresco: correcciones p50 120 ms / p95 196 ms; `set_catalog` p50 18 ms / p95 28 ms, una vez por ciclo de refresco.
- **No reconstruido:** compras hechas por nuestro carrusel en el estado offline (en el writer sí se excluyen), retraso de refresco y resolución de 10 minutos de la evidencia.

### E-341 — ensayo en seco con `policy.cold_new_r3.json` (T-034), 14 nov ~19:05 UTC, contenedor en la nube

- **Qué:** writer real con `--dry-run` (no escribe), 3,5 minutos. 0 errores, 100% de slates válidos, bucle p50 139 ms / p95 393 ms (445 peticiones tras el arranque, 4 caducadas).
- **Etiquetas emitidas por lfm:** `r3-k` (204), `r3-kh` (54), `r3-nh` (23), `r3-n` (37) y `cn1-n` (34). No aparece ninguna etiqueta `cn1` fuera de la cohorte objetivo. Productos nuevos en las impresiones: `cn1-n` 1,76%, `r3-n` 0,27%.

## E-350 — Filtrado colaborativo (`mf`) sobre el feedback en vivo (T-035, 2026-11-14 20:00 UTC)

- **Tipo:** OFFLINE ESTIMATE sobre LIVE FEEDBACK (79.868 peticiones, 11:09–18:33 UTC; usuarios conocidos: 463.598 impresiones vivas, 2.162 clics, 612 compras). Código: `recsys/lfm_mf_build.py`, `recsys/lfm_build.py --base lfm_coef_r3.json --add mf`.
- **Qué es `mf`:** SVD de rango 16 de la matriz usuario×producto del histórico orgánico (59.841 usuarios × 5.000 productos, log(1 + vistas + 3·carritos + 6·compras)); puntuación del producto para el usuario, estandarizada dentro del catálogo de cada usuario. Solo usa el histórico: nada de hoy, sin fuga.
- **Señal en bruto (conocidos, producto/categoría, compras por 10.000 impresiones), por banda de la puntuación r3 y banda de `mf`:**

| Banda r3 | `mf` < 3 | 3–7 | 7–11 | > 11 |
|---|---:|---:|---:|---:|
| 50% inferior | 0,1 | 1,4 | 0,0 | 4,8 |
| 50–80% | 2,9 | 6,1 | 6,9 | 21,3 |
| 80–95% | 14,7 | 23,2 | 30,6 | 62,6 |
| 5% superior | 138,5 | 138,1 | 174,5 | 325,3 |

- **Peso ajustado sobre r3 (resto de pesos fijos):** 0,0627 ± 0,0035 (18 errores estándar). Con todo reajustado a la vez: 0,083.
- **Validación:** (a) corte temporal (ajuste antes de 16:20, prueba después, 260 compras): MRR de compra 0,579 → 0,597, AUC 0,901 → 0,907, log-verosimilitud −1559,6 → −1545,6. (b) CV de 5 grupos por usuario, todo reajustado: MRR de compra en producto/categoría 0,602 → 0,624, acierto en el primer puesto 42,2% → 44,5%; en home 0,689 → 0,739 (39 compras). Bootstrap por usuario de la mejora de MRR de compra: +0,024, IC 95% [+0,010; +0,038]; de clic +0,010 [+0,002; +0,017].
- **Variantes:** rango 8/12/16/24/32 dan lo mismo (0,621–0,624); solo vistas, casi igual (0,622); binaria o sin logaritmo, peor (0,610); sin estandarizar por usuario, peor (0,609); en percentiles, nada (0,600). Vecinos producto-producto sobre el historial del usuario: nada (0,606).
- **Cuánto cambia la lista:** con el peso ajustado, r6 y r3 comparten 8,7 de 10 productos y el primer puesto cambia en el 24% de las peticiones de conocidos. Valor estimado por el propio modelo (optimista, sirve solo en relativo): +1,6% en producto/categoría, +1,1% en home. Coste: 1,06 ms por petición de mediana con todo el cálculo de lfm.
- **Lectura honesta:** la señal es real y nueva, pero el efecto esperado es moderado (del orden de +0,03 a +0,06 pt sobre conocidos con el peso ajustado). No explica por sí sola los ~0,45 pt que nos saca la referencia en no-cold. El feedback propio no puede medir el valor de productos que nunca enseñamos, así que el peso real puede ser mayor: se decide en el leaderboard.

### E-273 — `cold_new` (brazo `cn1`) contra r3 en usuarios nuevos, primera ronda, modelo oculto
- **Date / owner:** 2026-11-14 19:45 UTC · Javi (agente) · writer en `3b1596e`, política `recsys/policy.cold_new_r3.json` desde las 19:07 UTC. Etiqueta: HIDDEN MODEL, ventana fija 19:10–19:40 UTC, reparto 50/50 por usuario.

| Grupo | Control r3 | `cn1` |
|---|---:|---:|
| Nuevos, producto/categoría | 3,26% (633) | 3,75% (667) |
| € por petición | 2,02 | 1,31 |

- Sin tocar por el brazo: conocidos en páginas 1,87% (3.025), home conocidos 0,55% (727), home nuevos 1,38% (315).
- **Lectura:** +0,48 pt a favor de `cn1`, dentro de lo que oscila una ronda de 30 minutos (E-272: ±0,4 pt con 1.500 peticiones, y aquí hay ~650 por brazo). NO CONCLUYENTE: hace falta un bloque de confirmación antes de promover. El ingreso por petición baja; la puntuación es por conversión, pero conviene mirarlo en la confirmación.
- Equipo en la ventana: 2,05%, 4.º (team_06 2,45%, team_42 2,16%, team_22 2,08%, `reference` 2,14%), 99,98% a tiempo.

### E-274 — r6 (filtrado colaborativo) contra r3 en conocidos y bloque de confirmación de `cold_new`, modelo oculto
- **Date / owner:** 2026-11-14 20:25 UTC · Javi (agente) · writer en `1f20ae3`. HIDDEN MODEL, ventana 19:50–20:20 UTC. Brazos r3 y r6 desde las 19:48; tres brazos (r3, r6, `cn1`) desde las 19:55. El writer del Mac se paró a las 20:20:22 UTC para pasarlo a otra máquina.

| Grupo | r3 | r6 | `cn1` |
|---|---:|---:|---:|
| Conocidos, producto/categoría | 1,89% (1.907) | 1,90% (1.072) | — |
| Conocidos, home | 0,44% (430) | 0,40% (269) | — |
| Nuevos, producto/categoría | 3,04% (481) | 3,36% (471), mismos pesos que r3 | 3,97% (380) |

- **r6:** empate en conocidos (+0,00 pt). Sin efecto medible; NO se promueve. No borrar el código.
- **`cold_new`:** segundo bloque a favor: 3,97% contra 3,20% del control conjunto (r3-n + r6-n, 952 peticiones, mismos pesos). Primer bloque (E-273): 3,75% contra 3,26%. Sumados: 3,83% (1.047) contra 3,22% (1.585), +0,6 pt. La diferencia entre los dos controles idénticos (3,04% y 3,36%) da la escala del ruido: 0,3 pt.
- **Estado:** `cold_new` es el único retador con dos bloques seguidos a favor. Sigue como variante en la política de la noche (`recsys/policy.night_1114_x.json`, commit `d05e349`) para el veredicto con el acumulado.
- Puntualidad: 66 de las 84 pérdidas de 18:50–20:08 UTC son de los dos reinicios con relevo; 14 de parones de 2–4 s en el Mac (8 GB, 7,2 GB de swap) y tiempos de espera de la API. Ningún brazo es más lento (p95 ≈2,0 s en todos).

### E-390 — Feature `newp` (producto lanzado durante el evento) sobre r3 y brazo `np1` (T-039)
- **Date / owner / branch:** 2026-11-14 20:30 UTC · Javi (agente) · `javi/new-product-arm`. LIVE FEEDBACK (sesgado: solo lo que lfm enseñó) + OFFLINE ESTIMATE. No es conversión del modelo oculto.
- **Comandos:** `python lfm_build.py --pull --base lfm_coef_r3.json --add newp --no-write`; `python explore_t039_newp.py --cut "2026-11-14 17:10" --known 1.0 --new 0`.
- **Qué es:** `newp` = 1 si el producto está en el catálogo vivo y no tiene calidad de 60 días (hoy, exactamente los 300 lanzados), solo en páginas de producto/categoría con vistas; 0 en home. Peso 0 en todos los ficheros de pesos: ningún brazo existente cambia.
- **Peso ajustado con r3 fijo (92.434 peticiones, 1.354 compras):** conocidos 1,96 ± 0,14 (16 compras y 28 clics en 1.256 impresiones: 127 compras por 10.000 frente a 13); nuevos 0,86 ± 0,46 (1 compra en 342). Ajustado solo antes de las 17:10: conocidos 1,88 ± 0,22; nuevos sin información.
- **Corte temporal (ajuste antes de 17:09 UTC, lectura después; 303 compras de conocidos):** MRR de compra 0,581 -> 0,594, AUC 0,905 -> 0,908. Nuevos: sin cambio (0,584, AUC 0,896 -> 0,894).
- **Replay a fecha de cada petición (2.500–4.000 peticiones tras las 17:10), conocidos en páginas:**

| Peso de `newp` | Productos cambiados de 10 | Slot 1 cambia | Productos nuevos en las impresiones | Compras esperadas por 100 (peticiones cold de conocidos, estimación del modelo) |
|---:|---:|---:|---:|---:|
| 0 (r3) | — | — | 0,7% | 2,65 |
| 1,0 | 0,8 | 9% | 8,5% | 3,01 |
| 1,4 | 1,7 | 19% | 18% | 3,16 |
| 1,9 (ajustado) | 3,9 | 38% | 40% | (2,36 -> 2,85 en otra muestra) |

  Home y usuarios nuevos: 0 slates distintos (579 + 265 de home; nuevos en páginas 0,9% por desempates). 100% de slates válidos.
- **Límite:** el peso ajustado sale de 1.256 impresiones elegidas por lfm (productos nuevos con mucha afinidad); llevarlo al 40% de las impresiones es extrapolar. Por eso el primer brazo usa 1,0 (exposición del 8,5%, cerca del 6% que pesan en el catálogo) y el peso se sube solo si gana.
- **Ensayo en seco (writer real en la nube, `--dry-run`, `policy.newp_r3.json`, 5,5 min):** 956 peticiones, 0 errores, bucle p50 141 ms / p95 365 ms; 56 caducadas, las del arranque en frío del contenedor como en E-280.
- **Tests:** `tests/test_lfm_newp.py` (6 nuevos; 243 en total, todos pasan).

### E-391 — Variante de exploración en el último slot (T-039), 14 nov 20:35 UTC
- **Qué es:** clave de brazo `"explore"`: `true`, `"new"` o `"known"`. En páginas de producto/categoría con vistas, el slot 10 (10% de las impresiones; con los pesos de posición medidos, un 3,5% de las compras esperadas de una lista) pasa a un producto elegido al azar entre los puestos 11 a 60 del ranking de esa misma petición: válido, con stock y no comprado. Los 9 primeros no cambian. Determinista por petición. Home y peticiones sin vistas, intactas. Cualquier fallo deja la lista ordenada.
- **Política de la noche con exploración:** `recsys/policy.night_1114_x.json` = la de `policy.night_1114.json` con `"explore": "new"` en el brazo `np1`. Como `np1` solo cambia pesos de usuarios conocidos, su tráfico de usuarios nuevos (25% de los nuevos) servía r3: ahora es la fila de exploración, con la etiqueta de `np1` para nuevos. Reparto resultante: conocidos r3 50% / np1 25% / cvk 25%; nuevos r3 50% (brazos r3 y cvk) / cn1 25% / exploración 25%. El campeón conserva el 50% en cada tramo.
- **Tests:** 13 en `tests/test_lfm_newp.py` (250 en total): solo cambia el slot 10, sale de los puestos 11–60, nunca un excluido ni comprado, modos por tipo de usuario, validación del writer y aceptación de la política de la noche entera con sus rutas.
- **Ensayo en seco (nube, `--dry-run`, 4 brazos con un brazo de exploración `true`, 5 min):** 852 peticiones, 0 errores, bucle p50 145 ms / p95 397 ms; 57 caducadas en el arranque en frío.
- **No es conversión.** Sirve para medir en el leaderboard cuánto vende lo que lfm no prioriza.

### E-420 — Reproducción y regresiones del fallo de precios del snapshot de lfm (T-042), 14 nov 22:45 UTC
- **Etiqueta:** OBSERVED DATA (código). Rama `javi/snap-price-fix`.
- **Reproducción** (`tests/test_snap_prices.py::test_the_reported_reproduction`), precios [10, 30, 80]: sin correcciones `cheap` = [1, 0, 0] y `p40` = [0, 0, 1]; con cualquier diccionario de correcciones no vacío (válido, con ids desconocidos, con valores no finitos o que no cambian ninguna calidad) el código de `6150ffc` daba [0, 0, 0] en los dos.
- **Arreglo:** el buffer pasa a llamarse `corrected_lq` y los precios se leen solo del catálogo (`"price" in c.columns`). Pesos, firmas, política y transporte sin cambios. 10 líneas de `recsys/lfm.py`.
- **Por qué no lo vieron los tests anteriores:** `tests/test_lfm_cold_arm.py` usa pesos sin `p40` ni `segcheap` y compara control y retador dentro del mismo snapshot, que estaba mal para los dos.
- **Tests nuevos (13; 9 fallan con el código antiguo, todos pasan con el arreglo; 263 en total):** umbrales (5, 19,99, 20, 20,01, 39,99, 40, 40,01, 80), precio ausente o ilegible = 20, catálogo sin columna de precio; correcciones ausentes, vacías, válidas, sin efecto, desconocidas, NaN, ±inf y texto; indicadores idénticos en todos esos casos; puntuaciones y listas del control idénticas entre un snapshot construido sin correcciones y otro construido con ellas; home, peticiones sin vistas y usuarios conocidos bajo `cold_new` iguales al control limpio; contra el snapshot limpio solo cambian `lq` y `seglq` del producto corregido; vectores de solo lectura y separados; compras, stock y la exclusión del writer se respetan en los tres brazos; un test de guarda comprueba que en ese escenario los pesos de precio sí mueven listas; las tres políticas `policy.fix_*.json` pasan la validación del writer con etiquetas nuevas.
- **Comando:** `python -m unittest discover -s tests` → 263 tests, OK.

### E-421 — Replay con datos reales: qué cambia el arreglo con los mismos pesos (T-042), 14 nov 22:48 UTC
- **Etiqueta:** OBSERVED DATA / diagnóstico. **No es conversión.** Hecho en la nube, no en el Mac.
- **Método** (`recsys/snap_price_replay.py`, sobre `cold_lq_replay.py`): 6.527 peticiones respondidas entre las 19:07 y las 22:44 UTC (1 de cada 8). Para cada una, catálogo, stock, correcciones y estado del comprador a la hora de la petición (44 snapshots; evidencia orgánica solo de tramos de 10 minutos ya cerrados). Cada petición se puntúa dos veces con los mismos pesos: con los indicadores de precio que construye la clase `Snap` de `6150ffc` (cargada de git y ejecutada con las mismas entradas) y con los del código nuevo. Nada más difiere.
- **Indicadores frente al catálogo:** código antiguo, 44 de 44 snapshots mal (161.402 indicadores distintos del catálogo; `p40` y `cheap` valen 0 en los 5.400 productos). Código nuevo, 0 distintos: de media 1.989 productos por encima de 40 EUR y 1.679 por debajo de 20, igual que el catálogo de cada instante.
- **Listas (brazo r3):**

| Cohorte | Peticiones | Listas distintas | Primer slot distinto | Productos sustituidos por lista | Impresiones < 20 / 20–40 / > 40 EUR, antes → después |
|---|---|---|---|---|---|
| Conocidos, producto/categoría | 3.708 | 82,8% | 7,8% | 0,59 | 53,2 / 20,7 / 26,0 → 56,7 / 23,0 / 20,3 |
| Nuevos, producto/categoría | 1.549 | 86,8% | 11,5% | 0,97 | 55,9 / 16,6 / 27,5 → 63,7 / 17,4 / 18,9 |
| Conocidos, home | 883 | 82,2% | 6,6% | 0,53 | 53,2 / 20,5 / 26,3 → 56,6 / 22,2 / 21,2 |
| Nuevos, home | 387 | 89,1% | 11,9% | 0,97 | 56,3 / 17,6 / 26,1 → 64,3 / 18,2 / 17,5 |
| Todas | 6.527 | 84,1% | 8,7% | 0,70 | 54,1 / 19,5 / 26,4 → 58,8 / 21,2 / 20,0 |

  La mayoría de los cambios son de orden: el conjunto de 10 productos cambia en el 51% de las listas. El segmento sensible al precio (android en Andalucía, Canarias o Murcia) es donde más se nota en usuarios nuevos: en páginas, 98,8% de listas distintas, 29% de primeros slots y 2,8 productos por lista; las impresiones por debajo de 20 EUR pasan del 61% al 89% (168 peticiones).
- **Otros brazos, misma muestra:** `cn1` y `np1` cambian como r3 (84% y 86%); `np2` 89%; `og1` en conocidos de páginas solo 28,9% de listas y 1,0% de primeros slots (sus pesos de precio son casi nulos), pero su home y sus usuarios nuevos usan r3 y cambian igual que r3. La cuota de productos lanzados durante el evento apenas se mueve (r3 0,27% → 0,23%; `np1` en conocidos 7,8% → 7,3%; `np2` 48,1% → 47,5%; `cn1` en nuevos 2,8% → 3,3%).
- **Validez:** 100% de listas válidas antes y después en los 5 brazos (10 productos distintos, en catálogo, con stock, no comprados).
- **Latencia de `slate` (contenedor de la nube):** antes p50 0,85 / p95 1,72 / p99 3,57 ms; después 0,84 / 1,70 / 3,50 ms (32.635 llamadas cada uno). Sin coste.
- **No reconstruido:** retraso de refresco del writer (20 s catálogo y eventos, 1 s stock), resolución de 10 minutos de la evidencia orgánica, el slot de exploración y las compras hechas a través de nuestro carrusel.
- **Salida completa:** `/mnt/project-files/precios-snapshot/replay_e420.json` (carpeta del proyecto).
- **Conclusión:** el arreglo restaura las features y cambia la gran mayoría de las listas de todos los brazos, también del control. Que eso convierta más no está demostrado: hace falta lectura en el leaderboard (D-420).

### E-422 — Ensayo en seco del writer real con el arreglo (T-042), 14 nov 22:55–23:11 UTC
- **Etiqueta:** OBSERVED DATA. Nube, `live.py --dry-run` (el transporte rechaza cualquier escritura), una ejecución tras otra. Nada escrito en RawTree; el writer del Mac no se tocó. Un hilo auxiliar comparó cada 20 s `LF.snap.p40` y `LF.snap.cheap` con los precios del catálogo que el propio writer tenía cargado.

| Política | Minutos | Peticiones | Errores | Bucle p50 / p95 / p99 (ms) | Comprobaciones de precio | Indicadores distintos del catálogo |
|---|---|---|---|---|---|---|
| noche (`r3`, `og1`, `np2`, `cn1`; 400 correcciones) | 5,5 | 972 | 0 | 148 / 384 / 580 | 11 | 0 |
| `policy.fix_a_cold_new.json` (400 correcciones) | 3,5 | 612 | 0 | 172 / 383 / 770 | 5 | 0 |
| `policy.fix_b_np1.json` | 3,5 | 616 | 0 | 177 / 373 / 908 | 6 | 0 |
| `policy.fix_champion.json` | 2,8 | 493 | 0 | 201 / 359 / 1.034 | 4 | 0 |

- En todas, 1.985 productos con `p40` y 1.753 con `cheap` de 5.400. Con el código de `6150ffc` las dos primeras darían 0 y 0.
- Caducadas: 53–58 por ejecución, todas en los primeros 30 bucles (arranque en frío del contenedor, igual que en E-280 y E-390); 0 después.
- Etiquetas internas servidas, como se esperaba: en la fase A `v3-lfm-r3p-k/-kh/-n/-nh` y `v3-lfm-cn1p-n` (el resto del tráfico del brazo `cn1p` sale como control); en la fase B las cuatro de `r3p` y las cuatro de `np1p`. Con una sal de prueba cada una recibió su código nuevo.
- Un `stock refresh failed ReadTimeout` aislado en la segunda ejecución (consulta a RawTree), sin efecto en las respuestas.
- **Límite:** el p99 de la nube no es el del Mac. No mide conversión.
### E-430 — Variantes de carritos de un solo brazo para la rotación (T-043), 14 nov 23:40 UTC, contenedor en la nube

`OFFLINE ESTIMATE` + diagnóstico. `recsys/cart_variants.py` (`fit`, `replay`, `check`). Datos de solo lectura hasta las 23:03 UTC. Nada desplegado.

- **Tabla de base (feedback propio, conocidos en páginas con vistas, 11:09–23:03 UTC, 1.140 compras), compras por 10.000 impresiones por tipo de producto y puesto (1 / 2–3 / 4–5 / 6–7 / 8–10):** carrito de la categoría de la sesión 158 / 63 / 34 / 23 / 17; carrito de otra categoría 53 / 30 / 19 / 9 / 11; misma subcategoría 30 / 20 / 11 / 11 / 4; misma categoría 30 / 14 / 11 / 9 / 7; categoría propia del usuario 29 / 13 / 9 / 5 / 3; relleno (otra categoría) 4 / 3 / 2 / 1 / 1. Entre usuarios con 15 o más carritos pendientes, el carrito de otra categoría NO vende más que un producto de la categoría de la sesión (58 / 35 / 22 frente a 62 / 44 / 17). El relleno ocupa 167.500 de 800.000 impresiones y da 30 compras.
- **Lectura:** lo que falta no es "más carritos" sino (a) los carritos de la categoría de la sesión arriba (r3 pone 0,57 en los tres primeros puestos) y (b) quitar el relleno. Subir solo `chn` (cx3) deja además los carritos de HOY (`cl` 0,63) por debajo de los del histórico.
- **Repetición a fecha de cada petición (9.352 peticiones desde las 17:00 UTC, 5.309 de conocidos en páginas; catálogo, stock y estado anteriores a cada petición).** Contra r3, conocidos en páginas:

| variante | listas que cambian | puesto 1 cambia | productos sustituidos | carritos por lista | carritos de sesión en top 3 | relleno | estimación estratificada | modelo paramétrico |
|---|---|---|---|---|---|---|---|---|
| r3 | 0 | 0 | 0 | 3,08 | 0,57 | 16,3% | 0 | 0 |
| cx3 (en rotación) | 90,4% | 48,5% | 2,71 | 5,51 | 0,84 | 10,3% | +0,30 pp | −0,19 pp |
| og1 (en rotación) | 100% | 53,3% | 3,95 | 5,08 | 0,71 | 10,9% | +0,16 pp | −0,16 pp |
| **cs2r** | 99,6% | 53,5% | 4,65 | 4,54 | 1,17 | 0,1% | +0,62 pp | −0,11 pp |
| **ogsr** | 100% | 58,7% | 4,87 | 5,52 | 1,11 | 0,7% | +0,57 pp | −0,15 pp |
| **cs4r** | 99,9% | 50,0% | 3,64 | 5,28 | 1,02 | 1,5% | +0,48 pp | −0,09 pp |
| **cx6l** | 95,6% | 62,1% | 4,26 | 7,10 | 0,89 | 6,8% | +0,41 pp | −0,22 pp |
| **fsr** | 91,7% | 40,3% | 4,07 | 2,36 | 0,72 | 1,0% | +0,31 pp | −0,10 pp |
| cx3l | 92,4% | 47,6% | 2,92 | 5,91 | 0,86 | 9,4% | +0,34 pp | −0,07 pp |

  Usuarios nuevos y home: 0 listas cambiadas en todas (comprobado). Sobre todo el tráfico cambian el 52–57% de las listas.
- **Los dos estimadores no coinciden en el signo y ninguno es conversión.** "Estratificada" = tasas por (carritos pendientes del usuario × tipo × puesto) de la tabla de arriba aplicadas a la lista nueva; supone que el quinto producto de un tipo vende como los que r3 eligió (optimista). "Modelo" = logística sobre las mismas impresiones con rasgos del usuario; el puesto y la puntuación de r3 son casi colineales, así que penaliza cualquier lista que no sea la de r3 (pesimista: en el hold-out de 20:00–23:03 predice 328 compras frente a 291 y sobrevalora los carritos de otra categoría, 81 frente a 57). Sirven para ordenar las variantes entre sí; el veredicto es equipo − referencia en el leaderboard.
- **Intentado y descartado:** pesos ajustados solo a compras del feedback propio (con o sin rasgos del usuario) ordenan peor el hold-out que r3 (MRR 0,41–0,54 frente a 0,55): el puesto absorbe la señal. Ordenar carritos con un modelo propio no cabe en `policy.json` (los pesos son comunes a carritos y no carritos; solo `chn` y `cl` son propios del carrito): necesita código y reinicio.
- **Ensayo con el camino del writer (`check`: `clean_lfm_arms` → `set_arms` → `LiveFit.slate`, 1.590 peticiones desde las 21:00 UTC por política):** las 6 políticas aceptadas enteras, 100% de listas válidas (10 distintas, en stock, no compradas), mismo resultado que el camino rápido de `replay` (0 diferencias). Latencia de `slate` en el contenedor: p50 1,3 ms, p95 2,5 ms, p99 3,5–3,7 ms, igual que r3 (1,35 / 2,73 / 3,98).
- **Brazo `nc2` del hilo de auditoría (`w.new.cl` 2,2), mismo replay:** en usuarios nuevos en páginas cambia el 42,3% de las listas (puesto 1 el 20,0%), carritos por lista 0,58 → 0,94, peticiones con carritos y ninguno mostrado 27,4% → 14,1%. Tal como está escrito también cambia el 40,8% de las listas de home de usuarios nuevos; con `"home": {"file": "lfm_coef_r3.json"}` se queda en páginas.
- **Tests:** `tests/test_cart_variants.py` (2): el writer acepta cada política entera, un solo brazo, sin `lq` ni exploración, y usuarios nuevos y home puntúan exactamente como r3.
- **Salida:** `/mnt/project-files/variantes-carritos/replay_e430.json`.

### E-440 — Feature `hot` de lfm (producto de una subcategoría en ráfaga) — 2026-11-14 23:45 UTC, Javi (agente, T-044)
- **Medición (LIVE FEEDBACK, 115.240 peticiones servidas por el equipo, 14 nov):** ver I-440. Promociones de categoría (−20%, 2 h): en contexto ×1,77 (64 compras frente a 36 esperadas), fuera de contexto ×1,05; no se añade señal.
- **Detector (`trends.py`, sin cambios) repetido sobre los eventos del día en pasos de 5 min:** detecta las 6 ráfagas, entre 5 y 15 minutos después del inicio, sigue marcando unos 10 minutos tras el final, 0 falsos positivos.
- **Código:** `lfm.FEATS` gana `hot` (índice 22, peso 0 en todos los ficheros); `LiveFit.set_catalog(..., hot=)`; `live.hot_products()` consulta `trends.snapshot` en el hilo de refresco solo si algún brazo da peso a `hot` (`LiveFit.wants_hot`), y devuelve None si no hay ráfaga, si falla o si el conjunto supera el 10% del catálogo.
- **Tests:** 6 nuevos en `tests/test_lfm_hot.py`, 256 en total.
- **Ensayo en seco (nube, 1.200 peticiones reales, ráfaga simulada en Game Consoles, 46 productos):** 0 listas inválidas en r3 y t15; latencia por lista p50 0,9 ms / p95 1,5 ms en ambos. Productos calientes por lista r3 → t15: conocidos en páginas 0,05 → 1,34, nuevos en páginas 0,03 → 1,27, home 0,02–0,09 → 1,2–1,3, usuarios en contexto 0,5–0,7 → 3,9–5,3. Primer puesto cambia en el 14% de las listas fuera de contexto. Con el detector real y sin ráfaga: 1,05 s por ciclo de refresco, conjunto vacío, listas idénticas. Con r3 solo no hay consulta.
- **No es conversión.** Solo se puede medir en el leaderboard durante una ráfaga.
### E-460 — Re-carritos: un producto carrito del histórico pierde puntos al volver a carritarse hoy (T-046, 14 nov 23:55 UTC)

- **La interacción:** `lfm.features` pone `chn` a 0 en los productos del carrito de hoy. Un carrito del histórico vale `w_chn × log1p(n)` y, al volver a carritarse hoy, pasa a valer `w_cl`. Con cx3 (chn 3,0, cl 0,63) un producto carritado una vez baja de 2,08 a 0,63 puntos (−1,45). Con r3 (chn 0,73) solo afecta a los carritados 2 veces o más (−0,17 con 2).
- **Candidato:** opción de brazo `"recart": true` (apagada por defecto): suma `max(0, w_chn × log1p(n) − w_cl)` a esos productos, es decir, conserva el mayor de los dos aportes. Solo conocidos en producto/categoría con vistas. El contador sale de `LiveFit.hcart`. Ni `features()` ni `user_state()` cambian. Políticas: `policy.rot_cx3rc.json` (cx3 + opción) y `policy.rot_r3rc.json`.
- **Replay con el código del writer** (`recsys/recart_replay.py`: `clean_lfm_arms` → `set_arms` → `LiveFit.slate`, catálogo, stock y estado a fecha de cada petición; 12.459 peticiones del 14 nov 12:00–23:32 UTC). El 17,2% de las peticiones de conocidos en páginas tiene algún re-carrito servible (1,53 de media).

| pareja | cohorte | listas que cambian | slot 1 cambia | top 3 cambia | productos sustituidos | re-carritos en lista (control → candidato) | re-carrito en slot 1 | peticiones que muestran alguno |
|---|---|---|---|---|---|---|---|---|
| cx3 → cx3rc | conocidos en páginas | 12,9% | 3,5% | 7,7% | 0,11 | 0,055 → 0,162 | 0,24% → 3,78% | 5,1% → 13,2% |
| cx3 → cx3rc | ídem, con re-carritos (1.201) | 75,3% | 20,6% | 44,6% | 0,62 | 0,32 → 0,94 | 1,4% → 22,0% | 29,8% → 76,9% |
| r3 → r3rc | conocidos en páginas | 2,1% | 0,4% | 0,9% | 0,004 | 0,119 → 0,124 | 3,1% → 3,5% | 10,1% → 10,4% |
| r3 → r3rc | ídem, con re-carritos | 12,3% | 2,3% | 5,4% | 0,025 | 0,69 → 0,72 | 18,2% → 20,4% | 58,7% → 60,2% |

  Home de conocidos (1.790), nuevos en páginas (2.983) y nuevos en home (702): 0 listas cambiadas en las dos parejas. Validez 100% en los cuatro brazos (10 productos distintos, en stock, no comprados). Latencia de `slate`: cx3 p50 1,03 / p99 3,29 ms, cx3rc 1,02 / 3,27 ms.
- **Dato lateral:** cx3 enseña MENOS re-carritos que r3 (en el 30% de las peticiones que los tienen, frente al 59% de r3), porque sube los carritos solo históricos por encima.
- **Lo que vendió nuestro carrusel** (69.933 peticiones de conocidos en páginas, 14 nov 12:00–23:32 UTC, listas elegidas por los brazos en vivo: observado y seleccionado, no causal). Compras por 10.000 impresiones:

| tipo de producto mostrado | slot 1 | slots 2–3 | slots 4–10 | impresiones | compras |
|---|---|---|---|---|---|
| re-carrito (histórico y hoy) | 199,5 | 73,3 | 34,0 | 6.696 | 56 |
| carrito solo histórico | 99,1 | 41,4 | 17,0 | 151.451 | 567 |
| carrito solo de hoy | 54,2 | 38,4 | 10,9 | 17.510 | 44 |
| sin carrito | 27,6 | 11,4 | 5,3 | 480.345 | 377 |

  A igual slot el re-carrito vende el doble que el carrito solo histórico. Son 56 compras y el usuario que re-carrita es distinto del que no, así que no demuestra el efecto del cambio de orden.
- **No es conversión.** Es una hipótesis de política. Se decide en el leaderboard: cx3rc contra cx3 (su control) y la referencia en ventanas idénticas, sin sustituir a cx3 a mitad de su serie.
- **Tests:** 10 en `tests/test_lfm_recart.py` (260 en total): contadores 1/2/5, nunca baja una puntuación, comprados por historia / eventos de hoy / feedback del carrusel, stock, cohortes fuera del objetivo idénticas, opción apagada idéntica al control, estado y features sin cambios, ventana de día, y la opción sobrevive a la instalación de `alt` que hace la recarga validada del PR #42.

### E-470 — Entrada orgánica de la calidad: regresiones (T-047, 15 nov 00:15 UTC, contenedor en la nube)

- **Comando:** `python -m unittest tests.test_organic_quality` → 20 tests OK; suite completa `python -m unittest discover -s tests` → 339 OK (308 antes).
- **Qué cubren** (stream y feedback simulados que responden a las dos consultas reales del writer; ninguna red):
  - una compra del carrusel entra en `BOUGHT`, en `bought_in` y en las tablas de usuario, y la tasa orgánica del producto no se mueve; con la tabla antigua sí subía;
  - una compra orgánica sube la tasa exactamente a (compras + K·prior) / (vistas + K), K = 100;
  - las dos tablas difieren exactamente en las compras del carrusel deduplicadas por usuario y producto (mismo usuario dos veces, usuario que además compró orgánicamente, producto fuera de catálogo);
  - cuatro lecturas seguidas no duplican; un arranque nuevo reconstruye las mismas cuentas;
  - fallo de la consulta de eventos y fallo de la de feedback: las cuentas se conservan y la recuperación no duplica; si falla la primera lectura de feedback, la siguiente vuelve a ser completa;
  - el envoltorio de `LIVE.add` que instala D-130 sigue viendo todas las compras;
  - sin brazo `lq` no se calcula nada y las puntuaciones son idénticas al campeón; sin compras del carrusel las dos tablas son iguales.
- **Límite:** no hay replay con datos reales del tamaño del efecto por petición; el tamaño es el de I-470.

### E-471 — Un reintento con `ConnectTimeout`: tests y simulación con fallos inyectados (T-047, 15 nov 00:20 UTC)

- **Tests:** `python -m unittest tests.test_connect_retry` → 11 OK. Fallo de conexión y luego éxito (misma carga, plazo medido de nuevo, `acknowledged`); `ReadTimeout`, `Timeout`, `ConnectionError`, `HTTPError`, `TimeoutError` y desconocidas con cero reintentos; sin margen (más de 2,0 s) no se reintenta; dos fallos de conexión paran en dos intentos; fallo ambiguo en el segundo intento queda `uncertain` y la misma petición no se vuelve a enviar ni tras reabrir el diario; las 25 combinaciones de dos resultados dan como mucho un envío que pudo llegar al servidor; `--dry-run` no envía ni reclama; los adaptadores de `requests` siguen con 0 reintentos.
- **Medida real del Mac (hilo de despliegue, log del 14 nov, OBSERVED DATA):** 13:19–20:20 UTC, 15 lotes `ConnectTimeout` (48 peticiones) y 60 `ReadTimeout` (135) sobre 42.416 lotes; 21:54–23:59 UTC, 0 `ConnectTimeout` y 31 `ReadTimeout` (72) sobre 11.861 lotes. Los 15 son probablemente del despliegue de las 13:19 con el Mac en reposo (sin confirmar). Última hora: POST p50 321 / p95 447 / p99 516 ms; edad de la petición más vieja al confirmar p50 1.198 / p95 1.843 / p99 2.297 ms.
- **Simulación** (`python tools/connect_retry_sim.py --minutes 120`; ejecuta `serving.serve` y `live.send_answers` reales sobre un reloj virtual, 21.700 peticiones por fila, mismos números aleatorios en todas; calibrada con las cifras de arriba: edades simuladas 1.193 / 1.928 / 2.330 ms). Salida completa en `/mnt/project-files/reintento-envio/sim_e471.txt`. OFFLINE ESTIMATE:

| fallos de conexión inyectados | a tiempo sin reintento | con reintento ≤ 1,6 s | ≤ 2,0 s | ≤ 2,2 s | reintentadas / recuperadas (2,0 s) | llegadas tarde (> 3 s) | peticiones siguientes a tiempo, sin → con (2,0 s) |
|---|---|---|---|---|---|---|---|
| ninguno | 99,566% | 99,566% | 99,566% | 99,566% | 0 / 0 | 0 | — |
| 0,035% por intento (tasa del Mac de día) | 99,510% | 99,524% | 99,543% | 99,543% | 12 / 12 | 0 | 100% → 100% (53) |
| 1% por intento | 98,573% | 99,298% | 99,483% | 99,506% | 212 / 209 | 0 | 99,63% → 99,56% (≈850) |
| 5% por intento | 94,657% | 98,042% | 98,970% | 99,118% | 1.017 / 979 | 0 | 99,73% → 99,59% (≈3.650) |
| corte de 0,5 s cada ~60 s | 98,725% | 99,136% | 99,099% | 99,196% | 145 / 75 | 0 | 99,04% → 99,64% (≈540) |
| corte de 2 s cada ~60 s | 96,481% | 97,035% | 97,114% | 97,141% | 523 / 65 | 0 | 99,11% → 98,58% (≈720) |
| corte de 1 s cada ~30 s con POST ×1,6 (cola) | 93,548% | 94,310% | 94,841% | 94,864% | 543 / 159 | 0 | 99,32% → 98,84% (≈1.350) |

- **Lectura:** el reintento nunca hizo llegar tarde una respuesta en ningún umbral (el plazo se vuelve a medir). Con fallos sueltos recupera casi todo; en un corte largo recupera poco porque el segundo intento cae en el mismo corte. El coste para las peticiones de detrás es de 0,1 a 0,5 puntos de las que llegan justo después de un fallo, siempre menor que lo recuperado: el total a tiempo sube en las siete filas. 2,2 s gana algo más que 2,0 s pero es el máximo que cabe con un POST p99; se deja 2,0 s como pedía el encargo.
- **Límites:** es un modelo (retardo del stream y POST lognormales), no el Mac. Con la tasa actual del Mac (0 `ConnectTimeout` desde las 21:54 UTC) el efecto esperado es prácticamente nulo: lo que falla hoy es `ReadTimeout`, que no se reintenta porque el servidor pudo aceptar el envío. No se ha medido con un fallo de conexión real de `requests` contra RawTree.

### E-472 — Modo `cold_known` (calidad corregida solo para conocidos): regresiones (T-047, 15 nov 00:20 UTC)

- **Tests:** 6 en `tests/test_organic_quality.py` (`ColdKnownTests`): regla de cohorte (espejo de `cold_new`; `cold` y `cold_new` sin cambios), exige un control con pesos idénticos, no se mezcla con `cold_new` sin control, control / nuevos / home idénticos al campeón en puntuación y lista, solo se mueve el producto lanzado, y la ruta usa la misma regla que la puntuación (no existen etiquetas `ck1-n`, `ck1-kh`, `ck1-nh`; el tráfico no tratado sale idéntico al control solo).
- **Evidencia previa (dato del encargo, replay en sombra, 504 peticiones de conocidos en producto/categoría, 14 nov 23:10–23:15 UTC):** cuota de lanzamientos en la lista r3 0,26%, con corrección de calidad 7,64%, np2 52,46%; todas las listas válidas. Cambia la composición; no mide conversión.
- **No medido:** conversión, ni latencia en vivo. Sin activar.
## E-490 — La calidad orgánica sustituye a `lq` (T-049, 2026-11-15 01:30 UTC)

- **Pregunta:** ¿predice `lq` (qrank, carrusel histórico) lo que se compra mejor que la tasa orgánica del producto? T-018 tomó `q` como verdad y midió cuánto la reproducía el stream; nadie había medido las dos contra nuestras compras.
- **Datos:** feedback propio 14 Nov 11:09–23:44 UTC, 135.828 peticiones, 1,36 M impresiones, 2.112 compras, 5.800 clics (`recsys/lab_build.py`). Solo productos con historia.
- **Método:** logit condicional dentro de la petición (qué producto de los 10 se compra / clica), con indicadores de puesto y la puntuación de r3 sin su término de calidad (`z0`). Ajuste antes del corte, verosimilitud después. Variables: `lq`; tasa orgánica 60 d `log((p+1)/(v+20))`; vistas `log(v+5)`.
- **Resultado en muestra (desde 13:00 UTC):** con tasa y vistas en el modelo el coeficiente de `lq` cae a 0 (nuevos 0,03 ± 0,10; conocidos −0,06 ± 0,10; home −0,59 ± 0,31). Ganancia de log-verosimilitud sobre r3: nuevos +32,7 (707 compras), conocidos +30,7 (806), home +10,4 (107). Coeficientes relativos a `z0`: nuevos tasa 2,1 / vistas 0,33; conocidos 0,71 / 0,64; home 1,0 / 0,62.
- **Fuera de muestra (ajuste < 17:00, prueba ≥ 17:00), ganancia sobre el modelo con `lq`, IC 95% por bootstrap de peticiones:** nuevos en página compras +25,4 [11,9; 39,1] (n 469), clics +30,1 [14,2; 46,3]; conocidos en página compras +21,9 [9,2; 34,5] (n 574), clics +55,9 [36,2; 77,1]; home compras +18,0 [2,7; 33,7] (n 82), clics +15,5 [5,4; 25,5]. Con corte 19:30 mismo signo en todo salvo home compras (+0,6, n 55).
- **Solo stream de hoy (unas 10 h):** también gana a `lq` (nuevos +23,1 [10,3; 36,1]; conocidos +15,1 [2,3; 26,6]). Para productos lanzados basta el stream.
- **Lo que NO lo confirma:** el MRR del producto comprado dentro de la lista servida no mejora (−0,005 a +0,017); esa medida premia el orden que ya sirvió r3 (puesto y puntuación colineales, E-430). Dos features con residuo fuerte en estos mismos registros (`mf`, `cv`) empataron o perdieron en vivo.
- **Repetición de peticiones (E-490 replay, 3.028 peticiones desde 17:00 UTC, ruta del writer):** `oq1` 100% válidas, cambia el 100% de las listas, 7,0 de 10 productos en común con r3, puesto 1 distinto en 31% (home conocidos) a 47% (nuevos en página); latencia p50 1,34 ms / p99 3,8 ms (r3 1,34 / 4,0). Productos lanzados por lista 0,03 → 0,2 (con `lq` a 0 dejan de estar en la mediana de subcategoría y se mueven con su tasa del stream). `oqh` (mitad): puesto 1 distinto en 19–28%, 8,0–8,4 en común.
- **Valor, estimación de modelo (no conversión):** con el modelo que incluye la calidad orgánica, `oq1` +8% relativo (nuevos en página +9,6%, conocidos en página +5,7%); con el modelo de r3, −6%. La evidencia fuera de muestra apoya al primero; decide el leaderboard (equipo − referencia).
- **Descartado en la misma pasada:** (a) carritos de hoy de usuarios nuevos: el 65% de los pendientes no se enseña y los enseñados venden 209–648 por 10k en el puesto 1, pero con controles el plus de carrito es 1,0–1,8 logit frente al 1,1 que ya da r3 y el MRR apartado no mejora; (b) subcategorías vistas hoy (19 → 94 por 10k en tabla): coeficiente −0,03 ± 0,08 con la afinidad en el modelo.
- **Tests:** 8 en `tests/test_lfm_oq.py`: peso 0 idéntico al control en todas las páginas, orden por tasa, producto lanzado neutro en vistas, cierre seguro ante entradas raras, las tres políticas pasan `clean_lfm_arms`, y `organic_counts` lee historia + acumulador orgánico (nunca compras del carrusel).

### E-491 — Criba sistemática encima de la calidad orgánica: `mf` en conocidos y `aff10` en nuevos (T-049, 02:15 UTC)

- **Método:** el mismo logit condicional dentro de la petición con puesto controlado; 37 señales candidatas de una en una sobre la base (r3 sin `lq` + calidad orgánica), ajuste < 17:30 UTC y verosimilitud después, IC por bootstrap de peticiones.
- **Pasan (IC fuera de muestra sin el cero):** conocidos en página `mf` +20,2 [8,7; 30,1] en compras y +45,1 [26,5; 64,5] en clics; `bsub` +4,2 [0,7; 8,4]; `cv` +3,0 [0,5; 5,4]. Nuevos en página `aff10` +8,2 [4,0; 11,6] en compras y +8,3 [4,8; 11,9] en clics. Nada más pasa: precio, descuento, marca, popularidad de la última hora, edad del carrito, vistas de hoy, carrito × categoría de sesión.
- **Ajuste conjunto (coeficientes relativos a la puntuación de r3):** conocidos: tasa orgánica 0,5, vistas 0 (las absorbe `mf`), `mf` 0,16 (z 7,1; r6 llevaba 0,063), `bsub` +0,39. Nuevos: tasa 2,4, vistas 0,55, `aff10` +1,3 sobre el 0,88 de r3.
- **Ganancia total fuera de muestra sobre r3 con `lq`:** conocidos +47,0 [30,8; 63,4] (511 compras; corte 20:00 +26,0 [13,9; 37,6]); nuevos +31,9 [19,6; 43,6] (431; corte 20:00 +22,4 [12,3; 31,9]).
- **Sin código nuevo (solo `policy.json` sobre el writer actual):** `mf` 0,15 y `bsub` 0,3 encima de r3 en conocidos en página: +35,8 [22,0; 50,1] (corte 20:00 +22,7 [11,0; 33,6]). En nuevos, subir `aff10` sin la calidad orgánica no gana (−0,1 [−5,5; 5,6]). En home `mf` empeora (−10,8 [−20,7; −1,6], 37 compras): no se toca home.
- **Por qué r6 "empató" (E-274):** llevaba `mf` a 0,063 y se leyó con brazos paralelos (±0,4 pt por ronda).
- **Políticas:** `policy.rot_mf1.json` (r3 + mf 0,15 + bsub 0,3 en conocidos en página; válida HOY sin reinicio), `policy.rot_mf1cs.json` (lo mismo sobre cs2r), `policy.rot_oq2.json` (calidad orgánica + mf + bsub en conocidos, + aff10 1,9 en nuevos; necesita este PR). Repetición de 2.049 peticiones: 100% válidas; `mf1` solo cambia conocidos en página (puesto 1 distinto en 43%, 7,4 de 10 en común); `oq2` puesto 1 distinto en 49–51%. Latencia igual que r3.


## E-500 — Bot único: qué pieza entra, con peticiones reales y compras apartadas (T-050, 15 nov 00:30 UTC) — OFFLINE ESTIMATE

`python recsys/unified_eval.py targets` (salidas en `/mnt/project-files/bot-unico/targets_e500*.json`). 13.816 peticiones respondidas del 14 nov seguidas de (a) una compra ORGÁNICA del mismo comprador en los 30 minutos siguientes de un producto servible, o (b) una compra en nuestro carrusel. Cada una se vuelve a puntuar con catálogo, stock, estado, conteos orgánicos y ráfagas a fecha de la petición. `org@10` = parte de las compras orgánicas que caen en el top 10 de la variante (no las ordenó nuestro modelo); `fb@10` = lo mismo con compras del carrusel (sesgado a favor de lo que ordenó la lista, sirve de suelo).

- **Validación de la medida con lo ya leído en vivo:** conocidos en página, org@10 r1 12,0% < r2 12,2% < r3 14,5% (orden del leaderboard). Límite: cuenta igual cualquier compra orgánica y el carrusel no: el 41% de las compras del carrusel de conocidos son carritos de la categoría de la sesión y solo el 7% de las orgánicas. Por eso penaliza a cs2r (13,3%, −1,3 ± 0,4) más de lo que le toca; ponderando cada acierto ganado por compras de carrusel por acierto orgánico de su tipo bajo r3, cs2r queda en empate o ligera ganancia (+34 compras equivalentes sobre 1.049).
- **Calidad orgánica (T-049) gana en todos los grupos y encima de cualquier base.** Sobre r3: conocidos/página 14,5 → 18,3 (+3,8 ± 0,4), nuevos/página 10,4 → 12,4 (+2,0 ± 0,5), home conocidos 16,0 → 17,5 (+1,5 ± 0,6), home nuevos +0,4 ± 0,9. Productos lanzados hoy: conocidos 1,5% → 10,7%, nuevos 0% → 12,8% (125 objetivos). Sobre cs2r (dosis `orate` 1,6, `mf` 0,3, `bsub` 0,3): org@10 13,3 → 16,5 (+3,2 ± 0,3), fb@10 82,0 → 87,6 (+5,6 ± 1,0), lanzados 0,3% → 3,3%.
- **Tendencias (`hot` 1,5, páginas):** +0,1 ± 0,1 conocidos, +0,3 ± 0,15 nuevos; en ráfaga nuevos +1,4. `hot` 3,0 empeora. En home no aporta: fuera de home.
- **Fuera:** `nc2` (nuevos: org +0,1 ± 0,2, fb@3 −5,1 ± 1,0); og1 / ogsr (org igual que la calidad orgánica sobre r3 pero pierde 8–14% de las compras del carrusel); re-carritos (bajo cs2r cambia 3% de listas, E-510); una señal nueva "carrito de la categoría de la sesión" (cualquier dosis baja org y fb, y el logit condicional de E-491 le da coeficiente 0) no se añade; `cold_new` / `cold_known` corrigen `lq`, que aquí pesa 0. `aff10` 1,9 en nuevos no mejora org@3.

## E-501 — Bot único por el camino del writer: validez, listas cambiadas y latencia (T-050)

`python recsys/unified_eval.py check policy.unified.json policy.rot_cs2r.json policy.unified_nocarts.json` (`clean_lfm_arms` → `set_arms` → `LiveFit.slate`, 4.111 peticiones desde las 17:00 UTC del 14 nov, estado a fecha de cada una; salida `/mnt/project-files/bot-unico/check_e501.json`).
- **Válidas 100%** en los cuatro grupos y en ráfaga. Latencia por lista p50 1,24 ms, p95 2,4, p99 3,8 (r3: 1,26 / 2,4 / 3,9).
- **Frente a r3:** cambia el puesto 1 en 56% de conocidos/página, 49% de nuevos/página, 31% de home conocidos y 41% de home nuevos; en común 5,5–7,2 de 10.
- **Composición en conocidos/página (r3 → cs2r → u1):** carrito de la categoría de la sesión 12,1% → 24,7% → 19,7%; relleno 15,7% → 0,2% → 3,9%; categoría propia 22,6% → 2,9% → 12,2%. La calidad orgánica devuelve parte de lo que cs2r quitaba.
- **Lanzados por lista:** conocidos/página 0,04 → 0,22; nuevos/página 0,01 → 0,32. **Productos de la subcategoría en ráfaga por lista, en ráfaga:** conocidos 0,08 → 0,78; nuevos 0,09 → 0,98.

## E-502 — Ensayo en seco del writer y ensayo de la final con `policy.unified.json` (T-050)

- `RAWTREE_DRY_RUN=1 python live.py --dry-run` 330 s en la nube: `{"event": "policy"}` con el brazo u1, sin `policy_rejected`, 0 errores, `{"event": "hot"}` presente, 455 peticiones, bucle p50 292 ms / p95 484 ms, 0 caducadas tras el arranque.
- `python tools/final_rehearsal.py --n 500`: 0 respuestas inválidas en los 8 escenarios (comprador nuevo, sin vistas, producto nuevo, metadatos rotos, cambio de categoría, choque de stock, RawTree sin responder); todas con etiqueta `v3-lfm-u1-*`; p99 por petición ≤ 6,6 ms.

## E-520 - Unified-bot correctness audit (T-052, 15 Nov 2026, Codex)

**Evidence: SYNTHETIC REGRESSIONS / CODE AUDIT, not a conversion experiment.** Branch `codex/unified-bot-audit`, base `16e14c6`. No writer started and no live policy changed.

Reproduced before fixing:
- Organic events for a launch absent from the latest catalogue were discarded by `LiveTables.add_organic`. The event cursor then advances, so a later catalogue refresh cannot recover them. Organic product counters now retain those trusted stream events independently of category metadata; slate eligibility still requires the catalogue and stock checks. Per-user category tables retain their existing gate.
- `unified_eval.bursts` used the whole-day median, including later buckets. Appending future data changed past burst flags in a regression. It now uses only the preceding three hours, excluding the current bucket, with three prior 10-minute buckets required. The evaluator remains a coarse proxy; it is not the production detector.
- Its burst cache used only the first catalogue's product mapping, dropping later launches from trend calculations. It now refreshes that mapping when it changes.
- Target ranks used `count(score > target_score) + 1`, crediting every tied product with the best rank. A synthetic 80-way tie falsely reported 100% hit@10 and hit@3; corrected results are 12.5% and 3.75%. Evaluation now shares the deployed top-N selector, including tie order and stock-shock repair. The serving selector algorithm itself is preserved.

Validation:
```text
python -m unittest discover -s tests -q
Ran 360 tests: OK (skipped=8)

python tools/bench_unified_audit.py --base 16e14c6
seed=520; 5,400 products; 1,000 cases
identical slates=1,000; valid=1,000
selector p95/p99 ms: before 5.9802/6.9490; after 6.1438/7.2054
```
The benchmark alternates call order and includes tied scores, non-finite exclusions and stock shocks. It measures synthetic selection only, not inference or network latency. Test portability fixes close a reopened SQLite handle before temporary-directory cleanup and compare paths using POSIX separators on Windows.

**Limitations:** E-500 target-retrieval tables must be recomputed; none were rerun against team caches here. Organic purchase retrieval is a proxy for carousel response; feedback is exposure-biased; repeated users/purchase targets make naive standard errors optimistic. The coarse trend proxy cannot validate exact detection latency. No measured online conversion uplift, full-slate counterfactual estimate or production end-to-end p95/p99 is claimed.

## E-522 — Revisión de la auditoría E-520 y recálculo de E-500 (T-050 / T-052, 15 nov 01:10 UTC)

**OFFLINE + lectura de RawTree; no es un resultado en vivo.** Rama `javi/unified-audit-integration` = `codex/unified-bot-audit` (65d5d0b) revisada línea a línea. 360 tests OK; `tools/bench_unified_audit.py`: 1.000/1.000 listas idénticas y válidas.

- **Recalculo de E-500** (`unified_eval.py targets --base cs2r`, mismo caché y misma rejilla que `targets_e500_on_cs2r.json`; salida `/mnt/project-files/bot-unico/targets_e520_on_cs2r.json`): **todas las cifras iguales a la centésima** en todos los grupos (conocidos/página 13,27 → 16,46 con la dosis de u1, +3,19 ± 0,33; nuevos/página 10,39 → 12,36; fb@10 sin cambio). Motivo: (a) las puntuaciones son continuas, no hay empates en el borde del top 10 con datos reales (el caso de 80 empatados es sintético); (b) el proxy causal de ráfagas solo cambia 3 de 34 cubos de 10 minutos (Aquariums 10:10, 10:20 y 11:30 UTC), fuera de las peticiones evaluadas; (c) el catálogo de la evaluación ya traía los lanzamientos. Ninguna decisión de piezas ni de dosis cambia.
- **Pérdida de eventos orgánicos de lanzamientos en el writer:** el fallo existe (un lanzamiento que aparece entre `refresh_catalog()` y `refresh_events()` del mismo ciclo pierde los eventos de esos segundos), pero medido en `shop.events` del 14 nov: 400 lanzamientos, 0 eventos anteriores al alta en `catalog_updates`, 21 eventos en los primeros 5 s y 145 en los primeros 30 s, de 179.554 eventos de productos lanzados (0,08% como cota superior; la ventana real son los ~2 s entre las dos consultas, en uno de cada ~15 ciclos). En un arranque el catálogo se carga antes del relleno de eventos, así que no se pierde nada. **No justifica un reinicio por sí solo**; entra en el próximo reinicio planificado. Los consumidores de `organic_frame` (`attr_model`, `live_quality`, `cold_items`, `lfm.organic_quality`) reindexan al catálogo: una fila de un producto aún sin metadatos no les afecta.
- **Límite:** el proxy de ráfagas de `unified_eval` sigue sin servir para elegir ventanas del detector (I-521 usa `trends.compute`, que no tenía la fuga).
`python recsys/unified_eval.py check policy.unified.json ...` (`clean_lfm_arms` → `set_arms` → `LiveFit.slate`, estado a fecha de la petición). Primera pasada (4.111 peticiones desde las 17:00 UTC, versión sin carritos y versión con carritos a dosis 0,8): 100% válidas en todos los grupos; latencia por lista p50 1,3 ms, p95 5,0, p99 7,8, igual que r3. Cambia el puesto 1 en ~49% de las listas de nuevos en página. Pasada de la política final: ver el PR.

## E-530 — Dosis y momento de las ráfagas en nuestro carrusel (T-053, 15 nov 01:00 UTC) — LIVE FEEDBACK, muestras pequeñas

Feedback propio de las 7 ráfagas del 14 nov (Aquariums 09:30, Kettles 11:30, Cutting Boards 13:30, Bike Helmets 15:30, Game Consoles 19:30, Face Cream 21:30, Vitamins 23:30 UTC), 132.982 listas servidas por el equipo; "con contexto" = alguna vista reciente en la categoría de la subcategoría en ráfaga.

- **Forma:** escalón exacto en `shop.events`: vistas ×4 desde el minuto :30:00 hasta el :15:00, sin rampa. En el carrusel, productos calientes: 12–15 compras por 10.000 impresiones antes, 117 / 149 / 158 en los minutos 0–5 / 5–10 / 10–15, 66–97 hasta el 45, 35 y 20 después.
- **A quién:** con contexto (11% de las peticiones en ráfaga) 30 compras frente a 2,7 esperadas a igual puesto y tipo de usuario (×11); sin contexto 3 frente a 1,9 (clics 12 frente a 6). Fuera de ráfaga (placebo) 5 frente a 5,1 y 4 frente a 4,6. Home: 2 compras en 488 impresiones (0,8 esperadas).
- **Cuántos y dónde (con contexto):** conversión de la lista con 0 calientes 0,72% (3.600 listas), 1: 3,04% (691), 2: 4,83% (331), 3–4: 5,73% (227), 5 o más 4,55% (22). Caliente en el puesto 1: 6,93% (274) frente a 1,26% (4.597). Calientes en los puestos 4–10: 9 compras frente a 0,54 esperadas. Sin contexto, caliente en el puesto 1: 1,59% (126) frente a 1,66%.
- **Qué productos:** el alza de vistas es igual para todos los productos de la subcategoría (×3,7–4,5 en la mitad más vista y ×3,8–5,6 en la otra); venden los que ya vendían (correlación compras antes / durante 0,80–0,96; el 20% de productos reúne el 60–73% de las compras). Los lanzados hoy venden como el resto. Basta el orden que ya da `orate`.
- **Límite:** quienes vieron productos calientes los eligió el modelo (afinidad); el efecto sobre usuarios sin contexto a dosis alta es HYPOTHESIS.

## E-531 — u1 a varias dosis de `hot`, repetición por el camino del writer con ráfaga perfecta (T-053) — OFFLINE, exposición, no conversión

`clean_lfm_arms` → `set_arms` → `LiveFit.slate`, estado a fecha de la petición, conjunto caliente = subcategoría real durante sus 45 minutos (4 ráfagas, 4.037 peticiones, 100% válidas en todas). Calientes por lista / caliente en el puesto 1:

| Grupo | u1 (3 / 1,5) | u1t (6 / 3, home 1) | u1c (u1 + `hotc` 9) |
|---|---|---|---|
| conocido, última vista en la subcategoría | 5,4 / 55% | 8,7 / 84% | 10,0 / 100% |
| conocido, categoría en las vistas | 3,0 / 26% | 6,2 / 61% | 9,6 / 97% |
| nuevo, última vista en la subcategoría | 5,2 / 83% | 8,1 / 100% | 10,0 / 100% |
| nuevo, categoría en las vistas | 2,4 / 43% | 4,9 / 74% | 10,0 / 100% |
| conocido sin contexto (página) | 0,3 / 4% | 2,4 / 19% | 0,3 / 4% |
| nuevo sin contexto (página) | 0,8 / 9% | 3,1 / 50% | 0,8 / 9% |
| home | 0,1 / 1% | 0,5–0,8 / 5–12% | 0,1 / 1% |

## E-532 — Detector rápido repetido sobre todo el 14 nov (T-053)

`python recsys/trend_fast_replay.py` (necesita los agregados por minuto; solo lectura): `trends.compute` + `trends.fast_hot` cada minuto de 09:40 a 00:50 UTC. Regla de 15 minutos: entra en el minuto 4–8 y sale en el 52–56. Rápido (3 minutos, alza 2,5, z 8, 50 vistas; se mantiene con alza 1,5 y z 3): entra en el minuto 2–3, sale en el 46–47, 43–44 de los 45 minutos cubiertos, 0 minutos marcados fuera de las 7 ráfagas.

## E-540 — Vistas de peticiones anteriores (T-054, 15 nov 01:30 UTC)

**OBSERVED DATA / LIVE FEEDBACK.** Las `recent_views` de una petición no aparecen en `shop.events` (la última vista de la petición coincide con la última vista orgánica del usuario en el 0,09% de 110k peticiones): son una fuente aparte que el writer solo usaba para la petición en curso.

- Carrusel histórico (política antigua, exposición aleatorizada, 29 oct–14 nov, 5,1 M impresiones, páginas): producto sin historial orgánico del usuario, fuera de las vistas actuales y presente en las vistas de una petición anterior: 56,4 compras por 10k impresiones ponderadas por puesto frente a 12,6 (x4,5; 125 compras; 15,8 para la misma subcategoría sin haberlo visto). Plano por puesto. Por antigüedad: <24 h 80–86, 1–3 días 60, 3–10 días 45, >10 días 42. Por repeticiones: 1 → 46, 2 → 75. Como referencia, estar en las vistas actuales: 104.
- En vivo, conocidos en páginas (14 nov desde 16:00 UTC, productos sin historial orgánico, vistas de 24 días de `history_sessions`): 65 frente a 31 por 10k (40 compras, 19 esperadas); fuera del contexto de la sesión 51 frente a 17,7; clics x1,7. Carritos pendientes: x1,15 (sin evidencia; la feature vale 0 en ellos).
- En vivo, nuevos en páginas, visto en una petición anterior del mismo día: 369 frente a 65 por 10k (13 compras, 2,3 esperadas a igual puesto); clics x3,5. Solo se mostraba en el 10% de las peticiones con sesión previa.
- Home: sin evidencia (1 compra); la política lo deja a 0.
- Alcance: 99% de los conocidos tienen productos así (mediana 34 en 24 días); 43% de las páginas de nuevos y 61% de las de conocidos tienen una petición previa en el evento.
- Descartado en la misma pasada: reposición de stock (64 → 68 compras orgánicas por millón de vistas globales, sin efecto), promociones de categoría (productos sin carrito 32 → 35 por 10k; carritos de la categoría x1,4, 60 compras).

**Corrección (01:45 UTC), con control de afinidad:** la mayor parte del múltiplo en bruto es afinidad de categoría. Logística por impresión con puesto, cuota de categoría del usuario, contexto de sesión: conocidos +0,22 ± 0,16 a +0,36 ± 0,19 en compras y +0,37 ± 0,09 en clics por producto visto en el histórico; nuevos +1,0 ± 0,5 a +1,65 ± 0,7 en compras y +0,74 a +0,94 ± 0,25 en clics por producto visto en una petición anterior del día. El hilo de nuevos obtiene +0,77 ± 0,23 (nuevos) con las señales de u1. En el histórico aleatorizado, dentro de cada tramo de cuota de categoría, x2,3–x3,2. Dosis: nuevos 0,8, conocidos 0 (`policy.unified_prv_cold.json`, u1v) o 0,5 (`policy.unified_prv.json`, u1p). Los pesos 3,0–4,5 iniciales no tienen apoyo y se retiran.

**Limitación:** el efecto en vivo está medido sobre lo que el modelo ya decidía mostrar. Vuelta atrás en caliente: `policy.unified_hotc.json`.

## E-550 — Compras y clics del carrusel histórico (T-055, 15 nov 02:05 UTC)

**LIVE FEEDBACK, con controles.** `shop.history_sessions.purchased` (18.587 pares usuario-producto en 60 días) no está en los eventos orgánicos: el modelo veía esos productos como carritos pendientes o productos sin tocar. El 54% también se compró orgánicamente y sigue excluido (3 compras en 3.079 impresiones en todo el día: muerto, como siempre).

- Conocidos, 14 nov desde 16:00 UTC, logística por impresión con puesto, carrito, veces carritado, contexto de sesión, vistas actuales y cuota de categoría: comprado en el carrusel histórico +1,61 ± 0,14 en compras (109 compras en 4.350 impresiones) y +1,46 ± 0,09 en clics; solo clicado +0,40 ± 0,15 y +0,45 ± 0,11. Home: +0,88 ± 0,59 compras, +1,72 ± 0,52 clics.
- Dentro de las mismas peticiones (quita la propensión del usuario, que aquí es alta: sus otros carritos venden 258 por 10k en el puesto 1): carrito comprado antes en carrusel 512 frente a 258 en el puesto 1, 210 frente a 104 en 2–3, 101 frente a 51 en 4–6; no carrito 279 frente a 71 en 2–3, 123 frente a 41 en 4–6. Es decir x2 sobre otro carrito y x3–5 sobre un no carrito.
- Sin decaimiento por antigüedad (0–7 días 13/543, 40–61 días 32/1.030).
- Alcance: 13,8% de las peticiones de conocidos tienen al menos un candidato no comprado orgánicamente; hoy aparece en el 43% de ellas y en el puesto 1 en un tercio de esas.
- Estimación (conjetura): +0,05 a +0,15 puntos de conversión total.

Features `hcb` / `hcc` (peso 0 = inertes), fichero `data/hist_carousel.parquet` (`download_prev_views.py`). Política `policy.unified_hcb.json` (u1h = u1v + hcb 3,0 y hcc 0,8 en páginas de conocidos, hcb 1,5 en home). La dosis está en la escala de cs2r (chn 3,0) y no se ha pasado por repetición.

## E-610 — Deriva de la exposición de lanzados y tope por lista (T-061, 15 nov 05:40 UTC) — OFFLINE, exposición, no conversión

Repetición de 5.006 peticiones (desde las 04:00 UTC) por el camino del writer sobre `policy.rot_u3nh.json`, 5 tandas de 100 lanzados vigentes.

- Lanzados por lista hoy: páginas de conocidos newp 0,5 → 0,93; 1,0 → 1,35; 2,0 → 2,53 (49% de las listas con 3 o más). Home de conocidos newph 0,5 → 0,89. Home de nuevos newph 0,5 → 0,67; 0,8 → 1,41 (eran 0,81 con 400 lanzados). Páginas de nuevos sin refuerzo 0,62.
- Cada tanda aporta más o menos lo mismo y la edad no la apaga (aportes por tanda con newp 1,0: 0,33 / 0,24 / 0,28 / 0,08 / 0,41), así que la exposición de una dosis fija crece con el número de tandas: x1,2 con 6 y x1,4 con 7 (extrapolación lineal, conjetura).
- Tope `newcap` (clave del brazo, por segmento `known` / `new` / `home_known` / `home_new`; ausente = sin tope): `lfm.cap_launched` deja a −inf todos los lanzados menos los `c` mejores antes de elegir la lista; los que el comprador ha visto en la sesión o tiene en un carrito no se quitan y cuentan para el tope. Con las dosis de u3nkh (1,0 / 0,5 / 0,8): sin tope 1,35 / 0,89 / 1,41 por lista y 17% / 6% / 16% de listas con 3 o más; tope 2: 0,99 / 0,78 / 1,14 y 0,3% (solo productos propios); tope 1: 0,58 / 0,56 / 0,69. Con el triple de dosis (deriva exagerada): sin tope 4,1 / 4,1 / 8,9 por lista; tope 2: 1,7 / 1,9 / 2,0. El resto de la lista conserva su orden en las 5.006 peticiones; +0,2 ms por lista; ninguna lista inválida.
- No hay medida de conversión del tope: es un seguro contra el fallo conocido de inundar la lista (np2, 4,3 por lista), no una mejora medida. El tope 2 ya cambia hoy el 25% de las listas de páginas de conocidos y el 18% de las de home de nuevos respecto a la política probada en vivo; el tope 3 cambia el 10% de las de páginas de conocidos, el 2,5% de las de home de conocidos y el 7% de las de home de nuevos (1,21 / 0,86 / 1,32 por lista) y deja pasar más deriva.

## E-620 — Sombra del prior de atributos dentro de `orate` (T-062, 15 nov 07:20 UTC) — DIAGNÓSTICO, no conversión

`python attr_prior_shadow.py policy.rot_ug1.json --n 3000 --since "2026-11-15 02:00:00"`: 3.122 peticiones respondidas entre las 02:00 y las 07:10 UTC, puntuadas con catálogo, stock, estado y conteos orgánicos a la fecha de cada petición por el camino del writer (`clean_lfm_arms` → `set_arms` → `LiveFit.slate`), una vez con `uf1` y otra con `ug1` (`uf1` + `oqa: ["new", "home_new"]`).

| segmento | peticiones | válidas (ambos) | listas cambiadas | slot 1 cambiado | solape de 10 | lanzados por lista uf1 → ug1 |
|---|---|---|---|---|---|---|
| conocidos, home | 451 | 100 % | 0 % | 0 % | 10,00 | 0,67 → 0,67 |
| conocidos, página | 1.765 | 100 % | 0 % | 0 % | 10,00 | 0,60 → 0,60 |
| nuevos, home | 195 | 100 % | 35,9 % | 2,6 % | 9,81 | 1,10 → 1,17 |
| nuevos, página | 711 | 100 % | 24,5 % | 1,5 % | 9,87 | 0,53 → 0,60 |

- Latencia p50 / p99: 1,72 / 4,38 ms (uf1), 1,74 / 4,42 ms (ug1). Prior calculado para los 500 (02:00) y 600 (07:10) productos sin histórico, 0 en fallback.
- Nivel: el prior de los lanzados vale 0,007 / 0,022 / 0,067 (p10 / p50 / p90), igual que el del catálogo histórico (0,007 / 0,022 / 0,080). La fórmula actual los deja a todos en 0,05, que no es la mediana del catálogo: la mediana de `(p+1)/(v+20)` histórica es 0,017 (0,053 es la tasa agregada). Hoy, por tanto, todo lanzado entra 1,07 en `orate` por encima de la mediana (+1,9 puntos de score con peso 1,8). Con la opción, el lanzado mediano baja 0,85 y solo los del decil alto suben: **la opción cambia el nivel medio de los lanzados además de ordenarlos**, y una prueba en vivo leería las dos cosas juntas.
- Lo que no dice: nada sobre conversión. Cambia en torno a 0,15 productos por lista de usuario nuevo.

**E-621 (07:23 UTC), misma sombra sobre el main ee2955c:** `policy.rot_ug2.json` (uf2 frente a ug2) y `policy.rot_ug2n.json` (uf2n frente a ug2n), 3.122 peticiones. 100 % válidas, conocidos idénticos en las dos. Nuevos en página (sin tope en uf2): 27,0 % de listas cambiadas, slot 1 1,5 %, solape 9,85, lanzados por lista 0,62 → 0,70. Nuevos en home: 35,9 %, 2,6 %, 9,81, 1,10 → 1,17. La sombra no reconstruye `prv` (vale 0 en los dos brazos). Variante con el nivel compensado (devolver 0,85 × peso por `newp`/`newph`) descartada sin medir: es un cambio de dosis de lanzados sin tope en página, justo lo que salió mal con newp 2,0.
