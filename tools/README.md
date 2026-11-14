# RawTree feedback and local league — drop-in scripts

Copy the `tools/` folder into your **existing team starter repository** (next to `.env` and `starter/`). Do **not** replace the official starter and do **not** launch a second live submitter.

## 1. Monitor live feedback

Keep `python starter/recommender.py` in terminal A. Open terminal B:

```bash
python tools/feedback_monitor.py
python tools/feedback_monitor.py --watch 15 --window 30
```

Queries `team_NN.feedback` read-only. Shows team vs fallback, click/purchase rates, revenue per request, latency percentiles, fallback reasons, and most recent responses.

## 2. Run the local league

```bash
python tools/local_league.py --sample 10000
```

First run queries RawTree historic sessions and saves an identical, fixed holdout to `data/local_eval/holdout.json` for repeatable comparisons. **Add `data/local_eval/` to `.gitignore`**. Repeat runs load the same holdout so changes can be compared fairly. `--refresh` intentionally collects a new holdout; don't refresh during a league series. Queries can take some time on the first run.

The historical cut is 7 days before the last historical session. Baseline popularity is computed only from events before that cut. Four policies included: global best sellers, category-first, subcategory-first, and a hybrid category mix. These are **starter challengers**, not validated winners. Add future policies inside `policies()` or refactor into your own modules.

Outputs: clicked-item hit rate at 10 (biased toward the historical carousel), inverse-propensity and self-normalized estimates for slot 1 clicks, a slot-1 purchase proxy, matches with the logged item, and effective sample size. They **are not** the organizer's full-slate score, and they can be noisy for challengers with few logged-policy matches. This is why your first local objective is testing and rejecting ideas, not claiming a precise conversion uplift. The organizers' `starter/offline_eval.ipynb` uses the same evaluation principles.

## 3. Promotion rule

- Keep live baseline running in one terminal.
- Each agent works in a branch/worktree and adds a policy to the read-only evaluator.
- Use the same cached holdout and a separate validation period if tuning heavily.
- Require valid 10-item output on all cases and high enough effective sample size before trusting slot-1 scores.
- Test latency, new products, stockouts, and requests with no recent views before deployment.
- Merge only after review; have one operator restart/swap the **single** live runner.
- Record observed offline + live metrics in `experiments.md`.

## Sources

- https://github.com/rawtreedb/datathon-fme-2026/blob/main/starter/queries.sql
- https://github.com/rawtreedb/datathon-fme-2026/blob/main/starter/offline_eval.ipynb
- https://datathon.rawtree.dev/
