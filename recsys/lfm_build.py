"""Fit and validate lfm (live-fitted model) on our own carousel feedback. Read-only on RawTree; writes lfm_coef.json.

    python lfm_build.py --pull          # download feedback/requests/events/catalog to data/lfm_*.parquet, then fit
    python lfm_build.py                 # refit from the cached files
    python lfm_build.py --cut "2026-11-14 13:10"    # time split used for the hold-out report (default: last 30%)

What it does
  1. Replays every answered request: for each of the 10 products shown it rebuilds, AS OF the request time, the
     same features lfm.py computes when serving (lfm.features is shared, so training and serving cannot differ).
  2. Fits one logistic model for returning shoppers and one for new shoppers. Label = clicked, purchases weighted x3
     (a purchase is always a click; clicks are 3.3x more frequent, which halves the noise). Slot enters as log(slot)
     during the fit and is dropped when serving (the best product goes first).
  3. Hold-out report (fit on requests before --cut, test after): AUC, calibration by segment, and the model's
     estimate of expected purchases per 100 requests for the slates we actually showed vs the slates lfm would show.
  4. Refits on everything and writes lfm_coef.json.

The "would show" number is a MODEL estimate (the model grading its own choice, so it is optimistic). The real test
is the leaderboard's per-model_version row: the hidden model's expected conversion, readable ~15 min after switching.
"""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
import cold_items, attr_affinity, home_cands, lfm

warnings.filterwarnings("ignore")
DATA = Path(__file__).resolve().parent / "data"
BUY_W, C_REG = 3.0, 10.0


def pull():
    from rt import q
    team = __import__("os").environ.get("TEAM_ID", "team_26")
    fb = q(f"""SELECT request_id::String request_id, toJSONString(shown) shown, served_by::String served_by,
        clicked::String clicked, purchased::String purchased FROM {team}.feedback WHERE request_id::String != '__init__'""")
    t0 = q(f"SELECT min(ts::DateTime64(3))::String t FROM {team}.feedback WHERE request_id::String != '__init__'").t[0]
    rq = q(f"""SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user::Bool new_user,
        context.page::String page, toJSONString(recent_views) rv FROM shop.requests
        WHERE ts::DateTime64(3) >= toDateTime64('{t0[:19]}',3) - INTERVAL 10 MINUTE""")
    sb = q(f"SELECT request_id::String request_id, any(model_version::String) mv FROM {team}.submissions GROUP BY request_id")
    fb.merge(rq, on="request_id").merge(sb, on="request_id", how="left").to_parquet(DATA / "lfm_fb.parquet")
    ev = pd.concat([q(f"""SELECT user_id::String u, product_id::String i, event_type::String e, min(ts::DateTime64(3))::String t0
        FROM shop.events WHERE event_type::String IN ('add_to_cart','purchase') AND cityHash64(user_id::String)%2={m} GROUP BY u,i,e""") for m in range(2)])
    ev.to_parquet(DATA / "lfm_ev.parquet")
    q("""SELECT product_id::String product_id, argMax(category::String,v) category, argMax(subcategory::String,v) sub,
        argMax(brand::String,v) brand, argMax(price_eur::Float64,v) price, argMax(description::String,v) description
        FROM (SELECT product_id, category, subcategory, brand, price_eur, description, '' v FROM shop.catalog
              UNION ALL SELECT product_id, category, subcategory, brand, price_eur, description, toString(ts) FROM shop.catalog_updates)
        GROUP BY product_id""").to_parquet(DATA / "lfm_cat.parquet")
    print("pulled", len(fb), "feedback rows,", len(ev), "cart/purchase rows", flush=True)


def load():
    """-> (requests frame, LiveFit with history, Snap, AttrAffinity, events-as-of lookups)."""
    d = pd.read_parquet(DATA / "lfm_fb.parquet")
    d["shown"] = d.shown.map(json.loads)
    d["rv"] = d.rv.map(lambda s: [x["product_id"] for x in json.loads(s)] if s else [])
    d["ts"] = pd.to_datetime(d.ts); d = d.sort_values("ts").reset_index(drop=True)
    cat = pd.read_parquet(DATA / "lfm_cat.parquet").set_index("product_id")
    hist = pd.read_parquet(DATA / "user_item_all.parquet")
    cold = cold_items.ColdStart()
    for p, desc in cat.description.items():                       # new products: read their phrases from the description
        if p not in cold.attr: cold.attr[p] = cold_items.attrs(desc)
    aff = attr_affinity.AttrAffinity(cold, ui_path=DATA / "user_item_all.parquet")
    try:
        import joblib; lq = {k: float(np.log(max(v, 1e-6))) for k, v in joblib.load(DATA / "qrank.joblib")["q"].items()}
    except Exception as e:
        print("qrank.joblib not readable, lq = 0:", type(e).__name__); lq = {}
    lq0 = float(np.median(list(lq.values()))) if lq else 0.0
    sub_med = pd.Series(lq).reindex(cat.index).groupby(cat["sub"]).transform("median")     # new products: subcategory median, as qrank does
    lq = {p: (lq[p] if p in lq else (float(sub_med[p]) if pd.notna(sub_med[p]) else lq0)) for p in cat.index}
    hc = home_cands.HomeCands(hist, cat)
    LF = lfm.LiveFit({k: dict(w={f: 0.0 for f in lfm.FEATS}, b=0.0) for k in ("known", "new")} | {"lq0": lq0}, hist)
    LF.set_catalog(cat, set(), aff, lq, hc)
    ev = pd.read_parquet(DATA / "lfm_ev.parquet"); ev["t0"] = pd.to_datetime(ev.t0)
    carts, buys = {}, {}
    for u, i, e, t in zip(ev.u.values, ev.i.values, ev.e.values, ev.t0.values):
        (carts if e == "add_to_cart" else buys).setdefault(u, {})[i] = t
    return d, LF, aff, carts, buys


def state_asof(LF, carts, buys, u, ts):
    """Same triple as LiveFit.user_state, using only events before the request."""
    ts = np.datetime64(ts)
    b = {i for i, t in buys.get(u, {}).items() if t < ts} | LF.hbought.get(u, set())
    lc = {i for i, t in carts.get(u, {}).items() if t < ts} - b
    hc = {i: a for i, a in (LF.hcart.get(u) or {}).items() if i not in b and i not in lc}
    return b, lc, hc


def impressions(d, LF, aff, carts, buys):
    """One row per (request, shown product): features, slot, labels, dead flag."""
    S = LF.snap; rows = []; meta = []
    for r in d.itertuples():
        st = state_asof(LF, carts, buys, r.user_id, r.ts); b, lc, hc = st
        idx = [S.row.get(p, -1) for p in r.shown]
        X = lfm.features(S, aff.affinity_all(r.user_id, r.rv), r.rv, r.page, hc, lc, idx=[k if k >= 0 else 0 for k in idx])
        stale = S.stale(r.user_id)
        for s, (p, k) in enumerate(zip(r.shown, idx)):
            dead = k < 0 or p in b or (stale is not None and stale[k] and p not in hc and p not in lc)
            rows.append(X[s]); meta.append((r.Index, s + 1, int(p == r.clicked), int(p == r.purchased), int(dead)))
    I = pd.DataFrame(np.array(rows), columns=lfm.FEATS)
    M = pd.DataFrame(meta, columns=["rid", "slot", "clk", "buy", "dead"])
    I = pd.concat([M, I], axis=1); I["ls"] = np.log(I.slot)
    return I.merge(d[["new_user", "page", "ts"]], left_on="rid", right_index=True)


def fit(I):
    """-> coef dict {known/new: {w, b, slot, cal}}. cal = (a, b): P(buy) = sigmoid(a + b * logit)."""
    from sklearn.linear_model import LogisticRegression
    out = {}
    for seg, new in (("known", False), ("new", True)):
        a = I[(I.new_user == new) & (I.dead == 0)]
        cols = lfm.FEATS + ["ls"]
        m = LogisticRegression(C=C_REG, max_iter=5000).fit(a[cols], a.clk, sample_weight=np.where(a.buy == 1, BUY_W, 1.0))
        z = a[cols].values @ m.coef_[0] + m.intercept_[0]
        c = LogisticRegression(C=100.0, max_iter=5000).fit(z.reshape(-1, 1), a.buy)
        out[seg] = dict(w=dict(zip(lfm.FEATS, m.coef_[0][:-1].round(4).tolist())), b=round(float(m.intercept_[0]), 4),
                        slot=round(float(m.coef_[0][-1]), 4), cal=[round(float(c.intercept_[0]), 4), round(float(c.coef_[0][0]), 4)],
                        n=int(len(a)), clicks=int(a.clk.sum()), buys=int(a.buy.sum()))
    return out


def p_buy(coef, seg, X, slot):
    """Calibrated purchase probability of feature rows X shown in `slot` (array, 1-based)."""
    c = coef[seg]; w = np.array([c["w"][f] for f in lfm.FEATS])
    z = X @ w + c["b"] + c["slot"] * np.log(slot)
    return 1.0 / (1.0 + np.exp(-(c["cal"][0] + c["cal"][1] * z)))


def report(d, I, LF, aff, carts, buys, coef, test_rids, max_n=4000):
    """Hold-out: ranking quality, calibration by segment, and model-estimated value of logged vs lfm slates."""
    from sklearn.metrics import roc_auc_score
    T = I[I.rid.isin(test_rids) & (I.dead == 0)]
    for seg, new in (("known", False), ("new", True)):
        a = T[T.new_user == new]; p = p_buy(coef, seg, a[lfm.FEATS].values, a.slot.values)
        print(f"hold-out {seg:5s}: {len(a):6d} impressions, {int(a.buy.sum()):3d} buys, {int(a.clk.sum()):3d} clicks | "
              f"AUC buy {roc_auc_score(a.buy, p):.3f}  click {roc_auc_score(a.clk, p):.3f} | predicted buys {p.sum():.1f}")
    LF.w = {k: np.array([coef[k]["w"][f] for f in lfm.FEATS]) for k in ("known", "new")}; LF.b = {k: coef[k]["b"] for k in ("known", "new")}
    S = LF.snap; res = []; slots = np.arange(1, 11)
    rng = np.random.default_rng(0); rids = list(test_rids)
    if len(rids) > max_n: rids = list(rng.choice(rids, max_n, replace=False))
    for r in d.loc[rids].itertuples():
        st = state_asof(LF, carts, buys, r.user_id, r.ts); b, lc, hc = st
        req = dict(user_id=r.user_id, rv=r.rv, page=r.page, is_new_user=bool(r.new_user))
        seg = "new" if r.new_user else "known"
        X = lfm.features(S, aff.affinity_all(r.user_id, r.rv), r.rv, r.page, hc, lc)
        stale = S.stale(r.user_id)
        def value(items):
            v = 0.0
            for s, p in enumerate(items):
                k = S.row.get(p)
                if k is None or p in b or (stale is not None and stale[k] and p not in hc and p not in lc): continue   # dead: ~0
                v += float(p_buy(coef, seg, X[k:k + 1], np.array([s + 1]))[0])
            return v
        new = LF.slate(req, st, aff)
        res.append((seg, r.page == "home", (r.mv or "?") if r.served_by == "team" else "FALLBACK", int(r.purchased != ""),
                    value(r.shown), value(new) if new else np.nan, len(set(new or ()) & set(r.shown))))
    R = pd.DataFrame(res, columns=["seg", "home", "mv", "buy", "v_logged", "v_lfm", "overlap"])
    R["mv"] = R.mv.str.replace("-guard", "").str.replace(":v1", "").str.replace("-r1", "")
    g = R.groupby(["seg", "home"]).agg(n=("buy", "size"), real=("buy", "mean"), logged=("v_logged", "mean"), lfm=("v_lfm", "mean"), overlap=("overlap", "mean"))
    g["share"] = g.n / len(R)
    for c in ("real", "logged", "lfm"): g[c] = (100 * g[c]).round(2)
    print("\nexpected purchases per 100 requests (model estimate; 'real' = purchases that happened):\n", g.round(3).to_string())
    print("\nby logged policy (non-home):\n", (R[~R.home].groupby(["seg", "mv"]).agg(n=("buy", "size"), real=("buy", "mean"), logged=("v_logged", "mean"), lfm=("v_lfm", "mean")) * [1, 100, 100, 100]).round(2).query("n >= 100").to_string())
    tot = R[["buy", "v_logged", "v_lfm"]].mean() * 100
    print(f"\nall hold-out requests (n={len(R)}): real {tot.buy:.2f}%  model on logged slates {tot.v_logged:.2f}%  model on lfm slates {tot.v_lfm:.2f}%")
    return R


def main():
    if "--pull" in sys.argv: pull()
    d, LF, aff, carts, buys = load()
    I = impressions(d, LF, aff, carts, buys)
    print(len(d), "requests,", len(I), "impressions,", int(I.buy.sum()), "buys,", int(I.clk.sum()), "clicks; dead impressions:",
          int(I.dead.sum()), "with", int(I[I.dead == 1].buy.sum()), "buys")
    cut = pd.Timestamp(sys.argv[sys.argv.index("--cut") + 1]) if "--cut" in sys.argv else d.ts.quantile(0.7)
    train = I[I.ts < cut]; test_rids = d.index[d.ts >= cut]
    print("time split at", cut, "| train requests", int((d.ts < cut).sum()), "test", len(test_rids))
    report(d, I, LF, aff, carts, buys, fit(train), test_rids)
    coef = fit(I)
    coef["lq0"] = LF.lq0
    coef["meta"] = dict(fitted_on=f"{d.ts.min()} .. {d.ts.max()} UTC", requests=int(len(d)), buy_weight=BUY_W, C=C_REG, label="click, purchases x3")
    if "--no-write" not in sys.argv:
        lfm.ART.write_text(json.dumps(coef, indent=1)); print("\nwrote", lfm.ART.name)
    for seg in ("known", "new"): print(seg, coef[seg])


if __name__ == "__main__":
    main()
