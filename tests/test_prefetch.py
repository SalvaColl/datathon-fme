"""Local transport invariants: mock reads, no RawTree calls, no writer startup."""
import inspect
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from recsys.prefetch import RequestReader
from recsys import live


def row(rid, born=100):
    return dict(request_id=rid, ts=datetime.fromtimestamp(born,timezone.utc).isoformat(), rv=[])


class ReaderBufferTests(unittest.TestCase):
    def test_deduplicated_oldest_first_no_seen_claim(self):
        r=RequestReader(lambda:[], now=lambda:100)
        records=[row('b',99.5),row('a',99),row('b',99.5)]
        r.offer(records)
        self.assertEqual([x['request_id'] for x in r.take(0)], ['a','b'])
        self.assertEqual(r.take(0), [])
        self.assertEqual(records[0]['request_id'],'b')

    def test_expired_and_bad_records_are_not_buffered(self):
        r=RequestReader(lambda:[], now=lambda:100)
        r.offer([row('old',96),row('ok',99),{},dict(request_id='bad',ts='bad')])
        self.assertEqual([x['request_id'] for x in r.take(0)],['ok'])
        self.assertEqual(r.stats()['expired_observations'],1)
        self.assertEqual(r.stats()['invalid_observations'],2)

    def test_capacity_is_bounded_and_freshest_are_retained(self):
        r=RequestReader(lambda:[], capacity=2, now=lambda:100)
        r.offer([row('a',99),row('b',99.5),row('c',99.9)])
        self.assertEqual(r.stats()['overflow_drops'],1)
        self.assertEqual([x['request_id'] for x in r.take(0)],['b','c'])

    def test_queue_expiry_and_clock_warning(self):
        clock=[100]
        r=RequestReader(lambda:[], now=lambda:clock[0])
        r.offer([row('a',100)])
        clock[0]=104
        r.offer([row('future',105)])
        self.assertEqual([x['request_id'] for x in r.take(0)],['future'])
        self.assertEqual(r.stats()['future_observations'],1)


class ReaderThreadTests(unittest.TestCase):
    def test_off_by_default_reads_nothing(self):
        called=threading.Event()
        r=RequestReader(lambda:called.set() or []).start()
        try: self.assertFalse(called.wait(.05))
        finally: r.close()
        self.assertFalse(r.thread.is_alive())

    def test_read_can_finish_while_main_thread_is_busy_then_drains_on_disable(self):
        started,release=threading.Event(),threading.Event()
        calls=[]
        def pull():
            calls.append(threading.current_thread().name)
            started.set()
            self.assertTrue(release.wait(1))
            return [row('a')]
        r=RequestReader(pull,now=lambda:100).start()
        try:
            r.enable(True)
            self.assertTrue(started.wait(1))
            r.enable(False)  # rollback while read in flight
            self.assertTrue(r.should_drain())
            release.set()
            self.assertEqual([x['request_id'] for x in r.take(1)],['a'])
            with r.cv: self.assertTrue(r.cv.wait_for(lambda:not r.busy,1))
            self.assertFalse(r.should_drain())
            self.assertEqual(calls,['rawtree-request-reader'])
        finally: release.set(); r.close()

    def test_read_timeout_is_counted_and_recovery_is_possible(self):
        recovered=threading.Event(); failed=[]
        def pull():
            if not failed:
                failed.append(True)
                raise TimeoutError('mock')
            recovered.set()
            return [row('a')]
        r=RequestReader(pull,now=lambda:100,interval=.01).start()
        try:
            r.enable(True)
            self.assertTrue(recovered.wait(1))
            r.enable(False)
            self.assertEqual([x['request_id'] for x in r.take(1)],['a'])
            self.assertGreaterEqual(r.stats()['poll_errors'],1)
        finally: r.close()

    def test_reader_has_no_submission_or_journal_code(self):
        import recsys.prefetch as module
        source=inspect.getsource(module)
        self.assertNotIn('/v1/tables',source)
        self.assertNotIn('.post(',source)
        self.assertNotIn('sqlite3',source)


class DeliveryConfigTests(unittest.TestCase):
    def test_enable_disable_does_not_change_policy_or_public_labels(self):
        saved=dict(live.POLICY)
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(live,'DATA',Path(tmp)):
                p=Path(tmp)/'policy.json'
                for mode,expected in [('k28','k28'),('garbage','serial'),(None,'serial')]:
                    conf={'variant':saved['variant']}
                    if mode is not None: conf['delivery']=mode
                    p.write_text(json.dumps(conf))
                    live.read_policy()
                    self.assertEqual(live.POLICY['delivery'],expected)
                    self.assertEqual(live.POLICY['variant'],saved['variant'])
        finally:
            live.POLICY.clear(); live.POLICY.update(saved)

    def test_prefetch_overlaps_ack_but_only_main_thread_writes_once(self):
        # The entire integration is mocked: no model, RawTree call, real journal,
        # writer lock, or live producer is started by this test.
        from types import SimpleNamespace
        import pandas as pd
        second_read = threading.Event()
        claimed, writes, polls = set(), [], []
        saved_policy, saved_state, saved_labels = dict(live.POLICY), dict(live.state), dict(live.LABELS)
        def pull(seen):
            polls.append(threading.current_thread().name)
            rows = [row('a',time.time())]
            if writes:
                rows.append(row('b',time.time()))
                second_read.set()
            return rows                     # deliberately repeats already-claimed a
        def claim(answer):
            rid=answer['request_id']
            if rid in claimed: return False
            claimed.add(rid)
            return True
        def post(*args,**kwargs):
            writes.extend((a['request_id'],threading.current_thread().name,a['model_version']) for a in kwargs['json'])
            if len(writes)==1:
                self.assertTrue(second_read.wait(1),'reader blocked behind POST acknowledgement')
                return SimpleNamespace(raise_for_status=lambda:None)
            raise KeyboardInterrupt('end of entirely mocked integration')
        journal=SimpleNamespace(contains=lambda rid:rid in claimed, claim=claim, finish=lambda *a:None, close=lambda:None)
        ids=list('0123456789')
        try:
            live.POLICY['delivery']='k28'
            live.state['pools']={}
            live.LABELS.update(salt='unit-test',map={'neutralA':'zz01'},seen={})
            with patch.object(live,'initialize'), patch.object(live,'refresher'), patch.object(live,'stock_refresher'), \
                 patch.object(live,'WriterLock'), patch.object(live,'Journal',return_value=journal), \
                 patch.object(live,'query',return_value=[]), patch.object(live,'pull',side_effect=pull), \
                 patch.object(live,'DRY',False), patch.object(live,'AB',False), \
                 patch.object(live,'snapshot',return_value=({},set(),pd.DataFrame(index=ids),None,ids)), \
                 patch.object(live,'predict',side_effect=lambda rs:[dict(request_id=r['request_id'],items=ids,model_version='neutralA') for r in rs]), \
                 patch.object(live,'session') as http, patch('builtins.print'):
                http.return_value.post.side_effect=post
                with self.assertRaises(KeyboardInterrupt): live.main()
            self.assertEqual([w[0] for w in writes],['a','b'])
            self.assertTrue(all(w[1]==threading.current_thread().name for w in writes))
            self.assertTrue(all(w[2]=='zz01' for w in writes))
            self.assertTrue(all(p=='rawtree-request-reader' for p in polls))
        finally:
            live.POLICY.clear(); live.POLICY.update(saved_policy)
            live.state.clear(); live.state.update(saved_state)
            live.LABELS.clear(); live.LABELS.update(saved_labels)


class DiagnosticTests(unittest.TestCase):
    def test_log_summary_handles_legacy_noise_and_missing_fields(self):
        from tools.k28_log_summary import summarize
        rows=['not json',json.dumps(dict(event='loop',expired=2,predict_ms=3.,ts_utc=1.)),
              json.dumps(dict(event='push_ack',post_ms=500.,ts_utc=2.)),
              json.dumps(dict(event='push_uncertain',ts_utc=3.))]
        r=summarize(rows)
        self.assertEqual(r['expired'],2)
        self.assertEqual(r['post_ms']['p95'],500.)
        self.assertEqual(r['uncertain_batches'],1)
        self.assertIsNone(r['source_age_ms']['p95'])

    def test_timing_simulation_repeatability_and_outage_limitation(self):
        from tools.k28_simulate import simulate
        for mode in ('serial','k28'):
            a=simulate(mode,'outage')
            self.assertEqual(a,simulate(mode,'outage'))
            self.assertEqual(a['duplicate_attempts'],0)
            self.assertLess(a['on_time'],a['N'])  # overlap cannot remove a network outage


if __name__=='__main__': unittest.main()
