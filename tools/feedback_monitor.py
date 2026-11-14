"""Read-only live feedback monitor for the RawTree FME 2026 challenge.

Run from your team's repository root:
    python tools/feedback_monitor.py
    python tools/feedback_monitor.py --watch 15 --window 30

Never starts a second recommender and never inserts submissions.
"""
from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com").rstrip("/")
TEAM = os.environ.get("TEAM_ID", "")
KEY = os.environ.get("RAWTREE_API_KEY", "")


def sql(query: str):
    response = requests.post(
        f"{API}/v1/query",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"sql": query},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]


def show(window: int):
    where = (f"request_id != '__init__' AND "
             f"ts::DateTime64(3) >= now() - INTERVAL {window} MINUTE")
    summary = sql(f"""
        SELECT
            served_by::String AS source,
            count() AS requests,
            countIf(clicked::String != '') AS clicks,
            countIf(purchased::String != '') AS purchases,
            round(100 * countIf(purchased::String != '') / count(), 2) AS conversion_pct,
            round(sum(revenue_eur::Float64) / count(), 2) AS revenue_per_request,
            round(quantile(0.50)(latency_ms::Float64), 0) AS p50_ms,
            round(quantile(0.95)(latency_ms::Float64), 0) AS p95_ms
        FROM {TEAM}.feedback
        WHERE {where}
        GROUP BY source ORDER BY source
    """)
    reasons = sql(f"""
        SELECT fallback_reason::String AS reason, count() AS requests
        FROM {TEAM}.feedback
        WHERE {where} AND served_by::String = 'fallback'
        GROUP BY reason ORDER BY requests DESC
    """)
    latest = sql(f"""
        SELECT ts, request_id::String AS request_id,
               served_by::String AS source, fallback_reason::String AS reason,
               purchased::String AS purchased, latency_ms::Float64 AS latency_ms
        FROM {TEAM}.feedback
        WHERE {where}
        ORDER BY ts DESC LIMIT 5
    """)
    print(f"\n--- Feedback | {TEAM} | last {window} min ---")
    if not summary:
        print("No feedback yet. Feedback is delayed a few seconds.")
    for r in summary:
        print(f"{r['source']:>8}: requests={r['requests']} clicks={r['clicks']} "
              f"purchases={r['purchases']} conversion={r['conversion_pct']}% "
              f"revenue/request=€{r['revenue_per_request']} "
              f"p50={r['p50_ms']}ms p95={r['p95_ms']}ms")
    if reasons:
        print("Fallback reasons:", ", ".join(f"{r['reason']}={r['requests']}" for r in reasons))
    if latest:
        print("Latest:")
        for r in latest:
            print(f"  {str(r['ts'])[:19]} {r['source']:<8} {r['request_id']} "
                  f"buy={r['purchased'] or '-'} latency={r['latency_ms']}ms "
                  f"{r['reason'] or ''}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=30, help="Lookback minutes (default 30)")
    parser.add_argument("--watch", type=int, default=0, help="Refresh every N seconds (0: once)")
    a = parser.parse_args()
    if not re.fullmatch(r"team_[A-Za-z0-9_]+", TEAM) or not KEY:
        raise SystemExit("Set TEAM_ID and RAWTREE_API_KEY in the project .env")
    if a.window < 1 or a.watch < 0:
        raise SystemExit("Window must be positive, watch must be nonnegative")
    while True:
        try:
            show(a.window)
        except requests.RequestException as exc:
            print(f"Query error: {exc}")
        if not a.watch:
            break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
