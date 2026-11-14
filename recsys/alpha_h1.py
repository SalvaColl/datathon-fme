"""T-SA01 / H1: do today's CARTS (and exact phrase pairs of today's purchases) add predictive signal beyond lfm v2?

    cd recsys
    python lfm_build.py --pull     # Javi's read-only pull (feedback, requests, today's carts/purchases/views, catalogue)
    python alpha_h1.py             # reuses lfm_build.load()/impressions(): lfm v2 features as of each request

lfm v2 (T-021) already has: aff10 (phrase affinity, history + today's views + recent views), cl (product carted today),
chn (carted in history), nbp (phrases shared with something BOUGHT today, 0/1/2), bsub (same subcategory as a purchase).
One new family, all strictly before the request ts:
    ncp  = max phrases shared with a product carted today and not bought (the product itself excluded), 0/1/2
    csub = same subcategory as a product carted today and not bought (itself excluded)
    nbp2 = shares BOTH phrases with something bought today (exact pair; nbp is linear in the count)
Model: lfm_build's recipe (logistic on clicks, purchases x BUY_W, C_REG, log slot; one fit per known/new). Time split:
fit before the cut (70% of requests), test after. Paired bootstrap over test requests (1,000 draws) of the purchase
log-likelihood gain. Negative control: the same family computed from ANOTHER user's carts/purchases (random
permutation within the same new/known segment). Rows on dead products are excluded as in lfm_build.
Observational: impressions are what our policies showed; this is predictive value among shown items, not a
counterfactual conversion estimate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lfm, lfm_build as LB  # noqa: E402

NEW = ["ncp", "csub", "nbp2"]
SEED, DRAWS = 20261114, 1000


def family(d, LF, carts, buys, perm=None):
    """New-feature rows aligned with lfm_build.impressions() (same request order, same slot order)."""
    S = LF.snap; out = []
    for r in d.itertuples():
        u = perm.get(r.user_id, r.user_id) if perm else r.user_id
        _, lc, _, bt = LB.state_asof(LF, carts, buys, u, r.ts)
        idx = np.array([S.row.get(p, -1) for p in r.shown]); ok = idx >= 0; k = np.where(ok, idx, 0)
        f = np.zeros((len(idx), 3))
        lcr = np.array([S.row[p] for p in lc if p in S.row], dtype=int)
        if len(lcr):
            sh = S.A[k] @ S.A[lcr].T                                   # shared phrases with each carted product
            same = k[:, None] == lcr[None, :]
            sh = np.where(same, 0, sh); f[:, 0] = sh.max(axis=1)
            f[:, 1] = ((S.sub[k][:, None] == S.sub[lcr][None, :]) & ~same).any(axis=1)
        btr = np.array([S.row[p] for p in bt if p in S.row], dtype=int)
        if len(btr):
            f[:, 2] = ((S.A[k] @ S.A[btr].T) >= 2).any(axis=1)
        f[~ok] = 0
        out.append(f)
    return pd.DataFrame(np.vstack(out), columns=NEW)


def fit_predict(train, test, cols):
    from sklearn.linear_model import LogisticRegression
    p = np.zeros(len(test)); coefs = {}
    for new in (False, True):
        a, b = train[train.new_user == new], test.new_user.values == new
        X = a[cols + ["ls"]].values
        m = LogisticRegression(C=LB.C_REG, max_iter=5000).fit(X, a.clk, sample_weight=np.where(a.buy == 1, LB.BUY_W, 1.0))
        z = X @ m.coef_[0] + m.intercept_[0]
        c = LogisticRegression(C=100.0, max_iter=5000).fit(z.reshape(-1, 1), a.buy)
        zt = test.loc[b, cols + ["ls"]].values @ m.coef_[0] + m.intercept_[0]
        p[b] = 1 / (1 + np.exp(-(c.intercept_[0] + c.coef_[0][0] * zt)))
        coefs["new" if new else "known"] = dict(zip(cols[-3:], m.coef_[0][len(cols) - 3:len(cols)].round(3).tolist()))
    return np.clip(p, 1e-9, 1 - 1e-9), coefs


def main():
    d, LF, aff, carts, buys = LB.load()
    I = LB.impressions(d, LF, aff, carts, buys)
    F = family(d, LF, carts, buys)
    rng = np.random.default_rng(SEED)
    perm = {}
    for new in (False, True):
        us = sorted(set(d.user_id[d.new_user == new]))
        perm.update(dict(zip(us, rng.permutation(us))))
    Fn = family(d, LF, carts, buys, perm=perm).add_suffix("_neg")
    I = pd.concat([I.reset_index(drop=True), F, Fn], axis=1)
    I = I[I.dead == 0].copy()
    rids = np.sort(I.rid.unique()); cut = rids[int(0.7 * len(rids))]
    tr, te = I[I.rid < cut], I[I.rid >= cut].copy()
    base = list(lfm.FEATS)
    res = {"impressions_train": len(tr), "impressions_test": len(te), "buys_test": int(te.buy.sum()), "clicks_test": int(te.clk.sum()),
           "test_from": str(d.ts.iloc[cut]), "feature_prevalence_test": {c: round(float((te[c] > 0).mean()), 4) for c in NEW}}
    preds = {}
    for name, cols in (("lfm_v2", base), ("v2+family", base + NEW), ("v2+family_negctl", base + [c + "_neg" for c in NEW])):
        p, coefs = fit_predict(tr, te, cols); preds[name] = p; res[f"coef_{name}"] = coefs
    from sklearn.metrics import roc_auc_score
    ll = {k: np.where(te.buy == 1, np.log(p), np.log1p(-p)) for k, p in preds.items()}
    te_rid = te.rid.values; ur = np.unique(te_rid); pos = {r: k for k, r in enumerate(ur)}; ix = np.array([pos[r] for r in te_rid])
    by_req = {k: np.bincount(ix, weights=v, minlength=len(ur)) for k, v in ll.items()}
    for k in preds:
        seg = {}
        for new in (False, True):
            m = te.new_user.values == new
            seg["new" if new else "known"] = dict(auc_buy=round(float(roc_auc_score(te.buy[m], preds[k][m])), 4), loglik_buy=round(float(ll[k][m].sum()), 1))
        res[k] = dict(auc_buy=round(float(roc_auc_score(te.buy, preds[k])), 4), loglik_buy=round(float(ll[k].sum()), 1), by_segment=seg)
        if k != "lfm_v2":
            diff = by_req[k] - by_req["lfm_v2"]
            boot = [diff[rng.integers(0, len(diff), len(diff))].sum() for _ in range(DRAWS)]
            res[k]["delta_loglik_vs_v2"] = round(float(diff.sum()), 1)
            res[k]["delta_CI95"] = [round(float(np.percentile(boot, 2.5)), 1), round(float(np.percentile(boot, 97.5)), 1)]
            res[k]["nats_per_1000_test_buys"] = round(1000 * float(diff.sum()) / max(1, int(te.buy.sum())), 1)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
