"""Zero-downtime restart: lock handoff between two writer processes, chunked start-up backfill, graceful stop."""
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import pandas as pd

from recsys import live
from recsys.serving import WriterLock, holder_pid, pid_path, take_over

ROOT = Path(__file__).resolve().parents[1]

HOLDER = textwrap.dedent('''
    import signal, sys, time
    sys.path.insert(0, {root!r})
    from recsys.serving import WriterLock
    mode, lock_path, trace = sys.argv[1], sys.argv[2], sys.argv[3]
    stop = []
    if mode == 'graceful':
        signal.signal(signal.SIGINT, lambda *a: stop.append(1)); signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
    elif mode == 'deaf':                      # ignores everything catchable: only SIGKILL frees the lock
        signal.signal(signal.SIGINT, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN)
    elif mode == 'nohup':                     # background job of a non-interactive shell: SIGINT ignored, SIGTERM kills
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    lock = WriterLock(lock_path)
    print('holding', flush=True)
    while not stop:
        open(trace, 'a').write('w %.6f\\n' % time.time())      # "writes" only while it holds the lock
        time.sleep(0.005)
    open(trace, 'a').write('released %.6f\\n' % time.time())
    lock.close()
''')


def start_holder(mode, lock_path, trace):
    p = subprocess.Popen([sys.executable, '-c', HOLDER.format(root=str(ROOT)), mode, str(lock_path), str(trace)],
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == 'holding'
    return p


def last_write(trace):
    return max(float(line.split()[1]) for line in Path(trace).read_text().splitlines())


@unittest.skipIf(os.name == 'nt', 'POSIX signals')
class TakeoverTests(unittest.TestCase):
    def run_case(self, mode, steps, expect_signals):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path, trace = Path(tmp) / 'writer.lock', Path(tmp) / 'trace'
            old = start_holder(mode, lock_path, trace)
            try:
                self.assertEqual(holder_pid(lock_path), old.pid)
                with self.assertRaises(RuntimeError):
                    WriterLock(lock_path)                       # a plain second writer is still refused
                logged = []
                started = time.time()
                lock = take_over(lock_path, steps=steps, give_up=8, log=lambda *a, **k: logged.append(a))
                acquired = time.time()
                old.wait(timeout=5)
                # Single writer: the old process never "wrote" after the new one got the lock.
                self.assertLessEqual(last_write(trace), acquired)
                self.assertIn(expect_signals, logged[-1][0])
                self.assertEqual(int(pid_path(lock_path).read_text()), os.getpid())
                lock.close()
                self.assertFalse(pid_path(lock_path).exists())
                return acquired - started
            finally:
                if old.poll() is None:
                    old.kill()
                old.stdout.close()

    def test_graceful_writer_hands_over_on_sigint(self):
        waited = self.run_case('graceful', ((0.0, 'SIGINT'), (3.0, 'SIGTERM'), (6.0, 'SIGKILL')), '["SIGINT"]')
        self.assertLess(waited, 1.0)

    def test_writer_started_with_sigint_ignored_gets_sigterm(self):
        self.run_case('nohup', ((0.0, 'SIGINT'), (0.3, 'SIGTERM'), (5.0, 'SIGKILL')), '["SIGINT", "SIGTERM"]')

    def test_deaf_writer_is_killed_and_os_releases_lock(self):
        self.run_case('deaf', ((0.0, 'SIGINT'), (0.2, 'SIGTERM'), (0.4, 'SIGKILL')), '["SIGINT", "SIGKILL", "SIGTERM"]')

    def test_old_writer_without_pid_file_needs_replace_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path, trace = Path(tmp) / 'writer.lock', Path(tmp) / 'trace'
            old = start_holder('graceful', lock_path, trace)
            try:
                pid_path(lock_path).unlink()                    # writer from before this change
                with self.assertRaises(RuntimeError):           # nobody to signal -> gives up, nothing written
                    take_over(lock_path, give_up=0.3, log=lambda *a, **k: None)
                self.assertIsNone(old.poll())                   # old writer untouched and still serving
                lock = take_over(lock_path, old_pid=old.pid, give_up=5, log=lambda *a, **k: None)
                old.wait(timeout=5)
                lock.close()
            finally:
                if old.poll() is None:
                    old.kill()
                old.stdout.close()

    def test_no_running_writer_takes_lock_at_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            killed = []
            lock = take_over(Path(tmp) / 'writer.lock', kill=lambda *a: killed.append(a), log=lambda *a, **k: None)
            self.assertEqual(killed, [])
            lock.close()

    def test_stale_pid_file_of_dead_writer_is_harmless(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / 'writer.lock'
            dead = subprocess.Popen([sys.executable, '-c', 'pass']); dead.wait()
            pid_path(lock_path).write_text(str(dead.pid))
            lock = take_over(lock_path, give_up=2, log=lambda *a, **k: None)   # lock is free: no signal is needed
            self.assertEqual(int(pid_path(lock_path).read_text()), os.getpid())
            lock.close()

    def test_lock_wait_acquires_when_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'writer.lock'
            first = WriterLock(path)
            threading.Timer(0.15, first.close).start()
            # flock is per open file, so a second handle in this process contends like another process would
            second = WriterLock(path, wait=3)
            self.assertTrue(first.file.closed)
            second.close()

    def test_stop_signal_sets_flag_instead_of_killing(self):
        live.STOP.clear()
        previous = signal.signal(signal.SIGTERM, live.request_stop)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            deadline = time.time() + 2
            while not live.STOP.is_set() and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(live.STOP.is_set())
        finally:
            signal.signal(signal.SIGTERM, previous); live.STOP.clear()


class BackfillTests(unittest.TestCase):
    def test_windows_are_contiguous_and_end_open(self):
        w = live.event_windows('2026-11-14 07:00:00', pd.Timestamp('2026-11-14 10:20:00'), hours=1.0)
        self.assertEqual(w[0][0], '2026-11-14 07:00:00')
        self.assertEqual([a for a, _ in w][1:], [b for _, b in w][:-1])
        self.assertIsNone(w[-1][1])
        self.assertEqual(len(w), 4)
        self.assertEqual(live.event_windows('2026-11-14 10:19:50', pd.Timestamp('2026-11-14 10:20:00')),
                         [('2026-11-14 10:19:50', None)])

    def test_backfill_releases_feature_lock_between_chunks(self):
        product = live.fe.C.index[0]
        rows = [dict(u=f'u{k}', i=product, v=1, a=0, p=k % 2) for k in range(25)]
        saved = (live.LIVE, live.AP, live.LF, dict(live.BOUGHT))
        live.LIVE, live.AP, live.LF = live.LiveTables(), None, None
        free = []
        try:
            def pause(_):
                got = live.feature_lock.acquire(blocking=False)     # what a waiting predict() would do
                free.append(got)
                if got: live.feature_lock.release()
            live.apply_events(rows, chunk=10, pause=pause)
            self.assertEqual(free, [True, True])                    # 3 chunks -> 2 gaps, lock free in both
            self.assertEqual(live.LIVE['item'].d[product], [25, 0, 12])
            self.assertEqual(len(live.LIVE['utot'].d), 25)
            self.assertIn(product, live.BOUGHT['u1'])
        finally:
            live.LIVE, live.AP, live.LF = saved[:3]
            for k in range(25): live.BOUGHT.pop(f'u{k}', None)

    def test_live_tables_follow_catalog_swaps(self):
        old = live.fe.C
        try:
            T = live.LiveTables()
            known = old.index[0]
            T.add('u', known, 2, 1, 0)
            T.add('u', 'p_not_yet', 5, 0, 0)                        # unknown product: ignored, as before
            self.assertEqual(T['item'].d, {known: [2, 1, 0]})
            self.assertEqual(T['usub'].d[('u', old.at[known, 'sub'])], [2, 0])
            self.assertEqual(T['ucat'].d[('u', old.at[known, 'category'])], [2, 0])
            new = pd.concat([old, old.iloc[[0]].rename(index={known: 'p_not_yet'})])
            live.fe.set_catalog(new)                                # the refresher publishes a catalogue with the launch
            T.add('u', 'p_not_yet', 5, 0, 0)
            self.assertEqual(T['item'].d['p_not_yet'], [5, 0, 0])
        finally:
            live.fe.set_catalog(old)


if __name__ == '__main__':
    unittest.main()
