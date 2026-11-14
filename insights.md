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

## T-013 — home y usuarios nuevos (agente de Javi, 2026-11-14, rama `javi/home-new-users`; IDs I-13x para no chocar con otras ramas)

### I-130 — En vivo, lo ya comprado y lo "visto y no añadido al carrito" en el histórico NO se vende en el carrusel
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK) · 2026-11-14 12:41 UTC · agente de Javi · E-131
- **Claim:** el modelo oculto en vivo no vuelve a vender un producto que el usuario ya compró, ni uno que vio en los 60 días de histórico sin añadirlo al carrito. Lo añadido al carrito y no comprado es lo que más convierte sin vistas de sesión.
- **Evidence:** feedback propio servido por el equipo, 10.977 peticiones (11:09–12:41 UTC), 109.770 impresiones, relación usuario–producto calculada solo con `history_events` (termina a las 07:00 UTC, antes de la primera petición). Compras por 10.000 impresiones, fuera de `recent_views`: **ya comprado 0,0** (0 compras / 20.702; 12 clics), **visto sin carrito 0,0** (0 / 9.536; 20 clics), sin relación 8,7 (60 / 68.583), **carrito sin compra 27,5** (25 / 9.105). Dentro de `recent_views`: comprado 1 / 411, visto-histórico 0 / 198, sin relación 11 / 1.047, carrito 4 / 188. Compra por clic: un tercio (sin relación 71 de 205, carrito 29 de 88) frente a 1 de 35 clics (comprado + visto).
- **Consecuencia medida:** el 28% de todas nuestras impresiones (30.847 de 109.770) fueron de productos muertos, con 1 compra en total. En `home` con usuario conocido, el 36% (22,6% comprados + 13,8% vistos), y v1 pone un comprado en el slot 1 el 71% de las veces: CTR de v1 en home-conocidos 0,66% (5 / 760) frente al 2,0% del baseline (12 / 599).
- **Contradicción con el histórico (no borrar I-013):** en `history_sessions` home, un producto ya comprado convierte 44 por 10.000 (279 / 63.667) y el efecto es estable las 9 semanas. Orgánicamente los usuarios sí recompran (22% de las compras orgánicas en vivo son de algo ya comprado). Es decir, el log histórico del carrusel y el modelo oculto en vivo difieren en esto; el GBM v1 aprendió `ui_p`/`ui_v` del histórico.
- **Weakness:** 96 minutos de feedback realizado (ruidoso, pero 0 de ~26 compras esperadas es concluyente para "comprado" y 0 de ~8 para "visto"). No sabemos si una vista del stream de hoy cuenta como "rechazo": solo marcamos las del histórico.
- **What changed / next:** `home_cands.HomeCands.drop_dead()` filtra ambos en cualquier página; propuesta D-130. Verificar con un bloque de 10 min en el leaderboard.

### I-131 — Qué convierte en `home`: carrito pendiente, cuota de categoría del usuario y conversión orgánica del producto; el precio no
- **Status / date / owner:** SUPPORTED (OFFLINE ESTIMATE + transferencia a LIVE FEEDBACK) · 2026-11-14 · agente de Javi · E-130
- **Evidence (histórico home, 400.549 sesiones, features estrictamente anteriores al día de la sesión, filas ya compradas excluidas):** las 400.549 slates de home son de una sola categoría (la política antigua elegía categoría casi uniforme). Compras por 10.000 impresiones: carrito sin compra 20,4 (83 / 40.785); cuota de vistas orgánicas del usuario en la categoría del producto >40% → 5,0, 20–40% → 1,3, <5% → 0,08; usuario compró antes en la subcategoría 2,1 frente a 0,45; quintil alto de compras/vistas orgánicas del producto 1,64 frente a 0,12 (más fuerte que la popularidad: 1,17 frente a 0,34). Coeficiente logístico de log-precio −0,02 (nulo).
- **Transferencia a vivo:** en otras páginas, productos sin relación previa: cuota de categoría >40% → 65 por 10.000 (12 / 1.841), <5% → 0 (0 / 15.176); subcategoría comprada 20 frente a 2,6.
- **Weakness:** en home en vivo solo hay 7 compras; la cuota de categoría en otras páginas está confundida con la categoría de la sesión.
- **Implication:** candidatos de home = carrito pendiente + mejores productos (por conversión orgánica) de las categorías/subcategorías afines del usuario; usuario desconocido = mejores productos por conversión orgánica.

### I-132 — Región y dispositivo no cambian QUÉ se compra; los usuarios nuevos compran muy disperso
- **Status / date / owner:** SUPPORTED (OBSERVED DATA) → idea "top por región/dispositivo" **REJECTED** para región, débil para dispositivo · 2026-11-14 · agente de Javi
- **Evidence:** `shop.events` 09:00–12:30 UTC, 11.855 compras orgánicas de usuarios que no están en el histórico: el reparto por categoría es igual en las 10 regiones (±2 puntos, p. ej. Books & Media 20–25%); por dispositivo solo cambia Books & Media (web 32%, ios 20%, android 17%). Las diferencias de conversión de home por región en el histórico (Andalucía 0,26%, C. Valenciana 0,065%) y dispositivo (android 0,22%, web/ios 0,11%) son propensión del usuario, no gusto por productos. Misma conversión orgánica por vista en nuevos y conocidos (5,3%) y mismo top (p_0210c5, p_adc3e6, p_69d40e, p_1036d3…). Top-10 de productos = 6% de las compras de nuevos; top-100 = 27%.
- **Implication:** para usuario nuevo en home no hay palanca de contexto; una lista global tiene techo bajo. Además `live.pull()` no trae región/dispositivo, así que no pedimos ese cambio.
