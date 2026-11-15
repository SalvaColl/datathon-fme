from clfit import *
XF = np.concatenate([np.load(f"XF{j}.npy", mmap_mode="r") for j in range(4)]); DD = np.concatenate([np.load(f"DD{j}.npy") for j in range(4)])
FM = pd.concat([pd.read_parquet(f"FM{j}.parquet") for j in range(4)], ignore_index=True).join(R[["seg", "ts", "new", "coh", "mv"]], on="rid")
POS = np.array([1, .53, .40, .28, .22, .19, .16, .14, .12, .11])
def ranks(W, m):
    """W: {(seg,home): w}; -> rank (1-based) of the bought product among servable products, for rows m of FM"""
    out = np.zeros(m.sum(), int)
    for j, i in enumerate(np.nonzero(m)[0]):
        r = FM.iloc[i]; w = W[("new" if r.new else "known", r.coh == "home")]
        s = XF[i].astype(np.float64) @ w; s[DD[i]] = -np.inf; out[j] = 1 + int((s > s[r.kbuy]).sum())
    return out
def top10(W, i):
    r = FM.iloc[i]; w = W[("new" if r.new else "known", r.coh == "home")]; s = XF[i].astype(np.float64) @ w; s[DD[i]] = -np.inf
    return np.argsort(-s)[:10]
def summarize(name, rk, base=None):
    h10 = rk <= 10; pw = np.where(h10, POS[np.minimum(rk, 10) - 1], 0)
    s = f"{name:>14}: in top10 {100 * h10.mean():5.1f}%  top3 {100 * (rk <= 3).mean():5.1f}%  slot-weighted {100 * pw.mean():5.1f}"
    if base is not None:
        d = pw - np.where(base <= 10, POS[np.minimum(base, 10) - 1], 0); t, lo, hi = boot(d); s += f"  vs u1 {100 * t / len(d):+5.2f} [{100 * lo / len(d):+5.2f},{100 * hi / len(d):+5.2f}]"
    return s
if __name__ == "__main__":
    cut = np.datetime64("2026-11-14 21:00")
    W = {"u1": U1, "r3": pol("policy.rot_r3.json"), "cs2r": pol("policy.rot_cs2r.json"), "u2c": pol("policy.unified_u2c.json")}
    fitted = {}
    for name, segs, key in (("known", ["kS/page", "kR/page"], ("known", False)), ("new", ["new/page"], ("new", False))):
        Tb = tensor(segs, "buy"); Tc = tensor(segs, "clk"); sd = within_sd(Tc); tr, trc = sub(Tb, Tb["ts"] < cut), sub(Tc, Tc["ts"] < cut); th = fit_base(tr)
        for lam in (3, 30, 300, 3000):
            w, a = fit_w([tr, trc], th[0] * U1[key], lam, alphas=[1, 0.3], sd=sd); fitted.setdefault(lam, dict(U1))[key] = w / th[0]
    for lam, w in fitted.items(): W[f"fit lam{lam}"] = w
    for seg in (["kS/page"], ["kR/page"], ["new/page"]):
        m = (FM.ts >= cut).values & FM.seg.isin(seg).values
        print(f"\n== {seg} held-out carousel purchases after 21:00: {m.sum()}")
        base = ranks(U1, m)
        for n, w in W.items(): print(summarize(n, ranks(w, m), None if n == "u1" else base), flush=True)
        # only purchases logged under cs2r/u1 era vs before
        era = (FM.ts[m] >= np.datetime64("2026-11-14 23:55")).values
        for n in ("u1", "fit lam30"):
            rk = ranks(W[n], m); print(f"    {n} top10 on r3-era lists {100 * (rk[~era] <= 10).mean():.1f}% (n {int((~era).sum())}), cs2r/u1-era {100 * (rk[era] <= 10).mean():.1f}% (n {int(era.sum())})")
        idx = np.nonzero(m)[0][::3]
        print("    overlap of top 10 with u1:", {n: round(float(np.mean([len(set(top10(W[n], i)) & set(top10(U1, i))) for i in idx])), 2) for n in ("cs2r", "u2c", "fit lam3", "fit lam30", "fit lam300")})
