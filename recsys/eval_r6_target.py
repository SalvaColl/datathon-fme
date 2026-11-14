"""Offline screening of the targeted r6 challenger (T-039, E-390). Read-only; never touches the writer.

    python lfm_build.py --pull --no-write        # or lfm_build.pull(): refresh data/lfm_*.parquet
    python eval_r6_target.py --from "2026-11-14 18:33:39.355" --to "2026-11-14 19:42:06.715"

What it does, on logged requests of the window only:
  1. Refuses to run if any learned part of r3 or r6 saw the window (lfm_build.leaks over every component).
  2. Rebuilds each request as of its time with the writer's 6-part state (lfm_build.replay_state).
  3. Cohort = returning shopper, product/category page, recent views. Inside it: where the bought / clicked product
     ranks among the 10 shown under the champion arm and under the challenger arm of POLICY, shopper-clustered bootstrap.
  4. Slates each arm would serve: products in common, first-slot changes; outside the cohort they must be identical.

It measures ranking inside slates our own policies chose. It is screening evidence, not a conversion estimate.
"""
from __future__ import annotations
import json, sys
import numpy as np, pandas as pd
import lfm, lfm_build as B, eval_slices as E

POLICY = "policy.r6_target_r3.json"


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def boot(delta, users, n_boot=2000, seed=0):
    """Mean of delta with a 95% interval from a bootstrap over shoppers."""
    s = pd.DataFrame(dict(d=np.asarray(delta, float), u=np.asarray(users))).groupby("u").d.agg(["sum", "count"])
    rng = np.random.default_rng(seed); k = len(s); idx = rng.integers(0, k, size=(n_boot, k))
    m = s["sum"].values[idx].sum(1) / s["count"].values[idx].sum(1)
    return float(s["sum"].sum() / s["count"].sum()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), float((m > 0).mean())


def main():
    t0, t1 = pd.Timestamp(arg("--from")), pd.Timestamp(arg("--to"))
    n_slates = int(arg("--slates", 4000))
    arms = json.loads((lfm.HERE / arg("--policy", POLICY)).read_text())["lfm_arms"]
    ctl, ch = arms[0], arms[1]; assert ch.get("mf") == "known_pages" and "mf" not in ctl
    for f in ("lfm_coef_r3.json", "lfm_coef_r6.json"):
        c = json.loads((lfm.HERE / f).read_text())
        if B.leaks(c, t0): raise SystemExit(f"{f} was fitted through {B.fitted_until(c)}: it saw the window that starts {t0}")
        print(f"{f}: every component fitted before {B.fitted_until(c)} < window start {t0}")
    d, LF, aff, carts, buys = B.load()
    print("data:", d.ts.min(), "..", d.ts.max(), "| window", t0, "..", t1)
    if d.ts.max() < t1: print("WARNING: the pulled data ends before the window does")
    d = d[(d.ts > t0) & (d.ts <= t1)]
    LF.set_arms(arms)
    w3, w6 = LF.alt[ctl["tag"]][0]["known"], LF.alt[ch["tag"]][0]["known"]
    assert np.array_equal(np.nonzero(w3 != w6)[0], [lfm.FEATS.index("mf")])            # the arms differ in the mf weight only
    slot3 = json.loads((lfm.HERE / "lfm_coef_r3.json").read_text())["known"]["slot"]

    I = B.impressions(d, LF, aff, carts, buys)
    I = I.merge(d[["user_id"]], left_on="rid", right_index=True); I["nrv"] = I.rid.map(d.rv.map(len))
    C = I[(~I.new_user) & I.page.isin(lfm.LQ_PAGES) & (I.nrv > 0) & (I.dead == 0)].copy()
    X = C[lfm.FEATS].values; C["z3"] = X @ w3; C["z6"] = X @ w6
    print(f"\ncohort (returning, product/category, recent views): {C.rid.nunique()} requests, {C.user_id.nunique()} shoppers, {len(C)} live impressions, "
          f"{int(C.clk.sum())} clicks, {int(C.buy.sum())} purchases; impressions with a factor score: {(C.mf != 0).mean():.1%}")
    for z in ("z3", "z6"):
        C["r" + z] = C.groupby("rid")[z].rank(ascending=False, method="average"); C["g" + z] = E.slot_gain(C, C[z].values, slot3)
    rows = []
    for name, lab in (("purchase", "buy"), ("click", "clk")):
        b = C[C[lab] == 1]
        if len(b) == 0: continue
        for metric, a3, a6 in (("MRR", 1 / b.rz3, 1 / b.rz6), ("first place", (b.rz3 <= 1).astype(float), (b.rz6 <= 1).astype(float)), ("slot-corrected gain (nats)", b.gz3, b.gz6)):
            m, lo, hi, p = boot((a6 - a3).values, b.user_id.values)
            rows.append((name, metric, len(b), b.user_id.nunique(), round(float(a3.mean()), 4), round(float(a6.mean()), 4), round(m, 4), round(lo, 4), round(hi, 4), round(p, 3)))
    T = pd.DataFrame(rows, columns=["event", "metric", "n", "shoppers", "r3", "r6", "r6 - r3", "lo95", "hi95", "share of resamples > 0"])
    pd.set_option("display.width", 250); print("\nranking inside the logged slates, cohort only (shopper-clustered bootstrap, 2000 resamples):\n", T.to_string(index=False))

    # slates each arm would serve
    class AsOf:
        def __init__(self, ts): self.ts = ts
        def affinity_all(self, u, rv): return B.aff_asof(aff, u, rv, self.ts)
    rng = np.random.default_rng(0); catlog = getattr(aff, "catlog", None); S = LF.snap
    target = (~d.new_user) & d.page.isin(lfm.LQ_PAGES) & (d.rv.map(len) > 0)
    def sample(idx): return sorted(rng.choice(idx, min(n_slates, len(idx)), replace=False), key=lambda i: d.ts[i])
    res = {}
    for name, idx in (("cohort", sample(d.index[target])), ("outside", sample(d.index[~target]))):
        out = []
        for r in d.loc[idx].itertuples():
            st = B.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            req = dict(user_id=r.user_id, rv=r.rv, page=r.page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
            excl = {S.ids[k] for k in np.nonzero(catlog.ineligible(r.ts))[0]} if catlog is not None else ()
            a = LF.slate(req, st, AsOf(r.ts), exclude=excl, model=ctl["tag"]); b = LF.slate(req, st, AsOf(r.ts), exclude=excl, model=ch["tag"])
            ok = all(s is not None and len(s) == 10 and len(set(s)) == 10 and not (set(s) & st[0]) and not (set(s) & set(excl)) for s in (a, b))
            out.append((a == b, len(set(a or ()) & set(b or ())), bool(a and b and a[0] == b[0]), ok, st[5] is not None))
        res[name] = pd.DataFrame(out, columns=["identical", "common", "same_first", "valid", "has_factors"])
    c, o = res["cohort"], res["outside"]
    print(f"\nslates, cohort ({len(c)} requests): {c.common.mean():.2f} of 10 products in common, first slot changes in {1 - c.same_first.mean():.1%}, "
          f"identical ordered slate in {c.identical.mean():.1%}; shopper has factors in {c.has_factors.mean():.1%}; valid (10 distinct, none bought, none out of stock): {c.valid.mean():.1%}")
    print(f"slates, outside the cohort ({len(o)} requests): identical ordered slate in {o.identical.mean():.1%} (must be 100%); valid: {o.valid.mean():.1%}")
    return T, res


if __name__ == "__main__":
    main()
