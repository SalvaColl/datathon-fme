import copy
import unittest
from tools.content_linear import ContentLinear, heldout_ids
from tools.league_metrics import valid


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {str(i): dict(product_id=str(i), description='coffee beans roast' if i % 2 else 'garden flowers seed',
                                    category=str(i % 2), subcategory=str(i % 3), brand=str(i % 4),
                                    price_eur=i + 1, created_at='2026-01-01', is_active=True) for i in range(22)}
        self.training = dict(start='2026-02-01', end='2026-03-01', catalog=self.catalog,
                             best=list(self.catalog), organic_events=[], requests=[
                                 dict(request_id=str(i), ts=f'2026-02-{i+2:02}', user_id='u',
                                      recent_views=[dict(product_id='1')], shown=list(self.catalog)[:10],
                                      purchased='1' if i % 2 else None) for i in range(12)])
        self.request = dict(ts='2026-03-02', user_id='unknown', recent_views=[dict(product_id='1')])

    def test_learned_unique_and_no_id_coefficients(self):
        model = ContentLinear().fit(self.training)
        self.assertEqual(model.diagnostics['exposed_rows'], 120)
        self.assertEqual(model.diagnostics['purchase_positives'], 6)
        self.assertTrue(valid(model.recommend(self.request, {}, self.catalog), self.catalog))
        self.assertFalse(any('user_id' in f or 'product_id' in f for f in model.context.feature_names_))

    def test_missing_text_unknown_and_mutable_stock(self):
        t = copy.deepcopy(self.training)
        for row in t['catalog'].values():
            row['description'] = None
        model = ContentLinear().fit(t)
        slate = model.recommend(dict(ts='2026-03-02', recent_views=[dict(product_id='absent')]), {}, self.catalog)
        self.assertEqual(len(slate), 10)
        self.catalog[slate[0]]['is_active'] = False
        self.assertNotIn(slate[0], model.recommend(self.request, {}, self.catalog))
        self.catalog['new'] = dict(product_id='new', description='coffee roast', price_eur=2, is_active=True, created_at='2026-03-01')
        self.assertTrue(valid(model.recommend(self.request, {}, self.catalog), self.catalog))

    def test_strict_event_replay_and_future_views(self):
        class Spy(ContentLinear):
            def _design(inner, request, *args, **kwargs):
                if request['request_id'] == '0':
                    self.assertFalse(inner.history)
                return super(Spy, inner)._design(request, *args, **kwargs)
        t = copy.deepcopy(self.training)
        t['organic_events'] = [dict(ts='2026-02-02', user_id='u', product_id='1', event_type='purchase')]
        model = Spy().fit(t)
        self.assertTrue(model.history['u'])
        r = dict(self.request, recent_views=[dict(product_id='1', ts='2027-01-01')])
        self.assertEqual(model._views(r), [])
        with self.assertRaises(ValueError):
            model.recommend(dict(ts='2026-02-10'), {}, self.catalog)

    def test_only_exposed_labels_and_single_class_fallback(self):
        t = copy.deepcopy(self.training)
        for r in t['requests']:
            r['purchased'] = 'unshown'
        model = ContentLinear().fit(t)
        self.assertEqual(model.diagnostics['purchase_positives'], 0)
        self.assertIsNone(model.model)
        self.assertTrue(valid(model.recommend(self.request, {}, self.catalog), self.catalog))

    def test_mask_is_training_only_and_vocab_is_historical(self):
        t = copy.deepcopy(self.training)
        t['withheld_product_ids'] = ['1']
        t['catalog']['1']['description'] = 'neverlearnthisword'
        model = ContentLinear().fit(t)
        self.assertNotIn('neverlearnthisword', model.text.vocabulary_)
        self.assertEqual(model.diagnostics['purchase_positives'], 0)
        self.assertEqual(len(model._views(self.request)), 1)
        self.assertEqual(heldout_ids(self.catalog), heldout_ids(self.catalog))

    def test_invalid_training_and_impossible_inventory(self):
        t = copy.deepcopy(self.training)
        t['organic_events'] = [dict(ts='2026-03-01', product_id='1')]
        with self.assertRaises(ValueError):
            ContentLinear().fit(t)
        model = ContentLinear(False).fit(self.training)
        with self.assertRaises(ValueError):
            model.recommend(self.request, {}, dict(list(self.catalog.items())[:9]))


if __name__ == '__main__':
    unittest.main()
