# Team 26 — three-minute initial pitch

Open **Team26_3min.pptx** in PowerPoint, or import it into Google Slides. All slide text and graphics are editable. **Team26_3min.pdf** is the projection backup. **pitch.html** is a standalone browser presentation with no network dependencies.

English, six slides, with a 378-word speaker script. The timed plan totals 180 seconds; rehearse aloud, since reading speed and pauses vary. Speaker notes are embedded in PowerPoint and available in SCRIPT.md. The revised story follows the organizers' request for HOW and WHY.

## Published scoring weights

The stream is worth 70 of 100 overall points: conversion 50, cold start 10, reliability 10. The jury is worth the remaining 30.

| Jury criterion | Points out of 100 overall | Share of the 30 jury points | Where this pitch addresses it |
|---|---:|---:|---|
| Method | 10 | 33.3% | Slides 2 and 4: training, model choice, temporal validation and matched windows |
| Learning from the stream | 10 | 33.3% | Slide 3: live evidence versus fixed parameters and source separation |
| RawTree use | 5 | 16.7% | Slide 5: SQL, snapshots, validation and batched submissions |
| Communication | 5 | 16.7% | The entire story; slide 6 makes AI-assisted development explicit |

Source: [official scoring rubric](https://github.com/rawtreedb/datathon-fme-2026#evaluation). No separate published weighting for the three-minute screening round was provided. These are jury weights, not a requirement to divide speaking time into those exact percentages.

## Timing plan

| Slide | Time | Share of the pitch | Main point |
|---|---|---:|---|
| 1. Ten products. Three seconds. One shopper. | 0:00–0:15 | 8.3% | Which evidence should we trust? |
| 2. A deliberate choice | 0:15–0:55 | 22.2% | How we trained and why linear ranking stayed |
| 3. Live intelligence | 0:55–1:30 | 19.4% | How evidence updates while the policy remains stable |
| 4. Measure before believing | 1:30–2:10 | 22.2% | Why temporal validation and matched windows matter |
| 5. Precompute. Validate. Batch. | 2:10–2:35 | 13.9% | How the architecture protects the deadline |
| 6. Agents accelerated. Evidence decided. | 2:35–3:00 | 13.9% | How we used Claude/Codex; brief team credit |

## Browser controls

- Right arrow, Space or Page Down: next slide.
- Left arrow or Page Up: previous slide.
- F: fullscreen.
- N: speaker notes (keep off on the projector).
- R: start/reset the three-minute rehearsal clock.
- Home/End: first/last slide.

Append ?clean=1 to hide controls. Append ?s=3&clean=1 to open slide four. Printing exports all six slides.

## Evidence and wording

Read EVIDENCE.md before presenting. The initial pitch uses the +0.17 pp block comparison and documented reliability. The 2.159% team practice figure is retained in the evidence/README for questions, not used as the closing slide. No final result is claimed.

The new-product attribute prior and purchase-exclusion relaxation were not active in the final handoff; neither is presented as deployed. Carts are activity signals, not pending orders. Training details describe the baseline pipeline; final weights include later refits/overrides. The closing credits all four members and explains the coding agents; detailed roles can be covered in questions.

To rebuild with the existing project environment:

    python presentation/pitch_3min/build_pitch.py

This writes presentation artifacts only. It does not import serving code, read credentials or contact RawTree.
