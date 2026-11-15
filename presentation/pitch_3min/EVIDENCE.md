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

## HOW/WHY revision

The revised initial pitch keeps six slides and a 180-second plan, with 378 spoken words. Slide two now explains the baseline training mechanism and model-selection reason; slide three explains source separation and stable parameters; slide six explains Claude/Codex use and credits the confirmed four-member roster.

Training claims were checked directly in recsys/lfm_build.py: exposed-item rows, click labels, purchase row weight 3, separate known/new regularized logistic fits, log-slot and purchase calibration. The final JSON includes later refits/overrides; it is not claimed to be the untouched output of this default fit. R-24/E-260 supports the held-out model-choice account. See ../HOW_AND_WHY.md for the longer code walkthrough.

The 2.159% practice aggregate is supporting evidence in this file and the root README, no longer the closing slide. Team member names were supplied by the user; no unconfirmed person-specific workstream or agent-version assignment is presented.

## Spanish presentation

The current default HTML/slides and the exports with suffix ES are in Spanish. The shortened script has 300 words and retains the same six-slide, 180-second plan with room for pauses. Statistics, comparison caveats and confirmed team credits are unchanged. GUION_ES.md and SCRIPT.md contain the Spanish notes. Earlier English exports remain available under their original filenames.

## HTML-first diagram and RawTree revision

The current HTML and notes now have 316 spoken words with a 180-second plan. Slide one replaces the decorative number/tiles with the actual request -> local rank/validation -> submission flow, under a single three-second deadline. No stage latency is invented.

Slide five names RawTree's creator, Tinybird, and shows the actual uses: reading shared streams; SQL event aggregation feeding quality/trends; batched team submissions and private feedback; metrics in scratch. Ranking and indicator calculations remain local code, not falsely described as database-hosted ML.

Primary source for corporate attribution: https://rawtree.com/ (footer: "A Tinybird product"). Usage evidence: recsys/live.py, recsys/trends.py, final handoff and the 144-snapshot record in the earlier evidence map.

This revision updates HTML/SVG/notes only at the user's request. Earlier PDF/PowerPoint files are not claimed to contain these last changes.

## Observations, rejections and version data

Current slide four is a visual progression: team start 0.91% (reference 2.03%, public snapshot 14 Nov 13:50 UTC, N=10,785, source presentation/guion.md), u1 1.98825% (reference 1.94425%), u3k 2.117% (reference 1.9055%). Bars start at zero; orange markers give the corresponding reference. The first point mixes versions and a downtime interval and is labeled team average, not an isolated model result. Later points are block averages, not consecutive randomized arms. This visual is practice evidence, not a final result or a causal estimate of each change.

Current slide two returns to attribute affinity, checked in own live feedback (I-092/E-093): known shoppers, products without prior relationship and outside recent_views, 0.6 purchases per 10,000 exposures at affinity <0.10 versus 89.7 at affinity 0.20–0.25. Feedback covers 21,691 requests, 14 Nov 11:09–13:05 UTC; only 36 purchases in the main segment. This is an observational exposed-product group comparison, not before/after or a causal policy conversion uplift. Current script: 335 words.

Latest slide two supersedes the affinity example with the documented u1/u3k feedback-refit comparison: 1.988% -> 2.117%, shown as 1.99% -> 2.12%, N=10,800 per policy. It is the same temporal comparison detailed on slide four, not separate evidence and not a measured conversion effect of affinity alone. No metrics were fabricated.

Current slide two uses one complete I-092/E-092 example: observe recurring preference for description attributes, add attribute affinity to ranking, check historical hit@1 0.472 -> 0.519 over 4,697 purchased sessions. The earlier purchase-exclusion card is now only supporting data in the appendix. This is ranking accuracy conditioned on purchase, not live conversion. Current script: 317 words.

Latest visual revision: slide footers, page numbers and tiny source references removed; full provenance remains here and in the D panel. Explanations use plain language and connect observations to decisions. User-confirmed tool split: Claude for coding, Codex for research. Current script: 307 words, six slides, 180-second plan. All six browser renders reviewed.

Current pitch: six main slides, 308 words and a 180-second plan. Slide two adds E-081's 0 purchases/1,118 already-bought exposures and E-092's historical hit@1 0.472 -> 0.519 over 4,697 purchased sessions. The labels distinguish live feedback from offline ranking accuracy.

Slide three shows why replication changed the graph decision: +0.20 pp in E-271 followed by -0.41 pp in E-272 for known shoppers on pages. These are separate windows and named arms; the appendix lists all four cohorts and sample sizes. It does not claim all graph models universally fail.

Slide four replaces decorative block tiles with the actual u1/u3k group table: observed conversion, matched reference averages and their difference, each based on four equally sized blocks. Values are rounded from the documented block figures. Temporal confounding remains; it is not a randomized A/B.

datos_versiones.html and the embedded D/"Datos por versión" panel include the eight blocks, r3/graph cohort results from E-271/E-272, generic-home variants and the offline GBM comparison. Each section states its metric, population, window, available N and source. No ur2-only conversion is invented, and the 2.159% mixed practice-hour aggregate is not assigned to ur2.

The root data sources are experiments.md (E-081/E-092/E-260/E-271/E-272), insights.md (R-24/R-26) and presentation/cifras.md on javi/jury-final. These are the available documented comparisons, not an exhaustive reconstruction of every policy ever served.
