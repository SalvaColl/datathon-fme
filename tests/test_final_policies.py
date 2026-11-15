"""T-064: every policy file of the final (candidates and the documented rollback chain) goes through the REAL
validation path of the writer (live.read_policy -> check_policy -> clean_lfm_arms -> lfm_arm_weights -> publish_policy)
and then serves the four cohorts, so a file that the writer would silently turn into `v3-lfm-r1-*` fails here."""
import contextlib, io, json, math, tempfile, unittest
from pathlib import Path
import numpy as np

from recsys import lfm, live
from tests.test_lfm import FakeAff, catalog, COEF, HIST

HERE = Path(lfm.HERE)
# file -> (tag, weights the file must give a non-zero value on pages {segment: features}, same for home, newcap)
POLICIES = {
    "policy.rot_uf1.json": ("uf1", {"known": ("hot", "orate", "mf", "ucat"), "new": ("orate", "hot", "ucat")}, {"known": ("newph", "orate"), "new": ("newph", "orate")},
                            {"new": 2, "home_known": 2, "home_new": 2}),
    "policy.rot_uf1n.json": ("uf1n", {"known": ("newp", "hot", "orate"), "new": ("orate", "hot")}, {"known": ("newph",), "new": ("newph",)},
                             {"known": 2, "new": 2, "home_known": 2, "home_new": 2}),
    "policy.rot_uf2.json": ("uf2", {"known": ("hot", "orate", "mf", "ucat"), "new": ("orate", "hot", "ucat", "prv")}, {"known": ("newph", "orate"), "new": ("newph", "orate")},
                            {"home_known": 2, "home_new": 2}),
    "policy.rot_uf2n.json": ("uf2n", {"known": ("newp", "hot", "orate"), "new": ("orate", "hot", "prv")}, {"known": ("newph",), "new": ("newph",)},
                             {"known": 4, "home_known": 2, "home_new": 2}),
    "policy.rot_uf0.json": ("uf0", {"known": ("hot", "orate", "mf"), "new": ("orate", "hot")}, {"known": ("newph",), "new": ("newph",)},
                            {"new": 2, "home_known": 2, "home_new": 2}),
    "policy.rot_u3k.json": ("u3k", {"known": ("hot", "orate", "mf"), "new": ("orate", "hot")}, {"known": ("orate", "opop"), "new": ("orate", "opop")}, None),
    "policy.unified.json": ("u1", {"known": ("hot", "orate", "mf"), "new": ("orate", "hot")}, {"known": ("orate", "opop"), "new": ("orate", "opop")}, None),
    "policy.rot_cs2r.json": ("cs2r", {"known": ("chn", "cl", "lq"), "new": ("lq",)}, {"known": ("lq",), "new": ("lq",)}, None),
    "policy.unified_rollback.json": ("r3", {"known": ("lq", "ucat"), "new": ("lq", "ucat")}, None, None),
}
CHAIN = ("policy.rot_uf1.json", "policy.rot_uf0.json", "policy.rot_u3k.json", "policy.unified.json", "policy.rot_cs2r.json", "policy.unified_rollback.json")
K = lfm.FEATS.index


def raw_weights(spec):
    """Every weight key written in a policy arm (pages and home)."""
    out = []
    for block in (spec, spec.get("home") or {}):
        for seg, w in (block.get("w") or {}).items(): out += [(seg, f, v) for f, v in w.items()]
    return out


class FinalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.DATA, live.LF, live.AP, dict(live.POLICY), dict(live.POLICY_REJECTED), dict(live.LABELS))
        self.tmp = tempfile.TemporaryDirectory(); live.DATA = Path(self.tmp.name)
        self.cat = catalog(); self.aff = FakeAff(list(self.cat.index))
        lf = lfm.LiveFit(COEF, HIST)                                          # weight files are read from the real recsys/ folder
        oq = {p: (400.0, 20.0 + int(p[1:])) for p in self.cat.index}
        lf.set_catalog(self.cat, {"A31"}, self.aff, {p: -0.01 * int(p[1:]) for p in self.cat.index}, None, newp={"A38", "A39", "B38", "B39"},
                       hot={"A32", "A33"}, oq=oq, oq_hist=set(list(self.cat.index)[:60]))
        live.LF = lf; live.AP = type("AP", (), {"aff": self.aff})()
        live.POLICY.update(variant="v1", qrank_arms=[], lfm_arms=[], state_window=None); live.POLICY_REJECTED.update(sig=None, n=0)
        live.LABELS.update(salt=None, map={}, seen={})
        self.log = io.StringIO()

    def tearDown(self):
        live.DATA, live.LF, live.AP = self.saved[:3]
        for cur, old in ((live.POLICY, self.saved[3]), (live.POLICY_REJECTED, self.saved[4]), (live.LABELS, self.saved[5])): cur.clear(); cur.update(old)
        self.tmp.cleanup()

    def install(self, text):
        """Exactly what the operator does: copy the file to data/policy.json; the refresher calls read_policy()."""
        (live.DATA / "policy.json").write_text(text)
        with contextlib.redirect_stdout(self.log): live.read_policy()
        return [json.loads(l) for l in self.log.getvalue().splitlines() if l.startswith("{")]

    def labels(self):
        """model_version of the four cohorts, as predict() would label them (lfm_slates is the code that does it)."""
        reqs = [dict(request_id=f"{new}{k}{j}", user_id=f"u{j}", rv=rv, page=page, is_new_user=new)
                for new in (False, True) for k, (rv, page) in enumerate(((["A30"], "product"), ([], "home"))) for j in range(6)]
        ver = {}; out = live.lfm_slates(reqs, {"A31"}, ver)
        self.assertEqual(len(out), len(reqs))
        for s in out.values(): self.assertEqual(len(set(s)), 10); self.assertNotIn("A31", s)
        return set(ver.values())

    def check(self, text, tag, pages=None, home=None, cap=None):
        conf = json.loads(text); raw = conf["lfm_arms"]
        self.assertEqual(conf["variant"], "lfm")
        ev = self.install(text)
        self.assertEqual([e for e in ev if e.get("event") == "policy_rejected"], [], tag)
        self.assertEqual(live.POLICY["variant"], "lfm")
        self.assertEqual([a["tag"] for a in live.POLICY["lfm_arms"]], [tag])              # [] = silently back to r1 weights
        self.assertEqual(live.POLICY["lfm_arms"], live.clean_lfm_arms(raw))
        for seg, f, v in raw_weights(raw[0]):                                              # every weight key is a feature of the writer
            self.assertIn(f, lfm.FEATS, (tag, seg, f)); self.assertTrue(math.isfinite(v) and abs(v) <= 20, (tag, seg, f, v))
        for a in (raw[0], raw[0].get("home") or {}):                                       # coefficient files: present, complete, finite
            if a.get("file"):
                c = json.loads((HERE / a["file"]).read_text())
                for seg in ("known", "new"):
                    self.assertTrue(math.isfinite(float(c[seg]["b"])))
                    self.assertTrue(set(c[seg]["w"]) <= set(lfm.FEATS), (a["file"], set(c[seg]["w"]) - set(lfm.FEATS)))
                    self.assertTrue(all(math.isfinite(float(x)) for x in c[seg]["w"].values()))
        self.assertIn(tag, live.LF.alt); self.assertEqual("home" in raw[0], tag + "@home" in live.LF.alt)
        for name, (w, b) in live.LF.alt.items():
            for seg in ("known", "new"):
                self.assertTrue(np.all(np.isfinite(w[seg])) and math.isfinite(b[seg]), name); self.assertEqual(len(w[seg]), len(lfm.FEATS))
        for block, name in ((pages, tag), (home, tag + "@home")):
            for seg, feats in (block or {}).items():
                for f in feats: self.assertNotEqual(live.LF.alt[name][0][seg][K(f)], 0.0, (name, seg, f))
        self.assertEqual(live.LF.alt_cap.get(tag), cap)
        self.assertEqual(live.LF.alt_lq, {}); self.assertEqual(live.LF.alt_x, {})          # no cold-quality trial, no exploration slot
        self.assertFalse(any(k.endswith(lfm.RC) for k in live.LF.alt))
        self.assertEqual(self.labels(), {f"v3-lfm-{tag}-{c}" for c in ("k", "n", "kh", "nh")})

    def test_every_final_policy_is_accepted_and_serves_its_own_label(self):
        for f, (tag, pages, home, cap) in POLICIES.items():
            with self.subTest(policy=f):
                live.POLICY.update(variant="v1", lfm_arms=[]); live.LF.set_arms([])
                self.check((HERE / f).read_text(), tag, pages, home, cap)

    def test_rollback_chain_installs_step_by_step_on_a_running_writer(self):
        """uf1 -> uf0 -> u3k -> u1 -> cs2r -> r3, each over the previous one without a restart; nothing is rejected."""
        for f in CHAIN:
            ev = self.install((HERE / f).read_text())
            self.assertEqual([e for e in ev if e.get("event") == "policy_rejected"], [], f)
            tag = POLICIES[f][0]
            self.assertEqual([a["tag"] for a in live.POLICY["lfm_arms"]], [tag])
            self.assertEqual(set(live.LF.alt) - {tag + "@home"}, {tag})                    # the previous arm's weights are gone
            self.assertEqual(live.LF.alt_cap.get(tag), POLICIES[f][3])
            self.assertEqual(self.labels(), {f"v3-lfm-{tag}-{c}" for c in ("k", "n", "kh", "nh")})

    def test_last_rollback_is_plain_r3(self):
        """policy.unified_rollback.json = {"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_r3.json"}]}: the weights
        of the file and nothing else. It still ranks by `lq` (the 60-day quality), has no organic quality, no trends, no
        launched-product weight and no cap, so it asks the refresher for nothing that a new regime could break."""
        text = (HERE / "policy.unified_rollback.json").read_text()
        self.assertEqual(json.loads(text), {"variant": "lfm", "lfm_arms": [{"tag": "r3", "file": "lfm_coef_r3.json"}]})
        self.install(text)
        c = json.loads((HERE / "lfm_coef_r3.json").read_text()); w, b = live.LF.alt["r3"]
        for seg in ("known", "new"):
            np.testing.assert_allclose(w[seg], [c[seg]["w"].get(f, 0.0) for f in lfm.FEATS]); self.assertEqual(b[seg], c[seg]["b"])
            self.assertGreater(w[seg][K("lq")], 0.0); self.assertLess(w[seg][K("p40")], 0.0)
            for f in ("newp", "newph", "hot", "hotc", "orate", "opop", "prv", "hcb", "hcc", "mf", "cv"): self.assertEqual(w[seg][K(f)], 0.0, f)
        self.assertNotIn("r3@home", live.LF.alt)                                           # home = the same file, `home` weight included
        self.assertFalse(live.LF.wants_hot() or live.LF.wants_oq() or live.LF.wants_prv())
        self.assertEqual(live.LF.alt_cap, {})

    def test_price_flags_are_live_for_every_policy(self):
        """T-042 regression: p40 / cheap come from the catalogue prices of the snapshot (not all zero)."""
        S = live.LF.snap
        self.assertTrue(0 < S.p40.sum() < S.n); self.assertTrue(0 < S.cheap.sum() < S.n)

    def test_a_broken_copy_is_rejected_and_the_previous_policy_keeps_serving(self):
        self.install((HERE / "policy.rot_uf1.json").read_text())
        bad = json.loads((HERE / "policy.rot_uf1.json").read_text()); bad["lfm_arms"][0]["w"]["new"]["not_a_feature"] = 1.0
        ev = self.install(json.dumps(bad))
        self.assertEqual(len([e for e in ev if e.get("event") == "policy_rejected"]), 1)
        self.assertEqual(self.labels(), {f"v3-lfm-uf1-{c}" for c in ("k", "n", "kh", "nh")})
        ev = self.install((HERE / "policy.rot_uf1.json").read_text()[:-20])                # truncated copy (network mount)
        self.assertEqual(len([e for e in ev if e.get("event") == "policy_rejected"]), 2)
        self.assertEqual([a["tag"] for a in live.POLICY["lfm_arms"]], ["uf1"])

    def test_uf2_is_uf1_plus_prv_without_the_new_page_cap(self):
        """uf2 on main (ee2955c) = uf1 + prv 0.8 for new shoppers on pages, and no launched cap on new-shopper pages
        (the cap also counted the shopper's own launched products, bug-audit thread). Nothing else differs."""
        uf1 = json.loads((HERE / "policy.rot_uf1.json").read_text())["lfm_arms"][0]
        uf2 = json.loads((HERE / "policy.rot_uf2.json").read_text())["lfm_arms"][0]
        uf1["tag"] = "uf2"; uf1["w"]["new"]["prv"] = 0.8; del uf1["newcap"]["new"]
        self.assertEqual(uf2, uf1)
        self.check((HERE / "policy.rot_uf2.json").read_text(), *POLICIES["policy.rot_uf2.json"])
        self.assertTrue(live.LF.wants_prv())                                               # the refresher must feed earlier requests
        self.assertEqual(live.LF.alt["uf2"][0]["known"][K("prv")], 0.0); self.assertEqual(live.LF.alt["uf2@home"][0]["new"][K("prv")], 0.0)

if __name__ == "__main__":
    unittest.main()
