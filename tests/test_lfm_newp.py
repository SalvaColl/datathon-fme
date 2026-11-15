"""T-039: lfm feature `newp` (product launched during the event) and the arm that weights it."""
import unittest
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

NEW = {'A38', 'A39', 'B39'}                       # launched during the event: worst quality of the fixture, never in a slate
ARMS = [{"tag": "r3"}, {"tag": "np1", "w": {"known": {"newp": 6.0}}}]


def build(newp=NEW):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, newp=newp)
    lf.set_arms(ARMS)
    return lf, aff


def slate(lf, aff, model, rv=('A30',), new=False, page='product'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state('u9'), aff, model=model)


class NewpTests(unittest.TestCase):
    def test_feature_is_last_and_absent_from_committed_weights(self):
        self.assertEqual(lfm.FEATS.index("newp"), 21)
        lf, _ = build()
        self.assertEqual(float(lf.w["known"][21]), 0.0); self.assertEqual(float(lf.w["new"][21]), 0.0)

    def test_control_is_identical_with_and_without_the_new_product_set(self):
        a, aff = build(); b, aff2 = build(newp=None)
        for kw in (dict(), dict(new=True), dict(page='home', rv=()), dict(page='category')):
            self.assertEqual(slate(a, aff, "r3", **kw), slate(b, aff2, "r3", **kw))
        self.assertIsNone(b.snap.newp)
        self.assertEqual(slate(b, aff2, "np1"), slate(b, aff2, "r3"))             # no set known: the arm serves the control's slate

    def test_arm_brings_launched_products_for_returning_shoppers_on_pages_only(self):
        lf, aff = build()
        self.assertFalse(NEW & set(slate(lf, aff, "r3")))
        s = slate(lf, aff, "np1")
        self.assertEqual(len(set(s)), 10); self.assertEqual(set(s[:3]), NEW)
        self.assertEqual(slate(lf, aff, "np1", page='category')[:3], s[:3])
        self.assertEqual(slate(lf, aff, "np1", new=True), slate(lf, aff, "r3", new=True))                       # new shoppers: weight 0
        self.assertEqual(slate(lf, aff, "np1", page='home', rv=()), slate(lf, aff, "r3", page='home', rv=()))   # home: feature 0
        self.assertEqual(slate(lf, aff, "np1", page='home'), slate(lf, aff, "r3", page='home'))

    def test_feature_values(self):
        lf, aff = build(); S = lf.snap
        X = lfm.features(S, aff.affinity_all('u9'), ['A30'], 'product', {}, set())
        self.assertEqual({S.ids[k] for k in np.nonzero(X[:, 21])[0]}, NEW)
        for page, rv in (('home', ['A30']), ('product', []), ('home', [])):
            self.assertEqual(float(lfm.features(S, aff.affinity_all('u9'), rv, page, {}, set())[:, 21].sum()), 0.0)

    def test_unavailable_or_bought_launches_are_never_served(self):
        cat = catalog(); aff = FakeAff(list(cat.index)); lf = lfm.LiveFit(COEF, HIST)
        lf.set_catalog(cat, {'A39'}, aff, {p: 0.0 for p in cat.index}, None, newp=NEW); lf.set_arms(ARMS)
        lf.add('u9', 'A38', p=1)
        s = slate(lf, aff, "np1")
        self.assertEqual(len(set(s)), 10); self.assertNotIn('A39', s); self.assertNotIn('A38', s); self.assertIn('B39', s)

    def test_writer_accepts_the_arm_and_finds_the_launches(self):
        arms = [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "np1", "file": "lfm_coef_r3.json", "w": {"known": {"newp": 1.0}}}]
        self.assertEqual(live.clean_lfm_arms(arms), arms)
        cat = catalog(); saved = live.QR
        try:
            live.QR = type("QR", (), {"q": {p: 0.01 for p in cat.index if p not in NEW}})()
            self.assertEqual(live.new_products(cat), NEW)
            live.QR = type("QR", (), {"q": {p: 0.01 for p in list(cat.index)[:40]}})()        # half the catalogue "new": not credible
            self.assertIsNone(live.new_products(cat))
            live.QR = type("QR", (), {"q": {p: 0.01 for p in cat.index}})()
            self.assertIsNone(live.new_products(cat))
            live.QR = None; self.assertIsNone(live.new_products(cat))
        finally: live.QR = saved


class ExploreTests(unittest.TestCase):
    """T-039 exploration arm: only the last slot changes, to a valid product from ranks 11..60 of the same ranking."""
    def setUp(self):
        self.lf, self.aff = build(newp=None)
        self.lf.set_arms([{"tag": "r3"}, {"tag": "x1", "explore": True}])

    def req(self, rid, rv=('A30',), page='product', new=False):
        return dict(request_id=rid, user_id='u9', rv=list(rv), page=page, is_new_user=new)

    def both(self, rid, exclude=(), **kw):
        st = self.lf.user_state('u9'); r = self.req(rid, **kw)
        return self.lf.slate(r, st, self.aff, exclude=exclude, model="r3"), self.lf.slate(r, st, self.aff, exclude=exclude, model="x1")

    def test_only_the_last_slot_changes_and_comes_from_ranks_11_to_60(self):
        st = self.lf.user_state('u9'); ranked = self.lf.slate(self.req('r0'), st, self.aff, n=60, model="r3")
        seen = set()
        for k in range(200):
            a, x = self.both(f'r{k}')
            self.assertEqual(x[:9], a[:9]); self.assertEqual(len(set(x)), 10)
            self.assertIn(x[9], ranked[10:60]); seen.add(x[9])
        self.assertGreater(len(seen), 30)                                        # spreads over the pool
        self.assertEqual(self.both('r7')[1], self.both('r7')[1])                 # same request, same slate

    def test_home_and_requests_without_views_are_untouched(self):
        for kw in (dict(page='home', rv=()), dict(page='home'), dict(rv=())):
            a, x = self.both('r1', **kw); self.assertEqual(a, x)

    def test_never_serves_excluded_bought_or_out_of_stock_products(self):
        st = self.lf.user_state('u9'); ranked = self.lf.slate(self.req('r0'), st, self.aff, n=60, model="r3")
        gone = set(ranked[10:55]); self.lf.add('u9', ranked[55], p=1)
        for k in range(60):
            a, x = self.both(f'r{k}', exclude=gone)
            self.assertEqual(len(set(x)), 10); self.assertFalse(gone & set(x)); self.assertNotEqual(x[9], ranked[55])
        cat = catalog(); aff = FakeAff(list(cat.index)); lf = lfm.LiveFit(COEF, HIST)
        lf.set_catalog(cat, set(cat.index[12:]), aff, {p: 0.0 for p in cat.index}, None); lf.set_arms([{"tag": "x1", "explore": True}])
        s = lf.slate(dict(user_id='u9', rv=['A05'], page='product', is_new_user=False), lf.user_state('u9'), aff, model="x1")
        self.assertEqual(len(set(s)), 10); self.assertTrue(set(s) <= set(cat.index[:12]))

    def test_no_pool_keeps_the_ranked_slate(self):
        cat = catalog(); aff = FakeAff(list(cat.index)); lf = lfm.LiveFit(COEF, HIST)
        lf.set_catalog(cat, set(cat.index[10:]), aff, {p: 0.0 for p in cat.index}, None); lf.set_arms([{"tag": "r3"}, {"tag": "x1", "explore": True}])
        r = dict(user_id='u8', rv=['A05'], page='product', is_new_user=True); st = lf.user_state('u8')
        self.assertEqual(lf.slate(r, st, aff, model="x1"), lf.slate(r, st, aff, model="r3"))

    def test_writer_validation(self):
        arms = [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "x1", "file": "lfm_coef_r3.json", "explore": True}]
        self.assertEqual(live.clean_lfm_arms(arms), arms)
        for bad in ("yes", 1, 0.1, {"slot": 10}):
            self.assertEqual(live.clean_lfm_arms([arms[0], {**arms[1], "explore": bad}]), [])
        self.assertEqual(live.clean_lfm_arms([arms[0], {"tag": "x1", "file": "lfm_coef_r3.json", "explore": False}]), [])
        for mode in ("new", "known"):
            self.assertEqual(live.clean_lfm_arms([arms[0], {**arms[1], "explore": mode}])[1]["explore"], mode)

    def test_mode_new_or_known_only_touches_that_kind_of_shopper(self):
        for mode, hit, miss in (("new", True, False), ("known", False, True)):
            self.lf.set_arms([{"tag": "r3"}, {"tag": "x1", "explore": mode}])
            diff = 0
            for k in range(40):
                a, x = self.both(f'r{k}', new=miss); self.assertEqual(a, x)
                a, x = self.both(f'r{k}', new=hit); self.assertEqual(a[:9], x[:9]); diff += a != x
            self.assertEqual(diff, 40)
        self.assertFalse(lfm.x_target("new", True, "home", ["A01"])); self.assertFalse(lfm.x_target("new", True, "product", []))
        self.assertFalse(lfm.x_target(None, True, "product", ["A01"])); self.assertFalse(lfm.x_target(1, True, "product", ["A01"]))

    def test_the_night_policy_file_is_accepted_whole_and_routes_as_documented(self):
        import json, pathlib
        raw = json.loads((pathlib.Path(lfm.HERE) / "policy.night_1114_x.json").read_text())["lfm_arms"]
        arms = live.clean_lfm_arms(raw)
        self.assertEqual(arms, raw); self.assertEqual([a["tag"] for a in arms], ["r3", "np1", "cvk", "cn1"])
        saved = live.POLICY["lfm_arms"]
        try:
            live.POLICY["lfm_arms"] = arms; by = {a["tag"]: a for a in arms}
            self.assertEqual(live.lfm_route(by["cn1"], False, "product", ["A01"]), "r3")      # cn1's returning shoppers are the champion's
            self.assertEqual(live.lfm_route(by["cn1"], True, "product", ["A01"]), "cn1")
            self.assertEqual(live.lfm_route(by["np1"], True, "product", ["A01"]), "np1")       # np1's new shoppers = the exploration row
            self.assertEqual(live.lfm_route(by["np1"], False, "product", ["A01"]), "np1")
        finally: live.POLICY["lfm_arms"] = saved
        lf, aff = build(); lf.set_arms(arms)                                                    # real weight files, fixture catalogue
        self.assertEqual(lf.alt_x, {"np1": "new"}); self.assertEqual(lf.alt_lq, {"cn1": "cold_new"})
        st = lf.user_state('u9')
        for new in (False, True):
            r = dict(request_id='q1', user_id='u9', rv=['A30'], page='product', is_new_user=new)
            s = {t: lf.slate(r, st, aff, model=t) for t in by}
            self.assertTrue(all(v is not None and len(set(v)) == 10 for v in s.values()))
            if new: self.assertEqual(s["np1"][:9], s["r3"][:9]); self.assertNotEqual(s["np1"][9], s["r3"][9]); self.assertEqual(s["cvk"], s["r3"])
            else: self.assertTrue(NEW & set(s["np1"]) or s["np1"] == s["r3"])


if __name__ == "__main__":
    unittest.main()
