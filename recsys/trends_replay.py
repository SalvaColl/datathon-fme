"""Offline replay of live trends (T-008, E-010). READ-ONLY: only SELECTs, never writes submissions.

    python trends_replay.py --pull     # download today's aggregates to data/tr_*.parquet, then evaluate
    python trends_replay.py            # evaluate on cached files

Question: does the lift of the last 15 min (vs the previous 3 h) predict what is bought in the NEXT 15 min
better than static popularity? We walk through the day in 5-minute steps; at each step `t` we call the same
`trends.compute()` the server would call, using only events before `t`, and compare with what happened in
[t, t+15 min). Strict time order, no future data in any feature.

Bias notes: targets are ORGANIC purchases, not carousel purchases. They show where demand moves, not the
hidden P(buy | shown in carousel). Part C is the closest carousel proxy we can build without writing.
"""
import sys, json
import numpy as np, pandas as pd
import trends

pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200)
FUT = 3  # future window = 3 buckets = 15 min


def pull():
    from rt import q
    L = q("""SELECT toStartOfInterval(ts::DateTime64(3), INTERVAL 5 MINUTE)::String b, product_id::String i,
      toUInt32(countIf(event_type::String='view')) v, toUInt32(countIf(event_type::String='add_to_cart')) a,
      toUInt32(countIf(event_type::String='purchase')) p FROM shop.events GROUP BY b, i""")
    L.to_parquet("data/tr_live5.parquet")
    cat = q("""SELECT product_id::String i, argMax(subcategory::String, v) sub, argMax(category::String, v) category FROM (
      SELECT product_id, subcategory, category, '' v FROM shop.catalog UNION ALL
      SELECT product_id, subcategory, category, toString(ts) v FROM shop.catalog_updates) GROUP BY i""")
    cat.to_parquet("data/tr_cat.parquet")
    pu = q("SELECT ts::String ts, user_id::String u, product_id::String i FROM shop.events WHERE event_type::String='purchase'")
    pu.to_parquet("data/tr_purch.parquet")
    rq = pd.concat([q(f"""SELECT request_id::String rid, ts::String ts, user_id::String u, context.page::String page,
      arrayMap(x -> x.product_id::String, recent_views::Array(Dynamic)) rv FROM shop.requests
      WHERE cityHash64(request_id::String) % 4 = {k}""") for k in range(4)])
    rq.to_parquet("data/tr_req.parquet")
    print("pulled", len(L), "bucket rows,", len(pu), "purchases,", len(rq), "requests")


def dev(y, mu):
    """Poisson deviance."""
    y, mu = np.asarray(y, float), np.maximum(np.asarray(mu, float), 1e-9)
    return 2 * np.sum(np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / mu), 0) - (y - mu))


def replay(L, sub_of, recent=trends.RECENT):
    bs = sorted(L.b.unique())[:-1]  # drop the last (partial) bucket
    idx = {b: k for k, b in enumerate(bs)}
    L = L[L.b.isin(idx)].assign(k=lambda d: d.b.map(idx), sub=lambda d: d.i.map(sub_of)).dropna(subset=["sub"])
    rows, prows, snaps = [], [], {}
    for t in range(recent + trends.MIN_BASE, len(bs) - FUT + 1):
        past = L[L.k < t]
        s = trends.compute(past.assign(age=t - 1 - past.k)[["age", "i", "v", "a", "p"]], sub_of, recent=recent)
        snaps[bs[t]] = s
        fut = L[(L.k >= t) & (L.k < t + FUT)]
        old = past[past.k < t - recent]                       # static popularity: everything before the recent window
        d = pd.DataFrame({"vf": fut.groupby("sub").v.sum(), "pf": fut.groupby("sub").p.sum(),
                          "vb": old.groupby("sub").v.sum(), "pb": old.groupby("sub").p.sum()}).fillna(0)
        d["lift"] = pd.Series(s.sub_lift).reindex(d.index).fillna(1.0); d["z"] = pd.Series(s.sub_z).reindex(d.index).fillna(0.0)
        d["hot"] = d.index.isin(s.hot); d["t"] = bs[t]
        rows.append(d.reset_index())
        dp = pd.DataFrame({"pf": fut.groupby("i").p.sum(), "pb": old.groupby("i").p.sum(), "vb": old.groupby("i").v.sum()}).fillna(0)
        dp["sub"] = dp.index.map(sub_of); dp["pl"] = pd.Series(s.prod_lift).reindex(dp.index).fillna(1.0); dp["t"] = bs[t]
        dp["hot"] = dp["sub"].isin(s.hot)
        prows.append(dp.reset_index())
    return pd.concat(rows), pd.concat(prows), snaps, bs


def part_a(S):
    print(f"\n=== A. Subcategory level: {S.t.nunique()} replay steps x {S['sub'].nunique()} subcategories = {len(S)} rows ===")
    S = S.copy()
    S["e_v"] = S.vb / S.groupby("t").vb.transform("sum") * S.groupby("t").vf.transform("sum")   # expected future views, static share
    S["e_p"] = (S.pb + 0.5) / (S.groupby("t").pb.transform("sum") + 0.5 * S["sub"].nunique()) * S.groupby("t").pf.transform("sum")
    g = S.groupby("hot").agg(rows=("vf", "size"), vf=("vf", "sum"), e_v=("e_v", "sum"), pf=("pf", "sum"), e_p=("e_p", "sum"), vb=("vb", "sum"), pb=("pb", "sum"))
    g["future_views/expected"] = g.vf / g.e_v; g["future_purchases/expected"] = g.pf / g.e_p
    g["cr_future/cr_before"] = (g.pf / g.vf) / (g.pb / g.vb)
    print("When flagged hot at t, what happens in the next 15 min (organic):")
    print(g[["rows", "vf", "pf", "future_views/expected", "future_purchases/expected", "cr_future/cr_before"]].round(2).to_string())
    print("hot episodes:", S[S.hot].groupby("sub").t.agg(["min", "max", "size"]).to_string())
    print("\nPoisson deviance of next-15-min purchases per subcategory (lower = better):")
    half = S.t < sorted(S.t.unique())[S.t.nunique() // 2]
    res = []
    for name, mult in [("static popularity", np.ones(len(S))),
                       ("x hot multiplier alpha=0.5 cap 3 (default)", np.where(S.hot, np.clip(S.lift, 1, 3) ** 0.5, 1)),
                       ("x hot multiplier alpha=1 cap 5", np.where(S.hot, np.clip(S.lift, 1, 5), 1)),
                       ("x hot multiplier alpha=2 cap 5 (traffic x conversion)", np.where(S.hot, np.clip(S.lift, 1, 5) ** 2, 1)),
                       ("x raw lift, every subcategory (no hot gate)", S.lift.values)]:
        mu = S.e_p * mult; mu = mu * S.groupby("t").pf.transform("sum") / mu.groupby(S.t).transform("sum")  # renormalise per step
        res.append((name, dev(S.pf, mu), dev(S.pf[half], mu[half]), dev(S.pf[~half], mu[~half])))
    r = pd.DataFrame(res, columns=["model", "deviance", "first half", "second half"]).set_index("model")
    r["vs static %"] = 100 * (r.deviance / r.deviance.iloc[0] - 1)
    print(r.round(1).to_string())


def part_b(P):
    print("\n=== B. Product level inside a subcategory: does product lift add anything beyond the subcategory? ===")
    P = P.copy(); grp = [P.t, P["sub"]]
    P["e"] = (P.pb + 0.2) / (P.pb + 0.2).groupby(grp).transform("sum") * P.pf.groupby(grp).transform("sum")
    for name, m in [("all subcategories", np.ones(len(P), bool)), ("only while subcategory is hot", P.hot.values)]:
        Q = P[m]
        if not len(Q): continue
        mu2 = Q.e * Q.pl.clip(0.5, 3); den = mu2.groupby([Q.t, Q["sub"]]).transform("sum")
        mu2 = (mu2 * Q.pf.groupby([Q.t, Q["sub"]]).transform("sum") / den.where(den > 0, 1)).fillna(0)
        print(f"{name}: rows {len(Q)}, purchases {int(Q.pf.sum())}, deviance static-within-sub {dev(Q.pf, Q.e):.0f} vs x product lift {dev(Q.pf, mu2):.0f}")


def part_c(snaps, bs, sub_of, cat_of):
    print("\n=== C. Carousel-opportunity proxy: after a request, does the shopper buy (organically, next 10 min) from a hot subcategory? ===")
    rq = pd.read_parquet("data/tr_req.parquet"); pu = pd.read_parquet("data/tr_purch.parquet")
    rq["ts"] = pd.to_datetime(rq.ts); pu["ts"] = pd.to_datetime(pu.ts); pu["sub"] = pu.i.map(sub_of)
    ever_hot = sorted({s for sn in snaps.values() for s in sn.hot})
    hot_at = {pd.Timestamp(b): set(sn.hot) for b, sn in snaps.items()}
    rq["b"] = rq.ts.dt.floor("5min"); rq = rq[rq.b.isin(hot_at)]
    rows = []
    for s in ever_hot:
        c = next(cat_of[i] for i in sub_of if sub_of[i] == s)
        r = rq[["rid", "u", "ts", "page"]].copy()
        r["hot"] = [s in hot_at[b] for b in rq.b]
        r["rel"] = ["1 viewed that subcategory" if s in {sub_of.get(x) for x in v} else "2 viewed same category" if c in {cat_of.get(x) for x in v}
                    else "3 home / no views" if len(v) == 0 else "4 viewed another category" for v in rq.rv]
        p = pu[pu["sub"] == s][["u", "ts"]].rename(columns={"ts": "pts"})
        m = r.merge(p, on="u", how="left"); dt = (m.pts - m.ts).dt.total_seconds()
        m["buy"] = ((dt > 0) & (dt <= 600)).astype(int)
        r = r.merge(m.groupby("rid").buy.max().reset_index(), on="rid"); r["sub"] = s
        rows.append(r)
    R = pd.concat(rows)
    g = R.groupby(["rel", "hot"]).agg(requests=("buy", "size"), buyers=("buy", "sum")).unstack("hot").fillna(0)
    g.columns = [f"{a}_{'hot' if b else 'normal'}" for a, b in g.columns]
    g["rate_hot_%"] = 100 * g.buyers_hot / g.requests_hot; g["rate_normal_%"] = 100 * g.buyers_normal / g.requests_normal
    g["ratio"] = g["rate_hot_%"] / g["rate_normal_%"]
    print(f"subcategories ever flagged hot: {ever_hot}; rows are (request, subcategory) pairs"); print(g.round(3).to_string())
    nv = R[R.rel != "1 viewed that subcategory"].groupby("hot").buy.agg(["size", "sum"])
    try:
        from scipy.stats import fisher_exact
        tab = [[nv.loc[True, "sum"], nv.loc[True, "size"] - nv.loc[True, "sum"]], [nv.loc[False, "sum"], nv.loc[False, "size"] - nv.loc[False, "sum"]]]
        print("shoppers who had NOT viewed the subcategory: hot", tab[0], "normal", tab[1], "Fisher exact p = %.2g" % fisher_exact(tab)[1])
    except Exception as e: print("fisher skipped", e)


def part_d(L, sub_of):
    print("\n=== D. Window sensitivity: recent window 5 / 10 / 15 min ===")
    for rec in (1, 2, 3):
        S, _, _, _ = replay(L, sub_of, recent=rec)
        S = S.reset_index(drop=True)
        e_v = S.vb / S.groupby("t").vb.transform("sum") * S.groupby("t").vf.transform("sum")
        h = S[S.hot]; good = (h.vf / e_v[S.hot] > 2).mean() if len(h) else float("nan")
        print(f"recent={rec * 5} min: flagged rows {len(h)}, share where next-15-min views really > 2x expected: {good:.2f}")
        print(h.groupby("sub").t.agg(["min", "max", "size"]).to_string())


if __name__ == "__main__":
    if "--pull" in sys.argv: pull()
    L = pd.read_parquet("data/tr_live5.parquet"); cat = pd.read_parquet("data/tr_cat.parquet")
    sub_of = dict(zip(cat.i, cat["sub"])); cat_of = dict(zip(cat.i, cat.category))
    print("events", int(L[["v", "a", "p"]].sum().sum()), "from", L.b.min(), "to", L.b.max())
    S, P, snaps, bs = replay(L, sub_of)
    S = S.reset_index(drop=True); P = P.reset_index(drop=True)
    part_a(S); part_b(P); part_c(snaps, bs, sub_of, cat_of); part_d(L, sub_of)
