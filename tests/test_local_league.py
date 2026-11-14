import copy
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from tools import local_league as league
from tools.local_league import Catalog, boundaries, check_period, digest
from tools.league_metrics import evaluate, valid
from tools.league_policies import Popularity, train


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.base = [{'product_id': str(i), 'created_at': '2026-01-01', 'is_active': True,
                      'category': 'a', 'subcategory': 's', 'price_eur': 1} for i in range(12)]
        self.catalog = Catalog({'base': self.base, 'updates': []})
        self.rows = [{'request_id': str(i), 'ts': f'2026-02-01T{i:02}:00:00Z',
            'shown': [str(j) for j in range(10)], 'propensity': [.5]*10,
            'clicked': '0', 'purchased': '0' if i%2 else None, 'recent_views': []} for i in range(4)]

    def test_boundaries_and_leakage(self):
        c = {k: {'lo': '2026-01-01', 'hi': '2026-02-01'} for k in ('sessions', 'events')}
        b = boundaries(c)
        check_period([dict(request_id='a', ts=b[1])], b[1], b[2])
        with self.assertRaises(ValueError):
            check_period([dict(request_id='a', ts=b[1])], b[0], b[1])
        with self.assertRaises(ValueError):
            check_period(self.rows*2, '2026-01-01', '2026-03-01')

    def test_catalog_asof(self):
        updates = [{'product_id': '0', 'ts': '2026-02-02', 'change': 'out_of_stock', 'price_eur': 20},
                   {'product_id': '0', 'ts': '2026-02-03', 'change': 'back_in_stock', 'price_eur': 30}]
        c = Catalog({'base': self.base, 'updates': updates})
        self.assertEqual(c.at('2026-02-01')['0']['price_eur'], 1)
        self.assertNotIn('0', c.at('2026-02-02'))
        self.assertEqual(c.at('2026-02-03')['0']['price_eur'], 30)
        self.assertEqual(c.at('2025-01-01'), {})

    def test_policy_cache_stock_change(self):
        c = Catalog({'base': self.base, 'updates': [
            {'product_id': '0', 'ts': '2026-02-02', 'change': 'out_of_stock'}]})
        m = Popularity()
        m.fit({'best': [str(i) for i in range(12)]})
        self.assertEqual(m.recommend({}, {}, c.at('2026-02-01'))[0], '0')
        after = c.at('2026-02-02')
        self.assertNotIn('0', m.recommend({}, {}, after))
        self.assertTrue(valid(m.recommend({}, {}, after), after))
        # Backward replay must invalidate the cache as well.
        self.assertEqual(m.recommend({}, {}, c.at('2026-02-01'))[0], '0')

    def test_invalid(self):
        active = self.catalog.at('2026-02-01')
        for bad in [None, '0123456789', ['0']*10, [str(i) for i in range(9)], [str(i) for i in range(9)]+['unknown']]:
            self.assertFalse(valid(bad, active))
        class Bad:
            def recommend(self, *args):
                return ['0']*10
        result = evaluate({'bad': Bad()}, self.rows, self.catalog, 20)['results']['bad']
        self.assertEqual(result['invalid_outputs'], 4)
        self.assertFalse(result['eligible_for_comparison'])

    def test_no_labels_repeatability(self):
        class Spy:
            def recommend(inner, request, features, catalog):
                self.assertNotIn('shown', request)
                self.assertNotIn('clicked', request)
                self.assertNotIn('purchased', request)
                self.assertNotIn('propensity', request)
                return list(catalog)[:10]
        before = copy.deepcopy(self.rows)
        a = evaluate({'spy': Spy()}, self.rows, self.catalog, 100)
        b = evaluate({'spy': Spy()}, self.rows, self.catalog, 100)
        a['results']['spy'].pop('latency_ms')
        b['results']['spy'].pop('latency_ms')
        self.assertEqual(a, b)
        self.assertEqual(self.rows, before)
        self.assertEqual(a['results']['spy']['ESS'], 4)
        self.assertEqual(a['results']['spy']['IPS_slot1_buy'], 1)
        self.assertEqual(a['results']['spy']['SNIPS_slot1_buy'], .5)

    def test_training_independent(self):
        snapshot = {'best': [str(i) for i in range(12)], 'requests': self.rows}
        models = train(['baseline'], snapshot)
        snapshot['best'].reverse()
        self.assertEqual(models['baseline'].best[0], '0')
        self.assertEqual(digest({'b': 2, 'a': 1}), digest({'a': 1, 'b': 2}))

    def test_same_first_slot(self):
        models = [Popularity(mode) for mode in ['same_subcategory', 'mixed_category']]
        for model in models:
            model.fit({'best': [str(i) for i in range(12)]})
        req = {'recent_views': [{'product_id': '1'}]}
        outputs = [m.recommend(req, {}, self.catalog.at('2026-02-01')) for m in models]
        self.assertEqual(outputs[0][0], outputs[1][0])

    def test_snapshot_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            value = {'requests': self.rows}
            league.save(directory/'train.json', value)
            manifest = {'files': {'train.json': digest(value)}}
            self.assertEqual(league.load(directory, 'train.json', manifest), value)
            value['requests'][0]['purchased'] = 'tampered'
            league.save(directory/'train.json', value)
            with self.assertRaises(ValueError):
                league.load(directory, 'train.json', manifest)

    def test_validation_never_opens_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            snapshots = {
                'train.json': {'start': '2026-01-01', 'end': '2026-02-01', 'best': [str(i) for i in range(12)],
                               'requests': [{'request_id': 'train', 'ts': '2026-01-02'}]},
                'validation.json': {'requests': self.rows},
                'catalog.json': {'base': self.base, 'updates': [], 'limitation': 'fixture'}}
            manifest = {'boundaries': ['2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01'],
                        'files': {name: digest(v) for name, v in snapshots.items()}}
            for name, value in {**snapshots, 'manifest.json': manifest}.items():
                league.save(directory/name, value)
            # Deliberately no test file. Validation must still work.
            original = league.train
            def spy(names, training):
                self.assertEqual([r['request_id'] for r in training['requests']], ['train'])
                self.assertNotIn('test', training)
                return original(names, training)
            args = ['league', 'validation', '--cache', str(directory), '--policies', 'baseline', '--bootstrap', '10']
            with patch('sys.argv', args), patch.object(league, 'train', side_effect=spy), patch('builtins.print'):
                league.main()
            self.assertTrue((directory/'validation_report.json').exists())
            args[1] = 'freeze'
            with patch('sys.argv', args), patch('builtins.print'):
                league.main()
            args[1] = 'test'
            with patch('sys.argv', args):
                with self.assertRaises(FileNotFoundError):
                    league.main()
                # Fails closed: even unsuccessful first access is recorded.
                with self.assertRaises(ValueError):
                    league.main()
            args[1] = 'validation'
            with patch('sys.argv', args):
                with self.assertRaises(ValueError):
                    league.main()

    def test_propensity_and_exceptions(self):
        class Broken:
            def recommend(self, *args):
                raise RuntimeError('fixture')
        result = evaluate({'broken': Broken()}, self.rows, self.catalog, 10)
        self.assertEqual(result['results']['broken']['exceptions'], len(self.rows))
        self.assertIsNone(result['results']['broken']['SNIPS_slot1_buy'])
        rows = copy.deepcopy(self.rows)
        for row, p in zip(rows, [0, -1, float('nan'), 2]):
            row['propensity'] = [p]
        model = Popularity()
        model.fit({'best': [str(i) for i in range(12)]})
        result = evaluate({'p': model}, rows, self.catalog, 10)
        self.assertEqual(result['invalid_propensity_rows'], 4)
        self.assertEqual(result['results']['p']['ESS'], 0)


if __name__ == '__main__':
    unittest.main()
