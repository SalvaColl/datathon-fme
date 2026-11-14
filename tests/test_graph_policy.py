"""Tests for the graph league policies (T-GR01). Synthetic artifacts only; no network.

    python -m unittest tests.test_graph_policy -v      (or: python -m pytest -q tests/test_graph_policy.py)
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

from tools import graph_build, graph_pins, graph_policy as gp

START, END = "2026-09-15T07:00:06.371+00:00", "2026-10-27T07:00:01.356+00:00"


def catalog(n=30, drop=()):
    return MappingProxyType({f"p{k:02d}": MappingProxyType({"category": "A" if k % 2 else "B", "subcategory": f"s{k % 3}"})
                             for k in range(n) if f"p{k:02d}" not in drop})


class GraphPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        self.old = (gp.ARTIFACTS, dict(graph_pins.PINS))
        gp.ARTIFACTS = d
        adj = {"p01": [["p03", 0.9, 5], ["p05", 0.5, 3], ["p_gone", 0.4, 2]], "p03": [["p07", 0.8, 4], ["p01", 0.7, 4]],
               "p02": [["p04", 0.6, 2]]}
        prof = {"u_known": [["p09", 10], ["p11", 2]]}
        for name, payload in (("graph_B", {"adj": adj}), ("profiles", {"profiles": prof})):
            body = json.dumps({"provenance": {"train_start": START, "train_end": END}, **payload}).encode()
            (d / f"{name}.json").write_bytes(body); graph_pins.PINS[name] = hashlib.sha256(body).hexdigest()
        self.training = {"start": START, "end": END, "best": ["p20", "p21", "p22", "p20"], "requests": []}

    def tearDown(self):
        gp.ARTIFACTS = self.old[0]; graph_pins.PINS.clear(); graph_pins.PINS.update(self.old[1]); self.tmp.cleanup()

    def policy(self, **kw):
        p = gp.GraphPolicy(**{"graph": "graph_B", **kw}); p.fit(json.loads(json.dumps(self.training))); return p

    def check(self, items, cat):
        self.assertEqual(len(items), 10); self.assertEqual(len(set(items)), 10)
        self.assertTrue(all(isinstance(p, str) and p in cat for p in items))

    def req(self, views=(), user="u_x"):
        return {"request_id": "r", "ts": "2026-10-28T00:00:00Z", "user_id": user,
                "recent_views": [{"product_id": v, "ts": "x"} for v in views]}

    def test_graph_neighbours_rank_first_and_respect_eligibility(self):
        cat = catalog(); out = self.policy().recommend(self.req(["p01"]), {}, cat)
        self.check(out, cat); self.assertEqual(out[:2], ["p03", "p05"]); self.assertNotIn("p_gone", out)

    def test_unknown_user_unknown_products_empty_views(self):
        cat = catalog()
        for views in ([], ["p_unknown"], ["p_new_not_in_graph_or_catalog"]):
            self.check(self.policy(profile=True, rv_first=True).recommend(self.req(views, "u_never_seen"), {}, cat), cat)

    def test_new_product_absent_from_graph_falls_back_to_its_category(self):
        cat = catalog(); out = self.policy().recommend(self.req(["p29"]), {}, cat)   # p29 eligible, no edges, category A
        self.check(out, cat); self.assertTrue(all(cat[p]["category"] == "A" for p in out))

    def test_inactive_and_out_of_stock_excluded(self):
        cat = catalog(drop={"p03", "p01"})          # league passes only eligible products
        out = self.policy(rv_first=True).recommend(self.req(["p01"]), {}, cat)
        self.check(out, cat); self.assertNotIn("p03", out); self.assertNotIn("p01", out)

    def test_duplicates_and_repeated_views(self):
        cat = catalog(); out = self.policy(rv_first=True).recommend(self.req(["p01", "p03", "p01", "p01"]), {}, cat)
        self.check(out, cat); self.assertEqual(out[:2], ["p01", "p03"])   # most recent first, deduplicated

    def test_malformed_views_and_missing_catalog_fields(self):
        cat = MappingProxyType({**{f"p{k:02d}": {} for k in range(12)}, "p_none": None})
        r = {"request_id": "r", "user_id": None, "recent_views": [None, 5, {"ts": "x"}, {"product_id": None}, "p01"]}
        self.check(self.policy(rv_first=True, profile=True).recommend(r, {}, cat), cat)
        self.check(self.policy().recommend({"request_id": "r"}, {}, cat), cat)          # no recent_views key at all

    def test_insufficient_eligible_catalog_returns_all_distinct(self):
        cat = catalog(n=6); out = self.policy().recommend(self.req(["p01"]), {}, cat)
        self.assertEqual(sorted(out), sorted(cat)); self.assertEqual(len(set(out)), 6)   # unsatisfiable: documented

    def test_profile_seeds(self):
        cat = catalog(); out = self.policy(profile=True).recommend(self.req([], "u_known"), {}, cat)
        self.check(out, cat)

    def test_reproducible(self):
        cat = catalog(); r = self.req(["p03", "p01"])
        a = [self.policy(rv_first=True).recommend(r, {}, cat) for _ in range(3)]
        self.assertTrue(a[0] == a[1] == a[2])

    def test_leakage_guard_rejects_other_training_window(self):
        bad = dict(self.training, end="2026-11-05T07:00:00.281+00:00")
        with self.assertRaises(ValueError):
            gp.GraphPolicy("graph_B").fit(bad)

    def test_unpinned_artifact_rejected(self):
        graph_pins.PINS["graph_B"] = "0" * 64
        with self.assertRaises(ValueError):
            self.policy()

    def test_build_query_uses_exact_half_open_training_window_and_bounded_topk(self):
        s, e = graph_build.sqltime(START), graph_build.sqltime(END)
        q = graph_build.graph_sql(s, e, 3, 6, True, 5)
        self.assertIn(f"ts::DateTime64(3) >= '{s}'", q); self.assertIn(f"ts::DateTime64(3) < '{e}'", q)
        self.assertNotIn("history_sessions", q); self.assertNotIn("feedback", q)
        self.assertIn(f"LIMIT {graph_build.TOP_K} BY a", q); self.assertIn(f"pos <= {graph_build.MAX_POS}", q)
        self.assertEqual(s, "2026-09-15 07:00:06.371"); self.assertEqual(e, "2026-10-27 07:00:01.356")

    def test_built_artifacts_if_present_are_bounded_and_training_only(self):
        real = Path(__file__).resolve().parent.parent / "data" / "graph" / "graph_B.json"
        if not real.exists():
            self.skipTest("no local artifacts")
        art = json.loads(real.read_text())
        self.assertLessEqual(max(len(v) for v in art["adj"].values()), graph_build.TOP_K)
        self.assertEqual(art["provenance"]["train_end"], graph_pins.TRAIN_END)


if __name__ == "__main__":
    unittest.main()
