# T-SA01 — Synthetic-alpha search for cold start (d4xn + Claude, `feat/team26-synthetic-alpha`)

Two pre-stated hypotheses, each against Javi's current signals, with a negative control and an out-of-sample check.
Analysis only: no serving module, no change to `live.py`/`lfm.py`, read-only RawTree. Caches under `recsys/data/`
are git-ignored.

## H2 — time since launch (DESCARTADO)

`python alpha_h2.py --pull` (two small read-only aggregates), then `python alpha_h2.py`.
Reference = `live_quality`'s recipe (cold_items prior + live views, K = 100), with the rate of every 10-min bucket
computed only from earlier buckets. O/E = observed purchases / expected, corrected by the clock O/E of established
products in the same bucket (0.94–1.09). Discovery: 10:00 batch; validation: 14:00 batch; negative control: 300
established products with fake launches at the same times. Data until 16:10 UTC.

| Age (min) | Discovery O/E [95% CI] | Validation O/E [95% CI] | Negative control O/E |
|---|---|---|---|
| 0–10 | 1.10 [0.82, 1.44] (51 buys) | 1.12 [0.79, 1.55] (37) | 1.12 [0.95, 1.32] |
| 10–30 | 1.00 [0.80, 1.24] | 1.07 [0.84, 1.34] | 0.96 |
| 30–60 | 1.04 [0.88, 1.21] | 1.15 [0.95, 1.37] | 0.95 |
| 60–120 | 1.00 [0.88, 1.12] | 0.95 [0.82, 1.09] | 1.05 |
| 120+ | 0.98 [0.93, 1.04] | 1.09 [0.79, 1.46] | 0.99 |

Every interval contains 1, both batches and the control look alike, and views per product per 10 min are flat with age
(7–8). There is no novelty boost or decay that the prior + Bayesian update misses at this power (it could still hide
±40% in the first 10 minutes, which carry ~2% of a product's day). Interactions with phrases/subcategory were **not**
tested: with no main effect, slicing would only add false positives. Two batches do not establish any periodicity.

Side check: organic views are not uniform across products (variance/mean 68, Spearman 0.97 with history views,
0.67 with history purchase rate), so the organic view share is a meaningful exposure reference for new products.

## Secondary artefacts (Phase 3) — DESCARTADO, one cheap check only

Product id (hex) vs historical purchase rate, 5,000 products: Spearman −0.005 (p 0.71); first/last hex digit and
`id mod 67` / `mod 69` Kruskal p = 0.30 / 0.81 / 0.81 / 0.09 (5 tests, none significant after correction). New ids
interleave with old ones. No seed search was attempted.

## H1 — today's carts reveal phrase/subcategory taste beyond lfm v2 (INCONCLUSO: same sign twice, not significant)

lfm v2 (T-021) already models the purchase side: `nbp` (phrases shared with something bought today), `bsub`
(same subcategory as a purchase), `aff10` with today's views, `cl` (the carted product itself). One new family, all
strictly before the request: `ncp` (phrases shared with a product carted today and not bought, itself excluded),
`csub` (same subcategory as such a product), `nbp2` (exact phrase pair with a purchase).
`python lfm_build.py --pull` (Javi's read-only pull) then `python alpha_h1.py`: `lfm_build.load()/impressions()`
unchanged, same logistic recipe, one fit per known/new, dead rows excluded, paired bootstrap over test requests.

**Discovery** (70/30 time split, train 11:09–14:49, test 14:49–16:22 UTC; 165,588 test impressions, 318 purchases):

| Model | AUC buy | AUC buy (new users) | Purchase log-lik | Δ vs lfm v2 [95% CI] |
|---|---|---|---|---|
| lfm v2 features | 0.879 | 0.887 | −1,859.9 | — |
| + carts family | 0.886 | 0.900 | −1,847.1 | **+12.8 [−3.8, +29.0]** (+40 nats / 1,000 buys) |
| + family from ANOTHER user (negative control) | 0.875 | 0.885 | −1,867.2 | −7.3 [−16.3, +0.7] |

Weights (new users): `ncp` +0.67, `csub` +0.82, `nbp2` −0.67 (the exact-pair nonlinearity does not help; dropped).
Known users: little (`csub` +0.34). Prevalence in test impressions: `ncp` > 0 in 37%, `csub` 6%.

**Pre-registered confirmation** (committed 16:28 UTC, before its data: family `ncp + csub`, fit on ts < 16:35 UTC,
test on ts ≥ 16:35): see section below.

Pull at 17:10 UTC; train 488,407 impressions (ts < 16:35), test 62,954 impressions, 100 purchases, 370 clicks:

| Model | AUC buy | AUC buy (new users) | Purchase log-lik | Δ vs lfm v2 [95% CI] |
|---|---|---|---|---|
| lfm v2 features | 0.884 | 0.898 | −627.6 | — |
| + `ncp`, `csub` | 0.888 | 0.911 | −623.8 | **+3.8 [−1.7, +10.2]** (+38 nats / 1,000 buys) |
| negative control | 0.884 | 0.900 | −627.9 | −0.3 [−2.3, +1.6] |

Weights again positive for new users (`ncp` +0.57, `csub` +0.62), ~0 for known users. **Verdict: INCONCLUSO.** The
effect replicated in sign and size (+40 → +38 nats per 1,000 purchases; the control is flat) but both intervals contain 0
with 100–318 test purchases. It does not meet the bar for a module. Cheapest way to settle it: re-run
`python lfm_build.py --pull && python alpha_h1.py --confirm` after ~300 test purchases (about 1.5 h more of traffic);
if the CI then excludes 0, the change for Javi is two columns in `lfm.features` (same code as `nbp`/`bsub` but over
today's carts) and a refit with his `lfm_build.py`, served as an `lfm_arms` arm for new users.

## Limits

- Impressions are what our own policies showed (mostly lfm/qrank): this measures predictive value among shown items,
  not a counterfactual conversion gain. Purchases are real feedback with noise, not the hidden expected-purchase score.
- One day of data; the final round has only new shoppers, where the effect would matter most if it holds.
