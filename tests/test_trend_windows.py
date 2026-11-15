"""Optional causal five-minute trend arm; no network or submissions."""
import copy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from recsys import lfm, live, trends
from tests.test_lfm_hot import HOT, build, slate


def counts(tail=False):
    rows = []
    for age in range(39):
        a = (900 if age in (1, 2) else 100) if tail else (300 if age == 0 else 100)
        rows.extend([(age, "a", a, 0, 0), (age, "b", 1000 - a, 0, 0)])
    return pd.DataFrame(rows, columns=["age", "i", "v", "a", "p"])


class DetectorTests(unittest.TestCase):
    def test_fast_detects_onset_and_clears_tail_before_slow(self):
        for tail, fast, slow in ((False, {"A"}, set()), (True, set(), {"A"})):
            c = counts(tail)
            self.assertEqual(set(trends.compute(c, {"a": "A", "b": "B"}, recent=1).hot), fast)
            self.assertEqual(set(trends.compute(c, {"a": "A", "b": "B"}, recent=3).hot), slow)

    def test_both_detectors_share_one_query_and_slow_matches_incumbent(self):
        c = counts(); calls = []
        result = trends.window_snapshots(lambda sql: calls.append(sql) or c.to_dict("records"),
                                         {"a": "A", "b": "B"}, now="2026-11-14 13:35:00")
        self.assertEqual(len(calls), 1)
        self.assertIn("INTERVAL 195 MINUTE", calls[0])
        self.assertEqual(result[15].sub_lift, trends.compute(c, {"a": "A", "b": "B"}).sub_lift)
        self.assertEqual(result[5].hot, ["A"])

    def test_failure_empty_and_invalid_window_are_safe(self):
        for query in (lambda sql: [], lambda sql: (_ for _ in ()).throw(RuntimeError("offline"))):
            self.assertTrue(all(not s.hot for s in trends.window_snapshots(query, {}).values()))
        for windows in ((), (True,), (10,), ("5",)):
            with self.assertRaises(ValueError): trends.window_snapshots(lambda sql: [], {}, windows)


class FastArmTests(unittest.TestCase):
    @staticmethod
    def pair():
        weights = {"known": {"hot": 6.0}, "new": {"hot": 6.0}}
        return [{"tag": "off"}, {"tag": "slow", "w": weights},
                {"tag": "fast", "w": weights, "trend_window": 5}]

    def test_fast_mask_is_independent_and_missing_never_uses_slow_mask(self):
        lf, aff = build(hot=HOT, arms=self.pair())
        self.assertTrue(lf.wants_fast_hot())
        self.assertEqual(slate(lf, aff, "fast"), slate(lf, aff, "off"))
        self.assertNotEqual(slate(lf, aff, "slow"), slate(lf, aff, "fast"))
        S = lf.snap
        lf.set_catalog(pd.DataFrame({"category": ["A"] * len(S.ids),
                       "sub": ["s"] * len(S.ids), "brand": ["b"] * len(S.ids),
                       "price": [20.0] * len(S.ids)}, index=S.ids), set(), aff, hot_fast=HOT)
        for new in (False, True):
            self.assertEqual(slate(lf, aff, "slow", new=new), slate(lf, aff, "off", new=new))
            self.assertTrue(HOT <= set(slate(lf, aff, "fast", new=new)))
        with self.assertRaises(ValueError): lf.snap.hot_fast[0] = 1

    def test_stalled_refresh_expires_both_signals(self):
        with patch.object(lfm.time, "monotonic", return_value=100):
            lf, aff = build(hot=HOT, arms=self.pair())
            lf.snap.hot_fast = lf.snap.hot.copy()
        with patch.object(lfm.time, "monotonic", return_value=100 + lfm.HOT_TTL_S + 1):
            self.assertEqual(slate(lf, aff, "fast"), slate(lf, aff, "off"))
            self.assertEqual(slate(lf, aff, "slow"), slate(lf, aff, "off"))

    def test_hot_reload_installs_marker_and_preserves_existing_validation(self):
        arms = self.pair()
        self.assertEqual(live.clean_lfm_arms(arms), arms)
        lf, _ = build(arms=arms)
        saved = live.LF, copy.deepcopy(live.POLICY)
        try:
            live.LF = lf
            live.publish_policy(live.check_policy({"variant": "lfm", "lfm_arms": arms}))
            self.assertIn("fast" + lfm.FAST_HOT, lf.alt)
            for value in (True, "5", 10, 5.0):
                bad = copy.deepcopy(arms); bad[-1]["trend_window"] = value
                with self.assertRaises(live.PolicyRejected): live.check_policy({"lfm_arms": bad})
        finally:
            live.LF = saved[0]; live.POLICY.clear(); live.POLICY.update(saved[1])

    def test_only_requested_fast_detector_uses_shared_query(self):
        lf, _ = build(arms=self.pair()); cat = pd.DataFrame({"sub": ["A", "B"]}, index=["a", "b"])
        with patch.object(live, "LF", lf), patch.object(trends, "window_snapshots", return_value={
            15: trends.Snapshot(hot=["A"]), 5: trends.Snapshot()}) as shared:
            self.assertEqual(live.hot_snapshots(cat, max_share=1), ({"a"}, None))
            shared.assert_called_once()
        lf.set_arms([{"tag": "off"}])
        with patch.object(live, "LF", lf), patch.object(live, "hot_products", return_value=None) as legacy:
            self.assertEqual(live.hot_snapshots(cat), (None, None)); legacy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
