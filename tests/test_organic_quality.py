"""T-047: the product-quality estimate reads ORGANIC counts only; purchases of our own carousel stay in the exclusions and
in the shopper state. Also the known-only quality mode ("lq": "cold_known"). Synthetic, no network, deterministic."""
import collections
import json
import math
import re
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from recsys import cold_lq_arm, fe, lfm, live, live_quality
from tests.test_cold_lq import add_new, prior, world
from tests.test_lfm_cold_arm import ARMS, CASES, DESC_OK, VIEWS, W, build, scores

KNOWN_ARMS = [{"tag": "r3", "w": W}, {"tag": "ck1", "w": W, "lq": "cold_known"}]


class Stream:
    """A fake RawTree: shop.events rows and team feedback rows, answered with the writer's own two queries."""
    def __init__(self, t0):
        self.t0, self.events, self.feedback, self.fail, self.queries = t0, [], [], None, []

    def ts(self, minutes): return str(self.t0 + pd.Timedelta(minutes=minutes))[:23]
    def event(self, minutes, u, i, kind): self.events.append((self.ts(minutes), u, i, kind))
    def buy_from_carousel(self, minutes, u, i): self.feedback.append(dict(u=u, i=i, t=self.ts(minutes)))

    def query(self, sql, timeout=20):
        self.queries.append(sql)
        if ".feedback" in sql:
            if self.fail == "feedback": raise RuntimeError("feedback query failed")
            return [dict(r) for r in self.feedback]                      # every poll returns ALL rows: the dedup must hold
        if self.fail == "events": raise RuntimeError("events query failed")
        lo = re.search(r"> toDateTime64\('([^']+)',3\)", sql).group(1); hi = re.search(r"<= toDateTime64\('([^']+)',3\)", sql)
        agg = collections.OrderedDict()
        for t, u, i, kind in self.events:
            if pd.Timestamp(t) > pd.Timestamp(lo) and (hi is None or pd.Timestamp(t) <= pd.Timestamp(hi.group(1))):
                r = agg.setdefault((u, i), dict(u=u, i=i, v=0, a=0, p=0, mx=t, ta="", tp=""))
                r[{"view": "v", "add_to_cart": "a", "purchase": "p"}[kind]] += 1; r["mx"] = max(r["mx"], t)
        return list(agg.values())


class IngestionTests(unittest.TestCase):
    def setUp(self):
        base, self.q, self.hist = world()
        self.cat = add_new(base, [("new_a", "C0", "S0", 50.0), ("new_b", "C1", "S1", 20.0)])
        self.saved = (live.LIVE, live.fb_seen, live.query, live.LF, live.AP, fe.C, dict(live.state), dict(live.BOUGHT))
        self.s = Stream(pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(minutes=40))
        live.query = self.s.query; live.LF = None; live.AP = None; fe.set_catalog(self.cat)
        self.boot()
        for k in range(50): self.s.event(1 + k / 10, f"v{k}", "new_a", "view")
        for k in range(5): self.s.event(7 + k / 10, f"v{k}", "new_a", "purchase")       # organic: 5 purchases / 50 views
        for k in range(30): self.s.event(8 + k / 10, f"w{k}", "new_b", "view")

    def boot(self):
        """What a writer start does: empty tables, empty feedback memory, the stream read again from EVENTS_SINCE."""
        live.LIVE = live.LiveTables(); live.fb_seen = {}; live.BOUGHT.clear()
        live.state.update(ev_ts=self.s.ts(0)); live.state.pop("fb_full", None)

    def tearDown(self):
        live.LIVE, live.fb_seen, live.query, live.LF, live.AP = self.saved[:5]; fe.set_catalog(self.saved[5])
        live.state.clear(); live.state.update(self.saved[6]); live.BOUGHT.clear(); live.BOUGHT.update(self.saved[7])

    def organic(self, p="new_a"): return tuple(int(x) for x in live.LIVE.organic_item_frame().loc[p])
    def total(self, p="new_a"): return tuple(int(x) for x in live.LIVE.item_frame().loc[p])
    def rate(self, frame, p="new_a"):
        lq = live_quality.LiveQuality(prior=prior)
        lq.update(self.cat.assign(description=""), self.hist, frame, None, known=set(self.q))
        return float(lq.rate[p])

    def test_carousel_purchase_updates_exclusions_and_state_but_not_organic_quality(self):
        live.refresh_events(); before = self.rate(live.organic_frame(live.LIVE))
        self.assertEqual(self.organic(), (50, 0, 5)); self.assertEqual(self.total(), (50, 0, 5))
        for k in range(3): self.s.buy_from_carousel(20, f"c{k}", "new_a")
        live.refresh_events()
        self.assertEqual(self.organic(), (50, 0, 5))                               # organic counts untouched
        self.assertEqual(self.total(), (50, 0, 8))                                 # the all-purchases table still has them
        for k in range(3):
            self.assertIn("new_a", live.BOUGHT[f"c{k}"]); self.assertTrue(live.bought_in(f"c{k}", ["new_a"]))
            self.assertEqual(live.LIVE["uit"].d[(f"c{k}", "new_a")], [0, 0, 1])    # shopper-state features keep the purchase
            self.assertEqual(live.LIVE["utot"].d[f"c{k}"], [0, 1])
        self.assertEqual(self.rate(live.organic_frame(live.LIVE)), before)
        self.assertAlmostEqual(before, (5 + 100 * 0.015) / (50 + 100), places=12)   # (purchases + K prior) / (views + K), K = 100
        self.assertGreater(self.rate(live.LIVE.item_frame()), before)              # what the estimate used to read: inflated

    def test_organic_purchases_update_organic_quality(self):
        live.refresh_events(); before = self.rate(live.organic_frame(live.LIVE))
        self.s.event(21, "v7", "new_a", "view"); self.s.event(22, "v7", "new_a", "purchase"); self.s.event(22, "v8", "new_a", "add_to_cart")
        live.refresh_events()
        self.assertEqual(self.organic(), (51, 1, 6)); self.assertEqual(self.total(), (51, 1, 6))
        self.assertIn("new_a", live.BOUGHT["v7"])
        self.assertAlmostEqual(self.rate(live.organic_frame(live.LIVE)), (6 + 1.5) / (51 + 100), places=12)
        self.assertGreater(self.rate(live.organic_frame(live.LIVE)), before)

    def test_the_two_tables_differ_exactly_by_the_deduplicated_carousel_purchases(self):
        self.s.buy_from_carousel(20, "c0", "new_a"); self.s.buy_from_carousel(21, "c0", "new_a")      # same shopper and product twice
        self.s.buy_from_carousel(21, "c1", "new_a"); self.s.buy_from_carousel(21, "v0", "new_a")      # v0 also bought it organically
        self.s.buy_from_carousel(21, "c2", "new_b"); self.s.buy_from_carousel(21, "c3", "gone")       # not in the catalogue: dropped by both
        live.refresh_events()
        diff = live.LIVE.item_frame().sub(live.LIVE.organic_item_frame(), fill_value=0)
        self.assertEqual(diff.it_p.astype(int).to_dict(), {"new_a": 3, "new_b": 1})
        self.assertTrue((diff[["it_v", "it_a"]] == 0).all().all())
        self.assertNotIn("gone", live.LIVE.organic_item_frame().index)

    def test_duplicate_polling_does_not_double_count(self):
        self.s.buy_from_carousel(20, "c0", "new_a")
        for _ in range(4): live.refresh_events()
        self.assertEqual(self.organic(), (50, 0, 5)); self.assertEqual(self.total(), (50, 0, 6))
        self.assertEqual(self.organic("new_b"), (30, 0, 0))
        self.assertIn("INTERVAL 10 MINUTE", self.s.queries[-1]); self.assertNotIn("INTERVAL 10 MINUTE", self.s.queries[1])   # first read is the full one

    def test_restart_reconstruction_gives_the_same_counts(self):
        self.s.buy_from_carousel(20, "c0", "new_a"); self.s.buy_from_carousel(20, "c1", "new_b")
        live.refresh_events(); live.refresh_events()
        first = (live.LIVE.organic_item_frame().sort_index(), live.LIVE.item_frame().sort_index(), {u: set(b) for u, b in live.BOUGHT.items()})
        self.boot(); live.refresh_events(); live.refresh_events()
        pd.testing.assert_frame_equal(live.LIVE.organic_item_frame().sort_index(), first[0])
        pd.testing.assert_frame_equal(live.LIVE.item_frame().sort_index(), first[1])
        self.assertEqual({u: set(b) for u, b in live.BOUGHT.items()}, first[2])

    def test_failed_refresh_keeps_the_counts_and_recovers_without_double_counting(self):
        self.s.buy_from_carousel(20, "c0", "new_a"); live.refresh_events()
        self.s.event(25, "v9", "new_a", "purchase"); self.s.buy_from_carousel(26, "c5", "new_a")
        self.s.fail = "events"
        with self.assertRaises(RuntimeError): live.refresh_events()                # the refresher logs it and tries again in 20 s
        self.assertEqual(self.organic(), (50, 0, 5)); self.assertEqual(self.total(), (50, 0, 6))
        self.s.fail = "feedback"; live.refresh_events()                            # events arrive, the feedback read fails (caught inside)
        self.assertEqual(self.organic(), (50, 0, 6)); self.assertEqual(self.total(), (50, 0, 7)); self.assertNotIn("c5", live.BOUGHT)
        self.s.fail = None; live.refresh_events(); live.refresh_events()
        self.assertEqual(self.organic(), (50, 0, 6)); self.assertEqual(self.total(), (50, 0, 8)); self.assertIn("new_a", live.BOUGHT["c5"])

    def test_first_feedback_read_failing_is_repeated_in_full(self):
        self.s.buy_from_carousel(-600, "old", "new_a"); self.s.fail = "feedback"; live.refresh_events()
        self.assertNotIn("fb_full", live.state)
        self.s.fail = None; live.refresh_events()
        self.assertNotIn("INTERVAL 10 MINUTE", self.s.queries[-1]); self.assertIn("new_a", live.BOUGHT["old"])
        self.assertEqual(self.organic(), (50, 0, 5))

    def test_d130_style_wrapper_of_add_still_sees_every_purchase(self):
        seen = []; o_add = live.LIVE.add
        live.LIVE.add = lambda u, i, v, a, p: (seen.append((u, i, p)), o_add(u, i, v, a, p))[1]
        self.s.buy_from_carousel(20, "c0", "new_a"); live.refresh_events()
        self.assertIn(("c0", "new_a", 1), seen); self.assertEqual(sum(p for _, i, p in seen if i == "new_a"), 6)
        self.assertEqual(self.organic(), (50, 0, 5))


class ConsumerTests(unittest.TestCase):
    """Every purchases/view estimate of the writer receives the organic table."""
    def setUp(self):
        base, self.q, self.hist = world()
        self.cat = add_new(base, [("new_a", "C0", "S0", 50.0), ("new_b", "C1", "S1", 20.0)])
        self.desc = {"new_a": DESC_OK, "new_b": DESC_OK}
        qs = pd.Series(self.q).reindex(self.cat.index)
        self.lq = np.log(qs.fillna(qs.groupby(self.cat["sub"]).transform("median"))).to_dict()
        self.saved = (live.LF, live.AP, live.CLQ, live.QR, live.BASE, fe.C, dict(live.COLD_LOG))
        fe.set_catalog(self.cat)
        self.T = live.LiveTables()
        for k in range(200): self.T.add(f"v{k}", "new_a", 1, 0, int(k < 10)); self.T.add_organic("new_a", 1, 0, int(k < 10))
        self.organic_only = self.T.organic_item_frame().copy()
        for k in range(8): self.T.add(f"c{k}", "new_a", 0, 0, 1)                     # carousel purchases: add() only

    def tearDown(self):
        live.LF, live.AP, live.CLQ, live.QR, live.BASE = self.saved[:5]; fe.set_catalog(self.saved[5])
        live.COLD_LOG.clear(); live.COLD_LOG.update(self.saved[6])

    def hook(self, arms):
        lf, aff = build(); lf.set_arms(arms)
        live.LF = lf; live.AP = type("AP", (), {"aff": aff, "cold": type("C", (), {"desc": self.desc})()})()
        live.QR = type("QR", (), {"q": self.q, "lq": self.lq})(); live.BASE = {"item": self.hist}
        live.CLQ = cold_lq_arm.Corrector(prior=prior)
        return live.cold_lq_for_arms(self.cat, self.T)

    def test_quality_arm_corrections_ignore_carousel_purchases(self):
        got = self.hook(ARMS)
        ref = cold_lq_arm.Corrector(prior=prior).corrections(self.q, self.lq, self.cat, self.hist, self.organic_only, self.desc, lq0=live.LF.lq0)
        bad = cold_lq_arm.Corrector(prior=prior).corrections(self.q, self.lq, self.cat, self.hist, self.T.item_frame(), self.desc, lq0=live.LF.lq0)
        self.assertEqual(got, ref); self.assertEqual(set(got), {"new_a", "new_b"})
        self.assertGreater(bad["new_a"], got["new_a"]); self.assertEqual(bad["new_b"], got["new_b"])

    def test_inactive_quality_arms_compute_nothing_and_keep_incumbent_outputs(self):
        self.assertIsNone(self.hook([{"tag": "r3", "w": W}]))                        # no arm asks: nothing is computed at all
        champ, aff0 = build(); champ.set_arms([{"tag": "r3", "w": W}])
        lf, aff = build(None); lf.set_arms(ARMS + [KNOWN_ARMS[1]])                    # arms exist, no valid correction this refresh
        self.assertIsNone(lf.snap.lqc)
        for r in CASES:
            base = scores(champ, aff0, r, "r3")
            for tag in ("r3", "c1", "ck1"): self.assertTrue(np.array_equal(base, scores(lf, aff, r, tag)), (tag, r))

    def test_without_carousel_purchases_both_tables_and_all_outputs_are_identical(self):
        T = live.LiveTables()
        for k in range(200): T.add(f"v{k}", "new_a", 1, 0, int(k < 10)); T.add_organic("new_a", 1, 0, int(k < 10))
        pd.testing.assert_frame_equal(T.item_frame(), T.organic_item_frame())
        self.assertIsNone(live.LiveTables().organic_item_frame())
        self.assertEqual(sorted(live.LiveTables()), ["item", "ucat", "uit", "usub", "utot"])       # featurize sees the same five tables

    def test_objects_without_the_organic_table_keep_the_old_call(self):
        old = type("T", (), {"item_frame": lambda s: "frame"})()
        self.assertEqual(live.organic_frame(old), "frame"); self.assertIs(live.organic_frame(self.T).__class__, pd.DataFrame)

    def test_live_quality_hook_and_home_arms_read_the_organic_table(self):
        src = (Path(live.__file__).parent / "live_quality.py").read_text() + (Path(live.__file__).parent / "home_arms.py").read_text()
        self.assertEqual(src.count('"organic_item_frame"'), 2)
        text = Path(live.__file__).read_text()
        code = "\n".join(line for line in text.splitlines() if "T.item_frame()" in line and '"""' not in line and not line.lstrip().startswith(("f = ", "return ")))
        self.assertEqual(code.count("T.item_frame()"), 2, code)                      # make_pools (popularity) and the cold tables' subtraction term
        self.assertEqual(text.count("LIVE.add_organic("), 1)                         # one organic writer: apply_events

    def test_cold_tables_rates_use_organic_counts_and_still_cancel_the_served_table(self):
        from recsys import cold_items
        cs = cold_items.ColdStart.__new__(cold_items.ColdStart)
        cs.base_ids = set(self.q); cs.desc = self.desc; cs.prior_rate = {"new_a": (0.02, 0.05), "new_b": (0.02, 0.05)}; cs.k = 100.0
        cs.prior = None
        base = self.hist.assign(it_a=0.0)[["it_v", "it_a", "it_p"]]
        full = cs.tables(self.cat, base, self.T.item_frame(), self.T.organic_item_frame())["item"]
        old = cs.tables(self.cat, base, self.T.item_frame())["item"]
        ps = cs.pseudo_counts(self.cat, base, self.T.organic_item_frame())
        served = (full + self.T.item_frame().reindex(full.index).fillna(0.0).values).loc["new_a"]        # what featurize adds up
        self.assertAlmostEqual(served.it_p, ps.loc["new_a"].it_p, places=9)
        self.assertAlmostEqual(ps.loc["new_a"].it_p / ps.loc["new_a"].it_v, (10 + 2.0) / (200 + 100), places=9)
        self.assertGreater(old.loc["new_a"].it_p, full.loc["new_a"].it_p)


class ColdKnownTests(unittest.TestCase):
    """T-047: "lq": "cold_known" = corrected quality only for RETURNING shoppers on product/category pages with recent views."""
    def setUp(self):
        self.saved = (live.POLICY["variant"], live.LF, live.AP, live.POLICY["lfm_arms"])
        self.champ, self.aff0 = build(); self.champ.set_arms([{"tag": "r3", "w": W}])
        self.lf, self.aff = build({"B39": 9.0}); self.k = self.lf.snap.row["B39"]
        live.LF = self.lf; live.AP = type("AP", (), {"aff": self.aff})(); live.POLICY["variant"] = "lfm"
        arms = live.clean_lfm_arms(KNOWN_ARMS); self.assertEqual(arms, KNOWN_ARMS)
        self.lf.set_arms(arms); live.POLICY["lfm_arms"] = arms

    def tearDown(self):
        live.POLICY["variant"], live.LF, live.AP, live.POLICY["lfm_arms"] = self.saved

    def reqs(self, n=80, **kw):
        return [dict({"request_id": str(k), "user_id": f"u{k}", "rv": ["A30"], "page": "product", "is_new_user": False}, **kw) for k in range(n)]

    def test_target_rule_is_the_mirror_of_cold_new_and_older_modes_are_unchanged(self):
        t = lfm.lq_target
        for new in (False, True):
            for page in ("product", "category", "home", "cart"):
                for rv in (["A30"], []):
                    on = bool(rv) and page in ("product", "category")
                    self.assertEqual(t("cold_known", new, page, rv), on and not new)
                    self.assertEqual(t("cold_new", new, page, rv), on and new)
                    self.assertEqual(t("cold", new, page, rv), on)
                    self.assertFalse(t(None, new, page, rv)); self.assertFalse(t("known", new, page, rv))
        self.assertIs(t("cold_known", 0, "product", ["A30"]), True)

    def test_needs_a_control_with_identical_weights_and_never_mixes_selective_modes(self):
        c = live.clean_lfm_arms
        self.assertEqual(c([{"tag": "r3", "file": "lfm_coef_r3.json"}, {"tag": "ck1", "lq": "cold_known"}]), [])            # other base
        self.assertEqual(c([{"tag": "r3"}, {"tag": "ck1", "w": {"known": {"cl": 2}}, "lq": "cold_known"}]), [])            # other weights
        self.assertEqual(c([{"tag": "c1", "lq": "cold"}, {"tag": "ck1", "lq": "cold_known"}]), [])                         # a treated arm is not a control
        self.assertEqual(c([{"tag": "cn1", "lq": "cold_new"}, {"tag": "ck1", "lq": "cold_known"}]), [])                    # the two selective modes together, no control
        self.assertEqual(len(c([{"tag": "ck1", "lq": "cold_known"}])), 1)                                                   # promotion form, alone
        for bad in ("known", "cold_Known", "COLD_KNOWN", True): self.assertEqual(c([{"tag": "r3"}, {"tag": "ck1", "lq": bad}]), [])
        raw = json.loads((Path(lfm.__file__).parent / "policy.fix_c_cold_known.json").read_text())["lfm_arms"]
        arms = c(raw); self.assertEqual(arms, raw); self.assertEqual([a.get("lq") for a in arms], [None, "cold_known"])
        self.assertEqual({k: v for k, v in arms[1].items() if k not in ("tag", "lq")}, {k: v for k, v in arms[0].items() if k != "tag"})

    def test_control_new_shoppers_and_home_are_exactly_the_champion(self):
        for r in CASES:
            base = scores(self.champ, self.aff0, r, "r3")
            self.assertTrue(np.array_equal(base, scores(self.lf, self.aff, r, "r3")), r)
            if r["is_new_user"] or r not in VIEWS:
                self.assertTrue(np.array_equal(base, scores(self.lf, self.aff, r, "ck1")), r)
                st = self.lf.user_state(r["user_id"])
                self.assertEqual(self.champ.slate(r, self.champ.user_state(r["user_id"]), self.aff0, model="r3"), self.lf.slate(r, st, self.aff, model="ck1"))

    def test_only_the_launched_product_moves_for_returning_shoppers(self):
        seen = 0
        for r in VIEWS:
            if r["is_new_user"]: continue
            a, b = scores(self.lf, self.aff, r, "r3"), scores(self.lf, self.aff, r, "ck1"); seen += 1
            rest = np.arange(len(a)) != self.k
            self.assertTrue(np.array_equal(a[rest], b[rest]), r)
            if np.isfinite(a[self.k]): self.assertGreater(b[self.k], a[self.k])
        self.assertGreaterEqual(seen, 3)

    def test_routing_and_scoring_use_the_same_cohort(self):
        for kw in (dict(is_new_user=True), dict(rv=[], page="home"), dict(is_new_user=True, rv=[], page="home"), dict(rv=[]), dict(page="home")):
            ver = {}; out = live.lfm_slates(self.reqs(**kw), set(), ver)
            self.assertEqual(len(out), 80); self.assertEqual({v.split("-")[2] for v in ver.values()}, {"r3"}, kw)      # no ck1-n / ck1-kh / ck1-nh label exists
            live.POLICY["lfm_arms"] = [KNOWN_ARMS[0]]; alone = live.lfm_slates(self.reqs(**kw), set(), {})
            live.POLICY["lfm_arms"] = KNOWN_ARMS
            self.assertEqual(out, alone, kw)                                                                            # identical to control alone
        rq = self.reqs(); ver = {}; out = live.lfm_slates(rq, set(), ver)
        self.assertEqual(set(ver.values()), {"v3-lfm-r3-k", "v3-lfm-ck1-k"})
        for k, r in enumerate(rq):
            arm = live.lfm_arm(r["user_id"])["tag"]; self.assertEqual(ver[k], f"v3-lfm-{arm}-k")
            self.assertEqual("B39" in out[k], arm == "ck1")
            self.assertEqual(len(set(out[k])), 10)

    def test_old_modes_keep_their_routing(self):
        arms = [{"tag": "r3", "w": W}, {"tag": "cn1", "w": W, "lq": "cold_new"}]
        self.lf.set_arms(arms); live.POLICY["lfm_arms"] = arms
        ver = {}; live.lfm_slates(self.reqs(is_new_user=True), set(), ver); self.assertEqual(set(ver.values()), {"v3-lfm-r3-n", "v3-lfm-cn1-n"})
        ver = {}; live.lfm_slates(self.reqs(), set(), ver); self.assertEqual(set(ver.values()), {"v3-lfm-r3-k"})


if __name__ == "__main__":
    unittest.main()
