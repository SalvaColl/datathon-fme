from common import *
from scipy.optimize import minimize
from scipy.special import logsumexp
I, F, R = load()
I = I.join(R[["seg", "ts", "new", "coh"]], on="rid")
U1 = pol("policy.unified.json")
VAR = [f for f in FE if f not in ("home", "hcart", "lq", "seglq", "segcheap", "newp", "cv", "sbrand", "hotc", "hot")]   # fitted; others stay at u1's value
def tensor(segs, y):
    """requests of `segs` with one positive (not dead) -> X [n,10,NF], slot [n,10], mask, pos index, ts"""
    a = I[I.seg.isin(segs)]
    pos = a[(a[y] == 1) & (a.dead == 0)].rid.unique()
    a = a[a.rid.isin(pos)]; idx = a.index.values
    rid, inv = np.unique(a.rid.values, return_inverse=True); n = len(rid)
    X = np.zeros((n, 10, len(FE))); M = np.zeros((n, 10), bool); S = np.zeros((n, 10), int); P = np.zeros(n, int)
    j = a.slot.values - 1
    X[inv, j] = F[idx]; M[inv, j] = a.dead.values == 0; S[inv, j] = j
    P[inv[a[y].values == 1]] = j[a[y].values == 1]
    ts = R.ts.reindex(rid).values; home = (R.coh.reindex(rid) == "home").values; new = R.new.reindex(rid).values
    base = np.zeros((n, 10))
    for (sg, h), w in U1.items():
        m = (new == (sg == "new")) & (home == h); base[m] = X[m] @ w
    return dict(X=X, M=M, S=S, P=P, ts=ts, n=n, base=base, rid=rid)
def sub(T, m): return {k: (v[m] if isinstance(v, np.ndarray) and len(v) == T["n"] else v) for k, v in T.items()} | dict(n=int(m.sum()))
def ll_rows(T, util):
    u = np.where(T["M"], util, -np.inf)
    return u[np.arange(T["n"]), T["P"]] - logsumexp(u, axis=1)
def fit_base(T):
    """u1 score with a free scale + free slot effects"""
    def f(th):
        u = th[0] * T["base"] + np.r_[0, th[1:]][T["S"]]; return -ll_rows(T, u).sum()
    r = minimize(f, np.r_[1.0, -0.3 * np.arange(1, 10)], method="L-BFGS-B"); return r.x
def base_ll(T, th): return ll_rows(T, th[0] * T["base"] + np.r_[0, th[1:]][T["S"]])
def fit_w(Ts, w0, lam, feats=VAR, alphas=None, sd=None):
    """Ts: list of tensors (buy, click...) sharing w, own slot effects; w0: prior weights (full vector); ridge on (w-w0)*sd"""
    fi = [FI[f] for f in feats]; k = len(fi); alphas = alphas or [1.0] * len(Ts)
    Xv = [T["X"][:, :, fi] for T in Ts]; off = [T["X"] @ np.where(np.isin(np.arange(len(w0)), fi), 0, w0) for T in Ts]
    def f(th):
        w = th[:k]; tot = 0.0; g = np.zeros_like(th)
        for t, T in enumerate(Ts):
            a = np.r_[0, th[k + 9 * t:k + 9 * t + 9]]
            u = np.where(T["M"], off[t] + Xv[t] @ w + a[T["S"]], -np.inf)
            lse = logsumexp(u, axis=1); p = np.exp(u - lse[:, None])
            tot -= alphas[t] * (u[np.arange(T["n"]), T["P"]] - lse).sum()
            r = -p; r[np.arange(T["n"]), T["P"]] += 1
            g[:k] -= alphas[t] * np.einsum("ns,nsk->k", r, Xv[t])
            ga = np.bincount(T["S"].ravel(), weights=r.ravel(), minlength=10)[1:]; g[k + 9 * t:k + 9 * t + 9] -= alphas[t] * ga
        dv = (w - w0[fi]) * sd[fi]; tot += lam * (dv ** 2).sum(); g[:k] += 2 * lam * dv * sd[fi]
        return tot, g
    th0 = np.r_[w0[fi], np.tile(-0.3 * np.arange(1, 10), len(Ts))]
    r = minimize(f, th0, jac=True, method="L-BFGS-B", options=dict(maxiter=2000))
    w = w0.copy(); w[fi] = r.x[:k]; return w, [np.r_[0, r.x[k + 9 * t:k + 9 * t + 9]] for t in range(len(Ts))]
def w_ll(T, w, a): return ll_rows(T, T["X"] @ w + a[T["S"]])
def within_sd(T):
    X = T["X"]; M = T["M"][:, :, None]; mu = (X * M).sum(1, keepdims=True) / M.sum(1, keepdims=True)
    return np.sqrt((((X - mu) ** 2) * M).sum((0, 1)) / M.sum())
def boot(d, B=2000, seed=0):
    rng = np.random.default_rng(seed); n = len(d); s = d[rng.integers(0, n, (B, n))].sum(1); return d.sum(), np.percentile(s, 2.5), np.percentile(s, 97.5)
if __name__ == "__main__":
    import itertools
    GROUPS = {"known/page": ["kS/page", "kR/page"], "kS/page": ["kS/page"], "kR/page": ["kR/page"], "new/page": ["new/page"], "home": ["kS/home", "kR/home", "new/home"]}
    for name, segs in GROUPS.items():
        Tb = tensor(segs, "buy"); Tc = tensor(segs, "clk"); sd = within_sd(Tc)
        print(f"\n=== {name}: buy requests {Tb['n']}, click requests {Tc['n']}")
        for cut in ("2026-11-14 19:00", "2026-11-14 21:00", "2026-11-14 23:00"):
            c = np.datetime64(cut); tr, te = sub(Tb, Tb["ts"] < c), sub(Tb, Tb["ts"] >= c); trc, tec = sub(Tc, Tc["ts"] < c), sub(Tc, Tc["ts"] >= c)
            thb = fit_base(tr); thc = fit_base(trc); lb = base_ll(te, thb); lbc = base_ll(tec, thc)
            out = [f"cut {cut[11:]} test buys {te['n']} clicks {tec['n']} | u1 scale {thb[0]:.2f} ll/buy {lb.mean():.3f} (uniform {-np.log(10):.3f})"]
            segkey = ("new" if name.startswith("new") else "known", name == "home")
            w0 = thb[0] * U1[segkey]
            for lam, al in itertools.product((3, 30, 300), (0.0, 0.3)):
                Ts = [tr] + ([trc] if al else []); w, a = fit_w(Ts, w0, lam, alphas=[1.0, al][:len(Ts)], sd=sd)
                d = w_ll(te, w, a[0]) - lb; s, lo, hi = boot(d)
                out.append(f"   lam {lam:>3} click {al}: dLL buys {s:+7.1f} [{lo:+6.1f},{hi:+6.1f}]" + (f" | clicks {(w_ll(tec, w, a[1]) - lbc).sum():+7.1f}" if al else ""))
            print("\n".join(out), flush=True)
