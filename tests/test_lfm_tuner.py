"""lfm_tuner: rondas contra un leaderboard simulado. Sin red, sin RawTree, sin writer."""
import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "recsys"))
sys.argv = [sys.argv[0], "--dry-run"]
import lfm, lfm_tuner as T, live

R3 = json.loads((ROOT / "recsys" / "lfm_coef_r3.json").read_text())
CHAMP = {"tag": "r3", "file": "lfm_coef_r3.json", "w": {"new": {"cl": 1.5}}, "home": {"w": {"known": {"hcart": 1.5}}}}


def eff(arm, seg, home=False):
    """Pesos efectivos de un brazo, como los resuelve el writer (LiveFit.set_arms)."""
    sp = arm["home"] if home and "home" in arm else arm
    base = json.loads((ROOT / "recsys" / (sp.get("file") or "lfm_coef.json")).read_text())[seg]["w"]
    return {**base, **((sp.get("w") or {}).get(seg) or {})}


class FakeBoard:
    """Conversión 'oculta' de cada brazo y cohorte = función de sus pesos efectivos; solo responde a ventanas exactas."""
    def __init__(self, data, target, n=900, labels=None, base=2.0):
        self.data, self.target, self.n, self.labels, self.t, self.base = Path(data), target, n, labels, 1_000_000.0, base
        self.asked, self.hide, self.shift = [], set(), 0
    def now(self): return self.t
    def sleep(self, s): self.t += s
    def conv(self, arm, seg, home=False):
        w = eff(arm, seg, home)
        return self.base - sum(abs(w.get(f, 0.0) - v) for f, v in self.target.get((seg, home), {}).items())
    def fetch(self, start, end=None):
        self.asked.append((start, end))
        pol = json.loads((self.data / "policy.json").read_text()); rows = []
        for a in pol.get("lfm_arms", []):
            for (seg, suf, home) in T.COHORTS.values():
                if (a["tag"], suf) in self.hide: continue
                rows.append(dict(model_version=T.public_label(f"v3-lfm-{a['tag']}{suf}", self.labels), requests=self.n // (5 if home else 1),
                                 conversion=self.conv(a, seg, home), last=(end or self.t) - 5))
        return dict(mode="practice", final_start=self.t + 1e6, window=[start + self.shift, end if end else self.t], teams=[dict(team_id=T.TEAM, versions=rows)],
                    reference=dict(team_id="reference", requests=4500, conversion=1.77))


class Case(unittest.TestCase):
    policy = {"variant": "lfm", "aff": True, "lfm_arms": [CHAMP]}
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)
        (self.d / "policy.json").write_text(json.dumps(self.policy))
    def tearDown(self): self.tmp.cleanup()
    def pol(self): return json.loads((self.d / "policy.json").read_text())
    def tuner(self, board, cohort="known-pages", **kw):
        return T.Tuner(self.d, cohort, fetch_fn=board.fetch, now=board.now, sleep=board.sleep, log=lambda *a: None, **kw)
    def rounds(self): return [json.loads(l) for l in (self.d / "lfm_tuner" / "rounds.jsonl").read_text().splitlines()]


class ChampionTests(Case):
    def test_reference_is_the_champion_untouched_and_every_arm_keeps_its_home_and_other_segment(self):
        t = self.tuner(FakeBoard(self.d, {}))
        for r in range(4):
            t.round = r; arms, info = t.arms_for_round()
            self.assertEqual(arms[0], CHAMP)                                         # referencia fija: mismo brazo, misma etiqueta, primera
            self.assertEqual(live.clean_lfm_arms(arms), arms)                        # el writer los acepta tal cual
            self.assertEqual(sorted(a["tag"][0] for a in arms[1:]), ["m", "p"])
            for a in arms:
                self.assertEqual(eff(a, "known", home=True), eff(CHAMP, "known", home=True))      # home idéntico (hcart 1.5 incluido)
                self.assertEqual(eff(a, "new", home=True), eff(CHAMP, "new", home=True))
                self.assertEqual(eff(a, "new"), eff(CHAMP, "new"))                                # el otro segmento no se toca
                self.assertEqual(a.get("file"), "lfm_coef_r3.json")
            moved = {a["tag"][0]: eff(a, "known") for a in arms[1:]}
            diff = {f for w in moved.values() for f in w if w[f] != eff(CHAMP, "known")[f]}
            self.assertEqual(diff, {info["feature"]})                                # un solo peso, de la cohorte
        self.assertEqual(info["feature"], "ucat")

    def test_champion_without_home_gets_its_main_weights_pinned_on_home(self):
        champ = {"tag": "r3", "file": "lfm_coef_r3.json", "w": {"known": {"islast": 2.0}}}
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": [champ]}))
        t = self.tuner(FakeBoard(self.d, {})); arms, _ = t.arms_for_round()
        self.assertEqual(arms[0], champ)
        for a in arms[1:]:
            self.assertNotEqual(eff(a, "known"), eff(champ, "known"))
            self.assertEqual(eff(a, "known", home=True), eff(champ, "known"))        # en home sirve lo mismo que el campeón
            self.assertEqual(a["home"], {"file": "lfm_coef_r3.json", "w": {"known": {"islast": 2.0}}})

    def test_no_arms_means_committed_weights_and_several_arms_need_an_explicit_champion(self):
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm"}))
        t = self.tuner(FakeBoard(self.d, {})); arms, _ = t.arms_for_round()
        self.assertEqual(arms[0], {"tag": "ref"}); self.assertEqual(arms[1]["home"], {}); self.assertEqual(live.clean_lfm_arms(arms), arms)
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": [CHAMP, {"tag": "r5", "file": "lfm_coef_r5.json"}]}))
        with self.assertRaises(SystemExit): self.tuner(FakeBoard(self.d, {}))
        t = self.tuner(FakeBoard(self.d, {}), champion_tag="r5", fresh=True)
        self.assertEqual(t.champion, {"tag": "r5", "file": "lfm_coef_r5.json"})
        with self.assertRaises(SystemExit): self.tuner(FakeBoard(self.d, {}), champion_tag="zz")

    def test_unknown_arm_keys_travel_with_the_champion(self):
        champ = {**CHAMP, "lq": "cold"}
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": [champ]}))
        t = self.tuner(FakeBoard(self.d, {})); arms, _ = t.arms_for_round()
        self.assertTrue(all(a.get("lq") == "cold" for a in arms)); self.assertEqual(t.final_arms("restore"), [champ])

    def test_plans_start_with_category_mix_and_skip_features_that_are_zero_off_home(self):
        self.assertEqual(T.PLAN["known-pages"][:2], [("ucat", 1.5), ("usub", 0.7)])
        for c in ("known-pages", "new-pages"): self.assertFalse({"hcart", "home"} & {f for f, _ in T.PLAN[c]})
        for c in T.PLAN: self.assertTrue({f for f, _ in T.PLAN[c]} <= set(lfm.FEATS))

    def test_home_cohort_moves_only_the_home_weights(self):
        t = self.tuner(FakeBoard(self.d, {}), cohort="known-home"); arms, info = t.arms_for_round()
        self.assertEqual(info["feature"], "hcart"); self.assertEqual(info["value"], 1.5)       # parte del home del campeón
        for a in arms[1:]:
            self.assertEqual(eff(a, "known"), eff(CHAMP, "known")); self.assertEqual(eff(a, "new", home=True), eff(CHAMP, "new", home=True))
            self.assertIn(eff(a, "known", home=True)["hcart"], (0.5, 2.5))


class RoundTests(Case):
    def test_search_then_confirmation_then_promotion_and_policy_keys_survive(self):
        target = {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 3.0}}
        b = FakeBoard(self.d, target); t = self.tuner(b)
        t.run(rounds=1, finish="best")
        self.assertEqual(t.best, {}); self.assertEqual(t.pending["f"], "ucat")        # ganó una búsqueda: todavía NO es el mejor
        self.assertEqual(self.pol()["lfm_arms"], [CHAMP])                             # sin confirmar, policy vuelve a como estaba
        t.run(rounds=1, finish="best")
        r = self.rounds(); self.assertEqual([x["outcome"] for x in r], ["candidate", "confirmed"])
        self.assertEqual([a["tag"][0] for a in r[1]["arms"]], ["r", "x"])             # confirmación: referencia + candidato, ventana nueva
        self.assertGreater(r[1]["window"][0], r[0]["window"][1])
        self.assertAlmostEqual(t.best["ucat"], R3["known"]["w"]["ucat"] + 1.5, places=4)
        pol = self.pol(); self.assertEqual((pol["variant"], pol["aff"]), ("lfm", True))
        best = pol["lfm_arms"]; self.assertEqual([a["tag"] for a in best], ["best"]); self.assertEqual(live.clean_lfm_arms(best), best)
        self.assertEqual(eff(best[0], "known", home=True), eff(CHAMP, "known", home=True)); self.assertEqual(eff(best[0], "new"), eff(CHAMP, "new"))
        self.assertAlmostEqual(eff(best[0], "known")["ucat"], t.best["ucat"])

    def test_after_a_promotion_the_reference_stays_and_a_control_arm_appears(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 3.0}}); t = self.tuner(b)
        t.run(rounds=3, finish="restore")
        last = self.rounds()[-1]; self.assertEqual([a["tag"][0] for a in last["arms"]][0], "r")
        self.assertEqual(sorted(a["tag"][0] for a in last["arms"][1:]), ["c", "m", "p"]); self.assertTrue(last["control"].startswith("c"))
        self.assertEqual(self.pol()["lfm_arms"], [CHAMP])                             # restore: exactamente el campeón original

    def test_candidate_that_does_not_repeat_is_dropped(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 3.0}}); t = self.tuner(b)
        t.run(rounds=1, finish="restore"); b.target = {}                              # la ventaja desaparece en la ventana nueva
        t.run(rounds=1, finish="best")
        self.assertEqual(self.rounds()[-1]["outcome"], "not_confirmed"); self.assertEqual((t.best, t.pending, t.pos), ({}, None, 1))
        self.assertEqual(self.pol()["lfm_arms"], [CHAMP])

    def test_home_and_other_segment_results_are_ignored(self):
        """Un peso que solo mejora home o a los nuevos no mueve nada cuando la cohorte son los que vuelven en páginas."""
        b = FakeBoard(self.d, {("known", True): {"ucat": 9.0}, ("new", False): {"ucat": 9.0}}); t = self.tuner(b)
        t.run(rounds=2, finish="best"); self.assertEqual((t.best, t.pending), ({}, None))
        self.assertEqual([x["outcome"] for x in self.rounds()], ["no_change", "no_change"])

    def test_noise_sized_differences_and_few_requests_change_nothing(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 0.1}}); t = self.tuner(b)
        t.run(rounds=2); self.assertEqual((t.best, t.pending), ({}, None))
        b2 = FakeBoard(self.d, {("known", False): {"ucat": 9.0}}, n=100); t2 = self.tuner(b2, out_dir=self.d / "o2")
        t2.run(rounds=2); self.assertEqual((t2.best, t2.pending), ({}, None))


class WindowTests(Case):
    def test_reads_one_exact_common_window_after_warm_up(self):
        b = FakeBoard(self.d, {}); b.t = 1_000_090.0; t = self.tuner(b, window_s=1800, warmup_s=60)
        t.run(rounds=1)
        w = self.rounds()[0]["window"]; self.assertEqual(w, [1_000_200, 1_002_000])    # múltiplos de 300, >= escritura + 60 s
        self.assertEqual(b.asked[-1], (1_000_200, 1_002_000)); self.assertEqual(T.window_after(1_000_140, 60, 900), (1_000_200, 1_001_100))
        self.assertEqual(T.window_after(1_000_141, 60, 900)[0], 1_000_500)
        with self.assertRaises(SystemExit): self.tuner(b, window_s=1000)
        with self.assertRaises(SystemExit): self.tuner(b, window_s=600)

    def test_wrong_window_is_unavailable_never_zero(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": 9.0}}); b.shift = 300; t = self.tuner(b)
        t.run(rounds=1)
        r = self.rounds()[0]; self.assertEqual(r["outcome"], "unavailable"); self.assertTrue(all(v is None for v in r["results"].values()))
        self.assertEqual((t.best, t.pending, t.pos), ({}, None, 0))                   # ni promociona ni pasa al peso siguiente

    def test_missing_rows_are_unavailable(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 3.0}}); t = self.tuner(b)
        b.hide = {("p000", "-k")}; t.run(rounds=1)                                    # falta el brazo que habría ganado
        r = self.rounds()[0]; self.assertIsNone(r["results"]["p000"]); self.assertEqual(r["outcome"], "no_change")
        b.hide = {("r3", "-k")}; t.run(rounds=1)                                      # falta el control: la ronda entera no vale
        self.assertEqual(self.rounds()[-1]["outcome"], "unavailable")
        st = dict(window=[0, 900], teams=[dict(team_id=T.TEAM, versions=[dict(model_version="v3-lfm-a-k", requests=500, conversion=2.0, last=100)])])
        self.assertIsNone(T.read_row(st, "a", "-k", (0, 900)))                        # la fila dejó de servir a mitad de ventana
        st["teams"][0]["versions"][0]["last"] = 880; self.assertEqual(T.read_row(st, "a", "-k", (0, 900)), (500, 2.0))
        self.assertIsNone(T.read_row(st, "a", "-kh", (0, 900))); self.assertIsNone(T.read_row(st, "a", "-k", (300, 1200)))

    def test_stops_after_repeated_unavailable_rounds_and_restores(self):
        b = FakeBoard(self.d, {}); b.shift = 300; t = self.tuner(b)
        t.run(rounds=9); self.assertEqual(len(self.rounds()), 2); self.assertEqual(self.pol()["lfm_arms"], [CHAMP])

    def test_reads_opaque_labels(self):
        labels = {"salt": "s3"}
        b = FakeBoard(self.d, {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 3.0}}, labels=labels)
        (self.d / "labels.json").write_text(json.dumps(labels))
        t = self.tuner(b); t.run(rounds=1); self.assertEqual(self.rounds()[0]["outcome"], "candidate")
        saved = dict(live.LABELS); live.LABELS.update(salt="s3", map={}, seen={})
        try: self.assertEqual(T.public_label("v3-lfm-c000-k", labels), live.public_label("v3-lfm-c000-k"))
        finally: live.LABELS.clear(); live.LABELS.update(saved)

    def test_stops_outside_practice_and_near_the_final(self):
        b = FakeBoard(self.d, {}); f = b.fetch
        b.fetch = lambda s, e=None: {**f(s, e), "final_start": b.t + 3000}
        t = self.tuner(b); t.run(rounds=3); self.assertEqual(t.round, 0); self.assertEqual(self.pol(), self.policy)


class StateTests(Case):
    def test_resume_only_with_the_same_fingerprint(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": R3["known"]["w"]["ucat"] + 3.0}}); t = self.tuner(b)
        t.run(rounds=1, finish="restore")
        t2 = self.tuner(b); self.assertEqual((t2.round, t2.pending, t2.fp), (1, t.pending, t.fp))       # mismo campeón: retoma
        with self.assertRaises(SystemExit): self.tuner(b, cohort="new-pages")                           # otra cohorte
        other = {**CHAMP, "home": {"w": {"known": {"hcart": 0.5}}}}
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": [other]}))
        with self.assertRaises(SystemExit): self.tuner(b)                                               # otro home en el campeón
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_r2.json"}]}))
        with self.assertRaises(SystemExit): self.tuner(b)                                               # otros pesos base
        (self.d / "policy.json").write_text(json.dumps(self.policy))
        with self.assertRaises(SystemExit): self.tuner(b, feats=lfm.FEATS + ["zz"])                     # otra lista de features
        t3 = self.tuner(b, cohort="new-pages", fresh=True); self.assertEqual((t3.round, t3.pending), (0, None))
        self.assertEqual(len(list((self.d / "lfm_tuner").glob("state.*.json"))), 1)                     # el viejo queda archivado

    def test_fingerprint_ignores_the_tag_and_sees_coefficient_contents(self):
        with tempfile.TemporaryDirectory() as c:
            c = Path(c); (c / "lfm_coef.json").write_text(json.dumps(R3))
            a = T.fingerprint({"tag": "a"}, "known-pages", c, lfm.FEATS); self.assertEqual(a, T.fingerprint({"tag": "b"}, "known-pages", c, lfm.FEATS))
            r = json.loads(json.dumps(R3)); r["known"]["w"]["ucat"] += 0.01; (c / "lfm_coef.json").write_text(json.dumps(r))
            self.assertNotEqual(a, T.fingerprint({"tag": "a"}, "known-pages", c, lfm.FEATS))


class OwnerTests(Case):
    def test_dry_never_writes_policy_nor_owner_file(self):
        b = FakeBoard(self.d, {}); t = self.tuner(b, dry=True); t.run(rounds=1)
        self.assertEqual(self.pol(), self.policy); self.assertFalse((self.d / "policy_owner.json").exists())

    def test_owner_file_while_running_and_removed_at_the_end(self):
        b = FakeBoard(self.d, {}); t = self.tuner(b); seen = []
        s = b.sleep
        def sleep(x): seen.append(json.loads((self.d / "policy_owner.json").read_text())["owner"]); s(x)
        t.sleep = sleep; t.run(rounds=1)
        self.assertEqual(set(seen), {"lfm_tuner"}); self.assertFalse((self.d / "policy_owner.json").exists())

    def test_does_not_start_while_someone_else_owns_the_policy(self):
        (self.d / "policy_owner.json").write_text(json.dumps({"owner": "manual: cold_lq"}))
        b = FakeBoard(self.d, {}); t = self.tuner(b); t.run(rounds=2)
        self.assertEqual(self.pol(), self.policy); self.assertFalse((self.d / "lfm_tuner" / "rounds.jsonl").exists())
        self.assertEqual(json.loads((self.d / "policy_owner.json").read_text()), {"owner": "manual: cold_lq"})
        self.assertEqual(len(T.check(self.d, ROOT / "recsys" / "live.py")), 1)

    def test_foreign_change_mid_round_stops_without_overwriting(self):
        b = FakeBoard(self.d, {("known", False): {"ucat": 9.0}}); t = self.tuner(b); s = b.sleep; manual = {}
        def sleep(x):
            if b.t > 1_000_600 and not manual:                # alguien pone a mano una prueba en mitad de la ronda
                manual.update(self.pol()); manual["lfm_arms"] = [CHAMP, {"tag": "cq", "file": "lfm_coef_r3.json"}]; manual["note"] = "cold_lq"
                (self.d / "policy.json").write_text(json.dumps(manual))
            s(x)
        t.sleep = sleep; t.run(rounds=3, finish="best")
        self.assertEqual(self.pol(), manual)                  # ni la ronda siguiente ni el cierre lo pisan
        self.assertEqual((t.best, t.pending, t.round), ({}, None, 0)); self.assertFalse((self.d / "policy_owner.json").exists())

    def test_foreign_change_between_rounds_is_not_overwritten_at_finish(self):
        b = FakeBoard(self.d, {}); t = self.tuner(b)
        (self.d / "policy.json").write_text(json.dumps({"variant": "lfm", "lfm_arms": [CHAMP], "manual": 1}))
        t.run(rounds=1); self.assertEqual(self.pol(), {"variant": "lfm", "lfm_arms": [CHAMP], "manual": 1})

    def test_check_and_until(self):
        self.assertEqual(T.check(self.d, ROOT / "recsys" / "live.py"), [])
        (self.d / "policy.json").write_text(json.dumps({"variant": "qrank"}))
        self.assertEqual(len(T.check(self.d, ROOT / "recsys" / "live.py")), 1)
        self.assertGreater(T.parse_until("00:00", 1_800_000_000), 1_800_000_000)


if __name__ == "__main__":
    unittest.main()
