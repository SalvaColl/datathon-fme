# Shared insights, hypotheses, tests and discarded ideas

**Living team notebook.** `challenge.md` is for verified organizer facts; use this file for hypotheses, actual observations and what failed. **Do not delete ideas** after experimentation — change status to `REJECTED`/`SUPERSEDED` and link to evidence.

Statuses: `IDEA`, `INVESTIGATING`, `SUPPORTED`, `REJECTED`, `SUPERSEDED`, `BLOCKED`. A hypothesis is not `SUPPORTED` merely because it seems plausible. Add owner, date and experiment ID with results when available.

## Verified facts that changed our approach (from official specification)

| Insight | Evidence | Implication |
|---|---|---|
| ~**3 requests/second**; deadline 3 seconds from request `ts` to insertion at RawTree | [Official README](https://github.com/rawtreedb/datathon-fme-2026) | Optimize throughput and latency of polling + batched writer; not a leisurely single-request API |
| ~**2M historical carousel logs** with `shown`, `propensity`, `clicked`, `purchased`; **12M organic events** | Official README | Historical ranking is feasible; avoid exposure and position bias |
| Scoring: **50 conversion, 10 cold, 10 reliability, 30 jury** | [Challenge](https://datathon.rawtree.dev/) | Need real offline method and explainable pipeline; conversion primarily beats price/revenue |
| Conversion uses **hidden expected probability**, not random observed purchase count | Official FAQ/README | Feedback is noisy; avoid chasing tiny short-term win/loss fluctuations |
| Cold requests include new user OR request with a newly added product in `recent_views` | Official README | New-product description/category embedding becomes high priority |
| **New shoppers/products/trends** introduced in Sunday final 10:00–12:00 CET; leaderboard dark | Official README | Generalization and live adaptation matter more than memorized old IDs |
| Valid submission means **exactly 10 distinct active IDs**, ordered, submitted once | Official README | Stock cache and atomic last-minute eligibility check are mandatory |
| **Starter offline notebook** contains IPS estimation of historic click rates | Official repo | Use as an initial *proxy* estimator and inspect variance/support, not a guaranteed oracle for full-slate conversion |
| OpenAI/Claude coding agents **allowed**, team must explain work | Official FAQ | Keep code and validation understandable to jury |

## Hypothesis registry (UNTESTED unless evidence attached)

### I-001 — Strong personalized heuristic vs static best sellers
- **Status:** INVESTIGATING — offline support (Javi, 2026-11-14, E-002/E-003); live test pending
- **Evidence so far:** viewed-in-session items convert 13× more than other shown items; same subcategory 2.4×; user's past cart on the item is the strongest within-session signal (see I-010…I-014). Live baseline realized conversion 0.62% (3,219 feedback rows) vs 1.7% for the old historical system.
- **Hypothesis:** Recent views, co-views, subcategory/brand affinity and organic purchase history beat the starter's all-time best sellers.
- **Test:** B0 vs B1 on temporally separated `history_sessions`, particularly product-page sessions and cold requests; live results if safe to deploy.
- **Risk:** Historical exposure bias; noisy old users; profile leakage.
- **Owner/evidence:** TBD / no team experiment yet.

### I-002 — Live trends from organic `shop.events`
- **Status:** IDEA (data source confirmed; effect untested)
- **Hypothesis:** Recent category/subcategory momentum improves predictions under moving trends and generalizes to final round.
- **Test:** Compare global historic vs 15-min/1-hour/3-hour smoothed trends, sliding chronological holdout and live ablation; compare high-traffic and low-traffic categories.
- **Risk:** Seasonal noise, biased buyer mix and few purchases; 50/s organic stream may make views stronger signal than own carousel feedback.
- **Owner/evidence:** TBD / no team experiment yet.

### I-003 — Optimize slots and slate diversity
- **Status:** IDEA (position effect is official, diversity benefit untested)
- **Hypothesis:** Rank strongest items early; optionally penalize close substitutes so ten-item carousel covers relevant alternatives.
- **Test:** Fixed candidates/no penalty vs soft penalty; compare click/purchase proxies and category-specific slices.
- **Risk:** Strongly category-focused shoppers might convert better on similar items.
- **Owner/evidence:** TBD / no team experiment yet.

### I-004 — Bounded Thompson Sampling or Bayesian exploration
- **Status:** IDEA (feedback available; attribution/statistics not yet validated)
- **Hypothesis:** A tiny exploration allocation helps react faster to new products and taste shifts.
- **Test:** Reproducible shadow + carefully controlled live test against greedy ranker; report realized conversion uncertainty and cold performance.
- **Risk:** Rewards may be one purchase/slate and highly dependent on slot; uncontrolled exploration harms reliability/conversion.
- **Owner/evidence:** TBD / no team experiment yet.

### I-005 — Supervised gradient-boosted ranking
- **Status:** INVESTIGATING — offline support (Javi, 2026-11-14, E-003): within-session hit@1 0.49–0.52 vs 0.31 logged order; implemented in `recsys/` (sklearn HistGradientBoosting; LightGBM needs libomp, not installed)
- **Hypothesis:** Purchase-prediction ranker based on context, recent views, product metadata, history and organic signals beats engineered weights.
- **Test:** LightGBM/CatBoost vs logistic/heuristic with time-split evaluation, IPS support checks, calibration and cold-start ablation.
- **Risk:** Historical best-seller exposure/position bias; new product distribution shift; train/inference cost.
- **Owner/evidence:** TBD / no team experiment yet.

### I-006 — PPO isn't first priority
- **Status:** IDEA, **DEFERRED** for engineering priority; not an experimental rejection
- **Hypothesis:** Deep RL is slower/less robust than ranker + online bandit without access to a faithful simulator; purchase propensity mostly an immediate contextual objective.
- **Test:** Only reconsider with a realistic simulator and evidence of long-term sequential reward advantage.
- **Risk:** Wasting scarce build hours and overfitting to an imagined simulator.
- **Owner/evidence:** TBD / no team experiment yet.

### I-007 — Content-based cold start
- **Status:** IDEA (new product descriptions and cold-start score confirmed)
- **Hypothesis:** TF-IDF/text embeddings + category/brand/price priors make new-item ranking competitive with no interactions.
- **Test:** Simulate product launches with temporal held-out catalogue products and compare to only subcategory/popularity priors.
- **Risk:** Description text may be generic; embeddings may not separate simulated buyer preferences.
- **Owner/evidence:** TBD / no team experiment yet.

### I-008 — Inventory freshness more valuable than marginal ranker quality
- **Status:** IDEA (invalid-slate penalty confirmed)
- **Hypothesis:** Fast stock-update ingestion and strict eligibility validation produce a larger effective score gain than a small model AUC boost.
- **Test:** Measure fallback `invalid` rate under different stock refresh cadences, in replay/stress tests and live feedback.
- **Risk:** Extra RawTree query overhead; ensure freshness without violating deadline.
- **Owner/evidence:** TBD / no team experiment yet.

### I-009 — Historical propensity-aware evaluation
- **Status:** INVESTIGATING (method provided by organizers; not yet run by team)
- **Hypothesis:** Controlling for old-policy exposure helps select challengers better than naive replay, if full-slate support and effective sample size are adequate.
- **Test:** Examine `starter/offline_eval.ipynb`; compare naive metric vs clipped IPS, effective sample size, variance, temporal slices and compatibility with purchase vs click reward.
- **Risk:** Per-slot propensities may not give usable support for unseen slates; extremely high-variance inverse weights. Never claim unbiased conversion from invalid estimator.
- **Owner/evidence:** TBD / public notebook exists, no team experiment yet.


## Data findings — Javi, 2026-11-14 (history_sessions 15 Sep–14 Nov, 1.99M sessions; scripts in `recsys/explore_*.py`)

### I-010 — The old carousel is category-locked; home page is the dead zone
- **Status:** SUPPORTED (descriptive)
- **Evidence:** every non-home historical slate has all 10 items in the category of the last viewed product (1.59M sessions); 100% of clicks/purchases with views are in that category. Home = 20% of sessions, always zero `recent_views`, conversion 0.14% vs 1.71% (category page) / 1.72% (product page). Live stream mix (last 5k requests): 56% product, 24% category, 20% home; ~30% `is_new_user`.
- **Weakness:** "always same category" is the logging policy, so we cannot tell from history how much cross-category items would sell.
- **Implication:** non-home: candidates from last-viewed category. Home: personalise from organic user history (70% of live users appear in `history_events`).

### I-011 — Items already viewed in the session sell ~13× more
- **Status:** SUPPORTED (observational, 3.2M shown-item rows)
- **Evidence:** purchase rate per shown item 1.95% if viewed in session vs 0.15% otherwise; last-viewed item 2.0%. 16% of purchases are a product viewed earlier in the session, but only 13% of old slates contained any viewed item. Same subcategory as last view 0.34% vs 0.14% (2.4×); same brand 0.26% vs 0.16%.
- **Weakness:** confounded with interest; still a strong ranking feature.

### I-012 — Strong position effect
- **Status:** SUPPORTED
- **Evidence:** purchase rate by slot (items with views): 0.54%, 0.28%, 0.22%, 0.15%, 0.12%, 0.10%, 0.09%, 0.08%, 0.07%, 0.07%. Slot 1 ≈ 8× slot 10 (partly popularity of what the old system put first).
- **Implication:** put the highest-probability item first; order matters more than the tail.

### I-013 — Past add-to-cart by this user on this item is the top within-session signal
- **Status:** SUPPORTED (model importance, E-003)
- **Evidence:** permutation importance on the purchase model: user total activity, user×category purchases, user×item add-to-cart, item cart rate, same category, slot. Purchase always equals the click (100%): one purchase max per request.

### I-014 — Live session/feedback facts
- **Status:** SUPPORTED
- **Evidence:** at ~12:45 CET the team baseline writer was serving ~70% of requests (`served_by=team` 1,285 vs `fallback/missing` 515 in 10 min) → the starter's 50-row window/poll loop is losing requests; reliability is 10 pts. Last hour to ~13:15: team writer p95 latency **2,933 ms**, 1,370 of 4,573 answers replaced by fallback; leaderboard 11:46–12:46: team_26 on-time 40.4%, conv 0.643% vs baseline 0.664%, organisers' reference 2.19% (cold 1.87%). `catalog_updates` by 13:00: 620 price changes, 100 new products, 90 out-of-stock, 54 back-in-stock.

### I-015 — Live-feature refresh must be incremental
- **Status:** SUPPORTED (dry-run measurement)
- **Evidence:** rebuilding all live user tables every 20 s pushed request age to p95 2.2 s / max 2.87 s in one window; incremental dict tables + 1.8 s deadline guard → p95 0.9–1.5 s, max 1.9 s over 300 requests.

### I-016 — The leaderboard is a noise-free, 10-minute A/B instrument
- **Status:** SUPPORTED (Javi, 2026-11-14 13:05)
- **Evidence:** the page is fed by public JSON `https://datathon.rawtree.dev/api/state` (mode, window, per-team `requests`, `conversion`, `cold_conversion`, `on_time`, `revenue_per_request`, `model_version`, plus `baseline`, `reference`, hourly `progress`). Conversion = hidden-model *expected* purchases on every request of the rolling last hour (~10.8k requests), recomputed every 10 min.
- **Implication:** consecutive snapshots differ by (new 10-min block − dropped block)/6 → with the logged series (`recsys/lb_logger.py` → `recsys/data/lb_history.jsonl`) we can recover each 10-min block's exact expected conversion and compare versions without purchase noise. Always compare *relative to the `baseline` row* of the same window (stream drift moves it: 0.632 → 0.639 between two updates).
- **Reference benchmark:** 2.11% conversion, cold 1.82%, **€1.10/request** vs baseline €0.18 → the reference sells items averaging ~€52 vs ~€28: it does not shy away from expensive items.

### I-017 — Two writers: the later/other submission often wins
- **Status:** SUPPORTED (13:00–13:08, while baseline writer and v1 ran together)
- **Evidence:** of requests answered by both, feedback `shown` matched the baseline slate 906 times vs v1 531 → with duplicates v1 reached only ~37% of shoppers. Run **one** writer.

### I-090 — La descripción de cada producto son 2 frases de una lista fija de 20, y predicen su conversión
- **Status / date / owner:** SUPPORTED (OFFLINE ESTIMATE + OBSERVED DATA en vivo) · 2026-11-14 · agente de Javi (T-009, rama `javi/cold-items`) · E-090
- **Claim:** todas las descripciones (5.000 del catálogo y las 100 nuevas) son `marca + subcategoría` más exactamente 2 frases de 20 ("great value for money", "organic ingredients", "a minimalist design"…). Qué 2 frases lleva, cruzado con la categoría, explica la mayor parte de la conversión orgánica del producto; subcategoría, marca y precio explican poco.
- **Evidence:** compras por vista orgánica, 60 días: "great value for money" 10,6% frente a "organic ingredients" 2,3%, y el efecto cambia de signo por categoría (p. ej. "compact and lightweight" ×2,2 en Beauty y ×0,4 en Computers). Hold-out de productos (5 folds, N=5.000, 548k compras): Spearman con la conversión real 0,41 (subcategoría), 0,50 (sub+marca+precio), 0,60 (kNN TF-IDF sobre la descripción), **0,84 (GLM de Poisson con frases × categoría)**; devianza explicada 14% / 27% / 40% / **74%**. Lanzamiento real (ajuste con los 5.000, predicción de los 100 productos nuevos, 12.109 vistas y 775 compras en vivo): Spearman 0,50 / 0,50 / 0,59 / **0,68**, devianza 31% / 37% / 43% / **63%**; techo de ruido con esas vistas 0,84.
- **Weakness:** si la final trae frases nuevas el GLM cae a sub+marca+precio (el módulo lo tolera: frase desconocida = peso 0). El 26% restante es calidad propia del producto, solo observable con eventos.
- **What changed:** `recsys/cold_items.py` (prior + actualización bayesiana con eventos en vivo, K=100 vistas). TF-IDF queda como alternativa inferior, no descartada para descripciones con frases nuevas.

### I-091 — v1 nunca pone primero un producto recién lanzado; el prior lo arregla, pero el segmento es pequeño
- **Status / date / owner:** SUPPORTED (OFFLINE ESTIMATE) · 2026-11-14 · agente de Javi (T-009) · E-091
- **Evidence:** simulación de lanzamientos dentro de slates del histórico (20% del catálogo tratado como nuevo, 5 folds, 4.697 sesiones con compra desde el 4 nov, modelo v1 del repo). Cuando lo comprado es un "lanzamiento": hit@1 **0,000** sin contadores (así los ve v1 al salir), 0,004 con prior de subcategoría, **0,133** con el prior de frases, 0,154 con prior + 1 h de eventos, 0,472 con los contadores reales. Peticiones "cold" oficiales (un lanzamiento en `recent_views`, N=1.553): hit@1 0,227 → 0,402 → 0,442. Coste en sesiones donde se compra un producto antiguo: 0,517 → 0,503.
- **Tamaño (OBSERVED DATA):** productos nuevos = 100 de 5.100, 1,5% de las vistas orgánicas; **4,1% de las peticiones** tienen uno en `recent_views` (439 de 10.800, 12:00–13:00 UTC). Los nuevos convierten orgánicamente como los antiguos (6,5% frente a 5,3% por vista). El prior vale más que la primera hora de eventos del propio producto (log-verosimilitud de la hora siguiente: solo prior 738,8; solo eventos 636,2; mezcla K=100 762,2).
- **Implication:** mejora segura pero pequeña (afecta sobre todo a los 10 puntos de cold start). Dry-run en vivo con la tabla extra: 0,03 → 0,24 productos nuevos por slate, p95 1,2–1,5 s. Detalle: `pools["new"]` de `live.py` usa `last_change == "new_product"`, que deja de cumplirse en cuanto el producto nuevo recibe un cambio de precio o stock; `ColdStart.new_ids()` no depende de eso.

### I-092 — Afinidad usuario × frases de la descripción: la señal más fuerte que hemos medido, y v1 no la usa
- **Status / date / owner:** SUPPORTED (OBSERVED DATA orgánica + OFFLINE ESTIMATE + LIVE FEEDBACK) · 2026-11-14 · agente de Javi (T-009) · E-092, E-093
- **Claim:** cada usuario tiene gustos estables sobre las 20 frases. "Afinidad" = fracción de sus vistas orgánicas pasadas que fueron a productos con las mismas frases que el candidato (valor neutro 0,10). Predice la compra de productos que el usuario NUNCA ha tocado mucho mejor que la categoría, la subcategoría o la popularidad.
- **Evidence (tres fuentes independientes):**
  1. *Orgánico, sin sesgo de carrusel, split temporal:* afinidad con vistas anteriores al 15 oct, compras sobre pares usuario–producto vistos por primera vez después (48.592 usuarios, 3,9M pares, 167.527 compras). Compras por vista: 1,6% (afinidad <0,10), 3,3%, 5,6%, 8,4%, 11,7%, 15,9%, **23,4%** (>0,25). El 7,8% del catálogo con afinidad >0,15 concentra el 39% de las compras.
  2. *Slates del histórico (E-092):* multiplicar el score de v1 por exp(20·afinidad) sube hit@1 de 0,472 a **0,519** y hit@3 de 0,755 a 0,809 (N=4.697 sesiones con compra desde el 4 nov; IC 95% de la variante con features reentrenadas +0,012…+0,037). La afinidad sola (0,446) casi iguala a todo v1. Compartir frases con el último producto visto: ×2,2 con una frase y ×6 con las dos (5,2M impresiones, controlado por producto y slot), más que compartir subcategoría.
  3. *Feedback en vivo, modelo oculto (E-093, 21.691 peticiones, 11:09–13:05 UTC):* usuario conocido, producto sin relación previa y fuera de `recent_views`: **0,6 compras por 10.000 impresiones con afinidad <0,10; 1,2; 0,7; 10,0; 18,2; 89,7 con 0,20–0,25** (CTR 0,05% → 1,6%). El 85% de esas impresiones (71.371 de 84.388) tiene afinidad <0,15 y suma 6 compras. La misma pendiente aparece en usuarios sin historial usando solo las vistas de la sesión (4,7 → 143 por 10.000), en lo añadido al carrito y en lo visto en la sesión.
- **Weakness:** en vivo son 36 compras en el segmento principal (los clics, 145, dan la misma forma). No sabemos cómo interactúa con la categoría de la sesión fuera de lo que mostró v1. No hemos medido nada con el leaderboard todavía.
- **What changed:** `recsys/attr_affinity.py` (multiplicador de score + candidatos por afinidad, numpy puro, ~1 ms por petición). Propuesta D-090.
- **Next action:** bloque de 10 min en el writer con la variante `aff` y lectura del leaderboard (I-016).

## Correction register (superseded briefing assumptions)

- **SUPERSEDED:** `~1 request every 3 seconds` -> official **~3 requests/second**.
- **SUPERSEDED:** `leaderboard every hour` -> official **updates every 10 min, rolling last hour**.
- **SUPERSEDED:** `selling more / revenue might be official objective` -> **expected purchases** is core automatic objective; revenue tie-breaker.
- **SUPERSEDED:** `lack of historical data` -> official historical impressions with propensities and organic events are available.
- **SUPERSEDED:** `need to construct full simulator first` -> organizer notebook and real historical logs should be first evaluation target; synthetic league optional for robustness.

## Record a new experiment-derived insight

```markdown
### I-XXX — Description
- **Status / date / owner:** IDEA | INVESTIGATING | SUPPORTED | REJECTED | SUPERSEDED | BLOCKED
- **Claim or hypothesis:**
- **Evidence:** Source link or experiment ID, exact data/time range, sample size and metric
- **Potential confounding/weakness:**
- **What changed:** Strategy, feature, model, or ops
- **Next action:**
```

## Rejected/superseded *tested* ideas

_None tested/rejected by team yet. Corrected assumptions are listed above rather than erased._
