"""T-038: recsys/policy.home_cart_r3.json = pending carts first on home for returning shoppers, champion order otherwise."""
import json
import unittest
import numpy as np
import pandas as pd

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog

SPEC = json.loads((lfm.HERE / 'policy.home_cart_r3.json').read_text())
CTL, ARM = 'r3', 'h3c'
# u1: three pending carts (B05, B33, A21), one cart already bought (B12); u2: 14 pending carts; u3: nothing
HIST = pd.DataFrame([('u1', 'B05', 3, 1, 0), ('u1', 'B33', 2, 2, 0), ('u1', 'A21', 1, 1, 0), ('u1', 'B12', 1, 1, 1)]
                    + [('u2', f'A{k:02d}', 1, 1, 0) for k in range(14)] + [('u3', 'A01', 2, 0, 0)], columns=['u', 'i', 'v', 'a', 'p'])


def build(unavail=()):
    cat = catalog(); aff = FakeAff(list(cat.index), {'u1': 7, 'u2': 3})
    lf = lfm.LiveFit(json.loads((lfm.HERE / 'lfm_coef_r3.json').read_text()), HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: 0.03 * int(p[1:]) for p in cat.index}, None)
    lf.set_arms(live.clean_lfm_arms(SPEC['lfm_arms']))
    return lf, aff


def both(lf, aff, user, page='home', rv=(), new=False, exclude=()):
    req = dict(user_id=user, rv=list(rv), page=page, is_new_user=new); st = lf.user_state(user)
    return [lf.slate(req, st, aff, exclude=exclude, model=m) for m in (CTL, ARM)] + [lf.scores(req, st, aff, model=CTL), st]


class HomeCartFirstTests(unittest.TestCase):
    def test_spec_is_accepted_and_differs_from_control_only_on_home_known_hcart(self):
        arms = live.clean_lfm_arms(SPEC['lfm_arms'])
        self.assertEqual([a['tag'] for a in arms], [CTL, ARM]); self.assertEqual(SPEC['variant'], 'lfm')
        lf, _ = build(); k = lfm.FEATS.index('hcart')
        for seg in ('known', 'new'):
            np.testing.assert_array_equal(lf.alt[ARM][0][seg], lf.alt[CTL][0][seg])           # product/category: same weights
        np.testing.assert_array_equal(lf.alt[ARM + '@home'][0]['new'], lf.alt[CTL][0]['new'])  # new shoppers on home: same
        d = lf.alt[ARM + '@home'][0]['known'] - lf.alt[CTL][0]['known']
        self.assertEqual(np.flatnonzero(d).tolist(), [k]); self.assertEqual(lf.alt[ARM + '@home'][0]['known'][k], 20.0)

    def test_carts_lead_in_champion_order_and_the_rest_is_the_champion_slate(self):
        lf, aff = build()
        ctl, arm, (S, s), st = both(lf, aff, 'u1')
        carts = sorted(['B05', 'B33', 'A21'], key=lambda p: -s[S.row[p]])
        self.assertEqual(arm[:3], carts)                                               # ordered by the champion's own score
        order = [S.ids[k] for k in np.argsort(-s, kind='stable') if np.isfinite(s[k])]
        self.assertEqual(arm[3:], [p for p in order if p not in carts][:7])            # fill = champion order, nothing else
        self.assertTrue(set(arm[3:]) <= set(ctl) | set(order[:13]))
        self.assertEqual(len(set(arm)), 10); self.assertNotIn('B12', arm)              # bought cart stays out

    def test_more_than_ten_carts_keeps_the_ten_best_by_champion_score(self):
        lf, aff = build()
        _, arm, (S, s), st = both(lf, aff, 'u2')
        best = sorted(st[2], key=lambda p: -s[S.row[p]])[:10]
        self.assertEqual(arm, best)

    def test_no_pending_cart_gives_exactly_the_champion_slate(self):
        lf, aff = build()
        for user in ('u3', 'u9'):
            ctl, arm, _, _ = both(lf, aff, user)
            self.assertEqual(arm, ctl)

    def test_live_cart_counts_and_live_purchase_removes_it(self):
        lf, aff = build()
        lf.add('u3', 'B20', 1, 1, 0)
        self.assertEqual(both(lf, aff, 'u3')[1][0], 'B20')
        lf.add('u3', 'B20', 0, 0, 1)
        ctl, arm, _, _ = both(lf, aff, 'u3')
        self.assertNotIn('B20', arm); self.assertEqual(arm, ctl)

    def test_out_of_stock_and_excluded_carts_are_never_shown(self):
        lf, aff = build(unavail={'B05'})
        _, arm, _, _ = both(lf, aff, 'u1', exclude={'B33'})
        self.assertEqual(len(set(arm)), 10); self.assertFalse({'B05', 'B33', 'B12'} & set(arm)); self.assertEqual(arm[0], 'A21')

    def test_stale_history_views_stay_dead(self):
        class HC:                                   # home_cands stand-in: u1 viewed A00 in the history and never carted it
            idx = {p: k for k, p in enumerate(catalog().index)}
            stale = {'u1': np.packbits(np.eye(1, 80, 0, dtype=np.uint8)[0], bitorder='little').tobytes()}
        cat = catalog(); aff = FakeAff(list(cat.index), {'u1': 7})
        lf = lfm.LiveFit(json.loads((lfm.HERE / 'lfm_coef_r3.json').read_text()), HIST)
        lf.set_catalog(cat, set(), aff, {p: (9.0 if p == 'A00' else 0.0) for p in cat.index}, HC)
        lf.set_arms(live.clean_lfm_arms(SPEC['lfm_arms']))
        ctl, arm, _, _ = both(lf, aff, 'u1')
        self.assertNotIn('A00', ctl); self.assertNotIn('A00', arm)

    def test_product_pages_and_new_shoppers_are_untouched(self):
        lf, aff = build()
        lf.add('u8', 'B20', 1, 1, 0)
        for user, page, rv, new in (('u1', 'product', ('A30',), False), ('u2', 'category', ('A30', 'B02'), False),
                                    ('u8', 'home', (), True), ('u8', 'product', ('A30',), True)):
            ctl, arm, _, _ = both(lf, aff, user, page=page, rv=rv, new=new)
            self.assertEqual(arm, ctl, (user, page))

    def test_writer_labels_the_two_arms_separately_on_home(self):
        saved = live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms']
        try:
            lf, aff = build()
            live.LF, live.AP = lf, type('AP', (), {'aff': aff})()
            live.POLICY['variant'] = 'lfm'; live.POLICY['lfm_arms'] = live.clean_lfm_arms(SPEC['lfm_arms'])
            reqs = [dict(request_id=str(k), user_id=f'u{k}', rv=[], page='home', is_new_user=False) for k in range(40)]
            ver = {}; out = live.lfm_slates(reqs, set(), ver)
            self.assertEqual(len(out), 40); self.assertEqual(set(ver.values()), {'v3-lfm-r3-kh', 'v3-lfm-h3c-kh'})
        finally:
            live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'] = saved


if __name__ == '__main__':
    unittest.main()
