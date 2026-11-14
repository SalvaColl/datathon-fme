# Winning strategy — RawTree Datathon FME 2026

**Version 1.0, updated from official 2026-11-14 challenge rules. Status: PROPOSED / NOT YET TESTED AGAINST TEAM DATA.** A strategy is not a fact: `challenge.md` holds facts, `experiments.md` holds measurements, and `insights.md` records candidate ideas and rejected hypotheses.

## Executive recommendation

**Prioritize a reliable production loop, then a historical-data-trained personalized ranker with a fast online adaptation layer.** Optimize expected **conversion**, with dedicated cold-start evaluation and a strictly valid, low-latency ranked list of 10.

Use the published `starter/recommender.py` + `starter/offline_eval.ipynb` before writing new infrastructure. Compete against the all-time best-sellers baseline. Try LightGBM/CatBoost or simple learned/logistic scoring if available; add recent view/purchase trends and Bayesian-smoothed signals. A contextual bandit is an optional challenger. **Do not start with PPO**: there is no public faithful simulator, final distribution shifts, and most points favor immediate purchase prediction rather than long-horizon control.

## What matters under official scoring

- **50 points:** expected purchase probability from the simulator over final-round requests, not price-weighted revenue.
- **10 points:** expected conversion for **cold** requests (`is_new_user` or a `recent_views` item introduced during event). New products have descriptions but little/no interaction history; text/metadata generalization is valuable.
- **10 points:** validity and on-time reliability at ~**3 requests/s**; a single out-of-stock product invalidates the slate.
- **30 points:** strong offline method, adaptive learning, meaningful RawTree use, explainable presentation. Saving experiments and feature/ablation charts has actual score value.
- Tie-breaker: expected revenue per request. Consider a weak price-aware tie breaker **only if primary conversion stays similar**.
- Final round Sun 2026-11-15 **10:00–12:00 CET** with new shoppers/products/trends; offline success on a static history is insufficient.

## Proposed architecture

```text
RawTree history_sessions, history_events, catalog
    -> offline feature builds / time split / training / evaluation
                                  |
RawTree shop.requests (poll)       |                     shop.events/catalog_updates (poll)
    -> dedupe + request parser     |                             -> incremental features/catalog cache
    -> fast candidate retrieval <- model + cached item/user statistics <-+
    -> rank candidate items (purchase score + tested position/slate effects)
    -> current eligibility/stock check + dedupe + EXACTLY 10
    -> batch insert team_NN.submissions BEFORE request.ts + 3 seconds
    -> private team_NN.feedback -> join request_id -> online statistics/monitoring
                                              -> experiments and team_NN.scratch (optional)
```

Prefer one verified serving writer and independently updated feature/model snapshots. No remote LLM inference in critical path. Integrate with the starter rather than recreating its networking unless measured shortcomings justify it.

## Data and modeling: implement in ascending complexity

### Stage B0 — Run official baseline unchanged

- Get `TEAM_ID` / `RAWTREE_API_KEY` from stand, create private `.env`, choose virtualenv, run `python starter/recommender.py` in a reliable supervised terminal.
- Verify `feedback.served_by = 'team'`, `fallback_reason`, rate and latency. Inspect at least one real submission and current product eligibility.
- **Known code discrepancy:** starter's `recommend(recent_views,best,unavailable)` currently ignores `recent_views` and ranks globally by historical organic purchases, whereas site text loosely describes category-specific best sellers. Prefer source code over paraphrase and clarify at stand.
- Snapshot baseline metrics. Don't allow two instances to submit for same request.

### Stage B1 — Personalization from organic events and session context

Prepare fast lookups from 60 days of `shop.history_events` (~12M) and `history_sessions` (~2M):

- **User profile:** previously viewed/carted/purchased products and affinity per category/subcategory/brand; decay old events; avoid re-recommending previously bought item if evidence suggests low repeat interest.
- **Recent session:** latest viewed product(s), category/subcategory, recency, co-view/co-purchase neighbors, item text/brand similarity, price region.
- **Context:** home vs product vs category page, device, region, new vs returning buyer. Include request `is_new_user` and event-introduced-item cold status when known.
- **Product:** 10 categories, ~90 subcategories, brand, description text, current price, age/created_at, global popularity, recent views/carts/purchases.
- **Price:** relative to buyer's historic viewed/purchased price distribution and subcategory median, not always “cheaper is better”. Historical price and current price must be distinguished.
- **New products:** cold content-based neighbors (TF-IDF of description/category/brand, optional local embeddings), shared priors; no reliance on item ID memorization.

Recommended candidate pool: top relevant co-view items, same subcategory/brand/text neighbors, user/category favorites, trending and popular items, promising new items. Deduplicate and filter active products. Score perhaps 100–500 candidates locally, not all 5k if avoidable. 5k in memory is also tractable if measured.

### Stage B2 — Supervised ranker from 60 days of impressions

Start with simple calibrated logistic regression / weighted heuristic, then LightGBM/CatBoost if environment permits. Train against **purchase** or click-then-purchase outcome in `shop.history_sessions`, with per-request grouping and appropriate position features. Core issue: old policy over-exposes all-time best sellers, and slot position affects observations. A model predicting click/purchase may learn exposure/position artifacts instead of intrinsic relevance.

**Evaluation rules**:

1. Split by **timestamp**: earlier training, later validation, plus a newer holdout. Avoid leakage from post-impression event histories.
2. Do not label products that were **not shown** as negatives; they were never given a chance.
3. Use `shown`, `clicked`, `purchased`, slot index and `propensity` in evaluating a policy. Preserve request-level grouping.
4. Start with organizer's `starter/offline_eval.ipynb`; inspect exact estimator. Inverse-propensity scoring is valid only where logged policy has support and can have huge variance for rare actions/full slates. Report weight clipping, effective sample size, and uncertainty. Avoid presenting an IPS *click* estimate as the official *conversion* score.
5. In parallel, compute stable **proxy metrics** on temporal held-out data: pairwise positive-vs-negative item ranking within logged slate, recall/precision@10 when measurable, purchase AUC, calibration, cold-start slices, stockout invalid rate. These are proxies, not unbiased complete-slate estimates.
6. Explicitly test **new users**, **new products**, new/trending subcategories and price shifts. Split or simulate historical launch dates carefully; no futuristic catalogue or event features.

Potential model score: `P(purchase | current request, item, exposure)` with position and slate effects handled by a separate reranker, not assuming all independent product scores sum correctly.

### Stage B3 — 10-item slate and position optimization

- Exactly **10 unique currently active** products; order matters and first positions receive more attention.
- Rank high-conversion items first; test whether a limited diversity/redundancy penalty improves outcome vs no penalty. Do **not** force category variety if session strongly implies one category.
- Explore co-view/subcategory neighbors for product pages and mixed familiar/trending picks for home pages.
- Consider simple greedy slate selection with position discount + redundancy penalty, tuned empirically. A shopper may buy one item; naive sum of ten independent probabilities can overstate value.
- Validate against inventory that combines `shop.catalog` with **latest `shop.catalog_updates`** (including price, stock, new products). If refresh stale, favor safe fallback; don't submit any known-inactive product.

### Stage B4 — Online learning and trends (critical for final domain shift)

- Live `shop.events` (~50/s) offers *unbiased-by-your-carousel* behavioral signals, including earliest signals for new trends. Track short/medium/long time windows (e.g. 15 min, 1 hour, history) by subcategory/item; compare vs previous windows and smooth low counts.
- `team_NN.feedback` is **private and delayed**, with `shown`, served mode, click/purchase/revenue, latency. Join `request_id` to submitted `model_version` via a local ledger; exclude `served_by='fallback'` when attributing success to a deployed policy.
- Maintain Bayesian-smoothed item/segment conversion and uncertainty; discount old data gently when drift detected.
- Ingest `shop.catalog_updates` quickly and atomically update the active item set, price and new-product flag. A stale stock list is a hard reliability risk.
- **Do not overfit to own realized purchases**: official conversion score uses hidden *expected probabilities*; live feedback is noisy. Prefer dense shared organic trends and historical priors when feedback sample is sparse.

### Stage B5 — Controlled exploration / bandits (optional)

Use contextual Thompson Sampling or UCB as a small bounded exploratory component **only after** trusted baseline/ranker performance exists. Try limited exploration in low positions or a very small subset of traffic, subject to metric risk. Incorporate `is_new_user`, product age and uncertainty. Because `clicked`/`purchased` record a single product ID (or none), treating every non-purchased shown product as an independent failure is not necessarily statistically sound.

### PPO / RL decision

**Not recommended as primary solution in this 24-hour event.** Reconsider only if you acquire a realistic simulator or ample on-policy training data, can model longer-term customer behavior, and prove an advantage over a bandit/ranker within the time budget. No access to hidden simulator internals is documented. A local invented simulator may reward fake assumptions.

## Champion-versus-challenger testing (Battlecode-style)

A shared **champion** is the only live writer; each challenger is a versioned `recommend(...)` policy evaluated without submitting duplicate responses.

Evaluation tiers, in descending validity:

1. **Offline historical holdout with organizer notebook** and explicit off-policy limitations; compare matching requests/time periods, segment metrics, estimator uncertainty and validity.
2. **Shadow-mode predictions** logged privately for same live requests; compare latency/validity, but **cannot observe counterfactual purchases** for unshown slates.
3. **Controlled interleaving/randomized online policy allocation** if permitted, with request_id-policy assignment, attribution to live feedback, enough observations and stable guardrails. Public last-hour leaderboard alone is not an A/B test.
4. **Local synthetic customer league** for engineering robustness (stock, drift, cold starts, random seeds). Clearly label *synthetic* and don't treat wins as proof against hidden model.

Promotion = reproducible stronger evidence + no loss in cold/reliability/latency + rollback readiness. Time available may favor a simple conservative improvement rather than a shaky complex one.

## Performance budget

- At ~3 req/s, 50-record newest-request polling covers just **~16.7 seconds** of stream, so avoid losing requests on restart or slow poll. Prefer a durable checkpoint/cursor or safety overlap and request-ID deduplication; validate against observed RawTree query semantics.
- The **3-second deadline starts at request `ts`**, so **polling + querying + computation + batched POST + network latency** must fit. Starter polls every 0.3s, normal total ~1s, p95 ~1.5s. Performance optimization should preserve this working path.
- Use cached item/feature snapshots; do not run heavy RawTree joins or 12M-event scans per request. Refresh stock frequently (starter checks ~1s), update incremental trends asynchronously.
- Prioritize **0 invalid slates** and measure actual `feedback.latency_ms`, `served_by`, `fallback_reason`, not just local inference time. Check error spikes during network outages.
- Only one process writes to `submissions`; send once/request, batch perhaps every 0.5s, and avoid replay on restart. Log source event time (UTC), wallclock, model version and upload success.

## Parallel work priorities and team division

1. **NOW:** one owner gets starter running and feedback on leaderboard; one owner inspects history / builds time-split evaluation; one owner prepares RawTree SQL/incremental catalogue, another starts personalization candidate features.
2. **NEXT:** fit/test baseline heuristics and learned ranker; compare results on same holdout; build cold-start text/category representations and trend changes.
3. **LATER:** optionally add online Bayesian reweighting or bandit if demonstrably valuable, along with offline evaluation and reporting.
4. **BEFORE Sunday 10:00 CET:** champion deployed, credentials and machine uptime verified, 3-second end-to-end feedback verified, stock freshness and backup runner tested, experiment freeze + rollback. During final only safe recovery changes.
5. **JURY:** show architecture, source-feature timeline, genuine offline results/limitations, evidence of stream adaptation, RawTree SQL queries/visualization, demonstration and clear business explanation. Preserve readable repo and commit history.

## Research questions to test first

- Does the old baseline ignore session history enough that co-view / same-subcategory targeting wins substantially?
- How much more predictive are `recent_views` vs global popularity? Does personalization beat category-only baseline on **cold/new buyers**?
- Is a ranker trained on old impressions biased enough to lose to a heuristic? How much does propensity correction help when weights are clipped?
- Are simulator trends more visible in organic `shop.events` than in own sparse feedback?
- How frequently does active inventory change, and how many invalid slates does a stale cache cause?
- How much position/redundancy correction is supported by observed historical data? Is category diversity helpful or harmful?

## Sources and changelog

- Rules: https://datathon.rawtree.dev/ ; https://github.com/rawtreedb/datathon-fme-2026
- Starter + evaluation: https://github.com/rawtreedb/datathon-fme-2026/tree/main/starter
- **2026-11-14 v1.0:** replaced verbal-rate and reward assumptions; reprioritized historical ranker + cold start + offline evaluation; added actual table names, 3/s throughput, correct scoring, jury and final-phase details. **No team-specific experiments have yet been performed by the author of this file.**
