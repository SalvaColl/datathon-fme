import json, os, tempfile, unittest
import numpy as np
import pandas as pd

from recsys import live_quality as lqm, qrank
from tests.test_qrank import FakeModel, catalog


def counts(rows): return pd.DataFrame(rows, columns=['i', 'v', 'p']).set_index('i')


def history(cat, skip=()):
    # A-s0 products convert 10%, everything else 2%; 1,000 views each
    return counts([(i, 1000, 100 if i.startswith('A') and int(i[1:]) % 2 == 0 else 20) for i in cat.index if i not in skip])


class LiveQualityTests(unittest.TestCase):
    def test_old_product_barely_moves_and_new_product_follows_live_rate(self):
        cat = catalog(); h = history(cat, skip={'A03'})
        live = counts([('A01', 50, 10), ('A03', 400, 100)])            # A01 old (2% -> lucky 20%), A03 new and really 25%
        lq = lqm.LiveQuality().update(cat, h, live)
        self.assertLess(lq.rate['A01'], 0.03)                           # 1,000 historical views dominate 50 live ones
        self.assertGreater(lq.rate['A03'], 0.18)                        # new: live evidence dominates the prior
        self.assertEqual(lq.new, {'A03'})

    def test_new_product_without_views_gets_the_prior(self):
        cat = catalog(); h = history(cat, skip={'A03'})
        lq = lqm.LiveQuality().update(cat, h)
        self.assertAlmostEqual(lq.rate['A03'], 0.02, delta=0.005)       # rate of its subcategory A-s1
        lq = lqm.LiveQuality(prior=lambda c: np.full(len(c), 0.07)).update(cat, h)
        self.assertAlmostEqual(lq.rate['A03'], 0.07, places=6)

    def test_broken_prior_falls_back(self):
        cat = catalog()
        def boom(c): raise ValueError('no model')
        lq = lqm.LiveQuality(prior=boom).update(cat, history(cat))
        self.assertTrue(np.isfinite(lq.rate.values).all())

    def test_subcategory_multiplier_is_gated(self):
        cat = catalog(); h = history(cat)
        calm = counts([(i, 30, 1 if not i.startswith('A') or int(i[1:]) % 2 else 3) for i in cat.index])
        lq = lqm.LiveQuality().update(cat, h, None, calm)
        self.assertEqual(lq.hot, []); self.assertTrue((lq.multiplier(list(cat.index)) == 1).all())
        burst = calm.copy(); burst.loc[[i for i in cat.index if i.startswith('B') and int(i[1:]) % 2 == 0], 'p'] = 3   # B-s0: 2% -> 10%
        lq.update(cat, h, None, burst)
        self.assertEqual(lq.hot, ['B-s0'])
        m = lq.multiplier(['B00', 'B01', 'A00'])
        self.assertGreater(m[0], 2.0); self.assertLessEqual(m[0], lqm.MULT_CAP); self.assertEqual(list(m[1:]), [1.0, 1.0])

    def test_adjust_q_maps_new_products_with_beta_and_boosts_hot(self):
        cat = catalog(); h = history(cat, skip={'A02', 'A03'})
        rate = {i: (0.1 if i.startswith('A') and int(i[1:]) % 2 == 0 else 0.02) for i in cat.index}
        q = {i: 0.5 * rate[i] ** 2 for i in h.index}                    # carousel quality = organic rate squared
        live = counts([('A02', 2000, 200), ('A03', 2000, 400)])         # A02 like its shelf (10%), A03 ten times its shelf (20% vs 2%)
        lq = lqm.LiveQuality().update(cat, h, live, known=set(q))
        q2 = lq.adjust_q(q)
        self.assertEqual({k: q2[k] for k in q}, q)                      # nothing hot: old products untouched
        self.assertAlmostEqual(q2['A02'] / q['A00'], 1.0, delta=0.15)
        self.assertGreater(q2['A03'] / q['A01'], 50)                    # (0.2 / 0.02) ** 2, minus shrinkage
        lq.sub_mult = {'B-s0': 2.0}
        self.assertAlmostEqual(lq.adjust_q(q)['B00'], 2.0 * q['B00'])


class HookTests(unittest.TestCase):
    def setUp(self):
        self.cat = catalog(); self.h = history(self.cat, skip={'A39'})
        q = {i: 0.02 / (1 + int(i[1:])) for i in self.cat.index if i != 'A39'}      # A39 is new; qrank gives it a median q
        self.QR = qrank.Ranker(FakeModel(), q); self.QR.set_catalog(self.cat, set())
        self.tmp = tempfile.TemporaryDirectory(); self.policy = os.path.join(self.tmp.name, 'lq.json')
        self._old = (lqm.POLICY, dict(lqm._state), lqm.QR2, lqm.LQ)
        lqm.POLICY = self.policy; lqm._state.update(mode='off', mtime=None, checked=0.0)

        class Live:
            def item_frame(s): return pd.DataFrame({'it_v': [3000], 'it_a': [900], 'it_p': [900]}, index=['A39'])
        import threading
        self.calls = []
        def predict(reqs):
            sl = self.g['QR'].slates([{'user_id': r['user_id'], 'rv': r['rv'], 'page': 'product', 'bought': set()} for r in reqs])
            return [{'request_id': r['request_id'], 'items': s, 'model_version': 'v2-qrank-r1'} for r, s in zip(reqs, sl)]
        def query(sql):
            self.calls.append(sql)
            if 'new_product' in sql: return [{'i': 'A39', 'description': 'x'}]
            if 'shop.catalog' in sql: return [{'i': i, 'price': p} for i, p in self.cat.price.items()]
            return [{'i': 'A39', 'v': 100, 'p': 30}]
        self.g = dict(QR=self.QR, query=query, state={'cat': self.cat, 'unavail': set(), 'stock_out': set()}, feature_lock=threading.Lock(),
                      LIVE=Live(), BASE={'item': self.h.rename(columns={'v': 'it_v', 'p': 'it_p'})}, predict=predict, VERSION_Q='v2-qrank-r1')
        self.ctx = lqm.install(self.g, start_thread=False)
        self.reqs = [{'request_id': f'r{k}', 'user_id': f'u{k}', 'rv': ['A20']} for k in range(40)]

    def tearDown(self):
        lqm.POLICY, st, lqm.QR2, lqm.LQ = self._old; lqm._state.clear(); lqm._state.update(st); self.tmp.cleanup()

    def set_mode(self, m):
        with open(self.policy, 'w') as f: json.dump({'mode': m}, f)
        os.utime(self.policy, (1, 1 + len(m) + hash(m) % 1000)); lqm._state['checked'] = 0.0

    def test_off_is_identical_and_never_queries(self):
        base = [s for s in qrank.Ranker.slates(self.QR, [{'rv': ['A20'], 'page': 'product'}] * 3)]
        out = self.g['predict'](self.reqs[:3])
        self.assertEqual([a['items'] for a in out], base); self.assertTrue(all(a['model_version'] == 'v2-qrank-r1' for a in out))
        self.assertEqual(self.calls, [])

    def test_on_promotes_the_new_star_and_tags_the_version(self):
        self.assertTrue(lqm.refresh(self.g, self.ctx['desc'], self.ctx['base_price']))
        self.assertNotIn('A39', self.g['predict'](self.reqs[:1])[0]['items'])       # mode still off
        self.set_mode('on')
        out = self.g['predict'](self.reqs)
        for a in out:
            self.assertEqual(len(set(a['items'])), 10); self.assertEqual(a['model_version'], 'v2-qrank-r1+lq')
            self.assertIn('A39', a['items'][:3])                                    # 30% live rate: straight to the top (after the viewed item)

    def test_ab_splits_by_user_and_only_treated_change(self):
        lqm.refresh(self.g, self.ctx['desc'], self.ctx['base_price']); self.set_mode('ab')
        out = self.g['predict'](self.reqs)
        tr = [lqm.treated(r['user_id']) for r in self.reqs]
        self.assertTrue(5 < sum(tr) < 35)
        for a, t in zip(out, tr):
            self.assertEqual(a['model_version'].endswith('+lq'), t); self.assertEqual('A39' in a['items'], t)

    def test_stale_or_failing_live_data_falls_back_to_plain_qrank(self):
        lqm.refresh(self.g, self.ctx['desc'], self.ctx['base_price']); self.set_mode('on')
        lqm.LQ.updated -= 1000
        self.assertTrue(all(a['model_version'] == 'v2-qrank-r1' for a in self.g['predict'](self.reqs[:5])))
        lqm.LQ.updated += 1000
        class Broken:
            def slates(self, reqs): raise RuntimeError('boom')
        lqm.QR2 = Broken()
        out = self.g['predict'](self.reqs[:5])
        self.assertTrue(all(len(set(a['items'])) == 10 and a['model_version'] == 'v2-qrank-r1' for a in out))


if __name__ == '__main__':
    unittest.main()
