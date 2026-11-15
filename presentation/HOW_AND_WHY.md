# The HOW and WHY — presenter notes and judge walkthrough

The initial pitch has three minutes. Explain decisions and give one credible result; save code details for questions. This document is the longer-round preparation, not an instruction to retrain or restart the live system.

## The story in one sentence

We learned that the difficult part was deciding which evidence to trust, then built a small ranker around reliable data, controlled experiments and a bounded serving path.

## 1. Why a linear model?

The early gradient-boosting approach captured patterns in historical exposure that did not transfer cleanly to the live carousel. A later comparison on held-out shoppers did not justify gradient boosting or the tested interactions over the simpler model (R-24 / E-260). We kept the model whose measured behavior justified it.

Linear scoring made each feature's contribution inspectable and kept local ranking inexpensive. This is not a claim that linear models are universally superior.

Code to show: ../recsys/lfm.py, features(), LiveFit.scores(), top_items().

## 2. How did training work?

Code to show: ../recsys/lfm_build.py, impressions(), fit(), holdout(), leaks().

1. A logged request supplies ten exposed products. Build one row per shown product.
2. Join the request's context, user history and earlier activity to the observed click/purchase.
3. The baseline fits a regularized logistic model using clicks, with purchase rows weighted x3. Clicks provide a denser signal than purchases.
4. Include log(slot) in training to account for some position effects. This does not solve selection bias or identify responses to every unshown product.
5. Fit separate known/new models and purchase calibration for reports.
6. Split by time. Fit before the cutoff and evaluate after it. Rebuild a prefit base if its training period overlaps the holdout.
7. The final policy combines committed coefficients with selected cohort/home overrides and later refits. Running the default baseline fit once does not reconstruct every final setting.

Say: "We only label products that were exposed; an unshown item is not a failed recommendation."

Do not say: "Our logs give unbiased conversion for any new slate."

## 3. How does it adapt without retraining during the final?

Separate parameters from evidence.

- Fixed parameters: selected scoring weights and policy configuration.
- Fresh evidence: shopper/session memory, organic product counts, catalogue/price/stock and event-based trend flags.
- Purchase memory: includes historical, Saturday organic and private-feedback purchases; the final continues the same world.
- Cart events: activity signals, not future orders.

Quality uses organic views and organic purchases. Carousel feedback is an exposure process chosen by our own policy, so its purchases must not be added to an organic numerator without their exposure denominator. We found and fixed this separation.

Code to show: ../recsys/live.py, LiveTables.add_organic(), refresh_events(); ../recsys/trends.py, snapshot(); ../recsys/lfm.py, organic_quality().

The optional attribute prior was not enabled in the final handoff. Do not present it as serving new launches from metadata in the deployed system.

## 4. Why compare the same windows?

A different hour can have different shoppers, trends and inventory. We read each practice policy against the reference from its exact window. Some experiments used stable assignment by user; others used time blocks. Do not call a block comparison randomized A/B.

The +0.17 pp result is an observed reference-adjusted difference across eight blocks, 10,800 requests per policy. It is not proof that every component independently caused that gain.

Offline metrics screen hypotheses. Latency and valid output establish engineering behavior. The live simulator evaluates served slates. Those are three different claims.

## 5. How did agents help, and how did you check them?

We used Claude and Codex for implementation, hypotheses, analysis, code review and tests. The runtime does not call either model for each recommendation.

Concrete example: a test mock returned all feedback rows, ignoring the real query's ten-minute time filter. Tests passed while a long interruption could still cause purchases to be missed. A timestamp-aware counterexample failed on the old reader; T-066 changed recovery to use the last successful applied watermark. Passing tests are useful only when their assumptions match the real interface.

Other ideas were rejected after measurement: some price/discount changes, sequence models, excessive launch/trend doses and tested model interactions. Agent suggestions did not become evidence merely because they came with plausible explanations.

Human ownership stayed explicit: isolated experimental branches, documented decisions, and one owner controlling live integration and promotion.

## 6. Why did the serving design matter?

Expensive SQL aggregation and feature refresh occur in the background. The response path uses local scoring, filters purchased/unavailable items, validates the slate and batches writes. Durable request claims and a local OS lock reduce duplicate submissions.

The lock is local; it is not a cross-laptop lease. Do not promise automatic failover between machines.

Code to show: ../recsys/serving.py, Journal, WriterLock, serve(); ../recsys/live.py, send_answers().

Documented practice reliability: 43,182/43,200 on time, p99 2.35 s, 04:00–08:00 CET. Use the exact window; do not claim that all final requests met it.

## Suggested 60-second code walkthrough, if invited

1. 0–15 s: show fit() and explain exposed rows, click labels, x3 purchase weighting and slot effects.
2. 15–30 s: show shared features() and a policy override; distinguish model parameters from fresh feature state.
3. 30–45 s: show the feedback-watermark regression and the counterexample it captures.
4. 45–60 s: show serve()/send_answers() and the evidence table in the root README.

Use source and cached artifacts. Do not start another writer, refit on the production Mac, expose keys, or depend on a live query working on stage.

## Brief team credit

Salvador Coll, Héctor Verdeal, Daniel Nieto and Javier Andrés García. The initial pitch uses one credit line; team members can expand on the decisions they drove during questions. Team-level workstreams and agent use are recorded in TEAM.md.
