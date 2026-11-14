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
- **Status:** REJECTED como palanca grande (2026-11-14, T-020; ver R-02 en el tablero): medido en I-080/I-081, ~+0,04 pp. Sigue disponible con puerta estadística (I-181). Antes: IDEA (data source confirmed; effect untested)
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
- **Status:** REJECTED para el horizonte de 2 h (2026-11-14, T-020; ver R-07 en el tablero). Antes: IDEA (feedback available; attribution/statistics not yet validated)
- **Hypothesis:** A tiny exploration allocation helps react faster to new products and taste shifts.
- **Test:** Reproducible shadow + carefully controlled live test against greedy ranker; report realized conversion uncertainty and cold performance.
- **Risk:** Rewards may be one purchase/slate and highly dependent on slot; uncontrolled exploration harms reliability/conversion.
- **Owner/evidence:** TBD / no team experiment yet.

### I-005 — Supervised gradient-boosted ranking
- **Status:** SUPERSEDED por qrank (I-082, E-081) y lfm (I-180, E-180); ver R-05 y R-06 en el tablero (2026-11-14, T-020). Antes: INVESTIGATING — offline support (Javi, 2026-11-14, E-003): within-session hit@1 0.49–0.52 vs 0.31 logged order; implemented in `recsys/` (sklearn HistGradientBoosting; LightGBM needs libomp, not installed)
- **Hypothesis:** Purchase-prediction ranker based on context, recent views, product metadata, history and organic signals beats engineered weights.
- **Test:** LightGBM/CatBoost vs logistic/heuristic with time-split evaluation, IPS support checks, calibration and cold-start ablation.
- **Risk:** Historical best-seller exposure/position bias; new product distribution shift; train/inference cost.
- **Owner/evidence:** TBD / no team experiment yet.

### I-006 — PPO isn't first priority
- **Status:** REJECTED para este datathon (2026-11-14, T-020; ver R-13 en el tablero). Antes: IDEA, **DEFERRED** for engineering priority; not an experimental rejection
- **Hypothesis:** Deep RL is slower/less robust than ranker + online bandit without access to a faithful simulator; purchase propensity mostly an immediate contextual objective.
- **Test:** Only reconsider with a realistic simulator and evidence of long-term sequential reward advantage.
- **Risk:** Wasting scarce build hours and overfitting to an imagined simulator.
- **Owner/evidence:** TBD / no team experiment yet.

### I-007 — Content-based cold start
- **Status:** SUPERSEDED por el prior de frases (I-090: Spearman 0,84 frente a 0,60 de TF-IDF); ver R-14 en el tablero (2026-11-14, T-020). Antes: IDEA (new product descriptions and cold-start score confirmed)
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

### I-080 — Las "tendencias" del stream son ráfagas de subcategoría: escalón de ~45 min, ×4,5 en vistas y más conversión por vista
- **Status / date / owner:** SUPPORTED (OBSERVED DATA, orgánico) — 2026-11-14 13:50 CET — Javi (agente, T-008, rama `javi/live-trends`)
- **Evidence:** E-080. `shop.events` 09:00–12:35 UTC (873k eventos). Dos episodios: **Aquariums 09:30–10:15** (vistas por 5 min ~45 → ~190) y **Kettles 11:30–12:15** (~160 → ~760). Empiezan y acaban de golpe (un bucket de 5 min), afectan a **toda la subcategoría por igual** (los 60 kettles suben ×4–5) y la compra por vista sube a la vez (Kettles 2–3% → 6–7,5%; Aquariums 4,6% → 8%). El resto de las 89 subcategorías no se distingue del ruido de Poisson salvo los 100 productos nuevos de las 10:00 (escalón permanente, no tendencia; eso es T-009).
- **No hay ráfagas así en el histórico:** en `history_events` (60 días, bloques de 30 min) solo aparecen picos aislados de 1 bloque en subcategorías de poco tráfico (285 episodios, 282 de un solo bloque, conversión por vista 4,86% vs 4,96% normal = ruido). Por eso no se puede validar con `history_sessions`; solo con el stream de hoy.
- **Potential confounding/weakness:** N = 2 episodios. No sabemos si en la final duran lo mismo ni si son de subcategoría.
- **What changed:** el detector trabaja a nivel de subcategoría; el lift por producto dentro de la subcategoría no aporta (deviance 1245 → 1233 en 730 filas, 1.396 compras).
- **Next action:** re-ejecutar `python trends_replay.py --pull` esta tarde para sumar episodios.

### I-081 — Durante una ráfaga, también compran esa subcategoría los que NO la estaban viendo (home incluido)
- **Status / date / owner:** INVESTIGATING (OBSERVED DATA orgánico; efecto en el carrusel UNTESTED) — 2026-11-14 — Javi (agente, T-008)
- **Claim or hypothesis:** añadir los mejores productos de la subcategoría caliente como candidatos (sobre todo en `home` y en páginas de la misma categoría) y subir su score durante la ráfaga aumenta la conversión esperada.
- **Evidence:** E-080 parte C. Peticiones de `shop.requests` cuyo usuario **no** tenía esa subcategoría en `recent_views`: compran orgánicamente un producto de la subcategoría en los 10 min siguientes **14 de 13.063 (0,107%) con la subcategoría marcada caliente vs 6 de 43.739 (0,014%) en normal** → ×7,8, Fisher p = 1e-5. Por tipo: home 4/2.631 vs 1/8.555 (×13), misma categoría 3/1.056 vs 2/4.228 (×6), otra categoría 7/9.390 vs 3/30.962 (×7,7). La marca "caliente" se calcula solo con eventos anteriores a cada petición.
- **Potential confounding/weakness:** son compras **orgánicas**, no del carrusel; conteos pequeños (20 compradores). Nuestro feedback no sirve para medirlo: solo 34 kettles mostrados durante la ráfaga, 0 compras. El modelo oculto podría no aplicar el multiplicador de tendencia a quien no la busca. Tamaño: aunque el carrusel capturase todo, es ~+0,1 pp de conversión sobre las peticiones durante ráfagas (≈40% del tiempo hoy) → orden de +0,04 pp global; en `home` (0,14% de base) sería relativamente grande. No es lo que cierra la brecha con el 2,1%, pero es barato y es "aprender del stream" (10 pts de jurado).
- **What changed:** propuesta D-080 (variante `trend` apagable en `policy.json`).
- **Next action:** bloque A/B de 10 min por leaderboard **durante una ráfaga activa** (el detector avisa a los 5 min de empezar; quedan ~40 min de ráfaga).
### I-082 — v1 en vivo malgasta slots: 31% de otra categoría, productos ya comprados, y casi nunca el último visto
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK) — 2026-11-14 14:10 CET — Javi (agente, T-015, rama `javi/rv-first-slate`)
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

### I-160 — El leaderboard se recalcula cada 60 s sobre la última hora exacta (antes: cada 10 min)
- **Status / date / owner:** SUPPORTED (OBSERVED DATA) — 2026-11-14 13:25 UTC — Javi (agente, T-016, rama `javi/night-lab`)
- **Evidence:** E-160. En `https://datathon.rawtree.dev/api/state`, `next_update − updated_at = 60 s` y `window = [updated_at − 3600, updated_at]` en 9 snapshots consecutivos (13:24–13:39 UTC). Corrige la cadencia de I-016 (10 min).
- **Implication:** un bloque de 60 min o más con una sola variante se lee directamente de un snapshot (ventana entera dentro del bloque), sin restar snapshots ni conocer bloques anteriores: desaparece la limitación estadística anotada en E-REL-001. Entre snapshots consecutivos la diferencia es (minuto que entra − minuto que sale)/60. `recsys/night_lab.py` usa bloques de 65 min.

### I-161 — 14/11 13:24–13:39 UTC: `on_time` cayendo y dos `model_version` alternando
- **Status / date / owner:** OBSERVED DATA, causa SIN VERIFICAR — 2026-11-14 13:40 UTC — Javi (agente, T-016)
- **Evidence:** `on_time` horario de team_26: 73,5% (13:24) → 66,1% (13:29) → 57,2% (13:39), unos −1,5 puntos por minuto al principio, lo que equivale a minutos enteros casi sin respuestas a tiempo. En esos mismos snapshots `model_version` alterna entre `v1-gbm-cand-r1`, `v1-gbm-cand-r1-guard` y **`v1-gbm-cand:v1`**, una cadena que no produce el `live.py` de `javi/qrank-serving`.
- **Implication (HYPOTHESIS):** puede haber dos procesos escribiendo (I-017) o un reinicio a medias. No lo he comprobado en `submissions` (este hilo no tiene acceso al Mac). Hay que resolverlo antes de cualquier A/B: con `on_time` bajo, el lift medido se diluye.

### I-170 — Un ranker que describe productos por atributos iguala a qrank en productos conocidos y es el único que acierta con productos nuevos
- **Status / date / owner:** SUPPORTED (OFFLINE ESTIMATE + LIVE FEEDBACK) · 2026-11-14 15:00 UTC · agente de Javi (T-017, rama `javi/attr-model`) · E-170, E-171, E-172
- **Claim:** la calidad de un producto en el carrusel se reconstruye sin su ID: `exp(categoría + 1,04·prior de conversión por atributos + 0,71·popularidad relativa + 0,02·residuo de conversión)`, donde el prior sale de categoría, las 2 frases, marca y precio (absoluto y relativo a la subcategoría) y los otros dos términos son conteos con shrinkage que valen 0 en un producto recién lanzado. El comprador entra solo por `recent_views` (frases compartidas con lo último visto, reparto de frases de la sesión), sin ID ni historial.
- **Evidence:**
  1. *Calidad, split temporal (ajuste < 25 oct, compras del carrusel 25 oct–14 nov), 20% del catálogo (1.047 productos) oculto como "nuevo":* devianza explicada en esos productos nunca vistos (N=903 con exposición, 1.397 compras) 0,47 solo categoría → **0,66 solo atributos** → 0,90 con sus conteos. En los conocidos (N=3.455, 6.469 compras) 0,48 → 0,73 → 0,93.
  2. *Ranking dentro de slates del histórico, test 8–14 nov (3.013 sesiones con compra):* hit@1 `attr_model` 0,436 frente a 0,430 de qrank con todo conocido (empate dentro del error, ±0,009). Con el 20% de productos tratados como nuevos, y la compra es de uno de ellos (N=529): **qrank 0,002, `attr_model` 0,293** (al azar 0,100); global 0,418 frente a 0,441.
  3. *Feedback en vivo, modelo oculto (21.046 peticiones product/category, 11:09–13:35 UTC; 75.697 impresiones elegibles, 131 compras, 372 clics), puntuando en frío (sin conteos en vivo):* AUC de compra 0,831 frente a 0,787 de qrank (diferencia +0,046, IC 95% por bootstrap de peticiones 0,021…0,069); AUC de clic 0,748 frente a 0,721. En usuarios nuevos 0,870 frente a 0,823. Dentro de cada petición no hay ganador: log-verosimilitud de lo comprado −1,435 frente a −1,515 (mejor `attr_model`), pero hit@1 0,481 frente a 0,504 y en clics 0,401 frente a 0,446 (mejor qrank).
- **Potential confounding/weakness:** en productos conocidos NO hemos demostrado mejora sobre qrank; la ventaja medida está en productos nuevos y solo offline (en vivo hay 291 impresiones de productos lanzados hoy y 1 compra, sin potencia). El hit@1 offline se mide dentro de slates de best-sellers, no sobre los ~500 candidatos que puntúa en vivo. Nada medido con el leaderboard.
- **What changed:** `recsys/attr_model.py` + `attr_policy.py`, variantes `attr` / `attr_aff` / `ab_attr` / `ab_attr_aff` en el writer (apagadas por defecto). Propuesta D-170.
- **Next action:** bloque `ab_attr_aff` (qrank_aff frente a attr_aff) o bloque completo contra el leaderboard, a decidir por el dueño del writer.

### I-171 — El boost de afinidad con β=40 que incluye `recent_views` perjudica a los compradores sin historial (el caso de la final)
- **Status / date / owner:** SUPPORTED con muestra pequeña (LIVE FEEDBACK) · 2026-11-14 15:00 UTC · agente de Javi (T-017) · E-172
- **Claim:** `qrank_aff` multiplica por exp(40·afinidad) y la afinidad incluye las vistas de la petición. Con 1–6 vistas y nada más, una sola vista ya multiplica ×36 a los productos con sus frases. En compradores sin historial eso empeora el orden dentro del slate; en compradores con historial ayuda.
- **Evidence:** misma muestra que I-170, ranking dentro de cada petición de lo que se mostró. *Sin historial (71 compras, 173 clics):* qrank hit@1 0,507 / clics 0,491; qrank×exp(40·afinidad) **0,408 / 0,393**, log-verosimilitud −1,607 → −1,926; con β=20 0,437 / 0,428. *Con historial (60 compras, 199 clics):* qrank 0,500 / 0,407; β=40 0,567 / 0,437; β=20 0,550 / 0,442. `attr_model` ya usa las frases de la sesión dentro del modelo, así que su variante `attr_aff` solo añade el gusto guardado (historial + vistas en vivo, sin `recent_views`) con β=20: sin historial queda igual que `attr`, con historial hit@1 0,500 → 0,550.
- **Potential confounding/weakness:** 71 y 60 compras; diferencias de ±0,06 son ruido en compras, en clics la caída de 0,10 son unas 2,8 desviaciones. Es un análisis sobre slates ya mostrados (v1 y fallback), no un A/B. No contradice E-093: la pendiente por celda existe, lo que falla es la escala cuando casi toda la masa viene de la propia sesión.
- **What changed:** nada en `aff_policy.py` (no es mío). Aviso para quien active `qrank_aff` en la final, donde los compradores son nuevos.
- **Next action:** si se quiere `qrank_aff` en la final, probar β=20 (`AttrAffinity(beta=20)`) o excluir `recent_views` del vector cuando el usuario no tiene historial; decidirlo con un bloque del leaderboard.

### I-172 — Predecir la popularidad de un producto desde sus atributos no funciona (REJECTED)
- **Status / date / owner:** REJECTED · 2026-11-14 · agente de Javi (T-017) · E-170
- **Evidence:** los atributos explican el 29% del log de vistas orgánicas. Añadir ese prior de popularidad a la calidad bajó la devianza explicada en productos nunca vistos de 0,66 a 0,61 (N=903) con coeficiente negativo (colineal con el prior de conversión). Se usa "popularidad media" como prior y el conteo real, con shrinkage de 20 vistas, como corrección.
### I-180 — El hueco con la referencia está en los usuarios que vuelven: 70% del tráfico y convierten 3 veces menos
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK) — 2026-11-14 14:30 UTC — Javi (agente, T-018, rama `javi/lfm-live-fit`)
- **Evidence:** feedback propio 11:09–13:57 UTC, 30.280 peticiones (todas las políticas mezcladas), compras reales. Página producto: `is_new_user=false` **0,66%** (78/11.877) vs nuevo **2,00%** (102/5.107); categoría 0,87% (45/5.186) vs 1,37% (30/2.194); home 0,12% vs 0,39%. Pasa igual con el slate genérico del fallback (0,68% vs 1,34% en producto), así que no es solo culpa de v1. Con `v2-qrank-r1` el usuario que vuelve sigue en 0,53% (3/569) y 0,87% (2/231): qrank arregla al nuevo, no al que vuelve.
- **Tamaño:** usuario que vuelve fuera de home = 56% de las peticiones a 0,72%. Si convirtiera como el nuevo (~2%) serían **+0,7 pp** globales, dos tercios del hueco con la referencia (2,04–2,09%). Usuario nuevo fuera de home = 24% a 1,8%; home = 20% a 0,20% (techo bajo).
- **Por qué:** por impresión, a un usuario que vuelve un producto sin relación con él y con afinidad de frases <0,12 le vende **3 veces en 56.280 impresiones** (la mitad de lo que le enseñamos); con afinidad >0,20 vende 62–127 por 10.000. Lo que carritó en los 60 días y no compró: 28,6 por 10.000 de media, **110 en el slot 1**, y hasta 178 si además la afinidad es >0,20. El 96% de estos usuarios tiene algún carrito sin comprar (el 45% más de 10).
- **Potential confounding/weakness:** qué se mostró no fue aleatorio; compras reales con ruido (285 en total). Precio: sin efecto visible (8,0 por 10.000 por debajo de 10 €, 6,2 por encima de 80 €), así que ordenar por dinero esperado no es la palanca de conversión.
- **What changed:** variante `lfm` (D-180).

### I-181 — El usuario nuevo compra lo que ha metido hoy en el carrito, y casi nunca se lo enseñamos
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK) — 2026-11-14 — Javi (agente, T-018)
- **Evidence:** peticiones fuera de home de usuarios nuevos con algún producto añadido al carrito hoy y no comprado (antes de la petición): 2.514 de 7.301 (34%). Si el slate incluía alguno: **4,2% / 10,2% / 17,4%** de conversión con 1 / 2 / 3+ carritos (37 compras en 380 peticiones); si no: 1,8% / 3,9% / 5,0%. Por impresión: 3,7% en el slot 1 (9/241) y 4,0% en los slots 2–3, también cuando el producto es de otra categoría (218 por 10.000). Solo lo mostramos en 380 de 2.514 peticiones (15%).
- **Contraste:** en usuarios que vuelven el carrito de hoy apenas vende (2/895 impresiones); a ellos les vende el carrito del histórico. Por eso el modelo tiene pesos distintos por tipo de usuario.
- **Potential confounding/weakness:** 18 compras de carrito de hoy; quien tiene carrito ya es un comprador más activo (convierte 2,7% en otros productos).

### I-182 — El leaderboard da la conversión del modelo oculto por `model_version`: sirve para medir segmentos sin ruido
- **Status / date / owner:** SUPPORTED (OBSERVED DATA) — 2026-11-14 — Javi (agente, T-018)
- **Evidence:** `https://datathon.rawtree.dev/api/state?by=model` devuelve por equipo una lista `versions` con peticiones, conversión esperada, cold y €/petición de cada `model_version` de la última hora (las de menos de 300 peticiones salen sin clasificar). team_09 lo usa con 56 versiones.
- **Implication:** si la versión lleva el segmento en el nombre, el leaderboard devuelve la conversión esperada de cada segmento. `lfm` etiqueta `v3-lfm-r1-k` (vuelve), `-n` (nuevo), `-kh` y `-nh` (home).

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

### I-010 — Shared first action hides slate differences
- **Status / date / owner:** SUPPORTED / 2026-11-14 / Codex; E-010.
- **OBSERVED DATA:** same_subcategory and mixed_category agree on slot 1 for all 10,000 legacy cached requests. They both begin with the top same-subcategory best seller when available; the mixed policy changes later items. Identical first-action weights, rewards, match counts and ESS follow on this sample.
- **Implication:** slot-1 IPS/SNIPS cannot distinguish policies that change only later slots. Different hit@10 is an exposure-biased clicked-item coverage proxy, not evidence of full-slate purchase uplift. General agreement is not guaranteed if a subcategory is unavailable but a category fallback exists.

### I-011 — Temporal hygiene and final-test discipline
- **Status / date / owner:** SUPPORTED engineering change / 2026-11-14 / Codex; E-011.
- **OBSERVED DATA:** history spans approximately 60 days, while the old cache lacks impression timestamps. New 70/15/15 periods use verified overlapping source coverage, deterministic sampling and separate checksummed caches. Already inspected legacy IDs are excluded. Training factories receive only training data; inference sees a label-free request and read-only as-of eligible catalog.
- **Limitation:** historical base metadata has no field-level versions and there are no catalogue updates during history. Creation-time filtering prevents recommending future products, but cannot certify old prices or stock. Bootstrap intervals quantify sampling variation under an hourly-block approximation, not counterfactual identification or bias removal. Final test remains unopened for scoring; no policy selected for live promotion.
- **Next action:** tune independently registered policies on validation, inspect matches/ESS/intervals and validity, freeze the chosen configuration, then score final test once. Never tune on final results. Establish live E2E reliability separately with the existing single writer.
- **E-011 validation update (OFFLINE ESTIMATE):** 10,000 new validation rows, hit@10 baseline/category/subcategory/mixed = 0.3812/0.7572/0.2689/0.7154; SNIPS slot1 buy = 0.0296/0.0104/0.0108/0.0108. Subcategory/mixed again share all first actions; 825 matches yield only ~98 ESS. All reconstructed slates valid. Wider support/uncertainty context matters more than raw click coverage; these results do not establish full-slate conversion or justify deployment.

### I-REL-001 — Rolling on-time score can reflect an earlier outage
- **Status / owner / date:** SUPPORTED descriptive evidence / Codex / 2026-11-14; E-REL-001.
- **OBSERVED DATA:** one-hour audits show ~1,900 missing requests concentrated in 11:40–11:55 UTC and 1,060 request IDs with duplicate submissions. A recent 30-minute audit shows 5,363 team / 10 missing / 28 invalid (99.30% accepted), with no duplicates. Most old missing-feedback IDs still have a submission record. Compare five-minute source/reason groups; do not equate the user's 76% rolling score with the current failure rate or assume every missing row was never submitted.
- **Code-backed risks:** deadline-guard answers waited behind model inference; a shared mutable HTTP Session and blind retry risk; 20s stock cache; repeated per-candidate lookups and a global catalogue race. Fix commit `7176c03` is prepared but not deployed. Local feature benchmark shows identical 31 model inputs with lower feature-construction latency; no live conversion uplift claimed.
- **Next action:** Javi, sole deployed host owner, tests/applies the standalone fix and controls one writer. Record post-rollout five-minute acceptance, expired requests, uncertain pushes, POST timing and stock age. Retain prior model/checkout for rollback.

### I-REL-002 — Published branch work and evidence boundaries
- Published `javi/v1-gbm-recommender` has the implemented policy and a prior duplicate-writer finding. At fetched tips, cold-items, home-new-users and live-trends add task claims only; local/unpushed teammate implementations were not accessible. Main's league and Javi's home work both use T-013; reconcile task IDs before integrating future modules.
- A rolling leaderboard with expected rewards removes some purchase noise but does not create randomized causal comparisons. Earlier branch claims about exact recovery of every ten-minute block from rolling averages need starting blocks, request counts and allocation assumptions. Keep experiment windows/version ledgers and report fallback/overlap contamination.

### I-180 — La calidad de los productos antiguos NO se mueve durante el evento; el stream solo aporta en tres sitios (T-018) — OBSERVED DATA
- Replay de `shop.events` del 14 nov 09:00–13:50 UTC (1,00 M vistas, 52,7 k compras orgánicas), prediciendo cada 15 min las compras de los 15 min siguientes con datos solo del pasado (E-180). Para productos con historia, fuera de ráfagas y descuentos (22.731 compras en la mitad de test), la tasa en vivo no mejora a la histórica de 60 días: ganancia +0,6 nats por 1.000 compras, es decir, nada. Histórico y vivo coinciden (Spearman 0,86 producto a producto con solo 158 vistas vivas de mediana; ratio global 1,00).
- Consecuencia: una "tasa rolling por producto" genérica no es una gran mejora. Lo que el stream sí aporta: productos nuevos (I-183), ráfagas de subcategoría (I-181) y descuentos (I-182). `recsys/live_quality.py` hace exactamente esas tres cosas y deja el resto intacto.

### I-181 — Ráfagas de subcategoría: la calidad estática se queda en el 42% de lo real; multiplicador con puerta estadística — OBSERVED DATA
- En las subcategorías que el detector marca calientes (393 compras en test), la calidad estática predice el 42% de las compras reales; con el multiplicador de 30 min (compras observadas / esperadas, shrinkage de 20 compras) la calibración pasa a 0,97 y la ganancia es +312 nats por 1.000 compras (E-180). Confirma I-080 con otro método.
- Sin puerta (aplicarlo a todas las subcategorías) el multiplicador EMPEORA los productos en calma (−3,6 nats por 1.000 compras): es ruido. Con puerta (z ≥ 3 y ≥ ×1,3) el coste en calma es 0. Ventanas de 15, 30 y 60 min rinden igual.
- Limitación: en nuestro carrusel los productos de subcategorías calientes solo tuvieron 258 impresiones y 0 compras (E-183); el efecto en el modelo oculto es HYPOTHESIS.

### I-182 — Los descuentos son promociones de ~−20% por categoría durante 2 h y suben la compra orgánica un 14,5% — OBSERVED DATA
- `catalog_updates.price_change` no es ruido: a las 10:30 UTC ~610 productos (Pets) bajan un 11–20%, a las 12:30 vuelven a su precio, y a las 13:30 empieza otra tanda de 639 (Home & Garden). En descuento: 1.764 compras frente a 1.541 esperadas con las mismas vistas (×1,145, z = 5,7); los mismos productos a precio normal: ×1,016 (E-181).
- Como la promoción cubre casi toda una categoría y qrank solo ordena dentro de la categoría, apenas cambia el orden: ganancia pequeña. Queda como opción (`promo_q`) apagada; útil para `home`, donde compiten categorías.

### I-183 — La calidad en el carrusel es la tasa orgánica AL CUADRADO; con eso un producto nuevo recibe su calidad real en 1 hora — OBSERVED DATA + OFFLINE ESTIMATE
- En los 5.000 productos históricos, log q (calidad de qrank, medida en el carrusel aleatorizado) = a_subcategoría + 2,02 · log(tasa orgánica compra/vista), r = 0,94 dentro de la subcategoría (E-182).
- qrank da hoy a un producto nuevo la mediana de su subcategoría. Tratando cada producto antiguo como si fuera nuevo (prior de atributos ajustado sin él + solo sus eventos en vivo), el top-10 por categoría elegido con la mediana captura el 10% de la calidad del top-10 real; con el prior de atributos solo, 60%; con prior + 1 h de stream, 77%; con 4 h, 84%. Spearman dentro de categoría 0,23 → 0,79 → 0,81 → 0,85.
- Los 100 productos nuevos de hoy: 4 tienen tasas orgánicas del 16–26% (p. ej. `p_548697`: 208 compras en 796 vistas), al nivel de los mejores del catálogo. Hoy ninguno entra en el top-10 de su categoría y solo 1 está en el pool de candidatos de qrank; con calidad en vivo entran 3 y 29. El writer les dio 611 impresiones de 288 k (0,2%).
- Límite: la relación cuadrática es entre productos, medida en historia. Que se cumpla para productos nuevos en el modelo oculto es HYPOTHESIS hasta el A/B en vivo.

### I-184 — Nuestro feedback no puede validar nada de esto; hace falta el A/B del writer — LIVE FEEDBACK
- En 28,8 k respuestas (252 compras), productos nuevos: 611 impresiones, 2 compras (32,7 por 10 k frente a 8,6 del resto, no significativo); subcategorías calientes: 258 impresiones, 0 compras (E-183). No hay potencia. La única validación posible es encender `live_quality` en modo `ab` o en un bloque del laboratorio nocturno (D-180).
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

---

# TABLERO DE IDEAS DEL EQUIPO (T-020, abierto el 2026-11-14 15:00 UTC)

**Cómo se usa.** Cada idea nueva tiene `owner: free`. Para cogerla, cambia esa línea por tu nombre y la hora, haz commit (`git pull --rebase` antes) y trabaja en tu rama. Al terminar, cambia el estado (SUPPORTED / REJECTED) y enlaza la entrada E. No se borra nada.

**Cómo se mide.** (1) Offline, con el feedback propio: `cd recsys && python lfm_build.py --pull --no-write && python explore_t020.py --pull` deja en `recsys/data/` las peticiones respondidas con sus compras y los eventos de hoy; todo lo que se calcule debe usar solo eventos anteriores a cada petición. (2) En el modelo oculto: dar a la variante un `model_version` propio y leer su fila en `https://datathon.rawtree.dev/api/state?by=model` (conversión esperada, sin ruido de compras, fiable a partir de ~300 peticiones, I-182). Solo el dueño del writer toca `live.py`.

**Foto del leaderboard por versión, 14:46 UTC (OBSERVED DATA):** referencia 2,16%, baseline 0,78%. Nosotros: `v3-lfm-r1-k` (vuelve, producto/categoría) **2,39%** en 581 peticiones; `v3-lfm-r1-n` (nuevo) **2,79%** en 255; `v2-qrank-r1` 1,39% en 5.062 (mezcla de segmentos); `v1-gbm-cand-r1` 0,93% en 3.715; `v3-lfm-r1-kh` (vuelve, home) 0,35% en 143; `v3-lfm-r1-nh` 1,69% en 54. Rivales: team_06 `skore_money_v5` 1,85% y 0,90 €/petición (7.343); team_19 `v1-cp2` 1,82%, cold 2,69% (1.339) y `v1-search` 1,78% (7.393). Las filas de lfm tienen pocas peticiones todavía; qrank no está etiquetado por segmento, así que la comparación exacta es I-200.

## Descartadas o superadas (no repetir sin evidencia nueva)

| ID | Idea | Estado | Evidencia |
|---|---|---|---|
| R-01 | Ordenar por precio o por dinero esperado para subir la conversión | REJECTED | I-180 (T-018): 8,0 compras por 10.000 impresiones por debajo de 10 € frente a 6,2 por encima de 80 €. E-205: en usuarios que vuelven, lo que cuesta más de 40 € vende menos (3 compras en 20.953 impresiones genéricas frente a 50 en 96.207). `skore_money_v5` gana en euros (0,90) con 1,85% de conversión, por debajo de la referencia. El dinero solo sirve de desempate (I-206). |
| R-02 | Tendencias del stream como palanca principal | REJECTED como palanca grande | I-081: techo de unos +0,04 pp globales; nuestro carrusel dio 258 impresiones y 0 compras en subcategorías calientes (E-183). Se mantiene solo con puerta estadística (I-181 de T-018). |
| R-03 | Listas de top ventas por región o por dispositivo | REJECTED en esa forma, sustituida por I-204 | I-132 (T-013): el reparto por categoría de las compras es igual en las 10 regiones (±2 puntos, 11.855 compras orgánicas). Lo que sí existe es UN segmento concreto (android en Andalucía, Canarias y Murcia) sensible al precio: ver I-204 y E-204. Fuera de ese segmento las 27 celdas dispositivo × región restantes son iguales (10,8–23,7 compras por 10.000 en productos baratos). |
| R-04 | Lift por producto dentro de una subcategoría caliente | REJECTED | I-080: devianza 1.245 → 1.233 en 730 filas (1.396 compras). La ráfaga afecta a toda la subcategoría por igual. |
| R-05 | Estimación de que qrank llegaría al 2,1% | SUPERSEDED (demasiado optimista) | E-081 predecía 3,93% por modelo. Medido en el leaderboard por versión: 1,44% frente a 1,26% de v1 en producto/categoría; a las 14:46 UTC 1,39% en 5.062 peticiones. qrank arregla al usuario nuevo y no al que vuelve (0,57% real, 7 compras en 1.233 peticiones del hold-out de hoy). |
| R-06 | Ranking v1 (GBM) como campeón, incluido mostrar lo ya comprado | SUPERSEDED por qrank y lfm | I-082: lo ya comprado, 1.118 impresiones y 0 compras; 31% de las impresiones en otra categoría con 0,07%. Hoy: 93.624 impresiones "muertas" (ya comprado, o visto en el histórico sin carrito) con 11 compras. Rivales con GBM genérico: `v2-gbm` 0,80%, `lgbm-v1` 1,11%, `main-hgb-v1` 1,02%. |
| R-07 | Exploración (bandit, Thompson) durante el evento | REJECTED para un horizonte de 2 h | Los productos antiguos no derivan: la tasa en vivo aporta +0,6 nats por 1.000 compras (I-180 de T-018, N 22.731). Brazos de exploración de rivales: `skore_money_v5_explore` 1,17% frente a 1,85% de su brazo principal; `explore@0ac9a11` 0,10% frente a 1,26–1,51%. Explorar cuesta más de lo que se recupera en 2 h. Para productos nuevos se usa el prior de atributos (I-090, I-183), no exploración. |
| R-08 | Tasa rolling genérica por producto desde el stream | REJECTED | I-180 de T-018: sin ganancia en productos con historia. Solo aporta en productos nuevos, ráfagas y descuentos. |
| R-09 | Predecir la popularidad desde los atributos | REJECTED | I-172: devianza explicada en productos nunca vistos 0,66 → 0,61. |
| R-10 | Rellenar con productos genéricos de otra categoría | REJECTED | I-082: 19.092 impresiones, 13 compras (0,07%). Hoy, a usuarios que vuelven: 8 compras en 39.415 impresiones (2,0 por 10.000). Otra categoría solo vende si es carrito o afinidad alta. |
| R-11 | Afinidad con β=40 incluyendo `recent_views` para compradores sin historial | REJECTED para la final | I-171: hit@1 0,507 → 0,408 (71 compras), clics 0,491 → 0,393. Usar β=20 o solo historial. |
| R-12 | Frescura del carrito (minutos desde que se añadió) y carrito repetido | REJECTED | E-200: sin patrón (usuario nuevo: 2 compras en 73 impresiones con 10–30 min, 21 en 659 con más de 60 min; observado/esperado 1,53 y 1,18). En hold-out no mejora (log-verosimilitud de clic −971,8 → −971,7). El carrito vale igual sea reciente o no. |
| R-13 | PPO o RL profundo | REJECTED para este datathon | Sin simulador fiel y con una compra como máximo por petición (I-013) el objetivo es contextual e inmediato; R-07 muestra que ni la exploración simple compensa. |
| R-14 | TF-IDF o embeddings de la descripción para productos nuevos | SUPERSEDED | I-090: Spearman 0,60 frente a 0,84 del GLM de frases × categoría. Queda de reserva si la final trae frases nuevas. |
| R-15 | Elegir política con IPS del slot 1 en el histórico | SUPERSEDED | I-010 (Codex): no distingue políticas que cambian slots 2–10; unas 98 de tamaño efectivo. La medida válida es la fila por versión del leaderboard (I-182). |
| R-16 | "Visto antes hoy pero fuera de `recent_views`" como señal o como producto muerto | REJECTED (sin efecto medible) | E-201: 3 compras en 2.330 impresiones, observado/esperado 1,6–1,7, peso 0 en hold-out. Ni está muerto (a diferencia de lo visto en el histórico sin carrito) ni merece un peso. |

## Ideas nuevas (cógelas: cambia `owner: free`)

Orden por ganancia esperada. "pp" = puntos de conversión global. Todas las ganancias son HYPOTHESIS salvo donde se indica la medida.

### I-200 — Etiquetar el control por segmento para comparar lfm con qrank de igual a igual
- **Status / owner:** IDEA · **owner: free** (tiene que ser el dueño del writer)
- **Hipótesis:** hoy `v2-qrank-r1` mezcla usuarios nuevos y que vuelven, así que no se puede leer en el leaderboard cuánto gana lfm en cada segmento. Con `v2-qrank-r1-k` / `-n` la lectura es directa a los 15 min.
- **Ganancia:** 0 pp directos; evita promocionar o retirar lfm por una comparación mezclada. **Coste:** 15 min en `live.py` (una línea donde se asigna la versión).
- **Test:** `api/state?by=model`, filas `-k` y `-n` de las dos políticas en la misma hora.

### I-201 — Gusto de la sesión de hoy para compradores nuevos (lo que compró, carritó y vio hoy)
- **Status / owner:** SUPPORTED offline con muestra pequeña (E-202) · **owner: free**
- **Hipótesis:** un comprador nuevo que ya compró hoy vuelve a comprar productos parecidos a lo que compró. lfm se ajustó con la afinidad calculada solo con `recent_views`, mientras que el writer la calcula con todas las vistas de hoy (`AP.aff`): el peso `aff10` del segmento nuevo está ajustado con una señal distinta de la que se sirve.
- **Evidencia (E-202):** usuario nuevo, producto ni carritado ni en `recent_views`: sin frases en común con lo comprado hoy 7,8 compras por 10.000 impresiones (18/23.152); con frases en común 35–41 (62/16.820); con las dos frases 98 (7/711). Observado frente a lo que espera lfm: ×0,73, ×2,6–3,1 y ×6,8. Misma subcategoría que algo comprado hoy: 53,9 por 10.000 frente a 19,0. Hold-out temporal (68 compras): AUC de compra 0,873 → 0,885, log-verosimilitud de clic −971,8 → −968,7, hit@1 0,324 → 0,353. En usuarios que vuelven no aporta (su historial ya lo dice).
- **Ganancia esperada:** el 38% de las peticiones de usuarios nuevos fuera de home son de alguien que ya compró hoy, y convierten 1,7–9,5%. Si el orden mejora un 15% ahí, unos +0,05–0,1 pp hoy; en la final (compradores nuevos) pesa más. **Coste:** 1–2 h. En `lfm_build.impressions` reconstruir la afinidad con las vistas y compras de hoy anteriores a cada petición (los datos están en `data/t020_views.parquet` y `t020_cp.parquet`), reajustar y comparar pesos.
- **Test:** hold-out de `lfm_build.py` (AUC y hit@1 del segmento nuevo); en vivo, versión `v3-lfm-r2-n` frente a `v3-lfm-r1-n`.

### I-202 — Home para el usuario que vuelve: solo carritos del histórico
- **Status / owner:** SUPPORTED offline (E-203) · **owner: free**
- **Hipótesis:** en home, a un usuario que vuelve lo genérico no le vende nada; solo vende lo que carritó y no compró.
- **Evidencia (E-203, coincide con I-130 e I-131 de T-013):** home, usuario que vuelve: genéricos **1 compra en 23.363 impresiones** (0,4 por 10.000; 0 compras en los tres cuartiles bajos de calidad); carrito del histórico 6 en 5.441 (11,0 por 10.000); carrito de hoy 1 en 307. La fila `v3-lfm-r1-kh` va al 0,35% (143 peticiones) frente a 2,39% de `-k`.
- **Ganancia esperada:** home de usuario que vuelve es el 14% del tráfico al 0,35%. Llenando los 10 slots con carritos del histórico (hoy lfm pone unos 3) y ordenándolos por afinidad, objetivo 0,7–1,0%: **+0,05–0,09 pp**. **Coste:** 1 h (regla en `lfm.slate` para `page == "home"`: primero todos los carritos, después afinidad). El 96% de estos usuarios tiene carrito sin comprar y el 45% más de 10 (I-180).
- **Test:** offline, valor por modelo en el hold-out de home; en vivo, fila `-kh`.

### I-203 — Carrito primero como regla dura encima de cualquier ranker (plan B si lfm se retira)
- **Status / owner:** IDEA con evidencia (I-181, E-200) · **owner: free**
- **Hipótesis:** poner en los slots 1–3 lo carritado hoy (usuario nuevo) o en el histórico (usuario que vuelve) captura la mayor parte de la ganancia de lfm sin depender de sus 11 pesos.
- **Evidencia:** carrito de hoy en usuario nuevo, slot 1: **17 compras en 363 impresiones (4,7%)**; slots 2–3: 5 en 203 (2,5%); genérico de la misma categoría: 0,06–0,5%. Solo se mostraba en el 15% de las peticiones que tenían carrito (380 de 2.514, I-181). Carrito del histórico en usuario que vuelve: 78 compras en 20.245 impresiones (38,5 por 10.000) frente a 2–5 de lo genérico.
- **Ganancia esperada:** +0,2 pp sobre qrank (24% del tráfico × 34% con carrito × +2,4 pp), ya incluida en lfm. **Coste:** 30 min sobre qrank. Sirve también de red de seguridad para la final si los pesos de lfm no generalizan.
- **Test:** versión `v2-qrank-cart` frente a `v2-qrank-r1` en el leaderboard.

### I-204 — Segmento sensible al precio: android en Andalucía, Canarias y Murcia
- **Status / owner:** INVESTIGATING (E-204) · **owner: free**
- **Hipótesis:** el modelo oculto tiene un tipo de comprador que compra mucho más y casi solo barato, identificable por `context.device = android` y `context.region` en esas tres regiones. Para él hay que ordenar con una calidad propia (productos de menos de 20 € primero).
- **Evidencia (E-204):** *Histórico (mitad de `history_sessions`, 8,1M impresiones):* productos de menos de 20 € venden 62,4 / 50,2 / 72,8 por 10.000 impresiones en android × Andalucía / Canarias / Murcia frente a 10,8–23,7 en las otras 27 celdas dispositivo × región; los de más de 20 € venden igual en todas (5,7–17,1). *En vivo hoy:* el segmento es el 9,8% de las peticiones fuera de home y convierte **2,37% (70/2.955) frente a 0,93% (255/27.286)**. Clics en el segmento: 0,80% por impresión por debajo de 40 € (137/17.163) y 0,27% por encima (12/4.494); en el resto, 0,37% en ambos.
- **Debilidad:** en compras en vivo el efecto del precio dentro del segmento no se distingue todavía (8 compras por encima de 40 €) y un término lineal de precio no mejoró el hold-out. La señal fuerte es del histórico y de los clics.
- **Ganancia esperada:** el segmento pesa un 10% y convierte 2,4 veces más; si un orden propio sube su conversión un 20%, **+0,05 pp**; y sirve para los compradores nuevos de la final porque no necesita historial. **Coste:** 1–2 h. Calcular la calidad `q` de `qrank_build.py` solo con sesiones del segmento y usarla como `lq` en esas peticiones.
- **Test:** offline, hit@1 dentro de slates del histórico del segmento con `q` global frente a `q` del segmento; en vivo, versión con sufijo `-s`.

### I-205 — Reajustar lfm antes de la final con todo el feedback de la noche
- **Status / owner:** IDEA · **owner: free**
- **Hipótesis:** los pesos actuales salen de 3 h de feedback (333 compras). Con 18 h más de datos, incluidas las filas servidas por lfm, los pesos son más estables y dejan de extrapolar.
- **Evidencia:** reajuste de hoy con 37.601 peticiones frente a 31.776: AUC de compra en hold-out 0,926 (vuelve, 54 compras) y 0,873 (nuevo, 68); los pesos se mueven poco (`cl` nuevo 2,23 → 2,13; `oinrv` vuelve 2,01 → 1,49).
- **Ganancia esperada:** +0,05–0,1 pp. **Coste:** 1 min (`python recsys/lfm_build.py --pull`) más revisar el informe; hacerlo a las 08:30 CET del domingo y congelar a las 09:30. Riesgo: cambiar pesos sin poder ver el leaderboard (oculto en la final), por eso se valida en la práctica de antes de las 10:00.
- **Test:** hold-out del propio script; fila `v3-lfm-r2-*` durante la práctica.

### I-206 — Desempate por precio solo en compradores nuevos
- **Status / owner:** IDEA con evidencia (E-205) · **owner: free**
- **Hipótesis:** el ingreso es el desempate oficial. En compradores nuevos el precio no cambia la conversión, así que entre productos con score casi igual (menos de un 5% de diferencia) se puede poner primero el más caro sin coste.
- **Evidencia (E-205):** genéricos, usuario nuevo: 14,6 compras por 10.000 por debajo de 15 € y 15,4 por encima de 80 € (60/40.984 y 21/13.597). Usuario que vuelve: 5,5 y 1,9 (34/61.757 y 3/15.765), ahí no. Excluir siempre el segmento de I-204.
- **Ganancia esperada:** 0 pp de conversión, más €/petición. **Coste:** 30 min.
- **Test:** misma conversión y más €/petición en la fila de la versión.

### I-207 — Ensayo de generalización para la final: tratar a usuarios conocidos como nuevos
- **Status / owner:** IDEA · **owner: free**
- **Hipótesis:** en la final muchos compradores no tendrán historial. Hay que saber cuánto pierde lfm cuando solo dispone de la sesión, y si conviene usar el modelo "nuevo" para todos los que no tengan carritos en el histórico.
- **Ganancia esperada:** evita una caída en la final (el segmento que vuelve pasa de 2,39% a lo que dé sin historial). **Coste:** 1 h. En `lfm_build.py`, borrar el historial de una mitad aleatoria de los usuarios que vuelven y puntuar sus peticiones con los pesos `new` y con los `known`; comparar hit@1 y AUC.
- **Test:** solo offline; decide qué pesos usa cada usuario en la final.

### I-208 — Home para el comprador nuevo: no hay señal; usarlo para los puntos de cold start
- **Status / owner:** IDEA de baja prioridad (E-203) · **owner: free**
- **Evidencia:** home, usuario nuevo, genéricos: 10 compras en 21.366 impresiones (4,7 por 10.000) y plano por calidad del producto (3,7 / 5,6 / 3,6 / 5,9 por cuartil). Es el 6% del tráfico.
- **Hipótesis:** como nada ordena mejor que nada, estos slots pueden llevar productos nuevos con buen prior de atributos (I-183: 4 de los 100 nuevos tienen tasas del 16–26%) y promociones activas (×1,145, I-182 de T-018) sin perder conversión.
- **Ganancia esperada:** ≤ +0,03 pp; posible mejora en cold start. **Coste:** 1 h. **Test:** fila `-nh` (conversión y cold).

### I-209 — Último producto visto en el slot 1 para el usuario que vuelve
- **Status / owner:** IDEA con muestra pequeña (E-202) · **owner: free**
- **Evidencia:** usuario que vuelve, último visto: 10 compras en 1.018 impresiones frente a 3,0 esperadas por lfm (×3,3). En el usuario nuevo el modelo ya lo valora bien (14 frente a 16,2).
- **Hipótesis:** el peso `islast` del segmento que vuelve está bajo. **Ganancia esperada:** +0,02–0,05 pp. **Coste:** 15 min (se resuelve solo con I-205 si el reajuste lo sube; comprobar el peso).
- **Test:** peso `islast` tras reajustar; hit@1 del hold-out.

## Hallazgos de hoy (T-020)

### I-210 — Un comprador nuevo que ya ha comprado hoy convierte hasta 11 veces más
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK) · 2026-11-14 15:00 UTC · Javi (agente, T-020) · E-202
- **Evidencia:** peticiones fuera de home de usuarios nuevos según compras orgánicas hechas hoy antes de la petición: 0 compras **0,85%** (48/5.666); 1 compra 1,73% (36/2.081); 2 compras 3,82% (30/785); 3 o más **9,46%** (53/560). En usuarios que vuelven casi no cambia (0,56% → 1,10%). El aumento se reparte por todos los tipos de producto (×2,1–3,2 sobre lo esperado), así que es propensión del comprador, y además se concentra en productos parecidos a lo comprado (I-201).
- **Implicación:** el 15% de las peticiones de usuarios nuevos (2 o más compras hoy) da el 50% de sus compras en el carrusel (83 de 167). Ahí es donde más vale el orden del slate, y es el caso típico de la final.
- **Debilidad:** observacional; `is_new_user` significa "no está en el histórico", no "primera visita de hoy".


### I-211 — Con el feedback de compras ya no se distinguen mejoras de lfm; el instrumento es el leaderboard por versión
- **Status / date / owner:** SUPPORTED (LIVE FEEDBACK + OFFLINE ESTIMATE) · 2026-11-14 15:15 UTC · Javi (agente, T-021, rama `javi/lfm-v2`) · E-210
- **Evidencia:** reajuste con 44.026 peticiones (430 compras; incluye 40 min servidos por lfm) y 6 features nuevas (frases y subcategoría en común con lo comprado hoy, carrito en home, precio >40 €, segmento android × Andalucía/Canarias/Murcia × barato y × calidad). Hold-out temporal desde 14:01 UTC (152 compras): los pesos ya publicados, los mismos 11 pesos reajustados y los 17 pesos dan AUC de compra 0,887 / 0,881 / 0,888 (vuelve) y 0,884 / 0,879 / 0,884 (nuevo); el rango recíproco medio del producto comprado va de 0,54 a 0,64 sin orden claro. Ninguna diferencia supera el ruido de 70–80 compras por segmento.
- **Segundo dato:** el modelo sobreestima sus propios slates. Para `v3-lfm-r1-n` predice 4,8 compras por 100 peticiones y el leaderboard dice 2,9; para `-k` predice 2,75 y son 2,15–2,33. La estimación "modelo sobre su slate" ya no sirve para decidir entre variantes parecidas.
- **Implicación:** las mejoras de +0,05–0,1 pp del tablero (I-201, I-202, I-204, I-209) no se pueden validar offline. Sí se pueden leer en `api/state?by=model` sin ruido: 3 brazos a la vez dan unas 900 peticiones por brazo y hora en el segmento más pequeño fuera de home.
- **What changed:** brazos de pesos de lfm configurables en caliente (D-210).


## Synthetic alpha (T-SA01, d4xn+Claude)

### I-SA01 — Los carritos de hoy predicen la compra del usuario nuevo más allá de lfm v2 (frases y subcategoría), aún sin significación
- **Status:** HYPOTHESIS con dos estimaciones del mismo signo (E-SA01c/d: +40 y +38 nats por 1.000 compras, IC incluyen 0; control plano). `ncp` y `csub` positivos en usuarios nuevos, ~0 en los que vuelven. **owner: d4xn** hasta repetir la confirmación con más compras.

### I-SA02 — Ni la edad del producto ni su id llevan señal que no capture prior + actualización bayesiana
- **Status:** REJECTED (E-SA01a/b). Las vistas orgánicas no son uniformes entre productos (dispersión 68, Spearman 0,97 con el histórico): la cuota de vistas orgánicas sí es una referencia de exposición para productos nuevos (relevante para D-CS01: 5,9% de exposición frente a 2,4% de cuota).
