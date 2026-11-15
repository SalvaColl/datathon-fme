from clfit import *
LIVE = U1
NOF = ("prv", "hcb", "hcc", "newph")
print("era buys:", {s: int(((I.seg == s) & (I.buy == 1) & (I.ts >= pd.Timestamp("2026-11-15 02:20"))).sum()) for s in ("kS/page", "kR/page", "new/page")})
for name, segs, key, extra in (("known/page", ["kS/page", "kR/page"], ("known", False), ["newp"]), ("new/page", ["new/page"], ("new", False), [])):
    Tb = tensor(segs, "buy"); Tc = tensor(segs, "clk"); sd = within_sd(Tc)
    feats = [f for f in VAR if f not in NOF and sd[FI[f]] > 0] + extra
    for cut in ("2026-11-14 21:00", "2026-11-14 23:00", "2026-11-15 01:00", "2026-11-15 02:35"):
        c = np.datetime64(cut); tr, te, trc = sub(Tb, Tb["ts"] < c), sub(Tb, Tb["ts"] >= c), sub(Tc, Tc["ts"] < c); th = fit_base(tr); lb = base_ll(te, th)
        out = []
        for lam in (10, 30, 100, 300):
            w, a = fit_w([tr, trc], th[0] * LIVE[key], lam, feats=feats, alphas=[1, 0.3], sd=sd); out.append("lam%d %+.1f [%+.0f,%+.0f]" % ((lam,) + boot(w_ll(te, w, a[0]) - lb, B=1000)))
        print(f"{name} cut {cut[5:]} test buys {te['n']} scale {th[0]:.2f}: " + "  ".join(out), flush=True)
    th = fit_base(Tb); res = {"live": LIVE[key]}
    for lam in (30, 100):
        w, a = fit_w([Tb, Tc], th[0] * LIVE[key], lam, feats=feats, alphas=[1, 0.3], sd=sd); res[f"lam{lam}"] = w / th[0]
    # only u3-era lists
    m = Tb["ts"] >= np.datetime64("2026-11-15 02:20"); mc = Tc["ts"] >= np.datetime64("2026-11-15 02:20"); t3, t3c = sub(Tb, m), sub(Tc, mc); th3 = fit_base(t3)
    w, a = fit_w([t3, t3c], th3[0] * LIVE[key], 30, feats=feats, alphas=[1, 0.3], sd=sd); res["since 02:20 only"] = w / th3[0]
    print("scale all", round(th[0], 2), "since 02:20", round(th3[0], 2), "buys", t3["n"]); print(pd.DataFrame(res, index=FE).loc[feats + ["hot"]].round(2).T.to_string())
