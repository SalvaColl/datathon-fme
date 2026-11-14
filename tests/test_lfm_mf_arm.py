"""T-039: the collaborative feature as a targeted arm ({"mf": "known_pages"}): returning shoppers on product/category
pages with recent views, nothing else. Synthetic, no network, deterministic."""
import json
import unittest
from pathlib import Path

import numpy as np

from recsys import lfm, live
from tests.test_lfm import COEF, HIST, FakeAff, catalog

ROOT = Path(lfm.__file__).parent
MFW = 2.0
CTL = {"tag": "r3", "w": {"known": {"ucat": 1.5}}}
ARMS = [CTL, {"tag": "r6t", "w": {"known": {"ucat": 1.5, "mf": MFW}}, "mf": "known_pages"}]
USERS = [f"u{k}" for k in range(300)]


def build(unavail=(), factors=True):
    cat = catalog(); aff = FakeAff(list(cat.index))
    lf = lfm.LiveFit(COEF, HIST)
    lf.set_catalog(cat, set(unavail), aff, {p: -0.01 * int(p[1:]) for p in cat.index}, None)
    if factors:                                   # every test shopper likes B30-B39, which the base weights rank last
        items = [f"B{k:02d}" for k in range(40)] + ["GONE"]
        Q = np.zeros((len(items), 2)); Q[30:40, 0] = 1.0; Q[:30, 1] = 0.2
        lf.mf_items, lf.mf_Q, lf.mf_P, lf.mf_u = items, Q, np.tile([3.0, 0.0], (len(USERS), 1)), {u: k for k, u in enumerate(USERS)}
        lf._mf_catalog(lf.snap)
    return lf, aff


def req(user="u9", rv=("A30",), page="product", new=False):
    return dict(user_id=user, rv=list(rv), page=page, is_new_user=new)


def scores(lf, aff, r, model=None):
    return lf.scores(r, lf.user_state(r["user_id"]), aff, model)[1]


def slate(lf, aff, r, model=None, exclude=()):
    return lf.slate(r, lf.user_state(r["user_id"]), aff, model=model, exclude=exclude)


TARGET = [req(), req(page="category"), req(user="u1", rv=("B05", "A30"))]
OUTSIDE = [req(new=True), req(new=True, page="category"), req(rv=(), page="home"), req(rv=(), page="home", new=True), req(rv=(), page="product"),
           req(rv=("A30",), page="home"), req(rv=("A30",), page="cart"), req(user="stranger"), req(user="stranger", new=True)]


class TargetRuleTests(unittest.TestCase):
    def test_rule(self):
        t = lfm.mf_target
        self.assertTrue(t("known_pages", False, "product", ["A30"])); self.assertTrue(t("known_pages", False, "category", ["A30"]))
        for new, page, rv in ((True, "product", ["A30"]), (False, "home", ["A30"]), (False, "product", []), (False, "cart", ["A30"]), (True, "home", []), (None, "home", [])):
            self.assertFalse(t("known_pages", new, page, rv))
        self.assertFalse(t(None, False, "product", ["A30"])); self.assertFalse(t("everyone", False, "product", ["A30"]))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.champ, self.aff0 = build(factors=False); self.champ.set_arms([CTL])          # the champion as it runs today: no factors at all
        self.lf, self.aff = build(); self.lf.set_arms(live.clean_lfm_arms(ARMS))

    def test_control_is_exactly_the_champion_everywhere(self):
        for r in TARGET + OUTSIDE:
            self.assertTrue(np.array_equal(scores(self.champ, self.aff0, r, "r3"), scores(self.lf, self.aff, r, "r3")), r)
            self.assertEqual(slate(self.champ, self.aff0, r, "r3"), slate(self.lf, self.aff, r, "r3"))

    def test_outside_the_cohort_the_arm_gives_identical_scores_and_ordered_slates(self):
        for r in OUTSIDE:
            self.assertTrue(np.array_equal(scores(self.lf, self.aff, r, "r3"), scores(self.lf, self.aff, r, "r6t")), r)
            self.assertEqual(slate(self.lf, self.aff, r, "r3"), slate(self.lf, self.aff, r, "r6t"), r)
            self.assertEqual(slate(self.champ, self.aff0, r, "r3"), slate(self.lf, self.aff, r, "r6t"), r)

    def test_inside_the_cohort_only_the_mf_term_moves(self):
        k = lfm.FEATS.index("mf")
        for r in TARGET:
            a, b = scores(self.lf, self.aff, r, "r3"), scores(self.lf, self.aff, r, "r6t")
            st = self.lf.user_state(r["user_id"])
            X = lfm.features(self.lf.snap, self.aff.affinity_all(r["user_id"], r["rv"]), r["rv"], r["page"], st[2], st[1], bought_today=st[3], mix=st[4], mfu=st[5])
            live_rows = np.isfinite(a)
            self.assertTrue(np.array_equal(np.isfinite(a), np.isfinite(b)))               # same dead / bought / out-of-stock products
            self.assertTrue(np.allclose(b[live_rows] - a[live_rows], MFW * X[live_rows, k], atol=1e-9))
            self.assertNotEqual(slate(self.lf, self.aff, r, "r3"), slate(self.lf, self.aff, r, "r6t"))

    def test_an_arm_without_the_key_keeps_the_untargeted_behaviour(self):
        lf, aff = build(); lf.set_arms([{"tag": "r6", "w": {"known": {"mf": MFW}}}]); self.assertEqual(lf.alt_mf, {})
        r = req(rv=(), page="home")
        self.assertFalse(np.array_equal(scores(lf, aff, r, "r6"), scores(self.lf, self.aff, r, "r3")))

    def test_policy_weight_is_the_committed_r6_weight_and_equals_the_r6_file(self):
        r6 = json.loads((ROOT / "lfm_coef_r6.json").read_text()); r3 = json.loads((ROOT / "lfm_coef_r3.json").read_text())
        for name in ("policy.r6_target_r3.json", "policy.r6_target_cn1.json"):
            raw = json.loads((ROOT / name).read_text())["lfm_arms"]
            self.assertEqual(live.clean_lfm_arms(raw), raw, name); self.assertEqual(len(raw), 2)
            ctl, ch = raw
            self.assertEqual(ch["w"], {"known": {"mf": r6["known"]["w"]["mf"]}}); self.assertEqual(ch["mf"], "known_pages")
            self.assertEqual({k: v for k, v in ch.items() if k not in ("tag", "w", "mf")}, {k: v for k, v in ctl.items() if k != "tag"})
        self.assertEqual(r6["meta"]["mf_fit"]["w"], 0.0627); self.assertEqual(r6["new"]["w"]["mf"], 0.0)
        self.assertEqual({f: w for f, w in r6["known"]["w"].items() if f != "mf"}, r3["known"]["w"])
        lf, _ = build(); lf.set_arms(json.loads((ROOT / "policy.r6_target_r3.json").read_text())["lfm_arms"]); lf.add_model("file", r6)
        self.assertTrue(np.array_equal(lf.alt["r6t"][0]["known"], lf.alt["file"][0]["known"]))
        self.assertTrue(np.array_equal(lf.alt["r6t"][0]["new"], lf.alt["r3"][0]["new"]))


class CleanTests(unittest.TestCase):
    def test_needs_a_control_that_differs_only_in_the_mf_weight(self):
        self.assertEqual(live.clean_lfm_arms(ARMS), ARMS)
        bad = [
            [ARMS[1]],                                                                    # alone
            [{"tag": "r3"}, ARMS[1]],                                                     # control with other overrides
            [CTL, dict(ARMS[1], file="lfm_coef_r5.json")],                                # other base file
            [CTL, dict(ARMS[1], home={})],                                                # other home
            [CTL, dict(ARMS[1], lq="cold_new")],                                          # other quality mode than its control
            [CTL, dict(ARMS[1], w={"known": {"ucat": 1.5}})],                             # no mf weight: nothing to test
            [CTL, dict(ARMS[1], w={"known": {"ucat": 1.5, "mf": MFW}, "new": {"mf": 0.1}})],   # mf for new shoppers
            [CTL, dict(ARMS[1], mf="everyone")],                                          # unknown mode
            [dict(CTL, lq="cold"), ARMS[1]],                                              # a treated arm is not its control
        ]
        for arms in bad: self.assertEqual(live.clean_lfm_arms(arms), [], arms)

    def test_challenger_on_a_promoted_cold_new_champion(self):
        arms = [{"tag": "cn1", "w": {"known": {"ucat": 1.5}}, "lq": "cold_new"}, dict(ARMS[1], lq="cold_new")]
        self.assertEqual(live.clean_lfm_arms(arms), arms)
        self.assertEqual(live.clean_lfm_arms([CTL, arms[0]]), [CTL, arms[0]])            # the cold_new trial form still works
        self.assertEqual(live.clean_lfm_arms([{"tag": "r3"}, arms[0]]), [])              # ...and still needs its own control

    def test_lists_without_the_key_are_unchanged(self):
        for arms in ([{"tag": "r3", "file": "lfm_coef_r3.json"}], [{"tag": "r3"}, {"tag": "r6", "file": "lfm_coef_r6.json"}],
                     [{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "cn1", "file": "lfm_coef_r3.json", "lq": "cold_new"}]):
            self.assertEqual(live.clean_lfm_arms(arms), arms)


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.saved = (live.POLICY["variant"], live.LF, live.AP, live.POLICY["lfm_arms"], dict(live.LABELS))
        self.lf, self.aff = build(); live.LF = self.lf; live.AP = type("AP", (), {"aff": self.aff})(); live.POLICY["variant"] = "lfm"
        self.use(ARMS)
    def tearDown(self):
        live.POLICY["variant"], live.LF, live.AP, live.POLICY["lfm_arms"] = self.saved[:4]
        live.LABELS.clear(); live.LABELS.update(self.saved[4])
    def use(self, raw):
        arms = live.clean_lfm_arms(raw); self.assertEqual(arms, raw); self.lf.set_arms(arms); live.POLICY["lfm_arms"] = arms
    def reqs(self, n=80, **kw):
        return [dict({"request_id": str(k), "user_id": f"u{k}", "rv": ["A30"], "page": "product", "is_new_user": False}, **kw) for k in range(n)]

    def test_untouched_traffic_keeps_the_control_label_and_the_control_output(self):
        for kw in (dict(is_new_user=True), dict(rv=[], page="home"), dict(is_new_user=True, rv=[], page="home"), dict(rv=[]), dict(page="home"), dict(is_new_user=True, page="category")):
            rq = self.reqs(**kw)
            self.use(ARMS); ver = {}; two = live.lfm_slates(rq, set(), ver)
            self.assertEqual(len(two), 80); self.assertEqual({v.split("-")[2] for v in ver.values()}, {"r3"}, kw)    # no r6t-n / -kh / -nh labels exist
            self.use([CTL]); ver1 = {}; one = live.lfm_slates(rq, set(), ver1)
            self.assertEqual((one, ver1), (two, ver), kw)                                 # identical ordered slates and labels without the challenger

    def test_target_cohort_is_split_by_user_stable_and_only_the_challenger_half_changes(self):
        rq = self.reqs(); ver = {}; out = live.lfm_slates(rq, set(), ver); ver2 = {}; out2 = live.lfm_slates(rq, set(), ver2)
        self.assertEqual((out, ver), (out2, ver2))
        self.assertEqual(set(ver.values()), {"v3-lfm-r3-k", "v3-lfm-r6t-k"})
        n = sum(v == "v3-lfm-r6t-k" for v in ver.values()); self.assertTrue(25 <= n <= 55, n)
        self.use([CTL]); base = live.lfm_slates(rq, set(), {}); self.use(ARMS)
        for k, r in enumerate(rq):
            arm = live.lfm_arm(r["user_id"])["tag"]; self.assertEqual(ver[k], f"v3-lfm-{arm}-k")
            self.assertEqual(out[k] == base[k], arm == "r3"); self.assertEqual(len(set(out[k])), 10)
        cat = self.reqs(page="category"); ver = {}; live.lfm_slates(cat, set(), ver)
        self.assertEqual(set(ver.values()), {"v3-lfm-r3-k", "v3-lfm-r6t-k"})

    def test_on_a_cold_new_champion_new_shoppers_keep_its_policy_and_label(self):
        champ = {"tag": "cn1", "w": {"known": {"ucat": 1.5}}, "lq": "cold_new"}
        both = [champ, dict(ARMS[1], lq="cold_new")]
        for kw, suffix in ((dict(is_new_user=True), "n"), (dict(is_new_user=True, rv=[], page="home"), "nh"), (dict(rv=[], page="home"), "kh")):
            rq = self.reqs(**kw)
            self.use([champ]); v1 = {}; one = live.lfm_slates(rq, set(), v1)
            self.use(both); v2 = {}; two = live.lfm_slates(rq, set(), v2)
            self.assertEqual((one, v1), (two, v2)); self.assertEqual(set(v2.values()), {"v3-lfm-cn1-" + suffix})
        ver = {}; live.lfm_slates(self.reqs(), set(), ver); self.assertEqual(set(ver.values()), {"v3-lfm-cn1-k", "v3-lfm-r6t-k"})

    def test_labels_stay_opaque(self):
        live.LABELS.update(salt="s", map={"v3-lfm-r3-k": "ma32a4"}, seen={})
        self.assertEqual(live.public_label("v3-lfm-r3-k"), "ma32a4")
        new = live.public_label("v3-lfm-r6t-k")
        self.assertRegex(new, r"^m[0-9a-f]{5}$"); self.assertNotEqual(new, "ma32a4"); self.assertNotIn("r6", new); self.assertNotIn("mf", new)


class RobustnessTests(unittest.TestCase):
    def challenger(self, lf):
        lf.set_arms(live.clean_lfm_arms(ARMS)); return lf

    def test_ten_unique_active_products_and_purchase_exclusions(self):
        lf, aff = build(unavail={"B38"}); self.challenger(lf)
        lf.add("u9", "B37", p=1)                                    # bought today
        r = req("u1")                                               # HIST: u1 bought B06 in the 60-day history
        for rr in (req(), r, req(page="category")):
            s = slate(lf, aff, rr, "r6t"); self.assertEqual(len(s), 10); self.assertEqual(len(set(s)), 10)
            self.assertNotIn("B38", s); self.assertTrue(all(p in lf.snap.row for p in s))
        self.assertNotIn("B37", slate(lf, aff, req(), "r6t")); self.assertIn("B37", slate(lf, aff, req("u8"), "r6t"))
        self.assertNotIn("B06", slate(lf, aff, r, "r6t"))
        self.assertNotIn("B36", slate(lf, aff, req(), "r6t", exclude={"B36"}))

    def test_unknown_user_and_unknown_products(self):
        lf, aff = build(); self.challenger(lf)
        r = req("stranger"); self.assertIsNone(lf.user_mf("stranger"))
        self.assertEqual(slate(lf, aff, r, "r6t"), slate(lf, aff, r, "r3"))
        r = req(rv=("ZZ1", "A30", "??")); s = slate(lf, aff, r, "r6t"); self.assertEqual(len(set(s)), 10)
        self.assertEqual(slate(lf, aff, req(rv=("ZZ1",)), "r6t") is None, slate(lf, aff, req(rv=("ZZ1",)), "r3") is None)
        k = lfm.FEATS.index("mf"); st = lf.user_state("u9")
        X = lfm.features(lf.snap, aff.affinity_all("u9"), ["A30"], "product", {}, set(), mfu=st[5])
        self.assertTrue(np.all(X[[lf.snap.row[p] for p in lf.snap.ids if p.startswith("A")], k] == 0))      # products the factorisation never saw

    def test_missing_or_broken_factor_file_makes_the_arm_equal_to_its_control(self):
        saved = lfm.MF
        try:
            for path in (ROOT / "no_such_file.npz", Path(__file__)):                     # absent, and present but not a factor file
                lfm.MF = path; lf, aff = build(factors=False); self.challenger(lf)
                self.assertIsNone(lf.snap.mf)
                for r in TARGET + OUTSIDE: self.assertEqual(slate(lf, aff, r, "r6t"), slate(lf, aff, r, "r3"), r)
        finally: lfm.MF = saved

    def test_stock_shock_still_returns_ten(self):
        lf, aff = build(); self.challenger(lf)
        best = slate(lf, aff, req(), "r6t"); order = np.argsort(-scores(lf, aff, req(), "r6t"))
        gone = {lf.snap.ids[k] for k in order[:25]}                 # 25 of its 30 best vanish after the snapshot (T-037)
        s = slate(lf, aff, req(), "r6t", exclude=gone)
        self.assertEqual(len(set(s)), 10); self.assertFalse(gone & set(s)); self.assertNotEqual(s, best)

    def test_non_finite_factors_never_reach_a_slate(self):
        for bad in (np.nan, np.inf):
            lf, aff = build(); self.challenger(lf); lf.mf_P[lf.mf_u["u9"]] = bad
            s = slate(lf, aff, req(), "r6t"); self.assertEqual(s, slate(lf, aff, req(), "r3")); self.assertEqual(len(set(s)), 10)


if __name__ == "__main__":
    unittest.main()
