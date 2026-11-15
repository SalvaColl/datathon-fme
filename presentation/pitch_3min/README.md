# Team 26 — three-minute initial pitch

Open **Team26_3min.pptx** in PowerPoint, or import it into Google Slides. All slide text and graphics are editable. **Team26_3min.pdf** is the projection backup. **pitch.html** is a standalone browser presentation with no network dependencies.

English, six slides, with a 369-word speaker script. The timed plan totals 180 seconds; rehearse aloud, since reading speed and pauses vary. Speaker notes are embedded in PowerPoint and available in SCRIPT.md.

## Published scoring weights

The stream is worth 70 of 100 overall points: conversion 50, cold start 10, reliability 10. The jury is worth the remaining 30.

| Jury criterion | Points out of 100 overall | Share of the 30 jury points | Where this pitch addresses it |
|---|---:|---:|---|
| Method | 10 | 33.3% | Slides 2 and 4: model, temporal validation, matched windows, limitations |
| Learning from the stream | 10 | 33.3% | Slides 2 and 3: shopper memory, live quality, events and trends |
| RawTree use | 5 | 16.7% | Slide 5: SQL, snapshots, feedback and batched submissions |
| Communication | 5 | 16.7% | The entire deck: a clear product story, legible visuals and a concise result |

Source: [official scoring rubric](https://github.com/rawtreedb/datathon-fme-2026#evaluation). No separate published weighting for the three-minute screening round was provided. These are jury weights, not a requirement to divide speaking time into those exact percentages.

## Timing plan

| Slide | Time | Share of the pitch | Main point |
|---|---|---:|---|
| 1. The right ten | 0:00–0:20 | 11.1% | The problem and our promise |
| 2. Different evidence | 0:20–0:55 | 19.4% | Personalization, known and new shoppers |
| 3. Live intelligence | 0:55–1:35 | 22.2% | Frozen weights, continuously updated evidence |
| 4. Measure before believing | 1:35–2:15 | 22.2% | Evidence, comparison design and limits |
| 5. A ranking must arrive | 2:15–2:45 | 16.7% | RawTree, reliability and auditable operation |
| 6. Personalize. Adapt. Deliver. | 2:45–3:00 | 8.3% | One practice result and a memorable close |

## Browser controls

- Right arrow, Space or Page Down: next slide.
- Left arrow or Page Up: previous slide.
- F: fullscreen.
- N: speaker notes (keep off on the projector).
- R: start/reset the three-minute rehearsal clock.
- Home/End: first/last slide.

Append ?clean=1 to hide controls. Append ?s=3&clean=1 to open slide four. Printing exports all six slides.

## Evidence and wording

Read EVIDENCE.md before presenting. The last-hour figure is a TEAM practice result across several versions, not a result for the final policy alone. The final result is explicitly unknown.

The new-product attribute prior and purchase-exclusion relaxation were not active in the final handoff; neither is presented as deployed. Carts are activity signals, not pending orders. The 99.96% reliability and 2.159% conversion figures come from different, explicitly labeled practice windows.

To rebuild with the existing project environment:

    python presentation/pitch_3min/build_pitch.py

This writes presentation artifacts only. It does not import serving code, read credentials or contact RawTree.
