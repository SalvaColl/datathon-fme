"""T-063: taste transferred from the products of earlier requests (feature `rqa`, lfm.request_affinity)."""
import json, unittest
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

K = lfm.FEATS.index("rqa")
ARMS = [{"tag": "c"}, {"tag": "q", "w": {"known": {"rqa": 30.0}}}, {"tag": "p", "w": {"known": {"prv": 8.0}}}]


def build(arms=ARMS):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None)
    return lf, aff


def slate(lf, aff, model, rv=("A30",), new=False, rid="r9", page="product"):
    req = dict(user_id="u9", rv=list(rv), page=page, is_new_user=new, request_id=rid)
    return lf.slate(req, lf.user_state("u9"), aff, model=model)


class RequestTaste(unittest.TestCase):
    def test_feature_is_last_and_inert_in_committed_files_and_policies(self):
        self.assertEqual(K, len(lfm.FEATS) - 1); self.assertEqual(K, 30)
        for f in lfm.HERE.glob("lfm_coef*.json"):
            c = json.loads(f.read_text())
            for seg in ("known", "new"): self.assertEqual(c[seg]["w"].get("rqa", 0.0), 0.0)
        for f in lfm.HERE.glob("policy*.json"): self.assertNotIn('"rqa"', f.read_text(), f.name)
        lf, _ = build()
        self.assertEqual(float(lf.w["known"][K]), 0.0); self.assertEqual(float(lf.w["new"][K]), 0.0)

    def test_value_matches_the_affinity_formula(self):
        lf, _ = build(); S = lf.snap
        self.assertFalse(lfm.request_affinity(S, None).any()); self.assertFalse(lfm.request_affinity(S, {}).any())
        self.assertFalse(lfm.request_affinity(S, {"nope": 3.0, "A30": 0.0}).any())
        prev = {"A30": 2.0, "A31": 1.0, "B39": 4.0, "nope": 9.0}
        v = lfm.request_affinity(S, prev)
        vec = sum(c * S.A[S.row[p]] for p, c in prev.items() if p in S.row)
        for p in ("A10", "B20", "A30", "B39"):
            k = S.row[p]; own = prev.get(p, 0.0)
            num = S.A[k] @ vec - own * (S.A[k] @ S.A[k]); den = vec.sum() - own * S.A[k].sum()
            self.assertAlmostEqual(v[k], ((num + 2.0) / (den + 20.0) - 0.10) * 10.0, places=6)
        self.assertTrue(np.isfinite(v).all())

    def test_current_views_and_the_product_itself_do_not_count(self):
        lf, _ = build(); S = lf.snap
        self.assertFalse(lfm.request_affinity(S, {"A30": 2.0}, rv=["A30"]).any())          # only the views being answered
        one = lfm.request_affinity(S, {"A30": 5.0}); k = S.row["A30"]
        self.assertAlmostEqual(one[k], 0.0, places=6)                                         # its own views are `prv`, not taste
        same = [j for j in range(S.n) if j != k and (S.A[j] @ S.A[k]) > 0]
        if same: self.assertGreater(one[same[0]], 0.0)                                        # products sharing a phrase gain
        a = lfm.request_affinity(S, {"A30": 2.0, "B39": 2.0}, rv=["B39"]); b = lfm.request_affinity(S, {"A30": 2.0})
        self.assertTrue(np.allclose(a, b))

    def test_features_column_only_with_a_store(self):
        lf, aff = build(); S = lf.snap
        X0 = lfm.features(S, aff.affinity_all("u9"), ["A30"], "product", {}, set())
        self.assertFalse(X0[:, K].any())
        X1 = lfm.features(S, aff.affinity_all("u9"), ["A30"], "product", {}, set(), prev={"B39": 2.0})
        self.assertTrue(np.allclose(X1[:, K], lfm.request_affinity(S, {"B39": 2.0}, ["A30"])))
        keep = [j for j in range(len(lfm.FEATS)) if j not in (K, lfm.FEATS.index("prv"))]
        self.assertTrue(np.array_equal(X0[:, keep], X1[:, keep]))                             # nothing else moves

    def test_slates(self):
        lf, aff = build()
        base = slate(lf, aff, "c"); self.assertEqual(slate(lf, aff, "q"), base)               # empty store: the arm is the control
        lf.add_request("u9", "r1", ["B39"])
        self.assertEqual(slate(lf, aff, "c"), base)                                           # weight 0: the store changes nothing
        self.assertEqual(slate(lf, aff, "q", new=True), slate(lf, aff, "c", new=True))        # the arm weights returning shoppers only
        self.assertEqual(slate(lf, aff, "q", rid="r1"), base)                                 # the request being answered is not "earlier"
        out = slate(lf, aff, "q"); self.assertEqual(len(set(out)), 10)
        S = lf.snap; v = lfm.request_affinity(S, lf.prev_views("u9", "r9"), ["A30"])
        self.assertGreater(np.mean([v[S.row[p]] for p in out]), np.mean([v[S.row[p]] for p in base]) - 1e-12)
        self.assertTrue(lf.wants_prv())
        lf2, _ = build(arms=[{"tag": "c"}]); self.assertFalse(lf2.wants_prv())

    def test_policy_validation_accepts_the_key(self):
        arm = {"tag": "ur1", "file": "lfm_coef_r3.json", "w": {"known": {"rqa": 0.8}}}
        self.assertEqual(live.clean_lfm_arms([arm]), [arm])


if __name__ == "__main__":
    unittest.main()
