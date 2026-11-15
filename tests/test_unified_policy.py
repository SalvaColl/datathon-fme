"""T-050: the single-arm "unified" policy (recsys/policy.unified.json), its rollback and the carts overlay, plus the
no-history fallback of the organic quality features."""
import json, unittest
from pathlib import Path
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

HERE = Path(lfm.HERE)
FILES = ("policy.unified.json", "policy.unified_nocarts.json", "policy.unified_rollback.json")
K = lfm.FEATS.index


def arms_of(name):
    conf = json.loads((HERE / name).read_text())
    return conf, live.clean_lfm_arms(conf["lfm_arms"])


class UnifiedPolicyTests(unittest.TestCase):
    def test_writer_accepts_each_policy_unchanged(self):
        for f in FILES:
            conf, arms = arms_of(f)
            self.assertEqual(conf["variant"], "lfm")
            self.assertEqual(len(arms), 1, f)                               # clean_lfm_arms returns [] for a rejected list
            self.assertEqual(arms, [{**a, "tag": a["tag"].lower()} for a in conf["lfm_arms"]], f)
            self.assertNotIn("lq", arms[0]); self.assertNotIn("explore", arms[0]); self.assertNotIn("recart", arms[0])

    def test_rollback_is_the_champion(self):
        self.assertEqual(arms_of("policy.unified_rollback.json")[1], arms_of("policy.champion.json")[1])

    def test_unified_weights(self):
        """u1 = cs2r (the live base since 15 Nov 00:20 UTC) + organic quality + trends; u1n = the same pieces on r3's carts."""
        r3 = json.loads((HERE / "lfm_coef_r3.json").read_text())
        cs2r = arms_of("policy.rot_cs2r.json")[1][0]["w"]["known"]
        for name, tag, carts in (("policy.unified.json", "u1", cs2r), ("policy.unified_nocarts.json", "u1n", {})):
            lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms_of(name)[1])
            w, _ = lf.alt[tag]; h, _ = lf.alt[tag + "@home"]
            for seg in ("known", "new"):
                self.assertEqual(w[seg][K("lq")], 0.0); self.assertGreater(w[seg][K("orate")], 0.0); self.assertIn(w[seg][K("hot")], (1.5, 4.0))
                self.assertEqual(h[seg][K("lq")], 0.0); self.assertGreater(h[seg][K("orate")], 0.0)
                self.assertEqual(h[seg][K("hot")], 0.0)                     # a burst does not take over the home page
                for f in ("chn", "cl", "islast", "oinrv", "ssub2", "scat2", "ucat", "usub", "aff10"):
                    want = carts.get(f, r3[seg]["w"].get(f, 0.0)) if seg == "known" else r3[seg]["w"].get(f, 0.0)
                    self.assertAlmostEqual(w[seg][K(f)], want, msg=(name, seg, f))        # pages: cs2r for returning shoppers, r3 for new
                    self.assertAlmostEqual(h[seg][K(f)], r3[seg]["w"].get(f, 0.0))          # home: r3
            self.assertGreater(w["known"][K("mf")], 0.0); self.assertEqual(w["new"][K("mf")], 0.0); self.assertEqual(h["known"][K("mf")], 0.0)
            self.assertTrue(lf.wants_hot() and lf.wants_oq())
            self.assertEqual(lf.alt_lq, {}); self.assertEqual(lf.alt_x, {})

    def test_rollback_asks_for_nothing_new(self):
        lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms_of("policy.unified_rollback.json")[1])
        self.assertFalse(lf.wants_hot()); self.assertFalse(lf.wants_oq())

    def test_unified_serves_valid_slates_for_every_cohort(self):
        cat = catalog(); aff = FakeAff(list(cat.index))
        lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms_of("policy.unified.json")[1])
        oq = {p: (400.0, 20.0 + int(p[1:])) for p in cat.index}
        lf.set_catalog(cat, {"A31"}, aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, hot={"A32", "A33"}, oq=oq, oq_hist=set(list(cat.index)[:60]))
        for new in (False, True):
            for rv, page in ((["A30"], "product"), (["A30", "B30"], "category"), ([], "home")):
                s = lf.slate(dict(user_id="u9", rv=rv, page=page, is_new_user=new), lf.user_state("u9"), aff, exclude={"A31"}, model="u1")
                self.assertIsNotNone(s); self.assertEqual(len(set(s)), 10); self.assertNotIn("A31", s)


class NoHistoryCatalogueTests(unittest.TestCase):
    """A catalogue where (almost) no product has a 60-day history keeps `orate` from the stream and `opop` neutral."""

    def test_orate_from_the_stream_alone(self):
        ids = ["p%d" % k for k in range(80)]
        oq = {p: (100.0, 2.0) for p in ids}; oq["p3"] = (100.0, 40.0); oq["p4"] = (100.0, 0.0)
        orate, opop = lfm.organic_quality(ids, oq, hist=set())
        self.assertIsNotNone(orate)
        self.assertTrue((opop == 0).all())
        self.assertGreater(orate[3], orate[0]); self.assertLess(orate[4], orate[0]); self.assertAlmostEqual(orate[0], 0.0)
        self.assertTrue((np.abs(orate) <= lfm.OQ_CLIP).all())

    def test_still_off_without_any_view_or_with_a_tiny_catalogue(self):
        ids = ["p%d" % k for k in range(80)]
        self.assertEqual(lfm.organic_quality(ids, {p: (0.0, 0.0) for p in ids}, hist=set()), (None, None))
        self.assertEqual(lfm.organic_quality(ids, {p: (5.0, 1.0) for p in ids[:10]}, hist=set()), (None, None))

    def test_with_history_nothing_changes(self):
        ids = ["p%d" % k for k in range(80)]
        oq = {p: (100.0 + k, 2.0 + k % 7) for k, p in enumerate(ids)}
        orate, opop = lfm.organic_quality(ids, oq, hist=set(ids[:60]))
        r = np.log((np.array([oq[p][1] for p in ids]) + lfm.OQ_PRIOR_P) / (np.array([oq[p][0] for p in ids]) + lfm.OQ_PRIOR_V))
        np.testing.assert_allclose(orate, np.clip(r - np.median(r[:60]), -lfm.OQ_CLIP, lfm.OQ_CLIP))
        self.assertTrue((opop[60:] == 0).all())


if __name__ == "__main__":
    unittest.main()
