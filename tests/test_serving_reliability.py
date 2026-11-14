import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from recsys.serving import Journal, WriterLock, age, repair, serve
from recsys import live


def req(rid, age_s, now=100):
    return {'request_id': rid, 'ts': datetime.fromtimestamp(now-age_s, timezone.utc).isoformat(),
            'rv': [], 'user_id': 'u', 'page': 'home'}


class ServingTests(unittest.TestCase):
    def test_urgent_sent_before_inference_and_expired_skipped(self):
        calls = []
        def predict(rows):
            calls.append(('model', [r['request_id'] for r in rows]))
            return rows
        def send(rows, answers):
            calls.append(('send', [r['request_id'] for r in rows]))
        expired = serve([req('young', .1), req('urgent', 2), req('expired', 4)],
            predict, lambda r: r, send, now=lambda: 100)
        self.assertEqual(calls, [('send', ['urgent']), ('model', ['young']), ('send', ['young'])])
        self.assertEqual(expired, 1)

    def test_time_spent_on_one_batch_ages_the_next(self):
        clock = [100]
        events = []
        def predict(rows):
            events.append('model')
            clock[0] += 2
            return rows
        def fallback(rows):
            events.append('guard')
            return rows
        serve([req(str(i), .1) for i in range(5)], predict, fallback, lambda *args: None,
              now=lambda: clock[0], batch_size=4)
        self.assertEqual(events, ['model', 'guard'])

    def test_journal_restart_and_ambiguous_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'attempts.db'
            j = Journal(path)
            answer = {'request_id': 'a', 'items': list('0123456789'), 'model_version': 'x'}
            self.assertTrue(j.claim(answer))
            j.finish(['a'], 'uncertain')
            j.close()
            j = Journal(path)
            self.assertTrue(j.contains('a'))
            self.assertFalse(j.claim(answer))
            self.assertEqual(j.db.execute('SELECT status FROM attempts').fetchone()[0], 'uncertain')
            j.close()

    def test_process_lock_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'writer.lock'
            a = WriterLock(path)
            try:
                with self.assertRaises(RuntimeError):
                    WriterLock(path)
            finally:
                a.close()
            b = WriterLock(path)
            b.close()

    def test_repair_unknown_duplicate_out_of_stock(self):
        active = set(str(i) for i in range(1, 12))
        items = repair(['0', '1', '1', 'unknown'], [str(i) for i in range(12)], active)
        self.assertEqual(items, [str(i) for i in range(1, 11)])
        with self.assertRaises(ValueError):
            repair([], ['0'], {'0'})

    def test_age_utc_offsets(self):
        self.assertEqual(age({'ts': '1970-01-01T01:01:39+01:00'}, 100), 1)

    def test_pull_does_not_ack_before_send(self):
        seen = set()
        row = dict(req('a', .1), rv='[]')
        with patch.object(live, 'query', return_value=[row]):
            self.assertEqual(len(live.pull(seen)), 1)
        self.assertEqual(seen, set())

    def test_final_inventory_recheck_and_no_timeout_retry(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(Path(tmp)/'journal.db')
            r = req('a', .1)
            ans = dict(request_id='a', items=[str(i) for i in range(10)], model_version='x')
            snapshot = ({}, {'0'}, pd.DataFrame(index=[str(i) for i in range(12)]), None,
                        [str(i) for i in range(12)])
            seen = set()
            with patch.object(live, 'snapshot', return_value=snapshot), patch.object(live, 'age', return_value=.1), patch.object(live, 'session') as http:
                http.return_value.post.side_effect = TimeoutError('ack lost')
                live.send_answers([r], [ans], j, seen)
                live.send_answers([r], [ans], j, seen)
                self.assertEqual(http.return_value.post.call_count, 1)
                sent = http.return_value.post.call_args.kwargs['json'][0]
                self.assertNotIn('0', sent['items'])
                self.assertEqual(len(set(sent['items'])), 10)
                self.assertEqual(j.db.execute('SELECT status FROM attempts').fetchone()[0], 'uncertain')
            j.close()

    def test_dry_run_never_posts_or_claims(self):
        import pandas as pd
        r = req('a', .1)
        snapshot = ({}, set(), pd.DataFrame(index=list('0123456789')), None, list('0123456789'))
        with patch.object(live, 'snapshot', return_value=snapshot), patch.object(live, 'age', return_value=.1), patch.object(live, 'session') as http:
            live.send_answers([r], [], None, set(), dry=True)
            http.assert_not_called()

    def test_unknown_last_view_does_not_break_candidate_batch(self):
        import pandas as pd
        cat = pd.DataFrame({'category': ['x'], 'sub': ['s']}, index=['p'])
        pools = dict(sub={}, cat={}, glob=['p'], new=['p'])
        self.assertEqual(live.candidates(dict(rv=['unknown'], user_id='u'), pools, set(), cat), [])

    def test_catalog_snapshot_and_any_sub_features(self):
        import pandas as pd
        from recsys import fe
        ids = fe.CAT.product_id.tolist()[:12]
        ui = pd.DataFrame([('u', p, 3, 1, 0) for p in ids], columns=['u','i','v','a','p'])
        tables = fe.build_tables(ui)
        rows = pd.DataFrame([(0, 'u', p, 0, ids[:3], 'product', False) for p in ids],
                            columns=['sid','u','i','slot','rv','page','new_user'])
        catalog = fe.C
        now = pd.Timestamp('2026-11-14 12:00:00')
        expected = fe.featurize(rows, tables, now)
        expected_sub = [int(s in set(catalog['sub'].reindex(ids[:3]).values)) for s in expected['sub']]
        self.assertEqual(expected.any_sub.tolist(), expected_sub)
        with patch.object(fe, 'C', pd.DataFrame()):
            actual = fe.featurize(rows, tables, now, catalog=catalog)
        pd.testing.assert_frame_equal(actual[fe.FEATS], expected[fe.FEATS])


if __name__ == '__main__':
    unittest.main()
