import unittest
import numpy as np
import pandas as pd

from recsys import aff_policy, attr_affinity, cold_items, qrank, live
from tests.test_qrank import FakeModel


class FakeCold:
    """Stand-in for cold_items.ColdStart: 40 products per category, attribute pair decided by the product number."""
    def __init__(self):
        self.attr = {f'{c}{k:02d}': (k % 5, 5 + k % 3) for c in 'AB' for k in range(40)}
        self.base_ids = set(self.attr); self.desc = {}


def catalog():
    rows = [(f'{c}{k:02d}', c, f'{c}-s{k % 2}', 'brand', 10.0 + k) for c in 'AB' for k in range(40)]
    return pd.DataFrame(rows, columns=['product_id', 'category', 'sub', 'brand', 'price']).set_index('product_id')


def policy():
    cold = FakeCold(); aff = attr_affinity.AttrAffinity(cold, ui_path=None)
    for _ in range(30): aff.add('fan', 'A00', 1)          # 'fan' only ever looks at attribute pair (0, 5)
    return aff_policy.AffPolicy(cold, aff)


class AffinityTests(unittest.TestCase):
    def test_unknown_user_is_neutral_and_boost_is_constant(self):
        ap = policy()
        a = ap.aff.affinity('nobody', ['A00', 'A01', 'not-a-product'])
        self.assertTrue(np.allclose(a, attr_affinity.NEUTRAL))
        self.assertEqual(len(set(np.round(ap.aff.boost('nobody', ['A00', 'A01']), 6))), 1)

    def test_matching_products_score_higher(self):
        ap = policy()
        a = ap.aff.affinity('fan', ['A15', 'A05', 'A01'])   # A15 shares both attributes, A05 one, A01 none
        self.assertGreater(a[0], a[1]); self.assertGreater(a[1], a[2])
        self.assertLess(a[2], attr_affinity.NEUTRAL)

    def test_candidates_are_active_unseen_and_respect_category(self):
        ap = policy(); cat = catalog()
        c = ap.aff.candidates('fan', ['A15'], cat, unavail={'A30'}, n=10, category='A')
        self.assertTrue(c and all(p.startswith('A') for p in c))
        self.assertNotIn('A30', c); self.assertNotIn('A15', c)
        self.assertEqual(ap.aff.candidates('nobody', [], cat), [])

    def test_boost_frame_matches_per_request_boost(self):
        ap = policy()
        X = pd.DataFrame({'sid': [0, 0, 3], 'u': ['fan', 'fan', 'nobody'], 'i': ['A15', 'A01', 'B02'], 'rv': [[], [], ['B02']]})
        b = ap.boost(X)
        self.assertTrue(np.allclose(b[:2], ap.aff.boost('fan', ['A15', 'A01'])))
        self.assertTrue(np.allclose(b[2:], ap.aff.boost('nobody', ['B02'], ['B02'])))

    def test_new_product_is_scored_only_after_sync(self):
        ap = policy()
        ap.cold.attr['NEW1'] = (0, 5)
        self.assertAlmostEqual(float(ap.aff.affinity('fan', ['NEW1'])[0]), attr_affinity.NEUTRAL, places=5)
        self.assertEqual(ap.aff.sync_products(), 1)
        self.assertGreater(float(ap.aff.affinity('fan', ['NEW1'])[0]), 0.2)
        ap.aff.add('fan', 'NEW1', 2)   # live views of the new product are accepted after sync


class QrankAffinityTests(unittest.TestCase):
    def setUp(self):
        self.ap = policy(); cat = catalog()
        self.qr = qrank.Ranker(FakeModel(), {i: 0.02 / (1 + int(i[1:])) for i in cat.index}); self.qr.set_catalog(cat, unavail={'A01'})

    def test_slates_are_valid_same_category_and_skip_bought(self):
        s = self.ap.qrank_slates(self.qr, [{'user_id': 'fan', 'rv': ['A30'], 'page': 'product', 'bought': {'A00'}}])[0]
        self.assertEqual(len(set(s)), 10)
        self.assertTrue(all(i.startswith('A') for i in s))
        self.assertNotIn('A01', s); self.assertNotIn('A00', s)

    def test_affinity_pulls_matching_products_up(self):
        plain = self.qr.slates([{'rv': ['A30'], 'page': 'product'}])[0]
        s = self.ap.qrank_slates(self.qr, [{'user_id': 'fan', 'rv': ['A30'], 'page': 'product'}])[0]
        share = lambda sl: np.mean(self.ap.aff.affinity('fan', sl, ['A30']))
        self.assertGreater(share(s), share(plain))

    def test_home_and_unknown_last_view_are_left_to_the_caller(self):
        out = self.ap.qrank_slates(self.qr, [{'user_id': 'fan', 'rv': [], 'page': 'home'}, {'user_id': 'fan', 'rv': ['A03', 'ZZZ'], 'page': 'product'}])
        self.assertEqual(out, [None, None])


class LiveRoutingTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.POLICY['variant'], live.AP, live.QR)
        self.ap = policy(); cat = catalog()
        qr = qrank.Ranker(FakeModel(), {i: 0.02 / (1 + int(i[1:])) for i in cat.index}); qr.set_catalog(cat, unavail=set())
        live.AP, live.QR = self.ap, qr
        users = [f'u{k}' for k in range(40)]
        self.t = next(u for u in users if live.treated(u)); self.c = next(u for u in users if not live.treated(u))
    def tearDown(self): live.POLICY['variant'], live.AP, live.QR = self.saved
    def req(self, u, rv=('A30',)): return {'request_id': 'r', 'user_id': u, 'rv': list(rv), 'page': 'product'}

    def test_variants_route_requests_to_the_right_arm(self):
        expect = {'v1': (False, False, False, False), 'qrank': (False, True, False, True), 'ab_qrank': (False, True, False, False),
                  'aff': (True, False, True, False), 'qrank_aff': (True, True, True, True),
                  'ab_aff': (True, False, False, False), 'ab_qrank_aff': (True, True, False, True),
                  # D-170 (attr_model): the attr arm never goes to qrank; in ab_attr_aff the control arm is qrank_aff
                  'attr': (False, False, False, False), 'attr_aff': (True, False, True, False),
                  'ab_attr': (False, False, False, False), 'ab_attr_aff': (True, False, True, True),
                  'lfm': (False, False, False, False), 'ab_lfm': (False, False, False, True)}   # lfm arms: see test_lfm.py
        self.assertEqual(set(expect), set(live.VARIANTS))
        for v, e in expect.items():
            live.POLICY['variant'] = v
            got = (live.use_aff(self.req(self.t)), live.use_qrank(self.req(self.t)), live.use_aff(self.req(self.c)), live.use_qrank(self.req(self.c)))
            self.assertEqual(got, e, v)
        self.assertFalse(live.use_qrank(self.req(self.t, rv=())))          # home never goes to qrank

    def test_qrank_aff_versions_and_fallback_without_policy(self):
        live.POLICY['variant'] = 'ab_qrank_aff'; ver = {}
        out = live.qrank_slates([self.req(self.t), self.req(self.c)], set(), ver)
        self.assertEqual(sorted(out), [0, 1]); self.assertEqual(ver, {0: live.VERSION_QA})
        self.assertTrue(all(len(set(s)) == 10 for s in out.values()))
        live.AP = None; live.POLICY['variant'] = 'qrank_aff'; ver = {}      # affinity unavailable -> plain qrank
        out = live.qrank_slates([self.req(self.t)], set(), ver)
        self.assertEqual(len(set(out[0])), 10); self.assertEqual(ver, {})

    def test_broken_affinity_falls_back_to_plain_qrank(self):
        live.POLICY['variant'] = 'qrank_aff'; ver = {}
        self.ap.qrank_slates = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        out = live.qrank_slates([self.req(self.t)], set(), ver)
        self.assertEqual(len(set(out[0])), 10); self.assertEqual(ver, {})


class ColdPriorTests(unittest.TestCase):
    def test_attrs_and_unknown_phrases(self):
        self.assertEqual(len(cold_items.attrs('Vedo Yoga Mats with organic ingredients and extra durability.')), 2)
        self.assertEqual(cold_items.attrs('A brand new phrase nobody has seen.'), ())

    def test_shipped_prior_predicts_and_tables_cancel_live_counts(self):
        cs = cold_items.ColdStart()
        self.assertEqual(len(cs.attr), 5000)
        base = list(cs.attr)[:3]
        cat = pd.DataFrame({'category': ['Pets'] * 4, 'sub': ['Pet Shampoo'] * 4, 'brand': ['Timavo'] * 4, 'price': [10.0, 20.0, 30.0, 36.99]}, index=base + ['p_new'])
        cs.desc['p_new'] = 'Timavo Pet Shampoo line, known for great value for money and a minimalist design.'
        base_item = pd.DataFrame({'it_v': [1000.0, 2000.0, 3000.0], 'it_a': [100.0, 100.0, 100.0], 'it_p': [50.0, 50.0, 50.0]}, index=base)
        live_item = pd.DataFrame({'it_v': [10.0], 'it_a': [2.0], 'it_p': [1.0]}, index=['p_new'])
        ps = cs.pseudo_counts(cat, base_item, live_item)
        self.assertEqual(list(ps.index), ['p_new'])
        self.assertAlmostEqual(ps.at['p_new', 'it_v'], 2000.0)                 # median volume of the subcategory
        self.assertTrue(0 < ps.at['p_new', 'it_p'] < ps.at['p_new', 'it_a'] < ps.at['p_new', 'it_v'])
        t = cs.tables(cat, base_item, live_item)
        total = t['item'].reindex(['p_new']).fillna(0).values + live_item.values     # what fe.featurize adds up
        self.assertTrue(np.allclose(total, ps.values))
        self.assertEqual(len(t['uit'].reindex(pd.MultiIndex.from_arrays([['u'], ['p_new']])).fillna(0)), 1)


if __name__ == '__main__':
    unittest.main()
