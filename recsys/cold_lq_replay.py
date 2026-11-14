"""E-281 — per-request AS-OF replay of the cold_lq arm (T-028). DIAGNOSTICS ONLY: exposure and validity, not conversion.

    cd recsys
    python cold_lq_replay.py --pull            # READ-ONLY RawTree -> data/lfm_*.parquet + data/coldlq_replay/*.parquet
    python cold_lq_replay.py [--mode cold|cold_new] [--n 4000] [--since "2026-11-14 14:00"] [--coef lfm_coef_r3.json] [--out file.json]

Replaces the replay of `cold_lq_slates.py` (PR #17), which applied events up to 15:00 to earlier requests and did not
replay stock or stale-item eligibility. Here every answered request is scored twice (control arm / arm with
"lq": "cold", same weights) with the state the writer could have had at that instant:

  * catalogue: `shop.catalog` + every `shop.catalog_updates` row with ts <= request ts -> product existence, price,
    is_active and stock (out_of_stock / back_in_stock), with the writer's own rules (refresh_catalog + stock_refresher);
  * organic evidence for the corrections: per-product views/purchases of the 10-minute buckets that had CLOSED before
    the request (the writer has up to ~20 s fresher data: this is conservative, never from the future);
  * shopper state: lfm_build.state_asof / mix_asof / aff_asof (history + today's events strictly before the request);
  * eligibility: bought, stale-history and unavailable products excluded exactly as LiveFit.scores/slate do.

Requests sharing the same (last catalogue update, closed bucket) share one snapshot, so the replay is exact per request
at that resolution. Not reconstructed (flagged in the output): purchases made through OUR carousel (only organic
`shop.events` purchases are in the offline state; brief C2), the writer's 20 s refresh lag and 1 s stock lag, and the
product-to-product graph (the replayed weights have cv = 0 unless --coef says otherwise).
Never present these numbers as uplift: the hidden model decides, on the leaderboard.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "data" / "coldlq_replay"


def pull():
    import lfm_build as LB
    from rt import q
    LB.pull()
    OUT.mkdir(parents=True, exist_ok=True)
    q("""SELECT product_id::String product_id, ts::DateTime64(3)::String ts, change::String change, category::String category,
        subcategory::String sub, brand::String brand, price_eur::Float64 price, is_active::Bool active, description::String description
        FROM shop.catalog_updates""").to_parquet(OUT / "updates.parquet")
    q("""SELECT product_id::String product_id, category::String category, subcategory::String sub, brand::String brand,
        price_eur::Float64 price, is_active::Bool active FROM shop.catalog""").to_parquet(OUT / "base.parquet")
    q("""SELECT product_id::String i, toStartOfTenMinutes(ts::DateTime64(3))::String b, countIf(event_type::String='view') v,
        countIf(event_type::String='purchase') p FROM shop.events WHERE ts::DateTime64(3) < toStartOfTenMinutes(now()) GROUP BY i, b""").to_parquet(OUT / "item10.parquet")


class Catalogue:
    """State of the catalogue as of any instant, from the base table plus the timestamped update log."""

    def __init__(self):
        self.base = pd.read_parquet(OUT / "base.parquet").set_index("product_id")
        u = pd.read_parquet(OUT / "updates.parquet"); u["ts"] = pd.to_datetime(u.ts)
        self.upd = u.sort_values("ts", kind="stable").reset_index(drop=True)
        self.times = np.sort(self.upd.ts.unique())

    def version(self, ts):
        k = int(np.searchsorted(self.times, np.datetime64(ts), side="right"))
        return self.times[k - 1] if k else None

    def asof(self, version):
        """-> (cat frame like the writer's, unavailable set, {new product: description})."""
        u = self.upd[self.upd.ts <= version] if version is not None else self.upd.iloc[:0]
        last = u.groupby("product_id").tail(1).set_index("product_id")
        cat = self.base[["category", "sub", "brand", "price", "active"]].copy(); cat["last_change"] = ""
        new = last.index.difference(cat.index)
        cat = pd.concat([cat, last.loc[new, ["category", "sub", "brand", "price", "active"]].assign(last_change="")])
        cat.loc[last.index, ["category", "sub", "brand", "price", "active"]] = last[["category", "sub", "brand", "price", "active"]]
        cat.loc[last.index, "last_change"] = last.change
        unavail = set(cat.index[(~cat.active.astype(bool)) | (cat.last_change == "out_of_stock")])
        st = u[u.change.isin(("out_of_stock", "back_in_stock"))].groupby("product_id").tail(1)
        unavail |= set(st.product_id[st.change == "out_of_stock"])
        npd = u[u.change == "new_product"].groupby("product_id").tail(1)
        return cat, unavail, dict(zip(npd.product_id, npd.description))


class AffAsOf:
    """AttrAffinity stand-in whose affinity_all only sees today's views before `ts` (lfm_build.aff_asof)."""

    def __init__(self, aff): self.aff, self.ts = aff, None
    def affinity_all(self, u, rv=()):
        import lfm_build as LB
        return LB.aff_asof(self.aff, u, rv, self.ts)


def main(n=4000, since="2026-11-14 14:00:00", coef="lfm_coef_r3.json", out=None, mode="cold"):
    import time, cold_lq_arm, lfm, lfm_build as LB, qrank
    d, LF, aff, carts, buys = LB.load()
    LF.lq0 = float(json.loads((HERE / coef).read_text()).get("lq0", LF.lq0))
    LF.set_arms([{"tag": "ctl", "file": coef}, {"tag": "trt", "file": coef, "lq": mode}])
    hc = LF.snap.hc
    d = d[d.ts >= pd.Timestamp(since)]
    step = max(1, len(d) // n); d = d.iloc[::step]
    C = Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib"); COR = cold_lq_arm.Corrector()
    it = pd.read_parquet(OUT / "item10.parquet"); it["end"] = pd.to_datetime(it.b) + pd.Timedelta(minutes=10)
    hist = pd.read_parquet(HERE / "data" / "user_item_all.parquet", columns=["i", "v", "p"]).groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
    shim = AffAsOf(aff)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    stats = collections.defaultdict(collections.Counter); diag = []; home_changed = 0
    ms = {"ctl": [], "trt": [], "corrections": [], "set_catalog": []}
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        QR.set_catalog(cat, unavail)
        live_item = it[it.end <= bucket].groupby("i")[["v", "p"]].sum().rename(columns={"v": "it_v", "p": "it_p"})
        t0 = time.perf_counter(); corr = COR.corrections(QR.q, QR.lq, cat, hist, live_item, desc, lq0=LF.lq0); t1 = time.perf_counter()
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, lq_cold=corr or None)
        ms["corrections"].append(1000 * (t1 - t0)); ms["set_catalog"].append(1000 * (time.perf_counter() - t1))
        new = set(desc)
        dl = np.array([corr[p] - QR.lq[p] for p in corr]) if corr else np.zeros(0)
        diag.append(dict(bucket=str(bucket), requests=len(g), new_products=len(new), unavailable=len(unavail), corrected=len(corr),
                         clipped=int(COR.last["clipped"]), rejected=int(COR.last["rejected"]),
                         delta_lq_mean=round(float(dl.mean()), 3) if len(dl) else None, delta_lq_up=int((dl > 0).sum())))
        for r in g.itertuples():
            shim.ts = r.ts
            st = LB.state_asof(LF, carts, buys, r.user_id, r.ts) + (LB.mix_asof(LF, aff, r.user_id, r.ts),)
            req = dict(user_id=r.user_id, rv=r.rv, page=r.page or "product", is_new_user=bool(r.new_user), device=r.device, region=r.region)
            t0 = time.perf_counter(); a = LF.slate(req, st, shim, exclude=unavail, model="ctl") or []
            t1 = time.perf_counter(); b = LF.slate(req, st, shim, exclude=unavail, model="trt") or []
            ms["ctl"].append(1000 * (t1 - t0)); ms["trt"].append(1000 * (time.perf_counter() - t1))
            home = not r.rv or req["page"] not in ("product", "category")
            target = lfm.lq_target(mode, bool(r.new_user), req["page"], r.rv)
            home_changed += (not target) and a != b
            seg = ("new" if r.new_user else "known") + "/" + ("home_or_no_views" if home else req["page"])
            keys = [seg, "all", "target_cohort" if target else "untargeted"]
            if r.new_user and not home:          # little session evidence: one recent view and nothing else known about the shopper
                thin = len(r.rv) == 1 and not st[1] and not st[2] and not st[3]
                keys.append("new/with_views/" + ("thin_evidence" if thin else "more_evidence"))
            for key in keys:
                c = stats[key]; c["requests"] += 1; c["changed"] += a != b; c["slot1_changed"] += a[:1] != b[:1]
                for name, s in (("ctl", a), ("trt", b)):
                    ok = len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & st[0]) and all(p in cat.index for p in s)
                    c[name + "_valid"] += ok; c[name + "_imp"] += len(s); c[name + "_new"] += sum(p in new for p in s)
                    c[name + "_with_new"] += any(p in new for p in s); c[name + "_slot1_new"] += bool(s) and s[0] in new
    seg_out = {}
    for key, c in sorted(stats.items()):
        n_ = max(1, c["requests"]); row = dict(requests=c["requests"], slates_changed_pct=round(100 * c["changed"] / n_, 1), slot1_changed_pct=round(100 * c["slot1_changed"] / n_, 1))
        for name in ("ctl", "trt"):
            row[name] = dict(valid_pct=round(100 * c[name + "_valid"] / n_, 2), new_share_pct=round(100 * c[name + "_new"] / max(1, c[name + "_imp"]), 2),
                             slates_with_new_pct=round(100 * c[name + "_with_new"] / n_, 1), slot1_new_pct=round(100 * c[name + "_slot1_new"] / n_, 1))
        seg_out[key] = row
    pct = lambda v, q: round(float(np.percentile(v, q)), 2) if len(v) else None
    res = dict(kind="diagnostics only: exposure and validity, NOT conversion", coef=coef, mode=mode, since=since, requests=int(len(d)),
               first=str(d.ts.min()), last=str(d.ts.max()), snapshots=len(diag), untargeted_slates_changed=int(home_changed),
               latency_ms_cloud_container={k: dict(p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99), n=len(v)) for k, v in ms.items()},
               segments=seg_out, snapshots_first_last=[diag[0], diag[-1]] if diag else [],
               corrected_max=max((x["corrected"] for x in diag), default=0), clipped_max=max((x["clipped"] for x in diag), default=0),
               not_reconstructed=["carousel purchases in the bought set (organic purchases only; brief C2)",
                                  "writer refresh lag (20 s catalogue/events, 1 s stock)", "10-minute resolution of organic evidence (closed buckets only)"])
    print(json.dumps(res, indent=1))
    if out: Path(out).write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pull", action="store_true"); ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--since", default="2026-11-14 14:00:00"); ap.add_argument("--coef", default="lfm_coef_r3.json"); ap.add_argument("--out")
    ap.add_argument("--mode", default="cold", choices=("cold", "cold_new"))
    a = ap.parse_args()
    if a.pull: pull()
    main(a.n, a.since, a.coef, a.out, a.mode)
