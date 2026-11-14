import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recsys"))
import live, serving


class UrgentAgeTests(unittest.TestCase):
    def test_default_override_and_clamp(self):
        self.assertEqual(live.urgent_age(None), 2.2); self.assertEqual(live.urgent_age("2.0"), 2.0)
        self.assertEqual(live.urgent_age("9"), 2.4); self.assertEqual(live.urgent_age("0.1"), 1.5)
        self.assertEqual(live.urgent_age("abc"), 2.2); self.assertLess(live.URGENT_AGE, 2.5)

    def test_a_two_second_old_request_gets_the_model_not_the_guard(self):
        clock = [1000.0]; sent = []
        req = {"request_id": "r", "ts": "1970-01-01 00:16:38.000"}      # 998.0 -> 2.0 s old
        age = serving.age(req, clock[0])
        self.assertAlmostEqual(age, 2.0, places=3)
        for ua, expect in ((1.8, "guard"), (live.urgent_age(None), "model")):
            sent.clear()
            serving.serve([req], lambda rs: [{"who": "model"}], lambda rs: [{"who": "guard"}],
                          lambda rs, ans: sent.append(ans[0]["who"]), now=lambda: clock[0], urgent_age=ua)
            self.assertEqual(sent, [expect])


if __name__ == "__main__":
    unittest.main()
