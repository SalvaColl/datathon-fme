"""T-047: ONE deadline-bounded retry of the submissions POST, for requests' ConnectTimeout only. Synthetic clock, no network."""
import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests
from requests import exceptions as rx

from recsys import live
from recsys.serving import Journal

ITEMS = [str(i) for i in range(10)]
SNAP = ({}, set(), pd.DataFrame(index=[str(i) for i in range(12)]), None, [str(i) for i in range(12)])


def req(rid):
    return {'request_id': rid, 'ts': datetime.now(timezone.utc).isoformat(), 'rv': [], 'user_id': 'u' + rid, 'page': 'home'}


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.j = Journal(Path(self.tmp.name) / 'j.db')
        self.ages = {}            # request id -> age "now"; every POST attempt advances all of them by its duration
        self.calls = []           # (payload copy, remaining) per POST attempt
        self.script = []          # per attempt: (seconds it takes, exception or None)
        self.old_age = live.CONNECT_RETRY_AGE
        ps = [patch.object(live, 'snapshot', return_value=SNAP), patch.object(live, 'age', side_effect=lambda r, now=None: self.ages[r['request_id']]),
              patch.object(live, 'post_batch', side_effect=self.post)]
        for p in ps: p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        live.CONNECT_RETRY_AGE = self.old_age; self.j.close(); self.tmp.cleanup()

    def post(self, batch, remaining):
        took, exc = self.script[len(self.calls)]
        self.calls.append((json.loads(json.dumps(batch)), remaining))
        for k in self.ages: self.ages[k] += took
        if exc is not None: raise exc

    def send(self, ages, script, dry=False):
        self.script = script; self.calls = []
        reqs = [req(str(k)) for k in range(len(ages))]
        self.ages = {r['request_id']: a for r, a in zip(reqs, ages)}
        answers = [dict(request_id=r['request_id'], items=list(ITEMS), model_version='x') for r in reqs]
        out = io.StringIO()
        with redirect_stdout(out): live.send_answers(reqs, answers, None if dry else self.j, set(), dry=dry)
        self.reqs, self.answers = reqs, answers
        return [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{')]

    def status(self):
        return dict(self.j.db.execute('SELECT request_id, status FROM attempts').fetchall())

    def test_only_connect_timeout_counts_as_never_sent(self):
        self.assertTrue(live.never_sent(rx.ConnectTimeout()))
        self.assertTrue(issubclass(rx.ConnectTimeout, rx.ConnectionError) and issubclass(rx.ConnectTimeout, rx.Timeout))   # why isinstance on the parents would be wrong
        for exc in (rx.ReadTimeout(), rx.Timeout(), rx.ConnectionError(), rx.ProxyError(), rx.SSLError(), rx.HTTPError(), rx.ChunkedEncodingError(),
                    rx.RequestException(), TimeoutError(), ConnectionResetError(), OSError(), RuntimeError(), KeyboardInterrupt()):
            self.assertFalse(live.never_sent(exc), type(exc).__name__)

    def test_connect_failure_then_success_sends_the_same_payload_once_more(self):
        log = self.send([0.9, 1.2], [(0.3, rx.ConnectTimeout()), (0.32, None)])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][0], self.calls[1][0])                         # the very same claimed payload
        self.assertAlmostEqual(self.calls[0][1], 3 - 1.2); self.assertAlmostEqual(self.calls[1][1], 3 - 1.5)   # budget measured again before the retry
        self.assertEqual(self.status(), {'0': 'acknowledged', '1': 'acknowledged'})
        self.assertEqual([e['event'] for e in log], ['push_retry', 'push_ack']); self.assertEqual(log[1]['attempts'], 2)
        self.assertEqual(log[0]['oldest_age_ms'], 1500.0)

    def test_ambiguous_failures_get_zero_retries(self):
        for k, exc in enumerate((rx.ReadTimeout(), rx.Timeout(), rx.ConnectionError(), rx.HTTPError('500'), TimeoutError('ack lost'), ValueError('?'))):
            self.j.db.execute('DELETE FROM attempts'); self.j.db.commit()
            log = self.send([0.5], [(0.4, exc), (0.3, None)])
            self.assertEqual(len(self.calls), 1, type(exc).__name__)
            self.assertEqual(self.status(), {'0': 'uncertain'})
            self.assertEqual((log[-1]['event'], log[-1]['attempts'], log[-1]['error']), ('push_uncertain', 1, type(exc).__name__))
            self.assertNotIn('retry', log[-1])

    def test_insufficient_budget_gives_up_after_the_first_attempt(self):
        log = self.send([0.4, 1.75], [(0.3, rx.ConnectTimeout()), (0.3, None)])       # oldest is 2.05 s old after the failed connect
        self.assertEqual(len(self.calls), 1); self.assertEqual(self.status(), {'0': 'uncertain', '1': 'uncertain'})
        self.assertEqual(log[-1]['retry'], 'no_budget'); self.assertEqual(log[-1]['attempts'], 1)
        self.j.db.execute('DELETE FROM attempts'); self.j.db.commit()
        log = self.send([1.75], [(0.25, rx.ConnectTimeout()), (0.3, None)])           # exactly 2.0 s: still eligible
        self.assertEqual(len(self.calls), 2); self.assertEqual(log[-1]['event'], 'push_ack')

    def test_repeated_connect_failure_stops_at_two_attempts(self):
        log = self.send([0.5], [(0.3, rx.ConnectTimeout()), (0.3, rx.ConnectTimeout()), (0.3, None)])
        self.assertEqual(len(self.calls), 2); self.assertEqual(self.status(), {'0': 'uncertain'})
        self.assertEqual((log[-1]['event'], log[-1]['attempts'], log[-1]['error'], log[-1]['retry']), ('push_uncertain', 2, 'ConnectTimeout', 'ok'))

    def test_ambiguous_failure_on_the_second_attempt_is_final_and_durable(self):
        log = self.send([0.5], [(0.3, rx.ConnectTimeout()), (0.9, rx.ReadTimeout()), (0.3, None)])
        self.assertEqual(len(self.calls), 2); self.assertEqual(self.status(), {'0': 'uncertain'})
        self.assertEqual((log[-1]['attempts'], log[-1]['error']), (2, 'ReadTimeout'))
        self.ages = {'0': 0.6}; self.calls = []; self.script = [(0.3, None)]
        live.send_answers(self.reqs, self.answers, self.j, set())                     # the same request offered again (next poll, or after a restart)
        # addCleanup runs after tearDown, which already deletes the directory: close the reopened database first
        # so Windows can remove its file, too.
        with closing(Journal(Path(self.tmp.name) / 'j.db')) as j2:
            self.assertEqual(self.calls, []); self.assertTrue(j2.contains('0')); self.assertFalse(j2.claim(self.answers[0]))

    def test_at_most_one_accepted_submission_over_every_two_step_outcome(self):
        """A fake server that accepts whatever reaches it: an attempt 'reaches' it unless it failed with ConnectTimeout."""
        outcomes = [None, rx.ConnectTimeout(), rx.ReadTimeout(), rx.ConnectionError(), rx.HTTPError('502')]
        for a in outcomes:
            for b in outcomes:
                self.j.db.execute('DELETE FROM attempts'); self.j.db.commit()
                self.send([0.5], [(0.3, a), (0.3, b), (0.3, None)])
                reached = [k for k, e in enumerate([a, b][:len(self.calls)]) if not isinstance(e, rx.ConnectTimeout)]
                self.assertLessEqual(len(reached), 1, (a, b))
                self.assertLessEqual(len(self.calls), 2)

    def test_retry_age_zero_disables_and_the_value_is_clamped(self):
        live.CONNECT_RETRY_AGE = 0.0
        self.send([0.2], [(0.3, rx.ConnectTimeout()), (0.3, None)]); self.assertEqual(len(self.calls), 1)
        f = live.connect_retry_age
        self.assertEqual([f(None), f(''), f('0'), f('1.5'), f('9'), f('-1'), f('x'), f('nan')], [2.0, 2.0, 0.0, 1.5, 2.2, 0.0, 2.0, 2.0])

    def test_dry_run_never_posts_claims_or_retries(self):
        self.send([0.5], [(0.3, rx.ConnectTimeout()), (0.3, None)], dry=True)
        self.assertEqual(self.calls, []); self.assertEqual(self.status(), {})

    def test_no_adapter_level_retries(self):
        for s in (requests.Session(), live.ReadOnlySession()):
            for adapter in s.adapters.values():
                self.assertEqual(adapter.max_retries.total, 0); self.assertFalse(adapter.max_retries.read)

    def test_dry_run_transport_refuses_the_post_before_the_network(self):
        with self.assertRaises(PermissionError):
            live.ReadOnlySession().post('https://example.invalid/v1/tables/submissions', json=[{}], timeout=(0.1, 0.1))


if __name__ == '__main__':
    unittest.main()
