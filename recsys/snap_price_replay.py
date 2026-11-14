"""E-420 — what the snapshot price fix (T-042) changes on real requests. DIAGNOSTICS ONLY: lists, exposure, validity,
latency. Never a conversion estimate: the hidden model decides, on the leaderboard.

    cd recsys
    python cold_lq_replay.py --pull                      # READ-ONLY RawTree -> data/lfm_*.parquet + data/coldlq_replay/*.parquet
    python snap_price_replay.py [--n 6000] [--since "2026-11-14 19:07"] [--old-rev 6150ffc] [--og1 path/lfm_coef_og1.json] [--out file.json]

Every sampled answered request is scored with the SAME weights on two snapshots built for the instant of the request
(catalogue, stock, corrections and shopper state as of the request, exactly as cold_lq_replay.py does):

  old   price flags as the code of --old-rev builds them (its Snap class is loaded from git and run on the same inputs)
  new   price flags of the current code

Nothing else differs, so every changed list is the fix. Arms replayed: r3 (champion), cn1 (r3 + "lq": "cold_new"),
np1 / np2 (r3 + newp 1.0 / 2.0 for returning shoppers) and, with --og1, the og1 weight file (home = r3). The
exploration slot is left out (it would only reshuffle slot 10 from the same ranking).
Also checks, per snapshot, that p40 / cheap equal the catalogue prices as of that instant.
"""
from __future__ import annotations

import argparse
import collections
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def old_module(rev):
    src = subprocess.run(["git", "show", f"{rev}:recsys/lfm.py"], cwd=HERE, capture_output=True, text=True, check=True).stdout
    f = Path(tempfile.mkdtemp()) / "lfm_old.py"; f.write_text(src)
    spec = importlib.util.spec_from_file_location("lfm_old", f); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def band(price):
    return "lt20" if price < 20 else ("gt40" if price > 40 else "20to40")


def main(n=6000, since="2026-11-14 19:07:00", old_rev="6150ffc", og1=None, out=None):
    import cold_lq_arm, cold_lq_replay as R, lfm, lfm_build as LB, qrank
    OLD = old_module(old_rev)
    d, LF, aff, carts, buys = LB.load()
    coef = "lfm_coef_r3.json"
    LF.lq0 = float(json.loads((HERE / coef).read_text()).get("lq0", LF.lq0))
    arms = [{"tag": "r3", "file": coef}, {"tag": "cn1", "file": coef, "lq": "cold_new"},
            {"tag": "np1", "file": coef, "w": {"known": {"newp": 1.0}}}, {"tag": "np2", "file": coef, "w": {"known": {"newp": 2.0}}}]
    LF.set_arms(arms)
    if og1:                                                       # a weight file outside the repository (PR #40): registered by hand
        c = json.loads(Path(og1).read_text()); LF.add_model("og1", c); LF.alt["og1@home"] = LF.alt["r3"]
    tags = [a["tag"] for a in arms] + (["og1"] if og1 else [])
    hc = LF.snap.hc
    d = d[d.ts >= pd.Timestamp(since)]
    step = max(1, len(d) // n); d = d.iloc[::step]
    C = R.Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib"); COR = cold_lq_arm.Corrector()
    it = pd.read_parquet(R.OUT / "item10.parquet"); it["end"] = pd.to_datetime(it.b) + pd.Timedelta(minutes=10)
    hist = pd.read_parquet(HERE / "data" / "user_item_all.parquet", columns=["i", "v", "p"]).groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
    shim = R.AffAsOf(aff)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    stats = collections.defaultdict(collections.Counter); ms = {"old": [], "new": []}
    snaps = collections.Counter(); flag = collections.Counter()
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        QR.set_catalog(cat, unavail)
        live_item = it[it.end <= bucket].groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
        corr = COR.corrections(QR.q, QR.lq, cat, hist, live_item, desc, lq0=LF.lq0)
        newp = set(cat.index) - set(QR.q)
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, lq_cold=corr or None, newp=newp or None)
        S_new = LF.snap
        so = OLD.Snap(S_new.ids, S_new.A, cat, set(unavail), QR.lq, LF.lq0, hc, corr or None, newp or None)       # the old code, same inputs
        S_old = copy.copy(S_new); S_old.p40, S_old.cheap = so.p40, so.cheap
        assert np.array_equal(so.lq, S_new.lq) and (so.lqc is None) == (S_new.lqc is None) and (so.lqc is None or np.array_equal(so.lqc, S_new.lqc))
        price = pd.to_numeric(cat["price"].reindex(S_new.ids), errors="coerce").fillna(20.0).values
        want40, wantch = (price > 40).astype(float), (price < 20).astype(float)
        snaps["snapshots"] += 1; snaps["with_corrections"] += bool(corr); snaps["requests_with_corrections"] += len(g) * bool(corr)
        snaps["corrections_max"] = max(snaps["corrections_max"], len(corr))
        for name, S in (("old", S_old), ("new", S_new)):
            bad = int((S.p40 != want40).sum() + (S.cheap != wantch).sum())
            flag[name + "_snapshots_wrong"] += bad > 0; flag[name + "_flags_wrong"] += bad
            flag[name + "_p40_products_mean"] += float(S.p40.sum()); flag[name + "_cheap_products_mean"] += float(S.cheap.sum())
        flag["catalogue_p40_mean"] += float(want40.sum()); flag["catalogue_cheap_mean"] += float(wantch.sum()); flag["products_mean"] += S_new.n
        pr = dict(zip(S_new.ids, price))
        for r in g.itertuples():
            shim.ts = r.ts
            st = LB.state_asof(LF, carts, buys, r.user_id, r.ts) + (LB.mix_asof(LF, aff, r.user_id, r.ts),)
            req = dict(user_id=r.user_id, rv=r.rv, page=r.page or "product", is_new_user=bool(r.new_user), device=r.device, region=r.region)
            home = not r.rv or req["page"] not in lfm.LQ_PAGES
            coh = ("new" if r.new_user else "known") + "/" + ("home_or_no_views" if home else "page_with_views")
            seg = lfm.in_segment(r.device, r.region)
            for tag in tags:
                LF.snap = S_old; t0 = time.perf_counter(); a = LF.slate(req, st, shim, exclude=unavail, model=tag) or []
                LF.snap = S_new; t1 = time.perf_counter(); b = LF.slate(req, st, shim, exclude=unavail, model=tag) or []
                ms["old"].append(1000 * (t1 - t0)); ms["new"].append(1000 * (time.perf_counter() - t1))
                for key in (tag + "|" + coh, tag + "|all", tag + "|" + coh + ("|price_segment" if seg else "|other_shoppers")):
                    c = stats[key]; c["requests"] += 1; c["changed"] += a != b; c["slot1_changed"] += a[:1] != b[:1]
                    c["set_changed"] += set(a) != set(b); c["products_replaced"] += len(set(b) - set(a))
                    for name, s in (("old", a), ("new", b)):
                        ok = len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & st[0]) and all(p in cat.index for p in s)
                        c[name + "_valid"] += ok; c[name + "_imp"] += len(s)
                        for p in s: c[name + "_" + band(pr[p])] += 1
                        if s: c[name + "_slot1_" + band(pr[s[0]])] += 1
                        c[name + "_newp"] += sum(p in newp for p in s)
    LF.snap = S_new
    seg_out = {}
    for key, c in sorted(stats.items()):
        n_ = max(1, c["requests"])
        row = dict(requests=c["requests"], lists_changed_pct=round(100 * c["changed"] / n_, 1), slot1_changed_pct=round(100 * c["slot1_changed"] / n_, 1),
                   product_set_changed_pct=round(100 * c["set_changed"] / n_, 1), products_replaced_per_list=round(c["products_replaced"] / n_, 2))
        for name in ("old", "new"):
            imp = max(1, c[name + "_imp"])
            row[name] = dict(valid_pct=round(100 * c[name + "_valid"] / n_, 2),
                             price_share_pct={b: round(100 * c[name + "_" + b] / imp, 1) for b in ("lt20", "20to40", "gt40")},
                             slot1_price_share_pct={b: round(100 * c[name + "_slot1_" + b] / n_, 1) for b in ("lt20", "20to40", "gt40")},
                             launched_share_pct=round(100 * c[name + "_newp"] / imp, 2))
        seg_out[key] = row
    k = max(1, snaps["snapshots"])
    pct = lambda v, q: round(float(np.percentile(v, q)), 2) if len(v) else None
    res = dict(kind="diagnostics only: lists, exposure, validity and latency, NOT conversion", old_rev=old_rev, since=since, requests=int(len(d)),
               first=str(d.ts.min()), last=str(d.ts.max()), arms=tags, snapshots=dict(snaps),
               price_flags=dict(old_snapshots_wrong=flag["old_snapshots_wrong"], new_snapshots_wrong=flag["new_snapshots_wrong"],
                                old_flags_wrong=flag["old_flags_wrong"], new_flags_wrong=flag["new_flags_wrong"],
                                per_snapshot_mean={x: round(flag[x] / k, 1) for x in ("products_mean", "catalogue_p40_mean", "catalogue_cheap_mean", "old_p40_products_mean",
                                                                                      "old_cheap_products_mean", "new_p40_products_mean", "new_cheap_products_mean")}),
               latency_ms_cloud_container={name: dict(p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99), n=len(v)) for name, v in ms.items()},
               segments=seg_out,
               not_reconstructed=["writer refresh lag (20 s catalogue/events, 1 s stock)", "10-minute resolution of organic evidence (closed buckets only)",
                                  "exploration slot (slot 10 of og1 / np1 for new shoppers)", "carousel purchases in the bought set (organic purchases only)"])
    print(json.dumps(res, indent=1))
    if out: Path(out).write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=6000); ap.add_argument("--since", default="2026-11-14 19:07:00")
    ap.add_argument("--old-rev", default="6150ffc"); ap.add_argument("--og1"); ap.add_argument("--out")
    a = ap.parse_args()
    main(a.n, a.since, a.old_rev, a.og1, a.out)
