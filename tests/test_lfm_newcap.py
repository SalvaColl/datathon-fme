"""T-061: arm key `newcap`, the most launched products a list may carry (by segment; absent = no cap)."""
import copy
import unittest
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

NEW = {'A35', 'A36', 'A37', 'A38', 'A39', 'B39'}
W = {"w": {"known": {"newp": 6.0}, "new": {"newp": 6.0}}, "home": {"w": {"known": {"newph": 6.0}, "new": {"newph": 6.0}}}}
ARMS = [{"tag": "r3"}, {"tag": "big", **W}, {"tag": "cap2", **W, "newcap": {k: 2 for k in lfm.CAP_KEYS}},
        {"tag": "caph", **W, "newcap": {"home_new": 1}}]


def build(newp=NEW, arms=ARMS):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, newp=newp)
    lf.set_arms(arms)
    return lf, aff


def slate(lf, aff, model, rv=(), new=True, page='home', exclude=(), user='u9'):
    req = dict(user_id=user, rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state(user), aff, model=model, exclude=exclude)


SEGS = [dict(), dict(new=False), dict(rv=('A30',), page='product'), dict(rv=('A30',), page='product', new=False)]


class NewcapTests(unittest.TestCase):
    def test_cap_bounds_launched_products_in_every_segment(self):
        lf, aff = build()
        for kw in SEGS:
            big, cap = slate(lf, aff, "big", **kw), slate(lf, aff, "cap2", **kw)
            nb = [p for p in big if p in NEW]
            self.assertGreater(len(nb), 2, kw)                                  # the weight alone floods the list
            self.assertEqual(len(set(cap)), 10)
            self.assertEqual([p for p in cap if p in NEW], nb[:2], kw)          # the best two stay, in their order
            rest = [p for p in big if p not in NEW]
            self.assertEqual(set([p for p in cap if p not in NEW][:len(rest)]), set(rest), kw)   # the others stay (ties may swap), the gap is filled from below

    def test_cap_only_on_its_segment(self):
        lf, aff = build()
        self.assertEqual(sum(p in NEW for p in slate(lf, aff, "caph")), 1)
        for kw in SEGS[1:]: self.assertEqual(slate(lf, aff, "caph", **kw), slate(lf, aff, "big", **kw))

    def test_absent_cap_is_inert(self):
        lf, aff = build()
        self.assertEqual(lf.alt_cap, {"cap2": {k: 2 for k in lfm.CAP_KEYS}, "caph": {"home_new": 1}})
        loose = [{"tag": "big", **W}, {"tag": "wide", **W, "newcap": {k: 10 for k in lfm.CAP_KEYS}}]
        lf2, aff2 = build(arms=loose)
        for kw in SEGS: self.assertEqual(slate(lf2, aff2, "wide", **kw), slate(lf2, aff2, "big", **kw))
        lf3, aff3 = build(newp=None)                                            # no launched set: nothing to cap
        for kw in SEGS: self.assertEqual(slate(lf3, aff3, "cap2", **kw), slate(lf3, aff3, "big", **kw))
        self.assertEqual(slate(lf, aff, None), lf.slate(dict(user_id='u9', rv=[], page='home', is_new_user=True), lf.user_state('u9'), aff))

    def test_own_products_are_never_dropped(self):
        lf, aff = build()
        kw = dict(rv=('A35', 'A36', 'A37'), page='product')
        big, cap = slate(lf, aff, "big", **kw), slate(lf, aff, "cap2", **kw)
        own = {'A35', 'A36', 'A37'} & set(big)
        self.assertTrue(own <= set(cap))                                        # viewed launched products stay
        self.assertEqual({p for p in cap if p in NEW}, own if len(own) >= 2 else {p for p in cap if p in NEW})
        if len(own) >= 2: self.assertFalse((NEW - own) & set(cap))              # ...and use up the cap

    def test_excluded_products_do_not_use_the_cap(self):
        lf, aff = build()
        big = [p for p in slate(lf, aff, "big") if p in NEW]
        cap = slate(lf, aff, "cap2", exclude={big[0]})
        self.assertEqual(len(set(cap)), 10); self.assertNotIn(big[0], cap)
        self.assertEqual([p for p in cap if p in NEW], big[1:3])

    def test_cap_zero_and_scores_untouched(self):
        lf, aff = build(arms=[{"tag": "z", **W, "newcap": {k: 0 for k in lfm.CAP_KEYS}}])
        for kw in SEGS: self.assertFalse(NEW & set(slate(lf, aff, "z", **kw)))
        S = lf.snap; s = np.arange(S.n, dtype=float); s0 = s.copy()
        out = lfm.cap_launched(S, s, 1)
        self.assertTrue(np.array_equal(s, s0)); self.assertIsNot(out, s)        # works on a copy
        self.assertEqual(int(np.isfinite(out[S.newp > 0]).sum()), 1)
        self.assertIs(lfm.cap_launched(S, s, 99), s)

    def test_failure_serves_the_uncapped_list(self):
        lf, aff = build()
        lf.alt_cap = {"cap2": {"home_new": "x"}}                                # cannot happen through the validated policy
        self.assertEqual(slate(lf, aff, "cap2"), slate(lf, aff, "big"))

    def test_policy_validation(self):
        base = {"tag": "u3c", "file": "lfm_coef_r3.json"}
        full = {k: 2 for k in lfm.CAP_KEYS}
        self.assertEqual(live.clean_lfm_arms([{**base, "newcap": {"home_new": 2, "known": 3}}]), [{**base, "newcap": {"known": 3, "home_new": 2}}])
        self.assertEqual(live.clean_lfm_arms([{**base, "newcap": 2}]), [{**base, "newcap": full}])
        self.assertEqual(live.clean_lfm_arms([{**base, "newcap": {}}]), [base])
        for bad in ({"pages": 2}, {"known": -1}, {"known": 11}, {"known": 1.5}, {"known": True}, "2", [2], None, True):
            self.assertEqual(live.clean_lfm_arms([{**base, "newcap": bad}]), [], bad)
        self.assertEqual(live.clean_lfm_arms([base]), [base])

    def test_reload_installs_and_removes_the_cap(self):
        saved = live.LF
        try:
            lf, aff = build(arms=[{"tag": "big", **W}]); live.LF = lf
            arms = live.clean_lfm_arms([{"tag": "big", **W, "newcap": 1}])
            lf.alt, lf.alt_lq, lf.alt_x, lf.alt_cap = live.lfm_arm_weights(arms)
            self.assertEqual(sum(p in NEW for p in slate(lf, aff, "big")), 1)
            lf.alt, lf.alt_lq, lf.alt_x, lf.alt_cap = live.lfm_arm_weights(live.clean_lfm_arms([{"tag": "big", **W}]))
            self.assertEqual(lf.alt_cap, {}); self.assertGreater(sum(p in NEW for p in slate(lf, aff, "big")), 2)
        finally: live.LF = saved


class FakeSnap:
    """Just what cap_launched / top_items read: ids, n and the launched flags."""
    def __init__(self, ids, launched):
        self.ids = list(ids); self.n = len(ids); self.newp = np.array([1.0 if p in launched else 0.0 for p in ids])


def capped(ids, scores, launched, c, own=(), exclude=(), n=10):
    S = FakeSnap(ids, launched); s = np.array(scores, dtype=float)
    return S, s, lfm.top_items(S, lfm.cap_launched(S, s, c, exclude, own, n), n, exclude)


class ServedOwnTests(unittest.TestCase):
    """T-063: an own launched product uses the cap only when it is in the served list (cases E-RS13)."""
    OLD = [f"O{k}" for k in range(12)]

    def test_own_products_below_the_list_do_not_use_the_cap(self):
        # cap 2; launched A/B at 100/99; ten old products 90..81; two own launched products at 1/0
        ids = ["A", "B"] + self.OLD[:10] + ["X", "Y"]; sc = [100, 99] + list(range(90, 80, -1)) + [1, 0]
        _, _, out = capped(ids, sc, {"A", "B", "X", "Y"}, 2, own={"X", "Y"})
        self.assertEqual(out, ["A", "B"] + self.OLD[:8])

    def test_served_own_products_use_the_cap(self):
        ids = ["A", "B", "X"] + self.OLD; sc = [100, 99, 98] + list(range(90, 78, -1))
        _, _, out = capped(ids, sc, {"A", "B", "X"}, 2, own={"X"})
        self.assertEqual(out, ["A", "X"] + self.OLD[:8])                        # one own in the list: one place left
        _, _, out = capped(ids + ["Y"], sc + [97], {"A", "B", "X", "Y"}, 2, own={"X", "Y"})
        self.assertEqual(out, ["X", "Y"] + self.OLD[:8])                        # two own in the list: none left

    def test_own_product_that_enters_through_the_gap_counts(self):
        # dropping C lets the own product X (11th) into the list; then only one free launched product may stay
        ids = ["A", "B", "C"] + self.OLD[:7] + ["X"] + self.OLD[7:]; sc = [100, 99, 98] + list(range(90, 83, -1)) + [80] + [70, 69, 68, 67, 66]
        _, _, out = capped(ids, sc, {"A", "B", "C", "X"}, 2, own={"X"})
        self.assertEqual(sum(p in {"A", "B", "C", "X"} for p in out), 2)
        self.assertEqual(out, ["A"] + self.OLD[:7] + ["X", self.OLD[7]])

    def test_all_launched_products_are_own(self):
        ids = ["X", "Y", "Z"] + self.OLD; sc = [100, 99, 98] + list(range(90, 78, -1))
        S, s, out = capped(ids, sc, {"X", "Y", "Z"}, 1, own={"X", "Y", "Z"})
        self.assertEqual(out, ["X", "Y", "Z"] + self.OLD[:7])                   # never dropped, even above the cap
        self.assertIs(lfm.cap_launched(S, s, 1, (), {"X", "Y", "Z"}), s)

    def test_more_than_ten_own_products(self):
        own = [f"X{k}" for k in range(12)]; ids = own + ["A"] + self.OLD; sc = list(range(200, 188, -1)) + [150] + list(range(90, 78, -1))
        _, _, out = capped(ids, sc, set(own) | {"A"}, 2, own=set(own))
        self.assertEqual(out, own[:10])

    def test_stockout_of_an_own_product_frees_its_place(self):
        ids = ["A", "B", "X"] + self.OLD; sc = [100, 99, 98] + list(range(90, 78, -1))
        _, _, out = capped(ids, sc, {"A", "B", "X"}, 2, own={"X"}, exclude={"X"})
        self.assertEqual(out, ["A", "B"] + self.OLD[:8])

    def test_fewer_than_ten_old_products(self):
        ids = ["A", "B", "C", "D"] + self.OLD[:5]; sc = [100, 99, 98, 97, 5, 4, 3, 2, 1]
        S, s, out = capped(ids, sc, {"A", "B", "C", "D"}, 2)
        self.assertEqual(out, ["A", "B"] + self.OLD[:5])                        # short list: LiveFit.slate then serves the uncapped one

    def test_tie_at_the_border_keeps_the_first(self):
        ids = ["A", "B", "C"] + self.OLD; sc = [100, 99, 99] + list(range(90, 78, -1))
        _, _, out = capped(ids, sc, {"A", "B", "C"}, 2)
        self.assertEqual(out, ["A", "B"] + self.OLD[:8])

    def test_no_own_products_is_the_old_rule(self):
        rng = np.random.default_rng(0); ids = [f"P{k}" for k in range(60)]; launched = set(ids[::3])
        for c in range(0, 6):
            s = rng.normal(size=60); S = FakeSnap(ids, launched)
            out = lfm.cap_launched(S, s, c)
            keep = sorted((k for k in range(60) if ids[k] in launched), key=lambda k: -s[k])[:c]
            want = s.copy(); want[[k for k in range(60) if ids[k] in launched and k not in keep]] = -np.inf
            self.assertTrue(np.array_equal(out, want))

    def test_served_list_never_exceeds_the_cap_unless_own(self):
        rng = np.random.default_rng(1); ids = [f"P{k}" for k in range(80)]
        for _ in range(300):
            launched = set(rng.choice(ids, 25, replace=False)); own = set(rng.choice(sorted(launched), int(rng.integers(0, 6)), replace=False))
            c = int(rng.integers(0, 5)); s = rng.normal(size=80); S = FakeSnap(ids, launched)
            out = lfm.top_items(S, lfm.cap_launched(S, s, c, (), own), 10)
            free = [p for p in out if p in launched and p not in own]; mine = [p for p in out if p in own]
            self.assertLessEqual(len(free), max(0, c - len(mine)))
            base = lfm.top_items(S, s, 10)
            self.assertTrue(set(p for p in base if p in own) <= set(out))       # own products of the uncapped list stay


if __name__ == "__main__":
    unittest.main()
