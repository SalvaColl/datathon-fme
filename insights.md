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
- **Status:** IDEA (not yet empirically tested)
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
- **Status:** IDEA (training dataset now confirmed)
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

### I-020 — Organic item graph: weak on logged-policy proxies, unclear as a ranker, plausible as retrieval
- **Status:** INVESTIGATING (d4xn+Claude, 2026-11-14, E-020; offline estimate)
- **Evidence:** on the league validation period, graph-only policies have hit@10 0.16–0.20 vs 0.38 (baseline) and
  0.72 (`mixed_category`), and lower slot-1 SNIPS(buy) with CIs excluding 0; cart/purchase weighting helps over plain
  co-views; temporal decay does not. Recent-view-first policies have ESS ≈ 7 (inconclusive).
- **Potential confounding/weakness:** both metrics are anchored to the category-locked best-seller logging policy; a
  popularity-normalised graph is by construction far from it. Cannot place brand-new products (no edges).
- **What changed:** nothing in serving. Graph kept offline as a retrieval idea.
- **Next action:** feed graph neighbours of the recent views as extra candidates into the GBM pool and measure with a
  GBM league adapter or a writer-owner A/B; consider an organic next-event proxy (validation-period organic events)
  with Salva before trusting any graph ranking.

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
