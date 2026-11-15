# Team 26 — recommendations that remember, adapt and arrive on time

Our entry for the **RawTree Challenge, Datathon FME 2026**. One serving process ranks ten eligible products for each shopper within a three-second deadline. We chose a lightweight model and concentrated on trustworthy evaluation, live feature updates and reliable delivery.

**Final configuration reported by the deployment owner:** policy ur2, serving commit e8a1f18, fixed from 15 Nov 09:20 CET. This repository also contains experiments that were never deployed. Presence in Git does not mean a feature ran in the final.

## For the judges

- [Three-minute PDF](presentation/pitch_3min/Team26_3min.pdf), [editable PowerPoint](presentation/pitch_3min/Team26_3min.pptx), [browser deck](presentation/pitch_3min/pitch.html), [speaker script](presentation/pitch_3min/SCRIPT.md).
- [Evidence, windows, sample sizes and limitations](presentation/pitch_3min/EVIDENCE.md).
- [Training and evaluation walkthrough](presentation/HOW_AND_WHY.md).
- [Team and coding-agent credits](presentation/TEAM.md).
- [Experiments](experiments.md), [rejected ideas](insights.md), [decisions](decisions.md).

The final result is not yet included. Practice metrics below are labeled and must not be presented as final performance.

## Why this design

**Require evidence for complexity.** Early gradient boosting was superseded by a context-aware linear ranker. A later held-out comparison did not justify returning to gradient boosting or adding the tested interactions (E-260 / R-24). This is evidence about our experiments, not a universal claim about nonlinear models.

**Personalize with incomplete history.** Returning shoppers use historical and live preferences. New shoppers use session evidence and memory of earlier visits. A shopper can return repeatedly while still being marked new.

**Keep the policy stable while the evidence changes.** Organic views and purchases update product quality; event-volume changes drive trends; catalogue updates change price and eligibility. Known purchases remain excluded across the final-round boundary.

**Treat delivery as part of recommendation.** Background refresh, local ranking, validation, durable request claims and batched writes keep expensive aggregation away from the response deadline.

## How the baseline is trained

The reproducible baseline pipeline is [recsys/lfm_build.py](recsys/lfm_build.py); shared features and scoring are in [recsys/lfm.py](recsys/lfm.py).

1. Join served requests, their ten shown products, private clicks/purchases and earlier organic activity. Each exposed product becomes a row. **Unshown products are not labeled failed recommendations.**
2. Reconstruct user state before the request. Replay historical price/stock where available. Reports identify metadata that cannot be reconstructed exactly.
3. Fit separate regularized logistic models for known and new shoppers. The baseline target is a click, with purchased rows weighted three times as heavily. A log-slot term models position effects in training.
4. Fit purchase calibration for reporting. Serving ranks linear scores; policy overrides do not automatically preserve the old probability calibration.
5. Train on earlier requests and evaluate later requests. A base artifact is rebuilt on the training split if its original training period overlaps the holdout.

The final JSON contains cohort/home-specific overrides and subsequent refits. It is **not** reproduced by running the baseline fit once. The selected policy, coefficient files and deployment handoff identify what actually ran.

Signals include description-attribute affinity, current/previous views, category preferences, organic quality, cart activity, launches and trends. Carts are activity signals, **not pending orders**.

## How serving works

    Shared requests + organic events + catalogue updates
                         |
             SQL and background feature snapshots
                         |
           Context-specific local linear product ranking
                         |
           Purchase exclusions + stock/slate validation
                         |
          One writer -> batched submissions -> private feedback
                                                 |
                  Offline training/evaluation <--+
                  Permanent purchase memory   <--+

Private carousel purchases feed user state/exclusions, not organic purchases-per-view numerators. This prevents an accounting feedback loop we found during development.

| Component | Code | Purpose |
|---|---|---|
| Live process | [live.py](recsys/live.py) | Read, refresh, score and submit |
| Ranking/features | [lfm.py](recsys/lfm.py) | Shared features and eligible top ten |
| Training/replay | [lfm_build.py](recsys/lfm_build.py) | Exposed-item learning and temporal comparisons |
| Serving safeguards | [serving.py](recsys/serving.py) | Claims, local writer lock, repair and deadlines |
| Trends | [trends.py](recsys/trends.py) | Organic activity changes, without a hard-coded trend clock |
| Final template | [policy.rot_ur2.json](recsys/policy.rot_ur2.json) | Configuration reported by the deployment owner |
| Offline league | [LEAGUE.md](tools/LEAGUE.md) | Cached time splits, uncertainty and sealed test |

The writer lock coordinates local processes, not separate laptops. Deployment belongs to one designated owner.

## How we decide whether an idea works

**Offline screening:** chronological holdout, shared features, cohort slices, negative controls where appropriate, valid output and latency. Historical exposures are biased; retrieval and model-estimated scores are not unbiased full-slate conversion.

**Live confirmation:** compare exact practice windows with the reference from those same windows. We used user-hash A/B and time-block comparisons at different stages; they are not interchangeable. Time blocks retain possible temporal confounding.

**Final operation:** freeze the policy, keep features updating and monitor feedback. Serving does not depend on leaderboard access.

| Finding | Measurement | Limitation |
|---|---|---|
| Refitted weights | +0.167 pp versus predecessor after reference adjustment; 8 blocks, 10,800 requests per policy | Time blocks, not randomized contemporaneous A/B |
| Reliability | 43,182/43,200 valid/on time (99.96%); p99 2.35 s | Practice, 15 Nov 04:00–08:00 CET |
| Team expected conversion | 2.159% on 10,800 requests | Practice, 08:00–09:00 CET; several versions, not final-policy-only |
| Request-derived taste | Out-of-sample support | No demonstrated live uplift at final handoff |

See [EVIDENCE.md](presentation/pitch_3min/EVIDENCE.md) for provenance. The optional new-product attribute prior was **not active** in the final handoff.

## Reproducing safely

Use the existing team environment or a separate review environment. Dependencies: [recsys/requirements.txt](recsys/requirements.txt). Private data/credentials are not included. Do not run training or rehearsals on the serving machine during the final.

Synthetic engineering checks from the repository root:

    python -m unittest tests.test_serving_reliability tests.test_feedback_watermark tests.test_lfm_rqa

Baseline temporal evaluation from downloaded private caches, without writing coefficients:

    cd recsys
    python lfm_build.py --no-write --cut "2026-11-14 14:30"

This is an example baseline evaluation, not final-policy reproduction. It needs private caches described by the training script. The offline league has its own [preparation/validation/sealed-test procedure](tools/LEAGUE.md); do not open its test to tune models.

Deployment commands remain in the owner-facing [runbook](runbook.md), not a one-click demo. There must be one submission writer.

## Team and coding agents

**Salvador Coll · Héctor Verdeal · Daniel Nieto · Javier Andrés García**

We used **Claude and Codex** for implementation, analysis, review, failure cases and documentation. They are development tools, **not LLM calls on the recommendation path**. [TEAM.md](presentation/TEAM.md) records the roster, project workstreams and agent use.

Our coordination pattern: isolated branches, recorded hypotheses, targeted checks and one owner of live integration/promotion. Generated code was not evidence that a model improved.

## Lessons and limits

- Aggregate associations can disappear after controlling for context and position.
- A passing test can hide a bug when its mock ignores real query semantics. A timestamp-aware regression exposed purchases lost after a long reader outage; T-066 fixes recovery.
- Organic repeat purchases do not follow the carousel's repeat-purchase penalty.
- Offline quality, retrieval, output validity and conversion are different claims.
- The final taste addition had limited live evidence; the final outcome is left to the organizers' scoring.

The [organizer brief](challenge.md) and [archived starter README](docs/ORIGINAL_STARTER_README.md) describe the challenge. Newer organizer clarifications supersede older copies.
