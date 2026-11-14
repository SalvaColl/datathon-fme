# RawTree Real-Time Recommendation Challenge — official specification

**Status: VERIFIED FROM ORGANIZERS' PUBLIC RULES — 2026-11-14.** All timestamps in source data use UTC; event times below are Europe/Barcelona, **CET (UTC+1)**.

Authoritative sources (check for changes):
- Challenge: https://datathon.rawtree.dev/
- Official repository / README: https://github.com/rawtreedb/datathon-fme-2026
- Starter implementation: https://github.com/rawtreedb/datathon-fme-2026/blob/main/starter/recommender.py
- SQL examples: https://github.com/rawtreedb/datathon-fme-2026/blob/main/starter/queries.sql
- Offline evaluation: https://github.com/rawtreedb/datathon-fme-2026/blob/main/starter/offline_eval.ipynb
- Leaderboard: https://datathon.rawtree.dev/leaderboard

## Task and timeline

- The shop has **~5,000 products** across **10 categories** and ~90 subcategories.
- New recommendation requests enter **`shop.requests` at approximately 3 requests/second**, not one every three seconds. Live organic events plus catalogue updates are approximately 50/second according to the site.
- For every request, write an **ordered array of exactly 10 distinct, active product IDs** into RawTree **within 3 seconds of the request's `ts`**, as judged by organizers' clock. Order matters; earlier slots attract more attention.
- Your system continuously polls, predicts and submits; **there is no uploaded prediction file or required externally hosted HTTP recommendation endpoint**. A continuously running laptop is acceptable if it stays awake and online.
- **Practice:** Sat 2026-11-14 10:00 through Sun 2026-11-15 10:00 CET. Public leaderboard refreshes **every 10 minutes**, showing the **last hour** of practice. Practice does not count toward official score.
- **Final:** Sun 2026-11-15 10:00–12:00 CET, **new shoppers, new products, new trends**. Leaderboard goes dark (only green/red team health status); final score published at 12:00. The team's same live process continues to serve requests and receive feedback. Best tested version should run before 10:00.
- Rough volume at full advertised rate: 10,800 requests/hour, 259,200/day, 21,600 in the two-hour final. These are estimates, not guarantees.

## Scoring (100 points total)

| Component | Points | What matters |
|---|---:|---|
| Final-round conversion | **50** | Simulator's **expected purchases per 100 requests**, not only realized random purchases |
| Final-round cold start | **10** | Same expectation on cold requests only |
| Final-round reliability | **10** | Fraction of requests answered validly and on time |
| Jury: method | **10** | Sound methodology and credible offline validation |
| Jury: learning from stream | **10** | Adaptation to feedback, trends, price changes, cold start, exploration |
| Jury: RawTree use | **5** | Feature calculations in SQL, embeddings if relevant, reliable data pipeline |
| Jury: communication | **5** | Explainable solution and concise demo |

For conversion and cold start, organizers normalize to 0–100 using `100 * (team - baseline) / (oracle - baseline)`, clipped to `[0,100]`. Baseline is the starter best-sellers recommender; oracle is the hidden model's best 10 products. Leaderboard displays stream's 70 points normalized to 100 (~71 conversion/~14 cold-start/~14 reliability). **Official tie-breaker: expected revenue per request**; revenue is not the primary conversion metric. Real purchased items can slightly influence later user behavior. A **cold** request means `is_new_user == true` **OR** at least one `recent_views` product was introduced during the event (`change = new_product`).

**Crucial consequence:** optimize **purchase probability**, not raw selling price or revenue, except as a secondary/tie-break metric. Realized purchases in feedback are noisy proxies for hidden expected conversion; organize experiments accordingly.

## Data contract — RawTree

All data is in RawTree. Team has **one** secret `RAWTREE_API_KEY`, read access to shared `shop` database and read/write access to its own `TEAM_ID`, e.g. `team_07`. Never commit `.env` or share credentials with other teams.

### Historic (available from the start)

- `shop.catalog` (~5K): `product_id` (string), `category`, `subcategory`, `brand`, `price_eur`, `description`, `created_at`, `is_active`. Initial prices/status; update with catalog updates to obtain current catalog.
- `shop.history_sessions` (~2M impressions over 60 days): `request_id`, `ts`, `user_id`, `context` (`device`, `region`, `page`), `recent_views`, ordered `shown[10]`, ordered **`propensity`** (old policy slot-conditional probability), `clicked` (product ID or null), `purchased` (product ID or null), `revenue_eur`. Logged by old **best-sellers plus randomness** policy; highly exposure-/position-biased. Propensity is supplied to support off-policy correction.
- `shop.history_events` (~12M over 60 days): organic events `view`, `add_to_cart`, `purchase` with `ts`, `event_type`, `user_id`, `session_id`, `product_id`, `price_eur`, `device`, `region`. Useful for personal profiles, co-views and product signals not constrained by carousel exposure.

### Streaming (Sat–Sun)

- `shop.requests` **append-only**: `request_id`, `ts`, `user_id`, `is_new_user`, `context`, `recent_views`.
- `shop.events` **append-only**: live organic activity, same schema as history events; source of early trend signals.
- `shop.catalog_updates` **append-only**: latest full product state with `ts`, `change` in `new_product`, `price_change`, `out_of_stock`, `back_in_stock`; combine with `shop.catalog` to get current active products/price/description.
- `<TEAM_ID>.feedback` **team private**, arrives seconds after deadline: `request_id`, `ts`, `shown`, `served_by` (`team` or `fallback`), `fallback_reason` (`missing`, `late`, `invalid` or empty), `latency_ms`, `clicked`, `purchased`, `revenue_eur`. Empty string means no click/purchase; ignore placeholder row `request_id='__init__'`.
- `<TEAM_ID>.scratch`: team's schemaless JSON table for optional features/model outputs/embeddings.

Example request (abridged):

```json
{
  "request_id": "r_example", "ts": "2026-11-14T16:02:11.482Z",
  "user_id": "u_example", "is_new_user": false,
  "context": {"device": "ios", "region": "Catalunya", "page": "product"},
  "recent_views": [{"product_id": "p_example", "ts": "2026-11-14T16:01:40Z"}]
}
```

### Submission — ONE record per request

`POST https://api.rawtree.com/v1/tables/submissions?database=<TEAM_ID>`

```json
[{"request_id":"r_example","items":["p_01","p_02","p_03","p_04","p_05","p_06","p_07","p_08","p_09","p_10"],"model_version":"v1-hybrid"}]
```

`items` values above are **illustrative placeholders, not real product IDs**. Exactly 10 distinct and currently active real IDs are required. Late, missing and invalid submissions are served by the organizers' fallback, losing reliability points. Multiple answers for the same request are **not an update channel**; submit once. **Batch inserts** (e.g., every ~0.5 sec) rather than one HTTP call/request. The starter polls ~0.3s and normally responds ~1s, with p95 under ~1.5s from request timestamp.

RawTree query: `POST https://api.rawtree.com/v1/query` with JSON `{"sql":"SELECT ..."}` and header `Authorization: Bearer <RAWTREE_API_KEY>`. API host can be configured in starter using `RAWTREE_API_URL`. The starter uses `requests.Session()`, `.env`/environment variables `TEAM_ID`, `RAWTREE_API_KEY`, and `recommend(...)` as replacement point. Inspect actual function signature before modifying.

RawTree SQL columns are `Dynamic`; use casts such as `product_id::String`, `ts::DateTime64(3)` for joins and aggregate functions where required. Useful examples in `starter/queries.sql` include current catalogue (base + latest update), recent category popularity, 15-minute vs prior-3-hour trend lift, co-views, feedback conversion and latency/fallback, and historical position bias.

## Failure modes / operating rules

- A response is considered served **only if received in RawTree before `request.ts + 3s`**, not merely computed before then. Always include polling, inference, serialization, insert and network time.
- Current in-stock list must account for **catalogue updates**, including new products and out-of-stock/back-in-stock. Recommending one inactive item invalidates the entire slate.
- Feedback shows actual served slate and `served_by`; evaluate separately for `team` and `fallback`.
- Stream tables may have missing schema before their first rows are inserted (`Unknown expression identifier`); official starter retries.
- A laptop can run unattended, but it must stay awake and network-connected all night.
- External coding agents/LLMs **are allowed**. The jury may penalize unexplainable work. Code must generate recommendations automatically. Top teams share repository with jury.
- Team private feedback and credentials **must not** be shared with other teams.

## Open questions / discrepancies worth verifying at stand

1. Challenge site describes category-specific baseline; **official `starter/recommender.py` currently sorts global historic purchases and ignores `recent_views` in `recommend`**. Treat the actual running starter as your concrete baseline; ask organizers if benchmark semantics differ.
2. Does the historic `propensity` log cover every slot action under enough support for IPS? Validate notebook estimator before trusting it; zero-support slates cannot be reliably evaluated offline.
3. Are `clicked`/`purchased` mutually exclusive one-per-request by design? Examples contain single IDs; don't assume a more complex attribution model.
4. What's the precise leaderboard computation horizon when switching versions within one hour, and can we attribute feedback by submitted `model_version`? `feedback` schema doesn't list model version; join locally on `request_id`.
5. Does `is_active` in new-product/price updates always reflect stock, or must stock change be interpreted independently? Tests should validate both.

## Revision history

- 2026-11-14: Replaced preliminary verbal assumptions with published rules, schemas, scoring, dates, rates, starter details. Sources above; no API-key access or live test was performed while writing this file.
