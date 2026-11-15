"""Regressions for T-052: causal evaluation and catalogue/event arrival races."""
import unittest
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from recsys import fe, lfm, live, unified_eval
from tests.test_lfm import FakeAff, catalog


class CatalogueArrivalTests(unittest.TestCase):
    def test_organic_counts_survive_events_before_catalogue_metadata(self):
        previous = fe.C
        try:
            fe.set_catalog(pd.DataFrame({"category": ["C"], "sub": ["S"]}, index=["old"]))
            table = live.LiveTables()
            table.add_organic("launch", 7, 2, 1)
            fe.set_catalog(pd.DataFrame({"category": ["C", "C"], "sub": ["S", "S"]},
                                       index=["old", "launch"]))
            counts = table.organic_item_frame()
            self.assertIsNotNone(counts)
            self.assertEqual(tuple(counts.loc["launch"]), (7, 2, 1))
            table.add_organic("launch", 3, 0, 0)
            self.assertEqual(tuple(table.organic_item_frame().loc["launch"]), (10, 2, 1))
            self.assertIsNone(table.item_frame())  # no fabricated per-user or carousel events
        finally:
            fe.set_catalog(previous)


class CausalBurstTests(unittest.TestCase):
    @staticmethod
    def counts(future=False):
        rows = []
        for k in range(12 if future else 6):
            # An ordinary 20% share becomes 36% at 10:00: not a 2x burst.
            # A future collapse of A would lower the whole-day median and falsely flag it.
            a = 20 if k < 3 else 36 if k < 6 else 0
            t = pd.Timestamp("2026-11-14 09:30") + pd.Timedelta(minutes=10 * k)
            rows.extend([(t, "a", a), (t, "b", 100 - a)])
        return pd.DataFrame(rows, columns=["b", "i", "v"])

    def test_appending_future_events_cannot_change_past_bursts(self):
        mapping = {"a": "A", "b": "B"}
        early = unified_eval.bursts(self.counts(), mapping, min_views=1)
        full = unified_eval.bursts(self.counts(True), mapping, min_views=1)
        cutoff = pd.Timestamp("2026-11-14 10:20")
        self.assertEqual(early, {t: hot for t, hot in full.items() if t <= cutoff})
        self.assertNotIn("A", full.get(pd.Timestamp("2026-11-14 10:00"), set()))

    def test_snapshot_refresh_adds_later_launches_to_burst_mapping(self):
        early = pd.DataFrame({"sub": ["A"] * 11}, index=["old"] + ["old%d" % k for k in range(10)])
        later = pd.concat([early, pd.DataFrame({"sub": ["B"]}, index=["launch"])])
        times = pd.to_datetime(["2026-11-14 09:30", "2026-11-14 11:00"])
        requests = pd.DataFrame({"ts": times})
        catalogue = SimpleNamespace(version=lambda t: int(t >= times[1]),
                                    asof=lambda v: ((later if v else early), set(), {}))
        qr = SimpleNamespace(q={"old": 1.0}, lq={}, set_catalog=lambda *args: None)
        lf = SimpleNamespace(snap=SimpleNamespace(hc=None))

        def set_catalog(cat, unavail, aff, lq, hc, **kwargs):
            lf.snap = SimpleNamespace(hc=hc, hot=kwargs["hot"])

        lf.set_catalog = set_catalog
        item10 = pd.DataFrame({"b": times, "i": ["old", "launch"], "v": [100, 200], "p": [2, 5]})
        replay = SimpleNamespace(Catalogue=lambda: catalogue)
        ranker = SimpleNamespace(Ranker=SimpleNamespace(load=lambda *args: qr))

        def proxy(items, mapping):
            return {times[1]: {mapping["launch"]}} if "launch" in mapping else {}

        with patch.object(unified_eval, "bursts", side_effect=proxy):
            result = list(unified_eval.snapshots(replay, ranker, lf, None, requests, {}, item10))
        self.assertEqual(result[1][3].hot, {"launch"})


class TargetTieTests(unittest.TestCase):
    def test_evaluator_cannot_credit_eighty_tied_products_in_ten_slots(self):
        cat = catalog()
        aff = FakeAff(list(cat.index))
        zero = {seg: np.zeros(len(lfm.FEATS)) for seg in ("known", "new")}
        bias = {seg: 0.0 for seg in zero}
        lf = lfm.LiveFit({seg: {"w": {}, "b": 0.0} for seg in zero})
        lf.set_catalog(cat, set(), aff)
        req = pd.DataFrame([dict(user_id="u9", ts=pd.Timestamp("2026-11-14 15:00"),
                                 served_by="team", purchased="", rv=["A30"], page="product",
                                 new_user=False, device="web", region="Catalunya")])
        buys = {"u9": {p: np.datetime64("2026-11-14T15:05") for p in cat.index}}
        state = (set(), set(), {}, set(), None, None)
        lb = SimpleNamespace(replay_state=lambda *args: state,
                             aff_asof=lambda *args: aff.affinity_all("u9"))
        cv = SimpleNamespace(weights=lambda spec: ((zero, bias), None),
                             dead_mask=lambda *args: np.zeros(lf.snap.n, dtype=bool),
                             TYPES=[str(k) for k in range(8)],
                             types_of=lambda *args: (np.array([7]), None, None))
        loaded = (lfm, lb, None, None, cv, req, lf, aff, {}, buys, {}, pd.DataFrame())

        def snapshots(*args, **kwargs):
            yield args[4], cat, set(), lf.snap, set(), False

        with patch.object(unified_eval, "load_all", return_value=loaded), \
             patch.object(unified_eval, "snapshots", side_effect=snapshots), \
             patch.object(unified_eval, "GRID", {"r3": {}}), \
             contextlib.redirect_stdout(io.StringIO()):
            result = unified_eval.targets()
        metrics = result["org | known/page"]["variants"]["r3"]
        self.assertEqual(metrics["at10"], 12.5)  # exactly 10 of the 80 products fit
        self.assertEqual(metrics["at3"], 3.75)


if __name__ == "__main__":
    unittest.main()
