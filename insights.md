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

### I-082 — v1 en vivo malgasta slots: 31% de otra categoría, productos ya comprados, y casi nunca el último visto
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK) — 2026-11-14 14:10 CET — Javi (agente, T-014, rama `javi/rv-first-slate`)
- **Evidence:** E-081. Feedback propio de las peticiones servidas con `v1-gbm-cand` en páginas product/category, 12:01–13:02 UTC: 6.266 peticiones, 84 compras (1,34%; home aparte 0,14%). Por impresión: **otra categoría distinta de la última vista 19.092 impresiones (31%) → 13 compras (0,07%)**; misma categoría no vista 40.729 → 56 (0,14%); misma categoría vista en la sesión 1.721 → 15 (0,87%); **ya comprado hoy por ese usuario 1.118 → 0 compras** (251 veces en el slot 1). El último producto visto solo aparece en el 14% de los slates, y cuando aparece la petición convierte 2,8% frente a 1,15%.
- **Potential confounding/weakness:** qué muestra v1 no es aleatorio; 84 compras. Posible causa: el modelo se entrenó solo con slates de una categoría y extrapola mal con candidatos del historial del usuario en otras categorías (hipótesis, no comprobado en el código que corre en el Mac).
- **What changed:** nuevo ranker `recsys/qrank.py` restringido a la categoría de la última vista y sin lo ya comprado.

### I-083 — El comprador simulado ≈ calidad del producto × contexto; "visto en la sesión" multiplica ×10 en el histórico pero bastante menos en vivo
- **Status / date / owner:** SUPPORTED en histórico (OBSERVED DATA), INVESTIGATING en vivo — 2026-11-14 — Javi (agente, T-014)
- **Evidence:** `history_sessions` desde 25 oct, product/category, 543k sesiones / 5,4M impresiones. Compra por impresión en slot 1: producto visto 6,6% (N=4.663) vs no visto 0,40%; **mismo producto, mismo slot, visto vs no visto: ×10,4** (Mantel-Haenszel, 620 productos, 626 compras), así que no es solo popularidad. El efecto es multiplicativo con la calidad del producto: en el quintil más alto de propensity 12,7% vs 1,1%; en el más bajo 0,24% vs 0,09%. Curva de slot (no vistos): 1 / 0,53 / 0,40 / 0,30 / 0,24 / 0,21 / 0,18 / 0,16 / 0,13 / 0,13.
- **En vivo es más débil:** sobre las impresiones de v1, los vistos compran 0,35× lo que predice el modelo del histórico (15 compras vs 43,4 esperadas) y los no vistos 0,80× (56 vs 70,2). Por eso `qrank` escala los vistos por 0,45 (parámetro `viewed_factor`).
- **Potential confounding/weakness:** el factor en vivo sale de 15 compras; intervalo amplio (aprox. 0,2–0,6).
- **Next action:** recalibrar `viewed_factor` con más feedback; añadir carrito del usuario (I-013) como feature.

### I-084 — La fiabilidad ya no es la brecha; nadie en el leaderboard se acerca a la referencia
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK + leaderboard) — 2026-11-14 13:45 CET — Javi (agente)
- **Evidence:** feedback 12:00–13:00 UTC: 7.977 servidas por el equipo, 39 fallback (29 `invalid` por latencia >3 s, 10 `missing`) → 99,5% a tiempo, latencia p50 1,35 s, p95 2,1 s. El 84% del leaderboard era la hora anterior. Leaderboard 12:44 UTC: referencia 2,05%, mejor equipo 1,03% (team_09), nosotros 0,95% (ventana mixta baseline+v1), baseline 0,70%.
- **Implication:** el margen está en el ranking de product/category (80% del tráfico), no en la fiabilidad. Vigilar el p95 de 2,1 s: queda poco colchón.

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
