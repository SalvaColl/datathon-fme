"""Build and validate the attr_model artefact (T-017 / E-170, E-171). READ-ONLY on RawTree (SELECTs only).

    python qrank_build.py --pull          # once: downloads data/qr_*.parquet (shared with qrank)
    python attr_model_build.py            # validate (time split + simulated new products) and save data/attr_model.joblib

Time order, no future data in any feature:
  before 25 Oct      -> attribute priors, count corrections, carousel quality (what the model sees as `lq`)
  25 Oct .. 7 Nov    -> training of the context model on the randomized old carousel
  8 Nov .. 14 Nov    -> test
Simulated new products: a random 20% of the catalogue (H) is hidden from every fit of the first period and gets
quality from attributes only (no counts). The context model is trained with H hidden, so it also learns how far
to trust an attribute-only quality.
Simulated new shoppers: nothing to simulate. The model never reads a user id or stored history, only the
`recent_views` of the request, so every shopper in train and test is scored as a first-time shopper.
"""
import json, sys, warnings
import numpy as np, pandas as pd, joblib
from scipy import sparse
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, log_loss
import attr_model as am
import qrank, qrank_build

warnings.filterwarnings("ignore"); pd.set_option("display.width", 220)
CUT_TEST, SEED, HOLD = "2026-11-08", 0, 0.20


def glm(C, attrs, sub_median, num, den, alpha=1e-5):
    """Poisson GLM of num/den on attribute tokens (rows with den > 0). -> (coef dict, intercept)."""
    ok = den > 0; D = C[ok]
    T = [am.tokens(c, s, b, p, sub_median.get(s), attrs.get(i, ())) for i, c, s, b, p in zip(D.index, D.category, D["sub"], D.brand, D.price)]
    vocab = {}
    for t in T:
        for x in t: vocab.setdefault(x, len(vocab))
    ri = [i for i, t in enumerate(T) for _ in t]; ci = [vocab[x] for t in T for x in t]
    X = sparse.csr_matrix((np.ones(len(ri)), (ri, ci)), shape=(len(T), len(vocab)))
    m = PoissonRegressor(alpha=alpha, max_iter=2000).fit(X, (num / den)[ok], sample_weight=den[ok])
    return {k: float(m.coef_[j]) for k, j in vocab.items()}, float(m.intercept_)


def fit_quality(C, attrs, org, car, fit_items):
    """org: frame v,p (organic) and car: frame E,b (carousel, slot-1 equivalents), indexed by product.
    Every fit uses `fit_items` only; counts of all products are stored (compute() can mask them)."""
    sub_median = C.groupby("sub").price.median().to_dict()
    F = C.loc[C.index.isin(fit_items)]
    o = org.reindex(F.index).fillna(0.0); c = car.reindex(F.index).fillna(0.0)
    V = float(org.v.sum())
    coef_cr, b_cr = glm(F, attrs, sub_median, o.p.values, o.v.values)
    # Popularity prior = the average product (share 1/N). Predicting it from attributes was tried and REJECTED (E-170a):
    # attributes explain only 29% of log-views and the fitted prior made never-seen products worse (deviance 0.61 vs 0.66).
    coef_pop, b_pop = {}, float(np.log(o.v.mean() / V))
    p = dict(coef_cr=coef_cr, b_cr=b_cr, coef_pop=coef_pop, b_pop=b_pop, sub_median=sub_median, V_hist=V,
             hist=org[["v", "p"]].join(car[["E", "b"]], how="outer").fillna(0.0), cat={}, beta=[1.0, 0.0, 0.0, 0.0], b0=0.0)
    # carousel GLM on the parts: category intercept + conversion prior, popularity residual, conversion residual
    t = am.Quality(p).compute(F, attrs)
    cats = sorted(C.category.unique()); M = np.column_stack([pd.get_dummies(F.category).reindex(columns=cats, fill_value=0).values.astype(float),
                                                              t[["la_cr", "r_v", "r_cr"]].values])
    ok = c.E.values > 0
    m = PoissonRegressor(alpha=1e-4, max_iter=3000).fit(M[ok], (c.b / c.E).values[ok], sample_weight=c.E.values[ok])
    b = [float(x) for x in m.coef_[-3:]]
    p.update(cat={k: float(x) for k, x in zip(cats, m.coef_[:len(cats)])}, beta=[b[0], 0.0, b[1], b[2]], b0=float(m.intercept_))
    return am.Quality(p)


def session_features(h, index):
    rows = []
    for r in h.itertuples():
        rows.append(index.features(np.array([index.ix[i] for i in r.shown]), [index.ix[x] for x in r.rv], r.page, 0))
    X = np.vstack(rows); X[:, 0] = np.tile(np.arange(10), len(h))
    return X


def rank_metrics(p, y, group_size=10):
    """hit@1, hit@3, MRR of the purchased item inside its logged slate (sessions with a purchase)."""
    P = p.reshape(-1, group_size); Y = y.reshape(-1, group_size); has = Y.any(1)
    rk = (P[has] > (P[has] * Y[has]).sum(1, keepdims=True)).sum(1) + 1
    return dict(n=int(has.sum()), hit1=float((rk == 1).mean()), hit3=float((rk <= 3).mean()), mrr=float((1 / rk).mean()))


def main():
    C = pd.read_parquet("data/catalog.parquet").set_index("product_id")
    attrs = {p: tuple(a) for p, a in json.load(open("cold_prior.json"))["attrs"].items()}
    its = pd.read_parquet("data/qr_itemslot.parquet"); org = pd.read_parquet("data/qr_organic.parquet").rename(columns={"i": "item"})
    pos = its.groupby("slot").agg(n=("n", "sum"), b=("b", "sum")); pos = (pos.b / pos.n); pos = (pos / pos.iloc[0]).values
    its["E"] = its.n * pos[its.slot.values]
    car = lambda d: d.groupby("item")[["E", "b"]].sum().astype(float)
    orgf = lambda d: d.groupby("item")[["v", "p"]].sum().astype(float)
    rng = np.random.default_rng(SEED); H = set(C.index[rng.random(len(C)) < HOLD]); known = [i for i in C.index if i not in H]
    print(f"catalogue {len(C)}, simulated new products {len(H)}")

    # ---------- period 1: quality as of 25 Oct ----------
    Q1 = fit_quality(C, attrs, orgf(org[org.pre == 1]), car(its[its.pre == 1]), known)
    fmt = lambda b: "exp(category + %.2f*conversion_prior + %.2f*popularity_residual + %.2f*conversion_residual)" % (b[0], b[2], b[3])
    print("carousel quality =", fmt(Q1.p["beta"]))
    t_full = Q1.compute(C, attrs); t_mask = Q1.compute(C, attrs, masked=H); t_attr = Q1.compute(C, attrs, use_counts=False)
    post = car(its[its.pre == 0]).reindex(C.index).fillna(0.0)

    def dev(name, lq, sel):
        ok = (post.E.values > 0) & sel; b = post.b.values[ok]; E = post.E.values[ok]
        e = np.exp(lq[ok]) * E; e *= b.sum() / e.sum(); e0 = b.sum() / E.sum() * E
        d = lambda e: 2 * np.sum(np.where(b > 0, b * np.log(np.maximum(b, 1e-12) / e), 0) - (b - e))
        from scipy.stats import spearmanr
        big = E >= 200
        print(f"  {name:58s} N={ok.sum():4d} purchases {int(b.sum()):5d}  deviance explained {1 - d(e) / d(e0):.3f}  spearman(E>=200, n={big.sum()}) {spearmanr(lq[ok][big], (b / E)[big])[0]:.3f}")
    inH = C.index.isin(list(H))
    print("E-170a quality as of 25 Oct vs carousel purchases 25 Oct-14 Nov (non-viewed impressions, slot-corrected):")
    cat_only = np.log((post.b.groupby(C.category).transform("sum") / post.E.groupby(C.category).transform("sum")).values)
    dev("category only", cat_only, ~inH); dev("attributes only, known products", t_attr.lq.values, ~inH)
    dev("attributes + counts (deployed form), known products", t_full.lq.values, ~inH)
    dev("category only, SIMULATED NEW products", cat_only, inH)
    dev("attributes only, SIMULATED NEW products (never fitted)", t_mask.lq.values, inH)
    dev("attributes + counts, same products if they were known", t_full.lq.values, inH)

    # ---------- period 2/3: context model ----------
    h = pd.read_parquet("data/qr_sessions.parquet"); h = h[[len(r) > 0 for r in h.rv]].reset_index(drop=True)
    I = am.Index(C, t_mask.lq.values, attrs)
    X = session_features(h, I)
    y = np.concatenate([[i == r.purchased for i in r.shown] for r in h.itertuples()])
    shown_ix = np.concatenate([[I.ix[i] for i in r.shown] for r in h.itertuples()])
    tr = np.repeat((h.ts.str[:10] < CUT_TEST).values, 10); te = ~tr
    hgb = lambda: HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=300, l2_regularization=1.0, random_state=0)
    model = hgb().fit(X[tr], y[tr])
    Xte, yte = X[te], y[te]
    buyH = np.repeat((yte.reshape(-1, 10) * inH[shown_ix[te]].reshape(-1, 10)).any(1), 10)      # sessions whose purchased item is a simulated new product
    anyH = np.repeat(inH[shown_ix[te]].reshape(-1, 10).any(1), 10)

    def score(m, Xm, cols=None):
        Z = Xm.copy(); Z[:, 0] = 0                              # same slot for every item: rank by the item, not by where it was shown
        return m.predict_proba(Z if cols is None else Z[:, cols])[:, 1]

    def with_lq(lq):
        Z = Xte.copy(); Z[:, 1] = lq[shown_ix[te]]; return Z

    def line(name, p):
        a = rank_metrics(p, yte); b = rank_metrics(p[buyH], yte[buyH]); c = rank_metrics(p[~buyH], yte[~buyH])
        print(f"  {name:66s} all N={a['n']} hit@1 {a['hit1']:.3f} hit@3 {a['hit3']:.3f} MRR {a['mrr']:.3f} | bought item is NEW N={b['n']} hit@1 {b['hit1']:.3f} MRR {b['mrr']:.3f} | bought item known N={c['n']} hit@1 {c['hit1']:.3f}")
        return a

    p_raw = model.predict_proba(Xte)[:, 1]
    print(f"\nE-170b context model, test {CUT_TEST}..14 Nov: sessions {te.sum() // 10}, purchases {int(yte.sum())}, AUC {roc_auc_score(yte, p_raw):.4f}, "
          f"log-loss {log_loss(yte, p_raw):.5f} (constant {log_loss(yte, np.full(len(yte), y[tr].mean())):.5f}); random hit@1 would be 0.100")
    res = {}
    res["attr"] = line("attr_model, 20% products new (as trained)", score(model, Xte))
    res["attr_full"] = line("attr_model, every product known (deployed form)", score(model, with_lq(t_full.lq.values)))
    res["attr_only"] = line("attr_model, EVERY product new (attributes only, no counts)", score(model, with_lq(t_attr.lq.values)))
    base11 = list(range(11))
    m11 = hgb().fit(X[tr][:, base11], y[tr])
    res["no_phr"] = line("ablation: same without phrase features (shl, aff)", score(m11, Xte, base11))
    # qrank reference: per-ID quality (qrank_build.quality on the same first period), 11 features
    orgq = pd.read_parquet("data/qr_organic.parquet")
    q_hold, _ = qrank_build.quality(C, pd.read_parquet("data/qr_itemslot.parquet").query("pre == 1"), orgq[orgq.pre == 1])
    lq_id = np.log(q_hold.reindex(C.index)).values
    Xq = X.copy(); Xq[:, 1] = lq_id[shown_ix]
    mq = hgb().fit(Xq[tr][:, base11], y[tr])
    res["qrank"] = line("qrank (per-ID quality), every product known", score(mq, Xq[te], base11))
    lq_new = pd.Series(np.where(inH, np.nan, lq_id), index=C.index)
    lq_new = lq_new.fillna(lq_new.groupby(C["sub"]).transform("median")).values           # qrank's rule for a product without history
    Zq = Xq[te].copy(); Zq[:, 1] = lq_new[shown_ix[te]]
    res["qrank_new"] = line("qrank, 20% products new (subcategory median, its own rule)", score(mq, Zq, base11))
    mq13 = hgb().fit(Xq[tr], y[tr])
    res["qrank_phr"] = line("qrank per-ID quality + phrase features, every product known", score(mq13, Xq[te]))

    # calibration of the deployed form by phrase features (does the model capture the session-phrase effect?)
    pf = model.predict_proba(with_lq(t_full.lq.values))[:, 1]
    t = pd.DataFrame({"y": yte, "p": pf, "shl": Xte[:, 11], "viewed": (Xte[:, 2] + Xte[:, 3]) > 0})
    print("\n  test calibration, non-viewed impressions, by phrases shared with the last view:")
    print(t[~t.viewed].groupby("shl").agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")).round(5).to_string())

    # ---------- deploy: quality from ALL history, context model from the time split ----------
    QD = fit_quality(C, attrs, orgf(org), car(its), list(C.index))
    meta = dict(FE=am.FE, cut_test=CUT_TEST, hold=HOLD, seed=SEED, pos=pos.tolist(), beta=QD.p["beta"], results=res)
    joblib.dump({"model": model, "quality": QD.p, "attrs": attrs, "meta": meta}, "data/attr_model.joblib", compress=3)
    print("\ndeploy quality:", fmt(QD.p["beta"]), "; saved data/attr_model.joblib")


if __name__ == "__main__":
    main()
