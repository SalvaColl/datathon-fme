"""T-062: attribute prior inside `orate` for products without history (arm key `oqa`, off by default)."""
import contextlib, io, json, math, tempfile, types, unittest
from pathlib import Path
import numpy as np

from recsys import lfm, live, cold_items
from tests.test_lfm import FakeAff, catalog, COEF, HIST

NEW = ['A36', 'A37', 'A38', 'A39', 'B38', 'B39']             # launched during the event: no history, worst `lq`
PRIOR = {'A36': 0.20, 'A37': 0.15, 'A38': 0.005, 'A39': 0.004, 'B38': 0.18, 'B39': 0.003}
W = {"w": {"known": {"lq": 0.0, "orate": 6.0}, "new": {"lq": 0.0, "orate": 6.0}},
     "home": {"w": {"known": {"lq": 0.0, "orate": 6.0}, "new": {"lq": 0.0, "orate": 6.0}}}}
ARMS = [{"tag": "c0", **W}, {"tag": "c1", **W, "oqa": ["new", "home_new"]}, {"tag": "c2", **W, "oqa": list(lfm.CAP_KEYS)}]
SEGS = [dict(rv=(), page='home', new=True), dict(rv=(), page='home', new=False), dict(rv=('A30',), page='product', new=True),
        dict(rv=('A30',), page='product', new=False), dict(rv=('A30',), page='category', new=True)]


def counts(cat, live_new=None):
    """Old products: 400 organic views, 20 to 39 purchases. New ones: nothing, or `live_new`."""
    c = {p: (400.0, 20.0 + int(p[1:]) % 20) for p in cat.index if p not in NEW}
    c.update(live_new or {})
    return c


def build(prior=PRIOR, arms=ARMS, live_new=None, unavail=(), oq=True):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
    hist = set(cat.index) - set(NEW)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None,
                   oq=counts(cat, live_new) if oq else None, oq_hist=hist, oq_prior=prior)
    return lf, aff


def slate(lf, aff, model, rv=('A30',), new=True, page='product', exclude=(), user='u9'):
    req = dict(user_id=user, rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state(user), aff, model=model, exclude=exclude)


def score(lf, aff, model, rv=('A30',), new=True, page='product'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    S, s = lf.scores(req, lf.user_state('u9'), aff, model)
    return dict(zip(S.ids, s))


class AttrPriorTests(unittest.TestCase):
    def test_off_by_default_and_no_committed_policy_uses_it(self):
        a, aff = build(); b, aff2 = build(prior=None)
        self.assertIsNone(b.snap.orate_d); self.assertIsNotNone(a.snap.orate_d)
        np.testing.assert_array_equal(a.snap.orate, b.snap.orate)                 # the feature itself never moves
        for kw in SEGS:
            self.assertEqual(score(a, aff, "c0", **kw), score(b, aff2, "c0", **kw))          # arm without the key: identical
            self.assertEqual(score(b, aff2, "c1", **kw), score(b, aff2, "c0", **kw))         # key without a prior: identical
        self.assertFalse(lfm.LiveFit(COEF, HIST).wants_oqa())
        for f in Path(lfm.HERE).glob("policy*.json"):
            conf = json.loads(f.read_text())
            if ".rot_ug" in f.name: continue                                           # the trial policies of this task
            self.assertFalse(any(isinstance(x, dict) and "oqa" in x for x in conf.get("lfm_arms") or []), f.name)

    def test_products_with_history_are_identical(self):
        lf, aff = build()
        d = dict(zip(lf.snap.ids, lf.snap.orate_d))
        self.assertTrue(all(d[p] == 0.0 for p in d if p not in NEW))
        for kw in SEGS:
            a, b = score(lf, aff, "c0", **kw), score(lf, aff, "c2", **kw)
            for p in a:
                if p not in NEW: self.assertEqual(a[p], b[p], (p, kw))

    def test_products_without_interactions_differ_by_attributes(self):
        lf, aff = build()
        o = dict(zip(lf.snap.ids, lf.snap.orate)); d = dict(zip(lf.snap.ids, lf.snap.orate_d))
        self.assertEqual(len({o[p] for p in NEW}), 1)                             # today: all six at the flat prior
        centre = math.log(1 / 20) - o['A36']
        for p in NEW:                                                             # rate = (0 + 100 * prior) / (0 + 100), same centre
            self.assertAlmostEqual(o[p] + d[p], float(np.clip(math.log(PRIOR[p]) - centre, -3, 3)), places=12)
        order = sorted(NEW, key=lambda p: -(o[p] + d[p]))
        self.assertEqual(order, sorted(NEW, key=lambda p: -PRIOR[p]))
        s = slate(lf, aff, "c2", rv=(), page='home')
        self.assertTrue({'A36', 'B38', 'A37'} <= set(s)); self.assertFalse({'A38', 'A39', 'B39'} & set(s))

    def test_formula_blends_organic_counts_with_k_100(self):
        self.assertEqual(lfm.OQ_PRIOR_K, cold_items.K_PRIOR)
        lf, _ = build(live_new={'A36': (50.0, 1.0), 'A38': (300.0, 60.0)})
        o = dict(zip(lf.snap.ids, lf.snap.orate)); d = dict(zip(lf.snap.ids, lf.snap.orate_d))
        centre = math.log(1 / 20) - o['A37']
        self.assertAlmostEqual(o['A36'] + d['A36'], math.log((1 + 100 * 0.20) / (50 + 100)) - centre, places=12)
        self.assertAlmostEqual(o['A38'] + d['A38'], math.log((60 + 100 * 0.005) / (300 + 100)) - centre, places=12)
        self.assertAlmostEqual(o['A38'], math.log((60 + 1) / (300 + 20)) - centre, places=12)        # current formula untouched

    def test_only_the_segments_of_the_key(self):
        lf, aff = build()
        for kw in SEGS:
            same = score(lf, aff, "c1", **kw) == score(lf, aff, "c0", **kw)
            self.assertEqual(same, not kw['new'], kw)                              # known shoppers identical, new ones treated
            self.assertNotEqual(score(lf, aff, "c2", **kw), score(lf, aff, "c0", **kw))

    def test_fallback_per_product(self):
        bad = dict(PRIOR, A37=float('nan'), A38=-0.2, A39=1.5, B38=None, B39="0.2"); del bad['B38']
        lf, aff = build(prior=bad)
        d = dict(zip(lf.snap.ids, lf.snap.orate_d))
        self.assertNotEqual(d['A36'], 0.0)                                         # the valid one still gets its prior
        self.assertTrue(all(d[p] == 0.0 for p in NEW if p != 'A36'))               # the others keep the current formula
        self.assertIsNotNone(lf.snap.orate)                                        # quality as a whole stays on
        for junk in ({}, {'A36': float('inf')}, {'zzz': 0.1}, {'A00': 0.3}):       # nothing usable (A00 has history): no change at all
            lf2, aff2 = build(prior=junk)
            self.assertIsNone(lf2.snap.orate_d)
            for kw in SEGS: self.assertEqual(score(lf2, aff2, "c2", **kw), score(lf2, aff2, "c0", **kw))
        lf3, _ = build(oq=False); self.assertIsNone(lf3.snap.orate_d)              # no organic counts: nothing

    def test_ten_distinct_active_not_bought(self):
        lf, aff = build(unavail={'A36', 'A01'})
        lf.add('u7', 'B38', p=1); lf.add('u7', 'A37', a=1)
        for kw in SEGS:
            for m in ("c0", "c1", "c2"):
                s = slate(lf, aff, m, user='u7', exclude={'A02'}, **kw)
                self.assertEqual(len(s), 10); self.assertEqual(len(set(s)), 10)
                self.assertFalse({'A36', 'A01', 'B38', 'A02'} & set(s), (m, kw))

    def test_keeps_the_cap_on_launched_products(self):
        arms = [{"tag": "c2", **W, "oqa": list(lfm.CAP_KEYS), "newcap": {k: 1 for k in lfm.CAP_KEYS}}]
        cat = catalog(); aff = FakeAff(list(cat.index)); lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
        lf.set_catalog(cat, set(), aff, {p: 0.0 for p in cat.index}, None, newp=set(NEW), oq=counts(cat), oq_hist=set(cat.index) - set(NEW), oq_prior=PRIOR)
        for kw in SEGS: self.assertEqual(sum(p in NEW for p in slate(lf, aff, "c2", **kw)), 1, kw)


class RefresherPriorTests(unittest.TestCase):
    """live.attr_prior: metadata and price of the snapshot it is given, nothing else."""
    def setUp(self):
        self.saved = (live.LF, live.AP); live.OQA_CACHE.clear(); live.OQA_LOG.clear()
        self.cold = cold_items.ColdStart()
        self.cat = catalog(); self.hist = set(self.cat.index) - set(NEW)
        a, b = cold_items.ATTRS[0], cold_items.ATTRS[5]
        self.cold.desc = {p: f"b {p} with {a} and {b}." for p in NEW}
        live.AP = types.SimpleNamespace(cold=self.cold)
        live.LF = lfm.LiveFit(COEF, HIST); live.LF.set_arms(ARMS)
        self.out = io.StringIO()

    def tearDown(self): live.LF, live.AP = self.saved

    def prior(self, cat=None, hist=None):
        with contextlib.redirect_stdout(self.out): return live.attr_prior(self.cat if cat is None else cat, self.hist if hist is None else hist)

    def test_only_products_without_history_and_the_purchase_rate(self):
        p = self.prior()
        self.assertEqual(set(p), set(NEW))
        c = self.cat.loc['A36']
        self.assertEqual(p['A36'], self.cold.prior.rate(c.category, c['sub'], c.brand, c.price, self.cold.desc['A36'], "p"))   # the rate itself, not squared
        self.assertTrue(all(0 < v < 1 for v in p.values()))

    def test_no_arm_no_work(self):
        live.LF.set_arms([{"tag": "c0", **W}])
        self.assertIsNone(self.prior())
        live.LF = None; self.assertIsNone(self.prior())

    def test_no_future_information(self):
        """Function of (category, subcategory, brand, price now, description) only: no counts, no clock, and a later
        price does not leak back (the cache is keyed by price)."""
        p0 = self.prior()
        later = self.cat.copy(); later.loc['A36', 'price'] = 400.0
        p1 = self.prior(later)
        self.assertNotEqual(p1['A36'], p0['A36'])
        self.assertEqual({k: v for k, v in p1.items() if k != 'A36'}, {k: v for k, v in p0.items() if k != 'A36'})
        self.assertEqual(self.prior(), p0)                                          # the earlier snapshot still gives the earlier prior
        import inspect
        src = inspect.getsource(live.attr_prior)
        for word in ("query(", "organic_frame", "item_frame", "time.", "BASE["): self.assertNotIn(word, src)

    def test_incomplete_metadata_falls_back_per_product(self):
        cat = self.cat.copy()
        cat.loc['A37', 'price'] = float('nan'); cat.loc['A38', 'brand'] = None
        self.cold.desc['A39'] = "no known phrase here"; del self.cold.desc['B38']
        p = self.prior(cat)
        self.assertEqual(set(p), {'A36', 'B39'})
        ev = [json.loads(l) for l in self.out.getvalue().splitlines() if l.startswith('{')]
        self.assertEqual(ev[-1], dict(event='attr_prior', products=2, fallback=4))
        self.cold.prior = types.SimpleNamespace(rate=lambda *a: 1 / 0)             # the model itself breaks: nobody gets a prior
        live.OQA_CACHE.clear()
        self.assertIsNone(self.prior(cat))
        dup = cat.loc[list(cat.index) + ['A36']]
        self.assertIsNone(self.prior(dup))


class PolicyTests(unittest.TestCase):
    def test_clean_arms(self):
        ok = live.clean_lfm_arms([{"tag": "c0", **W}, {"tag": "c1", **W, "oqa": ["home_new", "new"]}])
        self.assertEqual(ok[1]["oqa"], ["new", "home_new"]); self.assertNotIn("oqa", ok[0])
        for bad in (True, "new", [], ["new", "new"], ["page"], {"new": 1}, [1]):
            self.assertEqual(live.clean_lfm_arms([{"tag": "c0", **W}, {"tag": "c1", **W, "oqa": bad}]), [], bad)

    def test_reload_turns_the_option_on_and_off(self):
        saved = (live.DATA, live.LF, dict(live.POLICY), dict(live.POLICY_REJECTED), dict(live.LABELS))
        tmp = tempfile.TemporaryDirectory()
        try:
            live.DATA = Path(tmp.name); live.LF, aff = build(arms=[])
            live.POLICY.update(variant="lfm", qrank_arms=[], lfm_arms=[], state_window=None)
            def load(arms):
                (live.DATA / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": arms}))
                with contextlib.redirect_stdout(io.StringIO()): live.read_policy()
            load([{"tag": "c0", **W}, {"tag": "c1", **W, "oqa": ["new", "home_new"]}])
            self.assertEqual(live.LF.alt_oqa, {"c1": frozenset({"new", "home_new"})}); self.assertTrue(live.LF.wants_oqa())
            self.assertNotEqual(score(live.LF, aff, "c1"), score(live.LF, aff, "c0"))
            load([{"tag": "c0", **W}, {"tag": "c1", **W, "oqa": "all"}])            # bad key: the valid policy stays
            self.assertEqual(live.LF.alt_oqa, {"c1": frozenset({"new", "home_new"})})
            load([{"tag": "c0", **W}, {"tag": "c1", **W}])                          # rollback: key removed
            self.assertEqual(live.LF.alt_oqa, {}); self.assertFalse(live.LF.wants_oqa())
            self.assertEqual(score(live.LF, aff, "c1"), score(live.LF, aff, "c0"))
        finally:
            live.DATA, live.LF = saved[:2]
            for cur, old in ((live.POLICY, saved[2]), (live.POLICY_REJECTED, saved[3]), (live.LABELS, saved[4])): cur.clear(); cur.update(old)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
