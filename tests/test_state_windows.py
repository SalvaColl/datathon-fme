"""Ventanas de estado de lfm (T-036): qué sobrevive al cambio de día / fase y qué no. Sin red, sin RawTree, sin writer."""
import unittest
import numpy as np
import pandas as pd

from recsys import lfm, live
from tests.test_lfm import build, COEF

SAT, SUN = "2026-11-14 ", "2026-11-15 "
DAY = SUN + "00:00:00"
REQ = dict(user_id="u9", rv=["A30"], page="product", is_new_user=False)


def saturday(lf):
    """A shopper's Saturday: views in B, two carts, one organic purchase, one purchase through our carousel."""
    for _ in range(20): lf.add("u9", "B02", 1, 0, 0)
    lf.add("u9", "A03", 0, 1, 0, ta=SAT + "16:00:00.000")
    lf.add("u9", "A04", 1, 1, 1, ta=SAT + "17:00:00.000", tp=SAT + "17:05:00.000")
    lf.add("u9", "B07", 0, 0, 1, tp=SAT + "23:59:59.999")           # carousel feedback, last instant of Saturday


class WindowTests(unittest.TestCase):
    def test_without_a_window_nothing_changes(self):
        a, _ = build(); b, _ = build()
        saturday(a)
        for _ in range(20): b.add("u9", "B02", 1, 0, 0)               # the same events, without their times (old call)
        b.add("u9", "A03", 0, 1, 0); b.add("u9", "A04", 1, 1, 1); b.add("u9", "B07", 0, 0, 1)
        sa, sb = a.user_state("u9"), b.user_state("u9")
        self.assertEqual(sa[:4], sb[:4]); self.assertEqual(sa[3], {"A04", "B07"}); self.assertEqual(sa[1], {"A03"})

    def test_purchases_stay_excluded_and_only_todays_feed_bought_today(self):
        lf, aff = build(); saturday(lf); lf.set_window(DAY)
        b, lc, hc, bt, mix = lf.user_state("u9")
        self.assertEqual(b, {"A04", "B07"}); self.assertEqual(bt, set())                 # excluded for ever, not "bought today"
        lf.add("u9", "A11", 0, 0, 1, tp=SUN + "00:00:00.000")                              # first instant of Sunday
        b, lc, hc, bt, mix = lf.user_state("u9")
        self.assertEqual(b, {"A04", "B07", "A11"}); self.assertEqual(bt, {"A11"})
        s = lf.slate(REQ, lf.user_state("u9"), aff)
        self.assertEqual(len(set(s)), 10); self.assertFalse({"A04", "B07", "A11"} & set(s))

    def test_boundary_is_the_event_time_not_the_arrival_order(self):
        lf, _ = build(); lf.set_window(DAY)
        lf.add("u9", "A11", 0, 0, 1, tp=SUN + "00:00:00.000"); lf.add("u9", "A12", 0, 0, 1, tp=SAT + "23:59:59.999")   # late arrival of an old event
        lf.add("u9", "A13", 0, 0, 1)                                                                                   # no time: counts as today
        self.assertEqual(lf.user_state("u9")[3], {"A11", "A13"})
        lf.add("u9", "A12", 0, 0, 1, tp=SAT + "10:00:00.000")                              # an older time never rewinds the latest one
        self.assertEqual(lf.lbought_t["u9"]["A12"], SAT + "23:59:59.999")

    def test_carts_persist_by_default_and_become_history_carts_in_day_mode(self):
        lf, aff = build(); saturday(lf); lf.set_window(DAY)
        self.assertEqual(lf.user_state("u9")[1], {"A03"})                                  # persistent: still a live cart on Sunday
        lf.set_window(DAY, carts="day")
        b, lc, hc, bt, mix = lf.user_state("u9")
        self.assertEqual(lc, set()); self.assertEqual(hc, {"A03": 1})                      # not erased: one earlier cart
        self.assertIn("A03", lf.slate(REQ, lf.user_state("u9"), aff))
        lf.add("u9", "A03", 0, 1, 0, ta=SUN + "08:00:00.000")                              # carted again on Sunday
        self.assertEqual(lf.user_state("u9")[1], {"A03"})
        lf2, _ = build(); lf2.set_window(DAY, carts="day")                                 # shopper with a 60-day history cart (B05 x2)
        lf2.add("u1", "B05", 0, 1, 0, ta=SAT + "12:00:00.000")
        self.assertEqual(lf2.user_state("u1")[2]["B05"], 3)

    def test_views_are_preferences_and_survive_the_boundary(self):
        lf, aff = build(); saturday(lf); before = lf.user_mix("u9")[0].copy()
        lf.set_window(DAY, carts="day")
        self.assertTrue(np.array_equal(lf.user_state("u9")[4][0], before)); self.assertEqual(before.sum(), 21)

    def test_bad_windows_are_rejected(self):
        lf, _ = build()
        for bad in ("2026-11-15", "2026-11-15T00:00:00", "mañana", "2026-13-40 00:00:00", 5):
            with self.assertRaises(ValueError): lf.set_window(bad)
        with self.assertRaises(ValueError): lf.set_window(DAY, carts="erase")
        self.assertIsNone(lf.day_start)
        self.assertIsNone(live.clean_state_window(None)); self.assertIsNone(live.clean_state_window({"day_start": "x"}))
        self.assertIsNone(live.clean_state_window({"day_start": DAY, "clear_purchases": True}))        # unknown key: whole spec rejected
        self.assertEqual(live.clean_state_window({"day_start": DAY}), {"day_start": DAY, "carts": "persistent"})
        self.assertEqual(live.clean_state_window({"day_start": DAY, "carts": "day"}), {"day_start": DAY, "carts": "day"})


class PhaseTransitionTests(unittest.TestCase):
    """Saturday practice -> Sunday final through the writer's own functions, without a writer."""

    def setUp(self):
        self.saved = (live.LIVE, live.AP, live.LF, live.POLICY["state_window"])
        self.lf, self.aff = build(); live.LIVE, live.AP, live.LF = live.LiveTables(), None, self.lf
    def tearDown(self):
        live.LIVE, live.AP, live.LF, live.POLICY["state_window"] = self.saved
        live.BOUGHT.pop("u9", None)

    ROWS = [dict(u="u9", i="B02", v=20, a=0, p=0, mx=SAT + "15:00:00.000", ta="1970-01-01 00:00:00.000", tp="1970-01-01 00:00:00.000"),
            dict(u="u9", i="A03", v=1, a=1, p=0, mx=SAT + "16:30:00.000", ta=SAT + "16:00:00.000", tp="1970-01-01 00:00:00.000"),
            dict(u="u9", i="A04", v=2, a=1, p=1, mx=SAT + "17:30:00.000", ta=SAT + "17:00:00.000", tp=SAT + "17:05:00.000"),
            dict(u="u9", i="A11", v=1, a=1, p=1, mx=SUN + "08:10:00.000", ta=SUN + "08:05:00.000", tp=SUN + "08:06:00.000")]

    def test_stream_times_reach_the_model_and_the_transition_keeps_what_it_should(self):
        live.apply_events(self.ROWS[:3], pause=lambda _: None)                             # Saturday, no window configured
        self.assertEqual(self.lf.user_state("u9")[3], {"A04"})
        self.lf.set_window(**live.clean_state_window({"day_start": DAY}))                  # Sunday morning: the window is switched on
        b, lc, hc, bt, mix = self.lf.user_state("u9")
        self.assertEqual((b, lc, bt), ({"A04"}, {"A03"}, set())); self.assertEqual(mix[0].sum(), 23)
        self.assertIn("A04", live.BOUGHT["u9"])                                            # the writer-wide exclusion is not touched either
        live.apply_events(self.ROWS[3:], pause=lambda _: None)                             # first Sunday events
        b, lc, hc, bt, mix = self.lf.user_state("u9")
        self.assertEqual((b, lc, bt), ({"A04", "A11"}, {"A03"}, {"A11"}))
        s = self.lf.slate(REQ, self.lf.user_state("u9"), self.aff)
        self.assertEqual(len(set(s)), 10); self.assertFalse({"A04", "A11"} & set(s))

    def test_a_restart_on_sunday_rebuilds_the_same_state(self):
        live.apply_events(self.ROWS[:3], pause=lambda _: None); self.lf.set_window(DAY); live.apply_events(self.ROWS[3:], pause=lambda _: None)
        kept = self.lf.user_state("u9")
        fresh, _ = build(); fresh.set_window(DAY); live.LF = fresh                         # new process: window first, then the whole backfill at once
        live.apply_events(list(reversed(self.ROWS)), pause=lambda _: None)
        again = fresh.user_state("u9")
        self.assertEqual(again[:4], kept[:4]); self.assertTrue(np.array_equal(again[4][0], kept[4][0]))

    def test_backfill_windows_cross_midnight_without_gaps(self):
        w = live.event_windows(SAT + "07:00:00", pd.Timestamp(SUN + "08:30:00"))
        self.assertEqual(len(w), 26); self.assertEqual(w[0][0], SAT + "07:00:00"); self.assertIsNone(w[-1][1])
        self.assertTrue(all(a[1] == b[0] for a, b in zip(w, w[1:]))); self.assertIn((SAT + "23:00:00", SUN + "00:00:00"), w)


if __name__ == "__main__":
    unittest.main()
