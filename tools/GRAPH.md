# Graph challenger (T-GR01) — handoff for the offline league

Independent item-to-item graph policies built from **training-period organic `shop.history_events`** and evaluated
with the existing league (`tools/LEAGUE.md`). Offline only: no serving code, no writer, no submissions.

## Run (same environment as the league; stdlib + `requests`, nothing new to install)

```bash
python -m tools.local_league prepare --sample 10000          # once, if data/local_eval/league_v2 does not exist
python -m tools.graph_build --pin                            # ~1 min, read-only RawTree; writes data/graph/*.json + tools/graph_pins.py
python -m unittest tests.test_graph_policy -v                # 13 tests, synthetic data, no network
python -m tools.local_league validation --plugin tools.graph_policy --bootstrap 300 \
  --policies baseline,mixed_category,same_subcategory,rv_first,graph_A,graph_B,graph_C,graph_B_rv,graph_B_rv_profile
```

Do **not** run `freeze`/`test` for these policies yet: nothing here is selected for a final test (see results).
If you rebuild artifacts, `--pin` rewrites `tools/graph_pins.py`; the policies refuse unpinned artifacts and artifacts
whose training window differs from the league training snapshot (leakage guard). `created_utc` is in the artifact, so a
rebuild changes the hash even when the graph is identical: review the diff of `graph_pins.py`.

## What is built (all inside RawTree, one aggregate query per artifact; SQL stored in each artifact's provenance)

- Window: `[boundaries[0], boundaries[1])` from `manifest.json` = 2026-09-15 07:00:06.371 → 2026-10-27 07:00:01.356 UTC.
- Organic only: `view`, `add_to_cart`, `purchase`. Not used: `history_sessions.shown` (would reproduce the logging
  policy), propensities, feedback, anything from validation/test.
- Real `session_id` exists (2.5 M sessions, mean 4.8 events, max 25), so no sessionisation rule was needed.
- Per (session, product): strength = max event weight; position = rank of first event; first 20 products per session.
- Pair weight Σ over sessions; popularity-normalised `co / sqrt(deg_a · deg_b)`; edges in < 2 sessions dropped;
  top-30 neighbours per product (`LIMIT 30 BY a`). 5,000 nodes × 30 = 150 k edges, 3.8 MB per graph.
- `profiles`: per user, top-20 products by Σ strength in training (59,591 users, 18 MB).

| Artifact | Weights | Temporal |
|---|---|---|
| `graph_A` | view = cart = purchase = 1 | no |
| `graph_B` | view 1, cart 3, purchase 6 | no |
| `graph_C` | as B | `/ |Δpos|`, only `|Δpos| ≤ 5` |

## Policies (`tools/graph_policy.py`)

`graph_A/B/C`: sum of neighbour scores of the last ≤ 5 distinct recent views (weight 0.7^k, most recent first).
`*_rv`: eligible recent views first. `*_profile`: also seeds from the user's training profile (weight 0.3, normalised).
`rv_first`: recent views first, no graph (attribution control). Fallback for every policy: training purchase popularity
in the last viewed category, then global, then any eligible product. Exactly 10 distinct eligible ids whenever ≥ 10
are eligible; otherwise all eligible ones (the league then marks it invalid; documented and tested).

## Validation results (E-GR01, N = 10,000 validation impressions, 300 hour-block bootstrap replicates)

See `experiments.md` E-GR01 for the table. Short version: graph-only policies are **below** the popularity baselines
on hit@10 and slot-1 SNIPS(buy) with CIs excluding zero, and policies that diverge from the logging policy have very
low ESS (7–59) → slot-1 IPS/SNIPS are **inconclusive** for them. Inference p99 ≤ 0.17 ms (0.64 ms with profiles);
validation of 9 policies 18 s, peak RSS 0.5 GB; build 62 s, peak RSS 0.66 GB.

## Limits you should keep in mind

- hit@10 counts the logged click among *our* 10; the logged slates were category-locked best sellers, so the metric
  rewards imitating that policy. Slot-1 IPS only has support where our first item equals the logged first item.
- No GBM league adapter exists in any branch, so GBM is not in the comparison.
- New products (final round) have no edges: the graph cannot place them; it falls back to category popularity.
