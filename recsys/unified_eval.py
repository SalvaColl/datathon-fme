"""E-500 — evidence for the single-arm "unified" policy (T-050). OFFLINE ESTIMATE, never a result: the hidden model decides.

    cd recsys
    python download_user_items.py && python cold_lq_replay.py --pull      # READ-ONLY RawTree
    python unified_eval.py targets [--grid grid.json] [--out file.json]   # which variant would have shown what was bought
    python unified_eval.py check policy.unified.json [--n 4000]           # writer's own path: validity, changed lists, mix, latency

targets: every answered request of the day followed by (a) an ORGANIC purchase by the same shopper within 30 minutes of a
product that was servable for the request, or (b) a purchase in OUR carousel, is scored again with the catalogue, stock,
shopper state, organic counts and live bursts AS OF the request, once per variant. Reported per cohort:
  org@10 / org@3 : share of the organic purchases that fall in the variant's top 10 / top 3. Organic purchases were not
                   chosen by our ranking, so no variant is favoured by having ordered the lists (the trap of carousel MRR).
                   Limit: it measures "we show what the shopper goes on to buy", not the hidden carousel response.
  fb@10 / fb@3   : the same for carousel purchases. BIASED towards whatever ordered the logged lists (r3 most of the day):
                   read it only as a floor, a variant that drops many of these is moving away from proven sellers.
Differences against the base variant are paired per request, with a standard error.
"""
from __future__ import annotations

import argparse, collections, json, math, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
R3 = "lfm_coef_r3.json"
CS = {"chn": 3.0, "cl": 3.0, "ssub2": 3.0, "scat2": 3.0, "ucat": 6.0, "islast": 3.7, "oinrv": 4.0}
HOME = {"home": {"file": R3}}
OQ1H = {"home": {"file": R3, "w": {"known": {"lq": 0.0, "orate": 1.0, "opop": 0.6}, "new": {"lq": 0.0, "orate": 1.0, "opop": 0.6}}}}
OQHH = {"home": {"file": R3, "w": {"known": {"lq": 0.24, "orate": 0.5, "opop": 0.3}, "new": {"lq": 0.33, "orate": 0.5, "opop": 0.3}}}}
OQ1K, OQ1N = {"lq": 0.0, "orate": 0.7, "opop": 0.6}, {"lq": 0.0, "orate": 1.8, "opop": 0.4}
OQHK, OQHN = {"lq": 0.24, "orate": 0.35, "opop": 0.3}, {"lq": 0.33, "orate": 0.9, "opop": 0.2}
GRID = {
    "r3": {"file": R3},
    "cs2r": {"file": R3, "w": {"known": CS}, **HOME},
    "cs2r_rc": {"file": R3, "w": {"known": CS}, **HOME, "recart": True},
    "ogsr": {"file": "lfm_coef_og1.json", "w": {"known": {"chn": 3.0, "cl": 3.0, "ssub2": 2.0, "scat2": 2.0, "islast": 2.0, "oinrv": 3.0}}, **HOME},
    "og1": {"file": "lfm_coef_og1.json", **HOME},
    "hot15": {"file": R3, "w": {"known": {"hot": 1.5}, "new": {"hot": 1.5}}},
    "nc2": {"file": R3, "w": {"new": {"cl": 2.2}}, **HOME},
    "oq1": {"file": R3, "w": {"known": OQ1K, "new": OQ1N}, **OQ1H},
    "oqh": {"file": R3, "w": {"known": OQHK, "new": OQHN}, **OQHH},
    "cs_oq1": {"file": R3, "w": {"known": {**CS, **OQ1K}, "new": OQ1N}, **OQ1H},
    "cs_oqh": {"file": R3, "w": {"known": {**CS, **OQHK}, "new": OQHN}, **OQHH},
}
COH = ("known/page", "new/page", "known/home", "new/home")


def bursts(item10, sub_of, lift=2.0, min_views=150):
    """{closed 10-minute bucket end -> set of hot subcategories}: share of the views of the last 10 minutes at least `lift`
    times its median share in the PRECEDING three hours, with at least 30 minutes of baseline. Current/future buckets
    never enter that baseline. This remains a 10-minute proxy, not the production detector's 5-minute-bucket replay;
    it must not be used to select a detector window or claim exact onset/expiry timing."""
    it = item10.assign(sub=item10.i.map(sub_of)).dropna(subset=["sub"])
    t = it.pivot_table(index="b", columns="sub", values="v", aggfunc="sum", fill_value=0)
    share = t.div(t.sum(axis=1).replace(0, np.nan), axis=0)
    med = share.rolling("3h", closed="left", min_periods=3).median()
    out = {}
    for b, row in share.iterrows():
        baseline = med.loc[b]
        hot = [s for s in row.index if pd.notna(baseline[s]) and
               row[s] >= lift * max(baseline[s], 1e-4) and t.at[b, s] >= min_views]
        if hot: out[b] = set(hot)
    return out


def load_all():
    import lfm, lfm_build as LB, cold_lq_replay as R, qrank, cart_variants as CV
    d, LF, aff, carts, buys = CV.setup()
    hist = pd.read_parquet(LB.DATA / "user_item_all.parquet").groupby("i")[["v", "p"]].sum()
    H = dict(zip(hist.index, zip(hist.v.values.astype(float), hist.p.values.astype(float))))
    it = pd.read_parquet(R.OUT / "item10.parquet"); it["b"] = pd.to_datetime(it.b) + pd.Timedelta(minutes=10); it = it.sort_values("b")
    return lfm, LB, R, qrank, CV, d, LF, aff, carts, buys, H, it


def snapshots(R, qrank, LF, aff, d, H, it, hot_on=True):
    """Yield (group of requests, cat, unavail, S, newp) with LF's snapshot built as of the group's 10-minute bucket."""
    C = R.Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib"); hc = LF.snap.hc; hset = set(H)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    B, burst_subs = None, None
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        sub_of = cat["sub"].to_dict()
        if B is None or sub_of != burst_subs:
            # A catalogue at the first request does not contain later launches. Rebuild the causal proxy when
            # its metadata changes, otherwise those products' organic events disappear from every later burst.
            B = bursts(it, sub_of); burst_subs = sub_of
        QR.set_catalog(cat, unavail); newp = set(cat.index) - set(QR.q)
        today = it[it.b <= bucket].groupby("i")[["v", "p"]].sum(); oq = dict(H)
        for i, v, p in zip(today.index, today.v.values, today.p.values):
            h = oq.get(i); oq[i] = (v + h[0], p + h[1]) if h else (float(v), float(p))
        hs = B.get(bucket) if hot_on else None
        hot = set(cat.index[cat["sub"].isin(hs)]) if hs else None
        if hot is not None and len(hot) > 0.10 * len(cat): hot = None
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, newp=newp or None, hot=hot, oq=oq, oq_hist=hset)
        yield g, cat, unavail, LF.snap, newp, bool(hot)


def targets(grid=None, out=None, base="r3", horizon_min=30):
    lfm, LB, R, qrank, CV, d, LF, aff, carts, buys, H, it = load_all()
    FI = {f: k for k, f in enumerate(lfm.FEATS)}
    G = dict(GRID); G.update(grid or {})
    W = {n: CV.weights({k: v for k, v in s.items() if k != "recart"}) for n, s in G.items()}
    RCV = {n for n, s in G.items() if s.get("recart")}
    names = list(G)
    hz = np.timedelta64(horizon_min, "m")
    d = d[d.served_by == "team"]
    # requests with a target: organic purchase within the horizon, or a purchase in our carousel
    ts64 = d.ts.values.astype("datetime64[ns]")
    org = []
    for u, t in zip(d.user_id.values, ts64):
        b = buys.get(u)
        org.append([i for i, tb in b.items() if t < tb <= t + hz] if b else [])
    d = d.assign(org=org)
    d = d[(d.org.map(len) > 0) | (d.purchased.fillna("") != "")]
    print("requests with a target:", len(d), flush=True)
    rows = []          # (cohort, burst, kind, [rank per variant])
    t0 = time.time()
    for g, cat, unavail, S, newp, burst in snapshots(R, qrank, LF, aff, d, H, it):
        ids = np.array(S.ids, dtype=object); un = np.isin(ids, list(unavail))
        for r in g.itertuples():
            st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            b, lc, hcu, bt, mix, mfu = st
            page = r.page or "product"; seg = "new" if r.new_user else "known"
            a = LB.aff_asof(aff, r.user_id, r.rv, r.ts)
            X = lfm.features(S, a, r.rv, page, hcu, lc, bought_today=bt, seg=lfm.in_segment(r.device, r.region), mix=mix, mfu=mfu, grp=lfm.seg_key(r.device, r.region))
            dead = CV.dead_mask(S, st, r.user_id) | un
            coh = seg + ("/page" if (r.rv and page in lfm.LQ_PAGES) else "/home" if not r.rv else "/other")
            tg = [("org", S.row[i]) for i in r.org if i in S.row and not dead[S.row[i]]]
            if r.purchased and r.purchased in S.row: tg.append(("fb", S.row[r.purchased]))
            if not tg: continue
            ranks = {k: [] for k in range(len(tg))}
            for n in names:
                pw, hw = W[n]; w, b0 = hw if (hw is not None and not r.rv) else pw
                s = X @ w[seg] + b0[seg]
                if n in RCV and lc and lfm.recart_target(seg == "new", page, r.rv):
                    h = LF.hcart.get(r.user_id)
                    if h:
                        for p in lc:
                            c = h.get(p); k = S.row.get(p) if c else None
                            if k is not None: s[k] += max(0.0, w[seg][FI["chn"]] * math.log1p(c) - w[seg][FI["cl"]])
                s[dead] = -np.inf
                top = lfm.top_items(S, s)
                # Count only products the writer would actually select, including ties at positions 3 and 10.
                positions = {S.row[p]: rank for rank, p in enumerate(top, start=1)} if len(top) == 10 else {}
                for j, (kind, k) in enumerate(tg):
                    ranks[j].append(positions.get(k, 9999))
            for j, (kind, k) in enumerate(tg):
                ty = "cart" if (X[k, FI["chn"]] > 0 or X[k, FI["cl"]] > 0) else "newp" if S.ids[k] in newp else "other"
                t8 = CV.TYPES[int(CV.types_of(X, S, np.array([k]), S.row.get(r.rv[-1]) if r.rv else None, mix)[0][0])]
                rows.append((coh, burst, kind, ty, ranks[j], t8))
    print("scored in %.0f s" % (time.time() - t0), flush=True)
    res = {}
    def table(sel, label):
        Rk = np.array([x[4] for x in sel]);
        if len(Rk) < 30: return
        o = {}
        for c, n in enumerate(names):
            h10 = (Rk[:, c] <= 10).astype(float); h3 = (Rk[:, c] <= 3).astype(float); bi = names.index(base)
            d10 = h10 - (Rk[:, bi] <= 10); d3 = h3 - (Rk[:, bi] <= 3)
            o[n] = dict(at10=round(100 * h10.mean(), 2), at3=round(100 * h3.mean(), 2), d10=round(100 * d10.mean(), 2), se10=round(100 * d10.std() / math.sqrt(len(d10)), 2),
                        d3=round(100 * d3.mean(), 2), se3=round(100 * d3.std() / math.sqrt(len(d3)), 2))
        res[label] = dict(n=len(Rk), variants=o)
        print("\n== %s (n = %d targets) | hit %% and paired difference vs %s (se)" % (label, len(Rk), base))
        print(pd.DataFrame(o).T.to_string())
    for kind in ("org", "fb"):
        for coh in COH:
            table([x for x in rows if x[0] == coh and x[2] == kind], f"{kind} | {coh}")
            table([x for x in rows if x[0] == coh and x[2] == kind and x[3] != "cart"], f"{kind} | {coh} | target not a cart")
            table([x for x in rows if x[0] == coh and x[2] == kind and x[3] == "newp"], f"{kind} | {coh} | target launched today")
            table([x for x in rows if x[0] == coh and x[2] == kind and x[1]], f"{kind} | {coh} | during a burst")
    # hits in the top 10 by product type of the target (cart_variants.TYPES), returning shoppers on pages
    for kind in ("org", "fb"):
        sel = [x for x in rows if x[0] == "known/page" and x[2] == kind]
        if not sel: continue
        T = pd.DataFrame({n: pd.Series([x[5] for x in sel if x[4][c] <= 10]).value_counts() for c, n in enumerate(names)}).fillna(0).astype(int)
        T.insert(0, "targets", pd.Series([x[5] for x in sel]).value_counts()); T.loc["TOTAL"] = T.sum()
        res[kind + " | known/page | top-10 hits by target type"] = T.to_dict()
        print("\n== %s | known/page | number of targets in the top 10, by type of the target" % kind); print(T.to_string())
    if out: Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(dict(kind="OFFLINE ESTIMATE", base=base, horizon_min=horizon_min, variants=G, tables=res), indent=1))
    return res


def check(files, n=4000, since="2026-11-14 17:00:00", out=None):
    """The writer's own path (clean_lfm_arms -> set_arms -> LiveFit.slate) for each policy against r3, same requests."""
    lfm, LB, R, qrank, CV, d, LF, aff, carts, buys, H, it = load_all()
    FI = {f: k for k, f in enumerate(lfm.FEATS)}
    src = (HERE / "live.py").read_text(); i0 = src.index("def clean_lfm_arms"); i1 = src.index("def lfm_route")
    ns = {"lfm": lfm}; exec(src[i0:i1], ns); clean = ns["clean_lfm_arms"]          # the writer's function, unchanged
    pol = {"r3": [{"tag": "r3", "file": R3}]}
    for f in files:
        conf = json.loads((HERE / f).read_text()); arms = clean(conf.get("lfm_arms"))
        assert conf.get("variant") == "lfm" and len(arms) == 1, f + ": rejected by clean_lfm_arms"
        assert json.dumps(arms, sort_keys=True) == json.dumps([{**a, "tag": a["tag"].lower()} for a in conf["lfm_arms"]], sort_keys=True), f + ": cleaned arm differs from the file"
        pol[f] = arms
    d = d[(d.ts >= pd.Timestamp(since)) & (d.served_by == "team")]; d = d.iloc[::max(1, len(d) // n)]
    ms = collections.defaultdict(list); st_ = collections.defaultdict(collections.Counter)
    for g, cat, unavail, S, newp, burst in snapshots(R, qrank, LF, aff, d, H, it):
        for r in g.itertuples():
            st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            shim = R.AffAsOf(aff); shim.ts = r.ts
            page = r.page or "product"
            req = dict(user_id=r.user_id, rv=r.rv, page=page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
            seg = ("new" if r.new_user else "known") + ("/page" if (r.rv and page in lfm.LQ_PAGES) else "/home" if not r.rv else "/other")
            X = lfm.features(S, shim.affinity_all(r.user_id, r.rv), r.rv, page, st[2], st[1], bought_today=st[3], seg=lfm.in_segment(r.device, r.region), mix=st[4], mfu=st[5], grp=lfm.seg_key(r.device, r.region))
            last = S.row.get(r.rv[-1]) if r.rv else None
            outs = {}
            for f, arms in pol.items():
                LF.set_arms(arms); t0 = time.perf_counter(); s = LF.slate(req, st, shim, exclude=unavail, model=arms[0]["tag"]); ms[f].append(1000 * (time.perf_counter() - t0))
                ok = s is not None and len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & st[0]) and all(p in cat.index for p in s)
                outs[f] = (s, ok)
            b = outs["r3"][0]
            for f in pol:
                s, ok = outs[f]
                for key in (f + "|" + seg, f + "|all") + ((f + "|" + seg + "|burst",) if burst else ()):
                    c = st_[key]; c["requests"] += 1; c["valid"] += ok; c["changed"] += s != b; c["slot1"] += bool(s and b and s[0] != b[0])
                    c["overlap"] += len(set(s or ()) & set(b or ()))
                    if s:
                        rows = np.array([S.row[p] for p in s]); ty, cart, sess = CV.types_of(X, S, rows, last, st[4])
                        for t in range(8): c["ty_" + CV.TYPES[t]] += int((ty == t).sum())
                        c["launched"] += sum(p in newp for p in s); c["hot"] += int(X[rows, FI["hot"]].sum()); c["carts_top3"] += int(cart[:3].sum())
    res = {}
    for key, c in sorted(st_.items()):
        m = max(1, c["requests"])
        res[key] = dict(requests=c["requests"], valid_pct=round(100 * c["valid"] / m, 2), changed_pct=round(100 * c["changed"] / m, 1), slot1_changed_pct=round(100 * c["slot1"] / m, 1),
                        overlap=round(c["overlap"] / m, 2), launched_per_list=round(c["launched"] / m, 2), hot_per_list=round(c["hot"] / m, 2), carts_top3=round(c["carts_top3"] / m, 2),
                        mix_pct={t: round(10 * c["ty_" + t] / m, 1) for t in CV.TYPES})
    pct = lambda v, q: round(float(np.percentile(v, q)), 2)
    lat = {f: dict(p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99), max=round(max(v), 1)) for f, v in ms.items()}
    pd.set_option("display.width", 250)
    print(pd.DataFrame({k: {c: v[c] for c in v if c != "mix_pct"} | v["mix_pct"] for k, v in res.items()}).T.to_string())
    print("latency ms", json.dumps(lat))
    if out: Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(dict(kind="diagnostics: validity and exposure, NOT conversion", since=since, requests=int(len(d)), policies={f: pol[f] for f in files}, segments=res, latency_ms=lat), indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["targets", "check"]); ap.add_argument("files", nargs="*")
    ap.add_argument("--n", type=int, default=4000); ap.add_argument("--since", default="2026-11-14 17:00:00"); ap.add_argument("--grid"); ap.add_argument("--out"); ap.add_argument("--base", default="r3")
    a = ap.parse_args()
    if a.cmd == "targets": targets(json.loads(Path(a.grid).read_text()) if a.grid else None, a.out, a.base)
    else: check(a.files, a.n, a.since, a.out)
