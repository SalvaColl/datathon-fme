# Team 26 — three-minute pitch

English. Six slides. Timings are rehearsal targets, not a promise of reading speed.
Aim for roughly 130–140 words per minute and rehearse with pauses. Slide sources are in the PowerPoint notes and EVIDENCE.md.

## 1. Ten products. Three seconds. One shopper. — 0:00–0:15

Ten products. Three seconds. One shopper. We are Team 26. The difficult part was choosing what to trust: old data, live behavior, or a more complicated model. Our answer was to make every extra layer earn its place.

## 2. A small model. A deliberate choice. — 0:15–0:55

We kept a linear ranker because gradient boosting did not improve our held-out results. For baseline training, each shown product becomes an example; unshown products are not labeled failures. Clicks provide more examples, while purchases receive three times the weight. We model slot position because exposure changes behavior. We reconstruct earlier shopper state and test on later requests. The final policy then combines cohort-specific refits and overrides, rather than blindly deploying the default training output.

## 3. Frozen weights. Live intelligence. — 0:55–1:30

We separated changing evidence from stable model weights. Shopper memory updates as people return, including new shoppers without historical profiles. Product quality uses organic views and purchases; recommendation purchases update user memory, not the organic rate. That separation prevents a feedback loop. Trends come from recent events versus a baseline, not yesterday's clock. This lets us adapt during the final without refitting on a handful of noisy purchases. Previous purchases still stay excluded.

## 4. Measure before believing. — 1:30–2:10

Offline screening was not enough, because logged impressions reflect what earlier policies chose to show. For live checks, we compared against the reference in the same windows, so a better hour would not look like a better model. Across eight practice blocks, refitted weights showed a zero-point-seventeen percentage-point improvement, with ten thousand eight hundred requests per policy. These were time blocks, not randomized A/B. We also rejected ideas and wrote counterexamples when passing tests missed real query behavior.

## 5. Precompute. Validate. Batch. — 2:10–2:35

To protect the deadline, SQL aggregation runs in the background and local scoring stays small. We validate products before batched writes, with one writer and durable request claims. That design served ninety-nine-point-nine-six percent on time across forty-three thousand two hundred practice requests. RawTree snapshots and feedback let us trace a decision from input to outcome.

## 6. Agents accelerated. Evidence decided. — 2:35–3:00

We used Claude and Codex to implement experiments, audit code and find failure cases in isolated branches. People controlled integration, measurements and the single live deployment. The four of us covered modeling, independent challengers, cold-start research and reliability. The lesson was to use agents to move faster, while making every claimed improvement explainable and testable. Build fast. Verify carefully.

## Delivery

Script: 378 words. Total slide budget: 180 seconds.
Start the browser timer with R before speaking. Right arrow/space advances; N toggles notes; F enters fullscreen.
The initial pitch explains HOW and WHY. Team names are credited briefly; no unconfirmed individual roles are assigned.
For questions, HOW_AND_WHY.md provides a code walkthrough. The 2.159% practice aggregate in EVIDENCE.md is not a final result.
Keep the caveat that the +0.17 pp comparison used time blocks, not randomized contemporaneous A/B.
