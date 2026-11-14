"""og1: lfm's features, weights fitted on ORGANIC purchases instead of our carousel feedback (T-041). Read-only on RawTree.

    python og_build.py --pull            # download (lfm_build.pull + every organic purchase with its time), build rows, fit, hold-out, write
    python og_build.py                   # same from the cached files
    python og_build.py --loop 30         # periodic refit: every 30 min pull + fit, writes data/og/lfm_coef_og1_<HHMM>.json
                                         # (never policy.json, never the committed file, never a submission)
    --out lfm_coef_og1.json  --neg 40  --window 30  --new   (--new: also write fitted weights for new shoppers)

Rows. For every answered request on a product/category page with recent views (the cohort labelled -k / -n), a positive
is a product that shopper bought organically (shop.events) within --window minutes after the request. Negatives are --neg
products drawn uniformly from the products lfm could have served to that request as of that moment (launched, in stock,
not bought, not dead for that shopper): lfm scores the whole active catalogue, so that is its candidate pool. Features
come from lfm.features with the state as of the request (lfm_build's replay helpers), so they match serving.
Requests without an organic purchase in the window carry no information for a ranking fit and are skipped.

Fit. One logistic regression per segment (known / new) on r3's feature list; `home` is constant 0 on pages and keeps
r3's weight. Hold-out is temporal (last 30% of requests): rank of the organic purchase among ALL servable products
under r3's weights and under og1's, same requests.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
import numpy as np, pandas as pd
import lfm, lfm_build

DATA = lfm_build.DATA
BASE = "lfm_coef_r3.json"


def arg(name, default, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def pull():
    from rt import q
    lfm_build.pull()
    pd.concat([q(f"""SELECT user_id::String u, product_id::String i, ts::String t FROM shop.events
        WHERE event_type::String='purchase' AND cityHash64(user_id::String)%2={m}""") for m in range(2)]).to_parquet(DATA / "og_buys.parquet")


def rows(d, LF, aff, carts, buys, window=30, neg=40, seed=0):
    """-> (R: one row per request with a servable organic purchase, X: list of full feature matrices is NOT kept;
    instead returns per-request positives, sampled negatives' features and the full matrix on demand through `full`)."""
    S = LF.snap; rng = np.random.default_rng(seed); catlog = getattr(aff, "catlog", None)
    ob = pd.read_parquet(DATA / "og_buys.parquet"); ob["t"] = pd.to_datetime(ob.t)
    by_u = {u: (g.t.values, g.i.values) for u, g in ob.groupby("u")}
    W = np.timedelta64(window, "m"); out = []; skipped = dict(no_buy=0, not_servable=0)
    pages = d[d.page.isin(lfm.LQ_PAGES) & (d.rv.map(len) > 0)]
    for r in pages.itertuples():
        e = by_u.get(r.user_id)
        if e is None: skipped["no_buy"] += 1; continue
        ts = np.datetime64(r.ts); m = (e[0] > ts) & (e[0] <= ts + W)
        if not m.any(): skipped["no_buy"] += 1; continue
        b, lc, hc, bt, mix, mfu = lfm_build.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
        seg = lfm.in_segment(r.device, r.region)
        X = lfm.features(S, lfm_build.aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, bought_today=bt, seg=seg, mix=mix, mfu=mfu)
        dead = ~S.ok if catlog is None else catlog.ineligible(r.ts).copy()
        if catlog is not None: catlog.price_features(X, np.arange(S.n), r.ts, seg)
        st = S.stale(r.user_id)
        if st is not None:
            keep = [S.row[p] for p in list(hc) + list(lc) if p in S.row]; st[keep] = False; dead = dead | st
        bb = [S.row[p] for p in b if p in S.row]
        if bb: dead[bb] = True
        pos = sorted({S.row[p] for p in e[1][m] if p in S.row and not dead[S.row[p]]})
        if not pos: skipped["not_servable"] += 1; continue
        alive = np.nonzero(~dead)[0]; cand = np.setdiff1d(alive, pos)
        ng = rng.choice(cand, min(neg, len(cand)), replace=False)
        out.append(dict(rid=r.Index, ts=r.ts, new=bool(r.new_user), pos=pos, Xpos=X[pos].copy(), Xneg=X[ng].copy(),
                        Xall=X[alive].astype(np.float32), posi=np.searchsorted(alive, pos)))
    print(f"page requests with views: {len(pages)}; with a servable organic purchase within {window} min: {len(out)}; "
          f"no purchase in window: {skipped['no_buy']}; purchase not servable (already bought / dead / out of stock): {skipped['not_servable']}", flush=True)
    return out


def fit(R, feats, base):
    from sklearn.linear_model import LogisticRegression
    cols = [lfm.FEATS.index(f) for f in feats if f != "home"]; out = {}
    for seg, new in (("known", False), ("new", True)):
        a = [r for r in R if r["new"] == new]
        if sum(len(r["pos"]) for r in a) < 50: out[seg] = None; continue
        X = np.vstack([np.vstack([r["Xpos"], r["Xneg"]]) for r in a])[:, cols]
        y = np.concatenate([np.r_[np.ones(len(r["pos"])), np.zeros(len(r["Xneg"]))] for r in a])
        m = LogisticRegression(C=lfm_build.C_REG, max_iter=5000).fit(X, y)
        w = {f: 0.0 for f in feats}; w.update(dict(zip([f for f in feats if f != "home"], m.coef_[0].round(4).tolist())))
        w["home"] = base[seg]["w"].get("home", 0.0)
        out[seg] = dict(w=w, b=round(float(m.intercept_[0]), 4), n=int(len(y)), requests=len(a), buys=int(y.sum()))
    return out


def ranks(R, coef, seg):
    w = np.array([coef[seg]["w"].get(f, 0.0) for f in lfm.FEATS], dtype=np.float32); rk = []
    for r in R:
        if r["new"] != (seg == "new"): continue
        s = r["Xall"] @ w
        for k in r["posi"]: rk.append(1 + int((s > s[k]).sum()) + 0.5 * int((s == s[k]).sum() - 1))
    return np.array(rk)


def top10(R, a, b, seg):
    """Mean overlap of the two top-10s and share of products launched during the event in each (hold-out requests of `seg`)."""
    wa, wb = (np.array([c[seg]["w"].get(f, 0.0) for f in lfm.FEATS], dtype=np.float32) for c in (a, b))
    k = lfm.FEATS.index("newp"); ov, na, nb = [], [], []
    for r in R:
        if r["new"] != (seg == "new"): continue
        X = r["Xall"]; ta = np.argsort(-(X @ wa), kind="stable")[:10]; tb = np.argsort(-(X @ wb), kind="stable")[:10]
        ov.append(len(set(ta) & set(tb))); na.append(X[ta, k].mean()); nb.append(X[tb, k].mean())
    return dict(overlap=float(np.mean(ov)), launched_r3=float(np.mean(na)), launched_og1=float(np.mean(nb)))


def summary(rk):
    return dict(n=len(rk), median=float(np.median(rk)), mean=float(rk.mean()), mrr=float((1 / rk).mean()),
                top1=float((rk <= 1).mean()), top10=float((rk <= 10).mean()), top30=float((rk <= 30).mean()))


def run(out_path, window, neg, write_new, do_pull):
    if do_pull: pull()
    base = json.loads((lfm.HERE / BASE).read_text()); feats = base["meta"]["feats"]
    d, LF, aff, carts, buys = lfm_build.load()
    R = rows(d, LF, aff, carts, buys, window, neg)
    cut = d.ts.quantile(0.7); tr = [r for r in R if r["ts"] < cut]; te = [r for r in R if r["ts"] >= cut]
    print("time split at", cut, "| train", len(tr), "test", len(te), flush=True)
    og_tr = fit(tr, feats, base); res = {}
    for seg in ("known", "new"):
        if og_tr[seg] is None: print(seg, "too few purchases to fit"); continue
        a, b = ranks(te, base, seg), ranks(te, og_tr, seg)
        if not len(a): continue
        res[seg] = dict(r3=summary(a), og1=summary(b), og1_better=float((b < a).mean()), r3_better=float((a < b).mean()))
        print(f"\nhold-out {seg}: rank of the organic purchase among all servable products (lower is better)")
        print(pd.DataFrame({"r3": res[seg]["r3"], "og1": res[seg]["og1"]}).T.round(3).to_string())
        res[seg]["top10"] = t = top10(te, base, og_tr, seg)
        print(f"top-10 overlap r3 vs og1: {t['overlap']:.2f} of 10 | launched today in top 10: r3 {t['launched_r3']:.1%}, og1 {t['launched_og1']:.1%}")
        print(f"og1 ranks it higher in {res[seg]['og1_better']:.1%} of purchases, r3 in {res[seg]['r3_better']:.1%}")
    og = fit(R, feats, base)
    coef = {"lq0": base["lq0"]}
    for seg in ("known", "new"):
        use = og[seg] is not None and (seg == "known" or write_new)
        coef[seg] = dict(og[seg], slot=base[seg]["slot"], cal=base[seg]["cal"]) if use else dict(base[seg])
    coef["meta"] = dict(fitted_on=f"{d.ts.min()} .. {d.ts.max()} UTC", label=f"organic purchase within {window} min of a page request",
                        negatives=neg, C=lfm_build.C_REG, feats=feats, base=BASE, holdout=res, holdout_cut=str(cut),
                        segments_fitted=[s for s in ("known", "new") if og[s] is not None and (s == "known" or write_new)],
                        note="slot and cal are r3's (not refitted): this file is for ranking only")
    out_path.write_text(json.dumps(coef, indent=1)); print("\nwrote", out_path)
    for seg in ("known", "new"): print(seg, "og" if og[seg] else "-", og[seg] and og[seg]["w"], "\n   r3", base[seg]["w"])
    return coef


def main():
    window, neg = arg("--window", 30, int), arg("--neg", 40, int)
    if "--loop" in sys.argv:
        every = arg("--loop", 30, int); (DATA / "og").mkdir(exist_ok=True)
        while True:
            t = time.time()
            try: run(DATA / "og" / f"lfm_coef_og1_{time.strftime('%H%M', time.gmtime())}.json", window, neg, "--new" in sys.argv, True)
            except Exception as e: print("refit failed:", type(e).__name__, e, flush=True)
            time.sleep(max(60, every * 60 - (time.time() - t)))
    run(lfm.HERE / arg("--out", "lfm_coef_og1.json"), window, neg, "--new" in sys.argv, "--pull" in sys.argv)


if __name__ == "__main__":
    main()
