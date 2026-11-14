# Cold-start challenger (T-CS01) — what exists, what is weak, one measured fix

Owner: d4xn (+Claude), branch `feat/team26-coldstart-challenger` (from `main@23f0496`). Complementary to Javi's
T-009 (`cold_items`), T-013 (`home_cands`), T-017 (`attr_model`), T-018 (`live_quality`, `lfm`): it reuses them and does
not touch `live.py`. Nothing here writes to RawTree or starts a writer.

## 1. How cold start works in `main` today (read from the code, 14 Nov ~16:00 UTC)

| Question | Answer in the code | Active live? |
|---|---|---|
| New user | `shop.requests.is_new_user` ("not in the 60-day history"). lfm has two weight sets (`known` / `new`, `lfm_coef.json`). qrank/v1 do not distinguish | lfm: yes (`ab_lfm`/`lfm`) |
| New product | not in `qrank.joblib`'s `q` (or `cold_items` base ids). New products arrive by `catalog_updates.change='new_product'`; so far 100 at 10:00 and 100 at 14:00 UTC | catalogue refresh every ~20 s |
| Candidates | lfm: **no candidate list**, scores every active product (affinity × context × carts × `lq`). qrank: same-category pools by `q`. v1/GBM: rv + subcategory/category pools + user history + `new` pool (same category) | lfm/qrank live |
| Quality without history | qrank `set_catalog`: **median q of the subcategory** for products without q, all day. lfm uses that `lq` (weight 0.48 known / 0.61 new). `cold_items` GLM prior (phrases × category × brand × price) is used only by the GBM path with `aff*` variants and by `live_quality` (off) | median: yes; GLM prior: no (off variants) |
| Category / brand / description / price / trends | lfm: affinity to the 20 description phrases (`attr_affinity`), same sub/category/brand as last view, attribute overlap `na`, `lq`. Price and trends: only in `live_quality` (promo ×1.145, hot subcategories) and `attr_model`, both off | partly |
| Product with no views/purchases | lfm: lq = sub median, affinity from its phrases, no penalty; qrank/v1: median q / zero counts | yes |
| Home without recent_views | lfm: only affinity (history + live views), carts (history not bought / today), `home` flag, `lq`. New user + no history => essentially `lq` order. `home_cands`/`d130` exists but `mode=off` | lfm yes, d130 off |
| Stock / catalogue changes | `stock_refresher` every 1 s, `repair()` before POST (unavailable → replaced from best sellers, version `-guard`), catalogue + new products every ~20 s | yes |

Policies implemented but **off by default**: `aff`, `qrank_aff`, `attr`, `attr_aff` (+ `ab_*`), `d130` (`nodead`/`home`),
`live_quality` (`lq.json`), qrank tuning arms, lfm arms (T-021, branch). Live since 14:33 UTC: `ab_lfm` (lfm vs qrank),
then lfm labels made opaque at ~15:01 UTC (HANDOFF.md). Do not assume an off module is serving.

## 2. Where cold start is weak — measured

**E-CS01a — the offline league cannot measure cold start.** Validation (10,000 impressions, 27 Oct–5 Nov): 0 products
created after the training end, 0 catalogue updates, 5 impressions of users unseen in training, home 2,050
impressions with 12 clicks. Only "known user with recent views" has support (7,945 impressions, 371 clicks).
`python -m tools.league_segments --profiles data/graph/profiles.json` reproduces it. → Cold start can only be
evaluated on today's live stream (time split), as Javi did in E-090b / E-180.

**E-CS01b — our live slates hide new products (OBSERVED, our own feedback, 14:35–15:40 UTC, 11,700 requests).**

| Segment | Requests | Buy / request | New products in our impressions | Slates with a new product |
|---|---|---|---|---|
| known / product | 4,578 | 1.46% | 0.15% | 1.5% |
| known / category | 1,963 | 2.24% | 0.16% | 1.6% |
| known / home | 1,678 | **0.36%** | 0.22% | 2.1% |
| new / product | 1,952 | 2.72% | 0.10% | 1.0% |
| new / category | 856 | 2.92% | 0.08% | 0.8% |
| new / home | 673 | 0.74% | 0.24% | 2.4% |
| **all** | 11,700 | 1.71% | **0.15%** | — |

Organic stream (all of today): the 200 new products got **2.4% of views and 2.8% of purchases** (purchase/view 6.2% vs
5.3% overall). Our carousel shows them **16× less** than shoppers view them; 2 of our 200 purchases (1%) were new products.
Home of known users (0.36%) is the weakest segment but already owned by Javi (`javi/home-known-findings`) and Salva
(`salva/k27`), so not taken here.

**E-CS01c — the median-q rule places new products badly; Javi's estimator does much better (OFFLINE, strict time split
on organic `shop.events`).** For each launch batch L: features = catalogue + description + the product's organic
events in [L, L+h); target = its organic purchase/view in [L+h, next batch or +4 h), expressed as a quantile among the
established products of its subcategory in the same window. Predicted quantile = the lq the serving would use vs the
established products' lq. `python cold_lq_eval.py`.

| h | new products | current (sub median) MAE | ablation, no phrase prior | prior only | **prior + live (cold_lq)** | top-quartile recall current → cold_lq |
|---|---|---|---|---|---|---|
| 0 min | 176 | 0.256 | 0.345 (worse, CI +0.044…+0.133) | 0.196 | **0.196** (Δ CI −0.098…−0.023) | 0.00 → 0.69 |
| 30 min | 161 | 0.265 | 0.307 | 0.203 | **0.200** (Δ CI −0.105…−0.024) | 0.00 → 0.78 |
| 60 min | 131 | 0.257 | 0.271 | 0.200 | **0.182** (Δ CI −0.116…−0.033) | 0.00 → 0.77 |

Noise floor (established products, history lq vs today's realized quantile): MAE 0.165 (n = 8,965). Spearman
predicted/realized quantile: current 0.05–0.18, cold_lq 0.59–0.69. 31% of new products realize their subcategory's top
quartile; the median rule never puts one there. A re-derivation with our own calibration (OLS slope 1.48 instead of
Javi's 2.0) gave the same picture (MAE 0.191 / 0.191 / 0.169), so we ship Javi's.

Finding for Javi (I-CS02): `LiveQuality(prior=None)` — its fallback when `cold_prior.json` fails to load — is **worse
than the median** at launch (150 of 176 new products predicted top quartile). Keep the GLM prior mandatory when lq is on.

**E-CS01d — effect on lfm's slates** (same 900 real requests of 14:5x–15:00 UTC, same per-user state, offline,
`python cold_lq_slates.py`, 41 s, 2.4 GB):

| Segment | Requests | New products in lfm impressions: qrank lq → cold_lq | Slot 1 new | Slates with ≥ 1 new |
|---|---|---|---|---|
| known / home | 123 | 0.08% → 6.99% | 0 → 4.1% | 0.8% → 57.7% |
| known / with views | 487 | 0.14% → 5.42% | 0 → 4.3% | 1.4% → 44.6% |
| new / home | 61 | 0.00% → 5.90% | 0 → 1.6% | 0 → 50.8% |
| new / with views | 229 | 0.09% → 6.20% | 0 → 6.1% | 0.9% → 46.3% |
| **all** | 900 | **0.11% → 5.87%** | 0 → 4.6% | 1.1% → 47.2% |

The offline baseline (0.11%) matches what we observed live (0.15%), so the replay is faithful. 100% valid slates in both.
cold_lq's predicted quantiles are slightly optimistic (mean +0.05…+0.07 vs realized; the median rule is −0.07…−0.11);
false promotions (predicted top quartile, realized below the median) 10% at launch, 4% after 60 min. Exposure ends at
~2.4× the organic view share: whether the hidden model rewards that is exactly what the live block must answer.

## 3. The change (one hypothesis: better new-product quality for lfm)

`recsys/cold_lq.py` (≈60 lines) reuses `live_quality.LiveQuality` + `default_prior()`; only products without a history q
change; qrank, `QR.lq` and established products are untouched; off unless `data/coldlq.json` = `{"mode": "on"}`.

Hook for the writer owner (proposal D-CS01, not applied): in `live.py`

```python
# initialize(), after qrank/aff_policy load
try: CLQ = cold_lq.ColdLQ()
except Exception as e: CLQ = None; print('cold_lq not loaded:', e, flush=True)
# refresher(), replace the LF.set_catalog(...) line
lq_lfm = CLQ.lq_for_lfm(QR, cat, BASE["item"], T.item_frame(), AP.cold.desc) if CLQ is not None and QR is not None else (QR.lq if QR is not None else None)
LF.set_catalog(cat, unavail, AP.aff, lq_lfm, d130.HC)
```

Test locally: `python -m unittest tests.test_cold_lq -v` (9 tests), `python -m unittest discover -s tests` (117),
`cd recsys && python cold_lq_eval.py` (cached snapshot; `--pull` refreshes it read-only), `python cold_lq_slates.py`.

A/B: lq is a property of the product, so the clean test is **time blocks** on the single writer: `{"mode":"on"}` and
`{"mode":"off"}` alternating every 15–20 min, read with the leaderboard's custom window (`/api/state?by=model&from=&to=`,
HANDOFF.md) per lfm label. A launch batch (next expected 18:00 UTC if the 4-hour pattern holds — not guaranteed) is the
moment the effect is largest. Rollback: delete `data/coldlq.json` → next refresh (≤ 20 s) is back to qrank's lq.

## 4. Limits

- Target is the **organic** purchase rate; the hidden carousel model is not observed. On established products log q
  and organic rate agree (within-subcategory Spearman 0.98, I-183 / our check), but for new products this is HYPOTHESIS
  until a live block.
- Two launch batches (200 products); the 14:00 batch has ≤ 1 h 40 min of target window.
- More exposure for new products can cost conversion if the hidden model does not reward them; the time-block A/B is the
  only valid check. No result here is an official score.
