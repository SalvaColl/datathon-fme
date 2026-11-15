# Team and AI-assisted development

Confirmed roster supplied by the team:

- Salvador Coll
- Héctor Verdeal
- Daniel Nieto
- Javier Andrés García

## Project workstreams

The repository records the following workstreams. The initial pitch credits the whole team rather than assigning exclusive individual roles from Git authorship; many commits were agent-authored.

| Workstream | Examples | Supporting evidence |
|---|---|---|
| Modeling and integration | Rankers, features, experiment integration and policy selection | recsys; experiments/decisions; Javi is the documented serving owner |
| Independent challengers | Temporal content/logistic policy and alternative recommenders | T-021; 04321f3 and 69f9cec |
| Cold-start and synthetic signals | New-product quality and additional-signal research | T-CS01/T-SA01; cold_lq and synthetic-alpha |
| Evaluation and reliability | Temporal league, audits, failure cases and latency | codex/unified-bot-audit, reliability branches and tests |
| Communication | Evidence map, three-minute pitch and judge-facing README | presentation/ and repository README |

The pitch keeps the team credit short; this workstream map points reviewers to the code.

## Coding agents

Confirmed at team level: Claude and Codex.

- Claude: substantial implementation and experiment work in modeling/integration branches.
- Codex: evaluation, reliability/leakage audits, research, regressions and presentation/documentation.
- No external LLM inference is required on the recommendation path.

Humans chose objectives and controlled integration, experiments and final deployment. Agents proposed implementations/tests; measured behavior and review determined what could be trusted.
