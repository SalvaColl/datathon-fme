"""Handoff patch 1: --dry-run is enforced by the transport, not only by a flag. No network (requests is mocked)."""
import os
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from recsys import live
from recsys.serving import Journal


class DryRunGuardTests(unittest.TestCase):
    def test_read_only_session_refuses_every_write_before_the_network(self):
        s = live.ReadOnlySession()
        with patch('requests.Session.request') as net:
            for url, body in (('https://api.x/v1/tables/submissions', [{'request_id': 'r'}]),
                              ('https://api.x/v1/query', {'sql': 'INSERT INTO team_26.submissions VALUES (1)'}),
                              ('https://api.x/v1/query', {'sql': '  alter table t delete where 1'}),
                              ('https://api.x/v1/query', None)):
                with self.assertRaises(PermissionError):
                    s.post(url, params={'database': 'team_26'}, json=body)
            net.assert_not_called()
            s.post('https://api.x/v1/query', json={'sql': ' select 1'})
            s.post('https://api.x/v1/query', json={'sql': 'WITH a AS (SELECT 1) SELECT * FROM a'})
            self.assertEqual(net.call_count, 2)

    def test_dry_flag_selects_the_read_only_session_per_thread(self):
        got = []
        with patch.object(live, 'DRY', True), patch.dict(os.environ, {'RAWTREE_API_KEY': 'not-used'}):
            t = threading.Thread(target=lambda: got.append(live.session())); t.start(); t.join()
        self.assertIsInstance(got[0], live.ReadOnlySession)

    def test_even_a_non_dry_send_cannot_post_in_dry_mode(self):
        """Belt and braces: if a code path forgot dry=True, the POST still never leaves the process."""
        cat = pd.DataFrame({'category': ['c'] * 12}, index=[f'p{k}' for k in range(12)])
        snap = (None, set(), cat, None, list(cat.index))
        now = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as tmp, patch.object(live, 'DRY', True), \
                patch.dict(os.environ, {'RAWTREE_API_KEY': 'not-used'}), \
                patch.object(live, 'snapshot', return_value=snap), patch('requests.Session.request') as net:
            done = []
            def run():                                                  # fresh thread -> fresh session()
                journal = Journal(Path(tmp) / 'a.db')
                live.send_answers([{'request_id': 'r1', 'ts': now}],
                                  [{'request_id': 'r1', 'items': list(cat.index[:10]), 'model_version': 'v'}],
                                  journal, set(), dry=False)
                done.append(journal.db.execute('SELECT status FROM attempts').fetchone()[0])
                journal.close()
            t = threading.Thread(target=run); t.start(); t.join()
        net.assert_not_called()
        self.assertEqual(done, ['uncertain'])


if __name__ == '__main__':
    unittest.main()
