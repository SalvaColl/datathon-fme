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

Trend bursts (amendment of 14 Nov 23:35 UTC, before any rotation block was read): during a 45-minute subcategory
burst our distance to the reference shrinks, and with this sequence the cx3 block never falls inside one while one of
its two r3 neighbours always does. So the PRIMARY pairing uses only champion neighbours in the same state (burst or
calm) as the challenger block; the pairing with both neighbours is printed as `paired_all_neighbours`.
--bursts "23:30,01:30,03:30,05:30" gives the UTC start times that really happened (check them in shop.events at read
time); default: :30 of every odd UTC hour.
"""
from __future__ import annotations
import argparse, json, time
import requests
from confirm_read import URL, epoch


SD_FLOOR = 0.10     # points: SD of a paired block difference, from the calm 15-minute blocks of 14 Nov (0.08 per block)


def stats(v, floor=0.0):
    n = len(v)
    if not n: return dict(blocks=0)
    m = sum(v) / n
    se = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5 / n ** 0.5 if n >= 3 else None
    h = n // 2
    if floor and se is not None: se = max(se, floor / n ** 0.5)       # few blocks give an unreliable SE: never below the prior one
    return dict(blocks=n, mean=round(m, 3), se=None if se is None else round(se, 3), z=None if not se else round(m / se, 2),
                halves=[round(sum(p) / len(p), 3) for p in (v[:h], v[h:]) if p] if h else [])


def in_burst(a, step, bursts):
    """Does the block [a, a+step) overlap a burst? bursts: None = :30 of every odd UTC hour, else minutes of the day."""
    for t in range(a, a + step, 300):
        m = (t % 86400) // 60
        if bursts is None:
            if any((m - (h * 60 + 30)) % 1440 < 45 for h in range(1, 24, 2)): return True
        elif any((m - b) % 1440 < 45 for b in bursts): return True
    return False


def main(start, block_min, seq, until=None, out=None, champion=None, min_on_time=99.0, team="team_26", bursts=None, kcodes=None, factors=None, step_at=None):
    step = block_min * 60; champion = champion or seq[0]
    end = min(until or 1 << 62, int(time.time()) // 300 * 300)
    rows = []
    for k, a in enumerate(range(start, end - step + 1, step)):
        d = requests.get(URL, params={"by": "model", "from": a, "to": a + step}, timeout=30).json()
        t = next((x for x in d["teams"] if x["team_id"] == team), None)
        if not t or not d.get("custom"): continue
        rows.append(dict(k=k, t=a, start=time.strftime("%H:%M", time.gmtime(a)), variant=seq[k % len(seq)], burst=in_burst(a, step, bursts), requests=t["requests"], conversion=round(t["conversion"], 3),
                         reference=round(d["reference"]["conversion"], 3), diff=round(t["conversion"] - d["reference"]["conversion"], 3),
                         cold=round(t["cold_conversion"], 3), cold_diff=round(t["cold_conversion"] - d["reference"].get("cold_conversion", 0), 3),
                         on_time=round(t["on_time"], 2), versions=len(t.get("versions", []))))
        # non-cold slice: every team gets the same requests, so the cold share comes from any team whose version rows cover its traffic
        sh = None
        for x in d["teams"]:
            n = sum(v["requests"] for v in x.get("versions", []))
            if x.get("requests") and n >= 0.99 * x["requests"]: sh = sum(v.get("cold_requests", 0) for v in x["versions"]) / n; break
        rc = d["reference"].get("cold_conversion")
        if sh and rc is not None and 0 < sh < 1:
            nc = lambda conv, cold: (conv - cold * sh) / (1 - sh)
            rows[-1].update(cold_share=round(sh, 3), noncold_diff=round(nc(t["conversion"], t["cold_conversion"]) - nc(d["reference"]["conversion"], rc), 3),
                            ref_noncold=round(nc(d["reference"]["conversion"], rc), 3))
        else: rows[-1].update(cold_share=None, noncold_diff=None, ref_noncold=None)
        kc = (kcodes or {}).get(rows[-1]["variant"])          # public code of this variant's row for returning shoppers on pages
        kr = next((v for v in t.get("versions", []) if v["model_version"] == kc), None) if kc else None
        rows[-1]["known"] = None if kr is None else round(kr["conversion"], 3); rows[-1]["known_requests"] = None if kr is None else kr["requests"]
        # returning shoppers on pages: their row minus the reference's non-cold conversion of the same window (drift), and their cold part
        rows[-1]["known_adj"] = None if kr is None or rows[-1]["ref_noncold"] is None else round(kr["conversion"] - rows[-1]["ref_noncold"], 3)
        rows[-1]["known_cold"] = None if kr is None or not kr.get("cold_requests") else round(kr["cold_conversion"], 3)
    good = [r for r in rows if r["on_time"] >= min_on_time]
    per = {}
    for name in dict.fromkeys(seq):
        b = [r for r in good if r["variant"] == name]
        per[name] = dict(stats([r["diff"] for r in b]), requests=sum(r["requests"] for r in b),
                         cold_mean=round(sum(r["cold"] for r in b) / len(b), 3) if b else None, cold_minus_reference=stats([r["cold_diff"] for r in b]), worst_on_time=min((r["on_time"] for r in b), default=None))
    paired = {}; paired_all = {}; paired_known = {}; paired_cold = {}
    for name in dict.fromkeys(seq):
        if name == champion: continue
        v, w, kn, co = [], [], [], []
        for r in good:
            if r["variant"] != name: continue
            for same, acc in ((False, w), (True, v)):       # nearest champion block(s), at most 2 blocks away (ABBA / random pairs)
                c = [x for x in good if x["variant"] == champion and 0 < abs(x["k"] - r["k"]) <= 2 and (not same or x["burst"] == r["burst"])]
                if not c: continue
                d0 = min(abs(x["k"] - r["k"]) for x in c); nb = [x for x in c if abs(x["k"] - r["k"]) == d0]
                acc.append(r["diff"] - sum(x["diff"] for x in nb) / len(nb))
                if same:
                    co.append(r["cold_diff"] - sum(x["cold_diff"] for x in nb) / len(nb))
                    nk = [x["known"] for x in nb if x.get("known") is not None]
                    if r.get("known") is not None and nk: kn.append(r["known"] - sum(nk) / len(nk))
        key = name + "_minus_" + champion
        paired[key] = stats(v, SD_FLOOR); paired_all[key] = stats(w, SD_FLOOR)
        paired_known[key] = stats(kn); paired_cold[key] = stats(co)       # secondary: row of returning shoppers on pages (no reference), cold minus reference cold
    fx = None
    if factors:                     # factorial read: OLS of the block value on the factors (0/1) plus a burst indicator
        import numpy as np
        fx = {}
        for col in ("diff", "noncold_diff", "cold_diff", "known_adj", "known_cold"):
            b = [r for r in good if r.get(col) is not None and r["variant"] in set(seq)]
            names = list(factors); X = [[1.0] + [float(r["variant"] in factors[f]) for f in names] + [float(r["burst"]), float(step_at is not None and r["t"] >= step_at)] for r in b]
            X = np.array(X); y = np.array([r[col] for r in b])
            X = X[:, [j for j in range(X.shape[1]) if j <= len(names) or X[:, j].min() != X[:, j].max()]]      # drop constant nuisance columns
            if len(b) <= X.shape[1] + 1: fx[col] = dict(blocks=len(b)); continue
            beta, *_ = np.linalg.lstsq(X, y, rcond=None); res_ = y - X @ beta
            s2 = float(res_ @ res_) / (len(b) - X.shape[1]); cov = np.linalg.inv(X.T @ X)
            fx[col] = dict(blocks=len(b), residual_sd=round(s2 ** 0.5, 3))
            for j, f in enumerate(names, 1):
                se = max(s2, 0.08 ** 2 if col == "diff" else 0.0) ** 0.5 * cov[j, j] ** 0.5      # floor: 0.08 pt per block on the total
                fx[col][f] = dict(effect=round(float(beta[j]), 3), se=round(float(se), 3), z=round(float(beta[j] / se), 2),
                                 ci95=[round(float(beta[j] - 1.96 * se), 3), round(float(beta[j] + 1.96 * se), 3)])
    res = dict(factorial=fx, kind="time rotation, team row minus reference per block; not a user-split A/B", block_min=block_min, seq=seq, champion=champion,
               per_variant=per, paired=paired, paired_all_neighbours=paired_all, paired_known_row=paired_known, paired_cold=paired_cold,
               champion_burst_vs_calm={k: stats([r["diff"] for r in good if r["variant"] == champion and r["burst"] == (k == "burst")]) for k in ("burst", "calm")}, left_out=[r for r in rows if r not in good], blocks=rows)
    print(json.dumps(res, indent=1))
    if out: open(out, "w").write(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True); ap.add_argument("--block-min", type=int, default=15); ap.add_argument("--seq", required=True)
    ap.add_argument("--until"); ap.add_argument("--out"); ap.add_argument("--champion"); ap.add_argument("--min-on-time", type=float, default=99.0); ap.add_argument("--bursts"); ap.add_argument("--step-at", help="UTC time of a change common to every arm (a level shift), e.g. \"2026-11-15 03:20\""); ap.add_argument("--factors", help='main effects: "hcb=u1hb,u2hb;dose=u2c,u2hb"'); ap.add_argument("--k-codes", help="variant=public code of its returning-shoppers-on-pages row, comma separated (never commit the codes)")
    g = ap.parse_args()
    b = None if g.bursts is None else [int(x[:2]) * 60 + int(x[3:5]) for x in g.bursts.split(",") if x]
    main(epoch(g.start), g.block_min, g.seq.split(","), epoch(g.until) if g.until else None, g.out, g.champion, g.min_on_time, bursts=b,
         kcodes=dict(x.split("=") for x in g.k_codes.split(",")) if g.k_codes else None,
         step_at=epoch(g.step_at) if g.step_at else None,
         factors={f.split("=")[0]: set(f.split("=")[1].split(",")) for f in g.factors.split(";")} if g.factors else None)
