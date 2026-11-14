"""T-036: lfm feature `newp` (product launched during the event) and the arm that weights it."""
import unittest
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

NEW = {'A38', 'A39', 'B39'}                       # launched during the event: worst quality of the fixture, never in a slate
ARMS = [{"tag": "r3"}, {"tag": "np1", "w": {"known": {"newp": 6.0}}}]


def build(newp=NEW):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, newp=newp)
    lf.set_arms(ARMS)
    return lf, aff


def slate(lf, aff, model, rv=('A30',), new=False, page='product'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state('u9'), aff, model=model)


class NewpTests(unittest.TestCase):
    def test_feature_is_last_and_absent_from_committed_weights(self):
        self.assertEqual(lfm.FEATS[-1], "newp"); self.assertEqual(lfm.FEATS.index("newp"), 21)
        lf, _ = build()
        self.assertEqual(float(lf.w["known"][21]), 0.0); self.assertEqual(float(lf.w["new"][21]), 0.0)

    def test_control_is_identical_with_and_without_the_new_product_set(self):
        a, aff = build(); b, aff2 = build(newp=None)
        for kw in (dict(), dict(new=True), dict(page='home', rv=()), dict(page='category')):
            self.assertEqual(slate(a, aff, "r3", **kw), slate(b, aff2, "r3", **kw))
        self.assertIsNone(b.snap.newp)
        self.assertEqual(slate(b, aff2, "np1"), slate(b, aff2, "r3"))             # no set known: the arm serves the control's slate

    def test_arm_brings_launched_products_for_returning_shoppers_on_pages_only(self):
        lf, aff = build()
        self.assertFalse(NEW & set(slate(lf, aff, "r3")))
        s = slate(lf, aff, "np1")
        self.assertEqual(len(set(s)), 10); self.assertEqual(set(s[:3]), NEW)
        self.assertEqual(slate(lf, aff, "np1", page='category')[:3], s[:3])
        self.assertEqual(slate(lf, aff, "np1", new=True), slate(lf, aff, "r3", new=True))                       # new shoppers: weight 0
        self.assertEqual(slate(lf, aff, "np1", page='home', rv=()), slate(lf, aff, "r3", page='home', rv=()))   # home: feature 0
        self.assertEqual(slate(lf, aff, "np1", page='home'), slate(lf, aff, "r3", page='home'))

    def test_feature_values(self):
        lf, aff = build(); S = lf.snap
        X = lfm.features(S, aff.affinity_all('u9'), ['A30'], 'product', {}, set())
        self.assertEqual({S.ids[k] for k in np.nonzero(X[:, 21])[0]}, NEW)
        for page, rv in (('home', ['A30']), ('product', []), ('home', [])):
            self.assertEqual(float(lfm.features(S, aff.affinity_all('u9'), rv, page, {}, set())[:, 21].sum()), 0.0)

    def test_unavailable_or_bought_launches_are_never_served(self):
        cat = catalog(); aff = FakeAff(list(cat.index)); lf = lfm.LiveFit(COEF, HIST)
        lf.set_catalog(cat, {'A39'}, aff, {p: 0.0 for p in cat.index}, None, newp=NEW); lf.set_arms(ARMS)
        lf.add('u9', 'A38', p=1)
        s = slate(lf, aff, "np1")
        self.assertEqual(len(set(s)), 10); self.assertNotIn('A39', s); self.assertNotIn('A38', s); self.assertIn('B39', s)

    def test_writer_accepts_the_arm_and_finds_the_launches(self):
        arms = [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "np1", "file": "lfm_coef_r3.json", "w": {"known": {"newp": 1.0}}}]
        self.assertEqual(live.clean_lfm_arms(arms), arms)
        cat = catalog(); saved = live.QR
        try:
            live.QR = type("QR", (), {"q": {p: 0.01 for p in cat.index if p not in NEW}})()
            self.assertEqual(live.new_products(cat), NEW)
            live.QR = type("QR", (), {"q": {p: 0.01 for p in list(cat.index)[:40]}})()        # half the catalogue "new": not credible
            self.assertIsNone(live.new_products(cat))
            live.QR = type("QR", (), {"q": {p: 0.01 for p in cat.index}})()
            self.assertIsNone(live.new_products(cat))
            live.QR = None; self.assertIsNone(live.new_products(cat))
        finally: live.QR = saved


if __name__ == "__main__":
    unittest.main()
