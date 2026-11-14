"""Deadline and at-most-once helpers; no network/model dependencies."""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def timestamp(value):
    t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t).timestamp()


def age(request, now=None):
    return (time.time() if now is None else now) - timestamp(request['ts'])


def repair(items, best, active):
    output, seen = [], set()
    for p in list(items or []) + list(best):
        if isinstance(p, str) and p in active and p not in seen:
            seen.add(p)
            output.append(p)
            if len(output) == 10:
                return output
    raise ValueError('Fewer than ten eligible products; refusing invalid submission')


class Journal:
    """Claim BEFORE POST. Ambiguous failures are never blindly retried.

    A crash after claim but before POST can lose that answer; this favors avoiding
    duplicate submissions when the server has no documented idempotency contract.
    """
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS attempts (request_id TEXT PRIMARY KEY, status TEXT, payload TEXT, at REAL)')
        self.db.commit()

    def contains(self, rid):
        return self.db.execute('SELECT 1 FROM attempts WHERE request_id=?', (rid,)).fetchone() is not None

    def claim(self, answer):
        with self.db:
            return self.db.execute('INSERT OR IGNORE INTO attempts VALUES (?, ?, ?, ?)',
                (answer['request_id'], 'attempted', json.dumps(answer), time.time())).rowcount == 1

    def finish(self, ids, status):
        with self.db:
            self.db.executemany('UPDATE attempts SET status=? WHERE request_id=?', [(status, rid) for rid in ids])

    def close(self):
        self.db.close()


def pid_path(lock_path):
    return Path(lock_path).with_suffix('.pid')


def holder_pid(lock_path):
    """Pid written by the current lock holder, or None (no file, garbage, or our own pid)."""
    try:
        pid = int(pid_path(lock_path).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 1 and pid != os.getpid() else None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def take_over(lock_path, old_pid=None, kill=os.kill, sleep=time.sleep, clock=time.monotonic,
              steps=((0.0, 'SIGINT'), (3.0, 'SIGTERM'), (6.0, 'SIGKILL')), give_up=12.0, log=print):
    """Ask the running writer to stop and return the WriterLock once the OS hands it over.

    The lock is the only authority: this process never writes before holding it, and the OS releases it
    only when the old process has closed it or died, so there are never two writers. The old process is
    signalled (old_pid if given, needed for a writer that predates the pid file; else the lock holder's pid file):
    SIGINT lets it finish its loop; SIGTERM / SIGKILL follow only if the lock is still held.
    Raises RuntimeError (and writes nothing) if the lock was not obtained within give_up seconds.
    """
    import signal
    pid = old_pid or holder_pid(lock_path)
    if pid == os.getpid():
        pid = None
    started, sent = clock(), set()
    while True:
        try:
            lock = WriterLock(lock_path)
            log(json.dumps(dict(event='takeover', old_pid=pid, waited_ms=round(1000*(clock()-started), 1),
                                signals=sorted(sent))), flush=True)
            return lock
        except RuntimeError:
            pass
        waited = clock() - started
        if waited >= give_up:
            raise RuntimeError('Takeover failed: the old writer still holds the lock; nothing was written')
        if pid:
            for after, name in steps:
                if waited >= after and name not in sent and hasattr(signal, name):
                    sent.add(name)
                    try:
                        kill(pid, getattr(signal, name))
                    except ProcessLookupError:
                        pass
                    except OSError as exc:
                        log('takeover signal failed', name, type(exc).__name__, flush=True)
        sleep(0.02)


class WriterLock:
    """Local OS lock released on crash; also protects different script copies.

    Does not coordinate laptops. Team must designate exactly one writer host.
    """
    def __init__(self, path, wait=0.0, poll=0.02, sleep=time.sleep, clock=time.monotonic):
        """wait=0: fail at once if another writer holds the lock (unchanged behaviour).
        wait>0: keep trying for that many seconds (takeover: the old writer is on its way out)."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = Path(path)
        self.file = open(path, 'a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'0')
            self.file.flush()
        deadline = clock() + wait
        while True:
            self.file.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if clock() >= deadline:
                    self.file.close()
                    raise RuntimeError('Another patched writer already holds this team lock') from None
                sleep(poll)
        # Only the lock holder writes its pid, so the next takeover knows whom to ask to step down.
        try:
            pid_path(path).write_text(str(os.getpid()))
        except OSError:
            pass

    def close(self):
        if not self.file.closed:
            try:
                if holder_pid_raw(self.path) == os.getpid():
                    pid_path(self.path).unlink()
            except OSError:
                pass
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()


def holder_pid_raw(lock_path):
    try:
        return int(pid_path(lock_path).read_text().strip())
    except (OSError, ValueError):
        return None


def serve(reqs, predict, fallback, send, now=time.time, urgent_age=1.8, max_age=2.5, batch_size=4):
    """Oldest first; urgent fallbacks go out BEFORE any model inference.

    send must revalidate inventory and dedupe atomically before POST. Requests
    too old to send safely are counted, not inserted as known-stale submissions.
    """
    reqs = sorted(reqs, key=lambda r: timestamp(r['ts']))
    urgent, model, expired = [], [], 0
    for r in reqs:
        seconds = age(r, now())
        if seconds > max_age:
            expired += 1
        elif seconds >= urgent_age:
            urgent.append(r)
        else:
            model.append(r)
    if urgent:
        send(urgent, fallback(urgent))
    for offset in range(0, len(model), batch_size):
        group = model[offset:offset+batch_size]
        ready = [r for r in group if age(r, now()) <= max_age]
        expired += len(group)-len(ready)
        if not ready:
            continue
        if age(ready[0], now()) >= urgent_age:
            answers = fallback(ready)
        else:
            try:
                answers = predict(ready)
            except Exception:
                answers = fallback(ready)
        send(ready, answers)
    return expired
