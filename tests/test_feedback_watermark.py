"""Carousel-purchase memory after a reader outage: the feedback read restarts from the last read that was fetched and
applied, not from the wall clock minus ten minutes. The fake RawTree here HONOURS the time predicates of the feedback
query (the Stream of test_organic_quality returns every feedback row whatever the WHERE says, which hid the bug) and
only shows a row once it has landed. Synthetic, no network, deterministic."""
import re
import unittest

import pandas as pd

from recsys import fe, live
from tests.test_cold_lq import add_new, world
from tests.test_organic_quality import Stream

TS = r"f\.ts::DateTime64\(3\)"


class TimedStream(Stream):
    """Stream whose feedback answers obey `ts > lo`, `ts > now() - 10 min` (the server clock is self.clock) and
    `ts <= hi`, and only contain rows whose landing time is not after the clock."""
    def __init__(self, t0):
        super().__init__(t0); self.clock = t0

    def at(self, minutes): self.clock = self.t0 + pd.Timedelta(minutes=minutes); return self.clock
    def buy_from_carousel(self, minutes, u, i, lands=None):
        self.feedback.append(dict(u=u, i=i, t=self.ts(minutes), land=self.t0 + pd.Timedelta(minutes=minutes if lands is None else lands)))

    def query(self, sql, timeout=20):
        if ".feedback" not in sql: return super().query(sql, timeout)
        self.queries.append(sql)
        if self.fail == "feedback": raise RuntimeError("feedback query failed")
        lo = re.search(TS + r" > toDateTime64\('([^']+)',3\)", sql); hi = re.search(TS + r" <= toDateTime64\('([^']+)',3\)", sql)
        ten = "now() - INTERVAL 10 MINUTE" in sql
        out = []
        for r in self.feedback:
            t = pd.Timestamp(r["t"])
            if r["land"] > self.clock: continue
            lower = []
            if lo: lower.append(t > pd.Timestamp(lo.group(1)))
            if ten: lower.append(t > self.clock - pd.Timedelta(minutes=10))
            if lower and not any(lower): continue                         # the two lower bounds are joined by OR
            if hi and not t <= pd.Timestamp(hi.group(1)): continue
            out.append(dict(u=r["u"], i=r["i"], t=r["t"]))
        return out


class FeedbackWatermarkTests(unittest.TestCase):
    def setUp(self):
        base, _, _ = world()
        self.cat = add_new(base, [("new_a", "C0", "S0", 50.0), ("new_b", "C1", "S1", 20.0)])
        self.saved = (live.LIVE, live.fb_seen, live.query, live.LF, live.AP, fe.C, dict(live.state), dict(live.BOUGHT),
                      getattr(live, "utcnow", None))
        self.s = TimedStream(pd.Timestamp("2026-11-15 09:00:00"))
        live.query = self.s.query; live.LF = None; live.AP = None; fe.set_catalog(self.cat)
        live.utcnow = lambda: self.s.clock
        self.boot()

    def boot(self):
        """What a writer start does: empty tables and feedback memory, no feedback mark."""
        live.LIVE = live.LiveTables(); live.fb_seen = {}; live.BOUGHT.clear()
        live.state.update(ev_ts=self.s.ts(0)); live.state.pop("fb_full", None); live.state.pop("fb_ts", None)

    def tearDown(self):
        live.LIVE, live.fb_seen, live.query, live.LF, live.AP = self.saved[:5]; fe.set_catalog(self.saved[5])
        live.state.clear(); live.state.update(self.saved[6]); live.BOUGHT.clear(); live.BOUGHT.update(self.saved[7])
        if self.saved[8] is not None: live.utcnow = self.saved[8]

    def poll(self, minutes, fail=None):
        self.s.at(minutes); self.s.fail = fail
        try: live.refresh_events()
        except RuntimeError: self.assertEqual(fail, "events")
        finally: self.s.fail = None

    def bought(self, u, p="new_a"): return p in live.BOUGHT.get(u, ())
    def purchases(self, u, p="new_a"): return live.LIVE["uit"].d.get((u, p), [0, 0, 0])[2]

    def test_purchase_during_an_outage_longer_than_ten_minutes_is_recovered(self):
        """THE regression: empty read at minute 0, reader down, purchase at minute 25, next good read at minute 40."""
        self.poll(0)
        for m in (10, 20, 30): self.poll(m, fail="feedback")
        self.s.buy_from_carousel(25, "c0", "new_a")
        self.poll(40)
        self.assertTrue(self.bought("c0")); self.assertTrue(live.bought_in("c0", ["new_a"]))
        self.assertEqual(self.purchases("c0"), 1)

    def test_outage_of_the_whole_refresh_is_recovered_too(self):
        self.poll(0)
        self.s.buy_from_carousel(5, "c0", "new_a")
        for m in (10, 30, 50): self.poll(m, fail="events")           # refresh_events raises before the feedback read
        self.poll(70)
        self.assertTrue(self.bought("c0"))

    def test_failed_first_read_keeps_the_next_one_full(self):
        self.s.buy_from_carousel(-600, "old", "new_a")                # bought ten hours before this start
        self.poll(0, fail="feedback")
        self.assertIsNone(live.state.get("fb_ts")); self.assertFalse(self.bought("old"))
        self.poll(1)
        self.assertNotIn(" > toDateTime64", self.s.queries[-1].split(".feedback")[1])     # no lower bound: everything
        self.assertTrue(self.bought("old"))

    def test_mark_advances_on_empty_reads_and_never_on_failed_ones(self):
        self.poll(0); self.assertEqual(live.state["fb_ts"], self.s.ts(0))
        self.poll(3); self.assertEqual(live.state["fb_ts"], self.s.ts(3))                 # empty but successful
        self.poll(6, fail="feedback"); self.assertEqual(live.state["fb_ts"], self.s.ts(3))
        self.poll(9, fail="events"); self.assertEqual(live.state["fb_ts"], self.s.ts(3))
        self.poll(12); self.assertEqual(live.state["fb_ts"], self.s.ts(12))
        q = self.s.queries[-1]                                         # lower bound = last good read (minute 3) - overlap
        lo = str(self.s.t0 + pd.Timedelta(minutes=3) - pd.Timedelta(seconds=live.FB_OVERLAP_S))[:23]
        self.assertIn(f"> toDateTime64('{lo}',3)", q); self.assertIn(f"<= toDateTime64('{self.s.ts(12)}',3)", q)

    def test_application_failure_does_not_advance_the_mark(self):
        self.poll(0)
        self.s.buy_from_carousel(1, "c0", "new_a")
        real = live.LIVE.add
        def boom(*a): raise ValueError("apply failed")
        live.LIVE.add = boom
        try: self.poll(2)
        finally: live.LIVE.add = real
        self.assertEqual(live.state["fb_ts"], self.s.ts(0))

    def test_row_exactly_on_a_read_boundary_is_taken_once(self):
        self.poll(0)
        self.s.buy_from_carousel(5, "edge", "new_a")                  # ts == upper bound of the read at minute 5
        self.poll(5)
        self.assertTrue(self.bought("edge"))                           # the upper bound is inclusive
        self.s.buy_from_carousel(5, "edge2", "new_a", lands=6)        # same instant, landed after that read
        for m in (6, 7, 30): self.poll(m)
        self.assertTrue(self.bought("edge2"))
        self.assertEqual(self.purchases("edge"), 1); self.assertEqual(self.purchases("edge2"), 1)

    def test_rows_after_the_upper_bound_wait_for_the_next_read(self):
        self.poll(0)
        self.s.buy_from_carousel(4, "ahead", "new_a", lands=0)        # server clock ahead of ours: ts after our upper bound
        self.poll(1); self.assertFalse(self.bought("ahead"))
        self.poll(5); self.assertTrue(self.bought("ahead"))

    def test_overlap_duplicates_are_applied_once(self):
        self.poll(0)
        self.s.buy_from_carousel(1, "c0", "new_a"); self.s.buy_from_carousel(1.5, "c0", "new_a")     # same pair twice
        for m in (2, 3, 4, 5, 6): self.poll(m)                         # each read contains both rows again
        self.assertEqual(self.purchases("c0"), 1)
        self.assertEqual(live.LIVE["utot"].d["c0"], [0, 1])
        self.assertIsNone(live.LIVE.organic_item_frame())              # carousel purchases never enter the organic counts

    def test_late_row_inside_the_overlap_is_read(self):
        for m in range(0, 21): self.poll(m)
        self.s.buy_from_carousel(20, "late", "new_a", lands=20 + live.FB_OVERLAP_S / 60 - 1)        # lands 9 min late
        for m in range(21, 32): self.poll(m)
        self.assertTrue(self.bought("late"))

    def test_late_row_beyond_the_overlap_waits_for_the_restart(self):
        """No unbounded promise: a row that lands later than the overlap is only recovered by the full read of a start."""
        for m in range(0, 21): self.poll(m)
        self.s.buy_from_carousel(20, "verylate", "new_a", lands=45)
        for m in range(21, 60): self.poll(m)
        self.assertFalse(self.bought("verylate"))
        self.boot(); self.poll(60)                                     # restart: full reconstruction
        self.assertTrue(self.bought("verylate"))

    def test_restart_rebuilds_every_carousel_purchase(self):
        self.poll(0)
        self.s.buy_from_carousel(1, "c0", "new_a"); self.s.buy_from_carousel(2, "c1", "new_b")
        self.poll(3); self.poll(120)
        self.boot(); self.assertFalse(self.bought("c0"))
        self.poll(121)
        self.assertTrue(self.bought("c0")); self.assertTrue(self.bought("c1", "new_b"))
        self.assertEqual(self.purchases("c0"), 1)

    def test_organic_purchase_exclusion_does_not_depend_on_the_feedback_read(self):
        self.s.event(1, "o0", "new_a", "purchase")
        self.poll(2, fail="feedback")
        self.assertTrue(self.bought("o0"))


if __name__ == "__main__":
    unittest.main()
