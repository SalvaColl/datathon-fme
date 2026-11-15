"""T-046: arm option "recart" — a product carted in the 60-day history AND again today keeps the larger cart contribution."""
import copy, math, unittest
import numpy as np
import pandas as pd

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF

# u1's history: carts never bought (B01 x1, B02 x2, B05 x5, B09 x4, B11 x2, B12 x3, B13 x2), one bought (B06), one only viewed (A07)
HIST = pd.DataFrame([('u1', 'B01', 2, 1, 0), ('u1', 'B02', 2, 2, 0), ('u1', 'B05', 6, 5, 0), ('u1', 'B06', 1, 1, 1), ('u1', 'A07', 4, 0, 0),
                     ('u1', 'B09', 4, 4, 0), ('u1', 'B11', 2, 2, 0), ('u1', 'B12', 3, 3, 0), ('u1', 'B13', 2, 2, 0)], columns=['u', 'i', 'v', 'a', 'p'])
CX = {"known": {"chn": 3.0}}
ARMS = [{"tag": "c", "w": CX}, {"tag": "rc", "w": CX, "recart": True}, {"tag": "b"}, {"tag": "brc", "recart": True}]
W_CL = COEF["known"]["w"]["cl"]; W_CHN = COEF["known"]["w"]["chn"]


def build(unavail=()):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None)
    lf.set_arms(ARMS)
    for p in ('B01', 'B02', 'B05', 'B06', 'B09', 'B12', 'B13', 'A10'): lf.add('u1', p, a=1)      # carted again today (A10: today only)
    return lf, aff


def req(user='u1', rv=('A30',), new=False, page='product'):
    return dict(user_id=user, rv=list(rv), page=page, is_new_user=new)


def score(lf, aff, model, **kw):
    S, s = lf.scores(req(**kw), lf.user_state(kw.get('user', 'u1')), aff, model)
    return {p: float(s[k]) for p, k in S.row.items()}


class RecartTests(unittest.TestCase):
    def test_recarted_product_keeps_the_larger_cart_contribution(self):
        lf, aff = build()
        c, rc = score(lf, aff, "c"), score(lf, aff, "rc")
        for p, n in (('B01', 1), ('B02', 2), ('B05', 5)):
            self.assertAlmostEqual(rc[p] - c[p], 3.0 * math.log1p(n) - W_CL, places=9)        # 0.98, 2.20, 4.28 with these weights
        # ...which is exactly the score the product had before it was carted again, when that was higher
        lf0, aff0 = build(); lf0.lcart['u1'].discard('B05')
        self.assertAlmostEqual(rc['B05'], score(lf0, aff0, "c")['B05'], places=9)
        changed = {p for p in c if rc[p] != c[p]}
        self.assertEqual(changed, {'B01', 'B02', 'B05', 'B09', 'B12', 'B13'})                 # A10 (carted only today) and B11 (history only) untouched
        self.assertEqual(rc['A10'], c['A10']); self.assertEqual(rc['B11'], c['B11'])

    def test_never_lowers_a_score(self):
        lf, aff = build()
        b, brc = score(lf, aff, "b"), score(lf, aff, "brc")                                    # committed weights: chn 1.2, cl 1.1
        self.assertEqual(brc['B01'], b['B01'])                                                # 1.2 * log(2) = 0.83 < 1.1: today's cart already wins
        self.assertAlmostEqual(brc['B02'] - b['B02'], W_CHN * math.log1p(2) - W_CL, places=9)
        self.assertTrue(all(brc[p] >= b[p] for p in b if np.isfinite(b[p])))

    def test_bought_products_stay_out_whatever_the_source(self):
        lf, aff = build()
        lf.add('u1', 'B12', p=1)                                           # bought today (event stream)
        lf.add('u1', 'B13', p=1, tp="2026-11-15 08:00:00.000")             # bought from our carousel (feedback path, live.refresh_feedback)
        st = lf.user_state('u1')
        self.assertTrue({'B06', 'B12', 'B13'} <= st[0]); self.assertFalse({'B06', 'B12', 'B13'} & st[1])
        rc = score(lf, aff, "rc")
        for p in ('B06', 'B12', 'B13'): self.assertEqual(rc[p], -np.inf)   # B06: bought in the history
        s = lf.slate(req(), st, aff, model="rc")
        self.assertEqual(len(set(s)), 10); self.assertFalse({'B06', 'B12', 'B13'} & set(s)); self.assertIn('B05', s[:3])

    def test_stock(self):
        lf, aff = build(unavail={'B09'})
        self.assertEqual(score(lf, aff, "rc")['B09'], -np.inf)
        s = lf.slate(req(), lf.user_state('u1'), aff, model="rc", exclude={'B05'})            # stock moved after the snapshot
        self.assertEqual(len(set(s)), 10); self.assertNotIn('B05', s); self.assertNotIn('B09', s)

    def test_other_cohorts_are_untouched(self):
        lf, aff = build()
        for kw in (dict(new=True), dict(page='home', rv=()), dict(page='home'), dict(rv=()), dict(user='u9'), dict(user='u9', new=True)):
            self.assertEqual(score(lf, aff, "rc", **kw), score(lf, aff, "c", **kw), kw)
            st = lf.user_state(kw.get('user', 'u1'))
            self.assertEqual(lf.slate(req(**kw), st, aff, model="rc"), lf.slate(req(**kw), st, aff, model="c"), kw)
        self.assertNotEqual(score(lf, aff, "rc", page='category'), score(lf, aff, "c", page='category'))      # category pages with views are in

    def test_option_off_is_the_control(self):
        lf, aff = build()
        self.assertEqual({k for k in lf.alt if k.endswith(lfm.RC)}, {"rc" + lfm.RC, "brc" + lfm.RC})
        lf2, aff2 = build(); lf2.set_arms([{"tag": "c", "w": CX}, {"tag": "rc", "w": CX}])       # same arm without the option
        self.assertFalse([k for k in lf2.alt if k.endswith(lfm.RC)])
        self.assertEqual(score(lf2, aff2, "rc"), score(lf, aff, "c"))
        self.assertEqual(score(lf, aff, None), score(lf2, aff2, None))                            # no arm: committed weights, no bonus
        for bad in (False, "yes", 1, "true"):
            self.assertEqual(live.clean_lfm_arms([{"tag": "c"}, {"tag": "rc", "recart": bad}]), [], bad)
        arms = live.clean_lfm_arms([{"tag": "c", "w": CX}, {"tag": "RC", "w": CX, "recart": True}])
        self.assertEqual(arms, [{"tag": "c", "w": CX}, {"tag": "rc", "w": CX, "recart": True}])
        self.assertEqual(live.clean_lfm_arms([{"tag": "c", "w": CX}]), [{"tag": "c", "w": CX}])   # arms without the key keep their exact shape

    def test_state_and_features_are_not_changed(self):
        lf, aff = build()
        st = lf.user_state('u1')
        self.assertEqual(len(st), 6); self.assertNotIn('B05', st[2]); self.assertIn('B05', st[1])   # served state still drops re-carted products from hc
        before = copy.deepcopy((st[0], st[1], st[2], lf.hcart))
        lf.scores(req(), st, aff, "rc")
        self.assertEqual(before, (st[0], st[1], st[2], lf.hcart))
        X = lfm.features(lf.snap, aff.affinity_all('u1', ['A30']), ['A30'], 'product', st[2], st[1])
        k = lf.snap.row['B05']; self.assertEqual((X[k, lfm.FEATS.index("chn")], X[k, lfm.FEATS.index("cl")]), (0.0, 1.0))   # features() as before

    def test_day_window_carts_moved_to_history_get_no_bonus_twice(self):
        lf, aff = build()
        lf.add('u1', 'B05', a=1, ta="2026-11-14 20:00:00.000"); lf.set_window("2026-11-15 00:00:00", "day")
        st = lf.user_state('u1')
        self.assertNotIn('B05', st[1]); self.assertEqual(st[2]['B05'], 6)                          # yesterday's cart: one more history cart
        S, c = lf.scores(req(), st, aff, "c"); _, rc = lf.scores(req(), st, aff, "rc")
        self.assertEqual(float(rc[S.row['B05']]), float(c[S.row['B05']]))

    def test_flag_survives_a_swap_of_alt_and_the_writer_labels_the_arm(self):
        saved = (live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'])
        try:
            lf, aff = build()
            arms = live.clean_lfm_arms([{"tag": "rc", "w": CX, "recart": True}])
            tmp = copy.copy(lf); tmp.set_arms(arms); lf.alt, lf.alt_lq, lf.alt_x = tmp.alt, tmp.alt_lq, tmp.alt_x     # how a validated reload installs arms
            live.LF = lf; live.AP = type('AP', (), {'aff': aff})(); live.POLICY['variant'] = 'lfm'; live.POLICY['lfm_arms'] = arms
            ver = {}; out = live.lfm_slates([dict(request_id='1', **req()), dict(request_id='2', **req(new=True))], set(), ver)
            self.assertEqual(ver, {0: 'v3-lfm-rc-k', 1: 'v3-lfm-rc-n'})
            self.assertEqual(out[0], lf.slate(req(), lf.user_state('u1'), aff, model="rc")); self.assertIn('B05', out[0][:3])
        finally:
            live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'] = saved

    def test_committed_policy_files_pass_the_writer(self):
        import json
        from pathlib import Path
        for name in ("cx3rc", "r3rc"):
            conf = json.loads((Path(lfm.HERE) / f"policy.rot_{name}.json").read_text())
            self.assertEqual(live.clean_lfm_arms(conf["lfm_arms"]), conf["lfm_arms"]); self.assertIs(conf["lfm_arms"][0]["recart"], True)
            self.assertNotIn("lq", conf["lfm_arms"][0])


if __name__ == "__main__":
    unittest.main()
