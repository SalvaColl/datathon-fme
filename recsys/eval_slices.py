"""Final-round generalisation check (T-032): how the lfm ranking holds on shoppers and products it has not seen.

    python lfm_build.py --pull --no-write        # refresh data/lfm_*.parquet (read-only on RawTree)
    python eval_slices.py                        # fit < 14:30 UTC, validation 14:30-16:30, confirmation >= 16:30
    python eval_slices.py --fit-end "2026-11-14 14:30" --confirm "2026-11-14 16:30"

Read-only and offline: no RawTree query, nothing written except data/eval_slices.csv, never touches the writer.

Design
  * Whole shoppers are held out: shoppers are split in 5 groups by hash and each group is scored by weights fitted
    without any request of that group (and only on requests before the fit end). Every number below is therefore
    out-of-shopper AND out-of-time.
  * Three kinds of shopper are kept apart:
      new        is_new_user in the request: no history exists (the truly unseen shopper)
      masked     returning shoppers replayed with their 60-day history removed (today's events and recent views kept),
                 scored with the "new" weights and with the "known" weights
      returning  returning shoppers with their history, split by how much history they have
  * Products launched during the event are reported apart, by launch batch (hour of their new_product row). Their
    quality prior is the subcategory median learned before the event; nothing about them is fitted.
  * Slices: page, recent views in the request, views earlier in the day, history size, product age.
  * The confirmation period is not used to choose anything: it is read once, and it is also where the committed
    lfm_coef_r3.json (fitted through 16:00:29 UTC) can be scored as a frozen file.
  * Intervals: bootstrap over shoppers (a shopper's requests move together); for launched products, over launch
    batches when the slice is a product slice.

Metrics
  gain  nats per purchase: log-probability the weights give to the bought product among the 10 shown, with the slot
        effect included, minus the same with the slot alone. 0 = no better than knowing the position. This is the one
        to read: position drives purchases and the logged order came from one of our own models. The correction is
        partial, so it cannot settle a comparison between two of our own weight sets; the leaderboard does that.
  mrr   mean reciprocal rank of the bought product by serving score (random order = 0.293). Shown for reference only:
        it favours whichever weights resemble the model that ordered the logged slate.
Both measure ranking INSIDE slates our own policies chose, not the slate another model would build, and not the
hidden model's expected conversion.
"""
from __future__ import annotations
import json, sys, zlib
import numpy as np, pandas as pd
import lfm, lfm_build as B

RANDOM_MRR = float(np.mean(1.0 / np.arange(1, 11)))
R3_FEATS = [f for f in lfm.FEATS if f != "cv"]


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


FOLDS = 5
def fold(u):
    return zlib.crc32(("evalfold:" + u).encode()) % FOLDS


def masked_copy(d, aff, carts, buys):
    """The same requests with every shopper renamed, so each history lookup misses while today's events still match."""
    k = lambda u: "~" + u
    d2 = d.copy(); d2["user_id"] = d2.user_id.map(k)
    saved = (aff.today, aff.fbuys)
    today = {k(u): v for u, v in aff.today.items()}; fb = {k(u): v for u, v in (aff.fbuys or {}).items()}
    return d2, today, fb, {k(u): v for u, v in carts.items()}, {k(u): v for u, v in buys.items()}, saved


def score(I, coef, seg):
    return I[lfm.FEATS].values @ np.array([coef[seg]["w"].get(f, 0.0) for f in lfm.FEATS])


def ranks(I, z):
    g = pd.DataFrame(dict(rid=I.rid.values, z=z, buy=I.buy.values, slot=I.slot.values), index=I.index)
    g["rank"] = g.groupby("rid").z.rank(ascending=False, method="average")
    return g


def slot_gain(I, z, slot_coef):
    """Per impression: log P(this product is the one bought | the 10 shown) under score + slot, minus the same under
    slot alone. Position drives purchases (slot 1 sells ~9x slot 10) and the logged order was chosen by one of our
    models, so plain MRR favours whichever weights resemble the logging policy; this gain reduces that bias. It does
    not remove it: the slot coefficient is fitted together with the features, so part of the position effect stays
    credited to the weights that produced the logged order."""
    ls = np.log(I.slot.values); pos = slot_coef * ls
    g = pd.DataFrame(dict(rid=I.rid.values, a=z + pos, b=pos), index=I.index)
    def lsm(x):
        m = x.groupby(g.rid).transform("max"); return x - m - np.log(np.exp(x - m).groupby(g.rid).transform("sum"))
    return lsm(g.a) - lsm(g.b)


def mrr_ci(rr, groups, n_boot=400, seed=0):
    """Mean of rr with a 95% interval from a bootstrap over `groups` (shoppers or launch batches)."""
    if len(rr) == 0: return np.nan, np.nan, np.nan
    s = pd.DataFrame(dict(rr=np.asarray(rr, float), g=np.asarray(groups))).groupby("g").rr.agg(["sum", "count"])
    rng = np.random.default_rng(seed); k = len(s); tot, cnt = s["sum"].values, s["count"].values
    idx = rng.integers(0, k, size=(n_boot, k)); m = tot[idx].sum(1) / cnt[idx].sum(1)
    return float(tot.sum() / cnt.sum()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    fit_end, confirm = pd.Timestamp(arg("--fit-end", "2026-11-14 14:30")), pd.Timestamp(arg("--confirm", "2026-11-14 16:30"))
    d, LF, aff, carts, buys = B.load()
    d["fold"] = d.user_id.map(fold)
    cache = arg("--cache", None)                 # optional pickle of the two replays (they take minutes)
    if cache and __import__("os").path.exists(cache): I, IM = pd.read_pickle(cache)
    else:
        I = B.impressions(d, LF, aff, carts, buys)
        I = I.merge(d[["user_id", "fold"]], left_on="rid", right_index=True)
        # history-masked replay of the returning shoppers
        d2, today, fb, c2, b2, saved = masked_copy(d[~d.new_user], aff, carts, buys)
        aff.today, aff.fbuys = today, fb
        if aff.catlog is not None: aff.catlog._reset()
        IM = B.impressions(d2, LF, aff, c2, b2); aff.today, aff.fbuys = saved
        IM = IM.merge(d[["user_id", "fold"]], left_on="rid", right_index=True)
        if cache: pd.to_pickle((I, IM), cache)

    # cross-fitting over shoppers: each shopper is scored by weights fitted WITHOUT any of their requests
    models = {"r3 features": R3_FEATS, "r1 features": B.R1_FEATS, "r3 + cv": lfm.FEATS}
    for m in models: I[m] = np.nan
    IM["masked, new-shopper weights"] = np.nan; IM["masked, returning weights"] = np.nan; I["p_r3"] = np.nan
    for f in range(FOLDS):
        fit_rows = I[(I.ts < fit_end) & (I.fold != f)]; t = I.fold == f; tm = IM.fold == f
        for m, feats in models.items():
            coef = B.fit(fit_rows, feats)
            for seg, new in (("known", False), ("new", True)):
                k = t & (I.new_user == new); I.loc[k, m] = score(I[k], coef, seg); I.loc[k, m + "|slot"] = coef[seg]["slot"]
                if m == "r3 features":
                    I.loc[k, "p_r3"] = B.p_buy(coef, seg, I.loc[k, lfm.FEATS].values, I.loc[k, "slot"].values)
                    if not new:
                        IM.loc[tm, "masked, returning weights"] = score(IM[tm], coef, "known"); IM.loc[tm, "masked, new-shopper weights"] = score(IM[tm], coef, "new")
                        IM.loc[tm, "masked, returning weights|slot"] = coef["known"]["slot"]; IM.loc[tm, "masked, new-shopper weights|slot"] = coef["new"]["slot"]
        print(f"fold {f}: fitted on {fit_rows.rid.nunique()} requests ({int(fit_rows.buy.sum())} purchases) before {fit_end} from other shoppers; scores {int(t.sum())} impressions", flush=True)
    print(f"{d.user_id.nunique()} shoppers in {FOLDS} groups | validation {fit_end} .. {confirm} | confirmation from {confirm} (read once)")
    print(f"random order MRR = {RANDOM_MRR:.3f}")

    # per-request and per-product descriptors
    S = LF.snap; hist = pd.read_parquet(B.DATA / "user_item_all.parquet")
    hsize = (hist.v + hist.a + hist.p).groupby(hist.u).sum()
    names = getattr(aff, "_names", None) or list(aff.pid)
    def today_views(u, ts):
        ts = np.datetime64(ts); return sum(n for t, k, n in aff.today.get(u, ()) if t < ts)
    R = d[["user_id", "new_user", "page", "ts"]].copy()
    R["nrv"] = d.rv.map(len); R["tv"] = [today_views(u, t) for u, t in zip(d.user_id.values, d.ts.values)]
    R["hsz"] = d.user_id.map(hsize).fillna(0).values
    R["s_user"] = np.where(R.new_user, "new shopper", np.where(R.hsz < 20, "returning, history < 20 events", np.where(R.hsz < 200, "returning, 20-199 events", "returning, 200+ events")))
    R["s_page"] = R.page
    R["s_recent"] = pd.cut(R.nrv, [-1, 0, 2, 100], labels=["0 recent views", "1-2 recent views", "3+ recent views"]).astype(str)
    R["s_today"] = pd.cut(R.tv, [-1, 0, 9, 1e9], labels=["0 views earlier today", "1-9 views earlier today", "10+ views earlier today"]).astype(str)
    R["s_evidence"] = np.where((R.nrv == 0) & (R.tv == 0), "no session evidence at all", np.where(R.nrv + R.tv < 5, "sparse (under 5 views)", "5+ views"))
    launch = {}
    if aff.catlog is not None:
        log = pd.read_parquet(B.DATA / "lfm_catlog.parquet"); nw = log[log.change == "new_product"]
        launch = dict(zip(nw.product_id, pd.to_datetime(nw.ts)))
    pid = {rid: sh for rid, sh in zip(d.index, d.shown)}
    def with_products(J):
        J = J.copy(); J["pid"] = [pid[r][s - 1] for r, s in zip(J.rid.values, J.slot.values)]
        J["launch"] = J.pid.map(launch); J["batch"] = J.launch.dt.strftime("%H:00").fillna("catalogue before the event")
        J["age_min"] = (J.ts - J.launch).dt.total_seconds() / 60
        J["s_product"] = np.where(J.launch.isna(), "existing product", np.where(J.age_min < 60, "launched under 1 h ago", "launched 1 h+ ago"))
        rows = np.array([S.row.get(p, -1) for p in J.pid.values])
        J["s_graph"] = np.where(J.launch.notna(), "launched (no graph edges)", np.where(np.array([S.g is not None and k in S.g for k in rows]), "has graph edges", "no graph edges"))
        return J
    I, IM = with_products(I), with_products(IM)

    out = []
    def block(title, J, zcol, period, slice_col=None, product=False):
        lo, hi = (fit_end, confirm) if period == "validation" else (confirm, pd.Timestamp("2100-01-01"))
        J = J[(J.dead == 0) & (J.ts >= lo) & (J.ts < hi)]
        if len(J) == 0: return
        g = ranks(J, J[zcol].values); J = J.assign(rr=1.0 / g["rank"], gain=slot_gain(J, J[zcol].values, J[zcol + "|slot"].values))
        if slice_col and not product: J = J.merge(R[[slice_col]], left_on="rid", right_index=True)
        for name, a in ([("all", J)] if slice_col is None else J.groupby(slice_col)):
            b = a[a.buy == 1]; by_batch = product and slice_col in ("s_product",) and name != "existing product"
            m, l, h = mrr_ci(b.rr.values, b.batch.values if by_batch else b.user_id.values)
            gm, gl, gh = mrr_ci(b.gain.values, b.batch.values if by_batch else b.user_id.values)
            out.append(dict(block=title, model=zcol, period=period, slice=name, requests=a.rid.nunique(), shoppers=a.user_id.nunique(), impressions=len(a),
                            purchases=len(b), products=b.pid.nunique() if product else np.nan, batches=b.batch.nunique() if product else np.nan,
                            buys_per_10k=round(1e4 * len(b) / len(a), 1), mrr=m, lo=l, hi=h, gain=gm, gain_lo=gl, gain_hi=gh, ci_over="launch batches" if by_batch else "shoppers"))

    for period in ("validation", "confirmation"):
        for m in models: block("A. unseen shoppers, all", I, m, period)
        block("B. by shopper history", I, "r3 features", period, "s_user")
        block("C. returning shoppers with history MASKED", IM, "masked, new-shopper weights", period)
        block("C. returning shoppers with history MASKED", IM, "masked, returning weights", period)
        block("C. same shoppers WITH history (reference)", I[~I.new_user], "r3 features", period)
        for col, t in (("s_page", "D. by page"), ("s_recent", "E. by recent views in the request"), ("s_today", "F. by views earlier today"), ("s_evidence", "G. by total session evidence")):
            block(t, I, "r3 features", period, col)
        block("H. by product launch (purchases of ...)", I, "r3 features", period, "s_product", product=True)
        block("I. by launch batch (purchases of launched products)", I, "r3 features", period, "batch", product=True)
        block("J. by graph coverage of the product", I, "r3 + cv", period, "s_graph", product=True)
    # frozen committed file, only where it had not seen the data
    try:
        frozen = json.loads((lfm.HERE / "lfm_coef_r3.json").read_text())
        if not B.leaks(frozen, confirm):
            I["lfm_coef_r3.json frozen"] = np.where(I.new_user, score(I, frozen, "new"), score(I, frozen, "known"))
            I["lfm_coef_r3.json frozen|slot"] = np.where(I.new_user, frozen["new"]["slot"], frozen["known"]["slot"])
            block("K. committed lfm_coef_r3.json (fitted through %s), frozen" % B.fitted_until(frozen), I, "lfm_coef_r3.json frozen", "confirmation")
        else: print("lfm_coef_r3.json overlaps the confirmation period: not scored")
    except Exception as e: print("frozen file not scored:", type(e).__name__, e)

    T = pd.DataFrame(out)
    for c in ("mrr", "lo", "hi", "gain", "gain_lo", "gain_hi"): T[c] = T[c].round(3)
    T.to_csv(B.DATA / "eval_slices.csv", index=False)
    pd.set_option("display.width", 250)
    for (blk, period), g in T.groupby(["block", "period"], sort=False):
        print(f"\n{blk} | {period}"); print(g[["model", "slice", "requests", "shoppers", "impressions", "purchases", "products", "batches", "buys_per_10k", "gain", "gain_lo", "gain_hi", "mrr"]].dropna(axis=1, how="all").to_string(index=False))
    # launched products: exposure and calibration of the prior, by batch
    L = I[(I.dead == 0) & I.launch.notna() & (I.ts >= fit_end)]
    if len(L):
        Lb = L.groupby("batch").agg(products=("pid", "nunique"), impressions=("buy", "size"), purchases=("buy", "sum"), predicted=("p_r3", "sum"))
        print("\nlaunched products after the fit period: purchases vs the model's prediction (prior = subcategory median, nothing fitted on them)")
        print(Lb.round(1).to_string()); print("total", int(Lb.purchases.sum()), "purchases vs", round(float(Lb.predicted.sum()), 1), "predicted;",
              "existing products same period:", int(I[(I.dead == 0) & I.launch.isna() & (I.ts >= fit_end)].buy.sum()), "purchases vs",
              round(float(I[(I.dead == 0) & I.launch.isna() & (I.ts >= fit_end)].p_r3.sum()), 1), "predicted")
    return T


if __name__ == "__main__":
    main()
