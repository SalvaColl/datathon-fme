# GBM serving and reliability fixes

The policy and trained model originate from Javi's `javi/v1-gbm-recommender` at `5541d74`. The user reports Javi is the sole active host, running `v1-gbm-cand` on his laptop. This branch contains an offline-tested transport/feature-processing update, `v1-gbm-cand-r1`; it has NOT been deployed by Codex. Model artifacts and ranking features are unchanged. Use the existing environment; install nothing for this patch.

Javi can apply only the code fix to his existing branch (commit unfinished work first):

```bash
git fetch origin
git cherry-pick 7176c03
python -m unittest discover -s tests -v
```

Run from repository root. His existing ignored `recsys/data/user_item_all.parquet` is required to initialize the actual recommender. Catalogue/model paths now resolve relative to the code, so both `python recsys/live.py --dry-run` and `cd recsys; python live.py --dry-run` work. `--dry-run` performs queries/inference but never claims journal entries or writes submissions. No full dry-run was performed here because the user-history artifact is only on Javi's machine. Plan any CPU-heavy rehearsal so it does not starve the active writer.

Only Javi, as live process owner, should do the eventual controlled stop/start. `python recsys/live.py` starts a real writer; do not run it alongside the existing one or on a second laptop. Do not use `--ab` for this transport change: retain 100% of the existing ranking policy unless intentionally running a separate experiment.

Changes:

- Urgent requests (age >=1.8s) send guarded answers before scoring younger requests. Model batches are at most four requests, oldest first. Requests older than 2.5s are counted as expired and not knowingly sent stale; rechecked immediately before POST. Poll interval targets 100ms rather than adding 250ms after every slow loop.
- Request polling has a 0.5s connect / 2s read timeout, replacing 20s. Eight read-only polls on this machine took 0.814–2.275s including fresh connection setup; median 1.107s, so a 1s read setting was rejected. Requests socket timeouts are not hard end-to-end deadlines.
- Separate thread-local persistent HTTP sessions for polling/submission, event refresh and stock refresh. Full catalogue/pools refresh remains 20s; an independent stock query runs every second after its previous request completes. Known stock-outs are rechecked against the latest local cache just before submission. Future stock changes/network lag can still invalidate an answer.
- Feature engineering uses a pinned catalogue snapshot and one viewed-subcategory lookup per unique session view sequence. Live count updates and feature reads synchronize. The first catalogue/pool snapshot becomes available before the initial live-event backfill completes.
- Durable SQLite claims precede POST. Lost acknowledgements are logged as uncertain and are not automatically retried. A crash between claim and POST can lose an answer: this is the explicit tradeoff for avoiding duplicates without documented server idempotency. Journal persists outside checkout in the OS temporary directory, `rawtree-<TEAM_ID>/attempts.sqlite3`; preserve it across routine restarts and do not manually replay uncertain rows. OS temp cleanup can remove it; startup also reconciles newest remote submission IDs.
- A local process lock at `rawtree-<TEAM_ID>/writer.lock` rejects a second patched writer on that machine. It cannot stop an unpatched script or another laptop. Team coordination remains mandatory.
- Unknown recent-view products do not abort the batch; invalid/duplicate/unknown/inactive items are repaired from eligible best sellers. Fewer than ten known eligible items causes a refused submission, rather than sending an invalid slate.

Logs: `push_ack` has POST duration and oldest request age; `push_uncertain` indicates acknowledgement ambiguity; `loop` reports total loop duration, expired requests and stock age. Watch for growing stock age and expired requests. Read-only server diagnostics: `python tools/reliability_audit.py --minutes 30` and `python tools/feedback_monitor.py --window 30`. Server feedback is the evidence for on-time acceptance; local POST acknowledgements alone do not prove it.

Rollback: keep the original `5541d74` checkout/model available to Javi. Restore that version only during a single-writer handoff; never run it in parallel. Preserve the journal and logs. No deployment or promotion occurred here. The shared starter was not modified, no new submitter was launched, and the league final test remains unscored.
