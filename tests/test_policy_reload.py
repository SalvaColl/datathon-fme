"""T-043: a failed policy update keeps the last valid policy (variant, arms and active weights)."""
import contextlib, io, json, sys, tempfile, unittest
from pathlib import Path
import numpy as np

from recsys import lfm, live
from tests.test_lfm import COEF, build

GOOD = {"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_a.json"}, {"tag": "x1", "file": "lfm_coef_a.json", "w": {"known": {"islast": 3.0}}}]}


def coef(**known_w):
    c = json.loads(json.dumps(COEF)); c["known"]["w"].update(known_w); return c


class PolicyReloadTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.DATA, lfm.HERE, live.LF, dict(live.POLICY), dict(live.POLICY_REJECTED), dict(live.LABELS))
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        live.DATA = d / "data"; live.DATA.mkdir(); lfm.HERE = d
        live.LF, _ = build()
        live.POLICY.update(variant="v1", qrank_arms=[], lfm_arms=[], state_window=None); live.POLICY_REJECTED.update(sig=None, n=0)
        (d / "lfm_coef_a.json").write_text(json.dumps(coef(islast=1.5)))
        self.log = io.StringIO()
        self.write(GOOD); self.read()
        self.assertEqual(live.POLICY["variant"], "lfm"); self.assertEqual([a["tag"] for a in live.POLICY["lfm_arms"]], ["r3", "x1"])
        self.before = self.active()

    def tearDown(self):
        live.DATA, lfm.HERE, live.LF = self.saved[:3]
        for cur, old in ((live.POLICY, self.saved[3]), (live.POLICY_REJECTED, self.saved[4]), (live.LABELS, self.saved[5])): cur.clear(); cur.update(old)
        self.tmp.cleanup()

    def write(self, conf): (live.DATA / "policy.json").write_text(conf if isinstance(conf, str) else json.dumps(conf))
    def read(self):
        with contextlib.redirect_stdout(self.log): live.read_policy()
    def events(self, name): return [e for e in (json.loads(l) for l in self.log.getvalue().splitlines() if l.startswith("{")) if e.get("event") == name]
    def active(self):
        """Everything a request reads: routing keys, the arm weights (by value AND by identity) and the arm switches."""
        return (json.dumps(live.POLICY, sort_keys=True), {t: id(v) for t, v in live.LF.alt.items()},
                {t: (w["known"].tolist(), w["new"].tolist(), dict(b)) for t, (w, b) in live.LF.alt.items()}, dict(live.LF.alt_lq), dict(live.LF.alt_x))

    def rejected(self, conf, reason=None):
        n = len(self.events("policy_rejected")); kept = {"variant": live.POLICY["variant"], "lfm_arms": [a["tag"] for a in live.POLICY["lfm_arms"]]}
        self.write(conf); self.read(); self.read()                           # two cycles: the same bad file is logged once
        self.assertEqual(self.active(), self.before)
        ev = self.events("policy_rejected"); self.assertEqual(len(ev), n + 1)
        self.assertEqual(ev[-1]["kept"], kept)
        if reason: self.assertIn(reason, ev[-1]["reason"])

    def test_missing_weight_file(self):
        self.rejected({"variant": "qrank", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_a.json"}, {"tag": "r9", "file": "lfm_coef_missing.json"}]}, "FileNotFoundError")

    def test_missing_policy_file_keeps_everything(self):
        (live.DATA / "policy.json").unlink(); self.read()
        self.assertEqual(self.active(), self.before); self.assertEqual(self.events("policy_rejected"), [])

    def test_incomplete_json(self):
        self.rejected(json.dumps({"variant": "v1", "lfm_arms": []})[:-9])                    # policy.json cut while being written
        (lfm.HERE / "lfm_coef_cut.json").write_text(json.dumps(coef())[:40])                 # weight file cut
        self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "c1", "file": "lfm_coef_cut.json"}]}, "lfm weights")
        (lfm.HERE / "lfm_coef_half.json").write_text(json.dumps({"known": COEF["known"]}))   # weight file without the new-user model
        self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "h1", "file": "lfm_coef_half.json"}]}, "KeyError")
        (lfm.HERE / "lfm_coef_nob.json").write_text(json.dumps({s: {"w": COEF[s]["w"]} for s in COEF}))
        self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "n1", "file": "lfm_coef_nob.json"}]}, "KeyError")

    def test_non_finite_coefficients(self):
        for name, c in (("nan", coef(islast=float("nan"))), ("inf", coef(chn=float("inf")))):
            (lfm.HERE / f"lfm_coef_{name}.json").write_text(json.dumps(c))                   # json writes NaN / Infinity and reads them back
            self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_a.json"}, {"tag": "bad", "file": f"lfm_coef_{name}.json"}]}, "non-finite")
        c = coef(); c["new"]["b"] = float("-inf"); (lfm.HERE / "lfm_coef_b.json").write_text(json.dumps(c))
        self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "bad", "file": "lfm_coef_b.json"}]}, "non-finite")
        c = coef(islast="1.5x"); (lfm.HERE / "lfm_coef_s.json").write_text(json.dumps(c))
        self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "bad", "file": "lfm_coef_s.json"}]})
        self.rejected('{"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_a.json", "w": {"known": {"islast": NaN}}}]}', "invalid lfm_arms")

    def test_invalid_configuration(self):
        arms = GOOD["lfm_arms"]
        for conf, reason in (([1, 2], "not an object"),
                             ({"variant": "lfmm", "lfm_arms": arms}, "unknown variant"),
                             ({"variant": "qrank", "lfm_arms": arms + [{"tag": "r3"}]}, "invalid lfm_arms"),            # duplicate tag
                             ({"variant": "qrank", "lfm_arms": {"tag": "r3"}}, "invalid lfm_arms"),                     # not a list
                             ({"variant": "qrank", "lfm_arms": [{"tag": "a", "w": {"known": {"nope": 1}}}]}, "invalid lfm_arms"),
                             ({"variant": "qrank", "lfm_arms": [{"tag": "cn1", "file": "lfm_coef_a.json", "lq": "cold_new"}, {"tag": "r3"}]}, "invalid lfm_arms"),   # cold_new without its control
                             ({"variant": "qrank", "lfm_arms": arms, "qrank_arms": [{"tag": "one"}]}, "invalid qrank_arms"),
                             ({"variant": "qrank", "lfm_arms": arms, "state_window": {"day_start": "tomorrow"}}, "invalid state_window")):
            self.rejected(conf, reason)

    def test_recovery_with_a_correct_configuration(self):
        self.rejected({"variant": "qrank", "lfm_arms": [{"tag": "r9", "file": "lfm_coef_missing.json"}]})
        (lfm.HERE / "lfm_coef_b.json").write_text(json.dumps(coef(islast=4.0)))
        self.write({"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_a.json"}, {"tag": "y2", "file": "lfm_coef_b.json"}], "state_window": {"day_start": "2026-11-15 00:00:00"}})
        self.read()
        self.assertEqual([a["tag"] for a in live.POLICY["lfm_arms"]], ["r3", "y2"]); self.assertEqual(set(live.LF.alt), {"r3", "y2"})
        self.assertEqual(live.LF.alt["y2"][0]["known"][lfm.FEATS.index("islast")], 4.0)
        self.assertEqual(live.POLICY["state_window"], {"day_start": "2026-11-15 00:00:00", "carts": "persistent"}); self.assertEqual(live.LF.day_start, "2026-11-15 00:00:00")
        self.assertEqual(len(self.events("policy_recovered")), 1)
        # the same file that was rejected is accepted once its weight file exists
        self.rejected_then_fixed()

    def rejected_then_fixed(self):
        self.before = self.active()
        self.rejected({"variant": "lfm", "lfm_arms": [{"tag": "z1", "file": "lfm_coef_late.json"}]})
        (lfm.HERE / "lfm_coef_late.json").write_text(json.dumps(coef(islast=2.5))); self.read()
        self.assertEqual([a["tag"] for a in live.POLICY["lfm_arms"]], ["z1"]); self.assertEqual(set(live.LF.alt), {"z1"})

    def test_documented_rollbacks_still_work(self):
        self.write({"variant": "lfm"}); self.read()                                           # removing lfm_arms = committed weights
        self.assertEqual(live.POLICY["lfm_arms"], []); self.assertEqual(live.LF.alt, {}); self.assertEqual(live.POLICY["variant"], "lfm")
        self.write(GOOD); self.read(); self.write({"variant": "qrank", "lfm_arms": []}); self.read()
        self.assertEqual((live.POLICY["variant"], live.POLICY["lfm_arms"]), ("qrank", []))
        self.assertEqual(self.events("policy_rejected"), [])

    def test_accepted_arms_serve_and_unchanged_file_does_nothing(self):
        alt = live.LF.alt; self.read(); self.assertIs(live.LF.alt, alt)                       # same policy.json: nothing rebuilt
        live.AP = type("AP", (), {"aff": build()[1]})(); self.addCleanup(setattr, live, "AP", None)
        reqs = [dict(request_id=str(k), user_id=f"u{k}", rv=["A30"], page="product", is_new_user=False) for k in range(40)]
        ver = {}; out = live.lfm_slates(reqs, set(), ver)
        self.assertEqual(len(out), 40); self.assertEqual(set(ver.values()), {"v3-lfm-r3-k", "v3-lfm-x1-k"})


if __name__ == "__main__":
    unittest.main()
