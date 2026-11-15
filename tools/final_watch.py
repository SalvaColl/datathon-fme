"""Read-only watch for the final: margins of the guards that switch features off without an error, freshness of every
feed, and health of our answers. Aggregate queries only; never starts a writer, never inserts.

    python tools/final_watch.py                 # once
    python tools/final_watch.py --watch 60      # every 60 s

What it CANNOT see: whether the writer's own queries fail (a quiet stream and a failing reader look the same from
here). For that, on the writer's machine: grep -c 'refresh failed\\|new_products failed\\|hot_products failed' data/live_main.log
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NEW_MAX, HOT_MAX, OQ_MIN = 0.25, 0.10, 50        # live.new_products, live.hot_products, lfm.organic_quality


def launched_guard(n_base: int, n_launched: int, max_share: float = NEW_MAX) -> dict:
    """live.new_products() returns None (newp, newph and newcap silently off) when launched > max_share of the whole
    catalogue (base + launched). `room` = how many more launches fit before that."""
    n = n_base + n_launched
    limit = int(max_share * n_base / (1 - max_share) + 1e-9)          # largest L with L <= max_share * (base + L)
    on = 0 < n_launched <= max_share * n
    return dict(guard="launched", on=on, launched=n_launched, catalogue=n, share=round(n_launched / n, 4) if n else 0.0,
                limit=limit, room=limit - n_launched)


def hot_guard(n_catalogue: int, n_hot: int, max_share: float = HOT_MAX) -> dict:
    """live.hot_products() returns None (trend feature off) when the hot subcategories cover over max_share of the
    catalogue. n_hot = 0 is the normal calm state, not a tripped guard."""
    return dict(guard="hot", on=n_hot <= max_share * n_catalogue, hot=n_hot, limit=int(max_share * n_catalogue),
                calm=n_hot == 0)


def quality_guard(n_with_history: int, n_viewed: int, minimum: int = OQ_MIN) -> dict:
    """lfm.organic_quality() gives no orate/opop at all when fewer than `minimum` catalogue products have a 60-day
    history AND fewer than `minimum` have a view in the stream; with history missing but views present, opop is neutral."""
    mode = "full" if n_with_history >= minimum else ("orate_only" if n_viewed >= minimum else "off")
    return dict(guard="quality", on=mode != "off", mode=mode, with_history=n_with_history, viewed=n_viewed, minimum=minimum)


def health(rows: list, n_requests: int) -> dict:
    """rows: feedback grouped by (served_by, fallback_reason) with n, p95, p99. The organisers' green light is >90%."""
    team = sum(r["n"] for r in rows if r["s"] == "team"); total = sum(r["n"] for r in rows)
    reasons = {r["f"] or "?": r["n"] for r in rows if r["s"] != "team"}
    t = [r for r in rows if r["s"] == "team"]
    return dict(requests=n_requests, feedback=total, team=team, team_share=round(team / total, 4) if total else None,
                fallback=reasons, p95=max((r["p95"] for r in t), default=None), p99=max((r["p99"] for r in t), default=None),
                alarm=bool(total) and team / total < 0.97 or (n_requests > 50 and total < 0.5 * n_requests))


def collect(q, team: str, minutes: int = 5) -> dict:
    one = lambda sql: q(sql)[0]
    base = int(one("SELECT count() n FROM shop.catalog")["n"])
    launched = int(one("SELECT uniqExact(product_id::String) n FROM shop.catalog_updates WHERE change::String='new_product' AND product_id::String NOT IN (SELECT product_id::String FROM shop.catalog)")["n"])
    viewed = int(one("SELECT uniqExact(product_id::String) n FROM shop.events WHERE event_type::String='view' AND ts::DateTime64(3) > now() - INTERVAL 60 MINUTE")["n"])
    out = dict(guards=[launched_guard(base, launched), quality_guard(base, viewed)])
    try:
        from recsys import trends
        sub = {r["i"]: r["s"] for r in q("SELECT product_id::String i, argMax(subcategory::String, v) s FROM (SELECT product_id, subcategory, '' v FROM shop.catalog UNION ALL SELECT product_id, subcategory, toString(ts) FROM shop.catalog_updates) GROUP BY i")}
        hot = set(trends.snapshot(q, sub).hot)
        g = hot_guard(len(sub), sum(1 for s in sub.values() if s in hot)); g["subcategories"] = sorted(hot); out["guards"].append(g)
    except Exception as e: out["guards"].append(dict(guard="hot", on=None, error=f"{type(e).__name__}: {e}"[:120]))
    f = one(f"""SELECT dateDiff('second', (SELECT max(ts::DateTime64(3)) FROM shop.events), now()) events,
        dateDiff('second', (SELECT max(ts::DateTime64(3)) FROM shop.requests), now()) requests,
        dateDiff('second', (SELECT max(ts::DateTime64(3)) FROM shop.catalog_updates), now()) catalog_updates,
        dateDiff('second', (SELECT max(ts::DateTime64(3)) FROM {team}.feedback), now()) feedback, now()::String now""")
    out["lag_s"] = f
    w = f"ts::DateTime64(3) > now() - INTERVAL {minutes + 1} MINUTE AND ts::DateTime64(3) <= now() - INTERVAL 1 MINUTE"
    rows = q(f"SELECT served_by::String s, fallback_reason::String f, toUInt32(count()) n, round(quantile(0.95)(latency_ms::Float64)) p95, round(quantile(0.99)(latency_ms::Float64)) p99 FROM {team}.feedback WHERE {w} AND request_id::String != '__init__' GROUP BY s, f")
    out["health"] = health(rows, int(one(f"SELECT count() n FROM shop.requests WHERE {w}")["n"])); out["minutes"] = minutes
    return out


def render(r: dict) -> str:
    L = [f"--- final watch | server {r['lag_s']['now']} UTC ---"]
    for g in r["guards"]:
        if g["guard"] == "launched":
            L.append(f"launched  {'ON ' if g['on'] else 'OFF'} {g['launched']} of {g['catalogue']} ({100 * g['share']:.1f}%), limit {g['limit']}, room for {g['room']} more"
                     + ("" if g["on"] else "   <-- newp / newph / newcap are OFF in the writer"))
        elif g["guard"] == "quality":
            L.append(f"quality   {g['mode'].upper():<10} products with history {g['with_history']}, viewed in the last hour {g['viewed']} (minimum {g['minimum']})"
                     + ("" if g["mode"] == "full" else "   <-- orate / opop degraded"))
        elif g.get("on") is None: L.append(f"hot       ?   {g['error']}")
        else:
            L.append(f"hot       {'calm' if g['calm'] else ('ON ' if g['on'] else 'OFF')} {g['hot']} products in {g.get('subcategories', [])}, limit {g['limit']}"
                     + ("" if g["on"] else "   <-- trend feature is OFF in the writer"))
    lag = r["lag_s"]
    L.append("feed lag (s): " + ", ".join(f"{k} {lag[k]}" for k in ("events", "requests", "catalog_updates", "feedback"))
             + ("   <-- requests arrive but no feedback: writer or network" if int(lag["feedback"]) > 60 and int(lag["requests"]) < 30 else ""))
    h = r["health"]
    L.append(f"last {r['minutes']} min: requests {h['requests']}, feedback {h['feedback']}, ours {h['team']} ({'-' if h['team_share'] is None else f'{100 * h['team_share']:.2f}%'}), "
             f"fallback {h['fallback'] or 0}, latency p95 {h['p95']} p99 {h['p99']} ms" + ("   <-- ALARM" if h["alarm"] else ""))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--watch", type=int, default=0); ap.add_argument("--minutes", type=int, default=5)
    a = ap.parse_args()
    os.chdir(ROOT / "recsys"); sys.path.insert(0, str(ROOT / "recsys"))
    import rt                                   # reads .env; read-only client
    team = os.environ.get("TEAM_ID", "team_26")
    q = lambda sql: rt.q(sql).to_dict("records")
    while True:
        try: print(render(collect(q, team, a.minutes)), flush=True)
        except Exception as e: print("watch query failed:", type(e).__name__, str(e)[:200], flush=True)
        if not a.watch: break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
