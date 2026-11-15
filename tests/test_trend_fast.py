"""T-053: fast burst detector (trends.fast_hot) and the feature `hotc` (hot product x burst category in the recent views)."""
import unittest
import numpy as np, pandas as pd

from recsys import lfm, trends
from tests.test_lfm import FakeAff, catalog, COEF, HIST

SUBS = {f"p{k}": f"S{k % 20}" for k in range(200)}                 # 20 subcategories, 10 products each
SHARE = {f"S{k}": 0.05 for k in range(20)}


def recent(hot=None, mult=4.0, per_sub=60):
    """Views of the last 3 minutes: `per_sub` per subcategory, `mult` times that for the hot one."""
    rows = []
    for k in range(20):
        v = per_sub * (mult if f"S{k}" == hot else 1.0)
        rows += [(f"p{k + 20 * j}", v / 10.0) for j in range(10)]
    return pd.DataFrame(rows, columns=["i", "v"])


class FastHotTests(unittest.TestCase):
    def test_calm_stream_flags_nothing(self):
        self.assertEqual(trends.fast_hot(SHARE, recent(), SUBS), [])

    def test_step_of_a_burst_enters(self):
        self.assertEqual(trends.fast_hot(SHARE, recent("S3"), SUBS), ["S3"])

    def test_small_rise_does_not_enter_but_keeps_a_burst_on(self):
        r = recent("S3", mult=1.9)
        self.assertEqual(trends.fast_hot(SHARE, r, SUBS), [])
        self.assertEqual(trends.fast_hot(SHARE, r, SUBS, prev={"S3"}), ["S3"])

    def test_burst_over_leaves_at_once(self):
        self.assertEqual(trends.fast_hot(SHARE, recent(), SUBS, prev={"S3"}), [])

    def test_few_views_never_enter(self):
        self.assertEqual(trends.fast_hot(SHARE, recent("S3", per_sub=4), SUBS), [])

    def test_no_baseline_or_no_views(self):
        self.assertEqual(trends.fast_hot({}, recent("S3"), SUBS), [])
        self.assertEqual(trends.fast_hot(SHARE, recent("S3").iloc[:0], SUBS), [])
        self.assertEqual(trends.fast_hot(SHARE, pd.DataFrame([("zz", 500.0)], columns=["i", "v"]), SUBS), [])

    def test_snapshot_uses_fast_path_and_survives_its_failure(self):
        base = [dict(age=a, i=p, v=6, a=0, p=0) for a in range(3, 39) for p in SUBS] + [dict(age=a, i=p, v=6, a=0, p=0) for a in range(3) for p in SUBS]
        calls = []
        def q(sql):
            calls.append(sql)
            if "GROUP BY age" in sql: return base
            return recent("S7").to_dict("records")
        trends._PREV = set()
        self.assertEqual(trends.snapshot(q, SUBS, now="2026-11-15 01:32:00").hot, ["S7"])
        self.assertEqual(len(calls), 2); self.assertEqual(trends._PREV, {"S7"})
        def bad(sql):
            if "GROUP BY age" in sql: return base
            raise RuntimeError("timeout")
        self.assertEqual(trends.snapshot(bad, SUBS, now="2026-11-15 01:32:00").hot, [])      # the 15-minute rule's answer
        self.assertEqual(trends.snapshot(q, SUBS, now="2026-11-15 01:32:00", fast=False).hot, [])


HOT = {'A38', 'A39', 'B38', 'B39'}


def build(arms, hot=HOT):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, hot=hot)
    return lf, aff, cat


def slate(lf, aff, model, rv=('A30',), new=False, page='product'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state('u9'), aff, model=model)


class HotContextTests(unittest.TestCase):
    ARMS = [{"tag": "r3"}, {"tag": "tc", "w": {"known": {"hotc": 9.0}, "new": {"hotc": 9.0}}}]

    def test_position_and_committed_weights(self):
        self.assertEqual(lfm.FEATS.index("hotc"), 25); self.assertEqual(lfm.FEATS.index("hot"), 22)
        lf, _, _ = build(self.ARMS)
        self.assertEqual(float(lf.w["known"][25]), 0.0); self.assertEqual(float(lf.w["new"][25]), 0.0)
        self.assertTrue(lf.wants_hot())
        lf2, _, _ = build([{"tag": "r3"}]); self.assertFalse(lf2.wants_hot())

    def test_only_hot_products_of_a_category_in_the_recent_views(self):
        lf, aff, cat = build(self.ARMS)
        S = lf.snap; rv = ['A30']
        X = lfm.features(S, aff.affinity_all('u9', rv), rv, 'product', {}, [])
        on = {S.ids[k] for k in np.flatnonzero(X[:, 25])}
        same = {p for p in HOT if cat.at[p, "category"] == cat.at['A30', "category"]}
        self.assertTrue(same); self.assertEqual(on, same); self.assertLess(len(on), len(HOT))
        X0 = lfm.features(S, aff.affinity_all('u9', []), [], 'home', {}, [])
        self.assertEqual(float(X0[:, 25].sum()), 0.0)                              # no views: no context
        self.assertEqual(float(X0[:, 22].sum()), float(len(HOT)))                  # `hot` itself is untouched

    def test_arm_moves_context_shoppers_only(self):
        lf, aff, cat = build(self.ARMS)
        same = {p for p in HOT if cat.at[p, "category"] == cat.at['A30', "category"]}
        s = slate(lf, aff, "tc"); self.assertEqual(set(s[:len(same)]), same)
        self.assertFalse(set(s) & (HOT - same))
        self.assertEqual(slate(lf, aff, "tc", rv=(), page='home'), slate(lf, aff, "r3", rv=(), page='home'))
        b, aff2, _ = build(self.ARMS, hot=None)
        self.assertEqual(slate(b, aff2, "tc"), slate(b, aff2, "r3"))               # no burst: the control's slate


if __name__ == "__main__":
    unittest.main()
