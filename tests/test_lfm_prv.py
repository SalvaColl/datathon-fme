"""T-054: views of earlier requests (feature `prv`, LiveFit.add_request / prev_views / load_prev_hist)."""
import json, math, sys, unittest
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recsys"))
import lfm


def fit():
    return lfm.LiveFit(json.loads((lfm.HERE / "lfm_coef_r3.json").read_text()))


class PrevViews(unittest.TestCase):
    def test_feature_is_last_and_inert_in_committed_files(self):
        self.assertEqual(lfm.FEATS[-1], "prv")
        for f in lfm.HERE.glob("lfm_coef*.json"):
            c = json.loads(f.read_text())
            for seg in ("known", "new"): self.assertEqual(c[seg]["w"].get("prv", 0.0), 0.0)

    def test_store_counts_once_per_request_and_excludes_own_request(self):
        LF = fit()
        LF.add_request("u", "r1", ["a", "a", "b"])
        LF.add_request("u", "r2", ["b", "c"])
        self.assertEqual(LF.prev_views("u"), {"a": 2.0, "b": 4.0, "c": 2.0})
        self.assertEqual(LF.prev_views("u", "r2"), {"a": 2.0, "b": 2.0})      # r2 is being answered: its views are not earlier
        self.assertEqual(LF.prev_views("u", "r1"), {"a": 2.0, "b": 4.0, "c": 2.0})   # only the newest request is tracked
        self.assertEqual(LF.prev_views("nobody"), {})
        LF.add_request("u", "r3", [])
        self.assertEqual(LF.prv_last["u"][0], "r2")

    def test_history_adds_to_event_requests(self):
        LF = fit()
        n = LF.load_prev_hist(pd.DataFrame(dict(u=["u", "u", "v"], i=["a", "z", "a"], n=[3, 1, 1])))
        self.assertEqual(n, 2)
        LF.add_request("u", "r1", ["a"])
        self.assertEqual(LF.prev_views("u"), {"a": 3.0 + lfm.PRV_TODAY, "z": 1.0})
        self.assertEqual(LF.prev_views("v"), {"a": 1.0})

    def test_slates(self):
        from tests.test_lfm import FakeAff, catalog, COEF, HIST
        arms = [{"tag": "c"}, {"tag": "p", "w": {"known": {"prv": 8.0}, "new": {"prv": 8.0}}}]
        cat = catalog(); aff = FakeAff(list(cat.index))
        lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
        lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None)
        def slate(model, rid="r9", new=False):
            req = dict(user_id="u9", rv=["A30"], page="product", is_new_user=new, request_id=rid)
            return lf.slate(req, lf.user_state("u9"), aff, model=model)
        base = slate("c"); self.assertEqual(slate("p"), base)                 # empty store: the arm is the control
        self.assertNotIn("B39", base)
        lf.add_request("u9", "r1", ["B39"])
        self.assertEqual(slate("c"), base)                                    # weight 0: the store changes nothing
        for new in (False, True): self.assertIn("B39", slate("p", new=new))
        self.assertEqual(slate("p", rid="r1"), base)                          # the request being answered is not "earlier"
        self.assertEqual(len(set(slate("p"))), 10)
        self.assertTrue(lf.wants_prv())


if __name__ == "__main__":
    unittest.main()
