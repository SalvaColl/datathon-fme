from clfit import *
import itertools
BASEF = [f for f in VAR if f not in ("prv", "hcb", "hcc")]
for name, segs, key in (("known/page", ["kS/page", "kR/page"], ("known", False)), ("new/page", ["new/page"], ("new", False))):
    Tb = tensor(segs, "buy"); Tc = tensor(segs, "clk")
    cart = lambda X: ((X[:, :, FI["chn"]] > 0) | (X[:, :, FI["cl"]] > 0)).astype(float)
    cand = {"aff10^2": lambda X: X[:, :, FI["aff10"]] ** 2, "aff10>1.5": lambda X: (X[:, :, FI["aff10"]] > 1.5).astype(float), "aff10<0.3": lambda X: (X[:, :, FI["aff10"]] < 0.3).astype(float),
            "cart*aff10": lambda X: cart(X) * X[:, :, FI["aff10"]], "cart*scat": lambda X: cart(X) * X[:, :, FI["scat2"]], "cart*ucat": lambda X: cart(X) * X[:, :, FI["ucat"]], "cart*orate": lambda X: cart(X) * X[:, :, FI["orate"]],
            "ssub2*aff10": lambda X: X[:, :, FI["ssub2"]] * X[:, :, FI["aff10"]], "scat2*aff10": lambda X: X[:, :, FI["scat2"]] * X[:, :, FI["aff10"]], "sess*orate": lambda X: (X[:, :, FI["ssub2"]] + X[:, :, FI["scat2"]]) * X[:, :, FI["orate"]],
            "aff10*orate": lambda X: X[:, :, FI["aff10"]] * X[:, :, FI["orate"]], "ucat*aff10": lambda X: X[:, :, FI["ucat"]] * X[:, :, FI["aff10"]], "na*aff10": lambda X: X[:, :, FI["na"]] * X[:, :, FI["aff10"]],
            "mf^2": lambda X: X[:, :, FI["mf"]] ** 2 / 10, "mf>5": lambda X: (X[:, :, FI["mf"]] > 5).astype(float), "orate^2": lambda X: X[:, :, FI["orate"]] ** 2, "chn>1(2+carts)": lambda X: (X[:, :, FI["chn"]] > 1).astype(float),
            "usub*ssub": lambda X: X[:, :, FI["usub"]] * X[:, :, FI["ssub2"]], "p40*aff": lambda X: X[:, :, FI["p40"]] * X[:, :, FI["aff10"]], "sbrand": lambda X: X[:, :, FI["sbrand"]], "nbp": None, "cv": lambda X: X[:, :, FI["cv"]], "newp": lambda X: X[:, :, FI["newp"]], "lq": lambda X: X[:, :, FI["lq"]]}
    res = []
    for cn, fn in cand.items():
        if fn is None: continue
        out = []
        for cut in ("2026-11-14 18:00", "2026-11-14 21:00"):
            c = np.datetime64(cut); d = []
            for extra in (False, True):
                Ts = []
                for T in (Tb, Tc):
                    T2 = dict(T); T2["X"] = np.concatenate([T["X"], fn(T["X"])[:, :, None] if extra else np.zeros(T["X"].shape[:2] + (1,))], axis=2); Ts.append(T2)
                tr, te, trc = sub(Ts[0], Ts[0]["ts"] < c), sub(Ts[0], Ts[0]["ts"] >= c), sub(Ts[1], Ts[1]["ts"] < c)
                th = fit_base(tr); sd = np.r_[within_sd(Tc), fn(Tc["X"])[Tc["M"]].std()]; w0 = np.r_[th[0] * U1[key], 0.0]
                fi = [FI[f] for f in BASEF if sd[FI[f]] > 0] + [len(FE)]
                import clfit; FI["extra"] = len(FE)
                # fit_w indexes by name; emulate by passing an index-aware variant
                FE2 = FE + ["extra"]; clfit.FI["extra"] = len(FE)
                w, a = fit_w([tr, trc], w0, 30, feats=[f for f in BASEF if sd[FI[f]] > 0] + ["extra"], alphas=[1, 0.3], sd=sd)
                d.append(ll_rows(te, te["X"] @ w + a[0][te["S"]])); coef = w[-1] / th[0]
            s, lo, hi = boot(d[1] - d[0], B=1000); out.append(f"{s:+6.1f} [{lo:+5.1f},{hi:+5.1f}]")
        print(f"{name:>10} {cn:>16}: coef(u1 scale) {coef:+.2f} | dLL cut18 {out[0]} | cut21 {out[1]}", flush=True)
