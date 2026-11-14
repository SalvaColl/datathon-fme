import unittest
import numpy as np
import pandas as pd

from recsys import qrank, live


class FakeModel:
    """P(buy) = exp(lq) * 10 if viewed, halved per slot: enough to check ordering logic."""
    def predict_proba(self, X):
        p = np.exp(X[:, 1]) * np.where((X[:, 2] + X[:, 3]) > 0, 10, 1) * 0.5 ** X[:, 0]
        return np.column_stack([1 - p, p])


def catalog():
    rows = []
    for c in ('A', 'B'):
        for k in range(40):
            rows.append((f'{c}{k:02d}', c, f'{c}-s{k % 2}', 'brand', 10.0 + k))
    return pd.DataFrame(rows, columns=['product_id', 'category', 'sub', 'brand', 'price']).set_index('product_id')


def ranker(**kw):
    cat = catalog()
    q = {i: 0.02 / (1 + int(i[1:])) for i in cat.index}      # A00/B00 best, then decreasing
    r = qrank.Ranker(FakeModel(), q, **kw)
    r.set_catalog(cat, unavail={'A01'})
    return r


class QrankTests(unittest.TestCase):
    def test_ten_distinct_same_category_in_stock(self):
        slate = ranker().slates([{'rv': ['A30'], 'page': 'product'}])[0]
        self.assertEqual(len(set(slate)), 10)
        self.assertTrue(all(i.startswith('A') for i in slate))
        self.assertNotIn('A01', slate)

    def test_home_and_unknown_last_view_are_left_to_the_caller(self):
        out = ranker().slates([{'rv': [], 'page': 'home'}, {'rv': ['A03', 'ZZZ'], 'page': 'product'}])
        self.assertEqual(out, [None, None])

    def test_bought_items_are_excluded_even_if_viewed(self):
        slate = ranker().slates([{'rv': ['A00'], 'page': 'product', 'bought': {'A00', 'A02'}}])[0]
        self.assertNotIn('A00', slate)
        self.assertNotIn('A02', slate)

    def test_viewed_boost_and_live_recalibration(self):
        # A05 viewed: q/6 * 10 beats A00 when history is trusted; with a tiny viewed_factor it must not be first
        self.assertEqual(ranker(viewed_factor=1.0).slates([{'rv': ['A05'], 'page': 'product'}])[0][0], 'A05')
        self.assertEqual(ranker(viewed_factor=0.05).slates([{'rv': ['A05'], 'page': 'product'}])[0][0], 'A00')

    def test_new_product_without_history_gets_a_prior(self):
        r = ranker(); cat = catalog(); cat.loc['Anew'] = ['A', 'A-s0', 'brand', 12.0]
        r.set_catalog(cat)
        self.assertTrue(np.isfinite(r.lq['Anew']))


class LiveRoutingTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.QR, live.POLICY['variant'])
        live.QR = ranker()
        live.BOUGHT.clear()

    def tearDown(self):
        live.QR, live.POLICY['variant'] = self.saved

    def reqs(self):
        return [{'request_id': 'r1', 'user_id': 'u1', 'rv': ['A30'], 'page': 'product'},
                {'request_id': 'r2', 'user_id': 'u2', 'rv': [], 'page': 'home'}]

    def test_v1_variant_never_uses_qrank(self):
        live.POLICY['variant'] = 'v1'
        self.assertEqual(live.qrank_slates(self.reqs(), set()), {})

    def test_qrank_variant_answers_only_requests_with_views(self):
        live.POLICY['variant'] = 'qrank'
        out = live.qrank_slates(self.reqs(), {'A00'})
        self.assertEqual(list(out), [0])
        self.assertEqual(len(set(out[0])), 10)
        self.assertNotIn('A00', out[0])          # live stock-outs are excluded

    def test_bought_today_is_excluded(self):
        live.POLICY['variant'] = 'qrank'
        live.BOUGHT['u1'].add('A02')
        self.assertNotIn('A02', live.qrank_slates(self.reqs(), set())[0])

    def test_tuning_arms_split_users_and_label_versions(self):
        live.POLICY['variant'] = 'qrank'
        saved = live.POLICY['qrank_arms']
        try:
            live.POLICY['qrank_arms'] = live.clean_arms([{'tag': 'vf005', 'viewed_factor': 0.05}, {'tag': 'vf100', 'viewed_factor': 1.0}])
            reqs = [{'request_id': f'r{k}', 'user_id': f'u{k}', 'rv': ['A05'], 'page': 'product'} for k in range(40)]
            versions = {}
            out = live.qrank_slates(reqs, set(), versions)
            self.assertEqual(len(out), 40)
            self.assertEqual(set(versions.values()), {'v2-qrank-vf005', 'v2-qrank-vf100'})
            for k, v in versions.items():      # the arm really changes the ranking: A05 first only when viewed counts fully
                self.assertEqual(out[k][0], 'A05' if v.endswith('vf100') else 'A00')
        finally:
            live.POLICY['qrank_arms'] = saved

    def test_invalid_arms_are_ignored(self):
        self.assertEqual(live.clean_arms([{'tag': 'only', 'viewed_factor': 1.0}]), [])
        self.assertEqual(live.clean_arms([{'tag': 'a', 'viewed_factor': 9}, {'tag': 'b!', 'viewed_factor': 1}]), [])

    def test_qrank_failure_falls_back_to_gbm_path(self):
        live.POLICY['variant'] = 'qrank'
        live.QR.model = None                      # predict_proba will raise
        self.assertEqual(live.qrank_slates(self.reqs(), set()), {})


if __name__ == '__main__':
    unittest.main()
