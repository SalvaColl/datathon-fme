# Operations runbook — RawTree realtime recommender

**Status:** official setup commands VERIFIED in public repo; **team deployment NOT YET TESTED**. One process must run continuously from practice through Sunday final. Handle secrets privately; never commit `.env`.

## Source and credentials

Official repo: https://github.com/rawtreedb/datathon-fme-2026

```bash
# Only if team has NOT yet cloned the official starter:
git clone https://github.com/rawtreedb/datathon-fme-2026.git
cd datathon-fme-2026
cp .env.example .env
# Edit .env privately with TEAM_ID=team_NN and RAWTREE_API_KEY=<secret>
# Use the existing virtualenv; if needed only:
pip install -r starter/requirements.txt
python starter/recommender.py
```

Official alternative without changing global Python: `uv run --with requests python starter/recommender.py` (verify your env already has needed dependencies). **Do not run a second live recommender if one is already serving; duplicates are not a legitimate policy comparison.** `TEAM_ID` and `RAWTREE_API_KEY` are supplied at RawTree stand.

RawTree endpoint: `https://api.rawtree.com`, bearer authorization. For terminal queries the official CLI offers:

```bash
rtree query --api-key "$RAWTREE_API_KEY" --database "$TEAM_ID" "SELECT count() FROM shop.requests"
```

You can query with Python HTTP API `POST /v1/query` `{"sql":"..."}` and submit batch JSON to `POST /v1/tables/submissions?database=$TEAM_ID`. Dynamic typed columns often need casts like `product_id::String`, `ts::DateTime64(3)` in SQL joins/aggregations. Reuse official `starter/queries.sql` when possible.

## Live polling and submission invariants

- `shop.requests`: ~**3/sec**. The starter queries 50 newest records and polls every **0.3 seconds**. A stall beyond ~16.7s at advertised rate can overrun the 50-record window; instrument gaps and consider durable request cursor / overlapping backfill.
- One record per request in `<TEAM_ID>.submissions`: `request_id`, ordered `items` with **exactly 10 unique and currently active IDs**, `model_version`.
- Endpoint insert must reach RawTree **within 3 sec of the request's UTC `ts`**. Batch ~0.5 sec; don't add ML model fitting or large SQL joins to request path. Normal starter ~1sec, p95 ~1.5sec total from `ts`.
- Model version ledger maps `request_id` to policy version. Do not rely on `feedback` to contain model_version. Retried POSTs require careful duplicate prevention.
- `shop.catalog_updates`: full latest product record, including new product, price change, stockout/back-in-stock. Rebuild current active/price cache from base catalog + latest updates; refresh frequently, validate final slate again just before posting.
- Response must be ordered. User sees first slots disproportionately often. Avoid known-inactive products, duplication, nonexistent IDs, or fewer/more than ten.

## Quick health checks

Query your team's `feedback` (ignore `request_id='__init__'`):

```sql
SELECT served_by::String AS served_by,
       fallback_reason::String AS reason,
       count() AS requests,
       quantile(0.95)(latency_ms::Float64) AS p95_ms,
       100.0 * countIf(purchased != '') / count() AS realized_conversion_pct
FROM team_NN.feedback
WHERE request_id != '__init__'
GROUP BY served_by, reason
ORDER BY requests DESC;
```

Replace `team_NN` with actual team DB; if you are querying using `$TEAM_ID`, substitute it safely in code. Example starter SQL also includes hourly conversion/revenue and last-30-minute fallback/latency. **Realized** conversion is *not* the official hidden expected-conversion score.

Health expectations: `served_by='team'` nearly always, `fallback_reason` usually blank, no `missing`/`late`/`invalid`, p95 comfortably under 3000ms. Monitor p99 and maximum, not just model inference. During final leaderboard only **team green/red health light** visible: green means **>90% valid and on-time over last 5 min**, it is not a quality score.

## Preflight checklist

- [ ] Confirm Sunday **Nov 15 10:00 CET** start, 12:00 end; monitor local time versus UTC event timestamps.
- [ ] Team id and API key configured privately in `.env` or environment. `.env` is `.gitignore`d; verify before commit.
- [ ] Existing virtualenv selected; starter script reads and writes RawTree successfully.
- [ ] Only **one** live writer; no accidental duplicate team submissions from tests/staging.
- [ ] All replies exactly ten unique active IDs; test missing user/session, new buyer, new product, price/stock changes and unexpected nulls.
- [ ] Last-known good model/champion and baseline fallback available; tested rollback command.
- [ ] Real `team_NN.feedback` confirms valid servability, latency, and not fallback.
- [ ] Request ledger/dedup survives process restart; no missed/newest-window races.
- [ ] Model artifacts cached, no full historic SQL in inference path.
- [ ] Machine/network stable; disable laptop sleep/hibernation, check AC power and Wi-Fi; designate monitoring/backup owner.
- [ ] Evidence/plots for jury: history feature SQL, time-split validation and controlled learning demonstration.

## Incident response

| Symptom | Action |
|---|---|
| `fallback_reason='late'` | Measure source timestamp to write acknowledgement; disable costly on-request inference, reduce batch delay, check network/query time; restore known fast champion |
| `invalid` | Check 10 distinct active real products, recent stockouts/new catalogue, serialized JSON/schema, duplicates; revert safely |
| `missing` | Inspect live process liveness, request backlog, polling cursor/window, API authorization/network; restart single supervised writer |
| RawTree SQL `Illegal type Dynamic` | Add explicit casts in joins/aggregate expressions (`::String`, `::DateTime64(3)`) |
| `Unknown expression identifier` on empty live tables | May occur before stream has rows; retry; shouldn't persist once live events arrive |
| Stock cache stale | Merge latest `catalog_updates`, refresh before slate validation; use known valid eligible candidates |
| Model regression / errors | Revert to pinned champion, retain one writer, log incident and measured effect in `experiments.md` |

## Timeline and freeze

- **Practice:** Sat Nov 14 10:00–Sun Nov 15 10:00 CET; leaderboard refreshed each **10min** with **last-hour** estimate. Historical offline benchmark is primary development signal.
- **Final:** Sun Nov 15 10:00–12:00 CET; new data distribution, leaderboard blacked out, monitor `feedback` and health only. Changes allowed but high-risk changes strongly discouraged. Stay online continuously.
- **12:00:** organizers stop stream and publish final ranking; jury presentation Sunday afternoon. Preserve readable repo and evidence; no submission file required.

## Team-specific operations to fill in

| Item | Command / owner / artifact |
|---|---|
| Exact Python interpreter/venv activation | TBD |
| Single-writer start/restart supervisor | TBD |
| Run unit/integration tests | TBD |
| Model/policy champion version and pinned commit | TBD |
| RawTree feature refresh process | TBD |
| Deployment host / backup machine / network monitoring | TBD |
| Rollback command and responsible person | TBD |
| Jury demo command and figures | TBD |

Official sources: https://datathon.rawtree.dev/ ; https://github.com/rawtreedb/datathon-fme-2026

## Offline league v2

See `tools/LEAGUE.md` for train/validation/test preparation, policy registration and freeze/final-test commands. Use the existing team virtualenv; no installations required. This offline workflow does not launch, stop or modify the live champion. The cached historical test must stay unscored until policy selection is frozen. Rollback requires no live action: retain the current champion and discard/revert offline-only changes if needed.

## v1-gbm reliability handoff — T-014 (2026-11-14)

Actual owner: **Javi on his laptop** (user report). Standalone tested code fix: `7176c03` on `salva/serving-reliability`, based on Javi's `5541d74`. It has not been deployed. Javi can fetch and cherry-pick that commit onto his existing branch without merging the imported snapshot or unrelated docs. Run tests with his existing environment and history artifact, then coordinate a single-writer handoff. See `recsys/README.md` for commands, lock/journal paths, telemetry, limitations and rollback.

Read-only diagnosis: `python tools/reliability_audit.py --minutes 30`; source/reason counts and p95/p99 by five-minute UTC bucket. An hourly 76% score can include old disruptions: measured recent 30-minute acceptance was 99.30%. Do not start another process to chase the rolling score. Current stock/transport risks still warrant the staged patch, but no post-fix E2E improvement has yet been measured. Do not delete the persistent attempts journal or blindly resend uncertain POSTs. Local lock cannot protect against another laptop or unpatched baseline.

## Variante qrank en el writer — T-015 (2026-11-14)

Rama `javi/qrank-serving` = writer robusto de Salva (`7176c03`) + ranker `recsys/qrank.py`. No está desplegado. Sigue habiendo **un único writer**.

- Arranque normal: `python recsys/live.py` sirve v1 como hasta ahora. Probar antes con `--dry-run` (no escribe).
- Cambiar de variante sin reiniciar: escribir `recsys/data/policy.json` con `{"variant": "v1"}`, `{"variant": "qrank"}` o `{"variant": "ab_qrank"}`. El proceso lo relee cada ~20 s y lo anota en el log (`{"event": "policy", ...}`).
- Prueba recomendada: `ab_qrank` durante 30–60 min y `python recsys/compare_versions.py 60` para comparar `v1-gbm-cand-r1` con `v2-qrank-r1` (compras reales; con ~5.000 peticiones por brazo y hora se distingue 1,3% de 2,1%). Para el leaderboard, un bloque de 10 min con `qrank` alineado con `updated_at`.
- Rollback: `{"variant": "v1"}` en `policy.json`, o borrar el archivo y reiniciar.
- Reconstruir el artefacto: `cd recsys && python qrank_build.py --pull` (scikit-learn 1.9.1).
