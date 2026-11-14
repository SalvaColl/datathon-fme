"""T-028: cold_lq (T-CS01) as a real lfm_arms arm: {"tag": ..., "lq": "cold" | "cold_new"}."""
import unittest

from recsys import lfm, live
from tests.test_lfm import build, catalog

REQ = dict(user_id='u9', rv=['A30'], page='product')


def build_cold(lq_cold):
    lf, aff = build()
    cat = catalog()
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, lq_cold=lq_cold)
    return lf, aff


class ColdArmTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'], live.CLQ, live.QR)
        lf, aff = build_cold({'B39': 12.0})                     # B39: a "new" product that cold_lq rates very high
        live.LF = lf; live.AP = type('AP', (), {'aff': aff})(); live.POLICY['variant'] = 'lfm'
    def tearDown(self):
        live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'], live.CLQ, live.QR = self.saved

    def arms(self, raw):
        arms = live.clean_lfm_arms(raw); live.LF.set_arms(arms); live.POLICY['lfm_arms'] = arms; return arms

    def sl(self, model, new):
        return live.LF.slate(dict(REQ, is_new_user=new), live.LF.user_state('u9'), live.AP.aff, model=model)

    def test_clean_keeps_lq_and_rejects_unknown_modes(self):
        self.assertEqual(live.clean_lfm_arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'cold_new'}])[1], {'tag': 'c1', 'lq': 'cold_new'})
        self.assertEqual(live.clean_lfm_arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'hot'}]), [])
        self.assertEqual(live.clean_lfm_arms([{'tag': 'r3'}, {'tag': 'c1', 'file': 'lfm_coef_r3.json', 'lq': 'cold'}])[1]['lq'], 'cold')

    def test_only_the_cold_arm_changes(self):
        base = {new: live.LF.slate(dict(REQ, is_new_user=new), live.LF.user_state('u9'), live.AP.aff) for new in (False, True)}
        self.arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'cold'}])
        for new in (False, True):
            self.assertEqual(self.sl('r3', new), base[new])                 # control arm is byte-identical
            self.assertNotIn('B39', base[new])
            self.assertIn('B39', self.sl('c1', new))

    def test_cold_new_touches_new_shoppers_only(self):
        self.arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'cold_new'}])
        self.assertEqual(self.sl('c1', False), self.sl('r3', False))
        self.assertIn('B39', self.sl('c1', True))

    def test_without_cold_vector_the_arm_equals_control(self):
        lf, aff = build_cold(None); live.LF = lf
        self.arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'cold'}])
        self.assertIsNone(live.LF.snap.lqc)
        self.assertEqual(self.sl('c1', True), self.sl('r3', True))

    def test_removing_the_arm_clears_the_flag(self):
        self.arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'cold'}]); self.assertEqual(live.LF.alt_lq, {'c1': 'cold'})
        self.arms([{'tag': 'r3'}]); self.assertEqual(live.LF.alt_lq, {})

    def test_hook_computes_nothing_unless_an_arm_asks(self):
        calls = []
        class CLQ:
            def lq_for_lfm(self, QR, *a, force=False): calls.append(force); return {'B39': 12.0}
        class T:
            def item_frame(self): return None
        live.CLQ = CLQ(); live.QR = type('QR', (), {'lq': {}})(); live.BASE = live.BASE or {'item': None}
        live.AP.cold = type('C', (), {'desc': {}})()
        self.arms([{'tag': 'r3'}, {'tag': 'r5'}])
        self.assertIsNone(live.cold_lq_for_arms(catalog(), T())); self.assertEqual(calls, [])
        self.arms([{'tag': 'r3'}, {'tag': 'c1', 'lq': 'cold'}])
        self.assertEqual(live.cold_lq_for_arms(catalog(), T()), {'B39': 12.0}); self.assertEqual(calls, [True])
        live.CLQ.lq_for_lfm = lambda QR, *a, force=False: QR.lq             # cold_lq's own "nothing to patch / error" answer
        self.assertIsNone(live.cold_lq_for_arms(catalog(), T()))

    def test_features_default_is_unchanged_for_training(self):
        S = live.LF.snap; aff = live.AP.aff.affinity_all('u9', ['A30'])
        a = lfm.features(S, aff, ['A30'], 'product', {}, set())
        b = lfm.features(S, aff, ['A30'], 'product', {}, set(), lq=S.lqc)
        k = lfm.FEATS.index('lq'); r = S.row['B39']
        self.assertEqual(a[r, k], S.lq[r]); self.assertEqual(b[r, k], S.lqc[r])
        self.assertTrue((a[:, [j for j in range(a.shape[1]) if j != k]] == b[:, [j for j in range(a.shape[1]) if j != k]]).all())


if __name__ == '__main__':
    unittest.main()
