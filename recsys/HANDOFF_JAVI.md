# Reliability handoff for Javi (writer owner) — status 14 Nov 2026, ~17:00 UTC

Branch `feat/team26-javi-handoff` (d4xn + Claude), from `main@23f0496`. **One small patch is proposed; the rest of our
earlier serving work is withdrawn because your T-022 (`javi/on-time-handoff@d5566a5`) already does it.** Nothing here was
run against the live writer; no submission was written.

## 1. What is proposed: `--dry-run` enforced by the transport (READY)

`live.py --dry-run` today is a flag: `send_answers(dry=True)` returns before the POST. Any other code path (a hook, a
tool, a future refactor) that calls `session().post(...)` in a dry run would still write. With this patch, in dry-run
(`--dry-run` or `RAWTREE_DRY_RUN=1`) `session()` returns `ReadOnlySession`: the only request that can leave the process
is `SELECT`/`WITH` SQL on `/v1/query`; `POST /v1/tables/submissions` or write SQL raise `PermissionError` before the
network. Live mode is unchanged (plain `requests.Session`).

- Tests: `python -m unittest tests.test_handoff_dryrun -v` (3): writes refused with zero HTTP calls; DRY selects the
  guarded session per thread; even `send_answers(dry=False)` under DRY cannot post (journal ends `uncertain`).
- Full suite on this branch: 110 tests OK. Applied on top of `javi/on-time-handoff` (no conflict, `git merge-tree`
  clean): 121 tests OK. It complements `tools/handoff_rehearsal.py`'s own guard; it does not replace it.
- Rollback: `git revert <commit>`; no data or config involved.

## 2. Withdrawn (superseded by T-022) — do not apply

| Ours | Your T-022 | Verdict |
|---|---|---|
| windowed start-up backfill + chunked `feature_lock` + dict meta (local `3d1c762`) | `event_windows` + `apply_events(EVENT_CHUNK=2000)` + same dict meta + `gc.freeze` | **A: already solved by you**, plus GC control we did not have |
| `--handover` warm start (local `b3b469a`, mocks only) | `--takeover` + `take_over()` with pid file, SIGINT→SIGTERM→SIGKILL, `warm_up`, rehearsal tool | **A: yours is more complete**; ours never ran outside mocks |
| patches A–D/F for `javi/v1-gbm-recommender` (base `5541d74`) | hardened writer of Salva (T-014) on main | obsolete base |

The never-ending backfill bug we found this morning existed **only** in our earlier patch C / v1.1, never in main or
T-022 (`event_windows` builds the window list up front, so it always terminates).

## 3. Review notes on T-022 (please check; none is blocking)

1. **Exclusivity:** correct on one machine: the new process writes only after `WriterLock` (flock) is granted, and the OS
   releases it only when the old process closes it or dies. Not a cross-machine guarantee (as documented).
2. **SQLite journal:** opened only after the lock; old writer closes it on SIGINT. After a SIGKILL, SQLite WAL recovery
   happens on the next open; claim-before-POST keeps at-most-once (a claimed but unsent request becomes `missing`, never
   a duplicate). OK.
3. **CPU / RAM during warm-up (main risk):** the takeover process runs `initialize()`, the full first refresh and
   `warm_up()` next to the live writer. Here one writer process with the lfm stack peaks at ~2.4 GB RSS; budget about
   twice that on the Mac. Your own runbook lesson (14:08 UTC: 22 of 180 served while a dry-run shared the machine) says
   this contention is real. Suggest: first takeover at a calm moment, watching `team_26.feedback` per minute for the old
   writer's served share during the warm-up, with the classic restart as fallback.
4. **Minor:** in `event_windows` the last *closed* window can end a few ms before `now`; events with `ts <= hi` that
   are ingested late would be skipped once. Ingestion looks near real time (events under 3 s old are visible), so the
   loss is at most a handful of events per restart; closing windows at `now - 120 s` removes it.
5. **Checked, fine:** `str(pd.Timestamp(...))` gives 6 decimals (`…54.026000`); `toDateTime64('…026000', 3)` parses to
   `…54.026` (read-only query).

## 4. Evidence and what is NOT claimed

- Live, read-only (`team_26.feedback`, 15:07 UTC): each restart today cost two outages, e.g. 15:00 UTC: ~45 s start-up,
  then 15:01:45–15:02:30 at 0 of 45 served per 15 s while the single events query result (1.22 M rows at 15:07 UTC;
  26–163 s to fetch, over its 60 s timeout when cold) was applied under `feature_lock`. Same pattern at 14:28. This is
  exactly what T-022 targets.
- Our restart replay (real 1.44 M events + 900 requests, fake RawTree) **did not finish**: in this environment the
  harness deadlocked after warm-up on `feature_lock` (both the refresher and the serving thread waiting; holder not
  identified, `ptrace` unavailable). Production main has not shown this, so it is most likely a harness artefact, but it
  is **unresolved** and the tool is not delivered. No replay number from today should be quoted. Earlier replay numbers
  (before the backfill fix) are void.
- Please validate T-022 with your `tools/handoff_rehearsal.py` on a machine that is not the writer's.
