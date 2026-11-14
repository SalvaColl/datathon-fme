# T-021 independent purchase policy

Branch `codex/content-linear-t021`. Implementation lives only in `tools/content_*`;
no graph, serving, `.env`, submission or live-loop changes. Existing Python environment;
no installations. `fit(training_snapshot)` and `recommend(request, features, catalog)`
implement the existing league contract. `features` is currently unused.

Run from the repository root in PowerShell:

```powershell
# Existing available interpreter on this workstation; install nothing.
$py = 'C:\Users\hecto\miniconda3\python.exe'
# Read-only downloads; reuse the completed immutable cache on subsequent runs.
& $py -m tools.content_data
& $py -m tools.local_league validation --cache data/local_eval/content_t021 --plugin tools.content_linear --policies baseline,same_category,same_subcategory,mixed_category,content_only,content_linear --bootstrap 500
& $py -m tools.content_validate --cache data/local_eval/content_t021 --bootstrap 500
& $py -m unittest discover -s tests -p test_content_linear.py -v
& $py -m unittest discover -s tests -p test_local_league.py -v
```

Do not run league `prepare`/`test` for this experiment. The dedicated downloader creates
training and validation only, never a final-test file. Completed caches are immutable.
Private data/reports are under ignored `data/local_eval/content_t021`; preserve them
for bit-identical reproduction. The manifest contains exact SQL, boundaries, seed,
snapshot SHA256 hashes, catalogue assumptions and sampling details. If the old legacy
holdout cache is absent, its request IDs cannot be excluded; this is recorded in the
manifest. This is not guaranteed to reproduce the earlier E-011 sample after source changes.

Representation: training-start TF-IDF description unigrams/bigrams (5,000-term cap),
category/subcategory/brand indicators and smooth log-price bands. Parameters are
fitted only on products available at training start. Missing text uses metadata and
price; unknown words/categories are ignored. Shopper vectors combine recency-weighted
recent views and the last 40 sampled organic events (view/cart/purchase weights 1/3/2,
14-day half-life). Organic events are replayed strictly before every training request;
event-time vectors are preserved and profiles freeze at training end for validation.
The 200,000-event deterministic sample gives incomplete histories and is not weighted
to reconstruct full organic counts. Full-period organic purchases determine fallback
order only, not earlier supervised features. Historical carousel rewards do not update profiles.

Retrieve 150 cosine neighbours, retain eligible recent-view items and 30 popularity
candidates. Unknown shoppers with no views use popularity candidates. The learned model
uses item content, sparse shopper/item and last-view/item interactions, similarity,
relative price, recent-view flags and category/context/price interactions. It has no
product-ID or user-ID coefficients. Regularization C=1 is predeclared, not a validated
optimum. Registered C=.1/10 alternatives are available for future validation-only tuning.
Both the content-only ablation and learned ranker use the same candidate procedure;
the content-only policy ranks by cosine with popularity ties. Product main effects
are shared text/metadata weights rather than learned ID intercepts.

Purchase labels are created only for actually shown, reconstructably eligible items.
No unshown negative sampling. Uniform weight per exposed item; no class balancing or
inverse-propensity training. Logged slot indicators are nuisance covariates; inference
scores all candidates as slot 0. This does not remove exposure, position, within-slate
dependence or policy confounding. Rare first-action support and approximate hourly-block
bootstrap intervals must be inspected with purchase/click IPS/SNIPS, matches and ESS.
Do not interpret these as expected full-slate conversion.

Catalogue history is explicitly **unreconstructable** for base field changes. Base
descriptions/brands/prices/status are assumed initial; creation times and timestamped
updates can be replayed, but no historical-field guarantee exists. Current merged
metadata is never substituted into training. Every inference checks current stock,
creation time and metadata before using cached content vectors; in-place changes and
new IDs invalidate the index. Stock freshness still depends on the caller supplying
an up-to-date snapshot. Fewer than ten eligible products raises an explicit error:
fabricating IDs cannot satisfy the contract. Otherwise exactly ten distinct eligible
real IDs are returned. Pre-training-cutoff inference is rejected to avoid frozen-profile leakage.

Masked-item simulation fixes a SHA256-based 20% mask using training product IDs and a
fixed seed. Masked products are absent from vocabulary fitting, profiles, popularity
and supervised exposures. They reappear with content during validation, including in
recent views. It is an interaction-removal simulation on existing products, not actual
launches, official cold-start performance or a final-test estimate. Shared attributes
and users remain. The masked-view cohort is defined by views, not validation rewards.

The checked-in GBM was trained into November, later than this league's October 27
training cutoff. There is no registered GBM league adapter. Scoring that artifact would
leak later labels; its direct comparison is therefore unavailable here. No GBM is refit
in this independent content-policy workstream.

Failure checks cover only-exposed labels, strict event-time ordering, future views,
unknown users/items, missing descriptions, mutable stock, new products, masked vocabulary,
one-class fallback and impossible inventory. Existing league tests cover label isolation,
snapshot checksums and final-test guards. Local inference timings exclude network,
polling and submission; they do not establish the live SLA. Model is single-threaded
stateful inference caching; a serving owner must handle concurrency and fresh inventory.

Strengths: explainable linear interactions, bounded content retrieval, transfer to
low-history products and deterministic fallback. Weaknesses: sparse purchases, incomplete
organic history, frozen interests, generic text, unknown vocabulary and the limitations
of additive logistic interactions. No claimed conversion gain without measured support.
Rollback: leave the current live champion running and discard this offline challenger.
Promotion, integration, merge and deployment remain the serving owner's decision.
