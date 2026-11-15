from clfit import *
from full import XF, DD, FM, POS
key = ("known", False); ni = FI["newp"]
m = np.nonzero(FM.seg.isin(["kS/page", "kR/page"]).values & (FM.ts >= pd.Timestamp("2026-11-14 21:00")).values)[0]
era3 = (FM.ts.values[m] >= np.datetime64("2026-11-15 02:20"))
for d in (0.0, 1.0, 1.5, 2.0, 2.5, 3.0):
    w = U1[key].copy(); w[ni] = d; nl = 0; n3 = 0; rk = []
    for i in m:
        s = XF[i].astype(np.float64) @ w; s[DD[i]] = -np.inf; t = np.argsort(-s)[:10]; nl += XF[i][t, ni].sum(); n3 += XF[i][t[:3], ni].sum(); rk.append(1 + int((s > s[FM.kbuy.values[i]]).sum()))
    rk = np.array(rk); pw = np.where(rk <= 10, POS[np.minimum(rk, 10) - 1], 0)
    print(f"newp {d}: launched/list {nl / len(m):.2f} (top3 {n3 / len(m):.2f}) | carousel buys kept top10 {100 * (rk <= 10).mean():.1f}% slot-weighted {100 * pw.mean():.1f} | u3-era lists only {100 * (rk[era3] <= 10).mean():.1f}% (n {era3.sum()})")
