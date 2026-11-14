"""night_lab contra un leaderboard simulado: media móvil de 60 min, recalculada cada minuto, que lee los MISMOS
ficheros policy.json / d130.json que el laboratorio escribe. Sin red y sin RawTree."""
import json, math, tempfile, unittest
from pathlib import Path

from recsys import night_lab as nl

TRUTH = {  # brazo -> (lift sobre baseline, on_time)
    "v1": (0.25, 95.0), "qrank": (0.60, 95.0), "qrank+home": (0.70, 95.0), "slow": (0.60, 40.0), "weak": (0.05, 95.0)}


class Sim:
    """Reloj falso + leaderboard. Cada minuto que pasa anota qué brazo está activo según los ficheros en disco."""
    def __init__(self, data, drift=True, mode="practice"):
        self.data, self.t, self.drift, self.mode, self.minutes, self.fetches = Path(data), 1_000_000 * 60.0, drift, mode, {}, 0

    def arm(self):
        try: v = json.loads((self.data / "policy.json").read_text())["variant"]
        except FileNotFoundError: v = "v1"
        try: m = json.loads((self.data / "d130.json").read_text())["mode"]
        except FileNotFoundError: m = "off"
        return v if m == "off" else f"{v}+{m}"

    def now(self): return self.t

    def sleep(self, dt):
        end = self.t + dt
        while math.floor(self.t / 60) < math.floor(end / 60):
            k = math.floor(self.t / 60); self.minutes[k] = self.arm(); self.t = (k + 1) * 60.0
        self.t = end

    def fetch(self):
        self.fetches += 1
        k = math.floor(self.t / 60); rows = []
        for j in range(k - 60, k):
            lift, ot = TRUTH[self.minutes.get(j, "v1")]
            base = 0.70 + (0.05 * math.sin(j / 40) if self.drift else 0)
            rows.append((base + lift, base, base + 1.30, ot))
        conv, base, ref, ot = (sum(r[i] for r in rows) / 60 for i in range(4))
        team = dict(team_id="team_26", requests=10800, conversion=conv, cold_conversion=conv + 0.5, on_time=ot, revenue_per_request=0.4, model_version="sim")
        row = lambda c: dict(team_id="x", requests=10800, conversion=c, cold_conversion=c + 0.4, on_time=100, revenue_per_request=0.1, model_version="")
        return dict(mode=self.mode, updated_at=k * 60.0, next_update=(k + 1) * 60.0, window=[k * 60.0 - 3600, k * 60.0],
                    final_start=self.t + 10 * 86400, teams=[team], baseline=row(base), reference=row(ref))


def lab(tmp, arms, hours, sim=None, **kw):
    data = Path(tmp); sim = sim or Sim(data)
    arms = [nl.parse_arm(a) for a in arms]
    kw.setdefault("block_s", 65 * 60)
    L = nl.Lab(arms, data, data / "night_lab", nl.parse_arm("v1"), deadline=sim.t + hours * 3600, fetch=sim.fetch, now=sim.now,
               sleep=sim.sleep, log=lambda *_: None, **kw)
    return L, sim


class NightLabTests(unittest.TestCase):
    def test_direct_reading_recovers_each_arm_and_original_policy_is_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "policy.json").write_text('{"variant": "v1", "note": "antes"}')
            L, sim = lab(tmp, ["v1", "qrank", "qrank+home"], hours=6.6)
            L.run()
            blocks, arms = nl.analyze(L.snaps, L.segments, L.settle_s)
            self.assertEqual([b["arm"] for b in blocks], ["v1", "qrank", "qrank+home"] * 2)
            self.assertTrue(all(b["status"] == "done" and b["direct"]["n"] >= 1 for b in blocks))
            for r in arms:
                self.assertEqual(r["blocks"], 2)
                self.assertAlmostEqual(r["lift"], TRUTH[r["arm"]][0], places=6)      # exacto pese a la deriva del baseline
                self.assertAlmostEqual(r["norm"], TRUTH[r["arm"]][0] / 1.30, places=6)
            self.assertEqual(nl.best_arm(arms, "v1"), "qrank+home")
            self.assertEqual((Path(tmp) / "policy.json").read_text(), '{"variant": "v1", "note": "antes"}')
            self.assertFalse((Path(tmp) / "d130.json").exists())                      # no existía antes: no queda
            self.assertIn("| `qrank+home` | 2 |", (Path(tmp) / "night_lab" / "report.md").read_text())

    def test_only_policy_files_and_own_logs_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            L, _ = lab(tmp, ["v1", "qrank"], hours=2.3)
            L.run()
            files = sorted(p.relative_to(tmp).as_posix() for p in Path(tmp).rglob("*") if p.is_file())
            self.assertEqual(files, ["night_lab/report.md", "night_lab/segments.jsonl", "night_lab/snapshots.jsonl"])

    def test_d130_file_untouched_when_no_arm_uses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "d130.json").write_text('{"mode": "nodead"}')
            sim = Sim(tmp); sim.arm = lambda: json.loads((Path(tmp) / "policy.json").read_text())["variant"] if (Path(tmp) / "policy.json").exists() else "v1"
            L, _ = lab(tmp, ["v1", "qrank"], hours=1.2, sim=sim)
            L.run()
            self.assertEqual((Path(tmp) / "d130.json").read_text(), '{"mode": "nodead"}')

    def test_guard_reverts_to_best_arm_and_retires_the_culprit(self):
        for bad, word in (("slow", "on_time"), ("weak", "lift")):
            with tempfile.TemporaryDirectory() as tmp:
                L, sim = lab(tmp, ["v1", bad, "qrank"], hours=5.6)
                L.run()
                kinds = [(s["arm"], s["kind"], s["status"]) for s in L.segments]
                self.assertEqual(kinds[:3], [("v1", "block", "done"), (bad, "block", "aborted"), ("v1", "revert", "done")])
                self.assertIn(word, L.segments[1]["reason"])
                self.assertLess(L.segments[1]["t1"] - L.segments[1]["t0"], 16 * 60)   # 10 min de gracia + 3 snapshots
                self.assertEqual([k[0] for k in kinds[3:]], ["qrank", "v1", "qrank"][:len(kinds) - 3])  # el retirado no vuelve a salir
                self.assertEqual(sum(1 for a in sim.minutes.values() if a == bad), round((L.segments[1]["t1"] - L.segments[1]["t0"]) / 60))

    def test_guard_leaves_a_better_arm_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            L, _ = lab(tmp, ["v1", "qrank", "qrank+home"], hours=3.3)
            L.run()
            self.assertEqual([s["status"] for s in L.segments], ["done"] * 3)

    def test_dry_run_writes_no_policy_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            L, _ = lab(tmp, ["qrank", "qrank+home"], hours=2.3, dry=True)
            L.run()
            self.assertFalse((Path(tmp) / "policy.json").exists()); self.assertFalse((Path(tmp) / "d130.json").exists())
            self.assertTrue(all(s["dry"] for s in L.segments))

    def test_stops_and_restores_when_the_final_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Sim(tmp, mode="final")
            L, _ = lab(tmp, ["qrank"], hours=5, sim=sim)
            L.run()
            self.assertEqual(L.segments, []); self.assertFalse((Path(tmp) / "policy.json").exists())

    def test_finish_best_leaves_the_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            L, _ = lab(tmp, ["v1", "qrank+home"], hours=2.3, finish="best")
            L.run()
            self.assertEqual(json.loads((Path(tmp) / "policy.json").read_text()), {"variant": "qrank"})
            self.assertEqual(json.loads((Path(tmp) / "d130.json").read_text()), {"mode": "home"})

    def test_fit_estimates_short_blocks_when_traffic_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            L, _ = lab(tmp, ["v1", "qrank"], hours=4.1, sim=Sim(tmp, drift=False), block_s=30 * 60, guard_consec=10 ** 6)
            L.run()
            blocks, arms = nl.analyze(L.snaps, L.segments, L.settle_s)
            self.assertTrue(all(b["direct"] is None for b in blocks))                  # sin lectura directa con 30 min
            for r in arms: self.assertAlmostEqual(r["fit"]["lift"], TRUTH[r["arm"]][0], delta=0.03)

    def test_plan_is_checked_against_the_writer_on_disk(self):
        live = Path(nl.__file__).with_name("live.py")
        arms = [nl.parse_arm(a) for a in ("v1", "qrank", "ab_qrank")]
        self.assertEqual(nl.check_plan(arms, live), [])
        problems = nl.check_plan([nl.parse_arm("no_such_variant"), nl.parse_arm("v1+home")], live)
        self.assertEqual(len(problems), 1 + (0 if "d130.install" in live.read_text() else 1))
        with self.assertRaises(ValueError): nl.parse_arm("qrank+bogus")

    def test_module_never_touches_rawtree(self):
        src = Path(nl.__file__).read_text()
        for word in ("api.rawtree.com", "RAWTREE_API_KEY", "/v1/tables", "import requests", "import live"):
            self.assertNotIn(word, src.split('"""', 2)[2])


if __name__ == "__main__":
    unittest.main()
