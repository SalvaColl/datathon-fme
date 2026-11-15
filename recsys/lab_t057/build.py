"""Impression frame for the carousel fit: every team-served request, features of the 10 shown items as of the request
(catalogue, organic quality, bursts, shopper state), plus the FULL catalogue matrix for requests with a carousel purchase."""
import sys, json, time, os, numpy as np, pandas as pd
from multiprocessing import Pool
sys.path.insert(0, "/home/user/datathon-fme/recsys"); os.chdir("/home/user/datathon-fme/recsys")
import unified_eval as U
lfm, LB, R, qrank, CV, d, LF, aff, carts, buys, H, it = U.load_all()
NF = len(lfm.FEATS)
d = d[d.served_by == "team"].copy()
d["mv"] = d.mv.fillna("?")
print(len(d), "team requests", d.ts.min(), d.ts.max(), "buys", int((d.purchased != "").sum()), flush=True)
hist = pd.read_parquet(LB.DATA / "user_item_all.parquet").groupby("u")[["v", "a", "p"]].sum()
HU = dict(zip(hist.index, zip(hist.v.values, hist.a.values, hist.p.values)))
N = LF.snap.n
def work(j):
    part = d.iloc[j::4] if False else d.iloc[(len(d) * j) // 4:(len(d) * (j + 1)) // 4]
    rows = []; feats = []; reqs = []; full = []; fullmeta = []
    for g, cat, unavail, S, newp, burst in U.snapshots(R, qrank, LF, aff, part, H, it):
        ids = np.array(S.ids, dtype=object); un = np.isin(ids, list(unavail))
        for r in g.itertuples():
            st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts); b, lc, hcu, bt, mix, mfu = st
            page = r.page or "product"
            a = LB.aff_asof(aff, r.user_id, r.rv, r.ts)
            X = lfm.features(S, a, r.rv, page, hcu, lc, bought_today=bt, seg=lfm.in_segment(r.device, r.region), mix=mix, mfu=mfu)
            dead = CV.dead_mask(S, st, r.user_id) | un
            coh = "page" if (r.rv and page in lfm.LQ_PAGES) else "home" if not r.rv else "other"
            hu = HU.get(r.user_id, (0, 0, 0))
            reqs.append((r.Index, r.request_id, r.ts, r.user_id, bool(r.new_user), coh, r.mv, hu[0], hu[1], hu[2], len(lc), len(hcu), len(r.rv), int(burst), r.purchased, r.clicked))
            for s, p in enumerate(r.shown):
                k = S.row.get(p, -1)
                if k < 0: continue
                rows.append((r.Index, s + 1, k, int(p == r.clicked), int(p == r.purchased), int(dead[k]))); feats.append(X[k].astype(np.float32))
            if r.purchased and r.purchased in S.row:
                full.append(X.astype(np.float32)); fullmeta.append((r.Index, S.row[r.purchased])); 
                full.append(None); full[-1] = dead.copy()
    I = pd.DataFrame(rows, columns=["rid", "slot", "k", "clk", "buy", "dead"])
    F = np.array(feats, dtype=np.float32)
    Rq = pd.DataFrame(reqs, columns=["rid", "request_id", "ts", "u", "new", "coh", "mv", "hv", "ha", "hp", "nlc", "nhc", "nrv", "burst", "pu", "cl"])
    XF = np.stack(full[0::2]) if full else np.zeros((0, N, NF), np.float32); DD = np.stack(full[1::2]) if full else np.zeros((0, N), bool)
    I.to_parquet(f"/home/user/lab/I{j}.parquet"); np.save(f"/home/user/lab/F{j}.npy", F); Rq.to_parquet(f"/home/user/lab/R{j}.parquet")
    np.save(f"/home/user/lab/XF{j}.npy", XF); np.save(f"/home/user/lab/DD{j}.npy", DD); pd.DataFrame(fullmeta, columns=["rid", "kbuy"]).to_parquet(f"/home/user/lab/FM{j}.parquet")
    return j, len(Rq), len(I)
if __name__ == "__main__":
    t0 = time.time()
    with Pool(4) as p:
        for x in p.imap_unordered(work, range(4)): print(x, time.time() - t0, flush=True)
    pd.DataFrame(dict(pid=LF.snap.ids)).to_parquet("/home/user/lab/P.parquet")
    print("done", time.time() - t0)
