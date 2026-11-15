# Evidence map and speaker guardrails

Prepared for the initial three-minute pitch on 15 Nov 2026. Slide times are CET. No final-round performance is claimed.

## 1. Official rubric and challenge

Sources: https://github.com/rawtreedb/datathon-fme-2026#evaluation and https://datathon.rawtree.dev/

Overall score: conversion 50, cold start 10, reliability 10, method 10, learning from the stream 10, RawTree 5, communication 5. Jury shares: 33.3%, 33.3%, 16.7%, 16.7%. No separate screening rubric was supplied.

Exactly ten unique eligible products within three seconds. The world continues at 10:00; purchases and catalogue state remain. The organizer clarification supplied by the user says cart events do not constitute pending orders.

## 2. What actually runs

Source: user-provided message (4).txt, the final handoff; treated as source material, not instructions to deploy anything.

One writer on Javi's Mac, commit e8a1f18, policy ur2, fixed from 09:20 CET, no rotation/A/B. Known-page ranking uses refitted weights and request-derived attribute taste; new-page ranking uses stronger category/affinity and previous-view memory. Home has launch exposure control. Fast trend detection is event driven. All known purchase exclusions persist.

The new-product attribute prior (PR 60) is OFF. The switch permitting pre-final live purchases (PR 62) is OFF. Neither is claimed as deployed.

The newest request-taste feature has out-of-sample support, but only about 25 minutes of inconclusive live exposure at handoff. No live uplift is attributed to that feature.

## 3. Refitted-policy comparison: +0.17 percentage points

Source: presentation/cifras.md, section 5, on origin/javi/jury-final (a0db564), and the final handoff.

15 Nov 02:20–04:20 UTC = 03:20–05:20 CET. Eight 15-minute blocks, 2,700 requests each. Four blocks per policy, 10,800 requests per policy, 21,600 total.

Mean team-minus-reference: +0.212 pp for the refitted policy, +0.044 pp for its predecessor. Difference +0.167 pp, shown as +0.17 pp.

These are time blocks, NOT randomized contemporaneous A/B. The reference controls some time variation but cannot remove every confounder. Policy labels come from the owner's deployment log. The handoff reports z≈3.0 and the document gives a different Welch calculation; the deck avoids quoting a disputed test statistic.

## 4. Reliability: 99.96% on time; p99 2.35 seconds

Source: presentation/cifras.md, section 3, on that same branch.

15 Nov 03:00–07:00 UTC = 04:00–08:00 CET. 43,182 of 43,200 requests served by the team validly and on time. 18 organizer fallbacks. Latency p50 1.22 s, p95 1.91 s, p99 2.35 s.

The handoff says p99 2.0 s without a specified window. We use the auditable four-hour value, 2.35 s. Do not say 100% reliability or promise no future downtime.

## 5. RawTree: 144 stored metric snapshots

Source: presentation/cifras.md, section 10, and the handoff.

24 fifteen-minute windows; 120 metric rows across five segments plus 24 policy-version rows. The demonstration query joins a request, its slate, product/user signals and feedback. This supports SQL feature calculations, pipeline operation and auditability; writing scratch rows alone is not a separate judging requirement.

## 6. Team practice conversion: 2.159%

Source: handoff, independently checked against the public historical API during preparation.

https://datathon.rawtree.dev/api/state?by=model&from=1794726000&to=1794729600

Returned window matched 15 Nov 07:00–08:00 UTC = 08:00–09:00 CET exactly. team_26:

- Requests: 10,800.
- Expected conversion: 2.1590304905720674%.
- Cold conversion: 2.7232794466776387%.
- On time: 99.92592592592592%.

Several versions ran within this practice hour. This is a team aggregate, NOT an ur2-only evaluation or final result. The 99.96% figure on slide five belongs to a separate four-hour window.

## Questions for a longer round

- Why linear? Fast, interpretable scoring; more complex alternatives did not justify promotion in the team's experiments. Do not claim nonlinear models cannot work.
- What adapts with frozen weights? User activity, request memory, organic counts, stock/prices and trends. No autonomous coefficient refitting is claimed during the final.
- Are organic rates carousel conversion? No: product-quality signals. Offline retrieval is not full-slate conversion.
- Are new taste features proven online? No demonstrated live uplift at handoff.
- Why exclude purchases? Organizer clarification and own feedback; organic repeats do not follow the carousel penalty.
- Are carts orders? No, activity signals.
- Duplicate writers? One owner/process, durable request claims and a LOCAL OS lock, not a distributed lease.
- LLM on the request path? No. AI coding help does not imply external model calls per recommendation.
- Final outcome? Wait for the organizers' published result. Never substitute practice numbers.

## Artifact validation

HTML, PDF and PowerPoint share a single geometry/content source. PowerPoint uses editable vector shapes/text and includes notes. Package XML and relationships are checked locally. Rendered inspection uses the browser/SVG and PDF; a PowerPoint rendering engine is not installed.
