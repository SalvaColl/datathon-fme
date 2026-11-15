import json, math, numpy as np, pandas as pd
I = pd.concat([pd.read_parquet(f"I{j}.parquet") for j in range(4)], ignore_index=True)
F = np.concatenate([np.load(f"F{j}.npy") for j in range(4)])
R = pd.concat([pd.read_parquet(f"R{j}.parquet") for j in range(4)], ignore_index=True).set_index("rid")
P = pd.read_parquet("P.parquet").pid.values; row = {p: k for k, p in enumerate(P)}
D = "/home/user/datathon-fme/recsys/data/"
pv = pd.read_parquet(D + "prev_views.parquet"); PH = {}
for u, i, n in zip(pv.u.values, pv.i.values, pv.n.values):
    k = row.get(i)
    if k is not None: PH.setdefault(u, {})[k] = float(n)
hc = pd.read_parquet(D + "hist_carousel.parquet"); HB = {}; HC = {}
for u, i, b in zip(hc.u.values, hc.i.values, hc.b.values):
    k = row.get(i)
    if k is not None: (HB if b else HC).setdefault(u, set()).add(k)
rq = pd.read_parquet("allreq.parquet"); rq["t"] = pd.to_datetime(rq.t); rq = rq.sort_values("t")
ev = {}                                       # user -> list of (t, set of rows)
for u, t, rv in zip(rq.u.values, rq.t.values, rq.rv.values):
    s = {row[x["product_id"]] for x in json.loads(rv) if x.get("product_id") in row}
    if s: ev.setdefault(u, []).append((t, s))
def prev(u, ts):
    out = dict(PH.get(u, {}))
    for t, s in ev.get(u, ()):
        if t >= ts: break
        for k in s: out[k] = out.get(k, 0.0) + 2.0
    return out
E = np.zeros((len(I), 3), np.float32)
ru = R.u.to_dict(); rt = R.ts.to_dict(); cache = {}
cart = (F[:, 1] > 0) | (F[:, 2] > 0)
for n, (rid, k) in enumerate(zip(I.rid.values, I.k.values)):
    c = cache.get(rid)
    if c is None:
        cache.clear(); u = ru[rid]; c = cache[rid] = (prev(u, np.datetime64(rt[rid])), HB.get(u, ()), HC.get(u, ()))
    v = c[0].get(k)
    if v and not cart[n]: E[n, 0] = math.log1p(min(v, 8.0))
    if k in c[1]: E[n, 1] = 1
    if k in c[2]: E[n, 2] = 1
np.save("E.npy", E)
print("impressions with prv", int((E[:, 0] > 0).sum()), "hcb", int(E[:, 1].sum()), "hcc", int(E[:, 2].sum()), "| buys", int(I.buy[E[:, 0] > 0].sum()), int(I.buy[E[:, 1] > 0].sum()), int(I.buy[E[:, 2] > 0].sum()), "| dead&hcb", int(((I.dead == 1) & (E[:, 1] > 0)).sum()), "buys", int(I.buy[(I.dead == 1) & (E[:, 1] > 0)].sum()))
# full matrices for buy requests
FM = pd.concat([pd.read_parquet(f"FM{j}.parquet") for j in range(4)], ignore_index=True)
XF = np.concatenate([np.load(f"XF{j}.npy", mmap_mode="r") for j in range(4)])
EX = np.zeros((len(FM), XF.shape[1], 3), np.float32)
for n, rid in enumerate(FM.rid.values):
    u = ru[rid]; pvs = prev(u, np.datetime64(rt[rid])); c = (XF[n, :, 1] > 0) | (XF[n, :, 2] > 0)
    for k, v in pvs.items():
        if not c[k]: EX[n, k, 0] = math.log1p(min(v, 8.0))
    for k in HB.get(u, ()): EX[n, k, 1] = 1
    for k in HC.get(u, ()): EX[n, k, 2] = 1
np.save("EX.npy", EX); print("done")
