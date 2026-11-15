"""T-059: lfm feature `newph` (product launched during the event, requests without recent views)."""
import unittest
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

NEW = {'A38', 'A39', 'B39'}
K = lfm.FEATS.index("newph")
ARMS = [{"tag": "r3"}, {"tag": "nh1", "home": {"w": {"new": {"newph": 6.0}}}}]


def build(newp=NEW):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, newp=newp)
    lf.set_arms(ARMS)
    return lf, aff


def slate(lf, aff, model, rv=(), new=True, page='home'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state('u9'), aff, model=model)


class NewphTests(unittest.TestCase):
    def test_feature_is_last_and_weightless_by_default(self):
        self.assertEqual(K, 29); self.assertEqual(lfm.FEATS[29], "newph")
        lf, _ = build()
        self.assertEqual(float(lf.w["known"][K]), 0.0); self.assertEqual(float(lf.w["new"][K]), 0.0)

    def test_values_only_without_recent_views(self):
        lf, aff = build(); S = lf.snap
        for page in ('home', 'product'):
            X = lfm.features(S, aff.affinity_all('u9'), [], page, {}, set())
            self.assertEqual({S.ids[k] for k in np.nonzero(X[:, K])[0]}, NEW)
            self.assertEqual(float(X[:, lfm.FEATS.index("newp")].sum()), 0.0)
        for page in ('home', 'product'):
            X = lfm.features(S, aff.affinity_all('u9'), ['A30'], page, {}, set())
            self.assertEqual(float(X[:, K].sum()), 0.0)
        b, aff2 = build(newp=None)
        self.assertEqual(float(lfm.features(b.snap, aff2.affinity_all('u9'), [], 'home', {}, set())[:, K].sum()), 0.0)

    def test_arm_changes_only_new_shoppers_without_views(self):
        lf, aff = build()
        base = slate(lf, aff, "r3")
        self.assertFalse(NEW & set(base))
        s = slate(lf, aff, "nh1")
        self.assertEqual(len(set(s)), 10); self.assertEqual(set(s[:3]), NEW)
        self.assertEqual(slate(lf, aff, "nh1", new=False), slate(lf, aff, "r3", new=False))                       # returning: weight 0
        for kw in (dict(rv=('A30',), page='product'), dict(rv=('A30',), page='product', new=False), dict(rv=('A30',), page='home')):
            self.assertEqual(slate(lf, aff, "nh1", **kw), slate(lf, aff, "r3", **kw))                              # with views: untouched

    def test_policy_validation_accepts_the_weight(self):
        arms = [{"tag": "u3nh", "file": "lfm_coef_r3.json", "home": {"file": "lfm_coef_r3.json", "w": {"new": {"newph": 1.0}}}}]
        self.assertEqual(live.clean_lfm_arms(arms), arms)


if __name__ == "__main__":
    unittest.main()
