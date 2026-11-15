"""T-063: watchdog thresholds are pure functions; no network here."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import watchdog as W


def minute(n=180, missing=0, invalid=0, guard=0):
    return dict(n=n, team=n - missing - invalid, missing=missing, invalid=invalid, guard=guard, purchases=0)


def healthy(**over):
    m = dict(hb_team_s=1.4, hb_any_s=1.4, minutes=[minute() for _ in range(5)],
             window=dict(n=900, team=900, missing=0, invalid=0, guard=1, minutes=5),
             latency=dict(p50=1300.0, p95=2000.0, p99=2400.0),
             conversion=W.conversion_check(110, 5400, 350, 16200))
    m.update(over)
    return m


def codes(v):
    return {r['code'] for r in v['reasons']}


class Wilson(unittest.TestCase):
    def test_interval_contains_the_rate_and_narrows_with_n(self):
        lo, hi = W.wilson(20, 1000)
        self.assertTrue(lo < 0.02 < hi)
        lo2, hi2 = W.wilson(200, 10000)
        self.assertLess(hi2 - lo2, hi - lo)

    def test_edges(self):
        self.assertEqual(W.wilson(0, 0), (0.0, 1.0))
        lo, hi = W.wilson(0, 900)
        self.assertAlmostEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)


class Conversion(unittest.TestCase):
    def test_minimum_sample_is_far_above_a_five_minute_window(self):
        for rate in (0.005, 0.01, 0.02, 0.03, 0.05, 0.2, 0.0, 1.0):
            self.assertGreaterEqual(W.min_conversion_sample(rate), 2000)       # 5 minutes = ~900 requests
        self.assertGreater(W.min_conversion_sample(0.02), 3000)

    def test_five_minutes_never_recommend_a_rollback_even_with_zero_purchases(self):
        for purchases in (0, 1, 5, 18):
            c = W.conversion_check(purchases, 900, 215 * 2, 21600)
            self.assertFalse(c['enough_sample'])
            self.assertFalse(c['rollback'])
            self.assertNotIn('conversion_drop', codes(W.evaluate(healthy(conversion=c))))

    def test_large_clear_drop_is_flagged_as_warn_only(self):
        c = W.conversion_check(20, 5400, 350, 16200)        # 0.37% against 2.16%
        self.assertTrue(c['rollback'])
        v = W.evaluate(healthy(conversion=c))
        self.assertEqual(v['level'], W.WARN)
        self.assertIn('conversion_drop', codes(v))

    def test_normal_noise_with_enough_sample_is_not_flagged(self):
        self.assertFalse(W.conversion_check(100, 5400, 350, 16200)['rollback'])     # 1.85% against 2.16%

    def test_thin_baseline_blocks_the_alarm(self):
        self.assertFalse(W.conversion_check(0, 5400, 40, 2000)['rollback'])


class FastAlarms(unittest.TestCase):
    def test_healthy_is_ok(self):
        v = W.evaluate(healthy())
        self.assertEqual((v['level'], v['reasons']), (W.OK, []))
        self.assertEqual(W.exit_code(v['level']), 0)

    def test_writer_silent_while_fallback_rows_arrive_is_critical(self):
        v = W.evaluate(healthy(hb_team_s=25.0, hb_any_s=1.5))
        self.assertEqual(v['level'], W.CRITICAL)
        self.assertIn('writer_silent', codes(v))
        self.assertEqual(W.exit_code(v['level']), 2)

    def test_no_team_row_at_all_is_critical(self):
        self.assertIn('writer_silent', codes(W.evaluate(healthy(hb_team_s=None, hb_any_s=1.5))))

    def test_whole_feedback_stale_is_warn_not_critical(self):
        v = W.evaluate(healthy(hb_team_s=40.0, hb_any_s=40.0))
        self.assertEqual(v['level'], W.WARN)
        self.assertEqual(codes(v), {'feedback_stale'})

    def test_slow_heartbeat_is_warn(self):
        v = W.evaluate(healthy(hb_team_s=12.0, hb_any_s=1.5))
        self.assertEqual((v['level'], codes(v)), (W.WARN, {'writer_slow'}))

    def test_one_bad_minute_is_warn_two_are_critical(self):
        one = [minute(missing=30)] + [minute() for _ in range(4)]
        v = W.evaluate(healthy(minutes=one, window=dict(n=900, missing=30, invalid=0, guard=0, minutes=5)))
        self.assertEqual(v['level'], W.WARN)
        two = [minute(missing=30), minute(missing=20)] + [minute() for _ in range(3)]
        v = W.evaluate(healthy(minutes=two, window=dict(n=900, missing=50, invalid=0, guard=0, minutes=5)))
        self.assertEqual(v['level'], W.CRITICAL)
        self.assertIn('missing_sustained', codes(v))

    def test_an_old_bad_minute_does_not_stay_critical(self):
        old = [minute(), minute(), minute(missing=60), minute(missing=60), minute()]
        v = W.evaluate(healthy(minutes=old, window=dict(n=900, missing=120, invalid=0, guard=0, minutes=5)))
        self.assertEqual(v['level'], W.WARN)

    def test_baseline_noise_does_not_alarm(self):
        m = [minute(), minute(missing=3, guard=5)] + [minute() for _ in range(3)]
        v = W.evaluate(healthy(minutes=m, window=dict(n=900, missing=3, invalid=0, guard=5, minutes=5)))
        self.assertEqual(v['level'], W.OK)

    def test_nearly_empty_minutes_are_not_evidence(self):
        self.assertFalse(W.consecutive_over([minute(n=10, missing=10), minute(n=10, missing=10)], 'missing', 0.05, 2, 60))
        self.assertFalse(W.consecutive_over([minute(missing=30)], 'missing', 0.05, 2, 60))

    def test_invalid_and_guard(self):
        bad = [minute(invalid=10), minute(invalid=10)] + [minute() for _ in range(3)]
        self.assertIn('invalid_sustained', codes(W.evaluate(healthy(minutes=bad))))
        v = W.evaluate(healthy(window=dict(n=900, missing=0, invalid=0, guard=40, minutes=5)))
        self.assertEqual((v['level'], codes(v)), (W.WARN, {'guard_share'}))

    def test_latency_levels(self):
        self.assertEqual(W.evaluate(healthy(latency=dict(p50=1300, p95=2000, p99=2600)))['level'], W.OK)
        self.assertEqual(codes(W.evaluate(healthy(latency=dict(p50=1300, p95=2450, p99=2600)))), {'p95_high'})
        self.assertEqual(codes(W.evaluate(healthy(latency=dict(p50=1300, p95=2450, p99=2750)))), {'p99_high'})
        v = W.evaluate(healthy(latency=dict(p50=1300, p95=2450, p99=2950)))
        self.assertEqual((v['level'], codes(v)), (W.CRITICAL, {'p99_deadline'}))

    def test_low_volume(self):
        v = W.evaluate(healthy(window=dict(n=400, missing=0, invalid=0, guard=0, minutes=5)))
        self.assertEqual(codes(v), {'low_volume'})


class Collect(unittest.TestCase):
    """collect() with a canned query function: bucket arithmetic, windows and the read-only guard."""
    def fake(self, sql):
        self.sqls.append(sql)
        if 'any_ts' in sql:
            return [dict(now='2026-11-15 08:00:10.000', any_ts='2026-11-15 08:00:08.500', team_ts='2026-11-15 08:00:08.000', n=5400)]
        if 'GROUPING SETS' in sql:
            return [dict(seg='recent', version='', n=900, purchases=18, q=[1300.0, 2000.0, 2400.0]),
                    dict(seg='recent', version='mA', n=897, purchases=18, q=[1300.0, 2000.0, 2400.0]),
                    dict(seg='recent', version='(fallback:missing)', n=3, purchases=0, q=[None, None, None]),
                    dict(seg='baseline', version='', n=7200, purchases=150, q=[1290.0, 1990.0, 2350.0])]
        return [dict(b=b, n=180, team=180 - (3 if b == 1 else 0), missing=3 if b == 1 else 0, invalid=0, guard=0,
                     purchases=4) for b in range(120) if b != 7]

    def test_metrics(self):
        self.sqls = []
        m = W.collect(self.fake, 'team_x', guard_labels=("m1'; DROP", 'm2'))
        self.assertEqual((m['hb_team_s'], m['hb_any_s']), (2.0, 1.5))
        self.assertEqual(m['window'], dict(n=900, team=897, missing=3, invalid=0, guard=0, purchases=20, minutes=5))
        self.assertEqual(m['baseline']['n'], 180 * 39)          # minute 7 is empty
        self.assertEqual(m['minutes'][7]['n'], 0)
        self.assertEqual(m['conversion']['recent']['requests'], 180 * 29)
        self.assertEqual(m['latency']['p99'], 2400.0)
        self.assertEqual([e['version'] for e in m['by_version']], ['mA', '(fallback:missing)'])
        self.assertEqual(W.evaluate(m)['level'], W.OK)
        self.assertTrue(all(s.lstrip().upper().startswith('SELECT') for s in self.sqls))
        self.assertNotIn("'; DROP", ''.join(self.sqls))
        self.assertTrue(all('submissions' not in s for s in self.sqls))

    def test_query_failure_is_a_warn_about_the_watchdog(self):
        def boom(sql):
            raise TimeoutError('x')
        args = W.argparse.Namespace(window=5, baseline=45, conv_window=30, conv_baseline=90, guard_labels='m0312d', settle=8.0)
        v = W.run_once(boom, 'team_x', args)
        self.assertEqual((v['level'], codes(v)), (W.WARN, {'watchdog_query_failed'}))


if __name__ == '__main__':
    unittest.main()
