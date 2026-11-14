"""Build item-to-item graph artifacts from TRAINING-PERIOD ORGANIC events (shop.history_events) for the league.

    python -m tools.graph_build --cache data/local_eval/league_v2            # all variants + user profiles
    python -m tools.graph_build --cache data/local_eval/league_v2 --pin      # also rewrite tools/graph_pins.py

Read-only RawTree queries. The time window is taken from the league manifest: [boundaries[0], boundaries[1]) = the
training period exactly (half-open, like the league). Nothing from validation/test periods, from carousel exposure
(history_sessions.shown) or from feedback is used: only organic view / add_to_cart / purchase events.

Graph (computed inside RawTree, SQL below):
- one row per (session, product): strength w = max over its events (view=1, cart=W_CART, purchase=W_BUY; variant A: 1),
  position = rank of the product's first event in the session (ties by product id); only the first MAX_POS products.
- pair weight per session: w_a * w_b (variant C: also / |pos_a - pos_b|, only |Δpos| <= WINDOW).
- popularity normalisation: score(a->b) = Σ pair weights / sqrt(deg_a * deg_b), deg = Σ strengths of the product;
  edges seen in < MIN_SESSIONS sessions are dropped; TOP_K neighbours kept per product (LIMIT K BY a) -> bounded size.
User profile (optional seeds): per user, the TOP_ITEMS products by Σ strength in the training period.
Artifacts -> data/graph/<name>.json with provenance; `--pin` records their SHA256 in tools/graph_pins.py (hashed by
league freeze because it is a tools/*.py module).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.league_data import ROOT, sql

OUT = ROOT / "data" / "graph"
MAX_POS, TOP_K, MIN_SESSIONS, TOP_ITEMS = 20, 30, 2, 20
VARIANTS = {
    "graph_A": dict(w_cart=1, w_buy=1, temporal=False, window=None),   # plain co-occurrence, popularity-normalised
    "graph_B": dict(w_cart=3, w_buy=6, temporal=False, window=None),   # + cart / purchase strength
    "graph_C": dict(w_cart=3, w_buy=6, temporal=True, window=5),       # + session-distance decay
}


def sqltime(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def session_items_sql(start: str, end: str, w_cart: int, w_buy: int) -> str:
    return f"""SELECT s, i, w, row_number() OVER (PARTITION BY s ORDER BY t, i) AS pos FROM (
    SELECT session_id::String s, product_id::String i,
      max(multiIf(event_type::String = 'purchase', {w_buy}, event_type::String = 'add_to_cart', {w_cart}, 1)) w,
      min(ts::DateTime64(3)) t
    FROM shop.history_events
    WHERE ts::DateTime64(3) >= '{start}' AND ts::DateTime64(3) < '{end}'
      AND event_type::String IN ('view', 'add_to_cart', 'purchase')
    GROUP BY s, i)"""


def graph_sql(start: str, end: str, w_cart: int, w_buy: int, temporal: bool, window: int | None) -> str:
    pw = "a.w * b.w / abs(a.pos - b.pos)" if temporal else "a.w * b.w"
    wf = f" AND abs(a.pos - b.pos) <= {window}" if window else ""
    return f"""WITH ev AS ({session_items_sql(start, end, w_cart, w_buy)}),
pairs AS (SELECT a.i a, b.i b, sum({pw}) co, count() n FROM ev a INNER JOIN ev b ON a.s = b.s
          WHERE a.i != b.i AND a.pos <= {MAX_POS} AND b.pos <= {MAX_POS}{wf}
          GROUP BY a, b HAVING n >= {MIN_SESSIONS}),
deg AS (SELECT i, sum(w) d FROM ev WHERE pos <= {MAX_POS} GROUP BY i)
SELECT p.a a, p.b b, p.co / sqrt(da.d * db.d) score, p.n n
FROM pairs p INNER JOIN deg da ON da.i = p.a INNER JOIN deg db ON db.i = p.b
ORDER BY a, score DESC, b LIMIT {TOP_K} BY a"""


def profile_sql(start: str, end: str) -> str:
    return f"""SELECT u, i, sw FROM (
    SELECT user_id::String u, product_id::String i,
      sum(multiIf(event_type::String = 'purchase', 6, event_type::String = 'add_to_cart', 3, 1)) sw,
      countIf(event_type::String = 'purchase') bought
    FROM shop.history_events
    WHERE ts::DateTime64(3) >= '{start}' AND ts::DateTime64(3) < '{end}'
      AND event_type::String IN ('view', 'add_to_cart', 'purchase')
    GROUP BY u, i)
ORDER BY u, sw DESC, i LIMIT {TOP_ITEMS} BY u"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: dict, prov: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps({"provenance": prov, **payload}, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def build(cache: Path, pin: bool) -> dict:
    manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    start_iso, end_iso = manifest["boundaries"][0], manifest["boundaries"][1]
    start, end = sqltime(start_iso), sqltime(end_iso)
    base = dict(source_table="shop.history_events (organic only: view/add_to_cart/purchase)",
                excluded="history_sessions.shown/propensity, feedback, any validation/test-period data",
                train_start=start_iso, train_end=end_iso, interval="[train_start, train_end) half-open",
                manifest_sha256=hashlib.sha256((cache / "manifest.json").read_bytes()).hexdigest())
    pins, report = {}, {}
    for name, cfg in VARIANTS.items():
        q = graph_sql(start, end, **cfg); t0 = time.time(); rows = sql(q); dt = time.time() - t0
        adj: dict[str, list] = {}
        for r in rows:
            adj.setdefault(r["a"], []).append([r["b"], round(float(r["score"]), 6), int(r["n"])])
        prov = dict(base, artifact=name, config=dict(cfg, max_pos=MAX_POS, top_k=TOP_K, min_sessions=MIN_SESSIONS),
                    query=q, rows=len(rows), nodes=len(adj), created_utc=datetime.now(timezone.utc).isoformat(),
                    query_seconds=round(dt, 1))
        path = write(name, {"adj": adj}, prov)
        pins[name] = sha(path); report[name] = dict(rows=len(rows), nodes=len(adj), seconds=round(dt, 1),
                                                    mb=round(path.stat().st_size / 1e6, 1))
        print(name, report[name], flush=True)
    q = profile_sql(start, end); t0 = time.time(); rows = sql(q); dt = time.time() - t0
    prof: dict[str, list] = {}
    for r in rows:
        prof.setdefault(r["u"], []).append([r["i"], int(r["sw"])])
    prov = dict(base, artifact="profiles", config=dict(top_items=TOP_ITEMS, weights="view=1,cart=3,purchase=6"),
                query=q, rows=len(rows), users=len(prof), created_utc=datetime.now(timezone.utc).isoformat(),
                query_seconds=round(dt, 1))
    path = write("profiles", {"profiles": prof}, prov)
    pins["profiles"] = sha(path); report["profiles"] = dict(rows=len(rows), users=len(prof), seconds=round(dt, 1),
                                                           mb=round(path.stat().st_size / 1e6, 1))
    print("profiles", report["profiles"], flush=True)
    report["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    if pin:
        (ROOT / "tools" / "graph_pins.py").write_text(
            '"""SHA256 of the graph artifacts the graph policies accept (written by tools/graph_build.py --pin).\n'
            'Being a tools/*.py module, it is part of the league freeze fingerprint."""\n'
            f"TRAIN_START = {start_iso!r}\nTRAIN_END = {end_iso!r}\nPINS = {json.dumps(pins, indent=4, sort_keys=True)}\n",
            encoding="utf-8")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=ROOT / "data/local_eval/league_v2")
    ap.add_argument("--pin", action="store_true")
    print(json.dumps(build(ap.parse_args().cache, ap.parse_args().pin), indent=1))
