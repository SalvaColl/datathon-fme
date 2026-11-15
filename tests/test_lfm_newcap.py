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


if __name__ == "__main__":
    unittest.main()
