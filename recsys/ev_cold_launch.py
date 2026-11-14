"""E-091: simulate product launches inside logged slates. Read-only.

For each of 5 folds, 20% of the catalogue is treated as "just launched": its item counters and user x item history
are wiped (what v1 sees for a new product) and replaced by different guesses. Priors are fitted on the OTHER 80% of
products with events before 2026-10-11; test = buying sessions >= 2026-11-04; committed v1 model, slot=0.
    python ev_cold_launch.py        (needs data/hs.parquet, data/user_item_A.parquet)"""
import json
import numpy as np, pandas as pd, joblib
from sklearn.model_selection import KFold
from rt import q
from fe import build_tables, featurize, FEATS
import cold_items

K = cold_items.K_PRIOR; FR = 0.04   # FR: share of an established item's counts a launch has after ~1 h of live events
rng = np.random.default_rng(0)
cat = q("SELECT product_id::String product_id, category::String category, subcategory::String sub, brand::String brand, price_eur::Float64 price, description::String description FROM shop.catalog")
h = q("SELECT product_id::String product_id, countIf(event_type='view') v, countIf(event_type='add_to_cart') a, countIf(event_type='purchase') p FROM shop.history_events WHERE ts::DateTime64(3) < toDateTime64('2026-10-11 00:00:00',3) GROUP BY product_id")
d = cat.merge(h, on="product_id")
for c in "vap": d[c] = d[c].astype(float)
ui = pd.read_parquet("data/user_item_A.parquet"); T = build_tables(ui); item = ui.groupby("i")[["v", "a", "p"]].sum()
hs = pd.read_parquet("data/hs.parquet"); hs = hs[(hs.ts >= "2026-11-04") & (hs.purchased != "")].copy()
hs["rv"] = hs.rv.map(lambda s: [x["product_id"] for x in json.loads(s)]); hs["shown"] = hs.shown.map(json.loads); hs["sid"] = np.arange(len(hs))
P = hs[["sid", "user_id", "rv", "page", "shown", "purchased"]].explode("shown").rename(columns={"user_id": "u", "shown": "i"}).reset_index(drop=True)
P["slot"] = 0; P["new_user"] = 0; P["y"] = (P.i == P.purchased).astype(int)
X0 = featurize(P, T, "2026-10-15"); M = joblib.load("data/model_buy.joblib"); res = []
for tri, tei in KFold(5, shuffle=True, random_state=0).split(d):
    tr, te = d.iloc[tri], d.iloc[tei]; g = {c: tr[c].sum() / tr.v.sum() for c in "pa"}
    pri = cold_items.ColdPrior().fit(tr).predict(te).rename(columns={"cr": "glm_p", "ar": "glm_a"}); pri.index = te.product_id.values
    gg = tr.groupby("sub")[["v", "a", "p"]].sum()
    for c in "pa": pri["sub_" + c] = ((gg[c] + 300 * g[c]) / (gg.v + 300)).reindex(te["sub"]).fillna(g[c]).values
    pri["vol"] = item.v.reindex(tr.product_id).groupby(tr["sub"].values).median().reindex(te["sub"]).fillna(item.v.median()).values
    true = item.reindex(pri.index).fillna(0)
    early = pd.DataFrame({"v": rng.binomial(true.v.astype(int).values, FR)}, index=pri.index)
    early["a"] = rng.binomial(early.v.values, (true.a / true.v.clip(lower=1)).clip(upper=1).values)
    early["p"] = rng.binomial(early.a.values, (true.p / true.a.clip(lower=1)).clip(upper=1).values)
    isS = X0.i.isin(set(pri.index)).values; ii = X0.i[isS]; pp = pri.reindex(ii); e = early.reindex(ii)
    cold_sid = set(X0[isS & (X0.in_rv == 1)].sid)
    for kind in ("no counts (v1 at launch)", "1h of live counts only", "subcategory prior", "attribute prior (cold_items)", "attribute prior + 1h live counts", "oracle (real counts)"):
        X = X0.copy()
        if not kind.startswith("oracle"):
            X.loc[isS, ["ui_v", "ui_a", "ui_p", "age"]] = 0
            if kind.startswith("no counts"): v = a = p = np.zeros(len(ii))
            elif kind.startswith("1h"): v, a, p = e.v.values, e.a.values, e.p.values
            else:
                k = "sub" if kind.startswith("sub") else "glm"; ev_, ea, ep = (e.v.values, e.a.values, e.p.values) if "+" in kind else (0, 0, 0)
                v = pp.vol.values; a = (ea + K * pp[k + "_a"].values) / (ev_ + K) * v; p = (ep + K * pp[k + "_p"].values) / (ev_ + K) * v
            X.loc[isS, "lp_v"] = np.log1p(v); X.loc[isS, "lp_a"] = np.log1p(a); X.loc[isS, "lp_p"] = np.log1p(p)
            X.loc[isS, "cr"] = (p + 1) / (v + 50); X.loc[isS, "cart"] = (a + 1) / (v + 50)
        X["r"] = X.assign(s=M.predict_proba(X[FEATS])[:, 1]).groupby("sid").s.rank(ascending=False, method="first")
        pos = X[X.y == 1]; new = pos[isS[pos.index]]; old = pos[~isS[pos.index]]; cold = pos[pos.sid.isin(cold_sid)]
        res.append(dict(kind=kind, n_new=len(new), hit1_new=(new.r == 1).sum(), hit3_new=(new.r <= 3).sum(), n_old=len(old), hit1_old=(old.r == 1).sum(),
                        n_cold=len(cold), hit1_cold=(cold.r == 1).sum()))
R = pd.DataFrame(res).groupby("kind", sort=False).sum()
R["hit1_all"] = (R.hit1_new + R.hit1_old) / (R.n_new + R.n_old)
for s in ("new", "old", "cold"):
    for m in ("hit1", "hit3"):
        if f"{m}_{s}" in R: R[f"{m}_{s}"] /= R[f"n_{s}"]
print("new = bought product is a simulated launch; old = bought product is established (slate may contain launches);")
print("cold = a simulated launch is in recent_views (official cold-request definition)"); print(R.round(3).to_string())
