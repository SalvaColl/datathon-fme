"""eval_slices: piezas de la validación con compradores y productos no vistos. Sin red, sin RawTree, sin writer."""
import sys, unittest
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "recsys"))
import eval_slices as E


class EvalSliceTests(unittest.TestCase):
    def test_folds_are_stable_and_keep_a_shopper_whole(self):
        users = [f"u_{k}" for k in range(5000)]; f = [E.fold(u) for u in users]
        self.assertEqual(f, [E.fold(u) for u in users]); self.assertEqual(set(f), set(range(E.FOLDS)))
        self.assertLess(max(np.bincount(f)) / min(np.bincount(f)), 1.2)

    def test_masked_copy_hides_history_and_keeps_todays_events(self):
        class Aff: pass
        aff = Aff(); aff.today = {"u1": [(1, 2, 3)]}; aff.fbuys = {"u1": {"p": 5}}
        d = pd.DataFrame(dict(user_id=["u1", "u2"], x=[1, 2]))
        d2, today, fb, carts, buys, saved = E.masked_copy(d, aff, {"u1": {"a": 1}}, {"u2": {"b": 2}})
        self.assertEqual(list(d2.user_id), ["~u1", "~u2"]); self.assertEqual(list(d.user_id), ["u1", "u2"])       # the original is untouched
        self.assertEqual((today, fb, carts, buys), ({"~u1": [(1, 2, 3)]}, {"~u1": {"p": 5}}, {"~u1": {"a": 1}}, {"~u2": {"b": 2}}))
        self.assertIs(saved[0], aff.today)

    def test_slot_gain_is_zero_without_signal_and_credits_the_bought_product(self):
        I = pd.DataFrame(dict(rid=[1] * 10 + [2] * 10, slot=list(range(1, 11)) * 2))
        self.assertTrue(np.allclose(E.slot_gain(I, np.zeros(20), -0.8), 0))
        z = np.zeros(20); z[4] = 2.0                                           # the weights like the product in slot 5 of request 1
        g = E.slot_gain(I, z, -0.8)
        self.assertGreater(g[4], 0); self.assertTrue((g[:4] < 0).all()); self.assertTrue(np.allclose(g[10:], 0))
        strong = E.slot_gain(I, z, -3.0)                                       # a stronger position effect leaves less credit to the weights
        self.assertGreater(strong[4], g[4]); self.assertTrue(np.allclose(E.slot_gain(I, np.zeros(20), -3.0), 0))

    def test_interval_resamples_whole_shoppers(self):
        rr = [1.0] * 50 + [0.1] * 50
        m, lo, hi = E.mrr_ci(rr, ["heavy"] * 50 + [f"u{k}" for k in range(50)])    # one shopper made half of the purchases
        m2, lo2, hi2 = E.mrr_ci(rr, [f"v{k}" for k in range(100)])
        self.assertAlmostEqual(m, 0.55); self.assertAlmostEqual(m2, 0.55)
        self.assertGreater(hi - lo, 1.5 * (hi2 - lo2))                             # repeated shoppers widen the interval
        self.assertTrue(np.isnan(E.mrr_ci([], [])[0]))


if __name__ == "__main__":
    unittest.main()
