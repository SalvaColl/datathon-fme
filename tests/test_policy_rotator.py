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

    # ---- T-044: absolute deadline, block size, served-policy check, phase balance ----
    def test_until_must_be_absolute(self):
        self.assertEqual(pr.parse_utc("2026-11-15 07:00"), 1794726000)
        for bad in ("07:00", "2026-11-15", "mañana", ""):
            with self.assertRaises(ValueError): pr.parse_utc(bad)

    def test_refuses_to_start_after_the_deadline_or_the_freeze(self):
        until, freeze = pr.parse_utc("2026-11-15 07:00"), pr.parse_utc("2026-11-15 08:00")
        now = pr.parse_utc("2026-11-14 23:41")
        self.assertEqual(pr.plan_window(now, until, freeze, 900), (pr.parse_utc("2026-11-14 23:45"), until))
        with self.assertRaisesRegex(ValueError, "ya ha pasado"): pr.plan_window(until + 60, until, freeze, 900)      # relaunch at 08:01 CET
        with self.assertRaisesRegex(ValueError, "congelado"): pr.plan_window(now, freeze + 300, freeze, 900)         # end after the freeze
        with self.assertRaisesRegex(ValueError, "congelado"): pr.plan_window(freeze + 60, freeze, freeze, 900)
        with self.assertRaisesRegex(ValueError, "no cabe"): pr.plan_window(until - 600, until, freeze, 900)
        with self.assertRaisesRegex(ValueError, "--start"): pr.plan_window(now, until, freeze, 900, start=now - 3600)
        with self.assertRaisesRegex(ValueError, "--start"): pr.plan_window(now, until, freeze, 900, start=pr.parse_utc("2026-11-15 00:00") + 60)
        self.assertEqual(pr.plan_window(now, until, freeze, 900, start=pr.parse_utc("2026-11-15 00:00"))[0], pr.parse_utc("2026-11-15 00:00"))

    def test_block_size_must_be_positive(self):
        until, freeze, now = pr.parse_utc("2026-11-15 07:00"), pr.parse_utc("2026-11-15 08:00"), pr.parse_utc("2026-11-14 23:41")
        for bad in (0, -900, 450, -300):
            with self.assertRaises(ValueError): pr.plan_window(now, until, freeze, bad)
        for bad in (0, -900):
            with self.assertRaises(ValueError): pr.schedule(0, 4, bad, 10 ** 6)          # used to loop forever / never advance
        for bm in ("0", "-15", "7"):
            with self.assertRaises(SystemExit): pr.main(["check", "--block-min", bm, "--until", "2026-11-15 07:00"], now=now)
        with self.assertRaises(SystemExit): pr.main(["check", "--until", "07:00"], now=now)
        with self.assertRaises(SystemExit): pr.main(["check", "--until", "2026-11-15 07:00"], now=pr.parse_utc("2026-11-15 07:01"))
        with self.assertRaises(SystemExit): pr.main(["check", "--until", "2026-11-16 07:00"], now=now)
        self.assertEqual(pr.main(["check", "--until", "2026-11-15 07:00"], now=now), 0)

    def test_expected_labels_follow_the_writers_rule(self):
        conf = {"variant": "lfm", "lfm_arms": [{"tag": "CX3"}]}
        self.assertEqual(pr.expected_labels(conf), {"v3-lfm-cx3-k", "v3-lfm-cx3-n", "v3-lfm-cx3-kh", "v3-lfm-cx3-nh"})
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pr.read_labels(d), (None, {}))
            (Path(d) / "labels.json").write_text(json.dumps({"salt": "s", "map": {"v3-lfm-cx3-k": "zz"}}))
            lab = pr.read_labels(d); pub = pr.expected_labels(conf, lab)
            live.LABELS.update(salt="s", map={"v3-lfm-cx3-k": "zz"}, seen={})
            try: self.assertEqual(pub, {live.public_label("v3-lfm-cx3" + s) for s in pr.SUFFIXES})
            finally: live.LABELS.update(salt=None, map={}, seen={})
            self.assertIn("zz", pub); self.assertEqual(len(pub), 4)

    def test_block_is_verified_only_when_the_planned_arm_served_it(self):
        exp = {"a-k", "a-n"}; t0 = 1794700800
        def state(vs): return {"teams": [{"team_id": "team_26", "versions": [dict(model_version=m, requests=n, last=t0 + l) for m, n, l in vs]}]}
        good = pr.verify_block(t0, 900, "a", exp, 90.0, fetch=lambda *x: state([("a-k", 800, 899), ("a-n", 150, 898), ("guard", 30, 700), ("b-k", 20, 6)]))
        self.assertTrue(good["verified"]); self.assertEqual((good["planned"], good["other"], good["share"]), (950, 50, 95.0))
        bad = pr.verify_block(t0, 900, "a", exp, 90.0, fetch=lambda *x: state([("b-k", 900, 899), ("a-k", 10, 3)]))       # the writer kept the old arm
        self.assertFalse(bad["verified"]); self.assertLess(bad["share"], 5)
        self.assertFalse(pr.verify_block(t0, 900, "a", exp, 90.0, fetch=lambda *x: {"teams": []})["verified"])
        def boom(*x): raise OSError("net")
        self.assertEqual(pr.verify_block(t0, 900, "a", exp, 90.0, fetch=boom)["error"], "OSError")
        self.assertTrue(pr.loaded(t0 + 120, t0, exp, fetch=lambda *x: state([("a-k", 5, 100)])))
        self.assertFalse(pr.loaded(t0 + 120, t0, exp, fetch=lambda *x: state([("a-k", 5, 4), ("b-k", 90, 110)])))
        self.assertIsNone(pr.loaded(t0 + 120, t0, exp, fetch=boom))

    def test_phase_balance(self):
        start = pr.parse_utc("2026-11-15 00:00"); bursts = pr.parse_bursts(None)
        self.assertTrue(pr.in_burst(pr.parse_utc("2026-11-15 01:30"), 900, bursts)); self.assertTrue(pr.in_burst(pr.parse_utc("2026-11-15 02:00"), 900, bursts))
        self.assertFalse(pr.in_burst(pr.parse_utc("2026-11-15 02:15"), 900, bursts)); self.assertFalse(pr.in_burst(pr.parse_utc("2026-11-15 01:15"), 900, bursts))
        self.assertEqual(pr.parse_bursts("none"), []); self.assertEqual(pr.parse_bursts("23:30,01:30"), [1410, 90])
        names = ["r3", "cx3", "r3", "og1"]                       # tonight's hourly plan: each challenger always in the same quarter
        per = pr.balance(pr.schedule(start, 4, 900, start + 7 * 3600), names, 900, bursts, "r3")
        self.assertEqual(per["cx3"]["quarters"], [0, 7, 0, 0]); self.assertEqual(per["og1"]["quarters"], [0, 0, 0, 7])
        self.assertEqual(per["cx3"]["burst"], 0); self.assertGreater(per["og1"]["burst"], 0)
        self.assertLess(per["cx3"]["bias_all"], 0)              # cx3 is never in a burst and one of its r3 neighbours often is
        names = ["r3", "a", "r3", "b", "r3", "c", "a", "r3", "b", "r3", "c", "r3"]
        per = pr.balance(pr.schedule(start, 12, 900, start + 6 * 3600), names, 900, bursts, "r3")
        self.assertTrue(all(sum(1 for q in per[n]["quarters"] if q) >= 2 for n in "abc"))


if __name__ == "__main__":
    unittest.main()
