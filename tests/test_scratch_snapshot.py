import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import scratch_snapshot as S


class ScratchSnapshot(unittest.TestCase):
    def test_windows_are_complete_and_aligned(self):
        now = 1794727163                                        # 07:19:23 UTC
        ws = S.windows(now, 6)
        self.assertEqual(len(ws), 24)
        self.assertTrue(all(a % 900 == 0 and b - a == 900 for a, b in ws))
        self.assertEqual(S.fmt(ws[-1][1]), '2026-11-15 07:15:00')
        self.assertLessEqual(ws[-1][1], now - 120)
        self.assertEqual(S.fmt(S.windows(1794726060, 1)[-1][1]), '2026-11-15 06:45:00')   # 07:01:00, 07:00 not settled yet

    def test_segment(self):
        self.assertEqual(S.segment(True, 'home'), 'new_home')
        self.assertEqual(S.segment('false', 'product'), 'known_page')
        self.assertEqual(S.segment('true', 'category'), 'new_page')

    def test_build_rows(self):
        m = [dict(w=1794726000, seg='', requests=2700, on_time=2699, guard=-1, p50=1230.0, p95=1950.44, purchases=55, clicks=160),
             dict(w=1794726000, seg='new_page', requests=600, on_time=600, guard=3, p50=1200, p95=float('nan'), purchases=20, clicks=40),
             dict(w=1794726000, seg='new_home', requests=0, on_time=0, guard=-1, p50=None, p95=None, purchases=0, clicks=0)]
        v = [dict(w=1794726000, mv='maaaaa', n=2000), dict(w=1794726000, mv='mbbbbb', n=699)]
        rows = S.build_rows(m, v, 1794727163)
        self.assertEqual(len(rows), 3)
        a = rows[0]
        self.assertEqual((a['kind'], a['segment'], a['window_start'], a['window_end']), ('metrics_15m', 'all', '2026-11-15 07:00:00', '2026-11-15 07:15:00'))
        self.assertEqual((a['fallback'], a['on_time_share'], a['latency_p95_ms']), (1, 0.99963, 1950.4))
        self.assertNotIn('guard', a)
        self.assertEqual((rows[1]['guard'], rows[1]['guard_share'], rows[1]['latency_p95_ms']), (3, 0.005, None))
        p = rows[2]
        self.assertEqual((p['kind'], p['n_versions'], p['requests']), ('policy_versions', 2, 2699))
        self.assertEqual(json.loads(p['versions']), {'maaaaa': 2000, 'mbbbbb': 699})
        for r in rows:
            for k in ('kind', 'ts', 'window_start', 'window_end'): self.assertIn(k, r)
            json.dumps(r)

    def test_missing_is_idempotent(self):
        rows = S.build_rows([dict(w=1794726000, seg='', requests=10, on_time=10, guard=-1, p50=1, p95=2, purchases=0, clicks=0)], [], 1794727163)
        self.assertEqual(len(S.missing(rows + rows, set())), 1)
        self.assertEqual(S.missing(rows, {S.key(rows[0])}), [])
        self.assertEqual(S.missing(rows, {('metrics_15m', '2026-11-15 07:00:00.000', 'all')[:1] + ('2026-11-15 07:00:00', 'all')}), [])

    def test_only_scratch_is_writable(self):
        with self.assertRaises(PermissionError): S.insert([{'kind': 'x'}], table='submissions')

    def test_sql_shape(self):
        s = S.metrics_sql('team_26', 1794726000, 1794726900, 'm12345')
        self.assertIn('team_26.feedback', s); self.assertIn("'m12345'", s); self.assertNotIn('submissions', s)
        with self.assertRaises(ValueError): S.metrics_sql('team_26', 1, 2, "x' OR 1=1")


if __name__ == '__main__':
    unittest.main()
