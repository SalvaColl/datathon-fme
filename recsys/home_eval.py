"""T-013 offline evaluation for home_cands.py. Needs data from `home_download.py all` + `home_feats.py`.

  python home_eval.py fit     # E-130: fit the 6-weight score on historical home rows (time split), transfer to live feedback
  python home_eval.py live    # E-131: live feedback by prior user-item relation (bought / carted / viewed / none)
  python home_eval.py dry     # read-only check on the current stream: valid slates (10 distinct in-stock ids) with the live catalog
  python home_eval.py slate   # E-132: replay live home requests through HomeCands (history-only state): composition + organic recall
"""
import sys, json
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score as auc
C = pd.read_parquet("data/catalog.parquet").set_index("product_id")
SPLIT = "2026-11-04"
COLS = ["carted", "sub_b", "ucs", "unknown", "lcr", "lpop", "slot"]

def ui_all():
    return pd.read_parquet("data/uid.parquet").groupby(["u", "i"], observed=True)[["v", "a", "p"]].sum().reset_index()

def live_rows():
    """One row per (live feedback request, shown item) with history-only user/item features (history ends 07:00 UTC,
    before the first live request, so there is no leakage)."""
    s = pd.read_parquet("data/live_fb.parquet"); s = s[s.sb == "team"]
    s["shown"] = s.shown.map(json.loads); s["rv"] = s.rv.map(lambda x: {y["product_id"] for y in json.loads(x)})
    ui = ui_all(); ui["sub"] = C["sub"].reindex(ui.i).values; ui["cat"] = C.category.reindex(ui.i).values
    E = s.explode("shown").rename(columns={"shown": "i"}); E["slot"] = E.groupby("rid").cumcount()
    E["sub"] = C["sub"].reindex(E.i).values; E["cat"] = C.category.reindex(E.i).values
    def look(g, keys):
        return g.reindex(pd.MultiIndex.from_arrays(keys) if len(keys) > 1 else keys[0]).fillna(0)
    m = look(ui.set_index(["u", "i"])[["v", "a", "p"]], [E.u, E.i]); E["ui_v"], E["ui_a"], E["ui_p"] = m.v.values, m.a.values, m.p.values
    m = look(ui.groupby(["u", "sub"])[["v", "p"]].sum(), [E.u, E["sub"]]); E["us_p"] = m.p.values
    m = look(ui.groupby(["u", "cat"])[["v", "p"]].sum(), [E.u, E["cat"]]); E["uc_v"] = m.v.values
    m = look(ui.groupby("u")[["v", "p"]].sum(), [E.u]); E["ut_v"] = m.v.values
    m = look(ui.groupby("i")[["v", "p"]].sum(), [E.i]); E["it_v"], E["it_p"] = m.v.values, m.p.values
    E["rel"] = np.select([E.ui_p > 0, E.ui_a > 0, E.ui_v > 0], ["bought", "carted", "viewed"], "none")
    E["inrv"] = [i in r for i, r in zip(E.i, E.rv)]
    E["y"] = (E.i == E.purchased).astype(int); E["yc"] = (E.i == E.clicked).astype(int); E["days"] = 60
    return E

def feats(D):
    X = pd.DataFrame(index=D.index)
    X["carted"] = ((D.ui_a > 0) & (D.ui_p == 0)).astype(float)
    X["sub_b"] = (D.us_p > 0).astype(float)
    X["ucs"] = D.uc_v / D.ut_v.clip(lower=1)
    X["unknown"] = (D.ut_v == 0).astype(float)
    X["lcr"] = np.log((D.it_p + 1) / (D.it_v + 50)) + 2.2
    X["lpop"] = np.log((D.it_v + 10) / D.days) - 3
    X["slot"] = D.slot / 9.0
    return X

def rank_metrics(D, score, label):
    b = D[D.rid.isin(D.loc[D[label] == 1, "rid"])].copy(); b["_s"] = score.reindex(b.index)
    r = b.groupby("rid")["_s"].rank(ascending=False, method="first")[b[label] == 1]
    return f"hit@1 {(r == 1).mean():.3f} MRR {(1 / r).mean():.3f} (N={len(r)})"

def fit():
    H = pd.read_parquet("data/home_E.parquet"); H["days"] = (H.d - pd.Timestamp("2026-09-15")).dt.days.clip(lower=1)
    H = H[H.ui_p == 0].reset_index(drop=True)         # already-bought rows excluded: dead in live (E-131)
    X = feats(H); tr = (H.d < SPLIT).values; te = ~tr
    m = LogisticRegression(C=10.0, max_iter=3000, tol=1e-6).fit(X.loc[tr, COLS], H.y[tr])
    print("weights", dict(zip(COLS, [float(x) for x in m.coef_[0].round(2)])), "intercept", m.intercept_.round(2))
    X0 = X[COLS].copy(); X0["slot"] = 0; H["s"] = m.predict_proba(X0)[:, 1]
    T = H[te]; print(f"history home test (>= {SPLIT}): rows {len(T)}, buys {T.y.sum()}, clicks {T.yc.sum()}")
    print(f"  item AUC buy {auc(T.y, T.s):.3f} click {auc(T.yc, T.s):.3f}")
    rng = np.random.default_rng(0)
    for nm, sc in [("random", pd.Series(rng.random(len(T)), T.index)), ("logged order", -T.slot), ("item cr only", X.lcr[te]), ("home score", T.s)]:
        print(f"  within-slate {nm:13s} buy: {rank_metrics(T, sc, 'y')} | click: {rank_metrics(T, sc, 'yc')}")
    L = live_rows(); L = L[(L.rel != "bought") & (~L.inrv)]; XL = feats(L)[COLS]; XL["slot"] = 0; L["s"] = m.predict_proba(XL)[:, 1]
    for nm, k in [("live home", L.page == "home"), ("live home known", (L.page == "home") & ~L.nu), ("live home new", (L.page == "home") & L.nu), ("live other pages", L.page != "home")]:
        D = L[k]; print(f"  {nm:17s} rows {len(D)} buys {D.y.sum()} clicks {D.yc.sum()} | AUC click {auc(D.yc, D.s):.3f} buy {auc(D.y, D.s):.3f}"
                        f" | baselines AUC click: shown slot {auc(D.yc, -D.slot):.3f}, item cr {auc(D.yc, np.log((D.it_p + 1) / (D.it_v + 50))):.3f}")

def live():
    E = live_rows(); E["home"] = E.page == "home"
    t = E.groupby(["home", "inrv", "rel"]).agg(n=("y", "size"), buy=("y", "sum"), click=("yc", "sum"))
    t["buy_per_10k"] = (1e4 * t.buy / t.n).round(1); t["click_per_10k"] = (1e4 * t.click / t.n).round(1); print(t.to_string())
    s = pd.read_parquet("data/live_fb.parquet"); print("requests", s.rid.nunique(), s.ts.min(), s.ts.max())

def slate():
    import home_cands
    ui = ui_all(); cat = C.copy()
    import time; t = time.time(); HC = home_cands.HomeCands(ui, cat); print("build s", round(time.time() - t, 1))
    s = pd.read_parquet("data/live_fb.parquet"); s = s[(s.page == "home")].copy(); s["shown"] = s.shown.map(json.loads)
    s["ours"] = [HC.slate(u) for u in s.u]
    assert all(len(x) == 10 and len(set(x)) == 10 for x in s.ours)
    ev = pd.read_parquet("data/live_ev.parquet")
    buys = ev[ev.e == "purchase"]; fut = buys.groupby("u").apply(lambda d: list(zip(d.ts, d.i)), include_groups=False).to_dict()
    def stats(col, D):
        st = bo = ca = hit_new = hit_any = n_new = n_any = 0
        for u, ts, items in zip(D.u, D.ts, D[col]):
            b = HC.bought.get(u, ()); c = HC.carted.get(u, {})
            bo += sum(i in b for i in items); ca += sum(i in c for i in items); st += sum(HC.is_stale(u, i) and i not in c and i not in b for i in items)
            later = {i for t, i in fut.get(u, ()) if t > ts}; new = {i for i in later if i not in b}
            n_any += bool(later); n_new += bool(new); hit_any += bool(later & set(items)); hit_new += bool(new & set(items))
        n = len(D)
        return (f"bought {bo / n / 10:.1%} carted {ca / n / 10:.1%} viewed-only {st / n / 10:.1%} of impressions | requests whose user later buys organically a shown item: "
                f"any {hit_any}/{n_any} ({hit_any / max(n_any, 1):.1%}), first-time purchases {hit_new}/{n_new} ({hit_new / max(n_new, 1):.1%})")
    for nm, D in [("known users", s[~s.nu]), ("new users", s[s.nu])]:
        print(nm, len(D))
        print("  shown live (all writers):", stats("shown", D)); print("  home_cands           :", stats("ours", D))
    t = time.time(); [HC.slate(u) for u in s.u.head(2000)]; print("slate ms/request", round((time.time() - t) / 2, 3))
    t = time.time(); HC.refresh(cat, set()); print("refresh s", round(time.time() - t, 2))

def dry():
    """READ-ONLY: latest home requests + current catalog/stock -> slates; writes nothing anywhere."""
    import home_cands, time
    from rt import q
    cat = q("""SELECT product_id::String product_id, argMax(category::String,v) category, argMax(subcategory::String,v) sub,
      argMax(is_active::Bool,v) active, argMax(chg,v) last_change
      FROM (SELECT product_id, category, subcategory, is_active, '' chg, '' v FROM shop.catalog
            UNION ALL SELECT product_id, category, subcategory, is_active, change::String, toString(ts) FROM shop.catalog_updates)
      GROUP BY product_id""").set_index("product_id")
    unavail = set(cat.index[(~cat.active.astype(bool)) | (cat.last_change == "out_of_stock")])
    HC = home_cands.HomeCands(ui_all(), C.copy())
    li = pd.read_parquet("data/live_ev.parquet")       # live carts/purchases snapshot (views not needed for the check)
    for u, i, e in zip(li.u.values, li.i.values, li.e.values): HC.add(u, i, 0, int(e == "add_to_cart"), int(e == "purchase"))
    t = time.time(); HC.refresh(cat, unavail); print("catalog", len(cat), "unavailable", len(unavail), "refresh s", round(time.time() - t, 3))
    r = q("SELECT request_id::String rid, user_id::String u, is_new_user::Bool nu FROM shop.requests WHERE context.page::String='home' ORDER BY ts DESC LIMIT 2000")
    t = time.time(); sl = [HC.slate(u) for u in r.u]; ms = (time.time() - t) / len(r) * 1000
    ok = [len(x) == 10 and len(set(x)) == 10 and not (set(x) & unavail) and all(i in cat.index for i in x) for x in sl]
    dead = sum(HC.is_dead(u, i) for u, x in zip(r.u, sl) for i in x)
    print(f"home requests {len(r)} (new users {int(r.nu.sum())}) | valid slates {sum(ok)}/{len(ok)} | dead items shown {dead} | {ms:.3f} ms/request")

if __name__ == "__main__":
    {"fit": fit, "live": live, "slate": slate, "dry": dry}[sys.argv[1]]()
