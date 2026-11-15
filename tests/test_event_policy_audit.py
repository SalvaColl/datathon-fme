"""Temporal/data integrity of the read-only promotion/trend research tool."""
import unittest
import numpy as np
import pandas as pd
from tools import event_policy_audit as audit


class AuditTests(unittest.TestCase):
    def test_promotion_depth_never_infers_savings_from_missing_or_bad_prices(self):
        price = np.array([80., 100., 120., np.nan, 0., -1., 20.])
        reference = np.array([100., 100., 100., 100., 100., 100., np.nan])
        np.testing.assert_allclose(audit.promotion_depth(price, reference), [1, 0, 0, 0, 0, 0, 0])

    def test_future_minutes_cannot_change_past_detector_flags(self):
        origin = pd.Timestamp("2026-11-14 09:00")
        def frame(n):
            rows = []
            for k in range(n):
                a = 60 if 195 <= k < 200 else 20 if k < 200 else 0
                rows.extend([(origin + pd.Timedelta(minutes=k), "A", a),
                             (origin + pd.Timedelta(minutes=k), "B", 200 - a)])
            return pd.DataFrame(rows, columns=["t", "sub", "v"])
        ts = origin + pd.Timedelta(minutes=200)
        past, full = audit.detectors(frame(200)), audit.detectors(frame(220))
        self.assertEqual(past(ts), full(ts))
        self.assertEqual(past(ts)[5], {"A"}); self.assertEqual(past(ts)[15], set())
        self.assertEqual(past(origin - pd.Timedelta(minutes=1)), {15: set(), 5: set()})
        self.assertEqual(past(ts + pd.Timedelta(hours=1)), {15: set(), 5: set()})


if __name__ == "__main__":
    unittest.main()
