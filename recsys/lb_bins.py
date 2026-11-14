"""lb_bins — the hidden model's expected purchases per model_version in 5-minute blocks (T-031, I-310).

The leaderboard API only answers windows of 15 minutes to 3 hours, aligned to 5 minutes:
`/api/state?by=model&from=<epoch>&to=<epoch>` gives, per model_version, requests and expected conversion.
requests x conversion is a SUM, so two windows that differ by one 5-minute block give that block by subtraction:

    block [a+15m, a+20m) = window [a, a+20m] - window [a, a+15m]
    block [a, a+5m)      = window [a, a+20m] - window [a+5m, a+20m]

The result has no purchase noise (it is the simulator's probability, not the coin flip), so a 5-minute block of one
arm is as informative as about 14 times more requests of realized feedback. Limits measured on 14 Nov: the API lists
only the 10 model_versions with most requests in each window, and hides those under 100 requests.

    python lb_bins.py --hours 3                 # table per model_version and block for team_26
    python lb_bins.py --hours 6 --out data/lb_bins.parquet

Read-only: it never writes to RawTree and does not touch the writer.
"""
from __future__ import annotations
import json, sys, time, urllib.request
import pandas as pd

URL = "https://datathon.rawtree.dev/api/state?by=model&from={a}&to={b}"
STEP, SHORT, LONG = 300, 900, 1200


def fetch(a: int, b: int, team: str, tries: int = 4) -> list[dict]:
    """Rows (a, b, mv, n, conv) of one window: every listed model_version of `team`, plus 'team', 'reference', 'baseline'."""
    for _ in range(tries):
        try:
            d = json.load(urllib.request.urlopen(URL.format(a=a, b=b), timeout=30)); break
        except Exception:
            time.sleep(2)
    else:
        return []
    if d.get("window") != [a, b]: return []
    out = [dict(a=a, b=b, mv=k, n=d[k]["requests"], conv=d[k]["conversion"]) for k in ("reference", "baseline") if d.get(k)]
    for t in d.get("teams", []):
        if t["team_id"] != team: continue
        out.append(dict(a=a, b=b, mv="team", n=t["requests"], conv=t["conversion"]))
        out += [dict(a=a, b=b, mv=v["model_version"], n=v["requests"], conv=v["conversion"]) for v in t.get("versions", [])]
    return out


def bins_from_windows(rows) -> pd.DataFrame:
    """Windows -> one row per (bin start, model_version): n requests and hs = expected purchases (hidden model).
    A block is only reported where the model_version is listed in both windows of a pair; when both pairs give the
    same block they are averaged (they agree to float precision)."""
    w = pd.DataFrame(rows, columns=["a", "b", "mv", "n", "conv"])
    if w.empty: return pd.DataFrame(columns=["bin", "mv", "n", "hs"])
    w["s"] = w.n * w.conv / 100.0; w["L"] = w.b - w.a
    s15, s20 = w[w.L == SHORT], w[w.L == LONG]
    tail = s20.merge(s15, on=["a", "mv"], suffixes=("20", "15")); tail["bin"] = tail.a + SHORT
    head = s20.merge(s15.assign(a=s15.a - STEP), on=["a", "mv"], suffixes=("20", "15")); head["bin"] = head.a
    j = pd.concat([tail, head])
    j["n"] = j.n20 - j.n15; j["hs"] = j.s20 - j.s15
    return j.groupby(["bin", "mv"], as_index=False)[["n", "hs"]].mean()


def pull(start: int, end: int, team: str = "team_26", pause: float = 0.15) -> pd.DataFrame:
    rows = []
    for a in range(start // STEP * STEP, end - SHORT + 1, STEP):
        for L in (SHORT, LONG):
            if a + L <= end: rows += fetch(a, a + L, team); time.sleep(pause)
    return bins_from_windows(rows)


def main():
    import os
    hours = float(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 1.0
    end = int(time.time()) // STEP * STEP - STEP
    B = pull(end - int(hours * 3600), end, os.environ.get("TEAM_ID", "team_26"))
    if "--out" in sys.argv: B.to_parquet(sys.argv[sys.argv.index("--out") + 1])
    g = B.groupby("mv").agg(blocks=("n", "size"), requests=("n", "sum"), expected_buys=("hs", "sum"))
    g["conversion_pct"] = (100 * g.expected_buys / g.requests.clip(lower=1)).round(3)
    print(g.sort_values("requests", ascending=False).round(2).to_string())


if __name__ == "__main__":
    main()
