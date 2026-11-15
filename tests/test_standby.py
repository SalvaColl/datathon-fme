"""T-063: standby with manual promote, foreign-writer yield and the remote lease. No network, no real submissions."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from recsys import failover, live
from recsys.failover import Gate, Lease, read_promote, foreign_count
from recsys.serving import WriterLock


class Clock:
    def __init__(self, t=1_000_000.0): self.t = t
    def __call__(self): return self.t
    def tick(self, s): self.t += s


class FakeRawTree:
    """query()/insert() over an in-memory scratch table and a scripted list of submissions."""
    def __init__(self):
        self.scratch, self.active, self.now_ms, self.fail, self.sqls = [], [], 1_794_700_000_000, False, []

    def query(self, sql):
        self.sqls.append(sql)
        if self.fail: raise ConnectionError('down')
        if 'submissions' in sql:
            return list(self.active)
        if 'scratch' in sql:
            if not self.scratch: raise RuntimeError('Unknown expression identifier `kind`')
            return [dict(m=max(r['token'] for r in self.scratch if r['kind'] == 'writer_lease'), now=self.now_ms)]
        return [dict(m=0, now=self.now_ms)]

    def insert(self, row):
        if self.fail: raise ConnectionError('down')
        self.scratch.append(dict(row))


def quiet(*a, **k): pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.promote, self.lock_path = self.dir / 'PROMOTE', self.dir / 'writer.lock'
        self.clock, self.rt, self.locks = Clock(), FakeRawTree(), []

    def lock_factory(self):
        lock = WriterLock(self.lock_path); self.locks.append(lock); return lock

    def gate(self, standby=True, lease=None, **kw):
        g = Gate('team_x', self.rt.query, self.lock_factory, standby, promote_path=self.promote, token='tok',
                 lease=lease, wall=self.clock, log=quiet, **kw)
        self.addCleanup(g.close)
        return g

    def lease(self, holder='a', **kw):
        return Lease('team_x', self.rt.query, self.rt.insert, holder, wall=self.clock, log=quiet, **kw)

    def write_promote(self, text='tok', age=0.0):
        self.promote.write_text(text)
        os.utime(self.promote, (self.clock.t - age, self.clock.t - age))

    def tick(self, g, seconds=1.1):
        self.clock.tick(seconds)
        return g.tick()


class PromoteFile(Base):
    def test_rules(self):
        now = self.clock.t
        self.assertEqual(read_promote(self.promote, 'tok', now - 10, now)[2], 'no_file')
        self.write_promote('tok')
        self.assertEqual(read_promote(self.promote, 'tok', now - 10, now), (True, False, 'ok'))
        self.assertEqual(read_promote(self.promote, 'tok', now + 1, now)[2], 'file_older_than_standby')
        self.assertEqual(read_promote(self.promote, 'tok', now - 500, now + 121)[2], 'file_expired')
        self.assertEqual(read_promote(self.promote, 'other', now - 10, now)[2], 'wrong_token')
        self.assertEqual(read_promote(self.promote, '', now - 10, now)[2], 'no_token_configured')
        self.write_promote('tok FORCE\n')
        self.assertEqual(read_promote(self.promote, 'tok', now - 10, now), (True, True, 'ok'))
        self.write_promote('')
        self.assertFalse(read_promote(self.promote, 'tok', now - 10, now)[0])


class Standby(Base):
    def test_never_writes_before_promote(self):
        g = self.gate()
        for _ in range(50):
            self.assertEqual(self.tick(g, 0.3), 'idle')
        self.assertEqual(self.locks, [])
        with self.assertRaises(PermissionError):
            g.before_post([dict(request_id='r1')])
        self.assertEqual(self.rt.scratch, [])
        self.assertFalse(any('submissions' in s for s in self.rt.sqls))      # no promote file: not even the remote check

    def test_promote_file_from_before_the_start_is_ignored(self):
        self.write_promote('tok', age=5)
        g = self.gate()
        self.assertEqual(self.tick(g), 'idle')
        self.assertEqual(self.locks, [])

    def test_wrong_token_and_expired_file_do_not_promote(self):
        g = self.gate()
        self.clock.tick(5); self.write_promote('nope')
        self.assertEqual(self.tick(g), 'idle')
        self.write_promote('tok')
        self.clock.tick(200)
        self.assertEqual(g.tick(), 'idle')
        self.assertEqual(self.locks, [])

    def test_promote_acquires_the_local_lock_and_then_writes(self):
        g = self.gate()
        self.clock.tick(5); self.write_promote()
        self.assertEqual(self.tick(g), 'promoted')
        self.assertEqual(len(self.locks), 1)
        with self.assertRaises(RuntimeError):
            WriterLock(self.lock_path)                       # really held: a local second writer cannot start
        self.assertEqual(g.tick(), 'write')
        g.before_post([dict(request_id='r1')])               # allowed now
        g.close()
        WriterLock(self.lock_path).close()                   # released on close

    def test_promote_refused_while_another_writer_answers(self):
        g = self.gate()
        self.rt.active = [dict(request_id=f'r{i}', c=1) for i in range(24)]
        self.clock.tick(5); self.write_promote()
        for _ in range(5):
            self.assertEqual(self.tick(g), 'idle')
        self.assertEqual(self.locks, [])
        self.assertTrue(g.refused.startswith('another_writer_is_answering'))
        self.rt.active = []                                   # the old writer is confirmed dead: same file now promotes
        self.assertEqual(self.tick(g), 'promoted')

    def test_promote_refused_when_the_check_cannot_run_or_the_local_lock_is_held(self):
        g = self.gate()
        self.rt.fail = True
        self.clock.tick(5); self.write_promote()
        self.assertEqual(self.tick(g), 'idle')
        self.rt.fail = False
        other = WriterLock(self.lock_path)
        self.assertEqual(self.tick(g), 'idle')
        self.assertEqual(g.refused, 'local_lock_held')
        other.close()
        self.assertEqual(self.tick(g), 'promoted')

    def test_force_skips_the_remote_check_and_the_automatic_yield(self):
        g = self.gate()
        self.rt.active = [dict(request_id=f'r{i}', c=1) for i in range(24)]
        self.clock.tick(5); self.write_promote('tok FORCE')
        self.assertEqual(self.tick(g), 'promoted')
        self.clock.tick(60)
        self.assertIsNone(g.check_once())
        self.assertEqual(g.tick(), 'write')

    def test_foreign_writer_sends_the_standby_back_to_standby(self):
        g = self.gate()
        self.clock.tick(5); self.write_promote()
        self.assertEqual(self.tick(g), 'promoted')
        mine = [dict(request_id=f'r{i}') for i in range(24)]
        g.before_post(mine)
        self.rt.active = [dict(request_id=f'r{i}', c=1) for i in range(24)]
        self.clock.tick(30)
        self.assertIsNone(g.check_once())                     # only our own rows
        self.assertEqual(g.tick(), 'write')
        self.rt.active = [dict(request_id=f'r{i}', c=2) for i in range(24)]      # the old writer is back: duplicates
        self.assertEqual(g.check_once(), 'foreign_writer')
        self.assertEqual(g.tick(), 'idle')
        with self.assertRaises(PermissionError):
            g.before_post([dict(request_id='r99')])
        WriterLock(self.lock_path).close()                    # local lock released
        self.rt.active = []
        self.assertEqual(self.tick(g), 'idle')                # the OLD promote file does not re-promote
        self.clock.tick(3); self.write_promote()
        self.assertEqual(self.tick(g), 'promoted')            # a fresh one does

    def test_foreign_count(self):
        rows = [dict(request_id='a', c=1), dict(request_id='b', c=2), dict(request_id='x', c=1)]
        self.assertEqual(foreign_count(rows, {'a', 'b'}), 2)
        self.assertEqual(foreign_count(rows, set()), 4)
        self.assertEqual(foreign_count([], {'a'}), 0)

    def test_no_yield_during_the_grace_period_or_below_the_limit(self):
        g = self.gate()
        self.clock.tick(5); self.write_promote()
        self.assertEqual(self.tick(g), 'promoted')
        self.rt.active = [dict(request_id=f'z{i}', c=1) for i in range(24)]
        self.clock.tick(5)
        self.assertIsNone(g.check_once())                     # requests from before the promotion may still be listed
        self.clock.tick(30)
        self.rt.active = [dict(request_id=f'z{i}', c=1) for i in range(4)]
        self.assertIsNone(g.check_once())                     # 4 < limit 5


class LeaseLogic(Base):
    def test_first_acquire_on_an_empty_table_and_tokens_grow(self):
        a, b = self.lease('a'), self.lease('b')
        t1 = a.acquire()
        self.assertEqual(self.rt.scratch, [dict(kind='writer_lease', token=t1, holder='a')])
        t2 = b.acquire()                                       # same server millisecond: still strictly larger
        self.assertGreater(t2, t1)
        self.assertTrue(b.check()); self.assertTrue(b.valid())
        self.assertFalse(a.check()); self.assertTrue(a.superseded()); self.assertFalse(a.valid())

    def test_unconfirmed_lease_ages_out_on_wall_time(self):
        a = self.lease('a', max_stale=20)
        a.acquire()
        self.clock.tick(19); self.assertTrue(a.valid())
        self.clock.tick(2); self.assertFalse(a.valid())        # e.g. the laptop slept
        self.assertTrue(a.check()); self.assertTrue(a.valid())

    def test_failed_check_is_not_a_confirmation(self):
        a = self.lease('a')
        a.acquire()
        self.rt.fail = True
        self.assertFalse(a.check()); self.assertFalse(a.superseded())
        self.clock.tick(21); self.assertFalse(a.valid())

    def test_acquire_fails_loudly_when_rawtree_is_down(self):
        self.rt.fail = True
        with self.assertRaises(ConnectionError):
            self.lease('a').acquire()

    def test_plain_writer_steps_down_for_good_when_superseded(self):
        a = self.lease('a')
        g = self.gate(standby=False, lease=a)
        g.start(lock=None)
        self.assertEqual(g.tick(), 'write')
        self.lease('b').acquire()
        self.assertEqual(g.check_once(), 'lease_superseded')
        self.assertEqual(g.tick(), 'stop')
        with self.assertRaises(PermissionError):
            g.before_post([dict(request_id='r1')])

    def test_old_writer_returning_with_a_stale_token_steps_down_before_writing(self):
        """Laptop sleeps for 5 minutes; a standby is promoted meanwhile; the laptop wakes up."""
        old = self.gate(standby=False, lease=self.lease('mac'))
        old.start(lock=None)
        self.assertEqual(old.tick(), 'write')
        new = Gate('team_x', self.rt.query, self.lock_factory, True, promote_path=self.promote, token='tok',
                   lease=self.lease('cloud'), wall=self.clock, log=quiet)
        self.addCleanup(new.close)
        self.clock.tick(300)                                   # asleep: no background check ran on the old writer
        self.write_promote()
        self.assertEqual(self.tick(new), 'promoted')
        self.assertEqual(old.tick(), 'stop')                   # first loop after waking: re-reads the token, stops
        with self.assertRaises(PermissionError):
            old.before_post([dict(request_id='r1')])
        self.assertEqual(new.tick(), 'write')

    def test_writer_holds_instead_of_writing_while_the_lease_cannot_be_confirmed(self):
        g = self.gate(standby=False, lease=self.lease('a'))
        g.start(lock=None)
        self.rt.fail = True
        self.clock.tick(10); self.assertEqual(g.tick(), 'write')       # within max_stale: keep serving
        self.clock.tick(15); self.assertEqual(g.tick(), 'hold')        # 25 s without confirmation: write nothing
        self.rt.fail = False
        self.assertEqual(g.tick(), 'write')

    def test_standby_with_lease_goes_back_to_standby(self):
        g = self.gate(lease=self.lease('cloud'))
        self.clock.tick(5); self.write_promote()
        self.assertEqual(self.tick(g), 'promoted')
        self.lease('other').acquire()
        self.assertEqual(g.check_once(), 'lease_superseded')
        self.assertEqual(g.tick(), 'idle')

    def test_promote_refused_if_the_lease_cannot_be_taken(self):
        g = self.gate(lease=self.lease('cloud'))
        self.clock.tick(5); self.write_promote('tok FORCE')
        self.rt.fail = True
        self.assertEqual(self.tick(g), 'idle')
        WriterLock(self.lock_path).close()                     # lock given back


class LiveWiring(unittest.TestCase):
    def test_default_start_has_no_gate(self):
        self.assertIsNone(live.GATE)
        self.assertIsNone(live.make_gate(False, 'x', argv=['live.py'], env={}))
        self.assertIsNone(live.make_gate(False, 'x', argv=['live.py'], env={'WRITER_LEASE': '0'}))

    def test_post_batch_without_gate_is_unchanged_and_with_closed_gate_never_reaches_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = Gate('team_x', lambda sql: [], lambda: WriterLock(Path(tmp) / 'writer.lock'), True,
                     promote_path=Path(tmp) / 'PROMOTE', token='tok', log=quiet)
            with patch.object(live, 'GATE', g), patch.object(live, 'session') as session:
                with self.assertRaises(PermissionError):
                    live.post_batch([dict(request_id='r1', items=[], model_version='x')], 2.0)
                session.assert_not_called()

    def test_standby_requires_a_token_and_builds_a_closed_gate(self):
        with self.assertRaises(SystemExit):
            live.make_gate(True, 'x', argv=['live.py', '--standby'], env={})
        g = live.make_gate(True, 'x', argv=['live.py', '--standby', '--promote-token', 'abc'], env={})
        self.assertEqual((g.state, g.token, g.lease), (failover.STANDBY, 'abc', None))
        self.assertTrue(str(g.promote_path).endswith('PROMOTE'))
        g = live.make_gate(False, 'x', argv=['live.py'], env={'WRITER_LEASE': '1'})
        self.assertIsNotNone(g.lease)
        self.assertFalse(g.yield_to_foreign)                   # a primary never yields on its own: only standbys do

    def test_idle_step_scores_and_sends_nothing(self):
        now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
        reqs = [dict(request_id=f'r{i}', ts=now, user_id='u') for i in range(20)]
        scored, seen = [], set()
        with patch.object(live, 'pull', return_value=reqs), patch.object(live, 'predict', side_effect=scored.append), \
                patch.object(live, 'post_batch') as post, patch.object(live, 'send_answers') as send:
            live.failover_idle(seen)
        self.assertEqual(len(scored[0]), 8)
        self.assertEqual(len(seen), 8)
        post.assert_not_called(); send.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class MainLoopStandby(unittest.TestCase):
    """live.main() itself in --standby with every model/network piece replaced: nothing is posted before the promote
    file, posts start after it, and the local lock is held while writing and released at exit."""
    def test_main_writes_only_after_promote(self):
        import gc, signal, sys, threading
        from unittest.mock import MagicMock
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        d = Path(tmp.name); promote = d / 'PROMOTE'
        http, counter, marks = MagicMock(), [0], {}

        def pull(seen):
            counter[0] += 1
            now = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()) + '.%03d' % int((time.time() % 1) * 1000)
            return [r for r in [dict(request_id=f'r{counter[0]}', ts=now, user_id='u', rv=[])] if r['request_id'] not in seen]

        def send(reqs, answers, journal, seen, dry=False):
            seen.update(r['request_id'] for r in reqs)
            live.post_batch([dict(request_id=r['request_id'], items=[], model_version='t') for r in reqs], 2.0)

        def operator():
            time.sleep(1.5)
            marks['before'] = http.post.call_count
            marks['lock_free_before'] = not live.GATE.lock
            promote.write_text('s3cret')
            end = time.time() + 6
            while http.post.call_count == 0 and time.time() < end: time.sleep(0.05)
            time.sleep(0.3)
            marks['after'] = http.post.call_count
            try: WriterLock(d / 'writer.lock').close(); marks['held'] = False
            except RuntimeError: marks['held'] = True
            live.STOP.set()

        handlers = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
        callbacks = list(gc.callbacks)
        fake_state = dict(live.state, pools=1, live=1, stock_checked=time.monotonic())
        live.STOP.clear()
        try:
            with patch.object(sys, 'argv', ['live.py', '--standby', '--promote-token', 's3cret', '--promote-file', str(promote)]), \
                    patch.dict(os.environ, {'RAWTREE_LOCK_DIR': str(d)}), patch.object(live, 'DRY', False), \
                    patch.object(live, 'initialize'), patch.object(live, 'refresher'), patch.object(live, 'stock_refresher'), \
                    patch.object(live, 'warm_up'), patch.object(live, 'settle_gc'), patch.object(live, 'state', fake_state), \
                    patch.object(live, 'query', return_value=[]), patch.object(live, 'pull', side_effect=pull), \
                    patch.object(live, 'predict', side_effect=lambda reqs: [dict(request_id=r['request_id']) for r in reqs]), \
                    patch.object(live, 'send_answers', side_effect=send), patch.object(live, 'session', return_value=http), \
                    patch.object(live, 'fallback_answers', return_value=[]), \
                    patch.object(live, 'GATE', None):
                t = threading.Thread(target=operator); t.start()
                live.main()
                t.join()
        finally:
            live.STOP.clear()
            signal.signal(signal.SIGINT, handlers[0]); signal.signal(signal.SIGTERM, handlers[1])
            gc.callbacks[:] = callbacks
        self.assertEqual(marks['before'], 0)
        self.assertTrue(marks['lock_free_before'])
        self.assertGreater(marks['after'], 0)
        self.assertTrue(marks['held'])
        self.assertTrue(all(c.args[0].endswith('/v1/tables/submissions') for c in http.post.call_args_list))
        WriterLock(d / 'writer.lock').close()                  # released when main() returned
