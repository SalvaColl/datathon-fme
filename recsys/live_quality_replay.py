"""Replay of live_quality on today's stream (T-018; E-180..E-183). Read-only.

    python live_quality_replay.py --pull     # download aggregates to data/lq/ (git-ignored), then run everything
    python live_quality_replay.py            # reuse the downloaded files

E-180  Every 15 minutes, with features from the PAST only, predict each product's purchases in the next 15 minutes
       given its views (Poisson log-likelihood). Baseline = static quality (60-day history shrunk to the attribute
       prior). Hyper-parameters are chosen on the first half of the day and reported on the second half.
E-181  Organic effect of a price discount (catalog_updates.price_change).
E-182  Can the organic rate predict the CAROUSEL quality q of a product that has no carousel history? Every old
       product is treated as if it were new: attribute prior fitted without it (5 folds) + its live events only.
E-183  Power check on our own carousel feedback: how many impressions did hot / new products get?
"""
from __future__ import annotations
import json, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
import cold_items, live_quality as LQM

D = LQM.DATA / "lq"
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)


def pull():
    from rt import q
    D.mkdir(parents=True, exist_ok=True)
    q("""SELECT toUInt32(intDiv(toUnixTimestamp(ts::DateTime64(3)), 300)) b, product_id::String i,
      toUInt32(countIf(event_type::String='view')) v, toUInt32(countIf(event_type::String='add_to_cart')) a,
      toUInt32(countIf(event_type::String='purchase')) p FROM shop.events GROUP BY b, i""").to_parquet(D / "ev5.parquet")
    q("""SELECT product_id::String i, toUInt32(countIf(event_type::String='view')) v, toUInt32(countIf(event_type::String='add_to_cart')) a,
      toUInt32(countIf(event_type::String='purchase')) p FROM shop.history_events GROUP BY i""").to_parquet(D / "hist.parquet")
    q("""SELECT product_id::String i, category::String category, subcategory::String sub, brand::String brand, price_eur::Float64 price,
      description::String description FROM shop.catalog""").to_parquet(D / "cat.parquet")
    q("""SELECT ts::DateTime64(3) ts, change::String change, product_id::String i, category::String category, subcategory::String sub,
      brand::String brand, price_eur::Float64 price, description::String description FROM shop.catalog_updates ORDER BY ts""").to_parquet(D / "upd.parquet")
    q("""SELECT request_id::String r, ts::DateTime64(3) ts, shown::Array(String) shown, served_by::String sb, purchased::String pur
      FROM team_26.feedback WHERE request_id::String != '__init__'""").to_parquet(D / "fb.parquet")


def load():
    ev = pd.read_parquet(D / "ev5.parquet"); h = pd.read_parquet(D / "hist.parquet").set_index("i")
    c = pd.read_parquet(D / "cat.parquet").set_index("i"); u = pd.read_parquet(D / "upd.parquet")
    u["ts"] = pd.to_datetime(u.ts); u["b"] = (u.ts - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=300)
    new = u[u.change == "new_product"].drop_duplicates("i").set_index("i")[["category", "sub", "brand", "price", "description"]]
    cat = pd.concat([c[["category", "sub", "brand", "price", "description"]], new])
    B = np.arange(ev.b.min(), ev.b.max())                 # the last bucket is partial: dropped
    mat = lambda col: ev.pivot_table(index="b", columns="i", values=col, aggfunc="sum").reindex(index=B, columns=cat.index).fillna(0).values
    pc = u[u.change == "price_change"].copy(); pc["ratio"] = pc.price / c.price.reindex(pc.i).values
    promo = pc.pivot_table(index="b", columns="i", values="ratio", aggfunc="last").reindex(index=B, columns=cat.index).ffill().fillna(1.0).values < LQM.PROMO_DISCOUNT
    return dict(ev=ev, h=h, c=c, u=u, cat=cat, B=B, V=mat("v"), P=mat("p"), promo=promo, isnew=~cat.index.isin(h.index))


def frame(v, p, idx): return pd.DataFrame({"v": v, "p": p}, index=idx)


def e180(d, H=3):
    cat, V, P, promo, isnew, h = d["cat"], d["V"], d["P"], d["promo"], d["isnew"], d["h"]
    I = cat.index; prior = LQM.default_prior()
    ll = lambda p, v, r: p * np.log(np.maximum(r, 1e-6) * np.maximum(v, 1e-9) + 1e-12) - np.maximum(r, 1e-6) * v
    static = LQM.LiveQuality(prior=prior).update(cat, h).rate.values
    recs = []
    for t in range(6, len(d["B"]) - H + 1, H):
        v, p = V[t:t + H].sum(0), P[t:t + H].sum(0)
        M = {"static": static, "static+promo": static * np.where(promo[t], LQM.PROMO_LIFT, 1.0)}
        cum = frame(V[:t].sum(0), P[:t].sum(0), I)
        for K in (30, 100, 300, 1000):
            M[f"product K={K}"] = LQM.LiveQuality(prior=prior, k_prod=K).update(cat, h, cum).rate.values
        hotmask = None
        for w in (3, 6, 12):
            win = frame(V[max(0, t - w):t].sum(0), P[max(0, t - w):t].sum(0), I)
            for K in (5, 20, 50):
                q = LQM.LiveQuality(prior=prior, k_sub=K).update(cat, h, None, win)
                M[f"sub gated w={w * 5}min K={K}"] = static * q.multiplier(I, promo=False)
                e = pd.DataFrame({"sub": cat["sub"].values, "e": win.v.values * static, "p": win.p.values}).groupby("sub").sum()
                M[f"sub ungated w={w * 5}min K={K}"] = static * ((e.p + K) / (e.e + K)).reindex(cat["sub"].values).values
                if (w, K) == (6, 20): hotmask = q.multiplier(I, promo=False) > 1
        full = LQM.LiveQuality(prior=prior).update(cat, h, cum, frame(V[max(0, t - 6):t].sum(0), P[max(0, t - 6):t].sum(0), I), promo=I[promo[t]])
        M["live_quality (module defaults)"] = full.live_rate(I)
        seg = {"all": np.ones(len(I), bool), "old, calm": ~isnew & ~hotmask & ~promo[t], "new products": isnew,
               "hot subcategory": hotmask, "discounted": promo[t]}
        for name, r in M.items():
            l = ll(p, v, r)
            for sg, m in seg.items(): recs.append((t, name, sg, l[m].sum(), p[m].sum(), v[m].sum(), (r * v)[m].sum()))
    R = pd.DataFrame(recs, columns=["t", "model", "seg", "ll", "p", "v", "exp"])
    R["half"] = np.where(R.t < R.t.median(), "tune", "test")
    base = R[R.model == "static"].set_index(["t", "seg"]).ll
    R["gain"] = R.ll - base.reindex(pd.MultiIndex.from_frame(R[["t", "seg"]])).values
    T = R.groupby(["half", "seg", "model"]).agg(gain=("gain", "sum"), p=("p", "sum"), v=("v", "sum"), exp=("exp", "sum")).reset_index()
    T["gain_per_1k"] = 1000 * T.gain / T.p; T["pred/obs"] = T["exp"] / T.p
    print("== E-180: next-15-min purchases given views, past-only features. Gain = log-likelihood vs static, nats per 1,000 purchases")
    for sg in ["all", "old, calm", "hot subcategory", "new products", "discounted"]:
        n = T[(T.seg == sg) & (T.model == "static")].set_index("half")
        a = T[T.seg == sg].pivot(index="model", columns="half", values="gain_per_1k")
        a["pred/obs test"] = T[(T.seg == sg) & (T.half == "test")].set_index("model")["pred/obs"]
        best = a.drop(index=["static", "live_quality (module defaults)"]).tune.idxmax()
        print(f"\n-- {sg}: purchases tune {int(n.p['tune'])} / test {int(n.p['test'])}, views test {int(n.v['test'])}; best on tune: {best}")
        print(a.loc[list(dict.fromkeys(["static", best, "product K=100", "sub gated w=30min K=20", "sub ungated w=30min K=20", "static+promo",
                                         "live_quality (module defaults)"]))].round(3).to_string())


def e181(d):
    ev, h, u, c = d["ev"], d["h"], d["u"], d["c"]
    pc = u[u.change == "price_change"].copy(); pc["ratio"] = pc.price / c.price.reindex(pc.i).values
    st = pc.pivot_table(index="b", columns="i", values="ratio", aggfunc="last").reindex(np.arange(ev.b.min(), ev.b.max() + 1)).ffill().fillna(1.0)
    e = ev[ev.i.isin(h.index)].copy()
    e["pr"] = st.stack().reindex(pd.MultiIndex.from_arrays([e.b, e.i])).fillna(1.0).values
    e["exp"] = (h.p / h.v).reindex(e.i).values * e.v
    e["state"] = np.where(e.pr < LQM.PROMO_DISCOUNT, "discounted now", np.where(e.i.isin(pc.i), "same products, full price", "never discounted"))
    g = e.groupby("state").agg(products=("i", "nunique"), views=("v", "sum"), purchases=("p", "sum"), expected=("exp", "sum"))
    g["obs/exp"] = g.purchases / g.expected; g["z"] = (g.purchases - g.expected) / np.sqrt(g.expected)
    print("\n== E-181: organic purchases vs what the same views give at the historical rate of each product")
    print(pc.groupby([pc.ts, pc.ratio.round(1)]).size().unstack(fill_value=0).to_string()); print(g.round(3).to_string())


def e182(d):
    import joblib
    cat, h, V, P = d["cat"], d["h"], d["V"], d["P"]
    q = pd.Series(joblib.load(LQM.DATA / "qrank.joblib")["q"])
    old = cat.loc[h.index].assign(v=h.v, a=h.a, p=h.p)
    lq = np.log(q.reindex(old.index)); ok = lq.notna().values
    s_full = np.log((old.p + 5) / (old.v + 100))
    w = lambda x: x - x.groupby(old["sub"]).transform("mean")
    print(f"\n== E-182: carousel quality q vs organic rate, {ok.sum()} historical products")
    print(f"   log q = a_sub + beta * log rate: beta {np.polyfit(w(s_full)[ok], w(lq)[ok], 1)[0]:.2f}, r {np.corrcoef(w(s_full)[ok], w(lq)[ok])[0, 1]:.3f} (within subcategory)")
    # pseudo-new: prior fitted on the other folds, plus only the first `hours` of live events
    rng = np.random.RandomState(0); fold = rng.randint(0, 5, len(old)); pr = np.zeros(len(old))
    for f in range(5):
        m = cold_items.ColdPrior().fit(old[fold != f]); pr[fold == f] = m.predict(old[fold == f]).cr.values
    pos = pd.Series(np.arange(len(cat)), index=cat.index).reindex(old.index).values
    rows = []
    for name, hours in [("subcategory median q (qrank today)", None), ("attribute prior only", 0), ("prior + 1 h of live events", 1),
                        ("prior + 2 h", 2), ("prior + 4 h", 4)]:
        res = []
        for f in range(5):
            te, tr = fold == f, (fold != f) & ok
            if hours is None:
                pred = lq[tr].groupby(old["sub"][tr]).median().reindex(old["sub"][te]).values
            else:
                v, p = V[:hours * 12].sum(0)[pos], P[:hours * 12].sum(0)[pos]
                rate = np.log((p + LQM.K_PROD * pr) / (v + LQM.K_PROD))
                a = (lq - LQM.BETA * s_full)[tr].groupby(old["sub"][tr]).median().reindex(old["sub"][te]).values
                pred = a + LQM.BETA * rate[te]
            res.append(pd.DataFrame({"pred": pred, "lq": lq[te].values, "sub": old["sub"][te].values, "cat": old.category[te].values}))
        r = pd.concat(res).dropna()
        wc = lambda col: r[col] - r.groupby("cat")[col].transform("mean")
        # ranking value: mean true q of the 10 products per category the predictor ranks highest, vs the true best 10
        top = r.sort_values("pred", ascending=False).groupby("cat").head(10); best = r.sort_values("lq", ascending=False).groupby("cat").head(10)
        rows.append((name, spearmanr(r.pred, r.lq)[0], spearmanr(wc("pred"), wc("lq"))[0], np.sqrt(((r.pred - r.lq) ** 2).mean()),
                     np.exp(top.lq).sum() / np.exp(best.lq).sum()))
    print("   every historical product treated as NEW (held out from the prior and from a_sub):")
    print(pd.DataFrame(rows, columns=["predictor of log q", "spearman", "spearman within category", "rmse log q", "top-10 q captured"]).round(3).to_string(index=False))
    # what it does to today's real new products
    I = cat.index; cum = frame(V.sum(0), P.sum(0), I)
    m = LQM.LiveQuality(prior=LQM.default_prior()).update(cat, h, cum, known=set(q.index))
    q2 = pd.Series(m.adjust_q(q.to_dict())); new = sorted(m.new)
    med = q.groupby(cat["sub"].reindex(q.index)).median().reindex(cat["sub"].reindex(new)).values
    rank = pd.concat([q2.rename("q"), cat.category], axis=1).groupby("category").q.rank(ascending=False)
    rank0 = pd.concat([pd.concat([q, pd.Series(med, index=new)]).rename("q"), cat.category], axis=1).groupby("category").q.rank(ascending=False)
    t = pd.DataFrame({"views": cum.v[new], "buys": cum.p[new], "rate": m.rate[new], "q_today(sub median)": med, "q_live": q2[new],
                      "rank_in_cat_today": rank0[new], "rank_in_cat_live": rank[new]})
    print(f"   {len(new)} real new products: in the category top-10 by q today {(t.rank_in_cat_today <= 10).sum()}, with live quality {(t.rank_in_cat_live <= 10).sum()}; "
          f"top-80 (qrank candidate pool) today {(t.rank_in_cat_today <= 80).sum()}, live {(t.rank_in_cat_live <= 80).sum()}")
    print(t.sort_values("q_live", ascending=False).head(8).round(5).to_string())
    print(f"   share of organic purchases that are new products: {cum.p[new].sum() / cum.p.sum():.3%}; "
          f"the 10 best new products: {t.sort_values('buys').buys.tail(10).sum() / cum.p.sum():.3%}")


def e183(d):
    fb = pd.read_parquet(D / "fb.parquet"); cat, V, P, h, B = d["cat"], d["V"], d["P"], d["h"], d["B"]
    fb["b"] = (pd.to_datetime(fb.ts) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=300)
    fb = fb[(fb.b <= B.max()) & (fb.b > B.min() + 6)]
    x = fb[["r", "b", "shown", "pur"]].explode("shown").rename(columns={"shown": "i"}); x = x[x.i.isin(cat.index)]
    x["y"] = x.pur == x.i; x["new"] = ~x.i.isin(h.index)
    static = LQM.LiveQuality(prior=LQM.default_prior()).update(cat, h)
    hot = {}
    for t in sorted(x.b.unique()):
        k = int(t - B[0]); win = frame(V[k - 6:k].sum(0), P[k - 6:k].sum(0), cat.index)
        hot[t] = set(LQM.LiveQuality(prior=lambda c: static.rate.values, k_prod=1e9).update(cat, None, None, win).hot)
    x["hot"] = [cat["sub"].get(i) in hot[b] for i, b in zip(x.i, x.b)]
    g = x.groupby(["new", "hot"]).agg(impressions=("y", "size"), purchases=("y", "sum"))
    g["per 10k"] = 1e4 * g.purchases / g.impressions
    print(f"\n== E-183: our carousel feedback ({fb.r.nunique()} requests): impressions by product type"); print(g.round(1).to_string())


if __name__ == "__main__":
    if "--pull" in sys.argv: pull()
    d = load()
    print(f"live events: {int(d['V'].sum())} views, {int(d['P'].sum())} purchases, {len(d['B'])} buckets of 5 min, "
          f"{d['isnew'].sum()} new products, {int(d['promo'].any(0).sum())} products discounted at some point")
    e180(d); e181(d); e182(d); e183(d)
