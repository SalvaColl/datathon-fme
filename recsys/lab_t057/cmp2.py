from clfit import *
P = {"u1": U1, "u1hb": pol("policy.rot_u1hb.json"), "u2c": pol("policy.rot_u2c.json"), "u2hb": pol("policy.rot_u2hb.json"), "u3k": pol("policy.unified_u3.json")}
NEWF = ["prv", "hcb", "hcc"]
def fixed_ll(tr, te, w):
    def f(th): return -ll_rows(tr, th[0] * (tr["X"] @ w) + np.r_[0, th[1:]][tr["S"]]).sum()
    th = minimize(f, np.r_[1.0, -0.3 * np.arange(1, 10)], method="L-BFGS-B").x
    return ll_rows(te, th[0] * (te["X"] @ w) + np.r_[0, th[1:]][te["S"]])
for name, segs, key in (("known/page", ["kS/page", "kR/page"], ("known", False)), ("new/page", ["new/page"], ("new", False)), ("known/home", ["kS/home", "kR/home"], ("known", True)), ("new/home", ["new/home"], ("new", True))):
    Tb = tensor(segs, "buy"); Tc = tensor(segs, "clk"); sd = within_sd(Tc); home = key[1]
    specs = {"fit old feats": [f for f in VAR if f not in NEWF], "fit +hcb,hcc": [f for f in VAR if f != "prv"], "fit +hcb,hcc,prv": VAR, "u1 + only new 3": NEWF}
    if home: specs = {"u1 + only new 3": NEWF, "u1 + hcb,hcc": ["hcb", "hcc"]}
    for cut in ("2026-11-14 17:00", "2026-11-14 19:00", "2026-11-14 21:00", "2026-11-14 23:00"):
        c = np.datetime64(cut); tr, te, trc = sub(Tb, Tb["ts"] < c), sub(Tb, Tb["ts"] >= c), sub(Tc, Tc["ts"] < c)
        L = {n: fixed_ll(tr, te, w[key]) for n, w in P.items() if not (home and n == "u3k")}
        th = fit_base(tr)
        for sn, fs in specs.items():
            w, a = fit_w([tr, trc], th[0] * U1[key], 30, feats=[f for f in fs if sd[FI[f]] > 0], alphas=[1, 0.3], sd=sd); L[sn] = w_ll(te, w, a[0])
        print(f"{name} cut {cut[5:]} buys {te['n']}: " + "  ".join("%s %+.1f [%+.0f,%+.0f]" % ((n,) + boot(L[n] - L["u1"])) for n in L if n != "u1"), flush=True)
    th = fit_base(Tb); fs = specs.get("fit +hcb,hcc,prv", NEWF)
    w, a = fit_w([Tb, Tc], th[0] * U1[key], 30, feats=[f for f in fs if sd[FI[f]] > 0], alphas=[1, 0.3], sd=sd)
    print("   full-data weights (u1 scale):", {f: round(w[FI[f]] / th[0], 2) for f in NEWF}, "scale", round(th[0], 2))
