import unittest
import numpy as np
import pandas as pd

from recsys import attr_model, attr_policy


class FakeModel:
    """P(buy) = exp(lq) * 10 if viewed * 3^(phrases shared with the last view), halved per slot."""
    def predict_proba(self, X):
        p = np.exp(X[:, 1]) * np.where((X[:, 2] + X[:, 3]) > 0, 10, 1) * 3.0 ** X[:, 11] * 0.5 ** X[:, 0]
        return np.column_stack([1 - p, p])


def catalog(extra=()):
    rows = [(f'{c}{k:02d}', c, f'{c}-s{k % 2}', 'brand', 10.0 + k) for c in 'AB' for k in range(40)] + list(extra)
    return pd.DataFrame(rows, columns=['product_id', 'category', 'sub', 'brand', 'price']).set_index('product_id')


ATTRS = {f'{c}{k:02d}': (k % 5, 5 + k % 3) for c in 'AB' for k in range(40)}


def quality():
    cat = catalog()
    hist = pd.DataFrame({'v': 1000.0, 'p': [200.0 / (1 + int(i[1:])) for i in cat.index], 'E': 0.0, 'b': 0.0}, index=cat.index)
    return attr_model.Quality(dict(
        coef_cr={'a=0': 1.0, 'a=4': -1.0}, b_cr=-3.0, coef_pop={}, b_pop=float(np.log(1 / 80)), sub_median={},
        V_hist=80000.0, hist=hist, cat={'A': 0.0, 'B': 0.0}, beta=[1.0, 0.0, 0.5, 1.0], b0=-2.0))


def ranker(cat=None, attrs=None, **kw):
    r = attr_model.Ranker(FakeModel(), quality(), ATTRS, **kw)
    r.set_catalog(catalog() if cat is None else cat, unavail={'A01'}, attrs=attrs)
    return r


class QualityTests(unittest.TestCase):
    def test_new_product_gets_exactly_its_attribute_prior(self):
        cat = catalog([('NEW1', 'A', 'A-s0', 'never-seen-brand', 15.0), ('NEW2', 'A', 'A-s0', 'never-seen-brand', 15.0)])
        t = quality().compute(cat, {**ATTRS, 'NEW1': (0, 6), 'NEW2': (4, 6)})
        self.assertAlmostEqual(t.at['NEW1', 'r_v'], 0.0); self.assertAlmostEqual(t.at['NEW1', 'r_cr'], 0.0)
        self.assertAlmostEqual(t.at['NEW1', 'lq'], -2.0 + (-3.0 + 1.0), places=6)       # b0 + conversion prior, no counts
        self.assertGreater(t.at['NEW1', 'lq'], t.at['NEW2', 'lq'])                      # the phrase decides

    def test_counts_move_quality_and_are_shrunk(self):
        cat = catalog(); t = quality().compute(cat, ATTRS)
        self.assertGreater(t.at['A00', 'lq'], t.at['A10', 'lq'])                        # same phrases (k%5, k%3 differ), more purchases
        few = pd.DataFrame({'it_v': [5.0], 'it_p': [5.0]}, index=['NEW1'])
        cat2 = catalog([('NEW1', 'A', 'A-s0', 'b', 15.0)]); A = {**ATTRS, 'NEW1': (0, 6)}
        a = quality().compute(cat2, A); b = quality().compute(cat2, A, live_item=few)
        self.assertGreater(b.at['NEW1', 'lq'], a.at['NEW1', 'lq'])                      # live evidence raises it...
        self.assertLess(b.at['NEW1', 'r_cr'], np.log(1.0 / np.exp(-2.0)))               # ...but 5 views do not make it "always bought"

    def test_masked_and_unknown_tokens_are_harmless(self):
        cat = catalog([('X1', 'ZZ-new-category', 'new-sub', 'b', 0.0)])
        t = quality().compute(cat, ATTRS, masked=['A00'])
        self.assertTrue(np.isfinite(t.lq).all())
        self.assertAlmostEqual(t.at['A00', 'r_v'], 0.0)


class RankerTests(unittest.TestCase):
    def test_ten_distinct_in_stock_same_category(self):
        s = ranker().slates([{'rv': ['A30'], 'page': 'product'}])[0]
        self.assertEqual(len(set(s)), 10)
        self.assertTrue(all(i.startswith('A') for i in s)); self.assertNotIn('A01', s)

    def test_home_and_unknown_last_view_are_left_to_the_caller(self):
        out = ranker().slates([{'rv': [], 'page': 'home'}, {'rv': ['A03', 'ZZZ'], 'page': 'product'}, {'page': 'product'}])
        self.assertEqual(out, [None, None, None])

    def test_bought_items_are_excluded_even_if_viewed(self):
        s = ranker().slates([{'rv': ['A00'], 'page': 'product', 'bought': {'A00', 'A02'}}])[0]
        self.assertNotIn('A00', s); self.assertNotIn('A02', s)

    def test_viewed_item_from_another_category_can_be_shown_but_no_other_cross_category_item(self):
        s = ranker(viewed_factor=1.0).slates([{'rv': ['B00', 'A30'], 'page': 'product'}])[0]
        self.assertIn('B00', s)
        self.assertEqual([i for i in s if i.startswith('B')], ['B00'])

    def test_session_phrases_change_the_slate_without_any_user_id(self):
        r = ranker()
        a = r.slates([{'rv': ['A30'], 'page': 'product'}])[0]; b = r.slates([{'rv': ['A32'], 'page': 'product'}])[0]
        self.assertNotEqual(a, b)
        shared = lambda last, s: np.mean([len(set(ATTRS[last]) & set(ATTRS[i])) for i in s])
        self.assertGreater(shared('A30', a), shared('A30', b))

    def test_new_product_can_enter_a_slate_from_attributes_alone(self):
        cat = catalog([('NEW1', 'A', 'A-s0', 'never-seen-brand', 15.0)])
        r = ranker(cat, attrs={'NEW1': ATTRS['A30']})                                   # shares both phrases with the viewed product
        self.assertIn('NEW1', r.slates([{'rv': ['A30'], 'page': 'product'}])[0])
        r = ranker(cat)                                                                 # phrases unknown: still valid, just unboosted
        self.assertEqual(len(set(r.slates([{'rv': ['A30'], 'page': 'product'}])[0])), 10)

    def test_history_boost_pulls_matching_products_up_and_none_is_neutral(self):
        r = ranker(); req = {'rv': ['A30'], 'page': 'product'}
        fan = np.zeros(20, dtype=np.float32); fan[[1, 6]] = 30.0                         # stored taste for phrases 1 and 6
        plain = r.slates([req])[0]; boosted = r.slates([{**req, 'uvec': fan}])[0]
        match = lambda s: sum(len({1, 6} & set(ATTRS[i])) for i in s)
        self.assertGreater(match(boosted), match(plain))
        self.assertEqual(r.slates([{**req, 'uvec': np.zeros(20)}])[0], plain)

    def test_before_first_catalogue_everything_is_left_to_the_caller(self):
        r = attr_model.Ranker(FakeModel(), quality(), ATTRS)
        self.assertEqual(r.slates([{'rv': ['A30'], 'page': 'product'}]), [None])
        self.assertFalse(r.ok)


class PolicyTests(unittest.TestCase):
    class FakeAff:
        def user_vec(self, u):
            v = np.zeros(20, dtype=np.float32)
            if u == 'fan': v[[4, 7]] = 30.0
            return v
        def sync_products(self): return 0

    class FakeCold:
        def __init__(self): self.attr = dict(ATTRS)
        def sync(self, query): self.attr['NEW1'] = ATTRS['A30']; return 1

    def policy(self):
        return attr_policy.AttrPolicy(attr_model.Ranker(FakeModel(), quality(), ATTRS), self.FakeCold(), self.FakeAff())

    def test_refresh_picks_up_new_products_and_live_counts(self):
        p = self.policy(); cat = catalog([('NEW1', 'A', 'A-s0', 'b', 15.0)])
        self.assertFalse(p.ok)
        p.refresh(lambda sql: [], cat, unavail={'A01'}, live_item=pd.DataFrame({'it_v': [50.0], 'it_a': [5.0], 'it_p': [20.0]}, index=['NEW1']))
        self.assertTrue(p.ok)
        self.assertIn('NEW1', p.slates([{'user_id': 'x', 'rv': ['A30'], 'page': 'product', 'bought': set()}])[0])

    def test_history_flag_only_affects_the_flagged_request(self):
        p = self.policy(); p.refresh(lambda sql: [], catalog(), unavail={'A01'})
        req = {'user_id': 'fan', 'rv': ['A30'], 'page': 'product', 'bought': set()}
        a, b = p.slates([req, req], history=[False, True])
        self.assertNotEqual(a, b)
        self.assertEqual(a, p.slates([req])[0])
        self.assertEqual(p.slates([{'user_id': 'fan', 'rv': [], 'page': 'home'}], history=[True]), [None])


class LiveRoutingTests(unittest.TestCase):
    def setUp(self):
        from recsys import live
        self.live = live; self.saved = (live.POLICY['variant'], live.ATP)
        live.ATP = PolicyTests().policy(); live.ATP.refresh(lambda sql: [], catalog(), unavail=set())
        users = [f'u{k}' for k in range(40)]
        self.t = next(u for u in users if live.treated(u)); self.c = next(u for u in users if not live.treated(u))
    def tearDown(self): self.live.POLICY['variant'], self.live.ATP = self.saved
    def req(self, u, rv=('A30',)): return {'request_id': 'r', 'user_id': u, 'rv': list(rv), 'page': 'product'}

    def test_variants_route_to_attr_only_when_asked(self):
        live = self.live; T, TA = live.VERSION_T, live.VERSION_TA
        expect = {'v1': (None, None), 'qrank': (None, None), 'qrank_aff': (None, None), 'attr': (T, T), 'attr_aff': (TA, TA),
                  'ab_attr': (T, None), 'ab_attr_aff': (TA, None)}
        for v, e in expect.items():
            live.POLICY['variant'] = v
            self.assertEqual((live.use_attr(self.req(self.t)), live.use_attr(self.req(self.c))), e, v)
        live.POLICY['variant'] = 'attr'
        self.assertIsNone(live.use_attr(self.req(self.t, rv=())))            # home never goes to attr_model

    def test_slates_versions_and_default_is_untouched(self):
        live = self.live; ver = {}
        live.POLICY['variant'] = 'v1'
        self.assertEqual(live.attr_slates([self.req(self.t)], set(), ver), {})
        live.POLICY['variant'] = 'ab_attr_aff'
        out = live.attr_slates([self.req(self.t), self.req(self.c), self.req(self.t, rv=())], {'A00'}, ver)
        self.assertEqual(sorted(out), [0]); self.assertEqual(ver, {0: live.VERSION_TA})
        self.assertEqual(len(set(out[0])), 10); self.assertNotIn('A00', out[0])   # out-of-stock is never shown

    def test_broken_or_missing_policy_falls_through(self):
        live = self.live; live.POLICY['variant'] = 'attr'; ver = {}
        live.ATP.slates = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        self.assertEqual(live.attr_slates([self.req(self.t)], set(), ver), {}); self.assertEqual(ver, {})
        live.ATP = None
        self.assertIsNone(live.use_attr(self.req(self.t)))
        self.assertEqual(live.attr_slates([self.req(self.t)], set(), ver), {})


if __name__ == '__main__':
    unittest.main()
