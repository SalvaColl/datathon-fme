"""Lab frame for T-046: one row per (answered request, shown product) with product type, context and as-of state. Read-only."""
import json, sys, glob
import numpy as np, pandas as pd
import lfm, lfm_build as LB
DATA = LB.DATA
def main():
    d, LF, aff, carts, buys = LB.load()
    S = LF.snap; catlog = aff.catlog
    r3 = json.loads((lfm.HERE / "lfm_coef_r3.json").read_text())
    W = {k: np.array([r3[k]["w"].get(f, 0.0) for f in lfm.FEATS]) for k in ("known", "new")}
    # raw events of today, per user, sorted
    ev = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(DATA / "lab/ev_*.parquet")))])
    ev["t"] = pd.to_datetime(ev.t); ev["k"] = ev.i.map(S.row).fillna(-1).astype(np.int64)
    ev = ev[ev.k >= 0].sort_values(["u", "t"], kind="stable")
    ucode, uniq = pd.factorize(ev.u); starts = np.r_[0, np.cumsum(np.bincount(ucode))]
    upos = {u: (starts[j], starts[j + 1]) for j, u in enumerate(uniq)}
    et = ev.t.values; ek = ev.k.values; ee = ev.e.values
    # item popularity per closed 10-min bucket
    it = pd.read_parquet(DATA / "coldlq_replay/item10.parquet"); it["b"] = pd.to_datetime(it.b); it["k"] = it.i.map(S.row)
    it = it.dropna(subset=["k"]); it["k"] = it.k.astype(int)
    b0 = it.b.min(); it["bi"] = ((it.b - b0) / pd.Timedelta(minutes=10)).astype(int); nb = it.bi.max() + 2
    PV = np.zeros((nb, S.n), dtype=np.float32); PP = np.zeros((nb, S.n), dtype=np.float32)
    PV[it.bi.values, it.k.values] = it.v.values; PP[it.bi.values, it.k.values] = it.p.values
    CV = np.cumsum(PV, axis=0); CP = np.cumsum(PP, axis=0)        # CV[b] = views in buckets 0..b
    launch = {}
    for t, k, pr, ac, ch in catlog.ev:
        if ch == "new_product" and k not in launch: launch[k] = t
    launch_t = np.full(S.n, np.datetime64("NaT"), dtype="datetime64[ns]")
    for k, t in launch.items(): launch_t[k] = t
    isnew = ~catlog.exists0
    rows = []; feats = []; reqs = []
    for r in d.itertuples():
        ts = np.datetime64(r.ts)
        b, lc, hc, bt, mix, mfu = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
        idx = [S.row.get(p, -1) for p in r.shown]; safe = np.array([k if k >= 0 else 0 for k in idx]); seg = lfm.in_segment(r.device, r.region)
        X = lfm.features(S, LB.aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, idx=safe, mix=mix, bought_today=bt, seg=seg, mfu=mfu)
        catlog.price_features(X, safe, r.ts, seg); _, unav, price = catlog.at(r.ts)
        stale = S.stale(r.user_id)
        # user's organic events today before ts
        tv = {}; tlast = {}; tcart = {}; nev = 0
        se = upos.get(r.user_id)
        if se:
            hi = se[0] + np.searchsorted(et[se[0]:se[1]], ts)
            for j in range(se[0], hi):
                k = ek[j]
                if ee[j] == "v": tv[k] = tv.get(k, 0) + 1; tlast[k] = et[j]
                elif ee[j] == "a": tcart[k] = et[j]
            nev = hi - se[0]
        tsub = {}; tcat = {}
        for k, n in tv.items(): tsub[S.sub[k]] = tsub.get(S.sub[k], 0) + n; tcat[S.cat[k]] = tcat.get(S.cat[k], 0) + n
        rvk = [S.row[p] for p in r.rv if p in S.row]; last = rvk[-1] if rvk else -1
        bi = int((ts - np.datetime64(b0)) / np.timedelta64(10, "m")) - 1     # last closed bucket
        lo = max(bi - 6, 0)
        seg_name = "new" if r.new_user else "known"
        z = X @ W[seg_name]
        cold_rv = any(isnew[k] for k in rvk)
        reqs.append((r.Index, len(rvk), last, len(lc), len(hc), len(bt), len(tv), nev, int(cold_rv), S.cat[last] if last >= 0 else -1, S.sub[last] if last >= 0 else -1,
                     price[last] if last >= 0 else np.nan, int(isnew[last]) if last >= 0 else 0))
        for s, (p, k) in enumerate(zip(r.shown, idx)):
            if k < 0: continue
            dead = p in b or (stale is not None and stale[k] and p not in hc and p not in lc)
            pv = CV[bi, k] - CV[lo, k] if bi > 0 else 0.0; pp = CP[bi, k] - CP[lo, k] if bi > 0 else 0.0
            ct = tcart.get(k)
            rows.append((r.Index, s + 1, k, int(p == r.clicked), int(p == r.purchased), int(dead), z[s], price[k], catlog.price0[k], int(isnew[k]),
                         (ts - launch_t[k]) / np.timedelta64(1, "m") if isnew[k] else np.nan, tv.get(k, 0),
                         (ts - tlast[k]) / np.timedelta64(1, "m") if k in tlast else np.nan, tsub.get(S.sub[k], 0), tcat.get(S.cat[k], 0),
                         (ts - ct) / np.timedelta64(1, "m") if ct is not None else np.nan, pv, pp, S.cat[k], S.sub[k], S.brand[k], S.lq[k],
                         int(k in rvk), rvk[::-1].index(k) if k in rvk else -1))
            feats.append(X[s])
    I = pd.DataFrame(rows, columns=["rid", "slot", "k", "clk", "buy", "dead", "z", "price", "price0", "isnew", "age_min", "tviews", "tlast_min", "tsub", "tcat",
                                    "tcart_min", "pop_v", "pop_p", "cat", "sub", "brand", "lqv", "inrv", "rvpos"])
    F = pd.DataFrame(np.array(feats, dtype=np.float32), columns=lfm.FEATS)
    I = pd.concat([I, F], axis=1)
    R = pd.DataFrame(reqs, columns=["rid", "nrv", "last", "n_lc", "n_hc", "n_bt", "n_tv", "n_ev", "cold_rv", "lcat", "lsub", "lprice", "lnew"]).set_index("rid")
    R = R.join(d[["request_id", "ts", "user_id", "new_user", "page", "device", "region", "mv", "served_by", "clicked", "purchased"]])
    I.to_parquet(DATA / "lab/I.parquet"); R.to_parquet(DATA / "lab/R.parquet")
    pd.DataFrame(dict(pid=S.ids, cat=S.cat, sub=S.sub, brand=S.brand, lq=S.lq, isnew=isnew, price0=catlog.price0)).to_parquet(DATA / "lab/P.parquet")
    print(len(R), "requests", len(I), "impressions", int(I.buy.sum()), "buys")
main()
