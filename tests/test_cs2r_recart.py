"""T-051: cs2r with "recart": true (policy.rot_cs2rrc.json) and the user-split pair cs2rc0 / cs2rc1 (policy.rot_cs2rab.json).
cs2r has chn 3.0 and cl 3.0 for returning shoppers, so a history cart counted n times that is carted again today drops from
3 * log1p(n) to 3: nothing to keep at n = 1 (2.08 < 3), +0.296 at n = 2, +2.375 at n = 5."""
import copy, json, math, unittest, zlib
from pathlib import Path
import numpy as np
import pandas as pd

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF

# u1: carts never bought B01 x1, B02 x2, B05 x5, B11 x2 (history only); B06 bought in the history; B12 x3, B13 x2 bought later
HIST = pd.DataFrame([('u1', 'B01', 2, 1, 0), ('u1', 'B02', 2, 2, 0), ('u1', 'B05', 6, 5, 0), ('u1', 'B06', 1, 1, 1), ('u1', 'A07', 4, 0, 0),
                     ('u1', 'B11', 2, 2, 0), ('u1', 'B12', 3, 3, 0), ('u1', 'B13', 2, 2, 0), ('u1', 'B09', 4, 4, 0)], columns=['u', 'i', 'v', 'a', 'p'])
POL = lambda name: json.loads((Path(lfm.HERE) / f"policy.rot_{name}.json").read_text())
CTL, RC, AB = POL("cs2r"), POL("cs2rrc"), POL("cs2rab")
ARMS = live.clean_lfm_arms([CTL["lfm_arms"][0], RC["lfm_arms"][0]])
KEEP = lambda n: max(0.0, 3.0 * math.log1p(n) - 3.0)
COHORTS = (dict(new=True), dict(new=True, page='category'), dict(page='home', rv=()), dict(page='home'), dict(rv=()), dict(new=True, rv=(), page='home'),
           dict(user='u9'), dict(user='u9', new=True), dict(user='u9', rv=(), page='home'))


def build(unavail=(), arms=ARMS, recarted=('B01', 'B02', 'B05', 'B09', 'B12', 'B13', 'A10')):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None)
    lf.set_arms(arms)
    for p in recarted: lf.add('u1', p, a=1)          # carted today (A10: today only)
    return lf, aff


def req(user='u1', rv=('A30',), new=False, page='product'):
    return dict(user_id=user, rv=list(rv), page=page, is_new_user=new)


def score(lf, aff, model, **kw):
    S, s = lf.scores(req(**kw), lf.user_state(kw.get('user', 'u1')), aff, model)
    return {p: float(s[k]) for p, k in S.row.items()}


class Cs2rRecartTests(unittest.TestCase):
    def test_policy_is_cs2r_plus_the_option_and_nothing_else(self):
        ctl, rc = CTL["lfm_arms"][0], RC["lfm_arms"][0]
        self.assertEqual(len(CTL["lfm_arms"]), 1); self.assertEqual(len(RC["lfm_arms"]), 1)
        self.assertEqual({k: v for k, v in rc.items() if k not in ("tag", "recart")}, {k: v for k, v in ctl.items() if k != "tag"})
        self.assertIs(rc["recart"], True); self.assertNotEqual(rc["tag"], ctl["tag"])
        self.assertEqual({k: v for k, v in RC.items() if k != "lfm_arms"}, {k: v for k, v in CTL.items() if k != "lfm_arms"})
        self.assertEqual(ctl["w"]["known"]["chn"], 3.0); self.assertEqual(ctl["w"]["known"]["cl"], 3.0)
        for a in (rc,): self.assertFalse({"lq", "explore"} & set(a))
        self.assertEqual(live.clean_lfm_arms(RC["lfm_arms"]), RC["lfm_arms"])
        # user-split pair: fresh tags for both, control = cs2r exactly, challenger = control + option
        a0, a1 = AB["lfm_arms"]
        self.assertEqual(live.clean_lfm_arms(AB["lfm_arms"]), AB["lfm_arms"])
        self.assertEqual({k: v for k, v in a0.items() if k != "tag"}, {k: v for k, v in ctl.items() if k != "tag"})
        self.assertEqual({k: v for k, v in a1.items() if k not in ("tag", "recart")}, {k: v for k, v in a0.items() if k != "tag"})
        self.assertIs(a1["recart"], True); self.assertNotIn("recart", a0)
        self.assertEqual(len({ctl["tag"], rc["tag"], a0["tag"], a1["tag"]}), 4)

    def test_weights_served_are_identical(self):
        lf, _ = build()
        for sfx in ("", "@home"):
            for k in (0, 1):
                for seg in ("known", "new"):
                    np.testing.assert_array_equal(lf.alt["cs2r" + sfx][k][seg], lf.alt["cs2rrc" + sfx][k][seg])
        self.assertEqual({k for k in lf.alt if k.endswith(lfm.RC)}, {"cs2rrc" + lfm.RC})
        self.assertEqual(lf.alt_lq, {}); self.assertEqual(lf.alt_x, {})

    def test_history_counts_1_2_5(self):
        lf, aff = build()
        c, rc = score(lf, aff, "cs2r"), score(lf, aff, "cs2rrc")
        self.assertEqual(rc['B01'], c['B01'])                                              # n = 1: 3 * log 2 = 2.08 < 3, today's cart already wins
        self.assertAlmostEqual(rc['B02'] - c['B02'], 3 * math.log(3) - 3, places=9)        # n = 2: +0.296
        self.assertAlmostEqual(rc['B05'] - c['B05'], 3 * math.log(6) - 3, places=9)        # n = 5: +2.375
        self.assertAlmostEqual(KEEP(2), 0.2958, places=4); self.assertAlmostEqual(KEEP(5), 2.3753, places=4); self.assertEqual(KEEP(1), 0.0)
        # never lower, for any product
        self.assertTrue(all(rc[p] >= c[p] for p in c if np.isfinite(c[p])))
        self.assertEqual({p for p in c if rc[p] != c[p]}, {'B02', 'B05', 'B09', 'B12', 'B13'})   # A10 (today only), B11 (history only), B01 (n = 1) untouched
        # with the option the product scores what it scored before being carted again (n = 2, 5), under the control
        for p in ('B02', 'B05'):
            lf0, aff0 = build(); lf0.lcart['u1'].discard(p)
            self.assertAlmostEqual(rc[p], score(lf0, aff0, "cs2r")[p], places=9)
            self.assertGreater(score(lf0, aff0, "cs2r")[p], c[p])                          # the control does lose points on the re-cart
        lf0, aff0 = build(); lf0.lcart['u1'].discard('B01')
        self.assertLess(score(lf0, aff0, "cs2r")['B01'], c['B01'])                         # n = 1 gains from being carted again, in both arms

    def test_category_pages_too(self):
        lf, aff = build()
        c, rc = score(lf, aff, "cs2r", page='category'), score(lf, aff, "cs2rrc", page='category')
        self.assertAlmostEqual(rc['B05'] - c['B05'], KEEP(5), places=9); self.assertEqual(rc['B01'], c['B01'])

    def test_bought_and_unavailable_stay_out(self):
        lf, aff = build(unavail={'B09'})
        lf.add('u1', 'B12', p=1)                                           # bought today (event stream)
        lf.add('u1', 'B13', p=1, tp="2026-11-13 08:00:00.000")             # bought earlier, from our carousel (feedback path), any date
        st = lf.user_state('u1')
        self.assertTrue({'B06', 'B12', 'B13'} <= st[0])
        for model in ("cs2r", "cs2rrc"):
            s = score(lf, aff, model)
            for p in ('B06', 'B12', 'B13', 'B09'): self.assertEqual(s[p], -np.inf, (model, p))
            for kw in (dict(), dict(page='category')):
                out = lf.slate(req(**kw), st, aff, model=model)
                self.assertEqual(len(out), 10); self.assertEqual(len(set(out)), 10); self.assertFalse({'B06', 'B12', 'B13', 'B09'} & set(out))
        out = lf.slate(req(), st, aff, model="cs2rrc", exclude={'B05'})    # stock moved after the snapshot
        self.assertEqual(len(set(out)), 10); self.assertNotIn('B05', out)
        lf.set_window("2026-11-15 00:00:00", "day")                        # a day window never brings a purchase back
        self.assertTrue({'B06', 'B12', 'B13'} <= lf.user_state('u1')[0])
        self.assertFalse({'B06', 'B12', 'B13'} & set(lf.slate(req(), lf.user_state('u1'), aff, model="cs2rrc")))

    def test_new_shoppers_and_home_are_identical(self):
        lf, aff = build()
        lf.add('u9', 'B05', a=1)
        for kw in COHORTS:
            self.assertEqual(score(lf, aff, "cs2rrc", **kw), score(lf, aff, "cs2r", **kw), kw)
            st = lf.user_state(kw.get('user', 'u1'))
            self.assertEqual(lf.slate(req(**kw), st, aff, model="cs2rrc"), lf.slate(req(**kw), st, aff, model="cs2r"), kw)
        self.assertNotEqual(lf.slate(req(), lf.user_state('u1'), aff, model="cs2rrc"), lf.slate(req(), lf.user_state('u1'), aff, model="cs2r"))

    def test_option_off_reproduces_the_control(self):
        off = [{k: v for k, v in RC["lfm_arms"][0].items() if k != "recart"}]
        lf, aff = build(arms=live.clean_lfm_arms(off)); lfc, affc = build()
        self.assertFalse([k for k in lf.alt if k.endswith(lfm.RC)])
        for kw in (dict(), dict(page='category')) + COHORTS:
            self.assertEqual(score(lf, aff, "cs2rrc", **kw), score(lfc, affc, "cs2r", **kw), kw)
            self.assertEqual(lf.slate(req(**kw), lf.user_state(kw.get('user', 'u1')), aff, model="cs2rrc"),
                             lfc.slate(req(**kw), lfc.user_state(kw.get('user', 'u1')), affc, model="cs2r"), kw)
        # no history carts, or nothing carted again today: both arms answer the same
        lf2, aff2 = build(recarted=('A10',))
        self.assertEqual(score(lf2, aff2, "cs2rrc"), score(lf2, aff2, "cs2r"))

    def test_state_untouched(self):
        lf, aff = build(); st = lf.user_state('u1')
        before = copy.deepcopy((st[0], st[1], st[2], lf.hcart))
        lf.scores(req(), st, aff, "cs2rrc"); lf.slate(req(), st, aff, model="cs2rrc")
        self.assertEqual(before, (st[0], st[1], st[2], lf.hcart))

    def test_writer_labels_and_user_split(self):
        saved = (live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'])
        try:
            arms = live.clean_lfm_arms(AB["lfm_arms"])
            lf, aff = build(arms=arms)
            live.LF = lf; live.AP = type('AP', (), {'aff': aff})(); live.POLICY['variant'] = 'lfm'; live.POLICY['lfm_arms'] = arms
            users = [f"user{k}" for k in range(4000)]
            side = [zlib.crc32(('lfmarm:' + u).encode()) % 2 for u in users]
            self.assertEqual([live.lfm_arm(u)['tag'] for u in users], [("cs2rc0", "cs2rc1")[s] for s in side])      # stable, by user
            self.assertLess(abs(sum(side) / len(side) - 0.5), 0.03)
            tag = live.lfm_arm('u1')['tag']
            reqs = [dict(request_id=str(k), **r) for k, r in enumerate((req(), req(new=True), req(rv=(), page='home'), req(new=True, rv=(), page='home')))]
            ver = {}; out = live.lfm_slates(reqs, set(), ver)
            self.assertEqual(ver, {0: f'v3-lfm-{tag}-k', 1: f'v3-lfm-{tag}-n', 2: f'v3-lfm-{tag}-kh', 3: f'v3-lfm-{tag}-nh'})
            st = lf.user_state('u1')
            self.assertEqual(out[0], lf.slate(req(), st, aff, model=tag))
            for k, r in enumerate(reqs[1:], 1):                                           # other cohorts: the same list from either arm
                q = {x: r[x] for x in ('user_id', 'rv', 'page', 'is_new_user')}
                self.assertEqual(lf.slate(q, st, aff, model="cs2rc0"), lf.slate(q, st, aff, model="cs2rc1")); self.assertEqual(out[k], lf.slate(q, st, aff, model=tag))
            # single-arm policy: every request of the block carries the new tag
            one = live.clean_lfm_arms(RC["lfm_arms"]); lf.set_arms(one); live.POLICY['lfm_arms'] = one
            ver = {}; live.lfm_slates(reqs, set(), ver)
            self.assertEqual(ver, {0: 'v3-lfm-cs2rrc-k', 1: 'v3-lfm-cs2rrc-n', 2: 'v3-lfm-cs2rrc-kh', 3: 'v3-lfm-cs2rrc-nh'})
        finally:
            live.POLICY['variant'], live.LF, live.AP, live.POLICY['lfm_arms'] = saved

    def test_same_correction_on_r3_if_r3_is_retained(self):
        """Fallback pair: r3 against r3 + option (policy.rot_r3rc.json alone, policy.rot_r3ab.json split by user)."""
        r3, r3rc, r3ab = POL("r3"), POL("r3rc"), POL("r3ab")
        base = {k: v for k, v in r3["lfm_arms"][0].items() if k != "tag"}
        self.assertEqual({k: v for k, v in r3rc["lfm_arms"][0].items() if k not in ("tag", "recart")}, base)
        a0, a1 = r3ab["lfm_arms"]
        self.assertEqual(live.clean_lfm_arms(r3ab["lfm_arms"]), r3ab["lfm_arms"])
        self.assertEqual({k: v for k, v in a0.items() if k != "tag"}, base)
        self.assertEqual({k: v for k, v in a1.items() if k not in ("tag", "recart")}, base); self.assertIs(a1["recart"], True)
        self.assertEqual(len({"r3", "r3rc", a0["tag"], a1["tag"]}), 4)
        lf, aff = build(arms=live.clean_lfm_arms(r3ab["lfm_arms"]))
        w = lf.alt["r3rc0"][0]["known"]; chn, cl = w[lfm.FEATS.index("chn")], w[lfm.FEATS.index("cl")]
        c, rc = score(lf, aff, "r3rc0"), score(lf, aff, "r3rc1")
        for p, n in (('B01', 1), ('B02', 2), ('B05', 5)):
            self.assertAlmostEqual(rc[p] - c[p], max(0.0, chn * math.log1p(n) - cl), places=9)       # 0, +0.166, +0.670 with r3
        self.assertEqual(rc['B01'], c['B01']); self.assertGreater(rc['B02'], c['B02'])
        self.assertTrue(all(rc[p] >= c[p] for p in c if np.isfinite(c[p]))); self.assertEqual(rc['B06'], -np.inf)
        for kw in COHORTS: self.assertEqual(score(lf, aff, "r3rc1", **kw), score(lf, aff, "r3rc0", **kw), kw)


if __name__ == "__main__":
    unittest.main()
