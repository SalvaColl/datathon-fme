from clfit import *
LIVE = U1; key = ("known", False); NOF = ("prv", "hcb", "hcc", "newph")
up = pd.read_parquet(RS + "data/coldlq_replay/updates.parquet"); NP = set(up.product_id[up.change == "new_product"])
rq = pd.read_parquet("allreq.parquet"); coldrid = set(rq.rid[[any(x["product_id"] in NP for x in json.loads(s)) for s in rq.rv]])
R["coldk"] = R.request_id.isin(coldrid)
print("known/page requests cold (launched in views): %d of %d, conv %.2f%% vs %.2f%%" % ((R.coldk & R.seg.isin(["kS/page", "kR/page"])).sum(), R.seg.isin(["kS/page", "kR/page"]).sum(), 100 * (R.pu[R.coldk & R.seg.isin(["kS/page", "kR/page"])] != "").mean(), 100 * (R.pu[~R.coldk & R.seg.isin(["kS/page", "kR/page"])] != "").mean()))
Tb = tensor(["kS/page", "kR/page"], "buy"); Tc = tensor(["kS/page", "kR/page"], "clk"); sd = within_sd(Tc)
ck = R.coldk.reindex(Tb["rid"]).values
base = [f for f in VAR if f not in NOF and sd[FI[f]] > 0]
def fixed(d):
    w = LIVE[key].copy(); w[FI["newp"]] = d; return w
for cut in ("2026-11-14 23:00", "2026-11-15 01:00", "2026-11-15 02:35"):
    c = np.datetime64(cut); m = Tb["ts"] >= c; tr, te, trc = sub(Tb, ~m), sub(Tb, m), sub(Tc, Tc["ts"] < c); th = fit_base(tr); lb = base_ll(te, th); ckt = ck[m]
    def rep(nm, w, a):
        d = w_ll(te, w, a) - lb; return "%s all %+.1f [%+.0f,%+.0f] | cold-known (%d buys) %+.1f | rest %+.1f" % ((nm,) + boot(d, B=1000) + (int(ckt.sum()), d[ckt].sum(), d[~ckt].sum()))
    print("cut", cut[5:], "test buys", te["n"])
    w, a = fit_w([tr, trc], th[0] * LIVE[key], 30, feats=base, alphas=[1, 0.3], sd=sd); print("  ", rep("refit, newp 0      ", w, a[0]))
    for d in (1.0, 1.5, 2.5):
        w, a = fit_w([tr, trc], th[0] * fixed(d), 30, feats=base, alphas=[1, 0.3], sd=sd); print("  ", rep("refit, newp %.1f fix" % d, w, a[0]))
        w, a = fit_w([tr, trc], th[0] * fixed(d), 30, feats=["mf"], alphas=[1, 0.3], sd=sd); w = th[0] * fixed(d); print("  ", rep("live + newp %.1f     " % d, w, a[0]))
    w, a = fit_w([tr, trc], th[0] * LIVE[key], 30, feats=base + ["newp"], alphas=[1, 0.3], sd=sd); print("  ", rep("refit, newp free %.1f" % (w[FI["newp"]] / th[0]), w, a[0]))
