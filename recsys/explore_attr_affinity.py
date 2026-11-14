"""Evidence for the user x description-attribute affinity (I-091, I-092). Read-only.

    python explore_attr_affinity.py organic   # E-093a: organic events, time split at 2026-10-15 (no carousel bias)
    python explore_attr_affinity.py live      # E-093b: our own live feedback (hidden model outcomes)
    python explore_attr_affinity.py slates    # E-092: within logged slates, v1 vs v1 x exp(beta * affinity)
Needs data/user_item_{A,all}.parquet and data/hs.parquet (download_*.py)."""
import sys, json
import numpy as np, pandas as pd
import cold_items, attr_affinity
BINS = [-1, 0.10, 0.125, 0.15, 0.175, 0.20, 0.25, 2]

def _tab(d, name):
    g = d.groupby(pd.cut(d.aff, BINS), observed=False).agg(impr=("buy", "size"), clicks=("click", "sum"), buys=("buy", "sum"))
    g["buys_per_10k"] = (g.buys / g.impr * 1e4).round(1); g["ctr_%"] = (g.clicks / g.impr * 100).round(2)
    print(f"\n{name} | impressions {len(d)}, purchases {int(d.buy.sum())}"); print(g.to_string())

def organic():
    """Affinity from views BEFORE 2026-10-15; outcome = purchases on user-product pairs first seen AFTER it."""
    AFF = attr_affinity.AttrAffinity(ui_path="data/user_item_A.parquet")
    a = pd.read_parquet("data/user_item_A.parquet"); al = pd.read_parquet("data/user_item_all.parquet")
    m = al.merge(a[["u", "i", "v"]], on=["u", "i"], how="left", suffixes=("", "_A")).fillna(0)
    late = m[(m.v_A == 0) & (m.v > 0) & m.u.isin(AFF.uix) & m.i.isin(AFF.pid)]
    R = AFF.UV[late.u.map(AFF.uix).values]; tot = R.sum(1); ok = tot >= 40
    late = late[ok]; aff = (R[ok] * AFF.A[late.i.map(AFF.pid).values]).sum(1) / tot[ok]
    rnd = (R[ok] * AFF.A[np.random.default_rng(0).integers(0, len(AFF.A), ok.sum())]).sum(1) / tot[ok]
    b = pd.cut(aff, BINS)
    t = pd.DataFrame({"first_views": late.v.groupby(b, observed=False).sum(), "purchases": late.p.groupby(b, observed=False).sum()})
    t["purchases_per_view"] = (t.purchases / t.first_views).round(4); t["share_of_purchases"] = (t.purchases / t.purchases.sum()).round(3)
    t["share_of_random_catalogue"] = (pd.Series(rnd).groupby(pd.cut(rnd, BINS), observed=False).size().values / len(rnd)).round(3)
    print(f"users {late.u.nunique()}, user-product pairs {len(late)} (raw affinity, users with >=20 prior views)"); print(t.to_string())

def live():
    from rt import q
    import os
    T = os.environ["TEAM_ID"]
    fb = pd.concat([q(f"""SELECT r.user_id::String u, r.context.page::String page, toJSONString(r.recent_views) rv, toJSONString(f.shown) shown,
        f.clicked::String clicked, f.purchased::String purchased FROM {T}.feedback f INNER JOIN shop.requests r ON r.request_id::String=f.request_id::String
        WHERE f.request_id::String!='__init__' AND cityHash64(f.request_id::String)%4={m}""") for m in range(4)])
    AFF = attr_affinity.AttrAffinity()      # history only (ends 07:00 UTC, before the first request)
    al = pd.read_parquet("data/user_item_all.parquet"); al = al[al.u.isin(set(fb.u))]
    rel = {(u, i): ("bought" if p > 0 else "cart" if a > 0 else "viewed") for u, i, a, p in zip(al.u, al.i, al.a, al.p)}
    rows = []
    for u, rv, sh, cl, pu in zip(fb.u, fb.rv, fb.shown, fb.clicked, fb.purchased):
        rvl = [x["product_id"] for x in json.loads(rv)]; sh = json.loads(sh); known = AFF.user_vec(u).sum() >= 20
        for i, a in zip(sh, AFF.affinity(u, sh, rvl)): rows.append((i in rvl, rel.get((u, i), "none"), known, len(rvl), a, i == cl, i == pu))
    r = pd.DataFrame(rows, columns=["in_rv", "rel", "known", "nrv", "aff", "click", "buy"])
    print(f"feedback requests {len(fb)} (team + fallback slates), shrunk affinity incl. session views")
    _tab(r[r.known & ~r.in_rv & (r.rel == "none")], "known user, product never touched, not in session views")
    _tab(r[~r.known & ~r.in_rv & (r.nrv > 0)], "user without history, affinity from session views only")
    _tab(r[r.known & ~r.in_rv & (r.rel == "cart")], "known user, carted-not-bought")
    _tab(r[r.in_rv], "product in session views")

def slates():
    """Time split as E-003: user tables < 2026-10-15, buying test sessions >= 2026-11-04. Committed v1 model, slot=0."""
    import joblib
    from fe import build_tables, featurize, FEATS
    AFF = attr_affinity.AttrAffinity(ui_path="data/user_item_A.parquet")
    T = build_tables(pd.read_parquet("data/user_item_A.parquet"))
    hs = pd.read_parquet("data/hs.parquet"); hs = hs[(hs.ts >= "2026-11-04") & (hs.purchased != "")].copy()
    hs["rv"] = hs.rv.map(lambda s: [x["product_id"] for x in json.loads(s)]); hs["shown"] = hs.shown.map(json.loads); hs["sid"] = np.arange(len(hs))
    P = hs[["sid", "user_id", "rv", "page", "shown", "purchased"]].explode("shown").rename(columns={"user_id": "u", "shown": "i"}).reset_index(drop=True)
    P["slot"] = 0; P["new_user"] = 0; P["y"] = (P.i == P.purchased).astype(int)
    X = featurize(P, T, "2026-10-15"); X["s"] = joblib.load("data/model_buy.joblib").predict_proba(X[FEATS])[:, 1]
    AFF.beta = 1.0; X["aff"] = np.log(AFF.boost_frame(X))
    nv = X.sid.map(X[X.y == 1].set_index("sid").in_rv) == 0
    def ev(sc, m=None):
        d = X.assign(_s=sc); d = d if m is None else d[m]
        r = d.groupby("sid")._s.rank(ascending=False, method="first")[d.y == 1]
        return f"N={len(r)} hit@1={np.mean(r == 1):.3f} hit@3={np.mean(r <= 3):.3f} MRR={np.mean(1 / r):.3f}"
    for beta in (0, 10, 20, 40, 60): print(f"v1 x exp({beta}*aff) | all {ev(X.s * np.exp(beta * X.aff))} | bought item not viewed in session {ev(X.s * np.exp(beta * X.aff), nv)}")
    print("affinity only         | all", ev(X.aff), "| not viewed", ev(X.aff, nv))

if __name__ == "__main__":
    {"organic": organic, "live": live, "slates": slates}[sys.argv[1]]()
