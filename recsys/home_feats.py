"""T-013: as-of (strictly before the session's date) organic user features for every (home session, shown item) row.
Input data/home_hs.parquet + data/uid.parquet -> data/home_E.parquet"""
import pandas as pd, numpy as np, json
C = pd.read_parquet("data/catalog.parquet").set_index("product_id")
h = pd.read_parquet("data/home_hs.parquet")
h["shown"] = h.shown.map(json.loads); h["prop"] = h.prop.map(json.loads)
h["d"] = pd.to_datetime(h.ts.str[:10])
E = h[["rid", "u", "ts", "d", "device", "region", "shown", "prop", "purchased", "clicked"]].explode(["shown", "prop"]).rename(columns={"shown": "i"})
E["prop"] = E.prop.astype(float)
E["slot"] = E.groupby("rid").cumcount(); E["y"] = (E.i == E.purchased).astype(int); E["yc"] = (E.i == E.clicked).astype(int)
for k in ("category", "sub", "brand", "price"): E[k] = C[k].reindex(E.i).values
U = pd.read_parquet("data/uid.parquet"); U["d"] = pd.to_datetime(U.d)
U["category"] = C.category.reindex(U.i).values; U["sub"] = C["sub"].reindex(U.i).values
U = U.dropna(subset=["category"])
def asof(E, keys, pre):
    g = U.groupby(keys + ["d"], observed=True)[["v", "a", "p"]].sum().reset_index().sort_values(keys + ["d"])
    g[["v", "a", "p"]] = g.groupby(keys, observed=True)[["v", "a", "p"]].cumsum()
    g = g.rename(columns={"v": pre + "v", "a": pre + "a", "p": pre + "p"}).sort_values("d")
    E = E.sort_values("d")
    out = pd.merge_asof(E, g, on="d", by=keys, allow_exact_matches=False)  # strictly earlier days only
    for c in "vap": out[pre + c] = out[pre + c].fillna(0)
    return out
E = asof(E, ["u"], "ut_"); E = asof(E, ["u", "category"], "uc_"); E = asof(E, ["u", "sub"], "us_"); E = asof(E, ["u", "i"], "ui_")
# item organic popularity as-of
E = asof(E, ["i"], "it_")
E.to_parquet("data/home_E.parquet"); print(len(E), E.y.sum(), E.yc.sum())
