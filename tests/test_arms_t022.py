"""T-022: the cart arms proposed in recsys/arms_t022.json are valid for the writer and do what they say."""
import json
import unittest
import numpy as np
import pandas as pd

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog

SPEC = json.loads((lfm.HERE / 'arms_t022.json').read_text())
# B05 and B33 are pending carts in another category than the product being viewed; B12 was bought
HIST = pd.DataFrame([('u1', 'B05', 3, 1, 0), ('u1', 'B33', 2, 1, 0), ('u1', 'B12', 1, 1, 1)], columns=['u', 'i', 'v', 'a', 'p'])


def build():
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(json.loads((lfm.HERE / 'lfm_coef_r2.json').read_text()), HIST)
    lf.set_catalog(cat, set(), aff, {p: 0.0 for p in cat.index}, None)
    arms = live.clean_lfm_arms(SPEC['lfm_arms']); lf.set_arms(arms)
    return lf, aff, arms


class CartArmsTests(unittest.TestCase):
    def test_spec_passes_the_writer_validation_untouched(self):
        arms = live.clean_lfm_arms(SPEC['lfm_arms'])
        self.assertEqual([a['tag'] for a in arms], ['r2', 'c2', 'c4'])
        self.assertEqual(SPEC['variant'], 'lfm')
        self.assertTrue(all(set(a.get('w', {})) <= {'known'} for a in arms))          # new shoppers are not touched

    def test_control_arm_equals_committed_r2(self):
        lf, aff, _ = build()
        r2 = json.loads((lfm.HERE / 'lfm_coef_r2.json').read_text())
        np.testing.assert_allclose(lf.alt['r2'][0]['known'], [r2['known']['w'].get(f, 0.0) for f in lfm.FEATS])
        np.testing.assert_allclose(lf.alt['c4'][0]['new'], lf.alt['r2'][0]['new'])

    def test_cart_arms_move_pending_carts_up_on_session_pages(self):
        lf, aff, arms = build()
        req = dict(user_id='u1', rv=['A30'], page='product', is_new_user=False)
        st = lf.user_state('u1'); pos = {}
        for a in arms:
            s = lf.slate(req, st, aff, model=a['tag'])
            self.assertEqual(len(set(s)), 10); self.assertNotIn('B12', s)           # bought stays dead in every arm
            pos[a['tag']] = [s.index(p) if p in s else 99 for p in ('B05', 'B33')]
        self.assertLessEqual(max(pos['c4']), 1)                                      # both carts lead the slate
        self.assertTrue(all(c4 <= c2 <= r2 for c4, c2, r2 in zip(pos['c4'], pos['c2'], pos['r2'])))
        self.assertLess(sum(pos['c4']), sum(pos['r2']))

    def test_home_score_of_a_single_cart_is_kept(self):
        """hcart is lowered by what chn adds, so the A/B reads only the session pages."""
        lf, _, _ = build(); k = lfm.FEATS.index
        def home_cart(tag, col): w = lf.alt[tag][0]['known']; return w[k(col)] * (np.log(2) if col == 'chn' else 1.0) + w[k('hcart')]
        for tag in ('c2', 'c4'):
            self.assertAlmostEqual(home_cart(tag, 'chn'), home_cart('r2', 'chn'), delta=0.06)
            self.assertAlmostEqual(home_cart(tag, 'cl'), home_cart('r2', 'cl'), delta=0.4)


if __name__ == '__main__':
    unittest.main()
