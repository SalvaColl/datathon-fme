import json, os, sys, tempfile, unittest
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recsys"))
import home_arms as ha


def catalog(n_cat=10, per=8):
    rows = [(f"p{c}_{k}", f"c{c}", f"s{c}_{k % 3}") for c in range(n_cat) for k in range(per)]
    return pd.DataFrame(rows, columns=["product_id", "category", "sub"]).set_index("product_id")


def items(cat, views=100, buys=lambda i: 1):
    return pd.DataFrame({"it_v": views, "it_a": 0, "it_p": [buys(i) for i in range(len(cat))]}, index=cat.index, dtype=float)


class HomeArms(unittest.TestCase):
    def setUp(self):
        ha._lists.clear(); ha._snaps.clear(); ha._state.update(arms=[], salt="h1", mtime=None, checked=0.0, errors=0)
        self.cat = catalog()

    def test_lists_are_distinct_and_skip_unavailable(self):
        out = ha.rebuild(self.cat, {"p0_0"}, items(self.cat), items(self.cat, buys=lambda i: i % 5), now=0)
        for arm in ha.ARMS:
            self.assertEqual(len(out[arm]), len(set(out[arm]))); self.assertNotIn("p0_0", out[arm]); self.assertGreaterEqual(len(out[arm]), 10)

    def test_catbest_starts_with_one_product_per_category(self):
        out = ha.rebuild(self.cat, set(), None, items(self.cat, buys=lambda i: i % 7), now=0)
        self.assertEqual(len({self.cat.category[p] for p in out["catbest"][:10]}), 10)

    def test_conv_and_trend_cap_per_subcategory(self):
        out = ha.rebuild(self.cat, set(), items(self.cat, buys=lambda i: 50 if i < 8 else 0), None, now=0)
        subs = pd.Series([self.cat["sub"][p] for p in out["conv"]]).value_counts()
        self.assertLessEqual(subs.max(), ha.MAX_PER_SUB)

    def test_trend_uses_the_window_delta(self):
        ha.rebuild(self.cat, set(), None, items(self.cat, buys=lambda i: 10), now=0)
        later = items(self.cat, buys=lambda i: 10); later.loc["p3_1", "it_p"] = 40
        out = ha.rebuild(self.cat, set(), None, later, now=600)
        self.assertEqual(out["trend"][0], "p3_1")

    def test_trend_window_drops_old_snapshots(self):
        for t in range(0, 4000, 500): ha.rebuild(self.cat, set(), None, items(self.cat), now=t)
        self.assertLessEqual(3500 - ha._snaps[0][0], ha.WINDOW_MIN * 60 + 500)

    def test_slate_filters_per_shopper_and_fails_closed(self):
        ha.rebuild(self.cat, set(), None, items(self.cat, buys=lambda i: i % 7), now=0)
        first = ha._lists["catbest"][0]
        s = ha.slate("catbest", "u", blocked={first}, is_dead=lambda u, p: p.endswith("_1"))
        self.assertEqual(len(set(s)), 10); self.assertNotIn(first, s); self.assertFalse(any(p.endswith("_1") for p in s))
        self.assertIsNone(ha.slate("catbest", "u", blocked=set(self.cat.index[5:])))
        self.assertIsNone(ha.slate("nope", "u"))

    def test_arm_split_is_stable_and_off_by_default(self):
        self.assertEqual(ha.arm_of("u1", []), "control")
        arms = ["control", "trend", "catbest", "conv"]
        got = [ha.arm_of(f"u{i}", arms, "h1") for i in range(2000)]
        self.assertEqual(got, [ha.arm_of(f"u{i}", arms, "h1") for i in range(2000)])
        for a in arms: self.assertGreater(got.count(a), 400)

    def test_policy_file_validation(self):
        with tempfile.TemporaryDirectory() as d:
            old = ha.POLICY; ha.POLICY = os.path.join(d, "home_arms.json")
            try:
                self.assertEqual(ha.read_policy(now=10), [])
                json.dump({"arms": ["control", "trend"], "salt": "x"}, open(ha.POLICY, "w"))
                self.assertEqual(ha.read_policy(now=20), ["control", "trend"]); self.assertEqual(ha._state["salt"], "x")
                json.dump({"arms": ["control", "bogus"]}, open(ha.POLICY, "w")); os.utime(ha.POLICY, (1, 1))
                self.assertEqual(ha.read_policy(now=30), [])
                os.remove(ha.POLICY); self.assertEqual(ha.read_policy(now=40), [])
            finally: ha.POLICY = old

    def test_install_swaps_only_home_non_control_and_survives_errors(self):
        class T:
            def __init__(s, f): s.f = f
            def item_frame(s): return s.f
        cat = self.cat
        def o_predict(reqs): return [{"request_id": r["request_id"], "items": ["x"] * 10, "model_version": "orig"} for r in reqs]
        g = {"make_pools": lambda c, u, T: ("pools", "best"), "predict": o_predict, "state": {"unavail": set(), "stock_out": {"p1_0"}},
             "BASE": {"item": items(cat)}, "BOUGHT": {"ub": {"p2_0"}}}
        ha.install(g)
        self.assertEqual(g["make_pools"](cat, set(), T(items(cat, buys=lambda i: i % 7))), ("pools", "best"))
        reqs = [{"request_id": f"r{i}", "user_id": f"u{i}", "rv": [], "is_new_user": i % 2 == 0} for i in range(40)]
        reqs += [{"request_id": "rv", "user_id": "u1", "rv": ["p0_0"], "is_new_user": False}, {"request_id": "rb", "user_id": "ub", "rv": [], "is_new_user": False}]
        self.assertTrue(all(a["model_version"] == "orig" for a in g["predict"](reqs)))        # off by default
        ha._state.update(arms=["control", "catbest"], checked=1e18)
        out = {a["request_id"]: a for a in g["predict"](reqs)}
        self.assertEqual(out["rv"]["model_version"], "orig")
        swapped = [a for a in out.values() if a["model_version"].startswith("hx-")]
        self.assertTrue(0 < len(swapped) < 41)
        for a in swapped:
            self.assertEqual(len(set(a["items"])), 10); self.assertNotIn("p1_0", a["items"]); self.assertIn(a["model_version"], ("hx-catbest-k", "hx-catbest-n"))
        ha._state.update(arms=["catbest"]); self.assertNotIn("p2_0", {a["request_id"]: a for a in g["predict"](reqs)}["rb"]["items"])
        ha._lists["catbest"] = None                                                         # broken state -> original answers
        self.assertTrue(all(a["model_version"] == "orig" for a in g["predict"](reqs)))


if __name__ == "__main__":
    unittest.main()
