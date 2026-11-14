"""Build the product-to-product graph that lfm's "cv" feature reads (T-027). Read-only on RawTree.

    python lfm_graph_build.py            # writes lfm_graph_B.json (about 1 minute)

It is the graph of feat/graph-recommender, variant B (tools/graph_build.py: view 1, cart 3, purchase 6, pair weight
w_a * w_b summed over sessions, divided by sqrt(deg_a * deg_b), pairs seen in < 2 sessions dropped, top 30 neighbours
per product), built with the SAME SQL. Only the time window differs: the league build stops at the end of its
training period (27 Oct) to keep its validation clean; the live writer has no such constraint, so this one uses the
whole organic history (shop.history_events, 15 Sep .. this morning). Nothing from today's stream or from feedback.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
OUT = HERE / "lfm_graph_B.json"


def main():
    from rt import q
    from tools.graph_build import graph_sql, VARIANTS, MAX_POS, TOP_K, MIN_SESSIONS
    cfg = VARIANTS["graph_B"]
    start, end = "2026-09-01 00:00:00.000", "2026-12-01 00:00:00.000"
    rng = q("SELECT min(ts::DateTime64(3))::String a, max(ts::DateTime64(3))::String b, count() n FROM shop.history_events")
    d = q(graph_sql(start, end, **cfg))
    adj = {}
    for a, b, s in zip(d.a.values, d.b.values, d.score.values): adj.setdefault(a, []).append([b, round(float(s), 5)])
    meta = dict(variant="graph_B", config=dict(cfg, max_pos=MAX_POS, top_k=TOP_K, min_sessions=MIN_SESSIONS),
                source="shop.history_events, organic view/add_to_cart/purchase", first_event=rng.a[0], last_event=rng.b[0],
                events=int(rng.n[0]), edges=int(len(d)), nodes=len(adj), created_utc=datetime.now(timezone.utc).isoformat())
    OUT.write_text(json.dumps({"meta": meta, "adj": adj}, sort_keys=True, separators=(",", ":")))
    print(json.dumps(meta, indent=1)); print("wrote", OUT.name, round(OUT.stat().st_size / 1e6, 2), "MB")


if __name__ == "__main__":
    main()
