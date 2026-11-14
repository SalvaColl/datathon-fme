"""T-042: the price flags of the shared lfm snapshot (p40, cheap) must come from the catalogue whatever the quality
corrections are. Before the fix, any non-empty `lq_cold` replaced the catalogue frame inside Snap.__init__ by the buffer
of corrections, every price fell back to 20 EUR and p40 / cheap were zero for EVERY arm (control included).

These tests use varied prices and non-zero p40 / segcheap weights, and they compare snapshots BUILT with and without
corrections (comparing control and treatment inside one snapshot cannot see a snapshot that is wrong for both).
Synthetic, no network, deterministic."""
import unittest

import numpy as np
import pandas as pd

from recsys import lfm
from tests.test_lfm import HIST, FakeAff, catalog

PRICES = [5.0, 19.99, 20.0, 20.01, 30.0, 39.99, 40.0, 40.01, 80.0, 10.0]      # below 20, exactly 20, exactly 40, above 40
SEG = dict(device="android", region="Murcia")                                  # the price-sensitive segment (segcheap, seglq)
W = dict(aff10=2.0, chn=1.2, islast=1.9, oinrv=1.8, ssub2=1.3, scat2=1.0, na=0.3, home=-0.3, lq=0.5, sbrand=0.1,
         p40=-0.9, segcheap=0.8, seglq=0.7)
COEF = {s: dict(w=dict(W, cl=cl), b=-9.0) for s, cl in (("known", 1.1), ("new", 2.2))}
ARMS = [{"tag": "r3"}, {"tag": "c1", "lq": "cold"}, {"tag": "cn1", "lq": "cold_new"}]
NEW = "B39"                                                                    # the corrected (launched) product
# name -> corrections; `moves` = the products whose quality really changes
VALID = {"valid": {NEW: 2.0}, "valid_and_junk": {NEW: 2.0, "ZZZ": 9.0, "A05": float("nan"), "A06": float("inf"), "A07": "x"}}
INERT = {"absent": None, "empty": {}, "unknown": {"ZZZ": 1.0}, "nan": {NEW: float("nan")}, "inf": {"A06": float("inf")},
         "minus_inf": {"A06": float("-inf")}, "text": {"A07": "x"}, "no_effect": {NEW: -0.39}, "mixed_inert": {"ZZZ": 1.0, "A05": float("nan"), NEW: -0.39}}


def cat_prices():
    cat = catalog()
    cat["price"] = [PRICES[k % len(PRICES)] for k in range(len(cat))]
    return cat


def build(lq_cold=None, unavail=(), cat=None):
    cat = cat_prices() if cat is None else cat
    aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, lq_cold=lq_cold)
    lf.set_arms(ARMS)
    return lf, aff, cat


def req(user="u9", rv=("A30",), page="product", new=False, **kw):
    return dict(user_id=user, rv=list(rv), page=page, is_new_user=new, **kw)


def scores(lf, aff, r, model):
    return lf.scores(r, lf.user_state(r["user_id"]), aff, model)[1]


def slate(lf, aff, r, model, exclude=()):
    return lf.slate(r, lf.user_state(r["user_id"]), aff, model=model, exclude=exclude)


VIEWS = [req(), req(new=True), req(page="category"), req(**SEG), req(new=True, **SEG), req(page="category", new=True, **SEG),
         req(user="u1", rv=("B05", "A30")), req(user="u1", rv=("B05", "A30"), **SEG)]
HOME = [req(rv=(), page="home"), req(rv=(), page="home", new=True, **SEG), req(rv=(), page="product", **SEG), req(rv=("A30",), page="home", **SEG),
        req(rv=(), page="home", **SEG)]
CASES = VIEWS + HOME


class PriceFlagTests(unittest.TestCase):
    def expect(self, cat, S):
        price = cat["price"].reindex(S.ids).values
        return (price > 40).astype(float), (price < 20).astype(float)

    def test_flags_follow_the_catalogue_at_the_thresholds(self):
        lf, _, cat = build()
        S = lf.snap; r = S.row
        for k, (price, cheap, p40) in enumerate([(5.0, 1, 0), (19.99, 1, 0), (20.0, 0, 0), (20.01, 0, 0), (30.0, 0, 0), (39.99, 0, 0), (40.0, 0, 0), (40.01, 0, 1), (80.0, 0, 1)]):
            p = f"A{k:02d}"; self.assertEqual(cat.loc[p, "price"], price)
            self.assertEqual((S.cheap[r[p]], S.p40[r[p]]), (cheap, p40), price)
        self.assertGreater(S.p40.sum(), 0); self.assertGreater(S.cheap.sum(), 0)

    def test_the_reported_reproduction(self):
        cat = pd.DataFrame([("P1", "A", "A-s0", "b0", 10.0), ("P2", "A", "A-s0", "b0", 30.0), ("P3", "A", "A-s0", "b0", 80.0)],
                           columns=["product_id", "category", "sub", "brand", "price"]).set_index("product_id")
        for c in (None, {}, {"P2": 1.5}, {"ZZZ": 1.0}, {"P2": float("nan")}, {"P2": 0.0}):
            S = lfm.Snap(list(cat.index), np.eye(3, dtype=np.float32), cat, set(), {}, 0.0, None, c)
            self.assertEqual(S.cheap.tolist(), [1.0, 0.0, 0.0], c); self.assertEqual(S.p40.tolist(), [0.0, 0.0, 1.0], c)

    def test_flags_are_identical_for_every_kind_of_corrections(self):
        base, _, cat = build()
        p40, cheap = self.expect(cat, base.snap)
        self.assertTrue(np.array_equal(base.snap.p40, p40)); self.assertTrue(np.array_equal(base.snap.cheap, cheap))
        for name, c in {**INERT, **VALID}.items():
            lf, _, _ = build(c)
            self.assertTrue(np.array_equal(lf.snap.p40, p40), name); self.assertTrue(np.array_equal(lf.snap.cheap, cheap), name)
            self.assertEqual(lf.snap.lqc is not None, name in VALID, name)

    def test_missing_or_unreadable_prices_count_as_20(self):
        for c in (None, {NEW: 2.0}):
            cat = cat_prices(); cat["price"] = cat["price"].astype(object)
            cat.loc["A00", "price"] = None; cat.loc["A08", "price"] = "n/a"
            lf, _, _ = build(c, cat=cat); S = lf.snap
            for p in ("A00", "A08"): self.assertEqual((S.cheap[S.row[p]], S.p40[S.row[p]]), (0.0, 0.0))
            self.assertEqual(S.p40[S.row["A07"]], 1.0); self.assertEqual(S.cheap[S.row["A01"]], 1.0)
            cat2 = cat_prices().drop(columns="price"); lf2, _, _ = build(c, cat=cat2)
            self.assertEqual(lf2.snap.p40.sum() + lf2.snap.cheap.sum(), 0.0)

    def test_feature_columns_carry_the_price_flags_with_and_without_corrections(self):
        i, j = lfm.FEATS.index("p40"), lfm.FEATS.index("segcheap")
        for name, c in {**INERT, **VALID}.items():
            lf, aff, cat = build(c); S = lf.snap; p40, cheap = self.expect(cat, S)
            a = aff.affinity_all("u9", ["A30"])
            for q in (None, S.lqc):
                X = lfm.features(S, a, ["A30"], "product", {}, set(), seg=True, lq=q)
                self.assertTrue(np.array_equal(X[:, i], p40), name); self.assertTrue(np.array_equal(X[:, j], cheap), name)
                X = lfm.features(S, a, ["A30"], "product", {}, set(), seg=False, lq=q)
                self.assertTrue(np.array_equal(X[:, i], p40), name); self.assertEqual(X[:, j].sum(), 0.0)


class CrossSnapshotTests(unittest.TestCase):
    """Snapshot built WITHOUT corrections against snapshots built WITH them."""

    def setUp(self):
        self.base, self.aff0, _ = build()

    def test_price_weights_matter_in_this_fixture(self):
        # guard for the tests below: with the price flags zeroed the control's scores and slates DO change here
        r = req(**SEG); S = self.base.snap
        s = scores(self.base, self.aff0, r, "r3"); sl = slate(self.base, self.aff0, r, "r3")
        S.p40 = np.zeros(S.n); S.cheap = np.zeros(S.n)
        self.assertFalse(np.array_equal(s, scores(self.base, self.aff0, r, "r3")))
        self.assertNotEqual(sl, slate(self.base, self.aff0, r, "r3"))

    def test_control_scores_and_slates_do_not_depend_on_corrections(self):
        for name, c in {**INERT, **VALID}.items():
            lf, aff, _ = build(c)
            for r in CASES:
                self.assertTrue(np.array_equal(scores(self.base, self.aff0, r, "r3"), scores(lf, aff, r, "r3")), (name, r))
                self.assertEqual(slate(self.base, self.aff0, r, "r3"), slate(lf, aff, r, "r3"), (name, r))

    def test_inert_corrections_leave_every_arm_equal_to_the_clean_control(self):
        for name, c in INERT.items():
            lf, aff, _ = build(c)
            for r in CASES:
                for arm in ("c1", "cn1"):
                    self.assertTrue(np.array_equal(scores(self.base, self.aff0, r, "r3"), scores(lf, aff, r, arm)), (name, arm, r))

    def test_home_and_cohorts_outside_the_target_keep_the_clean_control(self):
        for name, c in VALID.items():
            lf, aff, _ = build(c)
            for r in HOME:
                for arm in ("c1", "cn1"):
                    self.assertTrue(np.array_equal(scores(self.base, self.aff0, r, "r3"), scores(lf, aff, r, arm)), (name, arm, r))
                    self.assertEqual(slate(self.base, self.aff0, r, "r3"), slate(lf, aff, r, arm))
            for r in [x for x in VIEWS if not x["is_new_user"]]:                 # cold_new never touches returning shoppers
                self.assertTrue(np.array_equal(scores(self.base, self.aff0, r, "r3"), scores(lf, aff, r, "cn1")), (name, r))
                self.assertEqual(slate(self.base, self.aff0, r, "r3"), slate(lf, aff, r, "cn1"))

    def test_only_the_quality_of_the_corrected_product_moves(self):
        delta = 2.0 - (-0.39)
        for name, c in VALID.items():
            lf, aff, _ = build(c); k = lf.snap.row[NEW]; rest = np.arange(lf.snap.n) != k
            for r in VIEWS:
                seg = lfm.in_segment(r.get("device"), r.get("region")); want = (0.5 + (0.7 if seg else 0.0)) * delta
                a = scores(self.base, self.aff0, r, "r3")
                for arm in ("c1", "cn1"):
                    if arm == "cn1" and not r["is_new_user"]: continue
                    b = scores(lf, aff, r, arm)
                    self.assertTrue(np.array_equal(a[rest], b[rest]), (name, arm, r))
                    self.assertAlmostEqual(b[k] - a[k], want, places=9, msg=str((name, arm, r)))
            # feature level: against the clean snapshot only lq and seglq of that product differ
            a = lfm.features(self.base.snap, self.aff0.affinity_all("u9", ["A30"]), ["A30"], "product", {}, set(), seg=True)
            b = lfm.features(lf.snap, aff.affinity_all("u9", ["A30"]), ["A30"], "product", {}, set(), seg=True, lq=lf.snap.lqc)
            diff = np.argwhere(a != b)
            self.assertEqual({tuple(x) for x in diff.tolist()}, {(k, lfm.FEATS.index("lq")), (k, lfm.FEATS.index("seglq"))})

    def test_vectors_stay_read_only_and_separate(self):
        lf, _, _ = build(VALID["valid_and_junk"]); S = lf.snap
        self.assertFalse(np.shares_memory(S.lq, S.lqc)); self.assertEqual(int((S.lq != S.lqc).sum()), 1)
        self.assertTrue(np.array_equal(S.lq, self.base.snap.lq))                 # the incumbent vector is never altered
        for v in (S.lq, S.lqc):
            with self.assertRaises(ValueError): v[0] = 1.0
        for name, c in INERT.items():
            if c: self.assertIsNone(build(c)[0].snap.lqc, name)

    def test_purchases_and_stock_stay_excluded(self):
        c = {"B06": 9.0, NEW: 9.0, "A31": 9.0}                                   # B06 bought in the history, B39 out of stock
        lf, aff, _ = build(c, unavail={NEW}); base, aff0, _ = build(None, unavail={NEW})
        for r in (req(user="u1", new=True, **SEG), req(user="u1")):
            for arm in ("r3", "c1", "cn1"):
                s = scores(lf, aff, r, arm); S = lf.snap
                self.assertEqual(s[S.row["B06"]], -np.inf); self.assertEqual(s[S.row[NEW]], -np.inf)
                sl = slate(lf, aff, r, arm)
                self.assertEqual(len(set(sl)), 10); self.assertFalse({"B06", NEW} & set(sl))
                self.assertNotIn("A31", slate(lf, aff, r, arm, exclude={"A31"}))     # the writer's stock exclusion
            self.assertEqual(slate(base, aff0, r, "r3"), slate(lf, aff, r, "r3"))
        lf.add("u1", "A31", p=1)
        for arm in ("r3", "c1", "cn1"): self.assertNotIn("A31", slate(lf, aff, req(user="u1", new=True), arm))


if __name__ == "__main__":
    unittest.main()


class FixPolicyTests(unittest.TestCase):
    """The policies for the confirmation on the fixed base: fresh tags (so the leaderboard rows of the fixed control
    never mix with the rows served before the fix), one challenger each, same weights as the control."""

    def test_committed_policies_are_accepted_and_differ_from_the_control_by_one_key(self):
        import json
        from pathlib import Path
        from recsys import live
        here = Path(lfm.__file__).parent
        ctl = {"tag": "r3p", "file": "lfm_coef_r3.json"}
        old = {a["tag"] for f in here.glob("policy.*.json") if ".fix_" not in f.name for a in json.loads(f.read_text()).get("lfm_arms", [])}
        want = {"policy.fix_champion.json": [], "policy.fix_a_cold_new.json": [("cn1p", {"lq": "cold_new"})],
                "policy.fix_b_np1.json": [("np1p", {"w": {"known": {"newp": 1.0}}})]}
        for name, extra in want.items():
            raw = json.loads((here / name).read_text())
            self.assertEqual(raw["variant"], "lfm")
            arms = live.clean_lfm_arms(raw["lfm_arms"])
            self.assertEqual(arms, raw["lfm_arms"], name); self.assertEqual(arms[0], ctl)
            self.assertEqual([(a["tag"], {k: v for k, v in a.items() if k not in ("tag", "file")}) for a in arms[1:]], extra)
            self.assertFalse({a["tag"] for a in arms} & old, name)                 # distinguishable from every earlier row
            self.assertFalse(any("explore" in a for a in arms))
