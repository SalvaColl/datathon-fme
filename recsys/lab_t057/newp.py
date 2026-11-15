from clfit import *
B0 = [f for f in VAR if f not in ("prv", "hcb", "hcc")]
Tb = tensor(["kS/page", "kR/page"], "buy"); Tc = tensor(["kS/page", "kR/page"], "clk"); sd = within_sd(Tc); key = ("known", False)
X = Tb["X"]; npf = X[:, :, FI["newp"]]; bought_np = npf[np.arange(Tb["n"]), Tb["P"]]
print("buy requests", Tb["n"], "with a launched product shown", int((npf.sum(1) > 0).sum()), "bought launched", int(bought_np.sum()))
era = pd.Series(pd.cut(pd.to_datetime(Tb["ts"]), pd.to_datetime(["2026-11-14 11:00", "2026-11-14 17:00", "2026-11-14 20:30", "2026-11-14 23:55", "2026-11-15 03:00"])))
print(pd.DataFrame(dict(era=era.astype(str), has=(npf.sum(1) > 0), nshown=npf.sum(1), b=bought_np)).groupby("era").agg(buys=("has", "size"), lists_with=("has", "sum"), launched_shown=("nshown", "sum"), bought_launched=("b", "sum")))
ai = I[I.seg.isin(["kS/page", "kR/page"]) & (I.dead == 0)]; fn = F[ai.index.values][:, FI["newp"]] > 0
print("all known/page impressions: launched", int(fn.sum()), "buys", int(ai.buy[fn].sum()), "rate/10k %.1f" % (1e4 * ai.buy[fn].mean()), "| others rate/10k %.1f" % (1e4 * ai.buy[~fn].mean()), "| launched mean slot %.1f" % ai.slot[fn].mean())
for extra in (["newp"], ["newp", "lq"], ["newp", "lq", "cv"]):
    out = []
    for cut in ("2026-11-14 17:00", "2026-11-14 19:00", "2026-11-14 21:00", "2026-11-14 23:00"):
        c = np.datetime64(cut); tr, te, trc = sub(Tb, Tb["ts"] < c), sub(Tb, Tb["ts"] >= c), sub(Tc, Tc["ts"] < c); th = fit_base(tr)
        w0, a0 = fit_w([tr, trc], th[0] * U1[key], 30, feats=B0, alphas=[1, 0.3], sd=sd); w1, a1 = fit_w([tr, trc], th[0] * U1[key], 30, feats=B0 + extra, alphas=[1, 0.3], sd=sd)
        s, lo, hi = boot(w_ll(te, w1, a1[0]) - w_ll(te, w0, a0[0])); out.append(f"{s:+.1f} [{lo:+.0f},{hi:+.0f}] (newp {w1[FI['newp']] / th[0]:.2f})")
    print(extra, " | ".join(out), flush=True)
# era-specific coefficient
for lo_, hi_ in (("2026-11-14 11:00", "2026-11-14 20:30"), ("2026-11-14 20:30", "2026-11-15 03:00")):
    m = (Tb["ts"] >= np.datetime64(lo_)) & (Tb["ts"] < np.datetime64(hi_)); mc = (Tc["ts"] >= np.datetime64(lo_)) & (Tc["ts"] < np.datetime64(hi_))
    tr, trc = sub(Tb, m), sub(Tc, mc); th = fit_base(tr); w1, a1 = fit_w([tr, trc], th[0] * U1[key], 30, feats=B0 + ["newp"], alphas=[1, 0.3], sd=sd); wb, ab = fit_w([tr], th[0] * U1[key], 30, feats=B0 + ["newp"], alphas=[1], sd=sd)
    print("era", lo_[5:], hi_[5:], "buys", tr["n"], "newp coef (u1 scale) with clicks %.2f, buys only %.2f" % (w1[FI["newp"]] / th[0], wb[FI["newp"]] / th[0]))
