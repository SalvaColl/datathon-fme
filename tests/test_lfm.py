import unittest
import numpy as np
import pandas as pd

from recsys import lfm, live


class FakeAff:
    """Stand-in for attr_affinity.AttrAffinity: 2 phrases per product, affinity = share of the user's phrase mass."""
    def __init__(self, ids, taste=None):
        self.pid = {p: k for k, p in enumerate(ids)}
        self.A = np.zeros((len(ids), 20), dtype=np.float32)
        for k in range(len(ids)): self.A[k, [k % 20, (k + 1) % 20]] = 1
        self.taste = taste or {}
    def affinity_all(self, u, rv=()):
        t = self.taste.get(u)
        return np.full(len(self.A), 0.10) if t is None else np.where(self.A[:, t] > 0, 0.30, 0.05)


def catalog():
    rows = [(f'{c}{k:02d}', c, f'{c}-s{k % 2}', f'b{k % 3}', 10.0 + k) for c in ('A', 'B') for k in range(40)]
    return pd.DataFrame(rows, columns=['product_id', 'category', 'sub', 'brand', 'price']).set_index('product_id')


COEF = {s: dict(w=dict(aff10=2.0, chn=1.2, cl=cl, islast=1.9, oinrv=1.8, ssub2=1.3, scat2=1.0, na=0.3, home=-0.3, lq=0.5, sbrand=0.1), b=-9.0)
        for s, cl in (('known', 1.1), ('new', 2.2))}
HIST = pd.DataFrame([('u1', 'B05', 3, 2, 0), ('u1', 'B06', 1, 1, 1), ('u1', 'A07', 4, 0, 0)], columns=['u', 'i', 'v', 'a', 'p'])


def build(taste=None, unavail=(), hc=None):
    cat = catalog(); aff = FakeAff(list(cat.index), taste)
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, hc)
    return lf, aff


def slate(lf, aff, user='u9', rv=('A30',), new=False, page='product', exclude=()):
    req = dict(user_id=user, rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state(user), aff, exclude=exclude)


class LfmTests(unittest.TestCase):
    def test_ten_distinct_in_stock_last_view_first(self):
        lf, aff = build(unavail={'A01'})
        s = slate(lf, aff)
        self.assertEqual(len(set(s)), 10); self.assertNotIn('A01', s); self.assertIn('A30', s[:3])

    def test_exclude_argument_is_respected(self):
        lf, aff = build()
        s = slate(lf, aff, exclude={'A30', 'A00'})
        self.assertEqual(len(set(s)), 10); self.assertFalse({'A30', 'A00'} & set(s))

    def test_history_cart_shown_and_bought_never_shown(self):
        lf, aff = build()
        s = slate(lf, aff, user='u1', rv=('B05', 'B06', 'A30'))
        self.assertIn('B05', s)          # carted twice in the history, never bought
        self.assertNotIn('B06', s)       # bought: dead, even though it is in the recent views

    def test_live_cart_goes_up_and_live_purchase_removes_it(self):
        lf, aff = build()
        lf.add('u9', 'B11', 1, 1, 0)
        self.assertIn('B11', slate(lf, aff, new=True)[:3])       # other category, still near the top
        lf.add('u9', 'B11', 0, 0, 1)
        self.assertNotIn('B11', slate(lf, aff, new=True))

    def test_taste_beats_generic_quality_for_returning_shoppers(self):
        lf, aff = build(taste={'u9': 7})
        s = slate(lf, aff)
        liked = [p for p in s if aff.A[aff.pid[p], 7] > 0]
        self.assertGreaterEqual(len(liked), 4)                   # the 8 products carrying phrase 7 dominate the slate

    def test_home_without_views_still_answers(self):
        lf, aff = build()
        s = slate(lf, aff, rv=(), page='home')
        self.assertEqual(len(set(s)), 10)

    def test_stale_history_views_are_dropped_unless_carted(self):
        from recsys import home_cands
        hc = home_cands.HomeCands(HIST, catalog())
        lf, aff = build(hc=hc)
        s = slate(lf, aff, user='u1', rv=('A07',))
        self.assertNotIn('A07', s)       # viewed 4 times in the history, never carted: dead even as last view
        self.assertIn('B05', s)

    def test_unknown_products_in_views_do_not_break(self):
        lf, aff = build()
        self.assertEqual(len(set(slate(lf, aff, rv=('ZZZ',)))), 10)
        self.assertEqual(len(set(slate(lf, aff, rv=('A03', 'ZZZ')))), 10)

    def test_committed_coefficients_load(self):
        lf = lfm.LiveFit.load()
        self.assertEqual(set(lf.w), {'known', 'new'}); self.assertEqual(len(lf.w['known']), len(lfm.FEATS))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.POLICY['variant'], live.LF, live.AP)
        lf, aff = build()
        live.LF = lf; live.AP = type('AP', (), {'aff': aff})()
    def tearDown(self):
        live.POLICY['variant'], live.LF, live.AP = self.saved

    def test_default_variant_never_routes_to_lfm(self):
        live.POLICY['variant'] = 'v1'
        self.assertEqual(live.lfm_slates([dict(request_id='r', user_id='u9', rv=['A30'], page='product')], set(), {}), {})

    def test_lfm_variant_tags_segment_in_model_version(self):
        live.POLICY['variant'] = 'lfm'
        reqs = [dict(request_id='a', user_id='u9', rv=['A30'], page='product', is_new_user=False),
                dict(request_id='b', user_id='u8', rv=[], page='home', is_new_user=True)]
        ver = {}; out = live.lfm_slates(reqs, {'A00'}, ver)
        self.assertEqual(set(out), {0, 1}); self.assertNotIn('A00', out[0])
        self.assertEqual(ver, {0: live.VERSION_L + '-k', 1: live.VERSION_L + '-nh'})
        self.assertFalse(live.use_qrank(reqs[0]))

    def test_ab_lfm_splits_by_user_and_control_keeps_qrank(self):
        live.POLICY['variant'] = 'ab_lfm'
        users = [f'u{k}' for k in range(40)]
        t = [u for u in users if live.treated(u)]
        self.assertTrue(0 < len(t) < 40)
        for u in users:
            r = dict(request_id='r', user_id=u, rv=['A30'], page='product')
            self.assertEqual(live.use_lfm(r), live.treated(u)); self.assertEqual(live.use_qrank(r), not live.treated(u))

    def test_lfm_failure_falls_back_to_old_path(self):
        live.POLICY['variant'] = 'lfm'; live.LF.snap = None
        self.assertEqual(live.lfm_slates([dict(request_id='r', user_id='u9', rv=['A30'], page='product')], set(), {}), {})


class ArmTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'])
        lf, aff = build()
        live.LF = lf; live.AP = type('AP', (), {'aff': aff})(); live.POLICY['variant'] = 'lfm'
    def tearDown(self):
        live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'] = self.saved

    def arms(self, raw):
        arms = live.clean_lfm_arms(raw); live.LF.set_arms(arms); live.POLICY['lfm_arms'] = arms; return arms

    def test_bad_arm_lists_are_rejected(self):
        self.assertEqual(live.clean_lfm_arms([{'tag': 'only'}]), [{'tag': 'only'}])                     # one arm = tuned weights left in place
        self.assertEqual(live.clean_lfm_arms([{'tag': x} for x in 'abcde']), [])                        # more than 4
        self.assertEqual(live.clean_lfm_arms([{'tag': 'a'}, {'tag': 'a'}]), [])                         # duplicate tag
        self.assertEqual(live.clean_lfm_arms([{'tag': 'a'}, {'tag': 'b', 'w': {'known': {'nope': 1}}}]), [])
        self.assertEqual(live.clean_lfm_arms([{'tag': 'a'}, {'tag': 'b', 'file': '../secrets.json'}]), [])
        self.assertEqual(live.clean_lfm_arms([{'tag': 'a'}, {'tag': 'b', 'w': {'new': {'cl': 99}}}]), [])
        self.assertEqual(len(live.clean_lfm_arms([{'tag': 'a'}, {'tag': 'B2', 'w': {'new': {'cl': 3}}}])), 2)

    def test_arms_split_users_and_label_versions(self):
        self.arms([{'tag': 'r1'}, {'tag': 'x1', 'w': {'known': {'islast': 5.0}}}])
        reqs = [dict(request_id=str(k), user_id=f'u{k}', rv=['A30'], page='product', is_new_user=False) for k in range(40)]
        ver = {}; out = live.lfm_slates(reqs, set(), ver)
        self.assertEqual(len(out), 40)
        self.assertEqual(set(ver.values()), {'v3-lfm-r1-k', 'v3-lfm-x1-k'})
        self.assertTrue(all(out[k][0] == 'A30' for k in out if ver[k] == 'v3-lfm-x1-k'))             # the override acts

    def test_override_changes_only_that_arm_and_control_equals_no_arms(self):
        base = slate(live.LF, live.AP.aff, user='u1', rv=('B05', 'A30'))
        self.arms([{'tag': 'r1'}, {'tag': 'x1', 'w': {'known': {'chn': -5.0}}}])
        req = dict(user_id='u1', rv=['B05', 'A30'], page='product', is_new_user=False)
        st = live.LF.user_state('u1')
        self.assertEqual(live.LF.slate(req, st, live.AP.aff, model='r1'), base)
        self.assertNotIn('B05', live.LF.slate(req, st, live.AP.aff, model='x1')[:1])

    def test_arm_from_committed_r2_file(self):
        arms = self.arms([{'tag': 'r1'}, {'tag': 'r2', 'file': 'lfm_coef_r2.json'}])
        self.assertEqual(len(arms), 2)
        req = dict(user_id='u9', rv=['A30'], page='product', is_new_user=True, device='android', region='Murcia')
        self.assertEqual(len(set(live.LF.slate(req, live.LF.user_state('u9'), live.AP.aff, model='r2'))), 10)

    def test_no_arms_keeps_the_original_label(self):
        ver = {}; live.lfm_slates([dict(request_id='a', user_id='u9', rv=['A30'], page='product')], set(), ver)
        self.assertEqual(ver, {0: live.VERSION_L + '-k'})


class R2FeatureTests(unittest.TestCase):
    def test_bought_today_features_and_old_state_tuple(self):
        lf, aff = build()
        lf.add('u9', 'B11', 0, 0, 1)
        st = lf.user_state('u9'); self.assertEqual(st[3], {'B11'})
        S = lf.snap
        X = lfm.features(S, aff.affinity_all('u9'), ['A30'], 'product', {}, set(), bought_today=st[3])
        k = S.row['B11']; nb = lfm.FEATS.index('nbp'); bs = lfm.FEATS.index('bsub')
        self.assertEqual(X[k, nb], 0); self.assertEqual(X[S.row['B31'], nb], 2); self.assertEqual(X[S.row['B13'], bs], 1)
        req = dict(user_id='u9', rv=['A30'], page='product', is_new_user=True)
        self.assertEqual(len(set(lf.slate(req, st[:3], aff))), 10)                     # 3-tuple state still accepted

    def test_r1_weights_ignore_the_new_features(self):
        lf, aff = build()
        a = slate(lf, aff, new=True)
        lf.add('u9', 'B11', 0, 0, 1)
        self.assertEqual(slate(lf, aff, new=True), a)                                  # COEF has no r2 weights -> same slate


class R3CategoryMixTests(unittest.TestCase):
    def test_mix_counts_history_and_todays_views(self):
        lf, aff = build()
        cv, sv = lf.user_mix('u1'); A, B = lf.ccode['A'], lf.ccode['B']
        self.assertEqual((cv[A], cv[B], cv.sum(), sv.sum()), (4, 4, 8, 8))            # HIST: B05 x3, B06 x1, A07 x4
        lf.add('u1', 'A10', 2, 0, 0); lf.add('u9', 'B02', 1, 0, 0); lf.add('u1', 'ZZ9', 5, 0, 0)   # unknown product: ignored
        self.assertEqual(lf.user_mix('u1')[0][A], 6); self.assertEqual(lf.user_mix('u9')[0][B], 1)
        self.assertEqual(lf.user_mix('nobody')[0].sum(), 0)
        self.assertEqual(lf.user_mix('u1', asof={'B03': 4})[0][B], 8)                 # as-of view replaces the live counter

    def test_feature_is_zero_without_views_and_follows_the_favourite_category(self):
        lf, aff = build(); S = lf.snap; uc = lfm.FEATS.index('ucat'); us = lfm.FEATS.index('usub')
        X0 = lfm.features(S, aff.affinity_all('u9'), [], 'product', {}, set(), mix=lf.user_mix('nobody'))
        self.assertTrue(np.allclose(X0[:, [uc, us]], 0))
        for _ in range(20): lf.add('u9', 'B02', 1, 0, 0)
        X = lfm.features(S, aff.affinity_all('u9'), [], 'product', {}, set(), mix=lf.user_mix('u9'))
        self.assertGreater(X[S.row['B10'], uc], 0.5); self.assertLess(X[S.row['A10'], uc], 0)
        self.assertGreater(X[S.row['B10'], us], X[S.row['B11'], us])                  # B02 and B10 share the subcategory

    def test_weights_move_the_slate_to_the_favourite_category_and_old_files_do_not(self):
        lf, aff = build()
        for _ in range(20): lf.add('u9', 'B02', 1, 0, 0)
        base = slate(lf, aff, rv=())
        coef = {s: dict(w=dict(COEF[s]['w'], ucat=4.0, usub=1.3), b=COEF[s]['b']) for s in COEF}
        lf.add_model('r3', coef)
        req = dict(user_id='u9', rv=[], page='product', is_new_user=False)
        s3 = lf.slate(req, lf.user_state('u9'), aff, model='r3')
        self.assertTrue(all(p.startswith('B') for p in s3)); self.assertFalse(all(p.startswith('B') for p in base))
        self.assertEqual(slate(lf, aff, rv=()), base)

    def test_codes_survive_a_catalog_refresh_with_new_products(self):
        lf, aff = build(); before = dict(lf.icode)
        cat = catalog(); cat.loc['C00'] = ('C', 'C-s0', 'b0', 5.0); aff2 = FakeAff(list(cat.index))
        lf.set_catalog(cat, set(), aff2, {})
        self.assertEqual({p: lf.icode[p] for p in before}, before); self.assertIn('C00', lf.icode)
        self.assertEqual(lf.user_mix('u1')[0].sum(), 8)
        self.assertEqual(len(set(slate(lf, aff2, user='u1'))), 10)

    def test_committed_r3_file_is_a_valid_arm(self):
        self.assertEqual(live.clean_lfm_arms([{'tag': 'r1'}, {'tag': 'r3', 'file': 'lfm_coef_r3.json'}])[1]['file'], 'lfm_coef_r3.json')
        import json; c = json.loads((lfm.HERE / 'lfm_coef_r3.json').read_text())
        self.assertTrue(set(c['known']['w']) <= set(lfm.FEATS)); self.assertGreater(c['known']['w']['ucat'], 0)


if __name__ == '__main__':
    unittest.main()
