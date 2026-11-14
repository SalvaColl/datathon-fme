"""Read one predeclared confirmation window from the public leaderboard (T-042, D-420). Read-only, no RawTree key.

    python confirm_read.py --from "2026-11-15 00:10" --to "2026-11-15 01:40" --control CODE[,CODE...] --challenger CODE [--sd 6.0] [--out file.json]

Times are UTC, multiples of 5 minutes, 15 minutes to 3 hours. CODE is the public `model_version` of a row (the opaque
code; the table internal -> public lives only on the writer's machine, never write it in the repository).
Several control codes are pooled, weighted by requests: do that ONLY for rows that serve exactly the same policy to the
cohort (same weights, no exploration, same code version).

Prints, for control, challenger, `reference` and `baseline` in the SAME window: requests, expected conversion (hidden
model), expected purchases (requests x conversion), official cold requests and cold conversion; the team's on-time
share; the difference challenger - control with two standard errors:
  nominal  sd * sqrt(1/n_control + 1/n_challenger)   (--sd: per-request SD of the expected conversion, in points;
           measured on 14 Nov: about 5.5 on product/category pages of returning shoppers, 6.0 for new shoppers)
  blocks   from the differences of the non-overlapping 15-minute blocks of the window (request mix included)
and the sign of the difference in each half. The decision rule is in D-420; this script does not decide.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import time

import requests

URL = "https://datathon.rawtree.dev/api/state"


def epoch(s):
    t = calendar.timegm(time.strptime(s.strip().replace("T", " ")[:16], "%Y-%m-%d %H:%M"))
    if t % 300: raise ValueError("times must be multiples of 5 minutes")
    return t


def fetch(a, b, team="team_26"):
    d = requests.get(URL, params={"by": "model", "from": a, "to": b}, timeout=30).json()
    if not d.get("custom"): raise RuntimeError("the leaderboard did not return the requested window")
    t = next((x for x in d["teams"] if x["team_id"] == team), {})
    return d, t


def pool(rows):
    n = sum(r["requests"] for r in rows); cn = sum(r.get("cold_requests", 0) for r in rows)
    if not n: return dict(requests=0)
    conv = sum(r["requests"] * r["conversion"] for r in rows) / n
    cold = sum(r.get("cold_requests", 0) * r.get("cold_conversion", 0) for r in rows) / cn if cn else None
    if cold is None and len(rows) == 1 and rows[0].get("cold_conversion"): cold = rows[0]["cold_conversion"]; cn = None      # reference / baseline: no count
    return dict(requests=n, conversion=round(conv, 3), expected_purchases=round(n * conv / 100, 1), cold_requests=cn,
                cold_conversion=None if cold is None else round(cold, 3), expected_cold_purchases=None if cold is None or cn is None else round(cn * cold / 100, 1))


def arms(team, control, challenger):
    v = {x["model_version"]: x for x in team.get("versions", [])}
    return pool([v[c] for c in control if c in v]), pool([v[c] for c in challenger if c in v])


def main(a, b, control, challenger, sd, out=None, team="team_26"):
    d, t = fetch(a, b, team)
    c, x = arms(t, control, challenger)
    res = dict(window_utc=[time.strftime("%Y-%m-%d %H:%M", time.gmtime(a)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(b))], minutes=(b - a) // 60,
               control_codes=control, challenger_codes=challenger, control=c, challenger=x,
               reference=pool([d["reference"]]) if d.get("reference") else None, baseline=pool([d["baseline"]]) if d.get("baseline") else None,
               team=dict(requests=t.get("requests"), conversion=round(t.get("conversion", 0), 3), on_time=round(t.get("on_time", 0), 2)),
               min_requests_to_show_a_row=d.get("min_requests"))
    if c.get("requests") and x.get("requests"):
        diff = x["conversion"] - c["conversion"]; se = sd * math.sqrt(1 / c["requests"] + 1 / x["requests"])
        blocks = []
        for s in range(a, b - 899, 900):
            _, tb = fetch(s, s + 900, team); cb, xb = arms(tb, control, challenger)
            if cb.get("requests") and xb.get("requests"):
                blocks.append(dict(start=time.strftime("%H:%M", time.gmtime(s)), control=[cb["requests"], cb["conversion"]], challenger=[xb["requests"], xb["conversion"]],
                                   diff=round(xb["conversion"] - cb["conversion"], 3), on_time=round(tb.get("on_time", 0), 2)))
        dv = [k["diff"] for k in blocks]; m = len(dv)
        bse = (sum((v - sum(dv) / m) ** 2 for v in dv) / (m - 1)) ** 0.5 / m ** 0.5 if m >= 3 else None
        half = len(blocks) // 2
        hd = [round(sum(k["diff"] for k in part) / len(part), 3) for part in (blocks[:half], blocks[half:]) if part] if half else []
        res.update(diff=round(diff, 3), se_nominal=round(se, 3), z_nominal=round(diff / se, 2), se_blocks=None if bse is None else round(bse, 3),
                   z_blocks=None if not bse else round(diff / bse, 2), halves_mean_diff=hd, blocks=blocks,
                   cold_diff=None if c.get("cold_conversion") is None or x.get("cold_conversion") is None else round(x["cold_conversion"] - c["cold_conversion"], 3))
    else:
        res["note"] = "a row is missing in this window (fewer requests than the leaderboard shows, or a wrong code)"
    print(json.dumps(res, indent=1))
    if out: open(out, "w").write(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="a", required=True); ap.add_argument("--to", dest="b", required=True)
    ap.add_argument("--control", required=True); ap.add_argument("--challenger", required=True)
    ap.add_argument("--sd", type=float, default=6.0); ap.add_argument("--out"); ap.add_argument("--team", default="team_26")
    g = ap.parse_args()
    main(epoch(g.a), epoch(g.b), [s for s in g.control.split(",") if s], [s for s in g.challenger.split(",") if s], g.sd, g.out, g.team)
