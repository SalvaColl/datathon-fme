"""Build and validate the qrank artefact (T-015 / E-081). READ-ONLY on RawTree (SELECTs only).

    python qrank_build.py --pull     # download aggregates (~1 min), then build + validate
    python qrank_build.py            # reuse cached data/qr_*.parquet

Steps (time-ordered, no future data in any feature):
 1. q_holdout: item quality from carousel impressions BEFORE 25 Oct where the item was NOT in recent_views,
    corrected for slot, shrunk towards a prior fitted on organic counts before 25 Oct.
 2. Context model (small HistGradientBoosting, 11 readable features) trained on a 1/1 sample of the randomized
    carousel log 25 Oct - 7 Nov, tested on 8 - 14 Nov: AUC, log-loss, calibration (overall and viewed x slot).
 3. Policy check on the holdout: expected conversion (by the model) of the logged slates vs qrank slates.
 4. q_deploy from ALL history -> data/qrank.joblib (model from step 2 + q_deploy).

Bias notes: the old policy was "best sellers + randomness inside the category of the last view", with logged
propensities > 0 for the items it could show; qrank only ranks items of that same category, so it stays where
the log has support. Step 3 is a model-based estimate (not IPS) and inherits any model error; the live
leaderboard block is the real test.
"""
import sys
import numpy as np, pandas as pd, joblib
from sklearn.linear_model import PoissonRegressor
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, log_loss
import qrank
from qrank import FE, feature_rows

pd.set_option("display.width", 220)
CUT_Q, CUT_TEST, KAPPA = "2026-10-25", "2026-11-08", 300.0


def pull():
    from rt import q
    its = []
    for k in range(8):   # item x slot x period exposure of NON-viewed impressions, product/category pages
        its.append(q(f"""SELECT item, slot, pre, toUInt32(count()) n, toUInt32(countIf(purchased = item)) b FROM (
          SELECT arrayJoin(arrayZip(arrayMap(x -> x::String, shown::Array(Dynamic)), range(10))) t, t.1 item, t.2 slot,
                 ts::DateTime64(3) < '{CUT_Q}' pre, purchased::String purchased,
                 arrayMap(x -> x.product_id::String, recent_views::Array(Dynamic)) rv
          FROM shop.history_sessions WHERE context.page::String != 'home' AND cityHash64(request_id::String) % 8 = {k})
          WHERE NOT has(rv, item) GROUP BY item, slot, pre"""))
    pd.concat(its).groupby(["item", "slot", "pre"], as_index=False).sum().to_parquet("data/qr_itemslot.parquet")
    q(f"""SELECT product_id::String i, ts::DateTime64(3) < '{CUT_Q}' pre, toUInt32(countIf(event_type::String='view')) v,
      toUInt32(countIf(event_type::String='add_to_cart')) a, toUInt32(countIf(event_type::String='purchase')) p
      FROM shop.history_events GROUP BY i, pre""").to_parquet("data/qr_organic.parquet")
    hs = [q(f"""SELECT ts::String ts, context.page::String page, arrayMap(x -> x.product_id::String, recent_views::Array(Dynamic)) rv,
      arrayMap(x -> x::String, shown::Array(Dynamic)) shown, purchased::String purchased FROM shop.history_sessions
      WHERE ts::DateTime64(3) >= '{CUT_Q}' AND context.page::String != 'home' AND cityHash64(request_id::String) % 16 = {k}""") for k in range(16)]
    pd.concat(hs).to_parquet("data/qr_sessions.parquet")
    print("pulled")


def quality(C, its, org):
    """Slot-corrected purchase rate per item with empirical-Bayes shrinkage to a prior from organic counts."""
    pos = its.groupby("slot").agg(n=("n", "sum"), b=("b", "sum")); pos = (pos.b / pos.n); pos = (pos / pos.iloc[0]).values
    it = its.assign(E=its.n * pos[its.slot.values]).groupby("item").agg(E=("E", "sum"), b=("b", "sum"))
    X = C.join(org.groupby("i")[["v", "a", "p"]].sum()).join(it).fillna(0)
    M = pd.concat([np.log1p(X[["v", "a", "p"]]), np.log(X[["price"]]), np.log((X.p + 1) / (X.v + 50)).rename("cr"),
                   pd.get_dummies(X.category).astype(float)], axis=1)
    ex = X.E > 0
    prior = PoissonRegressor(alpha=1e-4, max_iter=2000).fit(M[ex], (X.b / X.E)[ex], sample_weight=X.E[ex]).predict(M)
    return ((X.b + KAPPA * prior) / (X.E + KAPPA)).clip(lower=1e-6), pos


def main():
    if "--pull" in sys.argv: pull()
    C = pd.read_parquet("data/catalog.parquet").set_index("product_id")
    its = pd.read_parquet("data/qr_itemslot.parquet"); org = pd.read_parquet("data/qr_organic.parquet")
    q_hold, pos = quality(C, its[its.pre == 1], org[org.pre == 1])
    q_all, _ = quality(C, its, org)
    print("slot curve (non-viewed):", pos.round(3)); print("q holdout vs deploy rank corr:", round(q_hold.corr(q_all, method="spearman"), 3))
    sub, brand, price, lq = C["sub"].to_dict(), C.brand.to_dict(), C.price.to_dict(), np.log(q_hold).to_dict()
    h = pd.read_parquet("data/qr_sessions.parquet")
    h = h[[len(r) > 0 for r in h.rv]]
    Xs = np.vstack([feature_rows(list(r.shown), list(r.rv), r.page, 0, lq, sub, brand, price) for r in h.itertuples()])
    Xs[:, 0] = np.tile(np.arange(10), len(h))
    y = np.concatenate([[i == r.purchased for i in r.shown] for r in h.itertuples()])
    day = np.repeat(h.ts.str[:10].values, 10); tr = day < CUT_TEST
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=300,
                                           l2_regularization=1.0, random_state=0).fit(Xs[tr], y[tr])
    p = model.predict_proba(Xs[~tr])[:, 1]; yt = y[~tr]; viewed = (Xs[~tr][:, 2] + Xs[~tr][:, 3]) > 0; slot = Xs[~tr][:, 0]
    print(f"\nholdout {CUT_TEST}..: impressions {len(yt)}, purchases {int(yt.sum())}, AUC {roc_auc_score(yt, p):.4f}, "
          f"log-loss {log_loss(yt, p):.5f} (constant rate {log_loss(yt, np.full(len(yt), y[tr].mean())):.5f})")
    t = pd.DataFrame({"y": yt, "p": p, "viewed": viewed, "slot": slot})
    print(t.assign(bin=pd.qcut(t.p, [0, .5, .8, .95, .99, .999, 1])).groupby("bin", observed=True).agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")).round(5).to_string())
    print(t[t.slot < 3].groupby(["viewed", "slot"]).agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")).round(4).to_string())
    # policy check on holdout sessions (model-based)
    R = qrank.Ranker(model, q_hold.to_dict(), viewed_factor=1.0); R.set_catalog(C)   # history: no live recalibration
    hh = h[h.ts >= CUT_TEST].sample(4000, random_state=0)
    res = R.slates([{"rv": list(r.rv), "page": r.page} for r in hh.itertuples()], with_scores=True)
    logged = [model.predict_proba(np.column_stack([np.arange(10), feature_rows(list(r.shown), list(r.rv), r.page, 0, lq, sub, brand, price)[:, 1:]]))[:, 1].sum() for r in hh.itertuples()]
    new = [sum(x[1]) for x in res if x is not None]
    has_last = np.mean([r.rv[-1] in x[0] for r, x in zip(hh.itertuples(), res) if x is not None])
    print(f"\npolicy check, {len(new)} holdout sessions: actual conversion of logged slates {100 * (hh.purchased != '').mean():.2f}% | "
          f"model on logged slates {100 * np.mean(logged):.2f}% | model on qrank slates {100 * np.mean(new):.2f}% | qrank shows last view in {has_last:.2f}")
    joblib.dump({"model": model, "q": q_all.to_dict(), "meta": {"FE": FE, "cut_q": CUT_Q, "cut_test": CUT_TEST, "pos": pos.tolist()}}, "data/qrank.joblib", compress=3)
    print("saved data/qrank.joblib")


if __name__ == "__main__":
    main()
