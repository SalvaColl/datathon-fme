"""List-level effects: does a request convert more or less than the sum of its items' appeal predicts, depending on variety?"""
from clfit import *
from sklearn.linear_model import LogisticRegression
P = pd.read_parquet("P.parquet")
import pyarrow
cat = pd.read_parquet(RS + "data/lfm_cat.parquet").set_index("product_id").reindex(P.pid)
sub = pd.factorize(cat["sub"])[0]; ct = pd.factorize(cat["category"])[0]; br = pd.factorize(cat["brand"])[0]
I["sub"] = sub[I.k.values]; I["cat"] = ct[I.k.values]; I["br"] = br[I.k.values]
POSW = np.exp(np.array([0, -.35, -.76, -.71, -.83, -1.08, -1.35, -1.13, -1.41, -1.51]))
u3 = pol("policy.unified_u3.json")
for name, segs, key, sc in (("kS/page", ["kS/page"], ("known", False), 0.27), ("new/page", ["new/page"], ("new", False), 0.81)):
    a = I[I.seg.isin(segs) & (I.dead == 0)].copy(); a["z"] = sc * (F[a.index.values] @ u3[key]); a["e"] = POSW[a.slot.values - 1] * np.exp(a.z)
    a["cartf"] = (F[a.index.values][:, FI["chn"]] > 0) | (F[a.index.values][:, FI["cl"]] > 0)
    g = a.groupby("rid").agg(n=("slot", "size"), buy=("buy", "max"), clk=("clk", "max"), E=("e", "sum"), emax=("e", "max"), nsub=("sub", "nunique"), ncat=("cat", "nunique"), nbr=("br", "nunique"), ncart=("cartf", "sum"))
    g = g[g.n == 10].join(R[["trait", "nrv", "nlc", "nhc", "ts", "hv"]])
    top = a[a.slot <= 3].groupby("rid").agg(nsub3=("sub", "nunique"), ncat3=("cat", "nunique")); g = g.join(top)
    g["lE"] = np.log(g.E); g["lt"] = np.log(g.trait); g["lhv"] = np.log1p(g.hv); g["share1"] = g.emax / g.E
    base = ["lE", "lt", "lhv", "nrv"]
    def fit(cols, y="buy"):
        Xm = g[cols].values.astype(float); Xm = (Xm - Xm.mean(0)) / Xm.std(0); m = LogisticRegression(C=100, max_iter=2000).fit(Xm, g[y])
        p = m.predict_proba(Xm)[:, 1]; A = np.hstack([Xm, np.ones((len(Xm), 1))]); se = np.sqrt(np.diag(np.linalg.inv((A * (p * (1 - p))[:, None]).T @ A)))
        return "  ".join(f"{c} {b:+.3f}±{s:.3f}" for c, b, s in zip(cols, m.coef_[0], se))
    print(f"== {name}: {len(g)} requests, {int(g.buy.sum())} buys (standardised coefficients)")
    print("  base       :", fit(base))
    for extra in (["nsub"], ["ncat"], ["nbr"], ["nsub3"], ["ncat3"], ["share1"], ["ncart"], ["nsub", "ncat", "share1"]):
        print("  +", extra, ":", fit(base + extra), "| clicks:", fit(base + extra, "clk").split("  ", len(base))[-1])
    print("  conversion by distinct subcategories in the list:", g.groupby(pd.cut(g.nsub, [0, 2, 4, 6, 8, 10])).agg(n=("buy", "size"), conv=("buy", "mean"), lE=("lE", "mean")).round(4).to_dict("index"))
