"""Fit and validate lfm (live-fitted model) on our own carousel feedback. Read-only on RawTree; writes lfm_coef.json.

    python lfm_build.py --pull          # download feedback/requests/events/catalog to data/lfm_*.parquet, then fit
    python lfm_build.py                 # refit from the cached files
    python lfm_build.py --cut "2026-11-14 13:10"    # time split used for the hold-out report (default: last 30%)
    python lfm_build.py --base lfm_coef_r3.json --add cv --out lfm_coef_r5.json    # keep r3's weights, fit only the new feature

What it does
  1. Replays every answered request: for each of the 10 products shown it rebuilds, AS OF the request time, the
     same features lfm.py computes when serving (lfm.features is shared, so training and serving cannot differ).
  2. Fits one logistic model for returning shoppers and one for new shoppers. Label = clicked, purchases weighted x3
     (a purchase is always a click; clicks are 3.3x more frequent, which halves the noise). Slot enters as log(slot)
     during the fit and is dropped when serving (the best product goes first).
  3. Hold-out report (fit on requests before --cut, test after): AUC, calibration by segment, and the model's
     estimate of expected purchases per 100 requests for the slates we actually showed vs the slates lfm would show.
  4. Refits on everything and writes lfm_coef.json.

The "would show" number is a MODEL estimate (the model grading its own choice, so it is optimistic). The real test
is the leaderboard's per-model_version row: the hidden model's expected conversion, readable ~15 min after switching.
"""
from __future__ import annotations
import json, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
import cold_items, attr_affinity, home_cands, lfm

warnings.filterwarnings("ignore")
DATA = Path(__file__).resolve().parent / "data"
BUY_W, C_REG = 3.0, 10.0


def pull():
    from rt import q
    team = __import__("os").environ.get("TEAM_ID", "team_26")
    fb = q(f"""SELECT request_id::String request_id, toJSONString(shown) shown, served_by::String served_by,
        clicked::String clicked, purchased::String purchased, ts::String fb_ts FROM {team}.feedback WHERE request_id::String != '__init__'""")
    t0 = q(f"SELECT min(ts::DateTime64(3))::String t FROM {team}.feedback WHERE request_id::String != '__init__'").t[0]
    rq = q(f"""SELECT request_id::String request_id, ts::String ts, user_id::String user_id, is_new_user::Bool new_user,
        context.page::String page, context.device::String device, context.region::String region, toJSONString(recent_views) rv FROM shop.requests
        WHERE ts::DateTime64(3) >= toDateTime64('{t0[:19]}',3) - INTERVAL 10 MINUTE""")
    sb = q(f"SELECT request_id::String request_id, any(model_version::String) mv FROM {team}.submissions GROUP BY request_id")
    fb.merge(rq, on="request_id").merge(sb, on="request_id", how="left").to_parquet(DATA / "lfm_fb.parquet")
    ev = pd.concat([q(f"""SELECT user_id::String u, product_id::String i, event_type::String e, min(ts::DateTime64(3))::String t0
        FROM shop.events WHERE event_type::String IN ('add_to_cart','purchase') AND cityHash64(user_id::String)%2={m} GROUP BY u,i,e""") for m in range(2)])
    ev.to_parquet(DATA / "lfm_ev.parquet")
    # today's organic views in 10-minute buckets: the writer's affinity includes them, so the fit must too (as of each request)
    pd.concat([q(f"""SELECT user_id::String u, product_id::String i, toStartOfInterval(ts::DateTime64(3), INTERVAL 10 MINUTE)::String t, count() n
        FROM shop.events WHERE event_type::String = 'view' AND cityHash64(user_id::String)%4={m} GROUP BY u,i,t""") for m in range(4)]).to_parquet(DATA / "lfm_views.parquet")
    q("""SELECT product_id::String product_id, argMax(category::String,v) category, argMax(subcategory::String,v) sub,
        argMax(brand::String,v) brand, argMax(price_eur::Float64,v) price, argMax(description::String,v) description
        FROM (SELECT product_id, category, subcategory, brand, price_eur, description, '' v FROM shop.catalog
              UNION ALL SELECT product_id, category, subcategory, brand, price_eur, description, toString(ts) FROM shop.catalog_updates)
        GROUP BY product_id""").to_parquet(DATA / "lfm_cat.parquet")
    # every catalogue state with its time (base catalogue: empty ts), so replays can rebuild price / existence / stock as of a request
    q("""SELECT product_id::String product_id, '' ts, price_eur::Float64 price, is_active::Bool active, 'base' change FROM shop.catalog
         UNION ALL SELECT product_id::String, ts::String, price_eur::Float64, is_active::Bool, change::String FROM shop.catalog_updates""").to_parquet(DATA / "lfm_catlog.parquet")
    print("pulled", len(fb), "feedback rows,", len(ev), "cart/purchase rows", flush=True)


def load():
    """-> (requests frame, LiveFit with history, Snap, AttrAffinity, events-as-of lookups)."""
    d = pd.read_parquet(DATA / "lfm_fb.parquet")
    d["shown"] = d.shown.map(json.loads)
    d["rv"] = d.rv.map(lambda s: [x["product_id"] for x in json.loads(s)] if s else [])
    d["ts"] = pd.to_datetime(d.ts); d = d.sort_values("ts").reset_index(drop=True)
    cat = pd.read_parquet(DATA / "lfm_cat.parquet").set_index("product_id")
    hist = pd.read_parquet(DATA / "user_item_all.parquet")
    cold = cold_items.ColdStart()
    for p, desc in cat.description.items():                       # new products: read their phrases from the description
        if p not in cold.attr: cold.attr[p] = cold_items.attrs(desc)
    aff = attr_affinity.AttrAffinity(cold, ui_path=DATA / "user_item_all.parquet")
    try:
        import joblib; lq = {k: float(np.log(max(v, 1e-6))) for k, v in joblib.load(DATA / "qrank.joblib")["q"].items()}
    except Exception as e:
        print("qrank.joblib not readable, lq = 0:", type(e).__name__); lq = {}
    lq0 = float(np.median(list(lq.values()))) if lq else 0.0
    sub_med = pd.Series(lq).reindex(cat.index).groupby(cat["sub"]).transform("median")     # new products: subcategory median, as qrank does
    lq = {p: (lq[p] if p in lq else (float(sub_med[p]) if pd.notna(sub_med[p]) else lq0)) for p in cat.index}
    hc = home_cands.HomeCands(hist, cat)
    LF = lfm.LiveFit({k: dict(w={f: 0.0 for f in lfm.FEATS}, b=0.0) for k in ("known", "new")} | {"lq0": lq0}, hist)
    LF.set_catalog(cat, set(), aff, lq, hc)
    ev = pd.read_parquet(DATA / "lfm_ev.parquet"); ev["t0"] = pd.to_datetime(ev.t0)
    carts, buys = {}, {}
    for u, i, e, t in zip(ev.u.values, ev.i.values, ev.e.values, ev.t0.values):
        (carts if e == "add_to_cart" else buys).setdefault(u, {})[i] = t
    views = {}
    if (DATA / "lfm_views.parquet").exists():
        v = pd.read_parquet(DATA / "lfm_views.parquet"); v = v[v.i.isin(aff.pid)]
        v["t"] = pd.to_datetime(v.t) + pd.Timedelta(minutes=10)            # usable once its bucket has closed
        for u, i, t, n in zip(v.u.values, v.i.values, v.t.values, v.n.values): views.setdefault(u, []).append((t, aff.pid[i], n))
    aff.today = views
    # Replay extras ride on `aff` (like aff.today) so load() keeps its 5-tuple for existing callers.
    aff.fbuys = feedback_buys(d)
    aff.catlog = CatLog(pd.read_parquet(DATA / "lfm_catlog.parquet"), LF.snap) if (DATA / "lfm_catlog.parquet").exists() else None
    return d, LF, aff, carts, buys


FB_LAG = np.timedelta64(30, "s")      # the writer reads its feedback once per refresh cycle (~20 s): a carousel purchase is usable this long after its feedback row


def feedback_buys(d):
    """{user: {product: time the purchase became usable}} from our own carousel feedback. These purchases are NOT in
    shop.events (676 of 695 on 14 Nov), and the scored model treats them as already bought (organizer note)."""
    out = {}
    if "fb_ts" not in d.columns: return out
    b = d[d.purchased != ""]
    for u, i, t in zip(b.user_id.values, b.purchased.values, pd.to_datetime(b.fb_ts).values):
        t = t + FB_LAG; cur = out.setdefault(u, {}).get(i)
        if cur is None or t < cur: out[u][i] = t
    return out


class CatLog:
    """Catalogue as of a moment: which products existed, which were in stock, and their price.
    Built from shop.catalog (state before the event) + every row of shop.catalog_updates (full product state + ts).
    at(ts) -> (exists, unavailable, price) arrays aligned with the snapshot rows. Cheap when called with increasing ts.
    NOT reconstructable (the replay uses the latest value): product quality `lq` (one snapshot), description phrases,
    category / subcategory / brand of a product, and the writer's own refresh delay (catalogue ~1 cycle, stock ~seconds)."""

    def __init__(self, log: pd.DataFrame, S):
        self.n = S.n; r = S.row.get
        base = log[log.change == "base"]; up = log[log.change != "base"].copy()
        self.exists0 = np.zeros(S.n, dtype=bool); self.unav0 = np.zeros(S.n, dtype=bool); self.price0 = np.full(S.n, np.nan)
        for p, pr, ac in zip(base.product_id.values, base.price.values, base.active.values):
            k = r(p)
            if k is not None: self.exists0[k] = True; self.unav0[k] = not ac; self.price0[k] = pr
        up["t"] = pd.to_datetime(up.ts); up = up.sort_values("t", kind="stable")
        self.ev = [(t, r(p), float(pr), bool(ac), ch) for t, p, pr, ac, ch in zip(up.t.values, up.product_id.values, up.price.values, up.active.values, up.change.values) if r(p) is not None]
        self._reset()

    def _reset(self):
        self.k = 0; self.last = None
        self.exists, self.unav, self.price = self.exists0.copy(), self.unav0.copy(), self.price0.copy()

    def at(self, ts):
        ts = np.datetime64(ts)
        if self.last is not None and ts < self.last: self._reset()
        while self.k < len(self.ev) and self.ev[self.k][0] <= ts:          # an update stamped exactly at ts is already in force
            _, k, pr, ac, ch = self.ev[self.k]; self.k += 1
            self.exists[k] = True; self.price[k] = pr
            self.unav[k] = (not ac) or ch == "out_of_stock"
        self.last = ts
        return self.exists, self.unav, self.price

    def price_features(self, X, rows, ts, seg):
        """Overwrite the price-derived columns of X (rows = snapshot rows of X's rows) with the price as of ts."""
        _, _, price = self.at(ts); pr = price[rows]; ok = ~np.isnan(pr)
        X[ok, lfm.FEATS.index("p40")] = (pr[ok] > 40)
        if seg: X[ok, lfm.FEATS.index("segcheap")] = (pr[ok] < 20)
        return X

    def ineligible(self, ts):
        """Row mask: not yet launched or out of stock / inactive as of ts."""
        exists, unav, _ = self.at(ts)
        return ~exists | unav


def aff_asof(aff, u, rv, ts):
    """AttrAffinity.affinity_all as the writer computes it: history + today's views before the request + recent views."""
    vec = aff.user_vec(u, rv); ts = np.datetime64(ts)
    for t, k, n in getattr(aff, "today", {}).get(u, ()):
        if t < ts: vec = vec + aff.A[k] * n
    return (aff.A @ vec + attr_affinity.SHRINK * attr_affinity.NEUTRAL) / (vec.sum() + attr_affinity.SHRINK)


def state_asof(LF, carts, buys, u, ts, fbuys=None):
    """First four parts of LiveFit.user_state, using only events before the request. fbuys: feedback_buys(d); those
    purchases count as bought (and as bought today, as the writer does) once their feedback was readable."""
    ts = np.datetime64(ts)
    bt = {i for i, t in buys.get(u, {}).items() if t < ts}
    if fbuys: bt |= {i for i, t in fbuys.get(u, {}).items() if t < ts}
    b = bt | LF.hbought.get(u, set())
    lc = {i for i, t in carts.get(u, {}).items() if t < ts} - b
    hc = {i: a for i, a in (LF.hcart.get(u) or {}).items() if i not in b and i not in lc}
    return b, lc, hc, bt


def mix_asof(LF, aff, u, ts):
    """LiveFit.user_mix as of the request: history + today's views whose 10-minute bucket had closed."""
    ts = np.datetime64(ts); today = {}
    names = getattr(aff, "_names", None)
    if names is None or len(names) != len(aff.pid): names = aff._names = list(aff.pid)      # row of the attribute matrix -> product
    for t, k, n in getattr(aff, "today", {}).get(u, ()):
        if t < ts: p = names[k]; today[p] = today.get(p, 0) + n
    return LF.user_mix(u, asof=today)


def replay_state(LF, aff, carts, buys, u, ts):
    """EXACTLY what LiveFit.user_state returns when serving (6 parts, the category mix and the collaborative factors
    included), as of the request.
    Use this for every replayed LF.slate()/LF.scores() call: with a 4-part state the model serves WITHOUT ucat/usub
    while the same replay values the slate WITH them (the E-240/E-270 report bug)."""
    return state_asof(LF, carts, buys, u, ts, getattr(aff, "fbuys", None)) + (mix_asof(LF, aff, u, ts), LF.user_mf(u))


def impressions(d, LF, aff, carts, buys):
    """One row per (request, shown product): features, slot, labels, dead flag. `inel` = the catalogue log says the
    product was not launched or not in stock at that moment (a diagnostic of the reconstruction, not a filter).
    d must be sorted by ts (load() does it): the catalogue cursor only moves forward cheaply."""
    S = LF.snap; rows = []; meta = []; catlog = getattr(aff, "catlog", None)
    for r in d.itertuples():
        b, lc, hc, bt, mix, mfu = replay_state(LF, aff, carts, buys, r.user_id, r.ts)
        idx = [S.row.get(p, -1) for p in r.shown]; safe = [k if k >= 0 else 0 for k in idx]; seg = lfm.in_segment(r.device, r.region)
        X = lfm.features(S, aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, idx=safe, mix=mix, bought_today=bt, seg=seg, mfu=mfu)
        inel = None
        if catlog is not None:                       # shown products get the price they had; eligibility is only a diagnostic here
            catlog.price_features(X, np.array(safe), r.ts, seg); inel = catlog.ineligible(r.ts)
        stale = S.stale(r.user_id)
        for s, (p, k) in enumerate(zip(r.shown, idx)):
            dead = k < 0 or p in b or (stale is not None and stale[k] and p not in hc and p not in lc)
            rows.append(X[s]); meta.append((r.Index, s + 1, int(p == r.clicked), int(p == r.purchased), int(dead), int(inel is not None and k >= 0 and inel[k])))
    I = pd.DataFrame(np.array(rows), columns=lfm.FEATS)
    M = pd.DataFrame(meta, columns=["rid", "slot", "clk", "buy", "dead", "inel"])
    I = pd.concat([M, I], axis=1); I["ls"] = np.log(I.slot)
    return I.merge(d[["new_user", "page", "ts"]], left_on="rid", right_index=True)


def fit(I, feats=None):
    """-> coef dict {known/new: {w, b, slot, cal}}. cal = (a, b): P(buy) = sigmoid(a + b * logit).
    feats: subset of lfm.FEATS to fit (the rest get weight 0); default all."""
    from sklearn.linear_model import LogisticRegression
    feats = list(feats or lfm.FEATS)
    out = {}
    for seg, new in (("known", False), ("new", True)):
        a = I[(I.new_user == new) & (I.dead == 0)]
        cols = feats + ["ls"]
        m = LogisticRegression(C=C_REG, max_iter=5000).fit(a[cols], a.clk, sample_weight=np.where(a.buy == 1, BUY_W, 1.0))
        z = a[cols].values @ m.coef_[0] + m.intercept_[0]
        c = LogisticRegression(C=100.0, max_iter=5000).fit(z.reshape(-1, 1), a.buy)
        out[seg] = dict(w=dict(zip(feats, m.coef_[0][:-1].round(4).tolist())), b=round(float(m.intercept_[0]), 4),
                        slot=round(float(m.coef_[0][-1]), 4), cal=[round(float(c.intercept_[0]), 4), round(float(c.coef_[0][0]), 4)],
                        n=int(len(a)), clicks=int(a.clk.sum()), buys=int(a.buy.sum()))
    return out


def p_buy(coef, seg, X, slot):
    """Calibrated purchase probability of feature rows X shown in `slot` (array, 1-based)."""
    c = coef[seg]; w = np.array([c["w"].get(f, 0.0) for f in lfm.FEATS])
    z = X @ w + c["b"] + c["slot"] * np.log(slot)
    return 1.0 / (1.0 + np.exp(-(c["cal"][0] + c["cal"][1] * z)))


def fit_add(I, base, add):
    """`base` weights kept exactly as they are; only the weights of the features in `add` (plus intercept and slot) are
    fitted, with the base score as a fixed offset. Gives a clean A/B: the new arm differs from the base arm ONLY in `add`."""
    out = {}
    for seg, new in (("known", False), ("new", True)):
        a = I[(I.new_user == new) & (I.dead == 0)]
        off = a[lfm.FEATS].values @ np.array([0.0 if f in add else base[seg]["w"].get(f, 0.0) for f in lfm.FEATS])
        Z = np.column_stack([np.ones(len(a)), a.ls.values] + [a[f].values for f in add])
        y = a.clk.values.astype(float); sw = np.where(a.buy == 1, BUY_W, 1.0)
        th = np.zeros(Z.shape[1]); th[0] = base[seg]["b"]; th[1] = base[seg].get("slot", 0.0)
        pen = np.r_[0.0, np.ones(Z.shape[1] - 1) / C_REG]
        for _ in range(50):                                   # Newton steps of a weighted logistic regression with offset
            p = 1.0 / (1.0 + np.exp(-(off + Z @ th)))
            g = Z.T @ (sw * (y - p)) - pen * th
            H = (Z * (sw * p * (1 - p))[:, None]).T @ Z + np.diag(pen)
            step = np.linalg.solve(H, g); th = th + step
            if np.abs(step).max() < 1e-8: break
        se = np.sqrt(np.diag(np.linalg.inv(H)))
        w = dict(base[seg]["w"]); w.update({f: round(float(v), 4) for f, v in zip(add, th[2:])})
        # intercept, slot and the added weights moved, so the base file's click->purchase calibration no longer applies:
        # refit it on the rows this function was given (training rows only when the caller passes the training split)
        from sklearn.linear_model import LogisticRegression
        c = LogisticRegression(C=100.0, max_iter=5000).fit((off + Z @ th).reshape(-1, 1), a.buy)
        out[seg] = dict(base[seg], w=w, b=round(float(th[0]), 4), slot=round(float(th[1]), 4), n=int(len(a)), clicks=int(a.clk.sum()),
                        cal=[round(float(c.intercept_[0]), 4), round(float(c.coef_[0][0]), 4)],
                        buys=int(a.buy.sum()), added={f: dict(w=round(float(v), 4), se=round(float(s), 4)) for f, v, s in zip(add, th[2:], se[2:])})
    return out


R1_FEATS = lfm.FEATS[:11]


def _end(text):
    """End of a "start .. end UTC" range as a Timestamp; raises when it is not one."""
    t = pd.Timestamp(str(text).split("..")[1].replace("UTC", "").strip())
    if pd.isna(t): raise ValueError("no end")
    return t


def provenance(coef, _seen=()):
    """[(component, end of the data it was fitted on)] for EVERY learned part of a coefficient file, or None when any
    part does not say what it saw (missing provenance is never trusted).

    Parts: the file's own fit (meta.fitted_on); every nested block of meta that carries a fitted_on (for example
    meta.mf_fit); and, for a file built on another one (meta.base / meta.added, as fit_add writes them), one entry of
    meta.provenance per inherited or added part: "base" plus each added feature. The base file itself is read too
    when it is in the repository, so a base that was refitted later cannot hide behind an old note.
    A file may also declare external learned inputs there (for example the factorisation behind `mf`)."""
    try:
        meta = coef["meta"]; out = [("fit", _end(meta["fitted_on"]))]
        def nested(d, path):
            for k, v in d.items():
                if isinstance(v, dict):
                    if "fitted_on" in v: out.append((path + k, _end(v["fitted_on"])))
                    nested(v, path + k + ".")
        nested(meta, "meta.")
        declared = meta.get("provenance")
        if declared is not None:
            for e in declared: out.append((str(e["component"]), _end(e["fitted_on"])))
        base, added = meta.get("base"), list(meta.get("added") or [])
        if base or added:
            names = {str(e["component"]) for e in (declared or [])}
            if "base" not in names or any(f not in names for f in added): return None
        if base:
            path = lfm.HERE / str(base)
            if path.exists() and str(base) not in _seen:
                inner = provenance(json.loads(path.read_text()), _seen + (str(base),))
                if inner is None: return None
                out += [(f"{base}:{c}", t) for c, t in inner]
        return out
    except Exception: return None


def fitted_until(coef):
    """End of the data ANY learned part of a coefficient file saw (the latest of provenance()), or None if some part
    does not say."""
    p = provenance(coef)
    return max(t for _, t in p) if p else None


def leaks(coef, cut):
    """True when a learned artifact saw data from the evaluation period (or does not say what it saw): it must not be
    scored on a hold-out that starts at `cut`."""
    t = fitted_until(coef)
    return t is None or t >= pd.Timestamp(cut)


def holdout(I, test_rids, coefs):
    """Ranking and likelihood on the hold-out for several coefficient sets {name: coef}."""
    from sklearn.metrics import roc_auc_score
    T = I[I.rid.isin(test_rids) & (I.dead == 0)]
    rows = []
    for name, coef in coefs.items():
        for seg, new in (("known", False), ("new", True)):
            a = T[T.new_user == new]; X = a[lfm.FEATS].values
            p = p_buy(coef, seg, X, a.slot.values)
            z = X @ np.array([coef[seg]["w"].get(f, 0.0) for f in lfm.FEATS])           # serving score (no slot)
            g = pd.DataFrame(dict(rid=a.rid.values, z=z, buy=a.buy.values, clk=a.clk.values))
            g["rank"] = g.groupby("rid").z.rank(ascending=False, method="average")
            ll = float(np.sum(np.where(a.buy == 1, np.log(p), np.log1p(-p))))
            rows.append((name, seg, len(a), int(a.buy.sum()), int(a.clk.sum()), roc_auc_score(a.buy, p), roc_auc_score(a.clk, p), ll,
                         float((1 / g[g.buy == 1]["rank"]).mean()), float((1 / g[g.clk == 1]["rank"]).mean()), float(p.sum())))
    H = pd.DataFrame(rows, columns=["weights", "seg", "imp", "buys", "clicks", "auc_buy", "auc_click", "loglik_buy", "mrr_buy", "mrr_click", "pred_buys"])
    print("\nhold-out (mrr = mean reciprocal rank of the bought / clicked product among the 10 shown, by serving score):\n", H.round(3).to_string(index=False))
    return H


def report(d, I, LF, aff, carts, buys, coef, test_rids, max_n=4000):
    """Model-estimated value of the logged slates vs the slates these weights would serve (optimistic: self-graded)."""
    LF.w = {k: np.array([coef[k]["w"].get(f, 0.0) for f in lfm.FEATS]) for k in ("known", "new")}; LF.b = {k: coef[k]["b"] for k in ("known", "new")}
    S = LF.snap; res = []
    rng = np.random.default_rng(0); rids = list(test_rids)
    if len(rids) > max_n: rids = list(rng.choice(rids, max_n, replace=False))
    rids = sorted(rids, key=lambda i: d.ts[i]); catlog = getattr(aff, "catlog", None)
    class AsOf:                                    # affinity as the writer sees it at that moment
        def __init__(self, ts): self.ts = ts
        def affinity_all(self, u, rv): return aff_asof(aff, u, rv, self.ts)
    for r in d.loc[rids].itertuples():
        st = replay_state(LF, aff, carts, buys, r.user_id, r.ts); b, lc, hc, bt, mix, mfu = st      # 6 parts: the slate below is built with the category mix and the factors
        seg_flag = lfm.in_segment(r.device, r.region)
        req = dict(user_id=r.user_id, rv=r.rv, page=r.page, is_new_user=bool(r.new_user), device=r.device, region=r.region)
        seg = "new" if r.new_user else "known"
        X = lfm.features(S, aff_asof(aff, r.user_id, r.rv, r.ts), r.rv, r.page, hc, lc, bought_today=bt, seg=seg_flag, mix=mix, mfu=mfu)
        excl = ()
        if catlog is not None:
            catlog.price_features(X, np.arange(S.n), r.ts, seg_flag); inel = catlog.ineligible(r.ts)
            excl = {S.ids[k] for k in np.nonzero(inel)[0]}          # candidate universe as of the request (S.ok is today's)
        stale = S.stale(r.user_id)
        def value(items):
            v = 0.0
            for s, p in enumerate(items):
                k = S.row.get(p)
                if k is None or p in b or (stale is not None and stale[k] and p not in hc and p not in lc): continue   # dead: ~0
                v += float(p_buy(coef, seg, X[k:k + 1], np.array([s + 1]))[0])
            return v
        new = LF.slate(req, st, AsOf(r.ts), exclude=excl)
        res.append((seg, r.page == "home", (r.mv or "?") if r.served_by == "team" else "FALLBACK", int(r.purchased != ""),
                    value(r.shown), value(new) if new else np.nan, len(set(new or ()) & set(r.shown))))
    R = pd.DataFrame(res, columns=["seg", "home", "mv", "buy", "v_logged", "v_new", "overlap"])
    R["mv"] = R.mv.str.replace("-guard", "").str.replace(":v1", "")
    g = R.groupby(["seg", "home"]).agg(n=("buy", "size"), real=("buy", "mean"), logged=("v_logged", "mean"), new=("v_new", "mean"), overlap=("overlap", "mean"))
    g["share"] = g.n / len(R)
    for c in ("real", "logged", "new"): g[c] = (100 * g[c]).round(2)
    print("\nexpected purchases per 100 requests (model estimate; 'real' = purchases that happened; 'new' = slates of these weights):\n", g.round(3).to_string())
    print("\nby logged policy:\n", (R.groupby(["seg", "home", "mv"]).agg(n=("buy", "size"), real=("buy", "mean"), logged=("v_logged", "mean"), new=("v_new", "mean"), overlap=("overlap", "mean")) * [1, 100, 100, 100, 1]).round(2).query("n >= 80").to_string())
    tot = R[["buy", "v_logged", "v_new"]].mean() * 100
    print(f"\nall hold-out requests (n={len(R)}): real {tot.buy:.2f}%  model on logged slates {tot.v_logged:.2f}%  model on new slates {tot.v_new:.2f}%")
    return R


def main():
    if "--pull" in sys.argv: pull()
    out = Path(lfm.HERE / sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else lfm.ART
    feats = R1_FEATS if "--r1" in sys.argv else lfm.FEATS
    d, LF, aff, carts, buys = load()
    I = impressions(d, LF, aff, carts, buys)
    print(len(d), "requests,", len(I), "impressions,", int(I.buy.sum()), "buys,", int(I.clk.sum()), "clicks; dead impressions:",
          int(I.dead.sum()), "with", int(I[I.dead == 1].buy.sum()), "buys; shown while not launched / out of stock per the catalogue log:", int(I.inel.sum()))
    cut = pd.Timestamp(sys.argv[sys.argv.index("--cut") + 1]) if "--cut" in sys.argv else d.ts.quantile(0.7)
    train = I[I.ts < cut]; test_rids = d.index[d.ts >= cut]
    print("time split at", cut, "| train requests", int((d.ts < cut).sum()), "test", len(test_rids))
    add = sys.argv[sys.argv.index("--add") + 1].split(",") if "--add" in sys.argv else None     # e.g. --base lfm_coef_r3.json --add cv
    base = json.loads((lfm.HERE / sys.argv[sys.argv.index("--base") + 1]).read_text()) if "--base" in sys.argv else None
    if add:
        for f in add:
            for seg, new in (("known", False), ("new", True)):
                a = I[(I.new_user == new) & (I.dead == 0)]; nz = a[a[f] > 0]; z = a[a[f] == 0]
                print(f"{f} {seg}: impressions with {f}>0 {len(nz)} ({len(nz) / len(a):.1%}), clicks {int(nz.clk.sum())}, buys {int(nz.buy.sum())}"
                      f" -> {1e4 * nz.buy.mean():.1f} buys per 10k vs {1e4 * z.buy.mean():.1f} without")
    cands = {"r1 features, refit": fit(train, R1_FEATS), "all features, refit": fit(train, lfm.FEATS)}
    hbase = base                                  # the base used for the HOLD-OUT (the file itself is still what gets written)
    if add:
        bname = sys.argv[sys.argv.index("--base") + 1]
        if leaks(base, cut):                       # E-270: r3 was fitted through 16:00 and scored on a hold-out starting 15:30
            bfeats = [f for f in (base.get("meta", {}).get("feats") or lfm.FEATS) if f in lfm.FEATS and f not in add]
            hbase = fit(train, bfeats); bname += " REBUILT on the training split"
            print(f"cutoff: {sys.argv[sys.argv.index('--base') + 1]} was fitted through {fitted_until(base)} (hold-out starts {cut}); "
                  f"for the hold-out its {len(bfeats)} features are refitted on the training rows only")
        cands = {"base " + bname: hbase, "base + " + ",".join(add): fit_add(train, hbase, add)} | cands
    try:
        old = json.loads(lfm.ART.read_text())
        if all("cal" in old[k] for k in ("known", "new")):
            if leaks(old, cut): print(f"cutoff: committed {lfm.ART.name} fitted through {fitted_until(old)} overlaps the hold-out; left out of the table")
            else: cands = {"committed " + lfm.ART.name: old} | cands
    except Exception: pass
    print("provenance: hold-out starts", cut, "| every row of the table was fitted on requests before it | graph:",
          "history events only" if lfm.GRAPH.exists() else "none", "| quality lq: one snapshot (qrank.joblib, history), not as-of",
          "| catalogue as-of:", "yes" if getattr(aff, "catlog", None) is not None else "NO (lfm_catlog.parquet missing, run --pull)",
          "| carousel purchases as bought:", "yes" if getattr(aff, "fbuys", None) else "NO (fb_ts missing, run --pull)")
    holdout(I, test_rids, cands)
    report(d, I, LF, aff, carts, buys, fit_add(train, hbase, add) if add else fit(train, feats), test_rids)
    coef = fit_add(I, base, add) if add else fit(I, feats)
    coef["lq0"] = LF.lq0
    coef["meta"] = dict(fitted_on=f"{d.ts.min()} .. {d.ts.max()} UTC", requests=int(len(d)), buy_weight=BUY_W, C=C_REG, label="click, purchases x3", feats=feats)
    if add:
        coef["meta"].update(base=sys.argv[sys.argv.index("--base") + 1], added=add, feats=base.get("meta", {}).get("feats", feats) + add,
                            provenance=[dict(component="base", fitted_on=base.get("meta", {}).get("fitted_on"))]
                                       + [dict(component=f, fitted_on=coef["meta"]["fitted_on"]) for f in add])
    if "--no-write" not in sys.argv:
        out.write_text(json.dumps(coef, indent=1)); print("\nwrote", out.name)
    for seg in ("known", "new"): print(seg, coef[seg])


if __name__ == "__main__":
    main()
