"""tools/final_watch.py: its guard arithmetic must agree with the writer's own fail-closed guards (live.new_products,
live.hot_products' share rule, lfm.organic_quality). No network."""
import unittest

import pandas as pd

from recsys import lfm, live
from tools import final_watch as fw


class GuardTests(unittest.TestCase):
    def writer_new(self, n_base, n_launched):
        cat = pd.DataFrame(index=[f"b{k}" for k in range(n_base)] + [f"n{k}" for k in range(n_launched)])
        saved = live.QR
        try:
            live.QR = type("QR", (), {"q": {f"b{k}": 0.01 for k in range(n_base)}})()
            return live.new_products(cat) is not None
        finally: live.QR = saved

    def test_launched_guard_matches_the_writer_on_both_sides_of_the_limit(self):
        for base in (40, 99, 300, 5000):
            g = fw.launched_guard(base, 1); lim = g["limit"]
            for n in (0, 1, lim - 1, lim, lim + 1, base):
                if n < 0: continue
                self.assertEqual(fw.launched_guard(base, n)["on"], self.writer_new(base, n), (base, n))
            self.assertEqual(fw.launched_guard(base, lim)["room"], 0)
        g = fw.launched_guard(5000, 600)
        self.assertEqual((g["on"], g["limit"], g["room"]), (True, 1666, 1066))          # the catalogue at 08:00 UTC, 15 Nov

    def test_quality_guard_matches_organic_quality(self):
        new = [f"n{k}" for k in range(60)]
        cases = [({p: (0.0, 0.0) for p in new}, set(), "off"),                           # 60 unseen products, no history
                 ({p: (20.0, 1.0) for p in new}, set(), "orate_only"),                   # no history, but the stream has views
                 ({p: (20.0, 1.0) for p in new}, set(new), "full")]
        for oq, hist, mode in cases:
            r, pop = lfm.organic_quality(new, oq, hist=hist)
            g = fw.quality_guard(len(hist), sum(1 for v, _ in oq.values() if v > 0))
            self.assertEqual(g["mode"], mode); self.assertEqual(g["on"], r is not None)
            if mode == "orate_only": self.assertFalse(pop.any())

    def test_hot_guard(self):
        self.assertTrue(fw.hot_guard(5600, 0)["calm"]); self.assertTrue(fw.hot_guard(5600, 560)["on"])
        self.assertFalse(fw.hot_guard(5600, 561)["on"])

    def test_health_alarm_and_render(self):
        ok = fw.health([dict(s="team", f="", n=900, p95=2000, p99=2500)], 900)
        self.assertFalse(ok["alarm"]); self.assertEqual(ok["team_share"], 1.0)
        bad = fw.health([dict(s="team", f="", n=800, p95=2000, p99=2500), dict(s="fallback", f="missing", n=100, p95=0, p99=0)], 900)
        self.assertTrue(bad["alarm"]); self.assertEqual(bad["fallback"], {"missing": 100})
        self.assertTrue(fw.health([], 900)["alarm"])                                      # requests but no feedback at all
        self.assertFalse(fw.health([], 0)["alarm"])                                       # quiet stream is not an alarm
        txt = fw.render(dict(guards=[fw.launched_guard(5000, 1700), fw.quality_guard(0, 10), fw.hot_guard(5600, 900)],
                             lag_s=dict(now="x", events=1, requests=1, catalog_updates=9, feedback=120), health=bad, minutes=5))
        for s in ("newp / newph / newcap are OFF", "orate / opop degraded", "trend feature is OFF", "writer or network", "ALARM"):
            self.assertIn(s, txt)


if __name__ == "__main__":
    unittest.main()
