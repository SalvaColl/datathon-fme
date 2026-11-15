"""Compras anteriores a la final (T-063): frontera, interruptor exclude / allow, diagnóstico en sombra, guarda de envío,
recarga en caliente y vuelta atrás. Sin red, sin RawTree, sin writer."""
import copy, unittest

from recsys import lfm, live
from tests.test_lfm import build

SAT, SUN = "2026-11-14 ", "2026-11-15 "
START = SUN + "09:00:00"
REQ = dict(user_id="u9", rv=["A30"], page="product", is_new_user=False)


def shopper(lf):
    """Saturday: one organic purchase (viewed a lot), one carousel purchase, one cart. Final: one purchase."""
    for _ in range(5): lf.add("u9", "A31", 1, 0, 0)
    lf.add("u9", "A31", 0, 1, 1, ta=SAT + "17:00:00.000", tp=SAT + "17:05:00.000")
    lf.add("u9", "A32", 0, 0, 1, tp=SUN + "08:59:59.999")            # last instant before the final
    lf.add("u9", "A03", 0, 1, 0, ta=SAT + "16:00:00.000")
    lf.add("u9", "A33", 0, 0, 1, tp=SUN + "09:00:00.000")            # first instant of the final
    lf.add("u9", "A34", 0, 0, 1)                                     # purchase without a time


def top(lf, aff, n=10, user="u9"):
    return lf.slate(dict(REQ, user_id=user), lf.user_state(user), aff, n=n)


class PriorPurchaseTests(unittest.TestCase):
    def test_no_boundary_and_exclude_mode_serve_the_same_lists(self):
        a, aff = build(); b, _ = build(); c, _ = build()
        for lf in (a, b, c): shopper(lf)
        b.set_prior(START); c.set_prior(START, "allow"); c.set_prior(None)
        for n in (10, 60):
            self.assertEqual(top(a, aff, n), top(b, aff, n)); self.assertEqual(top(a, aff, n), top(c, aff, n))
        self.assertFalse({"A31", "A32", "A33", "A34"} & set(top(b, aff, 60)))
        self.assertEqual(a.user_state("u9")[:4], b.user_state("u9")[:4])
        self.assertEqual(a.prior_stats, {})                                         # no boundary: nothing is even counted

    def test_allow_frees_only_purchases_before_the_boundary(self):
        lf, aff = build(); shopper(lf); before = lf.user_state("u9")
        lf.set_prior(START, "allow")
        self.assertEqual(lf.prior_bought("u9"), {"A31", "A32"})
        s = set(top(lf, aff, 60))
        self.assertTrue({"A31", "A32"} <= s); self.assertFalse({"A33", "A34"} & s)   # final purchase and unknown time stay out
        self.assertEqual(lf.user_state("u9")[:4], before[:4])                            # history, carts, preferences: untouched
        lf.add("u9", "A31", 0, 0, 1, tp=SUN + "09:30:00.000")                         # bought again during the final
        self.assertNotIn("A31", top(lf, aff, 60)); self.assertEqual(lf.prior_bought("u9"), {"A32"})

    def test_history_purchases_stay_excluded(self):
        lf, aff = build()                                                           # u1 bought B06 in the 60-day history
        lf.add("u1", "B06", 0, 0, 1, tp=SAT + "12:00:00.000"); lf.set_prior(START, "allow")
        self.assertEqual(lf.prior_bought("u1"), set()); self.assertNotIn("B06", top(lf, aff, 70, user="u1"))

    def test_switching_back_restores_the_exclusion_without_touching_state(self):
        lf, aff = build(); shopper(lf); base = top(lf, aff, 60); times = copy.deepcopy(lf.lbought_t)
        lf.set_prior(START, "allow"); self.assertNotEqual(top(lf, aff, 60), base)
        lf.set_prior(START, "exclude"); self.assertEqual(top(lf, aff, 60), base)
        lf.set_prior(START, "allow"); lf.set_prior(None); self.assertEqual(top(lf, aff, 60), base)
        self.assertEqual(lf.lbought_t, times); self.assertEqual(lf.lbought["u9"], {"A31", "A32", "A33", "A34"})

    def test_shadow_counts_without_changing_the_answer(self):
        lf, aff = build(); shopper(lf); base = top(lf, aff)
        lf.set_prior(START)
        self.assertEqual(top(lf, aff), base); top(lf, aff, user="nobody")
        c = lf.prior_stats
        self.assertEqual((c["requests"], c["requests_with_prior"], c["prior_candidates"]), (2, 1, 2))
        lf.set_prior(START, "allow"); served = top(lf, aff)
        self.assertEqual(lf.prior_stats["products_entering"], len({"A31", "A32"} & set(served)))
        self.assertEqual(c["products_entering"], len({"A31", "A32"} & set(served)))    # the shadow predicted the allow list

    def test_bad_values_are_rejected(self):
        lf, _ = build()
        for kw in (dict(boundary="2026-11-15"), dict(boundary="2026-11-15T09:00:00"), dict(boundary=START, mode="ignore")):
            with self.assertRaises(ValueError): lf.set_prior(**kw)
        self.assertIsNone(lf.prior_start); self.assertFalse(lf.prior_allow)


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.LF, dict(live.POLICY), dict(live.BOUGHT))
        live.LF, self.aff = build(); shopper(live.LF); live.BOUGHT.clear()
        for p in ("A31", "A32", "A33", "A34"): live.BOUGHT["u9"].add(p)
        live.POLICY.update(variant="lfm", qrank_arms=[], lfm_arms=[], state_window=None, prior_purchases=None)
        self.best = list(live.LF.snap.ids); self.active = set(self.best)

    def tearDown(self):
        live.LF = self.saved[0]; live.POLICY.clear(); live.POLICY.update(self.saved[1]); live.BOUGHT.clear(); live.BOUGHT.update(self.saved[2])

    def apply(self, conf):
        new = live.check_policy(dict(variant="lfm", **conf))
        if new: live.publish_policy(new)

    def test_policy_key_switches_hot_and_the_send_guard_follows(self):
        items = ["A31", "A32", "A33", "A34"] + [f"B{k:02d}" for k in range(6)]
        clean = live.repair_for("u9", items, self.best, self.active)
        self.assertFalse({"A31", "A32", "A33", "A34"} & set(clean))
        self.apply({"prior_purchases": {"boundary": START}})                          # shadow only
        self.assertEqual(live.repair_for("u9", items, self.best, self.active), clean)
        self.apply({"prior_purchases": {"boundary": START, "mode": "allow"}})
        out = live.repair_for("u9", items, self.best, self.active)
        self.assertEqual(out[:2], ["A31", "A32"]); self.assertFalse({"A33", "A34"} & set(out))   # final purchases never sent
        self.assertEqual(live.user_bought("u9"), {"A33", "A34"})
        fb = live.user_bought("u9"); self.assertNotIn("A31", fb)
        self.apply({})                                                              # rollback: the key removed
        self.assertIsNone(live.POLICY["prior_purchases"]); self.assertFalse(live.LF.prior_allow)
        self.assertEqual(live.repair_for("u9", items, self.best, self.active), clean)

    def test_invalid_key_rejects_the_whole_policy(self):
        self.apply({"prior_purchases": {"boundary": START, "mode": "allow"}})
        for bad in ({"boundary": START, "mode": "off"}, {"boundary": "soon"}, {"mode": "allow"}, {"boundary": START, "x": 1}, "allow"):
            with self.assertRaises(live.PolicyRejected): live.check_policy({"variant": "lfm", "prior_purchases": bad})
        self.assertTrue(live.LF.prior_allow)                                         # the active configuration is kept

    def test_restart_rebuilds_the_same_mode_from_the_stream_times(self):
        self.apply({"prior_purchases": {"boundary": START, "mode": "allow"}}); a = top(live.LF, self.aff, 60)
        live.LF, _ = build(); shopper(live.LF)                                       # new process: state from the stream again
        live.POLICY["prior_purchases"] = None
        self.apply({"prior_purchases": {"boundary": START, "mode": "allow"}})
        self.assertEqual(top(live.LF, self.aff, 60), a)


if __name__ == "__main__":
    unittest.main()
