"""E-430 — single-arm cart variants for the 15-minute rotation (T-043). DIAGNOSTICS + OFFLINE ESTIMATE, never a result:
the hidden model decides, on the leaderboard (team minus reference, same window).

    cd recsys
    python download_user_items.py && python cold_lq_replay.py --pull      # READ-ONLY RawTree
    python cart_variants.py fit                                           # value model from our own feedback -> data/cartv/value.json
    python cart_variants.py replay [--n 9000] [--since "2026-11-14 17:00"] [--grid file.json] [--out file.json]
    python cart_variants.py check  policy.rot_cx6.json ...                # the writer's own path: clean_lfm_arms + set_arms + slate, latency

replay: every sampled answered request is scored with the snapshot and shopper state AS OF the request (catalogue, stock
and state exactly as cold_lq_replay.py / snap_price_replay.py build them), once per variant. Output per variant:
how many lists change against r3, slate composition by product type, and two offline value estimates for returning
shoppers on product/category pages (cell rates, and a logistic model with shopper traits). Both estimates come from
lists r3 chose, so they are biased towards what r3 showed; they rank variants, they do not predict the leaderboard.
"""
from __future__ import annotations

import argparse, collections, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "data" / "cartv"
R3 = "lfm_coef_r3.json"
TYPES = ["cart_sess", "cart_other", "last", "rv_other", "same_sub", "same_cat", "own_cat", "filler"]
VF = ["ls", "cart", "chn", "cl", "cart_sess", "cart_ucat", "islast", "oinrv", "ssub2", "scat2", "ucat", "usub", "aff10", "lq", "na",
      "p40", "newp", "lpend", "lviews", "cart_lpend"]
OWN = 0.20            # a category holding at least this share of the shopper's views is "theirs"

# name -> arm spec without tag (the tag is the name). Every variant keeps r3 on home and never touches new shoppers.
H = {"home": {"file": R3}}
GRID = {
    "r3": {"file": R3},
    "cx3": {"file": R3, "w": {"known": {"chn": 3.0}}, **H},
    "og1": {"file": "lfm_coef_og1.json", **H},
}


def types_of(X, S, rows, last, mix):
    """Product type of each row (priority order of TYPES)."""
    f = lambda n: X[rows, FI[n]]
    cart = (f("chn") > 0) | (f("cl") > 0)
    sess = (S.cat[rows] == S.cat[last]) if last is not None else np.zeros(len(rows), bool)
    share = np.zeros(len(rows))
    if mix is not None and S.ucode is not None:
        cv = mix[0]; t = float(cv.sum()); uc = S.ucode[rows]
        if t > 0: share = np.where(uc >= 0, cv[np.maximum(uc, 0)] / t, 0.0)
    out = np.full(len(rows), 7)
    out[share >= OWN] = 6
    out[f("scat2") > 0] = 5
    out[f("ssub2") > 0] = 4
    out[f("oinrv") > 0] = 3
    out[f("islast") > 0] = 2
    out[cart & ~sess] = 1
    out[cart & sess] = 0
    return out, cart, sess


def vfeat(X, rows, slots, cart, sess, npend, nviews):
    f = lambda n: X[rows, FI[n]]
    lp, lv = np.log1p(npend), np.log1p(nviews)
    c = cart.astype(float)
    cols = dict(ls=np.log(slots), cart=c, chn=f("chn"), cl=f("cl"), cart_sess=c * sess, cart_ucat=c * f("ucat"), islast=f("islast"), oinrv=f("oinrv"),
                ssub2=f("ssub2"), scat2=f("scat2"), ucat=f("ucat"), usub=f("usub"), aff10=f("aff10"), lq=f("lq"), na=f("na"), p40=f("p40"), newp=f("newp"),
                lpend=np.full(len(rows), lp), lviews=np.full(len(rows), lv), cart_lpend=c * lp)
    return np.column_stack([cols[k] for k in VF])


SG = np.array([0, 1, 1, 2, 2, 3, 3, 4, 4, 4])            # slot group of slots 1..10: 1 | 2-3 | 4-5 | 6-7 | 8-10
def PB(npend): return 0 if npend == 0 else 1 if npend < 5 else 2 if npend < 15 else 3


def cell_table(k=1500.0):
    """Purchase rate by (shopper's pending carts: 0 | 1-4 | 5-14 | 15+) x product type x slot group, from the impressions saved
    by `fit`. Cells are shrunk towards (type rate within the pending bucket) x (overall slot curve) with weight k impressions."""
    I = pd.read_parquet(OUT / "imp.parquet"); I = I[I.dead == 0]
    pb = I.npend.map(PB).values; sg = SG[I.slot.values - 1]; ty = I.ty.values; buy = I.buy.values
    base = buy.mean(); curve = np.array([buy[sg == g].mean() / base for g in range(5)])
    T = np.zeros((4, 8, 5))
    for a in range(4):
        for t in range(8):
            m = (pb == a) & (ty == t); r = (buy[m].sum() + 50 * buy[ty == t].mean()) / (m.sum() + 50) if m.sum() else buy[ty == t].mean()
            r = r / max(1e-9, (curve[sg[m]].mean() if m.sum() else 1.0))              # rate at curve = 1
            for g in range(5):
                c = m & (sg == g); T[a, t, g] = (buy[c].sum() + k * r * curve[g]) / (c.sum() + k)
    return T


def setup():
    global FI, lfm, LB
    import lfm, lfm_build as LB
    FI = {f: k for k, f in enumerate(lfm.FEATS)}
    d, LF, aff, carts, buys = LB.load()
    LF.lq0 = float(json.loads((HERE / R3).read_text()).get("lq0", LF.lq0))
    return d, LF, aff, carts, buys


def dead_mask(S, st, u):
    bought, lc, hc = st[:3]
    dead = ~S.ok
    stl = S.stale(u)
    if stl is not None:
        keep = [S.row[p] for p in list(hc) + list(lc) if p in S.row]
        stl[keep] = False; dead = dead | stl
    b = [S.row[p] for p in bought if p in S.row]
    if b: dead[b] = True
    return dead


def fit(since=None, cut="2026-11-14 20:00:00"):
    """Value model on what we showed returning shoppers on pages with views (all day). Temporal hold-out reported."""
    from sklearn.linear_model import LogisticRegression
    d, LF, aff, carts, buys = setup()
    S = LF.snap
    k = d[(~d.new_user) & (d.rv.str.len() > 0) & d.page.isin(lfm.LQ_PAGES)]
    if since: k = k[k.ts >= pd.Timestamp(since)]
    rows, meta, xrows = [], [], []
    for r in k.itertuples():
        st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
        b, lc, hc, bt, mix, mfu = st
        idx = [S.row.get(p, -1) for p in r.shown]
        if min(idx) < 0 or len(idx) != 10: continue
        idx = np.array(idx)
        X = lfm.features(S, LB.aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, bought_today=bt, seg=lfm.in_segment(r.device, r.region), mix=mix, mfu=mfu)
        last = S.row.get(r.rv[-1])
        ty, cart, sess = types_of(X, S, idx, last, mix)
        V = vfeat(X, idx, np.arange(1, 11), cart, sess, len(hc) + len(lc), float(mix[0].sum()))
        dead = dead_mask(S, st, r.user_id)[idx]
        rows.append(V); xrows.append(X[idx])
        for s in range(10): meta.append((r.Index, s + 1, int(ty[s]), int(r.shown[s] == r.purchased), int(r.shown[s] == r.clicked), int(dead[s]), r.ts, len(hc) + len(lc)))
    V = np.vstack(rows); M = pd.DataFrame(meta, columns=["rid", "slot", "ty", "buy", "clk", "dead", "ts", "npend"])
    live = (M.dead == 0).values
    OUT.mkdir(parents=True, exist_ok=True); pd.concat([M, pd.DataFrame(V, columns=VF)], axis=1).to_parquet(OUT / "imp.parquet"); pd.DataFrame(np.vstack(xrows), columns=lfm.FEATS).to_parquet(OUT / "impx.parquet")
    tr = live & (M.ts < pd.Timestamp(cut)).values; te = live & ~tr
    m = LogisticRegression(C=1.0, max_iter=5000).fit(V[tr], M.buy[tr])
    p = m.predict_proba(V[te])[:, 1]
    hold = dict(test_impressions=int(te.sum()), test_buys=int(M.buy[te].sum()), predicted_buys=round(float(p.sum()), 1))
    # does the model order held-out slates? buys predicted vs observed per request, by tercile of predicted slate value
    T = M[te].assign(p=p).groupby("rid").agg(p=("p", "sum"), buy=("buy", "sum"))
    T["q"] = pd.qcut(T.p, 5, labels=False, duplicates="drop")
    hold["by_predicted_quintile"] = [dict(q=int(q), requests=int(len(g)), predicted_pct=round(100 * g.p.mean(), 2), observed_pct=round(100 * g.buy.mean(), 2)) for q, g in T.groupby("q")]
    by_ty = M[te].assign(p=p).groupby("ty").agg(n=("buy", "size"), buy=("buy", "sum"), p=("p", "sum"))
    hold["by_type"] = {TYPES[t]: dict(impressions=int(r.n), buys=int(r.buy), predicted=round(float(r.p), 1)) for t, r in by_ty.iterrows()}
    m = LogisticRegression(C=1.0, max_iter=5000).fit(V[live], M.buy[live])
    A = M[live]
    slot_rate = A.groupby("slot").buy.mean(); ty_rate = A.groupby("ty").buy.mean(); base = A.buy.mean()
    cells = dict(base=float(base), slot={int(s): float(v / base) for s, v in slot_rate.items()}, type={TYPES[int(t)]: float(v) for t, v in ty_rate.items()},
                 type_n={TYPES[int(t)]: int(n) for t, n in A.groupby("ty").size().items()}, type_buys={TYPES[int(t)]: int(n) for t, n in A.groupby("ty").buy.sum().items()})
    # the same table inside shoppers with 5+ pending carts, where stuffing carts matters
    B = A[A.npend >= 5]
    cells["type_5plus"] = {TYPES[int(t)]: dict(n=int(len(g)), buys=int(g.buy.sum()), per10k=round(1e4 * g.buy.mean(), 1)) for t, g in B.groupby("ty")}
    res = dict(feats=VF, w=m.coef_[0].tolist(), b=float(m.intercept_[0]), impressions=int(live.sum()), buys=int(A.buy.sum()), requests=int(A.rid.nunique()),
               dead_shown=int((~live).sum()), cells=cells, holdout=hold, first=str(k.ts.min()), last=str(k.ts.max()))
    OUT.mkdir(parents=True, exist_ok=True); (OUT / "value.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "w"}, indent=1)); print(dict(zip(VF, np.round(m.coef_[0], 3))))
    return res


def weights(spec):
    """(page weights, home weights) per segment, exactly as LiveFit.set_arms builds them."""
    def build(a):
        c = json.loads((HERE / a.get("file", R3)).read_text())
        w = {k: np.array([c[k]["w"].get(f, 0.0) for f in lfm.FEATS]) for k in ("known", "new")}
        b = {k: float(c[k]["b"]) for k in ("known", "new")}
        for seg, over in (a.get("w") or {}).items():
            for f, val in over.items(): w[seg][FI[f]] = float(val)
        return w, b
    return build(spec), (build(spec["home"]) if isinstance(spec.get("home"), dict) else None)


def replay(n=9000, since="2026-11-14 17:00:00", grid=None, out=None, base="r3"):
    import cold_lq_replay as R, qrank
    d, LF, aff, carts, buys = setup()
    G = dict(GRID); G.update(grid or {})
    W = {name: weights(spec) for name, spec in G.items()}
    val = json.loads((OUT / "value.json").read_text()); vw = np.array(val["w"]); vb = val["b"]; cells = val["cells"]
    slot_mult = np.array([cells["slot"][str(s)] for s in range(1, 11)]); ty_rate = np.array([cells["type"].get(t, 0.0) for t in TYPES])
    CT = cell_table()
    hc = LF.snap.hc
    d = d[d.ts >= pd.Timestamp(since)]
    step = max(1, len(d) // n); d = d.iloc[::step]
    C = R.Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib")
    shim = R.AffAsOf(aff)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    stats = collections.defaultdict(collections.Counter)
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        QR.set_catalog(cat, unavail)
        newp = set(cat.index) - set(QR.q)
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, newp=newp or None)
        S = LF.snap; ids = np.array(S.ids, dtype=object); un = np.isin(ids, list(unavail))
        for r in g.itertuples():
            shim.ts = r.ts
            st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            b, lc, hcu, bt, mix, mfu = st
            page = r.page or "product"; seg = "new" if r.new_user else "known"
            X = lfm.features(S, shim.affinity_all(r.user_id, r.rv), r.rv, page, hcu, lc, bought_today=bt, seg=lfm.in_segment(r.device, r.region), mix=mix, mfu=mfu)
            dead = dead_mask(S, st, r.user_id) | un
            is_page = bool(r.rv) and page in lfm.LQ_PAGES
            coh = seg + ("/page" if is_page else "/home")
            last = S.row.get(r.rv[-1]) if r.rv else None
            npend = len(hcu) + len(lc); nviews = float(mix[0].sum())
            pend_rows = [S.row[p] for p in list(hcu) + list(lc) if p in S.row]
            pend_ok = int((~dead[pend_rows]).sum()) if pend_rows else 0
            pb = "0" if pend_ok == 0 else "1-4" if pend_ok < 5 else "5-9" if pend_ok < 10 else "10-19" if pend_ok < 20 else "20+"
            slates = {}
            for name, (pw, hw) in W.items():
                w, b0 = hw if (hw is not None and not r.rv) else pw
                s = X @ w[seg] + b0[seg]; s[dead] = -np.inf
                top = np.argpartition(-s, 30)[:30]; top = top[np.argsort(-s[top], kind="stable")]
                top = top[np.isfinite(s[top])][:10]
                slates[name] = top
            ref = slates[base]
            for name, top in slates.items():
                keys = [name + "|" + coh, name + "|all"] + ([name + "|known/page|pend " + pb] if coh == "known/page" else [])
                ty, cart, sess = types_of(X, S, top, last, mix)
                if coh == "known/page":
                    V = vfeat(X, top, np.arange(1, len(top) + 1), cart, sess, npend, nviews)
                    pm = 1.0 / (1.0 + np.exp(-(V @ vw + vb)))
                    pc = ty_rate[ty] * slot_mult[:len(top)]
                    ps = CT[PB(npend), ty, SG[:len(top)]]
                for key in keys:
                    c = stats[key]; c["requests"] += 1; c["valid"] += len(top) == 10 and len(set(top.tolist())) == 10
                    c["changed"] += not np.array_equal(top, ref); c["slot1_changed"] += top[0] != ref[0]; c["top3_changed"] += not np.array_equal(top[:3], ref[:3])
                    c["replaced"] += len(set(top.tolist()) - set(ref.tolist()))
                    c["pending_available"] += pend_ok; c["carts"] += int(cart.sum()); c["carts_top3"] += int(cart[:3].sum()); c["slot1_cart"] += int(cart[0])
                    c["no_cart_but_has"] += int(cart.sum() == 0 and pend_ok > 0); c["newp"] += int(X[top, FI["newp"]].sum())
                    for t in range(8): c["ty_" + TYPES[t]] += int((ty == t).sum())
                    if coh == "known/page": c["v_model"] += float(pm.sum()); c["v_cells"] += float(pc.sum()); c["v_model_cart"] += float(pm[cart].sum()); c["v_strat"] += float(ps.sum()); c["sess_carts"] += int((ty == 0).sum()); c["sess_carts_top3"] += int((ty[:3] == 0).sum())
    res = {}
    for key, c in sorted(stats.items()):
        m = max(1, c["requests"]); row = dict(requests=c["requests"], valid_pct=round(100 * c["valid"] / m, 2), lists_changed_pct=round(100 * c["changed"] / m, 1),
                   slot1_changed_pct=round(100 * c["slot1_changed"] / m, 1), top3_changed_pct=round(100 * c["top3_changed"] / m, 1), products_replaced=round(c["replaced"] / m, 2),
                   carts_per_list=round(c["carts"] / m, 2), carts_top3=round(c["carts_top3"] / m, 2), slot1_cart_pct=round(100 * c["slot1_cart"] / m, 1),
                   pending_available=round(c["pending_available"] / m, 2), has_carts_none_shown_pct=round(100 * c["no_cart_but_has"] / m, 1),
                   launched_per_list=round(c["newp"] / m, 3), mix_pct={t: round(10 * c["ty_" + t] / m, 1) for t in TYPES})
        if "v_model" in c:
            row["est_conv_model_pct"] = round(100 * c["v_model"] / m, 3); row["est_conv_cells_pct"] = round(100 * c["v_cells"] / m, 3)
            row["est_cart_buys_model_pct"] = round(100 * c["v_model_cart"] / m, 3); row["est_conv_strat_pct"] = round(100 * c["v_strat"] / m, 3)
            row["sess_carts"] = round(c["sess_carts"] / m, 2); row["sess_carts_top3"] = round(c["sess_carts_top3"] / m, 2)
        res[key] = row
    for key, row in res.items():                      # differences against the base arm, same requests
        name, rest = key.split("|", 1); b = res.get(base + "|" + rest)
        if b and "est_conv_model_pct" in row:
            row["d_model_pp"] = round(row["est_conv_model_pct"] - b["est_conv_model_pct"], 3); row["d_cells_pp"] = round(row["est_conv_cells_pct"] - b["est_conv_cells_pct"], 3); row["d_strat_pp"] = round(row["est_conv_strat_pct"] - b["est_conv_strat_pct"], 3)
    full = dict(kind="diagnostics + OFFLINE ESTIMATE from r3-chosen lists; not a leaderboard prediction", since=since, requests=int(len(d)), first=str(d.ts.min()), last=str(d.ts.max()),
                base=base, variants=G, segments=res)
    if out: Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(full, indent=1))
    cols = ["lists_changed_pct", "slot1_changed_pct", "products_replaced", "carts_per_list", "carts_top3", "has_carts_none_shown_pct", "sess_carts_top3", "d_model_pp", "d_strat_pp", "d_cells_pp"]
    T = pd.DataFrame({k.split("|")[0]: {c: v.get(c) for c in cols} | {"filler%": v["mix_pct"]["filler"], "own%": v["mix_pct"]["own_cat"], "sub+cat%": v["mix_pct"]["same_sub"] + v["mix_pct"]["same_cat"]}
                      for k, v in res.items() if k.endswith("|known/page")}).T
    pd.set_option("display.width", 250); print(T.sort_values("d_model_pp", ascending=False).to_string())
    other = {k: v["lists_changed_pct"] for k, v in res.items() if k.split("|", 1)[1] in ("known/home", "new/page", "new/home")}
    print("changed outside known pages (must be 0):", {k: v for k, v in other.items() if v})
    return full


def check(files, n=1500, since="2026-11-14 21:00:00"):
    """The writer's own path for each policy file: clean_lfm_arms -> set_arms -> LiveFit.slate, validity and latency."""
    import os
    os.environ.setdefault("DRY_RUN", "1")
    import cold_lq_replay as R, qrank
    d, LF, aff, carts, buys = setup()
    import importlib
    try:
        sys.argv = [sys.argv[0], "--dry-run"]; live = importlib.import_module("live"); clean = live.clean_lfm_arms
    except BaseException as e:                         # live.py wants its environment: fall back to the function's source, unchanged
        print("live import failed (%s), reading clean_lfm_arms from live.py source" % type(e).__name__)
        src = (HERE / "live.py").read_text(); a = src.index("def clean_lfm_arms"); b = src.index("def lfm_route")
        ns = {"lfm": lfm}; exec(src[a:b], ns); clean = ns["clean_lfm_arms"]
    pol = {}
    for f in files:
        conf = json.loads((HERE / f).read_text()); arms = clean(conf.get("lfm_arms"))
        assert conf.get("variant") == "lfm" and len(arms) == 1 and "lq" not in arms[0], f + ": rejected by clean_lfm_arms or carries lq"
        assert json.dumps(arms, sort_keys=True) == json.dumps([{**a, "tag": a["tag"].lower()} for a in conf["lfm_arms"]], sort_keys=True), f + ": cleaned arms differ from the file"
        pol[f] = arms
    hc = LF.snap.hc
    d = d[d.ts >= pd.Timestamp(since)]; d = d.iloc[::max(1, len(d) // n)]
    C = R.Catalogue(); QR = qrank.Ranker.load(HERE / "data" / "qrank.joblib"); shim = R.AffAsOf(aff)
    d = d.assign(ver=[C.version(t) for t in d.ts], bucket=d.ts.dt.floor("10min"))
    ms = collections.defaultdict(list); ok = collections.Counter(); mism = collections.Counter()
    for (ver, bucket), g in d.groupby(["ver", "bucket"], sort=True, dropna=False):
        cat, unavail, desc = C.asof(None if pd.isna(ver) else ver)
        QR.set_catalog(cat, unavail); newp = set(cat.index) - set(QR.q)
        LF.set_catalog(cat, unavail, aff, QR.lq, hc, newp=newp or None)
        S = LF.snap; ids = np.array(S.ids, dtype=object); un = np.isin(ids, list(unavail))
        for r in g.itertuples():
            shim.ts = r.ts; st = LB.replay_state(LF, aff, carts, buys, r.user_id, r.ts)
            req = dict(user_id=r.user_id, rv=r.rv, page=r.page or "product", is_new_user=bool(r.new_user), device=r.device, region=r.region)
            for f, arms in pol.items():
                LF.set_arms(arms); tag = arms[0]["tag"]
                t0 = time.perf_counter(); s = LF.slate(req, st, shim, exclude=unavail, model=tag); ms[f].append(1000 * (time.perf_counter() - t0))
                good = s is not None and len(s) == 10 and len(set(s)) == 10 and not (set(s) & unavail) and not (set(s) & st[0]) and all(p in cat.index for p in s)
                ok[f] += good
                # the fast path used by `replay` must give the same list
                (pw, hw) = weights({k: v for k, v in arms[0].items() if k != "tag"}); w, b0 = hw if (hw is not None and not r.rv) else pw
                seg = "new" if r.new_user else "known"
                X = lfm.features(S, shim.affinity_all(r.user_id, r.rv), r.rv, req["page"], st[2], st[1], bought_today=st[3], seg=lfm.in_segment(r.device, r.region), mix=st[4], mfu=st[5])
                sc = X @ w[seg] + b0[seg]; sc[dead_mask(S, st, r.user_id) | un] = -np.inf
                top = np.argsort(-sc, kind="stable")[:10]
                mism[f] += s is None or [S.ids[k] for k in top] != s
    pct = lambda v, q: round(float(np.percentile(v, q)), 2)
    res = {f: dict(arms=pol[f], requests=len(ms[f]), valid_pct=round(100 * ok[f] / len(ms[f]), 2), fast_path_mismatch=mism[f],
                   latency_ms=dict(p50=pct(ms[f], 50), p95=pct(ms[f], 95), p99=pct(ms[f], 99), max=round(max(ms[f]), 2))) for f in pol}
    print(json.dumps(res, indent=1)); return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["fit", "replay", "check"]); ap.add_argument("files", nargs="*")
    ap.add_argument("--n", type=int, default=9000); ap.add_argument("--since", default="2026-11-14 17:00:00"); ap.add_argument("--grid"); ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "fit": fit()
    elif a.cmd == "replay": replay(a.n, a.since, json.loads(Path(a.grid).read_text()) if a.grid else None, a.out)
    else: check(a.files, since=a.since if a.since != "2026-11-14 17:00:00" else "2026-11-14 21:00:00")
