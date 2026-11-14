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


class WriterLock:
    """Local OS lock released on crash; also protects different script copies.

    Does not coordinate laptops. Team must designate exactly one writer host.
    """
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, 'a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Another patched writer already holds this team lock') from None

    def close(self):
        if not self.file.closed:
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()


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
