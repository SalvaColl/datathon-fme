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
        items = self.best[5:15]; live.BOUGHT["u"].add("p20")          # bought something, but nothing of this slate
        self.assertIs(live.repair_for("u", items, self.best, self.active), items)
        self.assertIs(live.repair_for("nobody", items, self.best, self.active), items)

    def test_full_slate_with_one_bought_is_repaired(self):
        items = self.best[5:15]; live.BOUGHT["u"].add("p07")
        out = live.repair_for("u", items, self.best, self.active)
        self.assertEqual(out, [p for p in items if p != "p07"] + ["p00"])       # order kept, first unbought best fills
        self.assertEqual(items, self.best[5:15])                                # the ranked list itself is not edited

    def test_partial_slate_with_one_bought(self):
        live.BOUGHT["u"].update({"x2", "p00"})
        out = live.repair_for("u", ["x1", "x2", "gone", "p03", "x1"], self.best, self.active)
        self.assertEqual(out, ["x1", "p03", "p01", "p02", "p04", "p05", "p06", "p07", "p08", "p09"])

    def test_three_sources_filter_ranked_products(self):
        class FakeLF: hbought = {"u": {"p05"}}; lbought = {"u": {"p06"}}
        live.LF = FakeLF(); live.BOUGHT["u"].add("p07")
        items = self.best[5:15]
        for src in ("p05", "p06", "p07"): self.assertTrue(live.bought_in("u", [src]))
        self.assertFalse(live.bought_in("u", ["p08"])); self.assertFalse(live.bought_in("other", items))
        out = live.repair_for("u", items, self.best, self.active)
        self.assertEqual(out, self.best[8:15] + self.best[0:3]); self.assertEqual(len(set(out)), 10)
        self.assertIs(live.repair_for("other", items, self.best, self.active), items)

    def test_purchase_known_between_ranking_and_send(self):
        import datetime
        items = self.best[5:15]; r = {"request_id": "r1", "user_id": "u", "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        ans = [{"request_id": "r1", "items": list(items), "model_version": "v3-lfm-r3-k"}]
        cat = type("Cat", (), {"index": list(self.active)})()
        old = (live.snapshot, live.post_batch); sent = []
        live.snapshot = lambda: (None, set(), cat, None, self.best); live.post_batch = lambda batch, remaining: sent.extend(batch)
        class J:
            def claim(self, a): return True
            def finish(self, ids, status): pass
        try:
            live.send_answers([r], ans, J(), set()); untouched = sent.pop()
            live.BOUGHT["u"].add("p09")                                     # the purchase arrives after the ranking
            live.send_answers([r], ans, J(), set()); repaired = sent.pop()
        finally: live.snapshot, live.post_batch = old
        self.assertEqual((untouched["items"], untouched["model_version"]), (items, "v3-lfm-r3-k"))
        self.assertNotIn("p09", repaired["items"]); self.assertEqual(len(set(repaired["items"])), 10)
        self.assertEqual(repaired["items"][:9], [p for p in items if p != "p09"])
        self.assertTrue(repaired["model_version"].endswith("-guard"))

    def test_too_few_unbought_still_sends_ten_valid_and_logs(self):
        import io, json, contextlib
        best = self.best[:12]; active = set(best); live.BOUGHT["u"].update(best[:5]); n0 = live.GUARD_SHORT[0]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): out = live.repair_for("u", best[:10], best, active)
        self.assertEqual(out[:7], best[5:12])                                # every unbought product first, ranked order
        self.assertEqual(len(out), 10); self.assertEqual(len(set(out)), 10); self.assertTrue(set(out) <= active)
        self.assertEqual(live.GUARD_SHORT[0], n0 + 1)
        ev = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual((ev["event"], ev["unbought"], ev["bought_sent"]), ("guard_bought_short", 7, 3))
        with self.assertRaises(ValueError): live.repair_for("u", best[:10], best[:9], set(best[:9]))     # < 10 active: refuse, as before

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
