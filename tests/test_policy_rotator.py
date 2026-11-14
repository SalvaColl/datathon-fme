import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recsys"))
import policy_rotator as pr
import live


class RotatorTests(unittest.TestCase):
    def test_plan_files_load_and_the_writer_accepts_each_whole(self):
        plan = pr.load_plan(["r3", "cx3", "r3", "og1"])
        self.assertEqual([n for n, _ in plan], ["r3", "cx3", "r3", "og1"])
        for _, conf in plan:
            self.assertEqual(live.clean_lfm_arms(conf["lfm_arms"]), conf["lfm_arms"])
        with self.assertRaises(ValueError): pr.load_plan(["nope"])

    def test_boundaries_and_schedule(self):
        self.assertEqual(pr.next_boundary(1200), 1500); self.assertEqual(pr.next_boundary(1201), 1500)
        blocks = pr.schedule(1500, 4, 1200, 1500 + 5 * 1200 + 100)
        self.assertEqual([k for _, k in blocks], [0, 1, 2, 3, 0]); self.assertEqual(blocks[1][0], 2700)
        self.assertTrue(all(t % 300 == 0 for t, _ in blocks))

    def test_write_and_log(self):
        with tempfile.TemporaryDirectory() as d:
            pr.write_policy({"variant": "lfm", "lfm_arms": [{"tag": "r3"}]}, d); pr.log_change(d, "x", now=0)
            self.assertEqual(json.loads((Path(d) / "policy.json").read_text())["variant"], "lfm")
            self.assertIn("1970-01-01 00:00:00 UTC x", (Path(d) / "policy_changes.log").read_text())

    def test_guard(self):
        state = {"teams": [{"team_id": "team_26", "on_time": 98.0, "conversion": 2.0}], "baseline": {"conversion": 0.5}}
        self.assertIn("on_time", pr.guard_trips(pr.guard_reading(state), 99.0))
        state["teams"][0]["on_time"] = 99.9; self.assertIsNone(pr.guard_trips(pr.guard_reading(state), 99.0))
        state["teams"][0]["conversion"] = 0.4; self.assertIn("baseline", pr.guard_trips(pr.guard_reading(state), 99.0))
        self.assertIsNone(pr.guard_trips(pr.guard_reading({"teams": []}), 99.0))


if __name__ == "__main__":
    unittest.main()
