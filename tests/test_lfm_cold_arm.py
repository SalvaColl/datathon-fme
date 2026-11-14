"""T-028: the cold_lq challenger as one lfm arm ({"tag": ..., "lq": "cold"}). Synthetic, no network, deterministic."""
import copy
import math
import threading
import time
import unittest

import numpy as np
import pandas as pd

from recsys import cold_lq, cold_lq_arm, lfm, live, live_quality
from tests.test_cold_lq import add_new, prior, world
from tests.test_lfm import COEF, HIST, FakeAff, catalog

DESC_OK = "Thing by b, featuring premium materials and a sporty style."
SEG = dict(device="android", region="Murcia")
W = {s: {"seglq": 0.7} for s in ("known", "new")}
ARMS = [{"tag": "r3", "w": W}, {"tag": "c1", "w": W, "lq": "cold"}]


def build(lq_cold=None, unavail=()):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, lq_cold=lq_cold)
    return lf, aff


def req(user="u9", rv=("A30",), page="product", new=False, **kw):
    return dict(user_id=user, rv=list(rv), page=page, is_new_user=new, **kw)


def scores(lf, aff, r, model=None):
    return lf.scores(r, lf.user_state(r["user_id"]), aff, model)[1]


CASES = [req(), req(new=True), req(page="category"), req(**SEG), req(new=True, **SEG), req(user="u1", rv=("B05", "A30")),
         req(rv=(), page="home"), req(rv=(), page="home", new=True, **SEG), req(rv=(), page="product"), req(rv=("A30",), page="home")]
HOME = [r for r in CASES if not r["rv"] or r["page"] == "home"]
VIEWS = [r for r in CASES if r not in HOME]


class ArmTests(unittest.TestCase):
    def setUp(self):
        self.champ, self.aff0 = build(); self.champ.set_arms([{"tag": "r3", "w": W}])        # unmodified champion: no corrected snapshot at all
        self.lf, self.aff = build({"B39": 2.0}); self.lf.set_arms(ARMS)
        self.k = self.lf.snap.row["B39"]

    def test_clean_keeps_lq_and_rejects_unknown_modes(self):
        self.assertEqual(live.clean_lfm_arms([{"tag": "r3"}, {"tag": "c1", "lq": "cold"}])[1], {"tag": "c1", "lq": "cold"})
        for bad in ("hot", "cold_new", 1, True):
            self.assertEqual(live.clean_lfm_arms([{"tag": "r3"}, {"tag": "c1", "lq": bad}]), [])
        a = live.clean_lfm_arms([{"tag": "r3", "file": "lfm_coef_r3.json", "home": {}}, {"tag": "c1", "file": "lfm_coef_r3.json", "home": {}, "lq": "cold"}])
        self.assertEqual(a[1], {"tag": "c1", "file": "lfm_coef_r3.json", "home": {}, "lq": "cold"})

    def test_control_is_exactly_the_unmodified_champion(self):
        for r in CASES:
            a, b = scores(self.champ, self.aff0, r, "r3"), scores(self.lf, self.aff, r, "r3")
            self.assertTrue(np.array_equal(a, b), r)
            st = self.lf.user_state(r["user_id"])
            self.assertEqual(self.champ.slate(r, self.champ.user_state(r["user_id"]), self.aff0, model="r3"), self.lf.slate(r, st, self.aff, model="r3"))

    def test_home_and_no_view_requests_are_untouched(self):
        for r in HOME:
            self.assertTrue(np.array_equal(scores(self.lf, self.aff, r, "r3"), scores(self.lf, self.aff, r, "c1")), r)
            st = self.lf.user_state(r["user_id"])
            self.assertEqual(self.lf.slate(r, st, self.aff, model="r3"), self.lf.slate(r, st, self.aff, model="c1"))

    def test_established_products_keep_their_score_and_both_quality_terms_move(self):
        delta = 2.0 - (-0.39)                                           # corrected lq - incumbent lq of B39 (lq0 = 0)
        for r in VIEWS:
            a, b = scores(self.lf, self.aff, r, "r3"), scores(self.lf, self.aff, r, "c1")
            rest = np.arange(len(a)) != self.k
            self.assertTrue(np.array_equal(a[rest], b[rest]), r)
            seg = lfm.in_segment(r.get("device"), r.get("region"))
            self.assertAlmostEqual(b[self.k] - a[self.k], (0.5 + (0.7 if seg else 0.0)) * delta, places=9, msg=str(r))

    def test_feature_columns_lq_and_seglq_both_carry_the_corrected_value(self):
        S = self.lf.snap; aff = self.aff.affinity_all("u9", ["A30"])
        a = lfm.features(S, aff, ["A30"], "product", {}, set(), seg=True)
        b = lfm.features(S, aff, ["A30"], "product", {}, set(), seg=True, lq=S.lqc)
        i, j = lfm.FEATS.index("lq"), lfm.FEATS.index("seglq")
        self.assertEqual((a[self.k, i], a[self.k, j]), (-0.39, -0.39)); self.assertEqual((b[self.k, i], b[self.k, j]), (2.0, 2.0))
        other = [c for c in range(a.shape[1]) if c not in (i, j)]
        self.assertTrue(np.array_equal(a[:, other], b[:, other]))
        self.assertTrue(np.array_equal(np.delete(a, self.k, 0), np.delete(b, self.k, 0)))

    def test_bought_inactive_unknown_and_invalid_products(self):
        lf, aff = build({"B06": 9.0, "B39": 9.0, "A31": 9.0, "ZZZ": 9.0, "A05": float("nan"), "A06": float("inf"), "A07": "x"}, unavail={"B39"})
        lf.set_arms(ARMS); S = lf.snap
        for p in ("A05", "A06", "A07"): self.assertEqual(S.lqc[S.row[p]], S.lq[S.row[p]])         # invalid numbers rejected
        r = req(user="u1", rv=("A30",)); s = scores(lf, aff, r, "c1")
        self.assertEqual(s[S.row["B06"]], -np.inf)                                                 # bought in history: never shown
        self.assertEqual(s[S.row["B39"]], -np.inf)                                                 # inactive / out of stock
        sl = lf.slate(r, lf.user_state("u1"), aff, model="c1")
        self.assertEqual(len(set(sl)), 10); self.assertIn("A31", sl); self.assertNotIn("B06", sl); self.assertNotIn("B39", sl)
        self.assertNotIn("A31", lf.slate(r, lf.user_state("u1"), aff, exclude={"A31"}, model="c1"))   # writer's stock exclusion still applies
        lf.add("u1", "A31", p=1)
        self.assertNotIn("A31", lf.slate(r, lf.user_state("u1"), aff, model="c1"))                   # bought today

    def test_snapshots_are_separate_read_only_and_deterministic(self):
        S = self.lf.snap
        self.assertIsNot(S.lq, S.lqc); self.assertFalse(np.shares_memory(S.lq, S.lqc))
        for v in (S.lq, S.lqc):
            with self.assertRaises(ValueError): v[0] = 1.0
        self.assertEqual(int((S.lq != S.lqc).sum()), 1)
        lf2, aff2 = build({"B39": 2.0}); lf2.set_arms(ARMS)
        self.assertTrue(np.array_equal(S.lqc, lf2.snap.lqc))
        for r in CASES: self.assertTrue(np.array_equal(scores(self.lf, self.aff, r, "c1"), scores(lf2, aff2, r, "c1")))

    def test_without_corrections_the_arm_equals_control(self):
        for c in (None, {}, {"ZZZ": 1.0}, {"B39": float("nan")}):
            lf, aff = build(c); lf.set_arms(ARMS)
            self.assertIsNone(lf.snap.lqc)
            for r in CASES: self.assertTrue(np.array_equal(scores(lf, aff, r, "r3"), scores(lf, aff, r, "c1")))

    def test_no_arm_with_lq_means_no_flag(self):
        self.lf.set_arms([{"tag": "r3"}, {"tag": "r5"}]); self.assertEqual(self.lf.alt_lq, {})

    def test_serving_latency_while_the_refresher_swaps_snapshots(self):
        cat = catalog(); lq = {p: -0.01 * int(p[1:]) for p in cat.index}; stop = threading.Event(); n = [0]
        def refresh():
            while not stop.is_set():
                self.lf.set_catalog(cat, set(), self.aff, lq, None, lq_cold={"B39": 2.0 + n[0] % 3}); n[0] += 1
        t = threading.Thread(target=refresh, daemon=True); t.start()
        ms = []
        try:
            for k in range(5000):                          # at least 300 slates, and until the snapshot was swapped a few times
                if k >= 300 and n[0] > 3: break
                r = CASES[k % len(CASES)]; t0 = time.perf_counter()
                sl = self.lf.slate(r, self.lf.user_state(r["user_id"]), self.aff, model="c1")
                ms.append(1000 * (time.perf_counter() - t0)); self.assertEqual(len(set(sl)), 10)
        finally:
            stop.set(); t.join()
        self.assertGreater(n[0], 3); self.assertLess(float(np.percentile(ms, 95)), 250.0)


class CorrectorTests(unittest.TestCase):
    def setUp(self):
        base, self.q, self.hist = world()
        self.cat = add_new(base, [("new_a", "C0", "S0", 50.0), ("new_b", "C1", "S1", 20.0), ("new_c", "C0", "S2", 30.0)])
        self.desc = {p: DESC_OK for p in ("new_a", "new_b", "new_c")}
        qs = pd.Series(self.q).reindex(self.cat.index)
        self.lq = np.log(qs.fillna(qs.groupby(self.cat["sub"]).transform("median"))).to_dict()      # qrank's rule: subcategory median
        self.cor = cold_lq_arm.Corrector(prior=prior)

    def run_(self, cor=None, cat=None, live=None, desc=None, hist="default"):
        return (cor or self.cor).corrections(self.q, self.lq, self.cat if cat is None else cat, self.hist if isinstance(hist, str) else hist,
                                             live, self.desc if desc is None else desc)

    def test_only_new_products_and_same_estimate_as_cold_lq_within_the_bound(self):
        out = self.run_()
        self.assertEqual(set(out), {"new_a", "new_b", "new_c"})
        ref = cold_lq.ColdLQ(live_quality.LiveQuality(prior=prior)).estimate(self.q, self.cat.assign(), self.hist, None, self.desc)
        for p, v in out.items():
            self.assertAlmostEqual(v, min(max(ref[p], self.lq[p] - math.log(20)), self.lq[p] + math.log(20)), places=12)
        self.assertEqual(self.cor.last["corrected"], 3)

    def test_correction_is_bounded_to_log_20_around_the_incumbent(self):
        live_ = pd.DataFrame({"it_v": [5000.0, 5000.0], "it_p": [4000.0, 0.0]}, index=["new_a", "new_b"])
        out = self.run_(live=live_)
        self.assertAlmostEqual(out["new_a"], self.lq["new_a"] + math.log(20), places=12)
        self.assertAlmostEqual(out["new_b"], self.lq["new_b"] - math.log(20), places=12)
        self.assertTrue(all(abs(v - self.lq[p]) <= math.log(20) + 1e-12 for p, v in out.items()))
        self.assertEqual(self.cor.last["clipped"], 2)

    def test_live_evidence_moves_the_estimate(self):
        hot = pd.DataFrame({"it_v": [300.0], "it_p": [60.0]}, index=["new_c"])
        self.assertGreater(self.run_(live=hot)["new_c"], self.run_()["new_c"])

    def test_missing_prior_never_uses_the_subcategory_fallback(self):
        cor = cold_lq_arm.Corrector(prior=None)
        self.assertFalse(cor.ready); self.assertEqual(self.run_(cor), {}); self.assertEqual(cor.last["reason"], "no_prior")

    def test_failed_or_malformed_prior_keeps_every_incumbent(self):
        def boom(cat): raise RuntimeError("bad")
        for bad in (boom, lambda cat: np.ones(3), lambda cat: np.full(len(cat), np.nan), lambda cat: np.zeros(len(cat))):
            cor = cold_lq_arm.Corrector(prior=bad)
            self.assertEqual(self.run_(cor), {}); self.assertEqual(cor.last["reason"], "prior_failed")

    def test_non_finite_prior_for_one_product_only_drops_that_product(self):
        def partial(cat):
            pr = prior(cat).astype(float); pr[list(cat.index).index("new_b")] = np.nan; return pr
        cor = cold_lq_arm.Corrector(prior=partial)
        out = self.run_(cor)
        self.assertEqual(set(out), {"new_a", "new_c"}); self.assertEqual(cor.last["rejected"], 1)
        good = self.run_()
        self.assertAlmostEqual(out["new_a"], good["new_a"], places=6)

    def test_missing_attributes_or_metadata_keep_the_incumbent(self):
        self.assertEqual(set(self.run_(desc={"new_a": DESC_OK, "new_b": "no known phrase here", "new_c": ""})), {"new_a"})
        self.assertEqual(set(self.run_(desc={"new_a": DESC_OK})), {"new_a"})                      # not a new_product update -> untouched
        for col, val in (("price", np.nan), ("price", 0.0), ("price", float("inf")), ("sub", None), ("category", None), ("brand", "")):
            cat = self.cat.copy(); cat[col] = cat[col].astype(object); cat.loc["new_b", col] = val
            self.assertNotIn("new_b", self.run_(cat=cat), (col, val))

    def test_established_products_are_never_corrected(self):
        desc = dict(self.desc, old_0_0=DESC_OK)
        self.assertNotIn("old_0_0", self.run_(desc=desc))

    def test_refresh_failure_and_duplicates_return_nothing(self):
        self.assertEqual(self.run_(hist=object()), {}); self.assertEqual(self.cor.last["reason"], "error")
        dup = pd.concat([self.cat, self.cat.loc[["new_a"]]])
        self.assertEqual(self.run_(cat=dup), {}); self.assertEqual(self.cor.last["reason"], "duplicate_ids")
        self.assertEqual(set(self.run_()), {"new_a", "new_b", "new_c"})                              # recovers on the next refresh

    def test_inputs_are_not_mutated_and_output_is_deterministic(self):
        q0, lq0, cat0 = copy.deepcopy(self.q), copy.deepcopy(self.lq), self.cat.copy()
        a = self.run_(); b = self.run_()
        self.assertEqual(a, b); self.assertEqual(self.q, q0); self.assertEqual(self.lq, lq0); pd.testing.assert_frame_equal(self.cat, cat0)
        self.assertTrue(all(math.isfinite(v) for v in a.values()))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.LF, live.AP, live.CLQ, live.QR, live.BASE)
        lf, aff = build()
        live.LF = lf; live.AP = type("AP", (), {"aff": aff, "cold": type("C", (), {"desc": {}})()})()
        live.QR = type("QR", (), {"q": {}, "lq": {}})(); live.BASE = {"item": None}
        self.T = type("T", (), {"item_frame": lambda s: None})()
    def tearDown(self):
        live.LF, live.AP, live.CLQ, live.QR, live.BASE = self.saved

    def fake(self, out, ready=True):
        calls = []
        class C:
            last = {}
            def corrections(s, *a, **k):
                calls.append(k)
                if isinstance(out, Exception): raise out
                return out
        C.ready = ready
        live.CLQ = C(); return calls

    def test_nothing_is_computed_unless_an_arm_asks(self):
        calls = self.fake({"B39": 2.0})
        live.LF.set_arms([{"tag": "r3"}, {"tag": "r5"}])
        self.assertIsNone(live.cold_lq_for_arms(catalog(), self.T)); self.assertEqual(calls, [])
        live.LF.set_arms(ARMS)
        self.assertEqual(live.cold_lq_for_arms(catalog(), self.T), {"B39": 2.0}); self.assertEqual(calls, [{"lq0": live.LF.lq0}])

    def test_not_ready_empty_or_failing_corrector_gives_none(self):
        live.LF.set_arms(ARMS)
        for out, ready in (({"B39": 2.0}, False), ({}, True), (RuntimeError("x"), True)):
            self.fake(out, ready); self.assertIsNone(live.cold_lq_for_arms(catalog(), self.T))
        live.CLQ = None; self.assertIsNone(live.cold_lq_for_arms(catalog(), self.T))


if __name__ == "__main__":
    unittest.main()
