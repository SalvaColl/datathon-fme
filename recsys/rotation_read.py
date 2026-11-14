"""Read a time rotation of single-variant blocks from the public leaderboard (T-042, D-421). Read-only, no key, no labels.

    python rotation_read.py --start "2026-11-14 23:00" --block-min 15 --seq r3,cx3,r3,og1 [--until "2026-11-15 07:15"] [--out file.json]

For a rotation where the WHOLE traffic is served by one variant per block (no user split), the team row of each block
is that variant. Each block is compared with `reference` in the same window (conversion minus reference), which removes
most of the traffic drift between blocks. Times are UTC, multiples of 5 minutes; a block must be at least 15 minutes.
Per variant: blocks, requests, mean difference to reference with its standard error across blocks, first and second
half, cold conversion and worst on-time. For each challenger: mean of (its block - mean of the champion blocks right
before and after it), with the standard error across cycles. The first ~40 s of every block still belong to the
previous variant (policy re-read plus snapshot rebuild). Blocks with on-time below --min-on-time are left out and listed.
The decision rule is in D-421; this script does not decide.
"""
from __future__ import annotations
import argparse, json, time
import requests
from confirm_read import URL, epoch


def stats(v):
    n = len(v)
    if not n: return dict(blocks=0)
    m = sum(v) / n
    se = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5 / n ** 0.5 if n >= 3 else None
    h = n // 2
    return dict(blocks=n, mean=round(m, 3), se=None if se is None else round(se, 3), z=None if not se else round(m / se, 2),
                halves=[round(sum(p) / len(p), 3) for p in (v[:h], v[h:]) if p] if h else [])


def main(start, block_min, seq, until=None, out=None, champion=None, min_on_time=99.0, team="team_26"):
    step = block_min * 60; champion = champion or seq[0]
    end = min(until or 1 << 62, int(time.time()) // 300 * 300)
    rows = []
    for k, a in enumerate(range(start, end - step + 1, step)):
        d = requests.get(URL, params={"by": "model", "from": a, "to": a + step}, timeout=30).json()
        t = next((x for x in d["teams"] if x["team_id"] == team), None)
        if not t or not d.get("custom"): continue
        rows.append(dict(k=k, start=time.strftime("%H:%M", time.gmtime(a)), variant=seq[k % len(seq)], requests=t["requests"], conversion=round(t["conversion"], 3),
                         reference=round(d["reference"]["conversion"], 3), diff=round(t["conversion"] - d["reference"]["conversion"], 3),
                         cold=round(t["cold_conversion"], 3), on_time=round(t["on_time"], 2), versions=len(t.get("versions", []))))
    good = [r for r in rows if r["on_time"] >= min_on_time]
    per = {}
    for name in dict.fromkeys(seq):
        b = [r for r in good if r["variant"] == name]
        per[name] = dict(stats([r["diff"] for r in b]), requests=sum(r["requests"] for r in b),
                         cold_mean=round(sum(r["cold"] for r in b) / len(b), 3) if b else None, worst_on_time=min((r["on_time"] for r in b), default=None))
    byk = {r["k"]: r for r in good}; paired = {}
    for name in dict.fromkeys(seq):
        if name == champion: continue
        v = []
        for r in good:
            if r["variant"] != name: continue
            nb = [byk[j]["diff"] for j in (r["k"] - 1, r["k"] + 1) if j in byk and byk[j]["variant"] == champion]
            if nb: v.append(r["diff"] - sum(nb) / len(nb))
        paired[name + "_minus_" + champion] = stats(v)
    res = dict(kind="time rotation, team row minus reference per block; not a user-split A/B", block_min=block_min, seq=seq, champion=champion,
               per_variant=per, paired=paired, left_out=[r for r in rows if r not in good], blocks=rows)
    print(json.dumps(res, indent=1))
    if out: open(out, "w").write(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True); ap.add_argument("--block-min", type=int, default=15); ap.add_argument("--seq", required=True)
    ap.add_argument("--until"); ap.add_argument("--out"); ap.add_argument("--champion"); ap.add_argument("--min-on-time", type=float, default=99.0)
    g = ap.parse_args()
    main(epoch(g.start), g.block_min, g.seq.split(","), epoch(g.until) if g.until else None, g.out, g.champion, g.min_on_time)
