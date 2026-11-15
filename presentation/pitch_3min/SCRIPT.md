# Team 26 — three-minute pitch

English. Six slides. Timings are rehearsal targets, not a promise of reading speed.
Aim for roughly 130–140 words per minute and rehearse with pauses. Slide sources are in the PowerPoint notes and EVIDENCE.md.

## 1. Ten products. Three seconds. One shopper. — 0:00–0:20

Every shopper gives us one decision: which ten products should we show, right now? We have three seconds, and the store keeps changing. We are Team 26. We built a recommender that remembers the shopper, adapts to the stream, and arrives before the deadline.

## 2. One policy. Different evidence. — 0:20–0:55

Our final system uses one lightweight linear ranker, with different weights for the shopper and page context. For returning shoppers, it combines historical preferences with current activity and tastes inferred from previous requests. For new shoppers, it starts with the current session and remembers earlier visits. Product quality comes from organic purchases and views. We train ranking weights using our own recommendation feedback, and always exclude known purchases.

## 3. Frozen weights. Live intelligence. — 0:55–1:35

Freezing the model does not freeze the store. We keep updating shopper activity, organic product quality, stock and prices. Our trend detector looks for changes in the event stream, rather than assuming yesterday's timetable will repeat. New launches can enter the ranking, with controlled exposure on home pages. At the final-round boundary, the world continues: Saturday's products and previous purchases still count. Cart events are activity signals, not pending orders.

## 4. Measure before believing. — 1:35–2:15

Our most useful improvement was also methodological. Historical impressions are biased, so offline evaluation uses temporal splits and only screens ideas. Live comparisons use the same time window as the organizers' reference, because traffic and trends change. Across eight practice blocks, refitted weights showed a zero-point-seventeen percentage-point improvement over the previous policy, with ten thousand eight hundred requests per policy. This was a time-block comparison, not a randomized trial. The newest preference feature has offline support, but no demonstrated live uplift yet.

## 5. A great ranking must arrive. — 2:15–2:45

RawTree is our operating backbone. SQL connects requests, store events, catalogue updates and private feedback. Background snapshots feed the ranker; validation checks the ten products before batched submission. In a documented four-hour practice window, we served ninety-nine-point-nine-six percent of forty-three thousand two hundred requests on time. The ninety-ninth latency percentile was two-point-three-five seconds, below the three-second limit. One writer prevents duplicate submissions, and stored snapshots make our decisions auditable.

## 6. Personalize. Adapt. Deliver. — 2:45–3:00

In our last measured practice hour, expected conversion reached two-point-one-five-nine percent across ten thousand eight hundred requests. The final result is still unknown. Our promise is simple: the right products, for this shopper, before the deadline.

## Delivery

Script: 369 words. Total slide budget: 180 seconds.
Start the browser timer with R before speaking. Right arrow/space advances; N toggles notes; F enters fullscreen.
The practice hour includes several versions. Never describe its conversion as an ur2-only or final result.
For the initial pitch, skip the statistics detail unless asked. Keep the caveat that the comparison used time blocks.
