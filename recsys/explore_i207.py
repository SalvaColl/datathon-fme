"""I-207 / T-024 · Generalisation rehearsal for the final: returning shoppers scored as if they had NO history.

    python explore_i207.py                       # uses the cached data/lfm_*.parquet (run `python lfm_build.py --pull` first)
    python explore_i207.py --cut "2026-11-14 13:10"

Read-only and offline: no RawTree query, no file written, never touches the writer. Do NOT run it on the writer's machine.

Why: the final brings new shoppers, new products and new trends. Today a returning shopper is scored with the
"known" weights and features that lean on the 60-day history (attribute affinity, historical carts, already-bought and
stale filters). Tomorrow most shoppers will only have what they do during the session.

What it does, on the time hold-out of lfm_build (fit before --cut, test after), for RETURNING shoppers only:
  full      real features (history + today), "known" weights          -> what we serve today
  amn-known history removed (today's events and recent_views kept), "known" weights
  amn-new   history removed, "new" weights                            -> the candidate rule for the final
For each: AUC and mean reciprocal rank of the bought / clicked product among the 10 shown, by serving score.
It also reports the truly new shoppers with "new" weights as the reference level.

Reading it: (full - best amnesia row) is what the returning segment loses without history; amn-new vs amn-known says
which weights a shopper without history should get.

Limits (state them when quoting the numbers): the labels come from slates chosen WITH history, so products that
history pushed up are over-represented among the 10 shown; it measures ranking inside the shown slate, not the slate
the amnesic model would have built; clicks/purchases are the noisy observable, not the hidden model's expectation.
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd
import attr_affinity, lfm
import lfm_build as lb


def aff_amnesia(aff, u, rv, ts):
    """lfm_build.aff_asof without the 60-day history: only today's closed view buckets and the request's recent views."""
    vec = np.zeros(20, dtype=np.float32)
    for p in rv:
        k = aff.pid.get(p)
        if k is not None: vec = vec + aff._rows[k]
    ts = np.datetime64(ts)
    for t, k, n in getattr(aff, "today", {}).get(u, ()):
        if t < ts: vec = vec + aff.A[k] * n
    return (aff.A @ vec + attr_affinity.SHRINK * attr_affinity.NEUTRAL) / (vec.sum() + attr_affinity.SHRINK)


def state_amnesia(carts, buys, u, ts):
    """lfm_build.state_asof without historical carts / purchases: only today's events before the request."""
    ts = np.datetime64(ts)
    bt = {i for i, t in buys.get(u, {}).items() if t < ts}
    lc = {i for i, t in carts.get(u, {}).items() if t < ts} - bt
    return bt, lc, {}, bt


def impressions_amnesia(d, LF, aff, carts, buys):
    """Same frame as lfm_build.impressions for the requests in d, with the history removed."""
    S = LF.snap; rows = []; meta = []
    for r in d.itertuples():
        b, lc, hc, bt = state_amnesia(carts, buys, r.user_id, r.ts)
        idx = [S.row.get(p, -1) for p in r.shown]
        X = lfm.features(S, aff_amnesia(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, idx=[k if k >= 0 else 0 for k in idx],
                         bought_today=bt, seg=lfm.in_segment(r.device, r.region))
        for s, (p, k) in enumerate(zip(r.shown, idx)):
            rows.append(X[s]); meta.append((r.Index, s + 1, int(p == r.clicked), int(p == r.purchased), int(k < 0 or p in b)))
    I = pd.concat([pd.DataFrame(meta, columns=["rid", "slot", "clk", "buy", "dead"]), pd.DataFrame(np.array(rows), columns=lfm.FEATS)], axis=1)
    return I.merge(d[["new_user", "page", "ts"]], left_on="rid", right_index=True)


def score(name, a, coef, seg):
    """One report row: ranking of the bought / clicked product by the serving score of weights `seg` on frame `a`."""
    from sklearn.metrics import roc_auc_score
    z = a[lfm.FEATS].values @ np.array([coef[seg]["w"].get(f, 0.0) for f in lfm.FEATS])
    g = pd.DataFrame(dict(rid=a.rid.values, z=z, buy=a.buy.values, clk=a.clk.values))
    g["rank"] = g.groupby("rid").z.rank(ascending=False, method="average")
    auc = lambda y: float(roc_auc_score(y, z)) if 0 < y.sum() < len(y) else float("nan")
    mrr = lambda m: float((1 / g[m]["rank"]).mean()) if m.any() else float("nan")
    top1 = lambda m: float((g[m]["rank"] <= 1).mean()) if m.any() else float("nan")
    return (name, seg, a.rid.nunique(), int(a.buy.sum()), int(a.clk.sum()), auc(g.buy), auc(g.clk), mrr(g.buy == 1), mrr(g.clk == 1), top1(g.clk == 1))


def boot(a_full, a_amn, coef, n=200, seed=0):
    """Request-level bootstrap of the click-MRR differences (full-known minus amn-new, amn-new minus amn-known)."""
    def rr(a, seg):
        z = a[lfm.FEATS].values @ np.array([coef[seg]["w"].get(f, 0.0) for f in lfm.FEATS])
        g = pd.DataFrame(dict(rid=a.rid.values, z=z, clk=a.clk.values)); g["rank"] = g.groupby("rid").z.rank(ascending=False, method="average")
        return (1 / g[g.clk == 1].set_index("rid")["rank"])
    f, an, ak = rr(a_full, "known"), rr(a_amn, "new"), rr(a_amn, "known")
    D = pd.DataFrame(dict(loss=f - an, new_vs_known=an - ak)).dropna()
    rng = np.random.default_rng(seed); out = {}
    for c in D.columns:
        v = D[c].values; m = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(n)]
        out[c] = (float(v.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), len(v))
    return out


def main():
    d, LF, aff, carts, buys = lb.load()
    I = lb.impressions(d, LF, aff, carts, buys)
    cut = pd.Timestamp(sys.argv[sys.argv.index("--cut") + 1]) if "--cut" in sys.argv else d.ts.quantile(0.7)
    coef = lb.fit(I[I.ts < cut])
    test = d[(d.ts >= cut)]
    known, new = test[~test.new_user.astype(bool)], test[test.new_user.astype(bool)]
    print(f"time split at {cut} | hold-out requests: returning {len(known)}, new {len(new)}", flush=True)
    A = impressions_amnesia(known, LF, aff, carts, buys)
    full = I[I.rid.isin(known.index)]
    rows = []
    for label, pages in (("all pages", None), ("product/category", False), ("home", True)):
        sel = lambda a: a if pages is None else a[(a.page == "home") == pages]
        f, am = sel(full[full.dead == 0]), sel(A[A.dead == 0])
        if not len(f): continue
        rows += [(label,) + score("full", f, coef, "known"), (label,) + score("amn-known", am, coef, "known"), (label,) + score("amn-new", am, coef, "new")]
        nw = sel(I[I.rid.isin(new.index) & (I.dead == 0)])
        if len(nw): rows.append((label,) + score("new shoppers (reference)", nw, coef, "new"))
    R = pd.DataFrame(rows, columns=["pages", "features", "weights", "requests", "buys", "clicks", "auc_buy", "auc_click", "mrr_buy", "mrr_click", "top1_click"])
    print("\nRanking inside the 10 shown, returning shoppers (mrr = mean reciprocal rank; top1 = clicked product ranked first):\n", R.round(3).to_string(index=False))
    b = boot(full[full.dead == 0], A[A.dead == 0], coef)
    for k, (m, lo, hi, n) in b.items():
        print(f"\nclick-MRR difference {k}: {m:+.3f}  (95% bootstrap {lo:+.3f} .. {hi:+.3f}, {n} clicked requests)")
    print("\nloss = full(known weights) - amnesia(new weights): what the returning segment loses without history."
          "\nnew_vs_known > 0 with an interval above 0 -> serve shoppers without history with the 'new' weights.")
    dropped = int((full.dead == 1).sum()) - int((A.dead == 1).sum())
    print(f"\nimpressions that only the history marks as dead (bought before / stale): {dropped} of {len(full)}"
          f" with {int(full[(full.dead == 1)].buy.sum())} purchases among all dead ones")


if __name__ == "__main__":
    main()
