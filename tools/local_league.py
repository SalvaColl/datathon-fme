"""Read-only offline league for the RawTree FME 2026 challenge.

Run from the team project root:
    python tools/local_league.py --sample 10000

Downloads and caches a fixed chronological holdout from the official historical
sessions, plus training-period best sellers and catalogue metadata. Scores all
policies on the SAME impressions. Does NOT submit to the live competition.

IMPORTANT: These are approximate OFF-POLICY metrics, not the true hidden-model
score or guaranteed estimates of full-slate purchases. Note the effective sample
size, position bias, and logged-policy support before promoting a challenger.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com").rstrip("/")
KEY = os.environ.get("RAWTREE_API_KEY", "")


def sql(query: str):
    resp = requests.post(
        f"{API}/v1/query",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"sql": query}, timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_snapshot(n: int):
    last = sql("SELECT toDate(max(ts::DateTime64(3))) AS d FROM shop.history_sessions")[0]["d"]
    cut = (date.fromisoformat(str(last)[:10]) - timedelta(days=7)).isoformat()
    print(f"Chronological split: training < {cut}, holdout >= {cut}", flush=True)
    print("Fetching training-period best sellers ...", flush=True)
    best_rows = sql(f"""
        SELECT product_id::String AS product_id, count() AS n
        FROM shop.history_events
        WHERE event_type = 'purchase' AND ts < '{cut}'
        GROUP BY product_id
        ORDER BY n DESC, product_id DESC LIMIT 6000
    """)
    print("Fetching catalogue categories ...", flush=True)
    catalog = sql("""
        SELECT product_id::String AS product_id,
               category::String AS category,
               subcategory::String AS subcategory
        FROM shop.catalog
    """)
    print(f"Fetching {n} holdout impressions (fixed cached sample) ...", flush=True)
    records = sql(f"""
        SELECT request_id::String AS request_id, recent_views, shown, propensity,
               clicked, purchased
        FROM shop.history_sessions
        WHERE ts >= '{cut}'
        ORDER BY rand() LIMIT {n}
    """)
    return {"cut": cut, "best": [r["product_id"] for r in best_rows],
            "catalog": catalog, "requests": records}


def unique(items, best):
    output, seen = [], set()
    for p in list(items) + list(best):
        if p not in seen:
            seen.add(p)
            output.append(p)
            if len(output) == 10:
                break
    return output


def policies(snapshot):
    best = snapshot["best"]
    catalog = {r["product_id"]: r for r in snapshot["catalog"]}
    def reference(req):
        return best[:10]
    def prefs(req, by="category", max_preferred=10):
        views = req.get("recent_views") or []
        if not views or not isinstance(views[-1], dict):
            return best[:10]
        target = catalog.get(views[-1].get("product_id"), {}).get(by)
        if not target:
            return best[:10]
        preferred = [p for p in best if catalog.get(p, {}).get(by) == target]
        return unique(preferred[:max_preferred], best)
    def same_cat(req):
        return prefs(req, "category")
    def same_subcat(req):
        return prefs(req, "subcategory")
    def mixed(req):
        views = req.get("recent_views") or []
        if not views or not isinstance(views[-1], dict):
            return best[:10]
        last = catalog.get(views[-1].get("product_id"), {})
        sub = last.get("subcategory")
        cat = last.get("category")
        first = [p for p in best if sub and catalog.get(p, {}).get("subcategory") == sub][:5]
        second = [p for p in best if cat and catalog.get(p, {}).get("category") == cat][:10]
        return unique(first + second, best)

    return {"baseline": reference, "same_category": same_cat,
            "same_subcategory": same_subcat, "mixed_category": mixed}


def summarize(name, policy, records):
    n = len(records)
    clicks = 0
    hits = 0
    matches = 0
    wsum = 0.0
    w2sum = 0.0
    wr_click = 0.0
    wr_purchase = 0.0
    for row in records:
        recommendations = policy(row)
        if len(recommendations) != 10 or len(set(recommendations)) != 10:
            raise ValueError(f"{name} returned an invalid top-10 for {row.get('request_id')}")
        clicked = row.get("clicked")
        purchased = row.get("purchased")
        if clicked not in (None, ""):
            clicks += 1
            hits += int(clicked in recommendations)
        shown = row.get("shown") or []
        propensity = row.get("propensity") or []
        if not shown or not propensity:
            continue
        try:
            p = float(propensity[0])
        except (ValueError, TypeError):
            continue
        if not (math.isfinite(p) and p > 0):
            continue
        if recommendations[0] == shown[0]:
            w = 1.0 / p
            matches += 1
            wsum += w
            w2sum += w * w
            wr_click += w * int(clicked == shown[0])
            wr_purchase += w * int(purchased == shown[0])
    hit = hits / clicks if clicks else float("nan")
    ips = wr_click / n if n else 0
    snips = wr_click / wsum if wsum else float("nan")
    snips_buy = wr_purchase / wsum if wsum else float("nan")
    ess = wsum**2 / w2sum if w2sum else 0
    return {"policy": name, "hit@10": hit, "IPS_slot1_click": ips,
            "SNIPS_slot1_click": snips, "SNIPS_slot1_buy": snips_buy,
            "slot1_matches": matches, "ESS": ess}


def fmt(x):
    if isinstance(x, float):
        return f"{x:.4f}" if math.isfinite(x) else "n/a"
    return str(x)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=10000)
    p.add_argument("--cache", type=Path, default=ROOT / "data" / "local_eval" / "holdout.json")
    p.add_argument("--refresh", action="store_true", help="Refresh the cached sample; keep unchanged for fair comparisons")
    a = p.parse_args()
    if a.sample < 100 or a.sample > 100000:
        raise SystemExit("--sample should be between 100 and 100000")
    if not KEY:
        raise SystemExit("Set RAWTREE_API_KEY in the project .env")
    if a.cache.exists() and not a.refresh:
        print(f"Loading fixed holdout from {a.cache}")
        snapshot = json.loads(a.cache.read_text(encoding="utf-8"))
    else:
        snapshot = fetch_snapshot(a.sample)
        a.cache.parent.mkdir(parents=True, exist_ok=True)
        a.cache.write_text(json.dumps(snapshot), encoding="utf-8")
        print(f"Saved fixed holdout to {a.cache}")
    print(f"Cut: {snapshot['cut']} | requests: {len(snapshot['requests'])} | "
          f"candidate products: {len(snapshot['best'])}")
    results = [summarize(name, policy, snapshot["requests"])
               for name, policy in policies(snapshot).items()]
    print("\n" + " | ".join(results[0].keys()))
    for result in results:
        print(" | ".join(fmt(v) for v in result.values()))
    print("\nWARNING: These metrics do not identify full-slate conversion. "
          "IPS/SNIPS only evaluate the logged first slot and may be unreliable "
          "when slot1_matches/ESS are small. Same cached requests allow consistent "
          "comparisons; future policies can be registered in policies().")
    print("Current catalogue metadata is used for categories; validate any changing "
          "features with proper historical as-of joins before claiming unbiased results.")


if __name__ == "__main__":
    main()
