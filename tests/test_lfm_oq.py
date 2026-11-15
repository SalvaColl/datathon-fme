"""T-049: lfm features `orate` / `opop` (product quality read from the organic stream) and the arms that weight them."""
import json, unittest
from pathlib import Path
import numpy as np, pandas as pd

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

GOOD = {'A38', 'A39', 'B39'}                      # worst `lq` of the fixture: never in a slate on their own
ARMS = [{"tag": "r3"}, {"tag": "oq1", "w": {"known": {"lq": 0.0, "orate": 6.0, "opop": 0.5}, "new": {"lq": 0.0, "orate": 6.0, "opop": 0.5}},
                        "home": {"w": {"known": {"lq": 0.0, "orate": 6.0}, "new": {"lq": 0.0, "orate": 6.0}}}}]


def counts(cat):
    """Every product 400 organic views and 20 purchases; the GOOD ones 200 purchases."""
    return {p: (400.0, 200.0 if p in GOOD else 20.0) for p in cat.index}


def build(oq=True, arms=ARMS, hist=None):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
    c = counts(cat) if oq is True else oq
    lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None, oq=c, oq_hist=hist)
    return lf, aff


def slate(lf, aff, model, rv=('A30',), new=False, page='product'):
    req = dict(user_id='u9', rv=list(rv), page=page, is_new_user=new)
    return lf.slate(req, lf.user_state('u9'), aff, model=model)


class OrganicQualityTests(unittest.TestCase):
    def test_features_are_last_and_committed_weights_are_zero(self):
        self.assertEqual(lfm.FEATS[23:25], ["orate", "opop"])
        for f in Path(lfm.HERE).glob("lfm_coef*.json"):
            c = json.loads(f.read_text())
            for seg in ("known", "new"):
                self.assertEqual(c[seg]["w"].get("orate", 0.0), 0.0); self.assertEqual(c[seg]["w"].get("opop", 0.0), 0.0)

    def test_control_is_identical_with_and_without_counts(self):
        a, aff = build(); b, aff2 = build(oq=None)
        self.assertIsNone(b.snap.orate); self.assertIsNotNone(a.snap.orate)
        for kw in (dict(), dict(new=True), dict(page='home', rv=()), dict(page='category')):
            self.assertEqual(slate(a, aff, "r3", **kw), slate(b, aff2, "r3", **kw))

    def test_arm_ranks_by_organic_rate_on_every_page(self):
        lf, aff = build()
        for kw in (dict(), dict(new=True), dict(page='home', rv=())):
            self.assertFalse(GOOD & set(slate(lf, aff, "r3", **kw)))
            s = slate(lf, aff, "oq1", **kw)
            self.assertTrue(GOOD <= set(s)); self.assertEqual(len(set(s)), 10)

    def test_values(self):
        ids = ["p%d" % k for k in range(100)]
        oq = {p: (1000.0, 50.0) for p in ids}; oq["p0"] = (1000.0, 500.0); oq["p1"] = (100000.0, 5000.0); oq["p2"] = (30.0, 3.0)
        r, pop = lfm.organic_quality(ids, oq, hist=set(ids) - {"p2"})
        self.assertAlmostEqual(r[5], 0.0); self.assertGreater(r[0], 2.0); self.assertAlmostEqual(pop[5], 0.0)
        self.assertGreater(pop[1], 2.9); self.assertEqual(pop[2], 0.0)             # launched today: popularity neutral, rate from the stream
        self.assertAlmostEqual(r[2], np.log(4 / 50) - np.log(51 / 1020))
        self.assertTrue((np.abs(r) <= 3).all() and (np.abs(pop) <= 3).all())
        r, pop = lfm.organic_quality(ids + ["zz"], oq, hist=set(ids)); self.assertEqual((r[-1] > -1, pop[-1]), (True, 0.0))   # unknown product: prior, neutral

    def test_fails_closed(self):
        ids = ["p%d" % k for k in range(100)]
        self.assertEqual(lfm.organic_quality(ids, None), (None, None))
        self.assertEqual(lfm.organic_quality(ids, {"p1": (5.0, 1.0)}), (None, None))                 # too few products with history
        self.assertEqual(lfm.organic_quality(ids, {p: (float("nan"), 1.0) for p in ids}), (None, None))
        self.assertEqual(lfm.organic_quality(ids, {p: "x" for p in ids}), (None, None))
        lf, aff = build(oq={"A01": (1.0, 1.0)})
        self.assertIsNone(lf.snap.orate); self.assertEqual(slate(lf, aff, "oq1"), slate(build(oq=None, arms=[{"tag": "oq1", "w": {"known": {"lq": 0.0}, "new": {"lq": 0.0}}}])[0], aff, "oq1"))

    def test_wants_oq_only_when_an_arm_weights_it(self):
        lf, _ = build(); self.assertTrue(lf.wants_oq())
        lf.set_arms([{"tag": "r3"}]); self.assertFalse(lf.wants_oq())
        lf.set_arms([{"tag": "h", "home": {"w": {"new": {"opop": 0.3}}}}]); self.assertTrue(lf.wants_oq())

    def test_policy_files_pass_the_writer_check(self):
        for f in ("policy.rot_oq1.json", "policy.rot_oqh.json", "policy.rot_oq1cs.json", "policy.rot_oq2.json", "policy.rot_mf1.json", "policy.rot_mf1cs.json"):
            conf = json.loads((Path(lfm.HERE) / f).read_text())
            self.assertEqual(live.clean_lfm_arms(conf["lfm_arms"]), conf["lfm_arms"]); self.assertNotIn("lq", conf["lfm_arms"][0])

    def test_organic_counts_reads_history_plus_organic_stream_only(self):
        class T:                                          # LiveTables stand-in: the organic frame differs from the one with carousel buys
            def item_frame(self): return pd.DataFrame({"it_v": [10], "it_a": [0], "it_p": [99]}, index=["A01"])
            def organic_item_frame(self): return pd.DataFrame({"it_v": [10, 7], "it_a": [0, 0], "it_p": [2, 1]}, index=["A01", "NEW1"])
        lf, _ = build(); old = (live.LF, live.BASE, dict(live.OQ_HIST))
        try:
            live.LF = lf; live.OQ_HIST.clear()
            live.BASE = {"item": pd.DataFrame({"it_v": [100.0, 50.0], "it_a": [0.0, 0.0], "it_p": [5.0, 1.0]}, index=["A01", "A02"])}
            oq, hist = live.organic_counts(T())
            self.assertEqual(oq, {"A01": (110.0, 7.0), "A02": (50.0, 1.0), "NEW1": (7.0, 1.0)}); self.assertEqual(hist, {"A01", "A02"})
            self.assertEqual(live.organic_counts(None)[0], {"A01": (100.0, 5.0), "A02": (50.0, 1.0)})
            lf.set_arms([{"tag": "r3"}]); self.assertEqual(live.organic_counts(T()), (None, None))      # no arm asks: nothing built
            lf.set_arms(ARMS); live.OQ_HIST.clear(); live.BASE = None
            self.assertEqual(live.organic_counts(T()), (None, None))                                    # any error: features stay 0
        finally:
            live.LF, live.BASE = old[0], old[1]; live.OQ_HIST.clear(); live.OQ_HIST.update(old[2])


if __name__ == "__main__":
    unittest.main()
