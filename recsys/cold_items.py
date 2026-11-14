"""Cold start for NEW PRODUCTS (T-009): a purchase-rate prior from catalogue metadata + description attributes.

Why: the v1 model reads an item's quality from its view/cart/purchase counts. A product launched a minute ago has
none, so v1 never ranks it first (E-091: hit@1 = 0.000 on simulated launches). This module predicts, from metadata
only, the organic purchase-per-view and cart-per-view rate a product will have, and turns that into the same count
features an established product has, blended with whatever live events exist (empirical Bayes, K views of prior).

Key fact (I-090): every description is "<brand> <subcategory>" + exactly 2 phrases out of a fixed list of 20
("great value for money", "organic ingredients", ...). Which 2 phrases, crossed with the category, explain most of
the product's conversion. A Poisson GLM on those tokens ranks unseen products with Spearman 0.84 (E-090).

Usage
    python cold_items.py fit      # refit on shop.catalog + shop.history_events -> cold_prior.json (committed)
    python cold_items.py eval     # 5-fold product hold-out + the real launch test on live new products
Serving (no sklearn needed, pure dict lookups) — see D-090 in ../decisions.md for the 4-line live.py hook:
    cold = cold_items.ColdStart()                                  # loads cold_prior.json
    cold.sync(query)                                               # fetch descriptions of products not seen yet
    tabs = cold.tables(cat, base_item, live_item)                  # extra table for fe.featurize([BASE, live, tabs])
    extra = cold.attr_neighbors(last_viewed, cat, unavail, n=20)   # candidates sharing description attributes
This module never writes to RawTree.
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
ART = HERE / "cold_prior.json"
ATTRS = ["a sporty style", "a family-size format", "a luxury feel", "a minimalist design", "organic ingredients",
         "built for professionals", "wireless connectivity", "bold colours", "premium materials", "designed for kids",
         "smart app control", "whisper-quiet operation", "a vintage look", "made from recycled materials",
         "great value for money", "a travel-ready build", "a waterproof shell", "extra durability", "a handmade finish",
         "compact and lightweight"]
K_PRIOR = 100      # prior strength in views (E-090: best next-hour likelihood at ~100, flat between 30 and 300)
INTER = ("cat", "sub", "pair")


def attrs(description: str) -> tuple:
    """Indices (into ATTRS) of the phrases present in a description. Unknown phrases are simply not matched."""
    d = description or ""
    return tuple(k for k, a in enumerate(ATTRS) if a in d)


def tokens(category, sub, brand, price, at, inter=INTER) -> list:
    """One-hot tokens of the GLM. Price bucket = powers of two from 2 EUR (8 buckets)."""
    pb = int(min(7, max(0, math.floor(math.log2(max(float(price), 2.0) / 2)))))
    t = [f"c={category}", f"s={sub}", f"b={brand}", f"pb={pb}", f"c={category}|pb={pb}"]
    t += [f"a={k}" for k in at]
    if "cat" in inter: t += [f"c={category}|a={k}" for k in at]
    if "sub" in inter: t += [f"s={sub}|a={k}" for k in at]
    if "pair" in inter and len(at) == 2: t += [f"a2={at[0]}_{at[1]}"]
    return t


class ColdPrior:
    """Poisson GLM: log(rate) = intercept + sum of token weights. Targets: 'p' purchases/view, 'a' carts/view."""

    def __init__(self, coef=None, intercept=None, inter=INTER):
        self.coef = coef or {}; self.intercept = intercept or {}; self.inter = tuple(inter)

    def fit(self, df: pd.DataFrame, alpha=1e-5):
        """df: category, sub, brand, price, description, v, a, p (one row per product)."""
        from scipy import sparse
        from sklearn.linear_model import PoissonRegressor
        toks = [tokens(r.category, r.sub, r.brand, r.price, attrs(r.description), self.inter) for r in df.itertuples()]
        vocab = {}
        for t in toks:
            for x in t: vocab.setdefault(x, len(vocab))
        ri = [i for i, t in enumerate(toks) for _ in t]; ci = [vocab[x] for t in toks for x in t]
        X = sparse.csr_matrix((np.ones(len(ri)), (ri, ci)), shape=(len(toks), len(vocab)))
        for T in ("p", "a"):
            m = PoissonRegressor(alpha=alpha, max_iter=500).fit(X, df[T] / df.v, sample_weight=df.v)
            self.coef[T] = {k: float(m.coef_[j]) for k, j in vocab.items()}; self.intercept[T] = float(m.intercept_)
        return self

    def rate(self, category, sub, brand, price, description, T="p") -> float:
        c = self.coef[T]
        return math.exp(self.intercept[T] + sum(c.get(x, 0.0) for x in tokens(category, sub, brand, price, attrs(description), self.inter)))

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """-> DataFrame(cr, ar) indexed like df: expected purchases/view and carts/view."""
        out = [(self.rate(r.category, r.sub, r.brand, r.price, r.description, "p"),
                self.rate(r.category, r.sub, r.brand, r.price, r.description, "a")) for r in df.itertuples()]
        return pd.DataFrame(out, columns=["cr", "ar"], index=df.index)

    def to_json(self): return {"inter": list(self.inter), "coef": self.coef, "intercept": self.intercept}

    @classmethod
    def from_json(cls, j): return cls(j["coef"], j["intercept"], j["inter"])


def tfidf_knn_rate(train_desc, train_rate, query_desc, k=20):
    """Text fallback: similarity-weighted mean rate of the k nearest descriptions (TF-IDF 1-2 grams).
    Weaker than the GLM (E-090: Spearman 0.60 vs 0.84); used only for descriptions without known attribute phrases."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(list(train_desc) + list(query_desc))
    S = (vec.transform(query_desc) @ vec.transform(train_desc).T).toarray()
    idx = np.argsort(-S, 1)[:, :k]; w = np.take_along_axis(S, idx, 1) + 1e-9
    return (w * np.asarray(train_rate)[idx]).sum(1) / w.sum(1)


class ColdStart:
    """Serving-side helper. Holds the prior, the attribute pair of every product and the new-product descriptions."""

    def __init__(self, path=ART, k=K_PRIOR):
        j = json.loads(Path(path).read_text())
        self.prior = ColdPrior.from_json(j["prior"]); self.k = k
        self.attr = {p: tuple(a) for p, a in j["attrs"].items()}      # base catalogue: product_id -> attr indices
        self.base_ids = set(self.attr)
        self.desc = {}                                                # new products: product_id -> description
        self.prior_rate = {}                                          # new products: product_id -> (cr, ar)

    # ---- data sync (read-only) ----
    def sync(self, query) -> int:
        """Fetch description of new products we have not seen. `query(sql)` -> list of dict rows (live.query)."""
        rows = query("SELECT product_id::String product_id, argMax(description::String, ts::String) description "
                     "FROM shop.catalog_updates WHERE change::String = 'new_product' GROUP BY product_id")
        n = 0
        for r in rows:
            if r["product_id"] not in self.desc and r["product_id"] not in self.base_ids:
                self.desc[r["product_id"]] = r["description"]; self.attr[r["product_id"]] = attrs(r["description"]); n += 1
        return n

    def new_ids(self, cat: pd.DataFrame) -> list:
        """Products of the live catalogue that are not in the historical one (robust to later price/stock updates)."""
        return [p for p in cat.index if p not in self.base_ids]

    # ---- prior -> model features ----
    def pseudo_counts(self, cat, base_item, live_item=None) -> pd.DataFrame:
        """it_v/it_a/it_p a new product 'deserves': the volume of a typical established product of its subcategory
        and the posterior rates (live counts + K views of prior). cat: live catalogue (index product_id; columns
        category, sub, brand, price). base_item/live_item: frames it_v,it_a,it_p (history totals / live totals)."""
        new = self.new_ids(cat)
        cols = ["it_v", "it_a", "it_p"]
        if not new: return pd.DataFrame(columns=cols, dtype=float)
        tot = base_item.reindex(cat.index).fillna(0.0)
        lv = (live_item.reindex(cat.index).fillna(0.0) if live_item is not None else tot * 0.0)
        tot = tot + lv.values
        old = ~cat.index.isin(new)
        vol_sub = tot.it_v[old].groupby(cat["sub"][old].values).median(); vol_all = float(tot.it_v[old].median())
        rows = []
        for p in new:
            c = cat.loc[p]
            if p not in self.prior_rate:
                d = self.desc.get(p, "")
                self.prior_rate[p] = (self.prior.rate(c.category, c["sub"], c.brand, c.price, d, "p"),
                                      self.prior.rate(c.category, c["sub"], c.brand, c.price, d, "a"))
            cr0, ar0 = self.prior_rate[p]
            v, a, pu = (float(lv.at[p, x]) for x in cols)
            cr = (pu + self.k * cr0) / (v + self.k); ar = (a + self.k * ar0) / (v + self.k)
            vol = float(vol_sub.get(c["sub"], vol_all))
            rows.append((vol, ar * vol, cr * vol))
        return pd.DataFrame(rows, index=new, columns=cols)

    def tables(self, cat, base_item, live_item=None) -> dict:
        """Extra lookup table for fe.featurize([BASE, live, tables]): for new products it holds pseudo-counts MINUS
        their live counts, so BASE(0) + live + this = pseudo-counts. Other lookups are empty (contribute zeros)."""
        ps = self.pseudo_counts(cat, base_item, live_item)
        if len(ps) and live_item is not None: ps = ps - live_item.reindex(ps.index).fillna(0.0).values
        e = lambda cols, names: pd.DataFrame(columns=cols, dtype=float,
                                             index=pd.MultiIndex.from_arrays([[], []], names=names) if len(names) > 1 else pd.Index([], name=names[0]))
        return dict(item=ps, usub=e(["us_v", "us_p"], ["u", "sub"]), ucat=e(["uc_v", "uc_p"], ["u", "category"]),
                    utot=e(["ut_v", "ut_p"], ["u"]), uit=e(["ui_v", "ui_a", "ui_p"], ["u", "i"]))

    # ---- content similarity (I-091) ----
    def shared(self, a, b) -> int:
        """Number of description attributes two products share (0, 1 or 2)."""
        return len(set(self.attr.get(a, ())) & set(self.attr.get(b, ())))

    def attr_neighbors(self, pid, cat, unavail=(), n=20, score=None) -> list:
        """Active products of the same category sharing >=1 attribute with `pid`, 2 shared first, then by `score`
        (Series product_id -> anything sortable, e.g. cart rate). Works for new products on both sides."""
        if pid not in cat.index: return []
        mine = set(self.attr.get(pid, ()))
        if not mine: return []
        same = cat.index[(cat.category == cat.at[pid, "category"]).values]
        c = [(len(mine & set(self.attr.get(q, ()))), q) for q in same if q != pid and q not in unavail]
        c = [(s, q) for s, q in c if s > 0]
        key = (lambda x: (-x[0], -float(score.get(x[1], 0.0)))) if score is not None else (lambda x: -x[0])
        return [q for _, q in sorted(c, key=key)[:n]]


# ------------------------------------------------------------------ offline: fit / eval
def _load_training():
    from rt import q
    cat = q("SELECT product_id::String product_id, category::String category, subcategory::String sub, brand::String brand, "
            "price_eur::Float64 price, description::String description FROM shop.catalog")
    h = q("SELECT product_id::String product_id, countIf(event_type='view') v, countIf(event_type='add_to_cart') a, "
          "countIf(event_type='purchase') p FROM shop.history_events GROUP BY product_id")
    d = cat.merge(h, on="product_id")
    for c in "vap": d[c] = d[c].astype(float)
    return d


def fit():
    d = _load_training()
    pr = ColdPrior().fit(d)
    ART.write_text(json.dumps({"prior": pr.to_json(), "attrs": {r.product_id: list(attrs(r.description)) for r in d.itertuples()},
                               "fitted_on": f"shop.catalog ({len(d)} products) + shop.history_events (60 d)"}, separators=(",", ":")))
    print("saved", ART, len(pr.coef["p"]), "tokens")


def evaluate(seeds=(0, 1, 2)):
    from scipy.stats import spearmanr
    from sklearn.model_selection import KFold
    from rt import q
    d = _load_training(); y = d.p / d.v; g = d.p.sum() / d.v.sum()

    def report(name, pr, dd=d, T="p"):
        yy = dd[T] / dd.v; e = pr * dd[T].sum() / (pr * dd.v).sum() * dd.v; e0 = dd[T].sum() / dd.v.sum() * dd.v
        dev = lambda e: 2 * np.sum(np.where(dd[T] > 0, dd[T] * np.log(dd[T] / e), 0) - (dd[T] - e))
        top = pr.rank(pct=True) > 0.8; bot = pr.rank(pct=True) <= 0.5
        print(f"{name:34s} spearman {spearmanr(pr, yy)[0]:.3f}  in-category {np.mean([spearmanr(pr[x.index], yy[x.index])[0] for _, x in dd.groupby('category')]):.3f}"
              f"  deviance explained {1 - dev(e) / dev(e0):.3f}  rate top20% {dd[T][top].sum() / dd.v[top].sum():.4f}  bottom50% {dd[T][bot].sum() / dd.v[bot].sum():.4f}")

    print(f"== E-090a: 5-fold hold-out of products (N={len(d)}, {int(d.p.sum())} purchases, {int(d.v.sum())} views), mean of {len(seeds)} seeds")
    acc = {}
    for seed in seeds:
        P = {k: pd.Series(0.0, index=d.index) for k in ("subcategory", "sub+brand+price GLM", "tfidf kNN", "attribute GLM (this module)")}
        for tri, tei in KFold(5, shuffle=True, random_state=seed).split(d):
            tr, te = d.iloc[tri], d.iloc[tei]
            gg = tr.groupby("sub").agg(p=("p", "sum"), v=("v", "sum"))
            P["subcategory"].iloc[tei] = ((gg.p + 300 * g) / (gg.v + 300)).reindex(te["sub"]).fillna(g).values
            P["sub+brand+price GLM"].iloc[tei] = ColdPrior(inter=()).fit(tr.assign(description="")).predict(te.assign(description="")).cr.values
            P["tfidf kNN"].iloc[tei] = tfidf_knn_rate(tr.description, (tr.p / tr.v).values, te.description)
            P["attribute GLM (this module)"].iloc[tei] = ColdPrior().fit(tr).predict(te).cr.values
        for k, v in P.items(): acc.setdefault(k, []).append(v)
    for k, v in acc.items(): report(k, sum(v) / len(v))

    new = q("SELECT product_id::String product_id, argMax(category::String,ts::String) category, argMax(subcategory::String,ts::String) sub, "
            "argMax(brand::String,ts::String) brand, argMax(price_eur::Float64,ts::String) price, argMax(description::String,ts::String) description "
            "FROM shop.catalog_updates WHERE change::String='new_product' GROUP BY product_id")
    lv = q("SELECT product_id::String product_id, countIf(event_type='view') v, countIf(event_type='add_to_cart') a, countIf(event_type='purchase') p "
           "FROM shop.events GROUP BY product_id")
    for c in "vap": lv[c] = lv[c].astype(float)
    n = new.merge(lv, on="product_id"); n = n[n.v > 0].reset_index(drop=True)
    print(f"== E-090b: REAL launch test. Fit on the {len(d)} historical products, predict the {len(n)} products launched during the event "
          f"({int(n.v.sum())} live views, {int(n.p.sum())} purchases)")
    gg = d.groupby("sub").agg(p=("p", "sum"), v=("v", "sum"))
    report("subcategory", pd.Series(((gg.p + 300 * g) / (gg.v + 300)).reindex(n["sub"]).fillna(g).values), n)
    report("sub+brand+price GLM", ColdPrior(inter=()).fit(d.assign(description="")).predict(n.assign(description="")).cr, n)
    report("tfidf kNN", pd.Series(tfidf_knn_rate(d.description, (d.p / d.v).values, n.description)), n)
    full = ColdPrior().fit(d); report("attribute GLM (this module)", full.predict(n).cr, n)
    old = d.merge(lv, on="product_id", suffixes=("", "_l")); old = old[old.v_l > 0]
    print(f"   noise ceiling: historical rate of the SAME product vs its live rate, old products: spearman {spearmanr(old.p / old.v, old.p_l / old.v_l)[0]:.3f}")
    print(f"   attribute coverage: {np.mean([len(attrs(x)) == 2 for x in n.description]):.0%} of new descriptions have 2 known phrases")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "eval"
    {"fit": fit, "eval": evaluate}[cmd]()
