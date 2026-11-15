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
        self.assertEqual(lfm.FEATS[-3:], ["prv", "hcb", "hcc"])
        for f in lfm.HERE.glob("lfm_coef*.json"):
            c = json.loads(f.read_text())
            for seg in ("known", "new"):
                for k in ("prv", "hcb", "hcc"): self.assertEqual(c[seg]["w"].get(k, 0.0), 0.0)

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


class HistoryCarousel(unittest.TestCase):
    def test_bought_in_history_carousel_comes_up_and_bought_organically_stays_out(self):
        from tests.test_lfm import FakeAff, catalog, COEF, HIST
        arms = [{"tag": "c"}, {"tag": "h", "w": {"known": {"hcb": 9.0, "hcc": 0.0}}, "home": {"w": {"known": {"hcb": 9.0}}}}]
        cat = catalog(); aff = FakeAff(list(cat.index))
        lf = lfm.LiveFit(COEF, HIST); lf.set_arms(arms)
        lf.set_catalog(cat, set(), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None)
        def slate(model, rv=("A30",), page="product", u="u9"):
            req = dict(user_id=u, rv=list(rv), page=page, is_new_user=False, request_id="r")
            return lf.slate(req, lf.user_state(u), aff, model=model)
        base = slate("c"); self.assertEqual(slate("h"), base); self.assertNotIn("B39", base)
        self.assertEqual(lf.load_hist_carousel(pd.DataFrame(dict(u=["u9", "u9", "x"], i=["B39", "A38", "B39"], b=[1, 0, 1]))), 2)
        self.assertEqual(lf.hcar["u9"], (("B39",), ("A38",)))
        self.assertEqual(slate("c"), base)
        self.assertEqual(slate("h")[0], "B39"); self.assertNotIn("A38", slate("h"))        # clicked only: weight 0 here
        self.assertEqual(slate("h", rv=(), page="home")[0], "B39")
        self.assertEqual(slate("h", u="other"), slate("c", u="other"))
        lf.add("u9", "B39", p=1)                                                             # bought since: excluded as always
        self.assertNotIn("B39", slate("h"))


if __name__ == "__main__":
    unittest.main()
