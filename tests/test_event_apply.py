import threading
import unittest
from recsys.event_apply import apply_chunks


class EventApplyTests(unittest.TestCase):
    def test_counts_order_and_lock_are_preserved_and_yield_is_outside_lock(self):
        lock=threading.Lock(); seen=[]; checkpoints=[]
        def apply(row):
            self.assertTrue(lock.locked())
            seen.append(row)
        def yielded():
            self.assertFalse(lock.locked())
            checkpoints.append(len(seen))
        result=apply_chunks(list(range(150)),lock,apply,chunk_size=64,yield_thread=yielded)
        self.assertEqual(seen,list(range(150)))
        self.assertEqual(checkpoints,[64,128])
        self.assertEqual(result['chunks'],3)

    def test_foreground_can_read_before_backlog_finishes(self):
        lock=threading.Lock(); yielded=threading.Event(); foreground=threading.Event(); seen=[]
        def pause():
            yielded.set()
            self.assertTrue(foreground.wait(1))
        worker=threading.Thread(target=lambda:apply_chunks(list(range(128)),lock,seen.append,yield_thread=pause))
        worker.start()
        try:
            self.assertTrue(yielded.wait(1))
            with lock: self.assertEqual(len(seen),64)
            foreground.set()
        finally:
            foreground.set(); worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(seen,list(range(128)))

    def test_exception_releases_lock_and_is_not_silently_swallowed(self):
        lock=threading.Lock()
        with self.assertRaises(ValueError):
            apply_chunks([1],lock,lambda row:(_ for _ in ()).throw(ValueError('fixture')))
        self.assertFalse(lock.locked())

    def test_empty_batch_is_no_work(self):
        self.assertEqual(apply_chunks([],threading.Lock(),lambda row:self.fail())['chunks'],0)

    def test_live_refresh_preserves_every_delta_and_checkpoint(self):
        from collections import defaultdict
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from recsys import live
        rows=[dict(u='u',i=str(i),v=2,a=3,p=i%2,mx=f'2026-11-14 15:00:{i%60:02}') for i in range(70)]
        stream=SimpleNamespace(add=Mock()); aff=SimpleNamespace(add=Mock()); lf=SimpleNamespace(add=Mock())
        bought=defaultdict(set); state={'ev_ts':'2026-11-14 07:00:00'}
        with patch.object(live,'query',side_effect=[rows,[]]), patch.object(live,'LIVE',stream), \
             patch.object(live,'AP',aff),patch.object(live,'LF',lf),patch.object(live,'BOUGHT',bought), \
             patch.object(live,'state',state),patch('builtins.print'):
            self.assertIs(live.refresh_events(),stream)
        expected=[(r['u'],r['i'],r['v'],r['a'],r['p']) for r in rows]
        self.assertEqual([c.args for c in stream.add.call_args_list],expected)
        self.assertEqual([c.args for c in lf.add.call_args_list],expected)
        self.assertEqual(aff.add.call_count,len(rows))
        self.assertEqual(bought['u'],{r['i'] for r in rows if r['p']})
        self.assertEqual(state['ev_ts'],max(r['mx'] for r in rows))


if __name__=='__main__':unittest.main()
