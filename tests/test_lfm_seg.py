"""T-057: what the shopper's segment (device x region) buys: features gsub / gbrand / gphr, tables in lfm_seg.json."""
import json, sys, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recsys import lfm
from tests.test_lfm import build

K = [lfm.FEATS.index(f) for f in ("gsub", "gbrand", "gphr")]


class SegmentPrior(unittest.TestCase):
    def setUp(self):
        self.old = lfm._SEG[0]
        self.lf, self.aff = build(); S = self.lf.snap
        self.sub, self.brand = S._names[0][0], S._names[1][0]
        lfm._SEG[0] = {"sub": {"ios|Madrid": {self.sub: 0.5}}, "brand": {"ios|Madrid": {self.brand: -0.25}},
                       "phr": {"ios|Madrid": [0.1] * S.A.shape[1]}}

    def tearDown(self): lfm._SEG[0] = self.old

    def X(self, grp):
        S = self.lf.snap
        return lfm.features(S, self.aff.affinity_all("u9", ["A30"]), ["A30"], "product", {}, set(), grp=grp)

    def test_features_are_last_and_inert_in_committed_files(self):
        self.assertEqual(lfm.FEATS[-3:], ["gsub", "gbrand", "gphr"]); self.assertEqual(K, [29, 30, 31])
        for f in lfm.HERE.glob("lfm_coef*.json"):
            c = json.loads(f.read_text())
            for seg in ("known", "new"):
                for k in ("gsub", "gbrand", "gphr"): self.assertEqual(c[seg]["w"].get(k, 0.0), 0.0)

    def test_values_follow_the_segment_table(self):
        S = self.lf.snap; X = self.X("ios|Madrid")
        np.testing.assert_allclose(X[:, K[0]], np.where(S._names[0] == self.sub, 0.5, 0.0))
        np.testing.assert_allclose(X[:, K[1]], np.where(S._names[1] == self.brand, -0.25, 0.0))
        np.testing.assert_allclose(X[:, K[2]], 0.1 * np.asarray(S.A, dtype=float).sum(axis=1), rtol=1e-5)

    def test_unknown_segment_or_no_segment_is_zero(self):
        for grp in ("tv|Mars", None, lfm.seg_key(None, None)):
            self.assertFalse(self.X(grp)[:, K].any())

    def test_no_file_means_zero(self):
        lfm._SEG[0] = {}; self.lf.snap._grp.clear()
        self.assertFalse(self.X("ios|Madrid")[:, K].any())

    def test_scores_ask_for_the_segment_only_when_weighted(self):
        lf, aff = self.lf, self.aff; S = lf.snap
        req = dict(user_id="u9", rv=["A30"], page="product", is_new_user=True, device="ios", region="Madrid")
        base = lf.scores(req, lf.user_state("u9"), aff)[1].copy()
        self.assertEqual(S._grp, {})                       # weight 0: the table is not even looked up
        lf.w["new"][K[0]] = 2.0
        s = lf.scores(req, lf.user_state("u9"), aff)[1]
        live = np.isfinite(base) & np.isfinite(s)
        np.testing.assert_allclose((s - base)[live], np.where(S._names[0] == self.sub, 1.0, 0.0)[live], atol=1e-9)

    def test_committed_tables_cover_every_segment_and_are_centred(self):
        T = json.loads(lfm.SEGT.read_text())
        self.assertEqual(len(T["sub"]), 30); self.assertEqual(set(T["sub"]), set(T["brand"])); self.assertEqual(set(T["sub"]), set(T["phr"]))
        for name in ("sub", "brand"):
            for row in T[name].values(): self.assertLess(abs(np.mean(list(row.values()))), 0.02)


if __name__ == "__main__": unittest.main()
