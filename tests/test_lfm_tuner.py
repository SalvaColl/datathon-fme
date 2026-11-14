"""lfm_tuner: rondas contra un leaderboard simulado. Sin red, sin RawTree, sin writer."""
import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "recsys"))
sys.argv = [sys.argv[0], "--dry-run"]
import lfm, lfm_tuner as T, live

COEF = json.loads((ROOT / "recsys" / "lfm_coef.json").read_text())


class FakeBoard:
    """Conversión 'oculta' = función de los pesos que el brazo lleva en policy.json; el óptimo está lejos de la base."""
    def __init__(self, data, target, n=900, labels=None):
        self.data, self.target, self.n, self.labels, self.t = Path(data), target, n, labels, 1_000_000.0
    def now(self): return self.t
    def sleep(self, s): self.t += s
    def conv(self, seg, w):
        base = COEF[seg]["w"]
        return 2.0 - sum(1.0 * abs(w.get(f, base.get(f, 0.0)) - v) for f, v in self.target[seg].items())
    def fetch(self, start, end=None):
        pol = json.loads((self.data / "policy.json").read_text()); rows = []
        for a in pol.get("lfm_arms", []):
            for seg, (s1, s2) in T.SEGS.items():
                c = self.conv(seg, (a.get("w") or {}).get(seg, {}))
                rows.append(dict(model_version=T.public_label(f"v3-lfm-{a['tag']}{s1}", self.labels), requests=self.n, conversion=c))
                rows.append(dict(model_version=T.public_label(f"v3-lfm-{a['tag']}{s2}", self.labels), requests=self.n // 5, conversion=c))
        return dict(mode="practice", final_start=self.t + 1e6, teams=[dict(team_id=T.TEAM, versions=rows)])


class TunerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "aff": True}))
    def tearDown(self): self.tmp.cleanup()
    def tuner(self, board, **kw):
        return T.Tuner(self.d, COEF, fetch_fn=board.fetch, now=board.now, sleep=board.sleep, log=lambda *a: None, **kw)

    def test_arms_are_valid_for_the_writer_and_rotate(self):
        t = self.tuner(FakeBoard(self.d, {"known": {}, "new": {}}))
        first = []
        for r in range(4):
            t.round = r; arms, moves = t.arms_for_round()
            self.assertEqual(live.clean_lfm_arms(arms), arms)                 # el writer los acepta tal cual
            self.assertEqual(sorted(a["tag"][0] for a in arms), ["c", "m", "p"])
            first.append(arms[0]["tag"][0])
            self.assertNotIn("w", next(a for a in arms if a["tag"][0] == "c"))  # sin cambios aceptados, control = pesos publicados
        self.assertEqual(first, ["c", "p", "m", "c"])

    def test_climbs_to_the_better_weights_and_keeps_other_policy_keys(self):
        target = {"known": {"aff10": COEF["known"]["w"]["aff10"] + 1.5}, "new": {"cl": COEF["new"]["w"]["cl"] - 1.4}}
        b = FakeBoard(self.d, target); t = self.tuner(b)
        t.run(rounds=6, finish="best")
        self.assertAlmostEqual(t.weight("known", "aff10"), target["known"]["aff10"], delta=0.26)
        self.assertGreater(b.conv("known", t.best["known"]), b.conv("known", {}) + 0.4)
        pol = json.loads((self.d / "policy.json").read_text())
        self.assertEqual((pol["variant"], pol["aff"]), ("lfm", True))
        self.assertEqual([a["tag"] for a in pol["lfm_arms"]], ["best"])
        self.assertEqual(live.clean_lfm_arms(pol["lfm_arms"]), pol["lfm_arms"])
        self.assertEqual(len((self.d / "lfm_tuner" / "rounds.jsonl").read_text().splitlines()), 6)
        t2 = self.tuner(b); self.assertEqual((t2.round, t2.best), (6, t.best))    # retoma donde lo dejó

    def test_noise_sized_differences_change_nothing(self):
        b = FakeBoard(self.d, {"known": {"aff10": COEF["known"]["w"]["aff10"] + 0.1}, "new": {}}, n=900)
        t = self.tuner(b); t.run(rounds=3, finish="best")
        self.assertEqual(t.best, {"known": {}, "new": {}})
        self.assertNotIn("lfm_arms", json.loads((self.d / "policy.json").read_text()))

    def test_few_requests_change_nothing(self):
        b = FakeBoard(self.d, {"known": {"aff10": 9.0}, "new": {"cl": 9.0}}, n=100)
        t = self.tuner(b); t.run(rounds=2); self.assertEqual(t.best, {"known": {}, "new": {}})

    def test_reads_opaque_labels(self):
        labels = {"salt": "s3"}
        b = FakeBoard(self.d, {"known": {"aff10": COEF["known"]["w"]["aff10"] + 1.0}, "new": {}}, labels=labels)
        (self.d / "labels.json").write_text(json.dumps(labels))
        t = self.tuner(b); t.run(rounds=2)
        self.assertGreater(t.weight("known", "aff10"), COEF["known"]["w"]["aff10"])
        saved = dict(live.LABELS); live.LABELS.update(salt="s3", map={}, seen={})
        try: self.assertEqual(T.public_label("v3-lfm-c000-k", labels), live.public_label("v3-lfm-c000-k"))
        finally: live.LABELS.clear(); live.LABELS.update(saved)

    def test_stops_outside_practice_and_near_the_final(self):
        b = FakeBoard(self.d, {"known": {}, "new": {}}); f = b.fetch
        b.fetch = lambda s, e=None: {**f(s, e), "final_start": b.t + 3000}
        t = self.tuner(b); t.run(rounds=3); self.assertEqual(t.round, 0)

    def test_dry_never_writes_policy(self):
        b = FakeBoard(self.d, {"known": {}, "new": {}})
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "aff": True, "lfm_arms": []}))
        t = self.tuner(b, dry=True); t.run(rounds=1)
        self.assertEqual(json.loads((self.d / "policy.json").read_text()), {"variant": "lfm", "aff": True, "lfm_arms": []})

    def test_check_and_until(self):
        self.assertEqual(T.check(self.d, ROOT / "recsys" / "live.py"), [])
        (self.d / "policy.json").write_text(json.dumps({"variant": "qrank"}))
        self.assertEqual(len(T.check(self.d, ROOT / "recsys" / "live.py")), 1)
        self.assertGreater(T.parse_until("00:00", 1_800_000_000), 1_800_000_000)


if __name__ == "__main__":
    unittest.main()
