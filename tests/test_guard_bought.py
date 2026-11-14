import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recsys"))
import live


class GuardBoughtTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.LF, dict(live.BOUGHT)); live.LF = None; live.BOUGHT.clear()
        self.best = ["p%02d" % k for k in range(30)]; self.active = set(self.best) | {"x1", "x2"}

    def tearDown(self):
        live.LF = self.saved[0]; live.BOUGHT.clear(); live.BOUGHT.update(self.saved[1])

    def test_valid_slate_untouched(self):
        items = self.best[5:15]; live.BOUGHT["u"].add("p05")
        self.assertIs(live.repair_for("u", items, self.best, self.active), items)

    def test_filler_skips_bought_from_all_sources(self):
        class FakeLF: hbought = {"u": {"p00"}}; lbought = {"u": {"p01"}}
        live.LF = FakeLF(); live.BOUGHT["u"].add("p02")
        out = live.repair_for("u", ["x1", "gone"], self.best, self.active)
        self.assertEqual(out[:4], ["x1", "p03", "p04", "p05"]); self.assertEqual(len(set(out)), 10)
        self.assertEqual(live.repair_for("other", None, self.best, self.active), self.best[:10])

    def test_fallback_answers_skip_bought(self):
        live.BOUGHT["u"].add("p00")
        old = live.snapshot; live.snapshot = lambda: (None, set(), None, None, self.best)
        try: out = live.fallback_answers([{"request_id": "r1", "user_id": "u"}, {"request_id": "r2", "user_id": "v"}])
        finally: live.snapshot = old
        self.assertNotIn("p00", out[0]["items"]); self.assertEqual(out[1]["items"], self.best[:10])

    def test_falls_back_when_too_few_left(self):
        live.BOUGHT["u"].update(self.best[:25])
        self.assertEqual(len(live.repair_for("u", [], self.best, set(self.best))), 10)


if __name__ == "__main__":
    unittest.main()
