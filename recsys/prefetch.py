"""Optional read-only request prefetch inside the EXISTING writer process.

One reader thread, one bounded deduplicated buffer. No submissions, journal or
models here. Off by default. Consumer still performs every deadline, inventory,
journal and POST operation in its existing single writer thread.
"""
import threading
import time
if __package__:
    from .serving import timestamp
else:
    from serving import timestamp


class RequestReader:
    def __init__(self, pull, capacity=256, max_age=2.5, interval=.1, now=time.time, on_error=None):
        if capacity < 1 or interval <= 0: raise ValueError('Invalid buffer configuration')
        self.pull, self.capacity, self.max_age, self.interval, self.now = pull, capacity, max_age, interval, now
        self.on_error = on_error
        self.cv = threading.Condition()
        self.pending = {}
        self.enabled = self.busy = self.closed = False
        self.counters = dict(polls=0, poll_errors=0, expired_observations=0, invalid_observations=0,
                             overflow_drops=0, future_observations=0, last_poll_ms=0., last_queue_wait_ms=0.)
        self.thread = threading.Thread(target=self._run, name='rawtree-request-reader', daemon=True)

    def start(self):
        self.thread.start()
        return self

    def enable(self, value):
        with self.cv:
            self.enabled = bool(value)
            self.cv.notify_all()

    def should_drain(self):
        # On rollback, wait for the in-flight read and consume its buffer before
        # serial polling resumes. Never create two request-query streams.
        with self.cv:
            return self.busy or bool(self.pending)

    def offer(self, rows):
        now = self.now()
        with self.cv:
            self.pending = {rid:entry for rid,entry in self.pending.items() if now-entry[0] <= self.max_age}
            for row in rows:
                try: ts = timestamp(row['ts']); rid = row['request_id']
                except (ValueError, TypeError, KeyError):
                    self.counters['invalid_observations'] += 1
                    continue
                if now-ts > self.max_age:
                    self.counters['expired_observations'] += 1
                    continue
                if ts-now > .25: self.counters['future_observations'] += 1
                if rid not in self.pending:
                    self.pending[rid] = (ts, time.perf_counter(), dict(row))
            while len(self.pending) > self.capacity:
                oldest = min(self.pending, key=lambda rid:self.pending[rid][0])
                del self.pending[oldest]
                self.counters['overflow_drops'] += 1
            self.cv.notify_all()

    def take(self, timeout=.1):
        with self.cv:
            self.cv.wait_for(lambda: self.pending or self.closed or (not self.busy and not self.enabled), timeout)
            entries = sorted(self.pending.values(), key=lambda entry:entry[0])
            self.pending.clear()
            self.counters['last_queue_wait_ms'] = max((1000*(time.perf_counter()-e[1]) for e in entries), default=0.)
            return [e[2] for e in entries]

    def stats(self):
        with self.cv:
            return dict(self.counters, buffered=len(self.pending), busy=self.busy)

    def _run(self):
        failures = 0
        while True:
            with self.cv:
                self.cv.wait_for(lambda:self.enabled or self.closed)
                if self.closed: return
                self.busy = True
            begin = time.perf_counter()
            try:
                rows = self.pull()           # read-only; caller supplies live.pull(seen)
                failures = 0
                with self.cv:
                    if not self.closed: self.offer(rows)
            except Exception as exc:
                failures += 1
                with self.cv:
                    self.counters['poll_errors'] += 1
                    count = self.counters['poll_errors']
                if self.on_error and (count <= 3 or count % 10 == 0):
                    try: self.on_error(type(exc).__name__, count)
                    except Exception: pass
            finally:
                with self.cv:
                    self.busy = False
                    self.counters['polls'] += 1
                    self.counters['last_poll_ms'] = 1000*(time.perf_counter()-begin)
                    self.cv.notify_all()
            with self.cv:
                pause = min(1., self.interval * 2**min(failures,4)) if failures else self.interval
                self.cv.wait_for(lambda:self.closed or not self.enabled,
                                 max(0,pause-(time.perf_counter()-begin)))

    def close(self):
        with self.cv:
            self.closed = True
            self.enabled = False
            self.pending.clear()
            self.cv.notify_all()
        if self.thread.is_alive(): self.thread.join(timeout=.1)
