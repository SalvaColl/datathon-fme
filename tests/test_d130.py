import json, os, tempfile, unittest
import pandas as pd

from recsys import d130, home_cands


def catalog():
    rows = [(f'{c}{k:02d}', c, f'{c}-s{k % 2}') for c in ('A', 'B', 'C') for k in range(30)]
    return pd.DataFrame(rows, columns=['product_id', 'category', 'sub']).set_index('product_id')


def history():
    rows = [('pop', i, 100, 30, 20 if i.endswith('00') else 5) for i in catalog().index]   # x00 items convert best
    rows += [('u1', 'A05', 3, 1, 1),      # bought
             ('u1', 'A06', 2, 1, 0),      # carted, not bought
             ('u1', 'A07', 4, 0, 0),      # viewed, never carted -> stale
             ('u1', 'B03', 1, 0, 0)]
    return pd.DataFrame(rows, columns=['u', 'i', 'v', 'a', 'p'])


def index(unavail=()):
    hc = home_cands.HomeCands(history(), catalog()); hc.refresh(catalog(), set(unavail)); return hc


class HomeCandsTests(unittest.TestCase):
    def test_slate_is_ten_distinct_in_stock_and_never_dead(self):
        hc = index(unavail={'A00'}); slate = hc.slate('u1')
        self.assertEqual(len(slate), 10); self.assertEqual(len(set(slate)), 10)
        self.assertFalse({'A00', 'A05', 'A07'} & set(slate))        # out of stock, bought, stale view

    def test_pending_cart_first_then_affine_category(self):
        slate = index().slate('u1')
        self.assertEqual(slate[0], 'A06')
        self.assertTrue(all(i.startswith('A') for i in slate[:5]))  # 9 of u1's 10 views are in category A

    def test_unknown_user_gets_best_converting_items(self):
        slate = index().slate('nobody')
        self.assertEqual(len(set(slate)), 10)
        self.assertEqual(set(slate[:3]), {'A00', 'B00', 'C00'})

    def test_live_purchase_kills_item_and_live_cart_promotes_it(self):
        hc = index(); hc.add('u1', 'A06', 0, 0, 1); hc.add('u1', 'A10', 1, 1, 0)
        self.assertTrue(hc.is_dead('u1', 'A06')); self.assertNotIn('A06', hc.slate('u1'))
        self.assertEqual(hc.slate('u1')[0], 'A10')

    def test_drop_dead_keeps_order_and_unknown_items(self):
        self.assertEqual(index().drop_dead('u1', ['A05', 'A01', 'A07', 'A06', 'NEW']), ['A01', 'A06', 'NEW'])
        self.assertEqual(index().drop_dead('nobody', ['A05', 'A07']), ['A05', 'A07'])

    def test_few_candidates_are_padded(self):
        hc = home_cands.HomeCands(history(), catalog()); hc.refresh(catalog().iloc[:12], set())
        self.assertEqual(len(set(hc.slate('u1'))), 10)


class FakeLive(dict):
    def add(self, u, i, v, a, p): self.setdefault('calls', []).append((u, i, v, a, p))


class FakeFe: C = catalog()


def fake_writer():
    g = dict(fe=FakeFe, LIVE=FakeLive(), state=dict(unavail=set(), stock_out={'B00'}))
    g['make_pools'] = lambda cat, unavail, T=None: ('pools', 'best')
    g['candidates'] = lambda req, *a: ['A05', 'A06', 'A07', 'A01']
    def predict(reqs):
        return [dict(request_id=r['request_id'], items=g['candidates'](r)[:10] if r['rv'] else list('abcdefghij'), model_version='v1') for r in reqs]
    g['predict'] = predict
    return g


REQS = [dict(request_id='r1', user_id='u1', rv=['A01']), dict(request_id='r2', user_id='u1', rv=[]), dict(request_id='r3', user_id='nobody', rv=[])]


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d130.POLICY = os.path.join(self.tmp.name, 'd130.json')
        d130._state.update(mode='off', mtime=None, checked=0.0, errors=0)
        self.g = fake_writer(); d130.install(self.g, history()); self.g['make_pools'](catalog(), set())
    def tearDown(self): self.tmp.cleanup()
    def set_mode(self, m):
        with open(d130.POLICY, 'w') as f: json.dump(dict(mode=m), f)
        d130._state['checked'] = 0.0

    def test_off_or_missing_file_changes_nothing(self):
        expected = fake_writer()['predict'](REQS)
        self.assertEqual(self.g['predict'](REQS), expected)
        self.set_mode('garbage'); self.assertEqual(self.g['predict'](REQS), expected)

    def test_nodead_filters_candidates_and_tags_only_those_answers(self):
        self.set_mode('nodead'); out = {a['request_id']: a for a in self.g['predict'](REQS)}
        self.assertEqual(out['r1']['items'], ['A06', 'A01']); self.assertEqual(out['r1']['model_version'], 'v1+nd')
        self.assertEqual(out['r2']['items'], list('abcdefghij')); self.assertEqual(out['r2']['model_version'], 'v1')

    def test_home_replaces_only_requests_without_views(self):
        self.set_mode('home'); out = {a['request_id']: a for a in self.g['predict'](REQS)}
        self.assertEqual(out['r1']['model_version'], 'v1+nd')
        for rid in ('r2', 'r3'):
            self.assertEqual(out[rid]['model_version'], 'v1+home'); self.assertEqual(len(set(out[rid]['items'])), 10)
            self.assertNotIn('B00', out[rid]['items'])                  # stock_out respected
        self.assertEqual(out['r2']['items'][0], 'A06')

    def test_events_reach_both_tables_and_errors_fall_back(self):
        self.g['LIVE'].add('u1', 'A06', 0, 0, 1)
        self.assertEqual(self.g['LIVE']['calls'], [('u1', 'A06', 0, 0, 1)]); self.assertTrue(d130.HC.is_dead('u1', 'A06'))
        self.set_mode('home'); d130.HC.snap = None                      # break the index: every hook path must fall back
        out = {a['request_id']: a for a in self.g['predict'](REQS)}
        self.assertEqual(out['r2']['items'], list('abcdefghij')); self.assertEqual(len(out), 3)


if __name__ == '__main__':
    unittest.main()
