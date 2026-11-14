"""T-CS01: cold_lq adapter (live_quality estimate -> lfm's lq for products without history). Synthetic, no network."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

from recsys import cold_lq, live_quality


def prior(cat):
    """Stand-in for the cold_items GLM: rate grows with price; the 'premium' phrase doubles it."""
    d = cat.description.fillna("") if "description" in cat else pd.Series("", index=cat.index)
    return (0.01 * (1 + cat.price.astype(float).fillna(0) / 100) * np.where(d.str.contains("premium"), 2.0, 1.0)).to_numpy()


def world(n_sub=3, per_sub=12):
    rows, q, hist = [], {}, []
    for s in range(n_sub):
        for k in range(per_sub):
            p = f"old_{s}_{k}"; r = 0.002 * (k + 1) * (s + 1)
            rows.append((p, f"C{s % 2}", f"S{s}", "b", 10.0 + k)); hist.append((p, 1000.0, 1000.0 * r))
            q[p] = 1e-4 * (r / 0.002) ** 2
    cat = pd.DataFrame(rows, columns=["product_id", "category", "sub", "brand", "price"]).set_index("product_id")
    return cat, q, pd.DataFrame(hist, columns=["product_id", "it_v", "it_p"]).set_index("product_id")


def add_new(cat, specs):
    extra = pd.DataFrame([(p, c, s, "b", pr) for p, c, s, pr in specs],
                         columns=["product_id", "category", "sub", "brand", "price"]).set_index("product_id")
    return pd.concat([cat, extra])


def qr(q):
    return SimpleNamespace(q=q, lq={p: math.log(max(v, 1e-6)) for p, v in q.items()}, ok=set(q))


class ColdLQTests(unittest.TestCase):
    def setUp(self):
        self.cat, self.q, self.hist = world()
        self.clq = cold_lq.ColdLQ(live_quality.LiveQuality(prior=prior))
        self.tmp = tempfile.TemporaryDirectory(); self.conf = Path(self.tmp.name) / "coldlq.json"
        self.p = mock.patch.object(cold_lq, "CONF", self.conf); self.p.start()

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def on(self): self.conf.write_text(json.dumps({"mode": "on"}))

    def test_off_returns_qranks_own_dict_untouched(self):
        cat = add_new(self.cat, [("new_a", "C0", "S0", 50.0)]); Q = qr(self.q); Q.lq["new_a"] = -9.0
        self.assertIs(self.clq.lq_for_lfm(Q, cat, self.hist), Q.lq)                 # no file
        self.conf.write_text(json.dumps({"mode": "off"}))
        self.assertIs(self.clq.lq_for_lfm(Q, cat, self.hist), Q.lq)
        self.conf.write_text("not json")
        self.assertIs(self.clq.lq_for_lfm(Q, cat, self.hist), Q.lq)

    def test_on_patches_only_products_without_history_q(self):
        self.on(); cat = add_new(self.cat, [("new_a", "C0", "S0", 50.0)]); Q = qr(self.q); Q.lq["new_a"] = -9.0
        before = dict(Q.lq)
        out = self.clq.lq_for_lfm(Q, cat, self.hist)
        self.assertIsNot(out, Q.lq); self.assertEqual(Q.lq, before)                 # qrank's own dict not mutated
        self.assertNotEqual(out["new_a"], -9.0)
        self.assertEqual({p: out[p] for p in self.q}, {p: before[p] for p in self.q})   # established unchanged
        self.assertEqual(set(self.clq.last), {"new_a"}); self.assertEqual(Q.ok, set(self.q))   # eligibility untouched

    def test_prior_orders_new_products_without_live_data(self):
        self.on()
        cat = add_new(self.cat, [("new_cheap", "C0", "S0", 1.0), ("new_dear", "C0", "S0", 300.0)])
        out = self.clq.estimate(self.q, cat, self.hist, None, {"new_prem": "x premium"})
        self.assertLess(out["new_cheap"], out["new_dear"])
        cat2 = add_new(self.cat, [("new_plain", "C0", "S0", 1.0), ("new_prem", "C0", "S0", 1.0)])
        out2 = self.clq.estimate(self.q, cat2, self.hist, None, {"new_prem": "x premium"})
        self.assertLess(out2["new_plain"], out2["new_prem"])

    def test_live_evidence_takes_over_as_views_accumulate(self):
        cat = add_new(self.cat, [("new_a", "C0", "S0", 1.0)])
        live = lambda v, rate: pd.DataFrame({"it_v": [v], "it_p": [rate * v]}, index=["new_a"])
        lq0 = self.clq.estimate(self.q, cat, self.hist, None)["new_a"]
        hot = [self.clq.estimate(self.q, cat, self.hist, live(v, 0.2))["new_a"] for v in (20, 200, 5000)]
        cold = self.clq.estimate(self.q, cat, self.hist, live(5000, 0.0005))["new_a"]
        self.assertLess(lq0, hot[0]); self.assertLess(hot[0], hot[1]); self.assertLess(hot[1], hot[2])
        self.assertLess(cold, lq0)
        self.assertAlmostEqual(float(self.clq.lq.rate["new_a"]), 0.0005, delta=0.0005)

    def test_unknown_subcategory_category_and_new_user_free(self):
        cat = add_new(self.cat, [("new_x", "C1", "S_unseen", 10.0), ("new_y", "C_unseen", "S_unseen2", 10.0)])
        out = self.clq.estimate(self.q, cat, self.hist, None)
        self.assertEqual(set(out), {"new_x", "new_y"}); self.assertTrue(all(math.isfinite(v) for v in out.values()))

    def test_prior_failure_and_bad_input_never_raise(self):
        self.on()
        broken = cold_lq.ColdLQ(live_quality.LiveQuality(prior=mock.Mock(side_effect=ValueError("bad"))))
        cat = add_new(self.cat, [("new_a", "C0", "S0", float("nan"))])
        self.assertTrue(math.isfinite(broken.estimate(self.q, cat, self.hist, None)["new_a"]))   # subcategory fallback
        Q = qr(self.q)
        self.assertIs(self.clq.lq_for_lfm(Q, cat.drop(columns=["sub"]), self.hist), Q.lq)          # error -> unchanged
        self.assertIs(self.clq.lq_for_lfm(Q, self.cat, self.hist), Q.lq)                           # no new product

    def test_catalogue_changes_follow_the_snapshot(self):
        a = self.clq.estimate(self.q, add_new(self.cat, [("new_a", "C0", "S0", 10.0)]), self.hist)
        b = self.clq.estimate(self.q, add_new(self.cat, [("new_b", "C0", "S1", 10.0)]), self.hist)   # new_a delisted
        self.assertEqual(set(a), {"new_a"}); self.assertEqual(set(b), {"new_b"})

    def test_no_hot_subcategory_or_promo_multipliers_reach_lfm(self):
        cat = add_new(self.cat, [("new_a", "C0", "S0", 10.0)])
        self.clq.estimate(self.q, cat, self.hist, None)
        self.assertEqual(self.clq.lq.sub_mult, {}); self.assertEqual(self.clq.lq.promo, set())

    def test_deterministic(self):
        cat = add_new(self.cat, [("new_a", "C0", "S0", 10.0), ("new_b", "C1", "S2", 20.0)])
        runs = [cold_lq.ColdLQ(live_quality.LiveQuality(prior=prior)).estimate(self.q, cat, self.hist) for _ in range(3)]
        self.assertTrue(runs[0] == runs[1] == runs[2])


if __name__ == "__main__":
    unittest.main()
