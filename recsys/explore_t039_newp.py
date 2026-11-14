"""T-039 replay (read-only): what the new-product arm changes. For requests after --cut, as of each request, builds
the r3 slate and the slate of the same weights plus `newp` (weights from --w, default the fitted file), and reports
how many slates change, how many products launched during the event are shown, and the purchases each slate is
expected to get under the model fitted BEFORE the cut (optimistic: the model grades its own choice).

    python lfm_build.py --pull --base lfm_coef_r3.json --add newp --out lfm_coef_np.json --cut "2026-11-14 17:10"
    python explore_t039_newp.py --cut "2026-11-14 17:10" [--known 1.96 --new 0.86] [--n 4000]
"""
import sys, json
import numpy as np, pandas as pd
import lfm, lfm_build as B


def arg(name, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def main():
    d, LF, aff, carts, buys = B.load()[:5]
    cut = pd.Timestamp(arg("--cut", str(d.ts.quantile(0.7))))
    I = B.impressions(d, LF, aff, carts, buys)
    base = json.loads((lfm.HERE / "lfm_coef_r3.json").read_text())
    judge = B.fit_add(I[I.ts < cut], base, ["newp"])                     # fitted before the cut only
    wk, wn = arg("--known", judge["known"]["w"]["newp"]), arg("--new", judge["new"]["w"]["newp"])
    print("judge fitted before", cut, {k: judge[k]["added"] for k in ("known", "new")}, "| arm weights known", wk, "new", wn)
    LF.set_arms([dict(tag="r3", file="lfm_coef_r3.json"), dict(tag="np", file="lfm_coef_r3.json", w=dict(known=dict(newp=wk), new=dict(newp=wn)))])
    S = LF.snap; catlog = getattr(aff, "catlog", None); newp = S.newp > 0
    rids = d.index[(d.ts >= cut)]; rng = np.random.default_rng(0); n = arg("--n", 4000)
    if len(rids) > n: rids = rng.choice(rids, n, replace=False)
    class AsOf:
        def __init__(self, ts): self.ts = ts
        def affinity_all(self, u, rv): return B.aff_asof(aff, u, rv, self.ts)
    res = []
    for r in d.loc[sorted(rids)].itertuples():
        st = B.replay_state(LF, aff, carts, buys, r.user_id, r.ts); b, lc, hc, bt, mix, mfu = st
        seg = "new" if r.new_user else "known"; sf = lfm.in_segment(r.device, r.region)
        req = dict(user_id=r.user_id, rv=r.rv, page=r.page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
        excl = ()
        if catlog is not None: excl = {S.ids[k] for k in np.nonzero(catlog.ineligible(r.ts))[0]}
        X = lfm.features(S, B.aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, bought_today=bt, seg=sf, mix=mix, mfu=mfu)
        def value(items):
            k = [S.row[p] for p in items]
            return float(B.p_buy(judge, seg, X[k], np.arange(1, len(k) + 1)).sum())
        a = LF.slate(req, st, AsOf(r.ts), exclude=excl, model="r3"); c = LF.slate(req, st, AsOf(r.ts), exclude=excl, model="np")
        if not a or not c: continue
        cold = bool(r.new_user) or any(p in S.row and newp[S.row[p]] for p in r.rv)
        res.append((seg, "home" if r.page == "home" or not r.rv else "page", cold, a != c, a[0] != c[0], len(set(c) - set(a)),
                    sum(newp[S.row[p]] for p in a), sum(newp[S.row[p]] for p in c), value(a), value(c), len(set(c)) == 10))
    R = pd.DataFrame(res, columns=["seg", "where", "cold", "changed", "slot1", "swapped", "new_r3", "new_np", "v_r3", "v_np", "valid"])
    g = R.groupby(["seg", "where", "cold"]).agg(n=("valid", "size"), valid=("valid", "mean"), changed=("changed", "mean"), slot1=("slot1", "mean"),
                                               swapped=("swapped", "mean"), new_r3=("new_r3", "mean"), new_np=("new_np", "mean"), v_r3=("v_r3", "mean"), v_np=("v_np", "mean"))
    for c in ("v_r3", "v_np"): g[c] = 100 * g[c]
    g["new_r3"] = 10 * g.new_r3; g["new_np"] = 10 * g.new_np          # % of impressions
    print("\nper request (new_* = % of impressions that are products launched during the event; v_* = expected purchases per 100 requests, model estimate):")
    print(g.round(3).to_string())


if __name__ == "__main__":
    main()
