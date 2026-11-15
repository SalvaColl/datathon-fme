# Equipo 26 — presentación inicial de tres minutos

**Versión actual: pitch.html**, en español y sin dependencias de red. El hilo es observación → decisión → prueba → resultado por versión. Conserva el flujo del plazo de tres segundos y el uso de RawTree/Tinybird. **D** abre las tablas de apoyo, que también están en **datos_versiones.html**. El guion actualizado está en **GUION_ES.md**. Los PDF/PPTX conservan una revisión anterior.

Seis diapositivas y un guion de **311 palabras**. Sin pies ni numeración: cada ejemplo conecta observación y decisión. Claude se acredita para programación y Codex para investigación. El plan reserva 180 segundos, con margen para pausas; ensaya en voz alta. Las notas actuales están en el HTML y en GUION_ES.md/SCRIPT.md. El foco es lo que pide el jurado: CÓMO y POR QUÉ.

## Published scoring weights

The stream is worth 70 of 100 overall points: conversion 50, cold start 10, reliability 10. The jury is worth the remaining 30.

| Jury criterion | Points out of 100 overall | Share of the 30 jury points | Where this pitch addresses it |
|---|---:|---:|---|
| Method | 10 | 33.3% | Slides 3 and 4: training, rejected models, replication and matched-window comparisons |
| Learning from the stream | 10 | 33.3% | Slides 2 and 5: purchase feedback changes the policy; event aggregates supply fresh signals |
| RawTree use | 5 | 16.7% | Slide 5: SQL, snapshots, validation and batched submissions |
| Communication | 5 | 16.7% | The entire story; slide 6 makes AI-assisted development explicit |

Source: [official scoring rubric](https://github.com/rawtreedb/datathon-fme-2026#evaluation). No separate published weighting for the three-minute screening round was provided. These are jury weights, not a requirement to divide speaking time into those exact percentages.

## Timing plan

| Slide | Time | Share of the pitch | Main point |
|---|---|---:|---|
| 1. Diez productos. Tres segundos. | 0:00–0:15 | 8,3% | Qué señales merecían confianza |
| 2. Observar. Cambiar. Comprobar. | 0:15–0:50 | 19,4% | Compras previas y afinidad: datos que motivaron señales |
| 3. Una ronda no bastaba | 0:50–1:25 | 19,4% | Grafo, complejidad y señales que no justificaron promoción |
| 4. Cada versión, con su contexto | 1:25–2:00 | 19,4% | Tabla u1/u3k con conversión, referencia y N |
| 5. RawTree: del dato a la acción | 2:00–2:35 | 19,4% | SQL, submissions/feedback, métricas y trazabilidad |
| 6. La IA acelera. La evidencia decide. | 2:35–3:00 | 13,9% | Claude/Codex, control humano y crédito breve |

## Browser controls

- Right arrow, Space or Page Down: next slide.
- Left arrow or Page Up: previous slide.
- F: fullscreen.
- N: speaker notes (keep off on the projector).
No timer or bottom toolbar is displayed.
- D: abrir/cerrar datos por versión; Esc vuelve al pitch.
- Home/End: first/last slide.

Append ?clean=1 to hide controls. Append ?s=3&clean=1 to open slide four. Printing exports all six slides.

Con ?datos=1 se abre directamente el panel de tablas. Está integrado en el HTML: no necesita red ni archivos externos para consultarlo.

## Evidence and wording

Read EVIDENCE.md before presenting. The initial pitch uses the +0.17 pp block comparison and documented reliability. The 2.159% team practice figure is retained in the evidence/README for questions, not used as the closing slide. No final result is claimed.

The new-product attribute prior and purchase-exclusion relaxation were not active in the final handoff; neither is presented as deployed. Carts are activity signals, not pending orders. Training details describe the baseline pipeline; final weights include later refits/overrides. The closing credits all four members and explains the coding agents; detailed roles can be covered in questions.

To rebuild with the existing project environment:

    python presentation/pitch_3min/build_pitch.py

This writes presentation artifacts only. It does not import serving code, read credentials or contact RawTree.

El comando anterior solo actualiza HTML, SVG y notas. Para regenerar también el PowerPoint de forma explícita:

    python presentation/pitch_3min/build_pitch.py --pptx

Para regenerar también PDF y vista previa, con Chrome ya instalado:

    python presentation/pitch_3min/render_pitch.py
