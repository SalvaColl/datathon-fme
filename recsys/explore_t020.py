"""T-020: cheap offline checks of new ideas on our own live feedback (read-only; writes nothing to RawTree).

    python lfm_build.py --pull --no-write      # caches data/lfm_*.parquet
    python explore_t020.py --pull              # adds today's views / cart / purchase events, then runs the checks
    python explore_t020.py

Checks (all features use only events BEFORE each request):
  A  cart recency: does a product carted today sell more when the cart is fresh?
  B  "viewed earlier today but not in recent_views and never carted": alive or dead?
  C  shoppers who already bought today: how do they convert afterwards?
  D  do A/B add anything to the lfm model? time-split hold-out, same split as lfm_build.
"""
import sys, json
import numpy as np, pandas as pd
import lfm, lfm_build
from lfm_build import DATA

def pull():
    from rt import q
    v = pd.concat([q(f"""SELECT user_id::String u, product_id::String i, min(ts::DateTime64(3))::String t0, toUInt32(count()) n
        FROM shop.events WHERE event_type::String='view' AND cityHash64(user_id::String)%6={m} GROUP BY u,i""") for m in range(6)])
    v.to_parquet(DATA / "t020_views.parquet")
    q("""SELECT user_id::String u, product_id::String i, ts::String ts, event_type::String e FROM shop.events
        WHERE event_type::String IN ('add_to_cart','purchase')""").to_parquet(DATA / "t020_cp.parquet")
    q("""SELECT request_id::String request_id, context.device::String dev, context.region::String reg FROM shop.requests
        WHERE ts::DateTime64(3) >= toDateTime64('2026-11-14 11:00:00',3)""").to_parquet(DATA / "t020_ctx.parquet")

def rate(g):
    return pd.Series(dict(imps=len(g), clicks=int(g.clk.sum()), buys=int(g.buy.sum()), exp_buys=round(g.p.sum(), 1),
                          buy_per_10k=round(1e4 * g.buy.mean(), 1), obs_over_exp=round(g.buy.sum() / max(g.p.sum(), 1e-9), 2),
                          clk_obs_over_exp=round(g.clk.sum() / max(g.pc.sum(), 1e-9), 2)))

def main():
    if "--pull" in sys.argv: pull()
    d, LF, aff, carts, buys = lfm_build.load()
    I = lfm_build.impressions(d, LF, aff, carts, buys)
    views = pd.read_parquet(DATA / "t020_views.parquet"); views["t0"] = pd.to_datetime(views.t0)
    vt = {(u, i): t for u, i, t in zip(views.u.values, views.i.values, views.t0.values)}
    cp = pd.read_parquet(DATA / "t020_cp.parquet"); cp["ts"] = pd.to_datetime(cp.ts)
    lastcart = {}; ubuy = {}
    for u, i, t, e in zip(cp.u.values, cp.i.values, cp.ts.values, cp.e.values):
        if e == "add_to_cart": lastcart.setdefault((u, i), []).append(t)
        else: ubuy.setdefault(u, []).append(t)
    extra = []
    for r in d.itertuples():
        ts = np.datetime64(r.ts); rv = set(r.rv)
        nb = sum(1 for t in ubuy.get(r.user_id, ()) if t < ts)
        for p in r.shown:
            cs = [t for t in lastcart.get((r.user_id, p), ()) if t < ts]
            age = (ts - max(cs)) / np.timedelta64(1, "m") if cs else np.nan
            t0 = vt.get((r.user_id, p))
            extra.append((age, len(cs), int(t0 is not None and t0 < ts and p not in rv), nb))
    E = pd.DataFrame(extra, columns=["cart_age", "ncart", "vtoday", "nbought"]); I = pd.concat([I.reset_index(drop=True), E], axis=1)
    I["seg"] = np.where(I.new_user, "new", "known"); A = I[I.dead == 0].copy()
    coef = lfm_build.fit(A.assign(dead=0))
    A["p"] = 0.0; A["pc"] = 0.0
    for seg in ("known", "new"):
        m = A.seg == seg; c = coef[seg]
        A.loc[m, "p"] = lfm_build.p_buy(coef, seg, A.loc[m, lfm.FEATS].values, A.loc[m, "slot"].values)
        z = A.loc[m, lfm.FEATS].values @ np.array([c["w"][f] for f in lfm.FEATS]) + c["b"] + c["slot"] * np.log(A.loc[m, "slot"].values)
        A.loc[m, "pc"] = 1 / (1 + np.exp(-z))
    A["pc"] *= A.clk.sum() / A.pc.sum()
    print(len(d), "requests", d.ts.min(), "..", d.ts.max(), "|", len(A), "live impressions,", int(A.buy.sum()), "buys,", int(A.clk.sum()), "clicks")
    pd.set_option("display.width", 200)

    print("\n== A. carted today (not bought): by minutes since the last cart ==")
    C = A[A.cl == 1].copy(); C["age"] = pd.cut(C.cart_age, [0, 10, 30, 60, 1e9], labels=["<10m", "10-30m", "30-60m", ">60m"])
    print(C.groupby(["seg", "age"], observed=True).apply(rate).to_string())
    print("by slot group:"); C["sg"] = pd.cut(C.slot, [0, 1, 3, 10], labels=["1", "2-3", "4-10"])
    print(C.groupby(["seg", "sg"], observed=True).apply(rate).to_string())
    print("carted more than once today:"); print(C.groupby(["seg", C.ncart.clip(upper=2)]).apply(rate).to_string())

    print("\n== B. viewed earlier today, not in recent_views, never carted ==")
    B = A[(A.cl == 0) & (A.chn == 0) & (A.islast == 0) & (A.oinrv == 0)]
    print(B.groupby(["seg", "vtoday"]).apply(rate).to_string())
    print("for reference, in recent_views (not last):"); print(A[(A.oinrv == 1) & (A.cl == 0)].groupby("seg").apply(rate).to_string())

    print("\n== C. requests by purchases already made today (request level, all impressions incl. dead) ==")
    R = I.groupby("rid").agg(buy=("buy", "max"), clk=("clk", "max"), nb=("nbought", "first"), seg=("seg", "first"), page=("page", "first"))
    R["nbg"] = R.nb.clip(upper=3); R["home"] = R.page == "home"
    print(R[~R.home].groupby(["seg", "nbg"]).agg(requests=("buy", "size"), buys=("buy", "sum"), conv_pct=("buy", lambda s: round(100 * s.mean(), 2)), ctr_pct=("clk", lambda s: round(100 * s.mean(), 2))).to_string())
    print("same, live impressions only, observed / lfm-expected:"); A["nbg"] = A.nbought.clip(upper=3)
    print(A[A.home == 0].groupby(["seg", "nbg"]).apply(rate).to_string())

    print("\n== D. time-split hold-out: lfm features vs lfm + [cart freshness, viewed today, bought today] ==")
    from sklearn.linear_model import LogisticRegression
    A["fresh"] = ((A.cl == 1) & (A.cart_age < 30)).astype(float); A["cart2"] = ((A.cl == 1) & (A.ncart >= 2)).astype(float)
    A["vt"] = ((A.vtoday == 1) & (A.cl == 0) & (A.chn == 0)).astype(float); A["nb1"] = (A.nbought > 0).astype(float)
    cut = d.ts.quantile(0.7)
    def ll(y, p, w=None): p = np.clip(p, 1e-9, 1 - 1e-9); v = y * np.log(p) + (1 - y) * np.log(1 - p); return float(v.sum())
    for seg in ("known", "new"):
        a = A[A.seg == seg]; tr = a[a.ts < cut]; te = a[a.ts >= cut]
        for name, cols in (("lfm", lfm.FEATS), ("+fresh,cart2", lfm.FEATS + ["fresh", "cart2"]), ("+vt", lfm.FEATS + ["vt"]),
                           ("+nb1", lfm.FEATS + ["nb1"]), ("+all", lfm.FEATS + ["fresh", "cart2", "vt", "nb1"])):
            cols = cols + ["ls"]
            m = LogisticRegression(C=10.0, max_iter=5000).fit(tr[cols], tr.clk, sample_weight=np.where(tr.buy == 1, 3.0, 1.0))
            p = m.predict_proba(te[cols])[:, 1]
            g = te.assign(s=p - m.coef_[0][-1] * 0)       # rank within request by score incl. slot (same for all variants)
            from sklearn.metrics import roc_auc_score
            print(f"{seg:5s} {name:14s} test imps {len(te)} clicks {int(te.clk.sum())} buys {int(te.buy.sum())} | click loglik {ll(te.clk.values, p):9.1f} | "
                  f"AUC click {roc_auc_score(te.clk, p):.4f} buy {roc_auc_score(te.buy, p):.4f} | extra weights {dict(zip(cols[len(lfm.FEATS):-1], m.coef_[0][len(lfm.FEATS):-1].round(2)))}")

if __name__ == "__main__":
    main()
