"""Cross-machine failover helpers (T-063). No model or network imports: every side effect is injected.

serving.WriterLock is a flock in the local temp directory, so it excludes a second writer on ONE machine only.
This module adds what can be added without touching a writer that is already running:

  Gate (live.py --standby)
      A process that loads, keeps its state fresh and scores real requests WITHOUT sending, and starts writing only
      when a person drops a promote file with the right token. Before it writes it checks, in RawTree, that nobody
      answered the requests of the last seconds (the other writer really is dead); after it writes it keeps checking
      for submissions it did not send and goes back to standby if another writer shows up. That last check works
      against an old writer that knows nothing about this module.

  Lease (WRITER_LEASE=1, off by default)
      A fencing token in <team>.scratch. A writer acquires a token larger than every existing one and re-reads the
      maximum every few seconds: a larger token means someone took over, so it stops. A writer that could not
      confirm its token recently (laptop sleep, network cut) must re-read it BEFORE writing again. Both writers have
      to run with the lease for it to fence anything.

Promotion is never automatic: without a fresh promote file nothing here ever opens the gate.
"""
import json
import os
import threading
import time
from pathlib import Path

STANDBY, WRITING, STOPPED = 'standby', 'writing', 'stopped'
LEASE_KIND = 'writer_lease'


def read_promote(path, token, armed_at, now, ttl=120.0):
    """(ok, force, why). The promote file counts only if it was written AFTER this process armed itself (start or last
    step-down), is younger than ttl seconds and its first word is the expected token. Second word FORCE skips the
    'nobody else is writing' check. A stale or foreign file never promotes."""
    if not token:
        return False, False, 'no_token_configured'
    try:
        p = Path(path)
        mtime, words = p.stat().st_mtime, p.read_text(encoding='utf-8', errors='replace').split()
    except OSError:
        return False, False, 'no_file'
    if mtime <= armed_at:
        return False, False, 'file_older_than_standby'
    if now - mtime > ttl:
        return False, False, 'file_expired'
    if not words or words[0] != token:
        return False, False, 'wrong_token'
    return True, len(words) > 1 and words[1] == 'FORCE', 'ok'


def active_sql(team, lo=12, hi=4):
    """Submissions for the requests issued between lo and hi seconds ago (hi leaves room for a slow answer)."""
    return (f"SELECT s.request_id::String request_id, count() c FROM {team}.submissions s WHERE s.request_id::String IN "
            f"(SELECT request_id::String FROM shop.requests WHERE ts::DateTime64(3) > now64(3) - INTERVAL {int(lo)} SECOND "
            f"AND ts::DateTime64(3) <= now64(3) - INTERVAL {int(hi)} SECOND) GROUP BY request_id")


def foreign_count(rows, mine):
    """Submission rows that this process cannot have written: every row for an id it never posted, and every row
    beyond the first for an id it did post."""
    return sum(int(r['c']) - (1 if r['request_id'] in mine else 0) for r in rows)


class Lease:
    """Fencing token in <team>.scratch: rows {kind: 'writer_lease', token: <int>, holder: <text>}.

    query(sql) -> list of dicts; insert(row) writes one row to scratch. Tokens come from the SERVER clock
    (milliseconds), bumped above the current maximum, so no machine clock is trusted.
    """
    def __init__(self, team, query, insert, holder, max_stale=20.0, wall=time.time, log=print):
        self.team, self.query, self.insert, self.holder = team, query, insert, holder
        self.max_stale, self.wall, self.log = max_stale, wall, log
        self.token, self.last_ok, self.superseded_by = None, None, None

    def _max(self):
        try:
            rows = self.query(f"SELECT max(token::Int64) m, toUnixTimestamp64Milli(now64(3)) now FROM {self.team}.scratch "
                              f"WHERE kind::String = '{LEASE_KIND}'")
        except Exception:
            # An empty scratch table has no columns yet: the first acquisition has nothing to compare with.
            rows = self.query("SELECT 0 m, toUnixTimestamp64Milli(now64(3)) now")
        return int(rows[0]['m'] or 0), int(rows[0]['now'])

    def acquire(self):
        """Take a token larger than every existing one. Raises if RawTree cannot be read or written."""
        highest, now = self._max()
        self.token = max(now, highest + 1)
        self.insert(dict(kind=LEASE_KIND, token=self.token, holder=self.holder))
        self.superseded_by, self.last_ok = None, self.wall()
        self.log(json.dumps(dict(event='lease_acquired', token=self.token, previous=highest)), flush=True)
        return self.token

    def check(self):
        """Re-read the maximum token. True = still ours. A failed read changes nothing (valid() then ages out)."""
        if self.token is None:
            return False
        try:
            rows = self.query(f"SELECT max(token::Int64) m FROM {self.team}.scratch WHERE kind::String = '{LEASE_KIND}'")
            highest = int(rows[0]['m'] or 0)
        except Exception as exc:
            self.log(json.dumps(dict(event='lease_check_failed', error=type(exc).__name__)), flush=True)
            return False
        if highest > self.token:
            if self.superseded_by is None:
                self.log(json.dumps(dict(event='lease_superseded', token=self.token, newer=highest)), flush=True)
            self.superseded_by = highest
            return False
        self.last_ok = self.wall()
        return True

    def superseded(self):
        return self.superseded_by is not None

    def valid(self):
        """Not superseded AND confirmed within max_stale seconds of WALL time (a sleeping laptop ages out)."""
        return (self.token is not None and self.superseded_by is None and self.last_ok is not None
                and 0 <= self.wall() - self.last_ok <= self.max_stale)


class Gate:
    """Decides, once per serving loop, whether this process may write. tick() -> 'write' | 'promoted' | 'idle' | 'hold' | 'stop'.

    standby=True : starts closed; opens on a valid promote file (see read_promote) when nobody else is writing and the
                   local lock is free; closes again (back to standby, lock released) if a foreign writer or a newer
                   lease token appears. A new promote file is needed to open it again.
    standby=False: a plain writer running with a lease; starts open (start() acquires the token) and returns 'stop'
                   for good once the token is superseded.
    """
    def __init__(self, team, query, lock_factory, standby, promote_path=None, token=None, lease=None,
                 promote_ttl=120.0, check_every=3.0, foreign_limit=5, yield_to_foreign=True, grace=6.0,
                 wall=time.time, log=print):
        self.team, self.query, self.lock_factory = team, query, lock_factory
        self.standby, self.promote_path, self.token, self.lease = standby, promote_path, token, lease
        self.promote_ttl, self.check_every, self.foreign_limit = promote_ttl, check_every, foreign_limit
        self.yield_to_foreign, self.grace, self.wall, self.log = yield_to_foreign and standby, grace, wall, log
        self.state = STANDBY if standby else STOPPED
        self.lock, self.armed_at, self.promoted_at = None, wall(), None
        self.sent, self.sent_lock = {}, threading.Lock()
        self.last_poll, self.last_check, self.refused, self.reason, self.forced = 0.0, 0.0, None, None, False

    # ---- transitions ----
    def start(self, lock=None):
        """Plain writer with a lease: the caller already holds the local lock. Raises if the token cannot be taken."""
        if self.lease is not None:
            self.lease.acquire()
        self.lock, self.state, self.promoted_at = lock, WRITING, self.wall()

    def _open(self, force):
        now = self.wall()
        if not force:
            try:
                rows = self.query(active_sql(self.team))
            except Exception as exc:
                return self._refuse(f'cannot_check_other_writer:{type(exc).__name__}')
            if rows:
                return self._refuse(f'another_writer_is_answering:{len(rows)}_requests_in_8s')
        try:
            lock = self.lock_factory()
        except RuntimeError:
            return self._refuse('local_lock_held')
        try:
            if self.lease is not None:
                self.lease.acquire()
        except Exception as exc:
            lock.close()
            return self._refuse(f'lease_not_acquired:{type(exc).__name__}')
        self.lock, self.state, self.promoted_at, self.refused, self.last_check = lock, WRITING, now, None, now
        self.forced = force          # FORCE = the operator overrides the remote checks: no automatic yield either
        with self.sent_lock:
            self.sent = {}
        self.log(json.dumps(dict(event='promoted', force=force, lease=getattr(self.lease, 'token', None))), flush=True)
        return True

    def _refuse(self, why):
        if why != self.refused:
            self.log(json.dumps(dict(event='promote_refused', reason=why)), flush=True)
        self.refused = why
        return False

    def step_down(self, reason):
        """Stop writing NOW. A standby returns to standby (old promote file disarmed); a plain writer stops for good."""
        if self.lock is not None and self.standby:
            try:
                self.lock.close()
            except Exception:
                pass
            self.lock = None
        self.state, self.reason, self.armed_at, self.refused = (STANDBY if self.standby else STOPPED), reason, self.wall(), None
        self.log(json.dumps(dict(event='stepped_down', reason=reason, to=self.state)), flush=True)

    # ---- called by the serving loop ----
    def tick(self):
        now = self.wall()
        if self.state == STOPPED:
            return 'stop'
        if self.state == STANDBY:
            if now - self.last_poll < 1.0:
                return 'idle'
            self.last_poll = now
            ok, force, _ = read_promote(self.promote_path, self.token, self.armed_at, now, self.promote_ttl)
            return 'promoted' if ok and self._open(force) else 'idle'
        # WRITING
        if self.lease is not None:
            if self.lease.superseded():
                self.step_down('lease_superseded')
            elif not self.lease.valid():
                # Not confirmed recently (sleep, network cut, slow checks): confirm before writing anything else.
                if not self.lease.check():
                    if self.lease.superseded():
                        self.step_down('lease_superseded')
                    else:
                        return 'hold'          # unknown: write nothing this loop, ask again on the next one
        if self.state != WRITING:
            return 'stop' if self.state == STOPPED else 'idle'
        return 'write'

    def before_post(self, batch):
        """Last line of defence, called inside post_batch: refuses the POST unless the gate is open."""
        if self.state != WRITING or (self.lease is not None and self.lease.superseded()):
            raise PermissionError('failover gate closed: this process is not the writer')
        now = self.wall()
        with self.sent_lock:
            for a in batch:
                self.sent[a['request_id']] = now
            if len(self.sent) > 4000:
                for k in [k for k, t in self.sent.items() if now - t > 120]:
                    del self.sent[k]

    # ---- background checks (own thread; never on the serving path) ----
    def check_once(self):
        """One round of remote checks while writing. Returns the reason for stepping down, or None."""
        if self.state != WRITING:
            return None
        now = self.wall()
        self.last_check = now
        if self.lease is not None:
            self.lease.check()
            if self.lease.superseded():
                self.step_down('lease_superseded')
                return 'lease_superseded'
        if self.yield_to_foreign and not self.forced and now - (self.promoted_at or now) >= 12 + self.grace:
            try:
                rows = self.query(active_sql(self.team))
            except Exception:
                return None
            with self.sent_lock:
                mine = set(self.sent)
            n = foreign_count(rows, mine)
            if n >= self.foreign_limit:
                self.step_down(f'foreign_writer:{n}_submissions_not_ours_in_8s')
                return 'foreign_writer'
        return None

    def run_checks(self, stop):
        while not stop.is_set():
            try:
                self.check_once()
            except Exception as exc:
                self.log(json.dumps(dict(event='gate_check_error', error=type(exc).__name__)), flush=True)
            stop.wait(self.check_every)

    def close(self):
        if self.lock is not None and self.standby:
            try:
                self.lock.close()
            except Exception:
                pass
            self.lock = None


def holder_name():
    import socket
    return f"{socket.gethostname()}:{os.getpid()}"
