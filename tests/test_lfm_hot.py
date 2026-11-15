"""T-044: lfm feature `hot` (product of a subcategory in a live burst) and the arm that weights it."""
import unittest
import pandas as pd

from recsys import lfm, live, trends
from tests.test_lfm import FakeAff, catalog, COEF, HIST

HOT = {'A38', 'A39', 'B39'}                       # worst quality of the fixture: never in a slate on their own
ARMS = [{"tag": "r3"}, {"tag": "t15", "w": {"known": {"hot": 6.0}, "new": {"hot": 6.0}}}]


def build(hot=HOT, arms=ARMS):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_arms(arms)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, hot=hot)
    return lf, aff


def slate(lf, aff, model, rv=('A30',), new=False, page='product'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state('u9'), aff, model=model)


class HotTests(unittest.TestCase):
    def test_feature_position_and_committed_weights_are_zero(self):
        self.assertEqual(lfm.FEATS.index("hot"), 22)
        lf, _ = build()
        self.assertEqual(float(lf.w["known"][22]), 0.0); self.assertEqual(float(lf.w["new"][22]), 0.0)

    def test_control_is_identical_with_and_without_a_burst(self):
        a, aff = build(); b, aff2 = build(hot=None)
        for kw in (dict(), dict(new=True), dict(page='home', rv=()), dict(page='category')):
            self.assertEqual(slate(a, aff, "r3", **kw), slate(b, aff2, "r3", **kw))
        self.assertIsNone(b.snap.hot)
        self.assertEqual(slate(b, aff2, "t15"), slate(b, aff2, "r3"))             # nothing hot: the arm serves the control's slate
        c, aff3 = build(hot=set()); self.assertIsNone(c.snap.hot)

    def test_arm_brings_hot_products_for_every_shopper_and_page(self):
        lf, aff = build()
        for kw in (dict(), dict(new=True), dict(page='home', rv=())):
            self.assertFalse(HOT & set(slate(lf, aff, "r3", **kw)))
            s = slate(lf, aff, "t15", **kw)
            self.assertTrue(HOT <= set(s)); self.assertEqual(len(set(s)), 10)

    def test_wants_hot_only_when_an_arm_weights_it(self):
        lf, _ = build(); self.assertTrue(lf.wants_hot())
        lf.set_arms([{"tag": "r3"}]); self.assertFalse(lf.wants_hot())
        lf.set_arms([]); self.assertFalse(lf.wants_hot())

    def test_policy_accepts_the_arm(self):
        arms = [{"tag": "t15", "file": "lfm_coef_r3.json", "w": {"known": {"hot": 1.5}, "new": {"hot": 1.5}}}]
        self.assertEqual(live.clean_lfm_arms(arms), arms)

    def test_hot_products_asks_only_when_needed_and_fails_closed(self):
        cat = catalog(); lf, _ = build(); old = (live.LF, live.query, trends.snapshot)
        calls = []
        try:
            live.LF = lf
            sub = cat["sub"].iloc[0]
            trends.snapshot = lambda q, sub_of, now=None: calls.append(1) or trends.Snapshot(hot=[sub], sub_of=sub_of)
            out = live.hot_products(cat, max_share=1.0)
            self.assertEqual(out, set(cat.index[cat["sub"] == sub])); self.assertEqual(len(calls), 1)
            self.assertIsNone(live.hot_products(cat, max_share=0.0001))           # implausibly large set: ignored
            trends.snapshot = lambda q, sub_of, now=None: trends.Snapshot(hot=[], sub_of=sub_of)
            self.assertIsNone(live.hot_products(cat))
            def boom(*a, **k): raise RuntimeError("x")
            trends.snapshot = boom
            self.assertIsNone(live.hot_products(cat))
            lf.set_arms([{"tag": "r3"}]); calls.clear()
            trends.snapshot = lambda q, sub_of, now=None: calls.append(1) or trends.Snapshot(hot=[sub], sub_of=sub_of)
            self.assertIsNone(live.hot_products(cat)); self.assertEqual(calls, [])   # no arm asks: no query at all
        finally:
            live.LF, live.query, trends.snapshot = old


if __name__ == "__main__":
    unittest.main()
