"""lfm_build: the replay must rebuild exactly what the writer knew at each request. No network, no RawTree, no writer."""
import json, sys, unittest
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "recsys"))
import lfm, lfm_build as B

T0 = np.datetime64("2026-11-14T12:00:00")
def at(sec): return T0 + np.timedelta64(sec, "s")


class FakeAff:
    def __init__(self, ids):
        self.pid = {p: k for k, p in enumerate(ids)}; self.today = {}
        self.A = np.zeros((len(ids), 20), dtype=np.float32)
        for k in range(len(ids)): self.A[k, [k % 20, (k + 1) % 20]] = 1
    def affinity_all(self, u, rv=()): return np.full(len(self.pid), 0.10)


def catalog():
    rows = [(f"{c}{k:02d}", c, f"{c}-s{k % 2}", f"b{k % 3}", 10.0 + k) for c in ("A", "B") for k in range(40)]
    return pd.DataFrame(rows, columns=["product_id", "category", "sub", "brand", "price"]).set_index("product_id")


W = dict(aff10=2.0, chn=1.2, cl=1.1, islast=1.9, oinrv=1.8, ssub2=1.3, scat2=1.0, na=0.3, home=-0.3, lq=0.5, sbrand=0.1, ucat=4.0, usub=1.3)
COEF = {s: dict(w=dict(W), b=-9.0) for s in ("known", "new")}
HIST = pd.DataFrame([("u1", "B05", 3, 2, 0), ("u1", "B06", 1, 1, 1), ("u1", "A07", 4, 0, 0)], columns=["u", "i", "v", "a", "p"])


def build():
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST); lf.set_catalog(cat, set(), aff, {p: 0.0 for p in cat.index}, None)
    return lf, aff


class ReplayStateParityTests(unittest.TestCase):
    """C1: the replayed state has the same five parts the writer serves with."""

    def setUp(self):
        self.live, self.aff = build(); self.rep, _ = build()
        # what happened today, fed to the writer's model ...
        for _ in range(20): self.live.add("u9", "B02", 1, 0, 0)
        self.live.add("u9", "A03", 0, 1, 0); self.live.add("u9", "A04", 0, 1, 1)
        # ... and the same facts as the replay reads them from the pulled files
        self.aff.today = {"u9": [(at(0), self.aff.pid["B02"], 20)]}
        self.carts = {"u9": {"A03": at(1), "A04": at(2)}}; self.buys = {"u9": {"A04": at(3)}}
        self.req = dict(user_id="u9", rv=[], page="product", is_new_user=False)

    def test_replay_state_equals_serving_state(self):
        live = self.live.user_state("u9"); rep = B.replay_state(self.rep, self.aff, self.carts, self.buys, "u9", at(60))
        self.assertEqual(len(rep), len(live)); self.assertEqual(len(rep), 6)
        self.assertEqual(rep[:4], live[:4])
        for x, y in zip(rep[4], live[4]): self.assertTrue(np.array_equal(x, y))

    def test_replayed_slate_equals_served_slate_and_fails_when_mix_is_omitted(self):
        served = self.live.slate(self.req, self.live.user_state("u9"), self.aff)
        full = B.replay_state(self.rep, self.aff, self.carts, self.buys, "u9", at(60))
        self.assertEqual(self.rep.slate(self.req, full, self.aff), served)
        self.assertTrue(all(p.startswith("B") for p in served))                       # the favourite category decides this slate
        short = B.state_asof(self.rep, self.carts, self.buys, "u9", at(60))          # the old report() call: four parts
        self.assertNotEqual(self.rep.slate(self.req, short, self.aff), served)

    def test_only_events_before_the_request_count(self):
        b, lc, hc, bt, mix, _ = B.replay_state(self.rep, self.aff, self.carts, self.buys, "u9", at(0))
        self.assertEqual((b, lc, bt), (set(), set(), set())); self.assertEqual(mix[0].sum(), 0)     # an event stamped at the request is not yet known
        b, lc, hc, bt, mix, _ = B.replay_state(self.rep, self.aff, self.carts, self.buys, "u9", at(3))
        self.assertEqual(lc, {"A03", "A04"}); self.assertEqual(bt, set()); self.assertEqual(mix[0].sum(), 20)


class FeedbackPurchaseTests(unittest.TestCase):
    """C2: purchases made through our carousel count as bought once their feedback was readable, never before."""

    def test_usable_only_after_the_feedback_row_plus_the_read_lag(self):
        d = pd.DataFrame(dict(user_id=["u9", "u9", "u8"], purchased=["A10", "", "B01"],
                              fb_ts=["2026-11-14 12:00:10", "2026-11-14 12:00:20", "2026-11-14 12:05:00"]))
        fb = B.feedback_buys(d); lf, aff = build(); aff.fbuys = fb
        self.assertEqual(set(fb), {"u9", "u8"}); self.assertEqual(fb["u9"]["A10"], at(10) + B.FB_LAG)
        lag = int(B.FB_LAG / np.timedelta64(1, "s"))
        for sec, known in ((5, False), (10, False), (10 + lag, False), (11 + lag, True)):
            b, lc, hc, bt, _, _ = B.replay_state(lf, aff, {}, {}, "u9", at(sec))
            self.assertEqual("A10" in b, known, sec); self.assertEqual("A10" in bt, known, sec)
        self.assertNotIn("B01", B.replay_state(lf, aff, {}, {}, "u9", at(900))[0])     # another shopper's purchase

    def test_earliest_feedback_wins_and_old_files_without_fb_ts_add_nothing(self):
        d = pd.DataFrame(dict(user_id=["u9", "u9"], purchased=["A10", "A10"], fb_ts=["2026-11-14 12:03:00", "2026-11-14 12:01:00"]))
        self.assertEqual(B.feedback_buys(d)["u9"]["A10"], at(60) + B.FB_LAG)
        self.assertEqual(B.feedback_buys(d.drop(columns="fb_ts")), {})

    def test_a_carousel_purchase_removes_the_live_cart(self):
        lf, aff = build(); aff.fbuys = {"u9": {"A03": at(10)}}
        self.assertEqual(B.replay_state(lf, aff, {"u9": {"A03": at(1)}}, {}, "u9", at(5))[1], {"A03"})
        self.assertEqual(B.replay_state(lf, aff, {"u9": {"A03": at(1)}}, {}, "u9", at(11))[1], set())


class CatalogueAsOfTests(unittest.TestCase):
    """C3: price, existence and stock as of each request; shown-item features apart from the candidate universe."""

    def setUp(self):
        self.lf, self.aff = build(); S = self.lf.snap
        base = [(p, "", 10.0 + int(p[1:]), True, "base") for p in S.ids if p != "B39"]            # B39 is launched during the event
        up = [("A00", "2026-11-14 12:10:00", 55.0, True, "price_change"), ("A01", "2026-11-14 12:10:00", 11.0, False, "out_of_stock"),
              ("A01", "2026-11-14 12:20:00", 11.0, True, "back_in_stock"), ("B39", "2026-11-14 12:15:00", 49.0, True, "new_product"),
              ("ZZ9", "2026-11-14 12:15:00", 1.0, True, "new_product")]                              # not in the snapshot: ignored
        self.log = B.CatLog(pd.DataFrame(base + up, columns=["product_id", "ts", "price", "active", "change"]), S); self.r = S.row

    def test_price_existence_and_stock_at_the_boundaries(self):
        r = self.r
        ex, un, pr = self.log.at(at(599)); self.assertEqual((pr[r["A00"]], bool(un[r["A01"]]), bool(ex[r["B39"]])), (10.0, False, False))
        ex, un, pr = self.log.at(at(600)); self.assertEqual((pr[r["A00"]], bool(un[r["A01"]])), (55.0, True))      # stamped at the request: in force
        ex, un, pr = self.log.at(at(900)); self.assertTrue(ex[r["B39"]]); self.assertEqual(pr[r["B39"]], 49.0)
        self.assertFalse(self.log.at(at(1200))[1][r["A01"]])                                                       # back in stock
        inel = self.log.ineligible(at(700)); self.assertTrue(inel[r["A01"]] and inel[r["B39"]]); self.assertEqual(int(inel.sum()), 2)
        self.assertEqual(self.log.at(at(0))[2][r["A00"]], 10.0)                                                    # going back in time rebuilds from the start
        self.assertEqual(int(self.log.ineligible(at(0)).sum()), 1)

    def test_shown_item_price_features_use_the_price_of_the_moment(self):
        S = self.lf.snap; p40 = lfm.FEATS.index("p40"); rows = np.array([self.r["A00"], self.r["A35"]])
        def feats(sec):
            X = lfm.features(S, self.aff.affinity_all("u9"), [], "product", {}, set(), idx=list(rows))
            return self.log.price_features(X, rows, at(sec), False)[:, p40].tolist()
        self.assertEqual(feats(0), [0.0, 1.0]); self.assertEqual(feats(700), [1.0, 1.0])

    def test_candidate_universe_excludes_what_could_not_be_served_then(self):
        S = self.lf.snap; req = dict(user_id="u9", rv=["A01", "B39"], page="product", is_new_user=False)
        st = B.replay_state(self.lf, self.aff, {}, {}, "u9", at(700))
        now = self.lf.slate(req, st, self.aff); self.assertIn("A01", now); self.assertIn("B39", now)                # today's catalogue would serve both
        excl = {S.ids[k] for k in np.nonzero(self.log.ineligible(at(700)))[0]}
        then = self.lf.slate(req, st, self.aff, exclude=excl)
        self.assertEqual(len(set(then)), 10); self.assertFalse({"A01", "B39"} & set(then))


class CutoffTests(unittest.TestCase):
    """C4: a learned artifact that saw the evaluation period cannot be scored on it."""

    def test_r3_file_overlaps_a_1530_holdout(self):
        r3 = json.loads((ROOT / "recsys" / "lfm_coef_r3.json").read_text())
        self.assertGreater(B.fitted_until(r3), pd.Timestamp("2026-11-14 15:30"))
        self.assertTrue(B.leaks(r3, "2026-11-14 15:30")); self.assertFalse(B.leaks(r3, "2026-11-14 16:30"))

    def test_boundary_and_missing_provenance(self):
        c = dict(meta=dict(fitted_on="2026-11-14 10:00:00 .. 2026-11-14 15:30:00 UTC"))
        self.assertTrue(B.leaks(c, "2026-11-14 15:30:00")); self.assertFalse(B.leaks(c, "2026-11-14 15:30:01"))
        self.assertIsNone(B.fitted_until({})); self.assertTrue(B.leaks({}, "2026-11-14 15:30"))               # no provenance = not trusted


class CalibrationTests(unittest.TestCase):
    """C5: fit_add moves intercept / slot / added weights, so it refits the purchase calibration on its own rows."""

    def test_fit_add_does_not_inherit_the_base_calibration(self):
        rng = np.random.default_rng(0); n = 6000
        I = pd.DataFrame(rng.normal(size=(n, len(lfm.FEATS))) * 0.3, columns=lfm.FEATS)
        I["slot"] = rng.integers(1, 11, n); I["ls"] = np.log(I.slot); I["new_user"] = rng.random(n) < 0.5; I["dead"] = 0; I["rid"] = np.arange(n) // 10
        z = -2.0 + 1.5 * I.aff10 + 1.0 * I.cv - 0.3 * I.ls
        I["clk"] = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int); I["buy"] = (I.clk * (rng.random(n) < 0.4)).astype(int)
        base = {s: dict(w={f: 0.0 for f in lfm.FEATS} | dict(aff10=1.5), b=-2.0, slot=-0.3, cal=[5.0, 0.1]) for s in ("known", "new")}
        out = B.fit_add(I, base, ["cv"])
        for s, new in (("known", False), ("new", True)):
            a = I[I.new_user == new]
            self.assertNotEqual(out[s]["cal"], base[s]["cal"])
            self.assertEqual(out[s]["w"]["aff10"], 1.5)                                      # base weights untouched
            pred = B.p_buy(out, s, a[lfm.FEATS].values, a.slot.values).sum()
            self.assertLess(abs(pred - a.buy.sum()) / a.buy.sum(), 0.03)                     # calibrated on its training rows
            stale = B.p_buy(dict(out, **{s: dict(out[s], cal=base[s]["cal"])}), s, a[lfm.FEATS].values, a.slot.values).sum()
            self.assertGreater(abs(stale - a.buy.sum()) / a.buy.sum(), 0.5)                  # the inherited one was not


if __name__ == "__main__":
    unittest.main()
